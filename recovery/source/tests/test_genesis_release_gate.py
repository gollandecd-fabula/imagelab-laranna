from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from release_gate.genesis.verify_no_prior_release import inspect_history, inspect_releases

ROOT = Path(__file__).resolve().parents[1]
SELFTEST_CASES = {"resize_ppi", "background", "halftone", "vector", "history_lineage", "export"}
QUALIFIED_GATES = {
    "G0_source",
    "G1_unit_matrix",
    "G2_candidate",
    "G2_reproducibility",
    "G3_clean_install",
    "G3_preinstall_selftest",
    "G3_postinstall_selftest",
    "G4_browser_ui",
    "G5_output_validation",
    "G8_independent",
    "G8_preinstall_selftest",
    "G8_postinstall_selftest",
    "G8_independent_ui",
    "G8_independent_outputs",
}
GENESIS_RUN_ID = 777


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")


def _selftest(version: str, build_id: str, install_id: str) -> dict[str, object]:
    return {
        "schema": 1,
        "status": "PASS",
        "app": "ImageLab by LarannA",
        "version": version,
        "build_id": build_id,
        "install_id": install_id,
        "tests": {name: {"status": "PASS"} for name in sorted(SELFTEST_CASES)},
    }


def _write_g7_bundle(root: Path, installer_sha: str, source_sha: str, *, mutate=None) -> str:
    directory = root / "g7"
    directory.mkdir(parents=True, exist_ok=True)
    bundle = directory / "ImageLab-GENESIS-G7-EVIDENCE.zip"
    inventory = {
        "schema": 1,
        "project_count": 3,
        "asset_count": 3,
        "projects_sha256": "d" * 64,
        "projects": [
            {"project_id": "TS-001"},
            {"project_id": "ZTR-SVG-PROJECT"},
            {"project_id": "ZTR-RASTER-PROJECT"},
        ],
    }
    baseline_sha = "b" * 64
    update = {
        "schema": 3,
        "status": "PASS",
        "installer_sha256": installer_sha,
        "baseline_installer_sha256": baseline_sha,
        "baseline_version": "9.9.8-diagnostic",
        "baseline_build_id": "DIAGNOSTIC-BASELINE",
        "first_install_id": "baseline-install",
        "second_install_id": "candidate-install",
        "old_process_stopped": True,
        "project_data_preserved": True,
        "sentinel_preserved": True,
        "project_count": 3,
        "asset_count": 3,
        "project_inventory_before": inventory,
        "project_inventory_after_update": inventory,
    }
    rollback = {
        "schema": 3,
        "status": "PASS",
        "installer_sha256": installer_sha,
        "restored_install_id": "candidate-install",
        "expected_install_id": "candidate-install",
        "fault_exit_code": 1,
        "critical_hashes_restored": True,
        "project_data_preserved": True,
        "sentinel_preserved": True,
        "project_count": 3,
        "asset_count": 3,
        "project_inventory_before": inventory,
        "project_inventory_after_rollback": inventory,
    }
    if mutate is not None:
        mutate(update, rollback)
    update_bytes = json.dumps(update, ensure_ascii=False, sort_keys=True).encode("utf-8")
    rollback_bytes = json.dumps(rollback, ensure_ascii=False, sort_keys=True).encode("utf-8")
    wrapper = {
        "schema": 1,
        "status": "PASS",
        "evidence_mode": "non_authorizing_diagnostic_baseline",
        "source_sha256": source_sha,
        "installer_sha256": installer_sha,
        "baseline_installer_sha256": baseline_sha,
        "update_test_sha256": hashlib.sha256(update_bytes).hexdigest(),
        "rollback_test_sha256": hashlib.sha256(rollback_bytes).hexdigest(),
    }
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("genesis-g7/g7-evidence.json", json.dumps(wrapper, sort_keys=True))
        archive.writestr("genesis-g7/update-test.json", update_bytes)
        archive.writestr("genesis-g7/rollback-test.json", rollback_bytes)
    return _sha(bundle)


def _physical_record(
    *,
    source_sha: str,
    installer_name: str,
    installer_sha: str,
    version: str,
    build_id: str,
) -> dict[str, object]:
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema": 1,
        "status": "PASS",
        "execution_environment": "physical_user_windows",
        "hosted_runner": False,
        "executed_at": timestamp,
        "candidate": {
            "source_sha256": source_sha,
            "installer_name": installer_name,
            "installer_sha256": installer_sha,
            "version": version,
            "build_id": build_id,
            "install_id": "physical-install",
        },
        "scenario": {
            "browser_driven": True,
            "steps": {
                "upload": {"status": "PASS"},
                "operation": {"status": "PASS"},
                "history": {"status": "PASS"},
                "export": {"status": "PASS"},
            },
        },
        "outputs": [
            {"name": "physical-output.png", "sha256": "f" * 64, "validator_status": "PASS"}
        ],
        "direct_witness": {
            "name": "Dmitry",
            "confirmed": True,
            "statement": "Dmitry directly witnessed the complete installed browser user path.",
            "witnessed_at": timestamp,
        },
    }


def _build_evidence(root: Path) -> tuple[str, str, str]:
    version = "9.9.9-genesis-test"
    build_id = "GENESIS-TEST"
    source_sha = "c" * 64
    installer_name = "ImageLab_by_LarannA_ZERO_TRUST_Setup_x64.exe"
    installer = root / "build" / installer_name
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_bytes(b"exact synthetic genesis installer")
    installer_sha = _sha(installer)
    identity = {"app": "ImageLab by LarannA", "version": version, "build_id": build_id}

    _write(root / "source/source-gate.json", {"status": "PASS"})
    _write(root / "unit/unit-matrix-verdict.json", {"status": "PASS"})
    _write(
        root / "build/candidate-manifest.json",
        {
            "status": "PASS",
            "identity": identity,
            "installer": {"name": installer_name, "sha256": installer_sha},
            "source": {"sha256": source_sha},
        },
    )
    _write(
        root / "build/reproducibility.json",
        {"status": "PASS", "installer_sha256": installer_sha, "second_build_sha256": installer_sha},
    )

    for folder, install_id, base_name in (
        ("clean", "clean-install", "clean-install.json"),
        ("independent", "independent-install", "independent-verification.json"),
    ):
        install = {
            "status": "PASS",
            "installer_sha256": installer_sha,
            "version": version,
            "build_id": build_id,
            "install_id": install_id,
        }
        _write(root / folder / base_name, install)
        _write(root / folder / "preinstall-selftest.json", _selftest(version, build_id, install_id))
        _write(root / folder / "postinstall-selftest.json", _selftest(version, build_id, install_id))
        _write(root / folder / "ui-gate.json", {"status": "PASS", "installer_sha256": installer_sha})
        _write(root / folder / "output-validation.json", {"status": "PASS", "installer_sha256": installer_sha})

    _write(
        root / "genesis/genesis-baseline-verification.json",
        {
            "schema": 2,
            "status": "PASS",
            "release_mode": "genesis_first_release",
            "protocol_rule": "GENESIS-FIRST-RELEASE-V1",
            "repository": "owner/repo",
            "query_source": "github_api_releases_actions_paginated",
            "query_complete": True,
            "current_run_id": GENESIS_RUN_ID,
            "release_count_scanned": 3,
            "workflow_run_count_scanned": 2,
            "artifact_count_scanned": 4,
            "authorized_installer_asset_count": 0,
            "authorization_record_asset_count": 0,
            "prior_successful_genesis_run_count": 0,
            "prior_authorized_genesis_artifact_count": 0,
            "prior_successful_genesis_run_ids": [],
            "prior_authorized_genesis_artifacts": [],
            "matching_assets": [],
        },
    )
    artifact_names = [
        "ztr-source-evidence",
        "ztr-unit-verdict",
        "UNVERIFIED_INTERNAL_EXACT_CANDIDATE",
        "ztr-clean-install-evidence",
        "ztr-independent-evidence",
        "ImageLab-RELEASE-VERDICT",
    ]
    _write(
        root / "qualification/qualification-run.json",
        {
            "schema": 1,
            "status": "PASS",
            "repository": "owner/repo",
            "run_id": 12345,
            "head_sha": "a" * 40,
            "workflow_name": "ImageLab Zero-Trust Release Gate",
            "event": "workflow_dispatch",
            "conclusion": "failure",
            "artifact_names": artifact_names,
        },
    )
    gates = {name: "PASS" for name in QUALIFIED_GATES}
    gates.update({"G6_baseline_pinned": "MISSING", "G6_update": "MISSING", "G7_rollback": "MISSING"})
    _write(
        root / "qualification-verdict/final-verdict.json",
        {"schema": 3, "status": "RELEASE_BLOCKED", "installer_sha256": installer_sha, "gates": gates},
    )

    g7_sha = _write_g7_bundle(root, installer_sha, source_sha)
    physical_path = root / "physical/physical-l5.json"
    _write(
        physical_path,
        _physical_record(
            source_sha=source_sha,
            installer_name=installer_name,
            installer_sha=installer_sha,
            version=version,
            build_id=build_id,
        ),
    )
    return installer_sha, _sha(physical_path), g7_sha


def _run(
    root: Path,
    output: Path,
    physical_sha: str,
    g7_sha: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = subprocess.run(
        [
            sys.executable,
            "release_gate/genesis/finalize_gate.py",
            "--aggregate-dir",
            str(root),
            "--output-dir",
            str(output),
            "--repository",
            "owner/repo",
            "--genesis-run-id",
            str(GENESIS_RUN_ID),
            "--qualification-run-id",
            "12345",
            "--qualification-head-sha",
            "a" * 40,
            "--g7-bundle-sha256",
            g7_sha,
            "--physical-l5-sha256",
            physical_sha,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    verdict = json.loads((output / "final-verdict.json").read_text("utf-8"))
    return result, verdict


def test_release_absence_verifier_rejects_normal_and_genesis_authorized_assets() -> None:
    clean = inspect_releases([[{"tag_name": "v0", "assets": []}]], "owner/repo")
    assert clean["status"] == "PASS"
    for name in (
        "ImageLab-RELEASE-AUTHORIZATION.json",
        "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json",
        "ImageLab_by_LarannA_GENESIS_RELEASE_AUTHORIZED_Setup_x64.exe",
    ):
        blocked = inspect_releases([{"tag_name": "v1", "assets": [{"name": name}]}], "owner/repo")
        assert blocked["status"] == "FAIL"


def test_release_absence_verifier_rejects_prior_successful_run_or_artifact() -> None:
    result = inspect_history(
        [],
        [{"workflow_runs": [{"id": 10, "conclusion": "success"}]}],
        [{"artifacts": [{"id": 20, "name": "ImageLab-GENESIS-RELEASE-AUTHORIZED", "workflow_run": {"id": 10}}]}],
        "owner/repo",
        GENESIS_RUN_ID,
    )
    assert result["status"] == "FAIL"
    assert result["prior_successful_genesis_run_count"] == 1
    assert result["prior_authorized_genesis_artifact_count"] == 1


def test_genesis_finalizer_authorizes_only_complete_first_release_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    installer_sha, physical_sha, g7_sha = _build_evidence(evidence)
    output = tmp_path / "output"
    result, verdict = _run(evidence, output, physical_sha, g7_sha)
    assert result.returncode == 0, result.stderr
    assert verdict["status"] == "GENESIS_RELEASE_AUTHORIZED"
    assert verdict["gates"]["G6_update_from_prior_authorized_release"] == "NOT_APPLICABLE_FIRST_RELEASE"
    assert verdict["gates"]["G7_rollback_to_prior_authorized_release"] == "PASS"
    record = json.loads((output / "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json").read_text("utf-8"))
    assert record["status"] == "GENESIS_RELEASE_AUTHORIZED"
    assert record["installer_sha256"] == installer_sha
    assert record["install_id"] == "physical-install"
    assert list(output.glob("*GENESIS_RELEASE_AUTHORIZED*_Setup_x64.exe"))
    assert not (output / "ImageLab-RELEASE-AUTHORIZATION.json").exists()
    assert not list(output.glob("ImageLab_by_LarannA_RELEASE_AUTHORIZED*_Setup_x64.exe"))


def test_genesis_finalizer_blocks_when_prior_authorized_asset_exists(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, physical_sha, g7_sha = _build_evidence(evidence)
    path = evidence / "genesis/genesis-baseline-verification.json"
    value = json.loads(path.read_text("utf-8"))
    value["status"] = "FAIL"
    value["authorization_record_asset_count"] = 1
    value["matching_assets"] = [{"tag": "v1", "name": "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json"}]
    _write(path, value)
    result, verdict = _run(evidence, tmp_path / "output", physical_sha, g7_sha)
    assert result.returncode != 0
    assert "genesis_absence_invalid:authorization_record_asset_count" in verdict["failed_conditions"]


def test_genesis_finalizer_requires_exact_pinned_g7_bundle(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, physical_sha, _ = _build_evidence(evidence)
    result, verdict = _run(evidence, tmp_path / "output", physical_sha, "f" * 64)
    assert result.returncode != 0
    assert "g7_bundle_pinned_sha_mismatch" in verdict["failed_conditions"]


def test_genesis_finalizer_rejects_failed_or_na_g7(tmp_path: Path) -> None:
    for status in ("FAIL", "NOT_APPLICABLE_FIRST_RELEASE"):
        evidence = tmp_path / status
        installer_sha, physical_sha, _ = _build_evidence(evidence)
        source_sha = json.loads((evidence / "build/candidate-manifest.json").read_text("utf-8"))["source"]["sha256"]
        g7_sha = _write_g7_bundle(
            evidence,
            installer_sha,
            source_sha,
            mutate=lambda update, rollback, status=status: rollback.update(status=status),
        )
        result, verdict = _run(evidence, tmp_path / f"output-{status}", physical_sha, g7_sha)
        assert result.returncode != 0
        assert "g7_rollback_status" in verdict["failed_conditions"]


def test_genesis_finalizer_rejects_current_candidate_as_g7_baseline(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    installer_sha, physical_sha, _ = _build_evidence(evidence)
    source_sha = json.loads((evidence / "build/candidate-manifest.json").read_text("utf-8"))["source"]["sha256"]

    def use_self_baseline(update, _rollback):
        update["baseline_installer_sha256"] = installer_sha

    g7_sha = _write_g7_bundle(evidence, installer_sha, source_sha, mutate=use_self_baseline)
    bundle = evidence / "g7/ImageLab-GENESIS-G7-EVIDENCE.zip"
    with zipfile.ZipFile(bundle) as archive:
        update = json.loads(archive.read("genesis-g7/update-test.json"))
        rollback = json.loads(archive.read("genesis-g7/rollback-test.json"))
    update_bytes = json.dumps(update, ensure_ascii=False, sort_keys=True).encode("utf-8")
    rollback_bytes = json.dumps(rollback, ensure_ascii=False, sort_keys=True).encode("utf-8")
    wrapper = {
        "schema": 1,
        "status": "PASS",
        "evidence_mode": "non_authorizing_diagnostic_baseline",
        "source_sha256": source_sha,
        "installer_sha256": installer_sha,
        "baseline_installer_sha256": installer_sha,
        "update_test_sha256": hashlib.sha256(update_bytes).hexdigest(),
        "rollback_test_sha256": hashlib.sha256(rollback_bytes).hexdigest(),
    }
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("g7-evidence.json", json.dumps(wrapper))
        archive.writestr("update-test.json", update_bytes)
        archive.writestr("rollback-test.json", rollback_bytes)
    result, verdict = _run(evidence, tmp_path / "output", physical_sha, _sha(bundle))
    assert result.returncode != 0
    assert "g7_self_baseline_forbidden" in verdict["failed_conditions"]


def test_genesis_finalizer_reuses_normal_physical_l5_validator(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, _, g7_sha = _build_evidence(evidence)
    physical_path = evidence / "physical/physical-l5.json"
    value = json.loads(physical_path.read_text("utf-8"))
    value["scenario"]["steps"]["export"]["status"] = "FAIL"
    _write(physical_path, value)
    result, verdict = _run(evidence, tmp_path / "output", _sha(physical_path), g7_sha)
    assert result.returncode != 0
    assert "physical_l5_step_failed:export" in verdict["failed_conditions"]


def test_genesis_finalizer_blocks_unpinned_physical_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, _, g7_sha = _build_evidence(evidence)
    result, verdict = _run(evidence, tmp_path / "output", "f" * 64, g7_sha)
    assert result.returncode != 0
    assert "physical_l5_sha_pin_mismatch" in verdict["failed_conditions"]


def test_genesis_finalizer_removes_stale_normal_and_genesis_outputs_on_failure(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, _, g7_sha = _build_evidence(evidence)
    output = tmp_path / "output"
    output.mkdir()
    stale_files = [
        output / "ImageLab_by_LarannA_RELEASE_AUTHORIZED_Setup_x64.exe",
        output / "ImageLab_by_LarannA_GENESIS_RELEASE_AUTHORIZED_Setup_x64.exe",
        output / "ImageLab-RELEASE-AUTHORIZATION.json",
        output / "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json",
    ]
    for path in stale_files:
        path.write_bytes(b"stale")
    result, _ = _run(evidence, output, "f" * 64, g7_sha)
    assert result.returncode != 0
    assert all(not path.exists() for path in stale_files)


def test_genesis_workflow_requires_history_g7_and_shared_physical_evidence() -> None:
    workflow = (ROOT / ".github/workflows/zero-trust-genesis-release.yml").read_text("utf-8")
    assert "qualification_run_id:" in workflow
    assert "g7_evidence_release_tag:" in workflow
    assert "g7_evidence_bundle_sha256:" in workflow
    assert "physical_l5_evidence_url:" in workflow
    assert "physical_l5_evidence_sha256:" in workflow
    assert "fetch_pinned_json.py" in workflow
    assert "workflow-runs.json" in workflow
    assert "artifacts.json" in workflow
    assert "--current-run-id" in workflow
    assert "ImageLab-GENESIS-G7-EVIDENCE.zip" in workflow
    assert "--g7-bundle-sha256" in workflow
    assert "--physical-l5-sha256" in workflow
    assert "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json" in workflow
    assert "ImageLab-RELEASE-AUTHORIZATION.json" not in workflow


def test_repository_root_has_executable_genesis_workflow() -> None:
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if not workspace:
        return
    workflow = (Path(workspace) / ".github/workflows/zero-trust-genesis-release.yml").read_text("utf-8")
    assert "working-directory: recovery/source" in workflow
    assert "recovery/source/authorized-release" in workflow
    assert "release_gate/genesis/finalize_gate.py" in workflow
