from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")


def _evidence(root: Path) -> None:
    _write(
        root / "request" / "genesis-request-verification.json",
        {
            "schema": 1,
            "status": "PASS",
            "release_mode": "genesis_first_release",
            "protocol_rule": "GENESIS-FIRST-RELEASE-V1",
            "request_source": "reviewed_recovery_push",
            "repository": "owner/repo",
            "request_id": "GENESIS-REQUEST-0001",
            "request_sha256": "a" * 64,
            "qualification_run_id": 123,
            "qualification_head_sha": "b" * 40,
            "physical_l5_release_tag": "physical-l5",
            "physical_l5_manifest_sha256": "c" * 64,
            "physical_l5_bundle_sha256": "d" * 64,
            "enable_attestation": False,
            "failed_conditions": [],
        },
    )
    _write(
        root / "genesis" / "genesis-history-verification.json",
        {
            "schema": 2,
            "status": "PASS",
            "release_mode": "genesis_first_release",
            "protocol_rule": "GENESIS-FIRST-RELEASE-V1",
            "repository": "owner/repo",
            "query_source": "github_api_releases_actions_paginated",
            "query_complete": True,
            "current_run_id": 777,
            "release_count_scanned": 3,
            "workflow_run_count_scanned": 4,
            "artifact_count_scanned": 0,
            "authorized_installer_asset_count": 0,
            "authorization_record_asset_count": 0,
            "prior_successful_genesis_run_count": 0,
            "prior_authorized_genesis_artifact_count": 0,
            "prior_successful_genesis_run_ids": [],
            "prior_authorized_genesis_artifacts": [],
            "matching_assets": [],
        },
    )


def _stub_finalizer(path: Path) -> None:
    path.write_text(
        """
import argparse, json, sys
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--aggregate-dir',type=Path,required=True); p.add_argument('--output-dir',type=Path,required=True); a=p.parse_args()
compat=json.loads((a.aggregate_dir/'genesis/genesis-baseline-verification.json').read_text())
a.output_dir.mkdir(parents=True,exist_ok=True)
if compat.get('status')!='PASS':
    (a.output_dir/'final-verdict.json').write_text(json.dumps({'status':'RELEASE_BLOCKED'}))
    raise SystemExit(1)
(a.output_dir/'ImageLab_by_LarannA_RELEASE_AUTHORIZED_Setup_x64.exe').write_bytes(b'exact')
(a.output_dir/'final-verdict.json').write_text(json.dumps({'status':'RELEASE_AUTHORIZED'}))
(a.output_dir/'release-evidence.zip').write_bytes(b'zip')
(a.output_dir/'installer-sha256.txt').write_text('0'*64)
(a.output_dir/'ImageLab-RELEASE-AUTHORIZATION.json').write_text(json.dumps({'schema':1,'status':'RELEASE_AUTHORIZED','authorization_source':'finalize_gate.py'}))
""".strip()
        + "\n",
        "utf-8",
    )


def _run(evidence: Path, output: Path, finalizer: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "release_gate/genesis/orchestrate_request_gate.py",
            "--aggregate-dir",
            str(evidence),
            "--output-dir",
            str(output),
            "--finalizer",
            str(finalizer),
            "--repository",
            "owner/repo",
            "--genesis-request-id",
            "GENESIS-REQUEST-0001",
            "--qualification-run-id",
            "123",
            "--qualification-head-sha",
            "b" * 40,
            "--physical-manifest-sha256",
            "c" * 64,
            "--physical-bundle-sha256",
            "d" * 64,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
    )


def test_request_orchestrator_authorizes_only_after_request_and_history_pass(tmp_path: Path) -> None:
    evidence, output, finalizer = tmp_path / "evidence", tmp_path / "output", tmp_path / "stub.py"
    _evidence(evidence)
    _stub_finalizer(finalizer)
    result = _run(evidence, output, finalizer)
    assert result.returncode == 0, result.stderr
    compat = json.loads((evidence / "genesis/genesis-baseline-verification.json").read_text("utf-8"))
    assert compat["status"] == "PASS"
    record = json.loads((output / "ImageLab-RELEASE-AUTHORIZATION.json").read_text("utf-8"))
    assert record["genesis_request_id"] == "GENESIS-REQUEST-0001"
    assert record["authorization_orchestrator"] == "release_gate/genesis/orchestrate_request_gate.py"


def test_request_orchestrator_blocks_prior_successful_genesis_run(tmp_path: Path) -> None:
    evidence, output, finalizer = tmp_path / "evidence", tmp_path / "output", tmp_path / "stub.py"
    _evidence(evidence)
    history_path = evidence / "genesis/genesis-history-verification.json"
    history = json.loads(history_path.read_text("utf-8"))
    history["status"] = "FAIL"
    history["prior_successful_genesis_run_count"] = 1
    history["prior_successful_genesis_run_ids"] = [99]
    _write(history_path, history)
    _stub_finalizer(finalizer)
    result = _run(evidence, output, finalizer)
    assert result.returncode != 0
    assert not list(output.glob("*RELEASE_AUTHORIZED*.exe"))
    verdict = json.loads((output / "final-verdict.json").read_text("utf-8"))
    assert verdict["status"] == "RELEASE_BLOCKED"
    assert any("genesis_history_invalid" in value for value in verdict["failed_conditions"])


def test_request_orchestrator_blocks_mismatched_request_and_cleans_outputs(tmp_path: Path) -> None:
    evidence, output, finalizer = tmp_path / "evidence", tmp_path / "output", tmp_path / "stub.py"
    _evidence(evidence)
    request_path = evidence / "request/genesis-request-verification.json"
    request = json.loads(request_path.read_text("utf-8"))
    request["qualification_run_id"] = 999
    _write(request_path, request)
    output.mkdir(parents=True)
    (output / "ImageLab_by_LarannA_RELEASE_AUTHORIZED_Setup_x64.exe").write_bytes(b"stale")
    _stub_finalizer(finalizer)
    result = _run(evidence, output, finalizer)
    assert result.returncode != 0
    assert not list(output.glob("*RELEASE_AUTHORIZED*.exe"))


def test_active_request_workflow_is_reviewed_push_only() -> None:
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if not workspace:
        return
    workflow = (Path(workspace) / ".github/workflows/zero-trust-genesis-request.yml").read_text("utf-8")
    assert "bootstrap/zero-trust-gate" in workflow
    assert "recovery/genesis-request/GENESIS-REQUEST.json" in workflow
    assert "changed-files.txt" in workflow
    assert "orchestrate_request_gate.py" in workflow
    assert "prior-workflow-runs.json" in workflow
    assert "prior-authorized-artifacts.json" in workflow
