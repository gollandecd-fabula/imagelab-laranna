from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from app.config import settings

ROOT = Path(__file__).resolve().parents[1]
SELFTEST_CASES = {"resize_ppi", "background", "halftone", "vector", "history_lineage", "export"}


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
    assert source.index('runReleaseSelfTest(stagingDir, installID, "preinstall"') < source.index("promoteAtomic(stagingDir, installDir, backupDir)")
    assert 'faultRequested("after_promotion")' in source
    assert 'IMAGELAB_INSTALLER_CI' in source
    assert 'IMAGELAB_EXTERNAL_BROWSER=1' in source
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
    assert "workflow_dispatch:" in workflow
    assert "baseline_release_tag:" in workflow
    assert "baseline_installer_sha256:" in workflow
    assert "baseline_authorization_record_sha256:" in workflow
    assert "UNVERIFIED_INTERNAL_EXACT_CANDIDATE" in workflow
    assert "ztr-unit-verdict" in workflow
    assert "ImageLab-RELEASE-VERDICT" in workflow
    assert "ImageLab-RELEASE-AUTHORIZED" in workflow
    assert "ImageLab-RELEASE-AUTHORIZATION.json" in workflow
    assert "run_clean_install_gate.ps1" in workflow
    assert "run_update_rollback_gate.ps1" in workflow
    assert "-BaselineInstallerPath" in workflow
    assert "-BrowserChannel msedge" in workflow
    assert "finalize_gate.py" in workflow
    assert "release_authorized=$true" in workflow
    assert "authorization_source='prior_finalizer_record'" in workflow
    assert "authorization_record_sha256" in workflow


def test_finalizer_requires_all_g0_g8_evidence() -> None:
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
    ):
        assert gate in source
    assert 'status = "RELEASE_AUTHORIZED" if not failed else "RELEASE_BLOCKED"' in source
    assert "selftest_identity_mismatch" in source
    assert "selftest_case_set_mismatch" in source
    assert "baseline_not_release_authorized" in source
    assert "baseline_authorization_source_invalid" in source
    assert "baseline_authorization_record_sha" in source
    assert "project_data_not_preserved" in source
    assert "project_handoff_mismatch" in source
    assert "ImageLab-RELEASE-AUTHORIZATION.json" in source


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


def _build_complete_release_evidence(root: Path) -> tuple[str, str]:
    version = "9.9.9-test"
    build_id = "TEST-BUILD"
    clean_install_id = "clean-install-id"
    independent_install_id = "independent-install-id"
    installer = root / "build" / "ImageLab_ZERO_TRUST_Setup_x64.exe"
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_bytes(b"synthetic exact installer evidence")
    installer_sha = hashlib.sha256(installer.read_bytes()).hexdigest()
    baseline_sha = "1" * 64
    authorization_record_sha = "6" * 64
    original_fixture_sha = "2" * 64
    canonical_uploaded_sha = "3" * 64
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
            "installer": {"sha256": installer_sha},
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
    return installer_sha, baseline_sha


def _run_finalizer(root: Path, output: Path) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = subprocess.run(
        [
            sys.executable,
            "release_gate/finalize_gate.py",
            "--aggregate-dir",
            str(root),
            "--output-dir",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    verdict = json.loads((output / "final-verdict.json").read_text("utf-8"))
    return result, verdict


def test_finalizer_accepts_complete_embedded_selftest_and_project_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    installer_sha, _ = _build_complete_release_evidence(evidence)
    output = tmp_path / "output"
    result, verdict = _run_finalizer(evidence, output)
    assert result.returncode == 0, result.stderr
    assert verdict["status"] == "RELEASE_AUTHORIZED"
    assert verdict["gates"]["G3_preinstall_selftest"] == "PASS"
    assert verdict["gates"]["G8_postinstall_selftest"] == "PASS"
    assert verdict["schema"] == 3
    authorization_path = output / "ImageLab-RELEASE-AUTHORIZATION.json"
    assert authorization_path.exists()
    authorization = json.loads(authorization_path.read_text("utf-8"))
    assert authorization["status"] == "RELEASE_AUTHORIZED"
    assert authorization["authorization_source"] == "finalize_gate.py"
    assert authorization["installer_sha256"] == installer_sha
    assert authorization["installer_name"] == "ImageLab_RELEASE_AUTHORIZED_Setup_x64.exe"
    assert len(authorization["final_verdict_sha256"]) == 64
    assert len(authorization["release_evidence_sha256"]) == 64


def test_finalizer_blocks_missing_or_malformed_selftest_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _build_complete_release_evidence(evidence)
    (evidence / "clean" / "preinstall-selftest.json").unlink()
    (evidence / "independent" / "postinstall-selftest.json").write_text("{not-json", "utf-8")
    result, verdict = _run_finalizer(evidence, tmp_path / "output")
    assert result.returncode != 0
    assert verdict["status"] == "RELEASE_BLOCKED"
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
    assert verdict["status"] == "RELEASE_BLOCKED"
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
    assert verdict["status"] == "RELEASE_BLOCKED"
    assert "baseline_evidence_schema" in verdict["failed_conditions"]
    assert "baseline_not_release_authorized" in verdict["failed_conditions"]
    assert "baseline_authorization_source_invalid" in verdict["failed_conditions"]
    assert "baseline_authorization_record_sha" in verdict["failed_conditions"]
    assert "project_transition_schema:update" in verdict["failed_conditions"]
    assert "project_data_not_preserved:update" in verdict["failed_conditions"]
    assert "project_snapshot_missing:update:before" in verdict["failed_conditions"]


def test_finalizer_blocks_tampered_authorization_record_binding(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _build_complete_release_evidence(evidence)
    baseline_path = evidence / "update" / "baseline-verification.json"
    baseline = json.loads(baseline_path.read_text("utf-8"))
    baseline["authorization_record_status"] = "RELEASE_BLOCKED"
    baseline["authorization_record_installer_sha256"] = "7" * 64
    baseline["authorization_record_installer_name"] = "wrong.exe"
    _write_json(baseline_path, baseline)
    result, verdict = _run_finalizer(evidence, tmp_path / "output")
    assert result.returncode != 0
    assert verdict["status"] == "RELEASE_BLOCKED"
    assert "baseline_authorization_record_status" in verdict["failed_conditions"]
    assert "baseline_authorization_record_installer_sha_mismatch" in verdict["failed_conditions"]
    assert "baseline_authorization_record_name_mismatch" in verdict["failed_conditions"]


def test_finalizer_blocks_tampered_project_transition(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _build_complete_release_evidence(evidence)
    update_path = evidence / "update" / "update-test.json"
    update = json.loads(update_path.read_text("utf-8"))
    update["project_evidence_after_update"]["asset_file_sha256"] = "5" * 64
    update["old_process_stopped"] = False
    _write_json(update_path, update)
    result, verdict = _run_finalizer(evidence, tmp_path / "output")
    assert result.returncode != 0
    assert verdict["status"] == "RELEASE_BLOCKED"
    assert "project_asset_file_sha_mismatch:update:after" in verdict["failed_conditions"]
    assert "project_transition_mismatch:update:asset_file_sha256" in verdict["failed_conditions"]
    assert "update_old_process_not_stopped" in verdict["failed_conditions"]


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
    assert "BaselineInstallerPath" in source
    assert "baselineInstallerSha" in source
    assert "Baseline and candidate installers must be different" in source
    assert "Get-ImageLabProjectEvidence" in source
    assert "Compare-ImageLabProjectEvidence" in source
    assert "/api/projects/$ProjectId" in source
    assert "/api/projects/$projectId/upload" in source
    assert "-Form @{ files = Get-Item" in source
    assert "project_file_sha256" in source
    assert "asset_file_sha256" in source
    assert "project-before-update.json" in source
    assert "project-after-update.json" in source
    assert "project-after-rollback.json" in source
    assert "original_fixture_sha256" in source
    assert "canonical_uploaded_sha256" in source
    assert "uploadedAssetSha" in source
    assert "zero-trust-update-sentinel.txt" in source
    assert "do not use it as the project-preservation proof" in source
    assert "project_data_preserved=$true" in source


def test_ui_gate_supports_edge_and_independent_bundled_chromium() -> None:
    source = (ROOT / "release_gate" / "ui_gate.py").read_text("utf-8")
    assert 'choices=("bundled", "msedge")' in source
    assert 'launch_options["channel"] = args.browser_channel' in source
    workflow = (ROOT / ".github" / "workflows" / "zero-trust-release.yml").read_text("utf-8")
    assert "-BrowserChannel msedge" in workflow
    assert "-BrowserChannel bundled" in workflow
