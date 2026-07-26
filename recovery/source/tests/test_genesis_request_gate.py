from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from release_gate.genesis.resolve_request import validate_request

ROOT = Path(__file__).resolve().parents[1]
GENESIS_RUN_ID = 777
G7_SHA = "e" * 64
PHYSICAL_SHA = "d" * 64
PHYSICAL_URL = "https://evidence.example/physical-l5.json"
AUTHORIZATION_WORKFLOWS = [
    "ImageLab Genesis First Release Gate",
    "ImageLab Genesis Request Gate",
    "ImageLab Zero-Trust Release Gate",
]


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")


def _evidence(root: Path) -> None:
    _write(
        root / "request/genesis-request-verification.json",
        {
            "schema": 2,
            "status": "PASS",
            "release_mode": "genesis_first_release",
            "protocol_rule": "GENESIS-FIRST-RELEASE-V1",
            "request_source": "reviewed_recovery_push",
            "repository": "owner/repo",
            "request_id": "GENESIS-REQUEST-0001",
            "request_sha256": "a" * 64,
            "qualification_run_id": 123,
            "qualification_head_sha": "b" * 40,
            "g7_evidence_release_tag": "g7-diagnostic",
            "g7_evidence_bundle_sha256": G7_SHA,
            "physical_l5_evidence_url": PHYSICAL_URL,
            "physical_l5_evidence_sha256": PHYSICAL_SHA,
            "enable_attestation": False,
            "failed_conditions": [],
        },
    )
    _write(
        root / "genesis/genesis-history-verification.json",
        {
            "schema": 3,
            "status": "PASS",
            "release_mode": "genesis_first_release",
            "protocol_rule": "GENESIS-FIRST-RELEASE-V1",
            "repository": "owner/repo",
            "query_source": "github_api_releases_all_authorization_runs_artifacts_paginated",
            "query_complete": True,
            "current_run_id": GENESIS_RUN_ID,
            "authorization_workflow_names": AUTHORIZATION_WORKFLOWS,
            "release_count_scanned": 3,
            "workflow_run_count_scanned": 4,
            "artifact_count_scanned": 0,
            "authorized_installer_asset_count": 0,
            "authorization_record_asset_count": 0,
            "prior_successful_authorization_run_count": 0,
            "prior_authorized_artifact_count": 0,
            "prior_successful_authorization_runs": [],
            "prior_authorized_artifacts": [],
            "matching_assets": [],
        },
    )


def _stub_finalizer(path: Path) -> None:
    path.write_text(
        """
import argparse, json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--aggregate-dir',type=Path,required=True)
p.add_argument('--output-dir',type=Path,required=True)
p.add_argument('--repository',required=True)
p.add_argument('--genesis-run-id',type=int,required=True)
p.add_argument('--qualification-run-id',type=int,required=True)
p.add_argument('--qualification-head-sha',required=True)
p.add_argument('--g7-bundle-sha256',required=True)
p.add_argument('--physical-l5-sha256',required=True)
a=p.parse_args()
history=json.loads((a.aggregate_dir/'genesis/genesis-baseline-verification.json').read_text())
a.output_dir.mkdir(parents=True,exist_ok=True)
if history.get('status')!='PASS' or history.get('current_run_id')!=a.genesis_run_id:
    (a.output_dir/'final-verdict.json').write_text(json.dumps({'status':'RELEASE_BLOCKED'}))
    raise SystemExit(1)
(a.output_dir/'ImageLab_by_LarannA_GENESIS_RELEASE_AUTHORIZED_Setup_x64.exe').write_bytes(b'exact')
(a.output_dir/'final-verdict.json').write_text(json.dumps({'status':'GENESIS_RELEASE_AUTHORIZED'}))
(a.output_dir/'release-evidence.zip').write_bytes(b'zip')
(a.output_dir/'installer-sha256.txt').write_text('0'*64)
(a.output_dir/'ImageLab-GENESIS-RELEASE-AUTHORIZATION.json').write_text(json.dumps({'schema':2,'status':'GENESIS_RELEASE_AUTHORIZED','authorization_source':'finalize_gate.py'}))
""".strip()
        + "\n",
        "utf-8",
    )


def _run(
    evidence: Path,
    output: Path,
    finalizer: Path,
    *,
    g7_sha: str = G7_SHA,
    physical_sha: str = PHYSICAL_SHA,
) -> subprocess.CompletedProcess[str]:
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
            "--genesis-run-id",
            str(GENESIS_RUN_ID),
            "--genesis-request-id",
            "GENESIS-REQUEST-0001",
            "--qualification-run-id",
            "123",
            "--qualification-head-sha",
            "b" * 40,
            "--g7-bundle-sha256",
            g7_sha,
            "--physical-l5-sha256",
            physical_sha,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
    )


def _request_value() -> dict[str, object]:
    return {
        "schema": 2,
        "status": "GENESIS_AUTHORIZATION_REQUESTED",
        "release_mode": "genesis_first_release",
        "protocol_rule": "GENESIS-FIRST-RELEASE-V1",
        "repository": "owner/repo",
        "request_id": "GENESIS-REQUEST-0001",
        "qualification_run_id": 123,
        "qualification_head_sha": "b" * 40,
        "g7_evidence_release_tag": "g7-diagnostic",
        "g7_evidence_bundle_sha256": G7_SHA,
        "physical_l5_evidence_url": PHYSICAL_URL,
        "physical_l5_evidence_sha256": PHYSICAL_SHA,
        "enable_attestation": False,
    }


def test_request_schema_requires_exact_g7_and_physical_inputs() -> None:
    value = _request_value()
    evidence, outputs = validate_request(
        value,
        "owner/repo",
        "reviewed_recovery_push",
        hashlib.sha256(b"request").hexdigest(),
    )
    assert evidence["status"] == "PASS"
    assert outputs["g7_evidence_bundle_sha256"] == G7_SHA
    assert outputs["physical_l5_evidence_url"] == PHYSICAL_URL
    assert outputs["physical_l5_evidence_sha256"] == PHYSICAL_SHA

    for field in ("g7_evidence_bundle_sha256", "physical_l5_evidence_sha256"):
        broken = dict(value)
        broken.pop(field)
        blocked, _ = validate_request(broken, "owner/repo", "reviewed_recovery_push", "a" * 64)
        assert blocked["status"] == "FAIL"
        assert any(field in item for item in blocked["failed_conditions"])

    broken_url = dict(value)
    broken_url["physical_l5_evidence_url"] = "http://insecure.example/evidence.json"
    blocked, _ = validate_request(broken_url, "owner/repo", "reviewed_recovery_push", "a" * 64)
    assert "invalid:physical_l5_evidence_url" in blocked["failed_conditions"]


def test_request_orchestrator_authorizes_only_after_request_history_g7_and_physical_match(tmp_path: Path) -> None:
    evidence, output, finalizer = tmp_path / "evidence", tmp_path / "output", tmp_path / "stub.py"
    _evidence(evidence)
    _stub_finalizer(finalizer)
    result = _run(evidence, output, finalizer)
    assert result.returncode == 0, result.stderr
    history = json.loads((evidence / "genesis/genesis-baseline-verification.json").read_text("utf-8"))
    assert history["schema"] == 3
    assert history["current_run_id"] == GENESIS_RUN_ID
    record = json.loads((output / "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json").read_text("utf-8"))
    assert record["status"] == "GENESIS_RELEASE_AUTHORIZED"
    assert record["genesis_request_id"] == "GENESIS-REQUEST-0001"
    assert record["authorization_orchestrator"] == "release_gate/genesis/orchestrate_request_gate.py"
    assert not (output / "ImageLab-RELEASE-AUTHORIZATION.json").exists()


def test_request_orchestrator_blocks_prior_successful_genesis_run(tmp_path: Path) -> None:
    evidence, output, finalizer = tmp_path / "evidence", tmp_path / "output", tmp_path / "stub.py"
    _evidence(evidence)
    history_path = evidence / "genesis/genesis-history-verification.json"
    history = json.loads(history_path.read_text("utf-8"))
    history["status"] = "FAIL"
    history["prior_successful_authorization_run_count"] = 1
    history["prior_successful_authorization_runs"] = [
        {"id": 99, "name": "ImageLab Genesis Request Gate"}
    ]
    _write(history_path, history)
    _stub_finalizer(finalizer)
    result = _run(evidence, output, finalizer)
    assert result.returncode != 0
    assert not list(output.glob("*RELEASE_AUTHORIZED*.exe"))
    verdict = json.loads((output / "final-verdict.json").read_text("utf-8"))
    assert any("genesis_history_invalid" in value for value in verdict["failed_conditions"])


def test_request_orchestrator_blocks_mismatched_g7_or_physical_sha(tmp_path: Path) -> None:
    evidence, finalizer = tmp_path / "evidence", tmp_path / "stub.py"
    _evidence(evidence)
    _stub_finalizer(finalizer)
    for label, kwargs, expected in (
        ("g7", {"g7_sha": "f" * 64}, "genesis_request_invalid:g7_evidence_bundle_sha256"),
        ("physical", {"physical_sha": "f" * 64}, "genesis_request_invalid:physical_l5_evidence_sha256"),
    ):
        output = tmp_path / f"output-{label}"
        output.mkdir()
        (output / "ImageLab_by_LarannA_GENESIS_RELEASE_AUTHORIZED_Setup_x64.exe").write_bytes(b"stale")
        result = _run(evidence, output, finalizer, **kwargs)
        assert result.returncode != 0
        assert not list(output.glob("*RELEASE_AUTHORIZED*.exe"))
        verdict = json.loads((output / "final-verdict.json").read_text("utf-8"))
        assert expected in verdict["failed_conditions"]


def test_active_request_workflow_is_reviewed_push_only_and_genesis_only() -> None:
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if not workspace:
        return
    workflow = (Path(workspace) / ".github/workflows/zero-trust-genesis-request.yml").read_text("utf-8")
    assert "bootstrap/zero-trust-gate" in workflow
    assert "recovery/genesis-request/GENESIS-REQUEST.json" in workflow
    assert "changed-files.txt" in workflow
    assert "orchestrate_request_gate.py" in workflow
    assert "all-authorization-runs.json" in workflow
    assert "all-authorization-artifacts.json" in workflow
    assert "g7_evidence_release_tag" in workflow
    assert "g7_evidence_bundle_sha256" in workflow
    assert "ImageLab-GENESIS-G7-EVIDENCE.zip" in workflow
    assert "physical_l5_evidence_url" in workflow
    assert "physical_l5_evidence_sha256" in workflow
    assert "fetch_pinned_json.py" in workflow
    assert "--genesis-run-id" in workflow
    assert "--g7-bundle-sha256" in workflow
    assert "--physical-l5-sha256" in workflow
    assert "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json" in workflow
    assert "ImageLab-RELEASE-AUTHORIZATION.json" not in workflow
