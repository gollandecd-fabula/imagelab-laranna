from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from release_gate.genesis.verify_no_prior_release import inspect_releases

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


def _build_evidence(root: Path) -> tuple[str, str, str]:
    version = "9.9.9-genesis-test"
    build_id = "GENESIS-TEST"
    installer = root / "build" / "ImageLab_by_LarannA_ZERO_TRUST_Setup_x64.exe"
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_bytes(b"exact synthetic genesis installer")
    installer_sha = _sha(installer)
    identity = {"app": "ImageLab by LarannA", "version": version, "build_id": build_id}

    _write(root / "source" / "source-gate.json", {"status": "PASS"})
    _write(root / "unit" / "unit-matrix-verdict.json", {"status": "PASS"})
    _write(root / "build" / "candidate-manifest.json", {"status": "PASS", "identity": identity, "installer": {"sha256": installer_sha}})
    _write(root / "build" / "reproducibility.json", {"status": "PASS", "installer_sha256": installer_sha, "second_build_sha256": installer_sha})

    for folder, install_id, base_name in (("clean", "clean-install", "clean-install.json"), ("independent", "independent-install", "independent-verification.json")):
        install = {"status": "PASS", "installer_sha256": installer_sha, "version": version, "build_id": build_id, "install_id": install_id}
        _write(root / folder / base_name, install)
        _write(root / folder / "preinstall-selftest.json", _selftest(version, build_id, install_id))
        _write(root / folder / "postinstall-selftest.json", _selftest(version, build_id, install_id))
        _write(root / folder / "ui-gate.json", {"status": "PASS", "installer_sha256": installer_sha})
        _write(root / folder / "output-validation.json", {"status": "PASS", "installer_sha256": installer_sha})

    _write(
        root / "genesis" / "genesis-baseline-verification.json",
        {
            "schema": 1,
            "status": "PASS",
            "release_mode": "genesis_first_release",
            "protocol_rule": "GENESIS-FIRST-RELEASE-V1",
            "repository": "owner/repo",
            "query_source": "github_api_releases_paginated",
            "query_complete": True,
            "release_count_scanned": 3,
            "authorized_installer_asset_count": 0,
            "authorization_record_asset_count": 0,
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
    _write(root / "qualification-verdict" / "final-verdict.json", {"schema": 3, "status": "RELEASE_BLOCKED", "installer_sha256": installer_sha, "gates": gates})

    physical_dir = root / "physical"
    physical_dir.mkdir(parents=True, exist_ok=True)
    bundle = physical_dir / "ImageLab-PHYSICAL-L5-EVIDENCE.zip"
    physical_install = {"status": "PASS", "installer_sha256": installer_sha, "version": version, "build_id": build_id, "install_id": "physical-install"}
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
            "evidence_files": sorted(members) + ["physical-l5/screenshot.png", "physical-l5/output.svg", "physical-l5/browser-trace.json"],
            "evidence_bundle_sha256": bundle_sha,
        },
    )
    return installer_sha, _sha(manifest), bundle_sha


def _run(root: Path, output: Path, manifest_sha: str, bundle_sha: str) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
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
            "--qualification-run-id",
            "12345",
            "--qualification-head-sha",
            "a" * 40,
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


def test_release_absence_verifier_rejects_any_prior_authorized_asset() -> None:
    clean = inspect_releases([[{"tag_name": "v0", "assets": []}]], "owner/repo")
    assert clean["status"] == "PASS"
    blocked = inspect_releases(
        [{"tag_name": "v1", "assets": [{"name": "ImageLab-RELEASE-AUTHORIZATION.json"}]}],
        "owner/repo",
    )
    assert blocked["status"] == "FAIL"
    assert blocked["authorization_record_asset_count"] == 1


def test_genesis_finalizer_authorizes_only_complete_first_release_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    installer_sha, manifest_sha, bundle_sha = _build_evidence(evidence)
    output = tmp_path / "output"
    result, verdict = _run(evidence, output, manifest_sha, bundle_sha)
    assert result.returncode == 0, result.stderr
    assert verdict["status"] == "RELEASE_AUTHORIZED"
    assert verdict["gates"]["G6_update_from_prior_authorized_release"] == "NOT_APPLICABLE_FIRST_RELEASE"
    record = json.loads((output / "ImageLab-RELEASE-AUTHORIZATION.json").read_text("utf-8"))
    assert record["authorization_source"] == "finalize_gate.py"
    assert record["authorization_source_path"] == "release_gate/genesis/finalize_gate.py"
    assert record["release_mode"] == "genesis_first_release"
    assert record["installer_sha256"] == installer_sha


def test_genesis_finalizer_blocks_when_prior_authorized_asset_exists(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, manifest_sha, bundle_sha = _build_evidence(evidence)
    path = evidence / "genesis" / "genesis-baseline-verification.json"
    value = json.loads(path.read_text("utf-8"))
    value["status"] = "FAIL"
    value["authorization_record_asset_count"] = 1
    value["matching_assets"] = [{"tag": "v1", "name": "ImageLab-RELEASE-AUTHORIZATION.json"}]
    _write(path, value)
    result, verdict = _run(evidence, tmp_path / "output", manifest_sha, bundle_sha)
    assert result.returncode != 0
    assert verdict["status"] == "RELEASE_BLOCKED"
    assert "genesis_absence_invalid:authorization_record_asset_count" in verdict["failed_conditions"]


def test_genesis_finalizer_blocks_unpinned_physical_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, _, bundle_sha = _build_evidence(evidence)
    result, verdict = _run(evidence, tmp_path / "output", "f" * 64, bundle_sha)
    assert result.returncode != 0
    assert verdict["status"] == "RELEASE_BLOCKED"
    assert "physical_manifest_pinned_sha_mismatch" in verdict["failed_conditions"]


def test_genesis_finalizer_rejects_physical_file_list_mismatch(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, manifest_sha, bundle_sha = _build_evidence(evidence)
    manifest = evidence / "physical" / "ImageLab-PHYSICAL-L5.json"
    value = json.loads(manifest.read_text("utf-8"))
    value["evidence_files"] = ["invented.txt"]
    _write(manifest, value)
    result, verdict = _run(evidence, tmp_path / "output", _sha(manifest), bundle_sha)
    assert result.returncode != 0
    assert "physical_manifest_evidence_files_mismatch" in verdict["failed_conditions"]


def test_genesis_finalizer_removes_stale_authorized_outputs_on_failure(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, _, bundle_sha = _build_evidence(evidence)
    output = tmp_path / "output"
    output.mkdir()
    stale = output / "ImageLab_by_LarannA_RELEASE_AUTHORIZED_Setup_x64.exe"
    stale.write_bytes(b"stale")
    (output / "ImageLab-RELEASE-AUTHORIZATION.json").write_text("{}", "utf-8")
    result, _ = _run(evidence, output, "f" * 64, bundle_sha)
    assert result.returncode != 0
    assert not stale.exists()
    assert not (output / "ImageLab-RELEASE-AUTHORIZATION.json").exists()


def test_genesis_workflow_is_one_time_and_fail_closed() -> None:
    workflow = (ROOT / ".github" / "workflows" / "zero-trust-genesis-release.yml").read_text("utf-8")
    assert "ImageLab Genesis First Release Gate" in workflow
    assert "qualification_run_id:" in workflow
    assert "physical_l5_manifest_sha256:" in workflow
    assert "physical_l5_bundle_sha256:" in workflow
    assert "verify_no_prior_release.py" in workflow
    assert "release_gate/genesis/finalize_gate.py" in workflow
    assert "ImageLab-GENESIS-RELEASE-AUTHORIZED" in workflow
    assert "Enforce fail-closed genesis verdict" in workflow


def test_repository_root_has_executable_genesis_workflow() -> None:
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if not workspace:
        return
    workflow = (Path(workspace) / ".github" / "workflows" / "zero-trust-genesis-release.yml").read_text("utf-8")
    assert "working-directory: recovery/source" in workflow
    assert "recovery/source/authorized-release" in workflow
    assert "release_gate/genesis/finalize_gate.py" in workflow
