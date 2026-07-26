from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest

from release_gate.genesis.verify_no_prior_release import inspect_history, inspect_releases

ROOT = Path(__file__).resolve().parents[1]
SELFTEST_CASES = {"resize_ppi", "background", "halftone", "vector", "history_lineage", "export"}
AUTH_WORKFLOWS = {
    "ImageLab Zero-Trust Release Gate",
    "ImageLab Genesis First Release Gate",
    "ImageLab Genesis Request Gate",
}
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


def _h(character: str) -> str:
    return character * 64


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


def _asset(
    asset_id: str,
    original_name: str,
    format_name: str,
    seed: str,
    *,
    source_asset_id: str | None = None,
    operation: str | None = None,
) -> dict[str, object]:
    upload_sha = _h(seed)
    asset = {
        "id": asset_id,
        "original_name": original_name,
        "stored_name": f"{asset_id}.{format_name.lower()}",
        "preview_name": f"{asset_id}.preview.png",
        "format": format_name,
        "record_sha256": upload_sha,
        "upload_file_sha256": upload_sha,
        "upload_size_bytes": 1024,
        "preview_file_sha256": _h(chr(ord(seed) + 1)),
        "preview_size_bytes": 512,
        "source_asset_id": source_asset_id,
        "operation": operation,
        "parameters_sha256": _h(chr(ord(seed) + 2)),
        "ai_sha256": _h(chr(ord(seed) + 3)),
    }
    if format_name == "SVG":
        asset["preview_file_sha256"] = None
        asset["preview_size_bytes"] = None
    return asset


def _inventory() -> dict[str, object]:
    default_asset = _asset("asset-default", "default.png", "PNG", "1")
    raster_source = _asset("asset-raster-source", "raster.png", "PNG", "5")
    raster_derived = _asset(
        "asset-raster-derived",
        "raster-clean.png",
        "PNG",
        "9",
        source_asset_id="asset-raster-source",
        operation="cleanup",
    )
    svg_asset = _asset("asset-svg", "vector.svg", "SVG", "d")
    projects = [
        {
            "project_id": "TS-001",
            "title": "Default project",
            "project_file_sha256": _h("a"),
            "workspace_sha256": _h("b"),
            "presets_sha256": _h("c"),
            "active_asset_id": "asset-default",
            "active_revision": 1,
            "asset_count": 1,
            "assets": [default_asset],
        },
        {
            "project_id": "ZTR-RASTER-PROJECT",
            "title": "Raster lineage project",
            "project_file_sha256": _h("e"),
            "workspace_sha256": _h("f"),
            "presets_sha256": _h("0"),
            "active_asset_id": "asset-raster-derived",
            "active_revision": 2,
            "asset_count": 2,
            "assets": [raster_source, raster_derived],
        },
        {
            "project_id": "ZTR-SVG-PROJECT",
            "title": "SVG project",
            "project_file_sha256": _h("2"),
            "workspace_sha256": _h("3"),
            "presets_sha256": _h("4"),
            "active_asset_id": "asset-svg",
            "active_revision": 1,
            "asset_count": 1,
            "assets": [svg_asset],
        },
    ]
    return {
        "schema": 1,
        "project_count": 3,
        "asset_count": 4,
        "projects_sha256": _h("8"),
        "projects": projects,
    }


def _write_g7_bundle(
    root: Path,
    installer_sha: str,
    source_sha: str,
    *,
    mutate: Callable[[dict[str, object], dict[str, object]], None] | None = None,
) -> str:
    directory = root / "g7"
    directory.mkdir(parents=True, exist_ok=True)
    bundle = directory / "ImageLab-GENESIS-G7-EVIDENCE.zip"
    before = _inventory()
    after_update = copy.deepcopy(before)
    rollback_before = copy.deepcopy(after_update)
    after_rollback = copy.deepcopy(before)
    baseline_sha = _h("b")
    update: dict[str, object] = {
        "schema": 3,
        "status": "PASS",
        "installer_sha256": installer_sha,
        "baseline_installer_sha256": baseline_sha,
        "baseline_version": "9.9.8-diagnostic",
        "baseline_build_id": "DIAGNOSTIC-BASELINE",
        "first_install_id": "baseline-install",
        "second_install_id": "candidate-install",
        "second_url": "http://127.0.0.1:8765",
        "old_process_stopped": True,
        "project_data_preserved": True,
        "sentinel_preserved": True,
        "project_count": 3,
        "asset_count": 4,
        "project_inventory_before": before,
        "project_inventory_after_update": after_update,
    }
    rollback: dict[str, object] = {
        "schema": 3,
        "status": "PASS",
        "installer_sha256": installer_sha,
        "restored_install_id": "candidate-install",
        "expected_install_id": "candidate-install",
        "restored_url": "http://127.0.0.1:8765",
        "fault_exit_code": 1,
        "critical_hashes_restored": True,
        "project_data_preserved": True,
        "sentinel_preserved": True,
        "project_count": 3,
        "asset_count": 4,
        "project_inventory_before": rollback_before,
        "project_inventory_after_rollback": after_rollback,
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
        "outputs": [{"name": "physical-output.png", "sha256": _h("f"), "validator_status": "PASS"}],
        "direct_witness": {
            "name": "Dmitry",
            "confirmed": True,
            "statement": "Dmitry directly witnessed the complete installed browser user path.",
            "witnessed_at": timestamp,
        },
    }


def _clean_history() -> dict[str, object]:
    return {
        "schema": 3,
        "status": "PASS",
        "release_mode": "genesis_first_release",
        "protocol_rule": "GENESIS-FIRST-RELEASE-V1",
        "repository": "owner/repo",
        "query_source": "github_api_releases_all_authorization_runs_artifacts_paginated",
        "query_complete": True,
        "current_run_id": GENESIS_RUN_ID,
        "authorization_workflow_names": sorted(AUTH_WORKFLOWS),
        "release_count_scanned": 3,
        "workflow_run_count_scanned": 0,
        "artifact_count_scanned": 0,
        "authorized_installer_asset_count": 0,
        "authorization_record_asset_count": 0,
        "prior_successful_authorization_run_count": 0,
        "prior_authorized_artifact_count": 0,
        "prior_successful_authorization_runs": [],
        "prior_authorized_artifacts": [],
        "matching_assets": [],
    }


def _build_evidence(root: Path) -> tuple[str, str, str]:
    version = "9.9.9-genesis-test"
    build_id = "GENESIS-TEST"
    source_sha = _h("c")
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

    _write(root / "genesis/genesis-baseline-verification.json", _clean_history())
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
        "ImageLab_by_LarannA_RELEASE_AUTHORIZED_Setup_x64.exe",
        "ImageLab_by_LarannA_GENESIS_RELEASE_AUTHORIZED_Setup_x64.exe",
    ):
        blocked = inspect_releases([{"tag_name": "v1", "assets": [{"name": name}]}], "owner/repo")
        assert blocked["status"] == "FAIL"


@pytest.mark.parametrize("workflow_name", sorted(AUTH_WORKFLOWS))
def test_release_absence_verifier_blocks_success_from_every_authorization_workflow(workflow_name: str) -> None:
    result = inspect_history(
        [],
        [{"workflow_runs": [{"id": 10, "name": workflow_name, "conclusion": "success", "head_sha": "a" * 40}]}],
        [],
        "owner/repo",
        GENESIS_RUN_ID,
    )
    assert result["status"] == "FAIL"
    assert result["prior_successful_authorization_run_count"] == 1


@pytest.mark.parametrize("artifact_name", ["ImageLab-RELEASE-AUTHORIZED", "ImageLab-GENESIS-RELEASE-AUTHORIZED"])
@pytest.mark.parametrize("expired", [False, True])
def test_release_absence_verifier_blocks_normal_genesis_and_expired_artifacts(
    artifact_name: str, expired: bool
) -> None:
    result = inspect_history(
        [],
        [],
        [{"artifacts": [{"id": 20, "name": artifact_name, "expired": expired, "workflow_run": {"id": 10}}]}],
        "owner/repo",
        GENESIS_RUN_ID,
    )
    assert result["status"] == "FAIL"
    assert result["prior_authorized_artifact_count"] == 1
    assert result["prior_authorized_artifacts"][0]["expired"] is expired


def test_release_absence_verifier_excludes_current_run_and_unrelated_workflows() -> None:
    result = inspect_history(
        [],
        [
            {
                "workflow_runs": [
                    {"id": GENESIS_RUN_ID, "name": "ImageLab Genesis First Release Gate", "conclusion": "success"},
                    {"id": 99, "name": "ImageLab Evidence Hardening CI", "conclusion": "success"},
                ]
            }
        ],
        [],
        "owner/repo",
        GENESIS_RUN_ID,
    )
    assert result["status"] == "PASS"
    assert result["prior_successful_authorization_run_count"] == 0


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
    assert list(output.glob("*GENESIS_RELEASE_AUTHORIZED*_Setup_x64.exe"))
    assert not (output / "ImageLab-RELEASE-AUTHORIZATION.json").exists()
    assert not list(output.glob("ImageLab_by_LarannA_RELEASE_AUTHORIZED*_Setup_x64.exe"))


def test_genesis_finalizer_requires_exact_pinned_g7_bundle(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _, physical_sha, _ = _build_evidence(evidence)
    result, verdict = _run(evidence, tmp_path / "output", physical_sha, _h("f"))
    assert result.returncode != 0
    assert "g7_bundle_pinned_sha_mismatch" in verdict["failed_conditions"]


@pytest.mark.parametrize("status", ["FAIL", "NOT_APPLICABLE_FIRST_RELEASE"])
def test_genesis_finalizer_rejects_failed_or_na_g7(tmp_path: Path, status: str) -> None:
    evidence = tmp_path / status
    installer_sha, physical_sha, _ = _build_evidence(evidence)
    source_sha = json.loads((evidence / "build/candidate-manifest.json").read_text("utf-8"))["source"]["sha256"]
    g7_sha = _write_g7_bundle(
        evidence,
        installer_sha,
        source_sha,
        mutate=lambda _update, rollback: rollback.update(status=status),
    )
    result, verdict = _run(evidence, tmp_path / f"output-{status}", physical_sha, g7_sha)
    assert result.returncode != 0
    assert "g7_rollback_status" in verdict["failed_conditions"]


def test_genesis_finalizer_rejects_current_candidate_as_g7_baseline(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    installer_sha, physical_sha, _ = _build_evidence(evidence)
    source_sha = json.loads((evidence / "build/candidate-manifest.json").read_text("utf-8"))["source"]["sha256"]
    bundle = evidence / "g7/ImageLab-GENESIS-G7-EVIDENCE.zip"
    _write_g7_bundle(evidence, installer_sha, source_sha)
    with zipfile.ZipFile(bundle) as archive:
        update = json.loads(archive.read("genesis-g7/update-test.json"))
        rollback = json.loads(archive.read("genesis-g7/rollback-test.json"))
    update["baseline_installer_sha256"] = installer_sha
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


@pytest.mark.parametrize(
    "label,mutator",
    [
        (
            "project_json_sha",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][0].pop("project_file_sha256"),
        ),
        (
            "workspace_sha",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][0].update(workspace_sha256="x"),
        ),
        (
            "preset_sha",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][1].update(presets_sha256="x"),
        ),
        (
            "active_asset",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][0].update(active_asset_id="missing"),
        ),
        (
            "active_revision",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][0].update(active_revision=-1),
        ),
        (
            "asset_file_sha",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][0]["assets"][0].update(
                upload_file_sha256=_h("0")
            ),
        ),
        (
            "asset_size",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][0]["assets"][0].update(
                upload_size_bytes=0
            ),
        ),
        (
            "asset_format",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][2]["assets"][0].update(format="JPEG"),
        ),
        (
            "preview_sha",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][0]["assets"][0].update(
                preview_file_sha256="x"
            ),
        ),
        (
            "lineage",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][1]["assets"][1].update(
                source_asset_id="missing"
            ),
        ),
        (
            "operation",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][1]["assets"][1].update(
                operation="vectorize"
            ),
        ),
        (
            "parameters_sha",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][1]["assets"][1].update(
                parameters_sha256="x"
            ),
        ),
        (
            "ai_sha",
            lambda _u, r: r["project_inventory_after_rollback"]["projects"][1]["assets"][1].update(ai_sha256="x"),
        ),
    ],
)
def test_genesis_g7_rejects_project_and_asset_inventory_mutation(
    tmp_path: Path,
    label: str,
    mutator: Callable[[dict[str, object], dict[str, object]], None],
) -> None:
    evidence = tmp_path / label
    installer_sha, physical_sha, _ = _build_evidence(evidence)
    source_sha = json.loads((evidence / "build/candidate-manifest.json").read_text("utf-8"))["source"]["sha256"]
    g7_sha = _write_g7_bundle(evidence, installer_sha, source_sha, mutate=mutator)
    result, verdict = _run(evidence, tmp_path / f"output-{label}", physical_sha, g7_sha)
    assert result.returncode != 0
    assert verdict["gates"]["G7_rollback_to_prior_authorized_release"] == "FAIL"
    assert any(
        marker in condition
        for condition in verdict["failed_conditions"]
        for marker in ("inventory_", "project_inventory_", "data_inventory_", "project_transition_")
    )


@pytest.mark.parametrize("field", ["second_url", "restored_url"])
def test_genesis_g7_requires_runnable_update_and_rollback(field: str, tmp_path: Path) -> None:
    evidence = tmp_path / field
    installer_sha, physical_sha, _ = _build_evidence(evidence)
    source_sha = json.loads((evidence / "build/candidate-manifest.json").read_text("utf-8"))["source"]["sha256"]

    def mutate(update: dict[str, object], rollback: dict[str, object]) -> None:
        (update if field == "second_url" else rollback)[field] = "https://example.invalid/not-loopback"

    g7_sha = _write_g7_bundle(evidence, installer_sha, source_sha, mutate=mutate)
    result, verdict = _run(evidence, tmp_path / f"output-{field}", physical_sha, g7_sha)
    assert result.returncode != 0
    expected = "g7_update_candidate_not_runnable" if field == "second_url" else "g7_rollback_restored_candidate_not_runnable"
    assert expected in verdict["failed_conditions"]


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
    result, _ = _run(evidence, output, _h("f"), g7_sha)
    assert result.returncode != 0
    assert all(not path.exists() for path in stale_files)


def test_genesis_workflow_queries_all_authorization_paths_and_requires_g7() -> None:
    workflow = (ROOT / ".github/workflows/zero-trust-genesis-release.yml").read_text("utf-8")
    assert 'actions/runs?per_page=100' in workflow
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
