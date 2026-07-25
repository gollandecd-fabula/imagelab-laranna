from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import settings

ROOT = Path(__file__).resolve().parents[1]
SELFTEST_CASES = {"resize_ppi", "background", "halftone", "vector", "history_lineage", "export"}
PHYSICAL_STEPS = ("upload", "operation", "history", "export")


def test_release_selftest_runs_all_critical_operations(tmp_path: Path) -> None:
    output = tmp_path / "selftest.json"
    env = dict(os.environ)
    env["IMAGELAB_DATA_DIR"] = str(tmp_path / "data")
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-m", "app.release_selftest", "--output", str(output)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    verdict = json.loads(output.read_text("utf-8"))
    assert verdict["status"] == "PASS"
    assert verdict["version"] == settings.app_version
    assert verdict["build_id"] == settings.build_id
    assert set(verdict["tests"]) == SELFTEST_CASES
    assert verdict["tests"]["resize_ppi"]["size_px"] == [400, 300]
    assert verdict["tests"]["resize_ppi"]["ppi"] == 200.0
    assert verdict["tests"]["vector"]["path_count"] >= 2


def test_installer_runs_selftest_before_and_after_promotion() -> None:
    source = (ROOT / "windows_installer" / "installer" / "main.go").read_text("utf-8")
    assert 'runReleaseSelfTest(stagingDir, installID, "preinstall"' in source
    assert 'runReleaseSelfTest(installDir, installID, "postinstall"' in source
    assert source.index('runReleaseSelfTest(stagingDir, installID, "preinstall"') < source.index(
        "promoteAtomic(stagingDir, installDir, backupDir)"
    )
    assert 'faultRequested("after_promotion")' in source
    assert "IMAGELAB_INSTALLER_CI" in source
    assert "IMAGELAB_EXTERNAL_BROWSER=1" in source
    assert 'filepath.Join("app", "release_selftest.py")' in source


def test_zero_trust_workflow_has_all_gates_and_exact_candidate_flow() -> None:
    workflow = (ROOT / ".github" / "workflows" / "zero-trust-release.yml").read_text("utf-8")
    for job in (
        "source-gate:",
        "unit-matrix:",
        "unit-verdict:",
        "build-exact-candidate:",
        "clean-install-ui:",
        "update-rollback:",
        "independent-verification:",
        "final-verdict:",
    ):
        assert job in workflow
    for value in (
        "workflow_dispatch:",
        "baseline_release_tag:",
        "baseline_installer_sha256:",
        "baseline_authorization_record_sha256:",
        "physical_l5_evidence_url:",
        "physical_l5_evidence_sha256:",
        "fetch_pinned_json.py",
        "--physical-l5-record",
        "--physical-l5-sha256",
        "UNVERIFIED_INTERNAL_EXACT_CANDIDATE",
        "ztr-unit-verdict",
        "ImageLab-RELEASE-VERDICT",
        "ImageLab-RELEASE-AUTHORIZED",
        "ImageLab-RELEASE-AUTHORIZATION.json",
        "run_clean_install_gate.ps1",
        "run_update_rollback_gate.ps1",
        "-BaselineInstallerPath",
        "-BrowserChannel msedge",
        "finalize_gate.py",
        "release_authorized=$true",
        "authorization_source='prior_finalizer_record'",
        "authorization_record_sha256",
        "GENESIS_RELEASE_AUTHORIZED",
    ):
        assert value in workflow
    assert "actions/setup-node@v6" not in workflow
    assert "actions/attest@v4" not in workflow


def test_finalizer_requires_all_g0_g8_and_physical_l5_evidence() -> None:
    source = (ROOT / "release_gate" / "finalize_gate.py").read_text("utf-8")
    for gate in (
        "G0_source",
        "G1_unit_matrix",
        "G2_candidate",
        "G2_reproducibility",
        "G3_clean_install",
        "G3_preinstall_selftest",
        "G3_postinstall_selftest",
        "G4_browser_ui",
        "G5_output_validation",
        "G6_baseline_pinned",
        "G6_update",
        "G7_rollback",
        "G8_independent",
        "G8_preinstall_selftest",
        "G8_postinstall_selftest",
        "G8_independent_ui",
        "G8_independent_outputs",
        "L5_physical_user_machine",
    ):
        assert gate in source
    for marker in (
        "physical_l5_sha_pin_mismatch",
        "physical_l5_hosted_runner",
        "physical_l5_timestamp_stale",
        "physical_l5_reused_hosted_install_id",
        "physical_l5_step_failed",
        "physical_l5_output_validator",
        "physical_l5_witness_not_confirmed",
        "clear_authorized_outputs",
        "selftest_identity_mismatch",
        "selftest_case_set_mismatch",
        "baseline_not_release_authorized",
        "baseline_authorization_source_invalid",
        "baseline_authorization_record_sha",
        "project_data_not_preserved",
        "project_handoff_mismatch",
        "ImageLab-RELEASE-AUTHORIZATION.json",
    ):
        assert marker in source


def _write_json(path: Path, value: object) -> None:
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


def _project_snapshot(canonical_sha: str) -> dict[str, object]:
    return {
        "project_id": "ZTR-UPDATE-PROJECT",
        "title": "Zero Trust Update baseline-install",
        "asset_id": "asset-1",
        "stored_name": "asset-1.svg",
        "asset_record_sha256": canonical_sha,
        "asset_file_sha256": canonical_sha,
        "asset_size_bytes": 306,
        "project_file_sha256": "4" * 64,
        "active_asset_id": "asset-1",
    }


def _physical_record(
    *,
    source_sha: str,
    installer_name: str,
    installer_sha: str,
    version: str,
    build_id: str,
) -> dict[str, object]:
    timestamp = datetime.now(timezone.utc).isoformat()
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
            "install_id": "physical-user-install-id",
        },
        "scenario": {
            "browser_driven": True,
            "steps": {name: {"status": "PASS"} for name in PHYSICAL_STEPS},
        },
        "outputs": [
            {
                "name": "physical-export.png",
                "sha256": "9" * 64,
                "validator_status": "PASS",
            }
        ],
        "direct_witness": {
            "name": "Dmitry",
            "confirmed": True,
            "statement": "I directly witnessed the complete ImageLab physical Windows L5 scenario.",
            "witnessed_at": timestamp,
        },
    }


def _build_complete_release_evidence(root: Path) -> tuple[str, str, str]:
    version = "9.9.9-test"
    build_id = "TEST-BUILD"
    clean_install_id = "clean-install-id"
    independent_install_id = "independent-install-id"
    installer = root / "build" / "ImageLab_by_LarannA_ZERO_TRUST_Setup_x64.exe"
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_bytes(b"synthetic exact installer evidence")
    installer_sha = hashlib.sha256(installer.read_bytes()).hexdigest()
    baseline_sha = "1" * 64
    authorization_record_sha = "6" * 64
    original_fixture_sha = "2" * 64
    canonical_uploaded_sha = "3" * 64
    source_sha = "8" * 64
    project_before = _project_snapshot(canonical_uploaded_sha)
    project_after_update = dict(project_before)
    project_after_rollback = dict(project_before)
    baseline_name = "ImageLab_by_LarannA_RELEASE_AUTHORIZED_Setup_x64.exe"

    _write_json(root / "source" / "source-gate.json", {"status": "PASS"})
    _write_json(root / "unit" / "unit-matrix-verdict.json", {"status": "PASS"})
    _write_json(
        root / "build" / "candidate-manifest.json",
        {
            "status": "PASS",
            "identity": {"app": "ImageLab by LarannA", "version": version, "build_id": build_id},
            "installer": {"name": installer.name, "sha256": installer_sha},
            "source": {"sha256": source_sha},
        },
    )
    _write_json(
        root / "build" / "reproducibility.json",
        {"status": "PASS", "installer_sha256": installer_sha, "second_build_sha256": installer_sha},
    )

    clean = {
        "status": "PASS",
        "installer_sha256": installer_sha,
        "version": version,
        "build_id": build_id,
        "install_id": clean_install_id,
    }
    independent = {
        "status": "PASS",
        "installer_sha256": installer_sha,
        "version": version,
        "build_id": build_id,
        "install_id": independent_install_id,
    }
    _write_json(root / "clean" / "clean-install.json", clean)
    _write_json(root / "clean" / "preinstall-selftest.json", _selftest(version, build_id, clean_install_id))
    _write_json(root / "clean" / "postinstall-selftest.json", _selftest(version, build_id, clean_install_id))
    _write_json(root / "clean" / "ui-gate.json", {"status": "PASS", "installer_sha256": installer_sha})
    _write_json(root / "clean" / "output-validation.json", {"status": "PASS", "installer_sha256": installer_sha})

    _write_json(
        root / "update" / "baseline-verification.json",
        {
            "schema": 3,
            "status": "PASS",
            "release_authorized": True,
            "authorization_source": "prior_finalizer_record",
            "authorization_record_status": "RELEASE_AUTHORIZED",
            "authorization_record_sha256": authorization_record_sha,
            "authorization_record_installer_name": baseline_name,
            "authorization_record_installer_sha256": baseline_sha,
            "release_tag": "v9.9.8-release-authorized",
            "installer_sha256": baseline_sha,
            "name": baseline_name,
        },
    )
    _write_json(
        root / "update" / "update-test.json",
        {
            "schema": 2,
            "status": "PASS",
            "installer_sha256": installer_sha,
            "baseline_installer_sha256": baseline_sha,
            "first_install_id": "baseline-install",
            "second_install_id": "candidate-install",
            "old_process_stopped": True,
            "project_data_preserved": True,
            "original_fixture_sha256": original_fixture_sha,
            "canonical_uploaded_sha256": canonical_uploaded_sha,
            "project_evidence_before": project_before,
            "project_evidence_after_update": project_after_update,
        },
    )
    _write_json(
        root / "update" / "rollback-test.json",
        {
            "schema": 2,
            "status": "PASS",
            "installer_sha256": installer_sha,
            "restored_install_id": "candidate-install",
            "expected_install_id": "candidate-install",
            "fault_exit_code": 1,
            "critical_hashes_restored": True,
            "project_data_preserved": True,
            "original_fixture_sha256": original_fixture_sha,
            "canonical_uploaded_sha256": canonical_uploaded_sha,
            "project_evidence_before": project_after_update,
            "project_evidence_after_rollback": project_after_rollback,
        },
    )

    _write_json(root / "independent" / "independent-verification.json", independent)
    _write_json(root / "independent" / "preinstall-selftest.json", _selftest(version, build_id, independent_install_id))
    _write_json(root / "independent" / "postinstall-selftest.json", _selftest(version, build_id, independent_install_id))
    _write_json(root / "independent" / "ui-gate.json", {"status": "PASS", "installer_sha256": installer_sha})
    _write_json(root / "independent" / "output-validation.json", {"status": "PASS", "installer_sha256": installer_sha})

    physical_path = root / "physical" / "physical-l5.json"
    _write_json(
        physical_path,
        _physical_record(
            source_sha=source_sha,
            installer_name=installer.name,
            installer_sha=installer_sha,
            version=version,
            build_id=build_id,
        ),
    )
    physical_sha = hashlib.sha256(physical_path.read_bytes()).hexdigest()
    return installer_sha, baseline_sha, physical_sha


def _run_finalizer(
    root: Path,
    output: Path,
    *,
    physical_sha: str | None = None,
    physical_path: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    path = physical_path or root / "physical" / "physical-l5.json"
    sha = physical_sha
    if sha is None and path.exists():
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
    result = subprocess.run(
        [
            sys.executable,
            "release_gate/finalize_gate.py",
            "--aggregate-dir",
            str(root),
            "--output-dir",
            str(output),
            "--physical-l5-record",
            str(path),
            "--physical-l5-sha256",
            sha or "",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    verdict = json.loads((output / "final-verdict.json").read_text("utf-8"))
    return result, verdict


def test_finalizer_parser_accepts_complete_synthetic_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    installer_sha, _, physical_sha = _build_complete_release_evidence(evidence)
    output = tmp_path / "output"
    result, verdict = _run_finalizer(evidence, output, physical_sha=physical_sha)
    assert result.returncode == 0, result.stderr
    assert verdict["status"] == "RELEASE_AUTHORIZED"
    assert verdict["gates"]["L5_physical_user_machine"] == "PASS"
    assert verdict["schema"] == 4
    authorization_path = output / "ImageLab-RELEASE-AUTHORIZATION.json"
    authorization = json.loads(authorization_path.read_text("utf-8"))
    assert authorization["schema"] == 2
    assert authorization["status"] == "RELEASE_AUTHORIZED"
    assert authorization["authorization_source"] == "finalize_gate.py"
    assert authorization["installer_sha256"] == installer_sha
    assert authorization["physical_l5_evidence_sha256"] == physical_sha
    assert authorization["physical_l5_install_id"] == "physical-user-install-id"


def test_finalizer_blocks_missing_physical_record_and_removes_stale_output(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _build_complete_release_evidence(evidence)
    physical = evidence / "physical" / "physical-l5.json"
    physical.unlink()
    output = tmp_path / "output"
    output.mkdir()
    stale_exe = output / "ImageLab_RELEASE_AUTHORIZED_Setup_x64.exe"
    stale_record = output / "ImageLab-RELEASE-AUTHORIZATION.json"
    stale_exe.write_bytes(b"stale")
    stale_record.write_text("{}", "utf-8")
    result, verdict = _run_finalizer(evidence, output, physical_sha="a" * 64)
    assert result.returncode != 0
    assert verdict["status"] == "RELEASE_BLOCKED"
    assert verdict["gates"]["L5_physical_user_machine"] == "MISSING"
    assert not stale_exe.exists()
    assert not stale_record.exists()


def test_finalizer_blocks_physical_sha_pin_mismatch(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _build_complete_release_evidence(evidence)
    result, verdict = _run_finalizer(evidence, tmp_path / "output", physical_sha="f" * 64)
    assert result.returncode != 0
    assert "physical_l5_sha_pin_mismatch" in verdict["failed_conditions"]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda value: value.__setitem__("hosted_runner", True), "physical_l5_hosted_runner"),
        (
            lambda value: value.__setitem__(
                "executed_at", (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
            ),
            "physical_l5_timestamp_stale",
        ),
        (
            lambda value: value["candidate"].__setitem__("installer_sha256", "0" * 64),
            "physical_l5_identity_mismatch:installer_sha256",
        ),
        (
            lambda value: value["scenario"]["steps"].pop("export"),
            "physical_l5_step_failed:export",
        ),
        (
            lambda value: value["outputs"][0].__setitem__("validator_status", "FAIL"),
            "physical_l5_output_validator:0",
        ),
        (
            lambda value: value["direct_witness"].__setitem__("confirmed", False),
            "physical_l5_witness_not_confirmed",
        ),
    ],
)
def test_finalizer_blocks_invalid_physical_l5_contract(tmp_path: Path, mutation, expected: str) -> None:
    evidence = tmp_path / "evidence"
    _build_complete_release_evidence(evidence)
    path = evidence / "physical" / "physical-l5.json"
    value = json.loads(path.read_text("utf-8"))
    mutation(value)
    _write_json(path, value)
    result, verdict = _run_finalizer(evidence, tmp_path / "output")
    assert result.returncode != 0
    assert expected in verdict["failed_conditions"]


def test_finalizer_blocks_missing_or_malformed_selftest_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _build_complete_release_evidence(evidence)
    (evidence / "clean" / "preinstall-selftest.json").unlink()
    (evidence / "independent" / "postinstall-selftest.json").write_text("{not-json", "utf-8")
    result, verdict = _run_finalizer(evidence, tmp_path / "output")
    assert result.returncode != 0
    assert verdict["gates"]["G3_preinstall_selftest"] == "MISSING"
    assert verdict["gates"]["G8_postinstall_selftest"] == "MALFORMED"
    assert "required_evidence_missing_or_malformed" in verdict["failed_conditions"]


def test_finalizer_blocks_tampered_selftest_identity_and_case_set(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _build_complete_release_evidence(evidence)
    path = evidence / "clean" / "postinstall-selftest.json"
    value = json.loads(path.read_text("utf-8"))
    value["install_id"] = "tampered-install"
    del value["tests"]["export"]
    _write_json(path, value)
    result, verdict = _run_finalizer(evidence, tmp_path / "output")
    assert result.returncode != 0
    assert "selftest_identity_mismatch:G3_postinstall_selftest:install_id" in verdict["failed_conditions"]
    assert "selftest_case_set_mismatch:G3_postinstall_selftest" in verdict["failed_conditions"]
    assert "selftest_case_failed:G3_postinstall_selftest:export" in verdict["failed_conditions"]


def test_finalizer_blocks_untrusted_baseline_and_sentinel_only_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _build_complete_release_evidence(evidence)
    baseline_path = evidence / "update" / "baseline-verification.json"
    baseline = json.loads(baseline_path.read_text("utf-8"))
    baseline["schema"] = 1
    baseline["release_authorized"] = False
    baseline["authorization_source"] = "filename_only"
    baseline.pop("authorization_record_sha256")
    _write_json(baseline_path, baseline)
    update_path = evidence / "update" / "update-test.json"
    update = json.loads(update_path.read_text("utf-8"))
    update["schema"] = 1
    update.pop("project_data_preserved")
    update.pop("project_evidence_before")
    update.pop("project_evidence_after_update")
    _write_json(update_path, update)
    result, verdict = _run_finalizer(evidence, tmp_path / "output")
    assert result.returncode != 0
    for expected in (
        "baseline_evidence_schema",
        "baseline_not_release_authorized",
        "baseline_authorization_source_invalid",
        "baseline_authorization_record_sha",
        "project_transition_schema:update",
        "project_data_not_preserved:update",
        "project_snapshot_missing:update:before",
    ):
        assert expected in verdict["failed_conditions"]


def test_finalizer_blocks_tampered_authorization_record_binding(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _build_complete_release_evidence(evidence)
    path = evidence / "update" / "baseline-verification.json"
    baseline = json.loads(path.read_text("utf-8"))
    baseline["authorization_record_status"] = "RELEASE_BLOCKED"
    baseline["authorization_record_installer_sha256"] = "7" * 64
    baseline["authorization_record_installer_name"] = "wrong.exe"
    _write_json(path, baseline)
    result, verdict = _run_finalizer(evidence, tmp_path / "output")
    assert result.returncode != 0
    assert "baseline_authorization_record_status" in verdict["failed_conditions"]
    assert "baseline_authorization_record_installer_sha_mismatch" in verdict["failed_conditions"]
    assert "baseline_authorization_record_name_mismatch" in verdict["failed_conditions"]


def test_finalizer_accepts_genesis_authorized_baseline_for_later_normal_release(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _build_complete_release_evidence(evidence)
    path = evidence / "update" / "baseline-verification.json"
    baseline = json.loads(path.read_text("utf-8"))
    baseline["authorization_record_status"] = "GENESIS_RELEASE_AUTHORIZED"
    baseline["name"] = "ImageLab_by_LarannA_GENESIS_RELEASE_AUTHORIZED_Setup_x64.exe"
    baseline["authorization_record_installer_name"] = baseline["name"]
    _write_json(path, baseline)
    result, verdict = _run_finalizer(evidence, tmp_path / "output")
    assert result.returncode == 0, result.stderr
    assert verdict["status"] == "RELEASE_AUTHORIZED"


def test_finalizer_blocks_tampered_project_transition(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _build_complete_release_evidence(evidence)
    path = evidence / "update" / "update-test.json"
    update = json.loads(path.read_text("utf-8"))
    update["project_evidence_after_update"]["asset_file_sha256"] = "5" * 64
    update["old_process_stopped"] = False
    _write_json(path, update)
    result, verdict = _run_finalizer(evidence, tmp_path / "output")
    assert result.returncode != 0
    assert "project_asset_file_sha_mismatch:update:after" in verdict["failed_conditions"]
    assert "project_transition_mismatch:update:asset_file_sha256" in verdict["failed_conditions"]
    assert "update_old_process_not_stopped" in verdict["failed_conditions"]


def test_pinned_json_fetcher_rejects_non_https_and_bad_sha(tmp_path: Path) -> None:
    output = tmp_path / "record.json"
    result = subprocess.run(
        [
            sys.executable,
            "release_gate/fetch_pinned_json.py",
            "--url",
            "http://example.invalid/evidence.json",
            "--sha256",
            "a" * 64,
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert not output.exists()

    result = subprocess.run(
        [
            sys.executable,
            "release_gate/fetch_pinned_json.py",
            "--url",
            "https://example.invalid/evidence.json",
            "--sha256",
            "invalid",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert not output.exists()


def test_release_identity_is_consistent_across_python_and_go() -> None:
    expected_version = settings.app_version
    expected_build = settings.build_id
    for path in (
        ROOT / "windows_installer" / "launcher" / "main.go",
        ROOT / "windows_installer" / "installer" / "main.go",
    ):
        text = path.read_text("utf-8")
        assert expected_version in text
        assert expected_build in text


def test_unit_matrix_is_complete_and_fail_closed(tmp_path: Path) -> None:
    from release_gate.finalize_unit_matrix import EXPECTED

    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    for case_id, test_file in EXPECTED.items():
        (case_dir / f"{case_id}.json").write_text(
            json.dumps({"schema": 1, "status": "PASS", "case_id": case_id, "test_file": test_file}),
            "utf-8",
        )
    output = tmp_path / "verdict.json"
    result = subprocess.run(
        [sys.executable, "release_gate/finalize_unit_matrix.py", "--input-dir", str(case_dir), "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    verdict = json.loads(output.read_text("utf-8"))
    assert verdict["status"] == "PASS"
    assert verdict["passed_case_count"] == len(EXPECTED)

    (case_dir / "a0.json").unlink()
    result = subprocess.run(
        [sys.executable, "release_gate/finalize_unit_matrix.py", "--input-dir", str(case_dir), "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode != 0
    verdict = json.loads(output.read_text("utf-8"))
    assert verdict["status"] == "FAIL"
    assert "a0" in verdict["missing_cases"]


def test_workflow_lists_every_unit_file_exactly_once() -> None:
    from release_gate.finalize_unit_matrix import EXPECTED

    workflow = (ROOT / ".github" / "workflows" / "zero-trust-release.yml").read_text("utf-8")
    for case_id, test_file in EXPECTED.items():
        assert f"id: {case_id}" in workflow
        assert workflow.count(f"file: {test_file}") == 1


def test_update_gate_uses_real_pinned_baseline_and_preserves_real_project() -> None:
    source = (ROOT / "release_gate" / "run_update_rollback_gate.ps1").read_text("utf-8")
    for marker in (
        "BaselineInstallerPath",
        "baselineInstallerSha",
        "Baseline and candidate installers must be different",
        "Get-ImageLabProjectEvidence",
        "Compare-ImageLabProjectEvidence",
        "/api/projects/$ProjectId",
        "/api/projects/$projectId/upload",
        "-Form @{ files = Get-Item",
        "project_file_sha256",
        "asset_file_sha256",
        "project-before-update.json",
        "project-after-update.json",
        "project-after-rollback.json",
        "original_fixture_sha256",
        "canonical_uploaded_sha256",
        "uploadedAssetSha",
        "zero-trust-update-sentinel.txt",
        "do not use it as the project-preservation proof",
        "project_data_preserved=$true",
    ):
        assert marker in source


def test_ui_gate_supports_edge_and_independent_bundled_chromium() -> None:
    source = (ROOT / "release_gate" / "ui_gate.py").read_text("utf-8")
    assert 'choices=("bundled", "msedge")' in source
    assert 'launch_options["channel"] = args.browser_channel' in source
    workflow = (ROOT / ".github" / "workflows" / "zero-trust-release.yml").read_text("utf-8")
    assert "-BrowserChannel msedge" in workflow
    assert "-BrowserChannel bundled" in workflow
