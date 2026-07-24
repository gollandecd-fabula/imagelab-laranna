from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.config import settings

ROOT = Path(__file__).resolve().parents[1]


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
    assert set(verdict["tests"]) == {"resize_ppi", "background", "halftone", "vector", "history_lineage", "export"}
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
    assert "UNVERIFIED_INTERNAL_EXACT_CANDIDATE" in workflow
    assert "ztr-unit-verdict" in workflow
    assert "ImageLab-RELEASE-VERDICT" in workflow
    assert "ImageLab-RELEASE-AUTHORIZED" in workflow
    assert "run_clean_install_gate.ps1" in workflow
    assert "run_update_rollback_gate.ps1" in workflow
    assert "-BaselineInstallerPath" in workflow
    assert "-BrowserChannel msedge" in workflow
    assert "finalize_gate.py" in workflow


def test_finalizer_requires_all_g0_g8_evidence() -> None:
    source = (ROOT / "release_gate" / "finalize_gate.py").read_text("utf-8")
    for gate in ("G0_source", "G1_unit_matrix", "G2_candidate", "G2_reproducibility", "G3_clean_install", "G4_browser_ui", "G5_output_validation", "G6_baseline_pinned", "G6_update", "G7_rollback", "G8_independent"):
        assert gate in source
    assert 'status = "RELEASE_AUTHORIZED" if not failed else "RELEASE_BLOCKED"' in source


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


def test_update_gate_uses_real_pinned_baseline_and_preserves_data() -> None:
    source = (ROOT / "release_gate" / "run_update_rollback_gate.ps1").read_text("utf-8")
    assert "BaselineInstallerPath" in source
    assert "baselineInstallerSha" in source
    assert "Baseline and candidate installers must be different" in source
    assert "zero-trust-update-sentinel.txt" in source
    assert "project_data_preserved=$true" in source


def test_ui_gate_supports_edge_and_independent_bundled_chromium() -> None:
    source = (ROOT / "release_gate" / "ui_gate.py").read_text("utf-8")
    assert 'choices=("bundled", "msedge")' in source
    assert 'launch_options["channel"] = args.browser_channel' in source
    workflow = (ROOT / ".github" / "workflows" / "zero-trust-release.yml").read_text("utf-8")
    assert "-BrowserChannel msedge" in workflow
    assert "-BrowserChannel bundled" in workflow
