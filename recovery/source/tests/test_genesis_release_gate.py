from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from release_gate.genesis.verify_no_prior_release import inspect_history, inspect_releases

ROOT = Path(__file__).resolve().parents[1]
SELFTEST_CASES = {"resize_ppi", "background", "halftone", "vector", "history_lineage", "export"}
PHYSICAL_CASES = SELFTEST_CASES | {"installed_launch", "browser_ui_path", "output_file_validation"}
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


def _build_evidence(root: Path) -> tuple[str, str, str, str]:
    version = "9.9.9-genesis-test"
    build_id = "GENESIS-TEST"
    source_sha = "c" * 64
    installer = root / "build" / "ImageLab_by_LarannA_ZERO_TRUST_Setup_x64.exe"
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_bytes(b"exact synthetic genesis installer")
    installer_sha = _sha(installer)
    identity = {"app": "ImageLab by LarannA", "version": version, "build_id": build_id}

    _write(root / "source" / "source-gate.json", {"status": "PASS"})
    _write(root / "unit" / "unit-matrix-verdict.json", {"status": "PASS"})
    _write(
        root / "build" / "candidate-manifest.json",
        {
            "status": "PASS",
            "identity": identity,
            "installer": {"sha256": installer_sha},
            "source": {"sha256": source_sha},
        },
    )
    _write(
        root / "build" / "reproducibility.json",
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
        root / "genesis" / "genesis-baseline-verification.json",
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
        root / "qualification" / "qualification-run.json",
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
        root / "qualification-verdict" / "final-verdict.json",
        {"schema": 3, "status": "RELEASE_BLOCKED", "installer_sha256": installer_sha, "gates": gates},
    )

    g7_sha = _write_g7_bundle(root, installer_sha, source_sha)

    physical_dir = root / "physical"
    physical_dir.mkdir(parents=True, exist_ok=True)
    bundle = physical_dir / "ImageLab-PHYSICAL-L5-EVIDENCE.zip"
    physical_install = {
        "status": "PASS",
        "installer_sha256": installer_sha,
        "version": version,
        "build_id": build_id,
        "install_id": "physical-install",
    }
    members = {
        "physical-l5/clean-install.json": physical_install,
        "physical-l5/preinstall-selftest.json": _selftest(version, build_id, "physical-install"),
        "physical-l5/postinstall-selftest.json": _selftest(version, build_id, "physical-install"),
        "physical-l5/ui-gate.json": {"status": "PASS", "installer_sha256": installer_sha},
        "physical-l5/output-validation.json": {"status": "PASS", "installer_sha256": installer_sha},
    }
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, json.dumps(value))
        archive.writestr("physical-l5/screenshot.png", b"png")
        archive.writestr("physical-l5/output.svg", b"<svg/>")
        archive.writestr("physical-l5/browser-trace.json", b"{}")
    bundle_sha = _sha(bundle)
    manifest = physical_dir / "ImageLab-PHYSICAL-L5.json"
    _write(
        manifest,
        {
            "schema": 1,
            "status": "PASS",
            "evidence_level": "L5",
            "execution_environment": "physical_user_machine",
            "installer_sha256": installer_sha,
            "app": identity["app"],
            "version": version,
            "build_id": build_id,
            "install_id": "physical-install",
            "observed_at_utc": "2026-07-25T15:00:00Z",
            "witness": {"name": "Dmitry", "role": "product_owner"},
            "machine": {"windows_version": "Windows 11"},
            "tests": {name: {"status": "PASS"} for name in sorted(PHYSICAL_CASES)},
            "evidence_files": sorted(members)
            + ["physical-l5/screenshot.png", "physical-l5/output.svg", "physical-l5/browser-trace.json"],
            "evidence_bundle_sha256": bundle_sha,
        },
    )
    return installer_sha, _sha(manifest), bundle_sha, g7_sha


def _run(
    root: Path,
    output: Path,
    manifest_sha: str,
    bundle_sha: str,
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
            "--physical-manifest-sha256",
            manifest_sha,
            "--physical-bundle-sha256",
            bundle_sha,
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
        [
            {
                "artifacts": [
                    {
                        "id": 20,
                        "name": "ImageLab-GENESIS-RELEASE-AUTHORIZED",
                        "workflow_run": {"id": 10},
                    }
                ]
            }
        ],
        "owner/repo",
        GENESIS_RUN_ID,
    )
    assert result["status"] == "FAIL"
    assert result["prior_successful_genesis_run_count"] == 1
    assert result["prior_authorized_genesis_artifact_count"] == 1


def test_genesis_finalizer_authorizes_only_complete_first_release_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    installer_sha, manifest_sha, bundle_sha, g7_sha = _build_evidence(evidence)
    output = tmp_path / "output"
    result, verdict = _run(evidence, output, manifest_sha, bundle_sha, g7_sha)
    assert result.returncode == 0, result.stderr
    assert verdict["status"] == "GENESIS_RELEASE_AUTHORIZED"
    assert verdict["gates"]["G6_update_from_prior_authorized_release"] == "NOT_APPLICABLE_FIRST_RELEASE"
    assert verdict["gates"]["G7_rollback_to_prior_authorized_release"] == "PASS"
    record_path = output / "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json"
    record = json.loads(record_path.read_text("utf-8"))
    assert record["status"] == "GENESIS_RELEASE_AUTHORIZED"
    assert record["authorization_source_path"] == "release_gate/genesis/finalize_gate.py"
    assert record["installer_sha256"] == installer_sha
    assert record["install_id"] == "physical-install"
    assert list(output.glob("*GENESIS_RELEASE_AUTHORIZED*_Setup_x64.exe"))
    assert not (output / "ImageLab-RELEASE-AUTHORIZATION.json").exists()
    assert not list(output.glob("ImageLab_by_LarannA_RELEASE_AUTHORIZED*_Setup_x64.exe"))


def test_genesis_finalizer_blocks_when_prior_authorized_asset_exists(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, manifest_sha, bundle_sha, g7_sha = _build_evidence(evidence)
    path = evidence / "genesis" / "genesis-baseline-verification.json"
    value = json.loads(path.read_text("utf-8"))
    value["status"] = "FAIL"
    value["authorization_record_asset_count"] = 1
    value["matching_assets"] = [{"tag": "v1", "name": "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json"}]
    _write(path, value)
    result, verdict = _run(evidence, tmp_path / "output", manifest_sha, bundle_sha, g7_sha)
    assert result.returncode != 0
    assert "genesis_absence_invalid:authorization_record_asset_count" in verdict["failed_conditions"]


def test_genesis_finalizer_requires_exact_pinned_g7_bundle(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, manifest_sha, bundle_sha, _ = _build_evidence(evidence)
    result, verdict = _run(evidence, tmp_path / "output", manifest_sha, bundle_sha, "f" * 64)
    assert result.returncode != 0
    assert "g7_bundle_pinned_sha_mismatch" in verdict["failed_conditions"]


def test_genesis_finalizer_rejects_failed_or_na_g7(tmp_path: Path) -> None:
    for status in ("FAIL", "NOT_APPLICABLE_FIRST_RELEASE"):
        evidence = tmp_path / status
        installer_sha, manifest_sha, bundle_sha, _ = _build_evidence(evidence)
        source_sha = json.loads((evidence / "build/candidate-manifest.json").read_text("utf-8"))["source"][
            "sha256"
        ]
        g7_sha = _write_g7_bundle(
            evidence,
            installer_sha,
            source_sha,
            mutate=lambda update, rollback, status=status: rollback.update(status=status),
        )
        result, verdict = _run(evidence, tmp_path / f"output-{status}", manifest_sha, bundle_sha, g7_sha)
        assert result.returncode != 0
        assert "g7_rollback_status" in verdict["failed_conditions"]


def test_genesis_finalizer_rejects_current_candidate_as_g7_baseline(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    installer_sha, manifest_sha, bundle_sha, _ = _build_evidence(evidence)
    source_sha = json.loads((evidence / "build/candidate-manifest.json").read_text("utf-8"))["source"]["sha256"]
    bundle = evidence / "g7/ImageLab-GENESIS-G7-EVIDENCE.zip"
    inventory = {"schema": 1, "project_count": 3, "asset_count": 3, "projects_sha256": "d" * 64, "projects": []}
    update = {
        "schema": 3,
        "status": "PASS",
        "installer_sha256": installer_sha,
        "baseline_installer_sha256": installer_sha,
        "first_install_id": "baseline",
        "second_install_id": "candidate",
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
        "restored_install_id": "candidate",
        "expected_install_id": "candidate",
        "fault_exit_code": 1,
        "critical_hashes_restored": True,
        "project_data_preserved": True,
        "sentinel_preserved": True,
        "project_count": 3,
        "asset_count": 3,
        "project_inventory_before": inventory,
        "project_inventory_after_rollback": inventory,
    }
    update_bytes = json.dumps(update, sort_keys=True).encode()
    rollback_bytes = json.dumps(rollback, sort_keys=True).encode()
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
    result, verdict = _run(evidence, tmp_path / "output", manifest_sha, bundle_sha, _sha(bundle))
    assert result.returncode != 0
    assert "g7_self_baseline_forbidden" in verdict["failed_conditions"]


def test_genesis_finalizer_blocks_unpinned_physical_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, _, bundle_sha, g7_sha = _build_evidence(evidence)
    result, verdict = _run(evidence, tmp_path / "output", "f" * 64, bundle_sha, g7_sha)
    assert result.returncode != 0
    assert "physical_manifest_pinned_sha_mismatch" in verdict["failed_conditions"]


def test_genesis_finalizer_rejects_physical_file_list_mismatch(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, manifest_sha, bundle_sha, g7_sha = _build_evidence(evidence)
    manifest = evidence / "physical" / "ImageLab-PHYSICAL-L5.json"
    value = json.loads(manifest.read_text("utf-8"))
    value["evidence_files"] = ["invented.txt"]
    _write(manifest, value)
    result, verdict = _run(evidence, tmp_path / "output", _sha(manifest), bundle_sha, g7_sha)
    assert result.returncode != 0
    assert "physical_manifest_evidence_files_mismatch" in verdict["failed_conditions"]


def test_genesis_finalizer_removes_stale_normal_and_genesis_outputs_on_failure(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, _, bundle_sha, g7_sha = _build_evidence(evidence)
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
    result, _ = _run(evidence, output, "f" * 64, bundle_sha, g7_sha)
    assert result.returncode != 0
    assert all(not path.exists() for path in stale_files)


def test_genesis_workflow_requires_history_g7_and_physical_evidence() -> None:
    workflow = (ROOT / ".github" / "workflows" / "zero-trust-genesis-release.yml").read_text("utf-8")
    assert "ImageLab Genesis First Release Gate" in workflow
    assert "qualification_run_id:" in workflow
    assert "g7_evidence_release_tag:" in workflow
    assert "g7_evidence_bundle_sha256:" in workflow
    assert "physical_l5_manifest_sha256:" in workflow
    assert "workflow-runs.json" in workflow
    assert "artifacts.json" in workflow
    assert "--current-run-id" in workflow
    assert "ImageLab-GENESIS-G7-EVIDENCE.zip" in workflow
    assert "--g7-bundle-sha256" in workflow
    assert "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json" in workflow
    assert "ImageLab-RELEASE-AUTHORIZATION.json" not in workflow
    assert "Enforce fail-closed genesis verdict" in workflow


def test_repository_root_has_executable_genesis_workflow() -> None:
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if not workspace:
        return
    workflow = (Path(workspace) / ".github" / "workflows" / "zero-trust-genesis-release.yml").read_text("utf-8")
    assert "working-directory: recovery/source" in workflow
    assert "recovery/source/authorized-release" in workflow
    assert "release_gate/genesis/finalize_gate.py" in workflow
