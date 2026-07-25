from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SELFTEST_CASES = {
    "resize_ppi",
    "background",
    "halftone",
    "vector",
    "history_lineage",
    "export",
}
PHYSICAL_L5_STEPS = {"upload", "operation", "history", "export"}
PHYSICAL_L5_MAX_AGE = timedelta(hours=72)
PHYSICAL_L5_MAX_BYTES = 1024 * 1024
INVENTORY_MIN_PROJECTS = 3
INVENTORY_MIN_ASSETS = 3


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text.lower())


def read_optional(path: Path, missing: list[str]) -> dict[str, Any]:
    if not path.exists():
        missing.append(path.as_posix())
        return {"status": "MISSING", "evidence_path": path.as_posix()}
    try:
        value = json.loads(path.read_text("utf-8-sig"))
        if not isinstance(value, dict):
            raise TypeError("top-level JSON evidence must be an object")
        return value
    except Exception as exc:
        missing.append(f"{path.as_posix()}:malformed:{type(exc).__name__}")
        return {
            "status": "MALFORMED",
            "evidence_path": path.as_posix(),
            "error": str(exc),
        }


def read_physical(path: Path, missing: list[str]) -> dict[str, Any]:
    if not path.exists():
        missing.append(path.as_posix())
        return {"status": "MISSING", "evidence_path": path.as_posix()}
    try:
        if path.stat().st_size > PHYSICAL_L5_MAX_BYTES:
            raise ValueError("physical L5 record exceeds 1 MiB")
        value = json.loads(path.read_text("utf-8-sig"))
        if not isinstance(value, dict):
            raise TypeError("top-level physical L5 JSON must be an object")
        return value
    except Exception as exc:
        missing.append(f"{path.as_posix()}:malformed:{type(exc).__name__}")
        return {
            "status": "MALFORMED",
            "evidence_path": path.as_posix(),
            "error": str(exc),
        }


def parse_utc_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def clear_authorized_outputs(output: Path) -> None:
    patterns = (
        "*RELEASE_AUTHORIZED*.exe",
        "*GENESIS_RELEASE_AUTHORIZED*.exe",
        "ImageLab-RELEASE-AUTHORIZATION.json",
        "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json",
        "installer-sha256.txt",
    )
    for pattern in patterns:
        for path in output.glob(pattern):
            if path.is_file():
                path.unlink(missing_ok=True)


def validate_selftest(
    name: str,
    data: dict[str, Any],
    *,
    candidate_identity: dict[str, Any],
    install_evidence: dict[str, Any],
    failed: list[str],
) -> None:
    if data.get("schema") != 1:
        failed.append(f"selftest_schema:{name}")

    expected_identity = {
        "app": candidate_identity.get("app"),
        "version": candidate_identity.get("version"),
        "build_id": candidate_identity.get("build_id"),
        "install_id": install_evidence.get("install_id"),
    }
    for field, expected in expected_identity.items():
        if not expected or data.get(field) != expected:
            failed.append(f"selftest_identity_mismatch:{name}:{field}")

    tests = data.get("tests")
    if not isinstance(tests, dict):
        failed.append(f"selftest_cases_missing:{name}")
        return
    if set(tests) != SELFTEST_CASES:
        failed.append(f"selftest_case_set_mismatch:{name}")
    for case_name in SELFTEST_CASES:
        case = tests.get(case_name)
        if not isinstance(case, dict) or case.get("status") != "PASS":
            failed.append(f"selftest_case_failed:{name}:{case_name}")


def _validate_inventory_asset(
    name: str,
    asset: object,
    *,
    failed: list[str],
) -> dict[str, Any]:
    if not isinstance(asset, dict):
        failed.append(f"inventory_asset_invalid:{name}")
        return {}
    for field in ("id", "stored_name", "preview_name", "format", "original_name"):
        if not isinstance(asset.get(field), str) or not str(asset.get(field)).strip():
            failed.append(f"inventory_asset_field:{name}:{field}")
    for field in (
        "record_sha256",
        "upload_file_sha256",
        "parameters_sha256",
        "ai_sha256",
    ):
        if not valid_sha256(asset.get(field)):
            failed.append(f"inventory_asset_sha:{name}:{field}")
    if asset.get("record_sha256") != asset.get("upload_file_sha256"):
        failed.append(f"inventory_asset_record_file_mismatch:{name}")
    size = asset.get("upload_size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        failed.append(f"inventory_asset_size:{name}")
    if asset.get("format") != "SVG":
        if not valid_sha256(asset.get("preview_file_sha256")):
            failed.append(f"inventory_preview_sha:{name}")
        preview_size = asset.get("preview_size_bytes")
        if isinstance(preview_size, bool) or not isinstance(preview_size, int) or preview_size <= 0:
            failed.append(f"inventory_preview_size:{name}")
    return asset


def _validate_inventory_project(
    name: str,
    project: object,
    *,
    failed: list[str],
) -> dict[str, Any]:
    if not isinstance(project, dict):
        failed.append(f"inventory_project_invalid:{name}")
        return {}
    for field in ("project_id", "title"):
        if not isinstance(project.get(field), str) or not str(project.get(field)).strip():
            failed.append(f"inventory_project_field:{name}:{field}")
    for field in ("project_file_sha256", "workspace_sha256", "presets_sha256"):
        if not valid_sha256(project.get(field)):
            failed.append(f"inventory_project_sha:{name}:{field}")
    assets = project.get("assets")
    if not isinstance(assets, list):
        failed.append(f"inventory_project_assets_missing:{name}")
        assets = []
    if project.get("asset_count") != len(assets):
        failed.append(f"inventory_project_asset_count:{name}")
    validated = [
        _validate_inventory_asset(f"{name}:{index}", asset, failed=failed)
        for index, asset in enumerate(assets)
    ]
    asset_ids = [str(asset.get("id", "")) for asset in validated if asset]
    if len(asset_ids) != len(set(asset_ids)):
        failed.append(f"inventory_project_duplicate_assets:{name}")
    active = project.get("active_asset_id")
    if active is not None and active not in asset_ids:
        failed.append(f"inventory_project_active_asset:{name}")
    by_id = {str(asset.get("id")): asset for asset in validated if asset.get("id")}
    for asset in validated:
        source_id = asset.get("source_asset_id")
        if source_id is not None and source_id not in by_id:
            failed.append(f"inventory_project_lineage:{name}:{asset.get('id')}")
    revision = project.get("active_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        failed.append(f"inventory_project_revision:{name}")
    return project


def validate_data_inventory(
    name: str,
    inventory: object,
    *,
    failed: list[str],
) -> dict[str, Any]:
    if not isinstance(inventory, dict):
        failed.append(f"data_inventory_missing:{name}")
        return {}
    if inventory.get("schema") != 1:
        failed.append(f"data_inventory_schema:{name}")
    if not valid_sha256(inventory.get("projects_sha256")):
        failed.append(f"data_inventory_sha:{name}")
    projects = inventory.get("projects")
    if not isinstance(projects, list):
        failed.append(f"data_inventory_projects_missing:{name}")
        projects = []
    if inventory.get("project_count") != len(projects):
        failed.append(f"data_inventory_project_count:{name}")
    if len(projects) < INVENTORY_MIN_PROJECTS:
        failed.append(f"data_inventory_project_coverage:{name}")
    validated_projects = [
        _validate_inventory_project(f"{name}:{index}", project, failed=failed)
        for index, project in enumerate(projects)
    ]
    project_ids = [str(project.get("project_id", "")) for project in validated_projects if project]
    if project_ids != sorted(project_ids):
        failed.append(f"data_inventory_project_order:{name}")
    if len(project_ids) != len(set(project_ids)):
        failed.append(f"data_inventory_duplicate_projects:{name}")
    asset_count = sum(
        int(project.get("asset_count", 0))
        for project in validated_projects
        if isinstance(project.get("asset_count"), int)
        and not isinstance(project.get("asset_count"), bool)
    )
    if inventory.get("asset_count") != asset_count:
        failed.append(f"data_inventory_asset_count:{name}")
    if asset_count < INVENTORY_MIN_ASSETS:
        failed.append(f"data_inventory_asset_coverage:{name}")
    formats = {
        str(asset.get("format"))
        for project in validated_projects
        for asset in project.get("assets", [])
        if isinstance(asset, dict)
    }
    if not {"PNG", "SVG"}.issubset(formats):
        failed.append(f"data_inventory_format_coverage:{name}")
    derived = [
        asset
        for project in validated_projects
        for asset in project.get("assets", [])
        if isinstance(asset, dict) and asset.get("source_asset_id")
    ]
    if not derived:
        failed.append(f"data_inventory_history_coverage:{name}")
    non_empty_presets = [
        project
        for project in validated_projects
        if project.get("asset_count", 0) > 0 and project.get("presets_sha256")
    ]
    if len(non_empty_presets) < 2:
        failed.append(f"data_inventory_preset_coverage:{name}")
    active_values = {
        project.get("active_asset_id")
        for project in validated_projects
        if project.get("active_asset_id") is not None
    }
    if len(active_values) < 2:
        failed.append(f"data_inventory_active_selection_coverage:{name}")
    return inventory


def validate_project_transition(
    name: str,
    data: dict[str, Any],
    *,
    failed: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if data.get("schema") != 3:
        failed.append(f"project_transition_schema:{name}")
    if data.get("project_data_preserved") is not True:
        failed.append(f"project_data_not_preserved:{name}")
    before_key = "project_inventory_before"
    after_key = (
        "project_inventory_after_update"
        if name == "update"
        else "project_inventory_after_rollback"
    )
    before = validate_data_inventory(
        f"{name}:before", data.get(before_key), failed=failed
    )
    after = validate_data_inventory(
        f"{name}:after", data.get(after_key), failed=failed
    )
    if before and after and before != after:
        failed.append(f"project_inventory_mismatch:{name}")
    if data.get("project_count") != before.get("project_count"):
        failed.append(f"project_transition_project_count:{name}")
    if data.get("asset_count") != before.get("asset_count"):
        failed.append(f"project_transition_asset_count:{name}")

    if name == "update":
        if data.get("old_process_stopped") is not True:
            failed.append("update_old_process_not_stopped")
        first_install_id = str(data.get("first_install_id", ""))
        second_install_id = str(data.get("second_install_id", ""))
        if not first_install_id or not second_install_id or first_install_id == second_install_id:
            failed.append("update_install_identity_not_changed")
    else:
        if data.get("critical_hashes_restored") is not True:
            failed.append("rollback_critical_hashes_not_restored")
        restored = str(data.get("restored_install_id", ""))
        expected = str(data.get("expected_install_id", ""))
        if not restored or restored != expected:
            failed.append("rollback_install_identity_not_restored")
        fault_exit = data.get("fault_exit_code")
        if isinstance(fault_exit, bool) or not isinstance(fault_exit, int) or fault_exit == 0:
            failed.append("rollback_fault_not_observed")
    return before, after


def validate_physical_l5(
    data: dict[str, Any],
    *,
    record_path: Path,
    expected_record_sha256: str,
    candidate: dict[str, Any],
    installer_name: str,
    installer_sha256: str,
    clean_install_id: str,
    independent_install_id: str,
    failed: list[str],
) -> dict[str, Any]:
    if not expected_record_sha256:
        failed.append("physical_l5_sha_pin_missing")
    elif not valid_sha256(expected_record_sha256):
        failed.append("physical_l5_sha_pin_invalid")
    elif record_path.exists() and sha256(record_path) != expected_record_sha256.lower():
        failed.append("physical_l5_sha_pin_mismatch")

    if data.get("schema") != 1:
        failed.append("physical_l5_schema")
    if data.get("status") != "PASS":
        failed.append("physical_l5_status")
    if data.get("execution_environment") != "physical_user_windows":
        failed.append("physical_l5_environment")
    if data.get("hosted_runner") is not False:
        failed.append("physical_l5_hosted_runner")

    identity = candidate.get("identity") if isinstance(candidate.get("identity"), dict) else {}
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    candidate_record = data.get("candidate")
    if not isinstance(candidate_record, dict):
        failed.append("physical_l5_candidate_missing")
        candidate_record = {}
    expected_candidate = {
        "source_sha256": source.get("sha256"),
        "installer_name": installer_name,
        "installer_sha256": installer_sha256,
        "version": identity.get("version"),
        "build_id": identity.get("build_id"),
    }
    for field, expected in expected_candidate.items():
        if not expected or candidate_record.get(field) != expected:
            failed.append(f"physical_l5_identity_mismatch:{field}")

    physical_install_id = str(candidate_record.get("install_id", "")).strip()
    if not physical_install_id:
        failed.append("physical_l5_install_id_missing")
    if physical_install_id in {clean_install_id, independent_install_id}:
        failed.append("physical_l5_reused_hosted_install_id")

    executed_at = parse_utc_timestamp(data.get("executed_at"))
    now = datetime.now(timezone.utc)
    if executed_at is None:
        failed.append("physical_l5_timestamp_invalid")
    else:
        if executed_at > now + timedelta(minutes=5):
            failed.append("physical_l5_timestamp_future")
        if now - executed_at > PHYSICAL_L5_MAX_AGE:
            failed.append("physical_l5_timestamp_stale")

    scenario = data.get("scenario")
    if not isinstance(scenario, dict):
        failed.append("physical_l5_scenario_missing")
        scenario = {}
    if scenario.get("browser_driven") is not True:
        failed.append("physical_l5_browser_not_verified")
    steps = scenario.get("steps")
    if not isinstance(steps, dict):
        failed.append("physical_l5_steps_missing")
        steps = {}
    for step in sorted(PHYSICAL_L5_STEPS):
        value = steps.get(step)
        status = value.get("status") if isinstance(value, dict) else value
        if status != "PASS":
            failed.append(f"physical_l5_step_failed:{step}")

    outputs = data.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        failed.append("physical_l5_outputs_missing")
        outputs = []
    seen_names: set[str] = set()
    for index, output in enumerate(outputs):
        if not isinstance(output, dict):
            failed.append(f"physical_l5_output_invalid:{index}")
            continue
        name = str(output.get("name", "")).strip()
        if not name or name in seen_names:
            failed.append(f"physical_l5_output_name:{index}")
        seen_names.add(name)
        if not valid_sha256(output.get("sha256")):
            failed.append(f"physical_l5_output_sha:{index}")
        if output.get("validator_status") != "PASS":
            failed.append(f"physical_l5_output_validator:{index}")

    witness = data.get("direct_witness")
    if not isinstance(witness, dict):
        failed.append("physical_l5_witness_missing")
        witness = {}
    witness_name = str(witness.get("name", "")).strip().casefold()
    if witness_name not in {"dmitry", "дмитрий"}:
        failed.append("physical_l5_witness_identity")
    if witness.get("confirmed") is not True:
        failed.append("physical_l5_witness_not_confirmed")
    if len(str(witness.get("statement", "")).strip()) < 20:
        failed.append("physical_l5_witness_statement_missing")
    witnessed_at = parse_utc_timestamp(witness.get("witnessed_at"))
    if witnessed_at is None:
        failed.append("physical_l5_witness_timestamp_invalid")
    elif executed_at is not None and abs((witnessed_at - executed_at).total_seconds()) > 24 * 3600:
        failed.append("physical_l5_witness_timestamp_mismatch")

    return {
        "status": data.get("status", "MISSING"),
        "record_sha256": sha256(record_path) if record_path.exists() else None,
        "install_id": physical_install_id or None,
        "executed_at": data.get("executed_at"),
        "witness": witness.get("name"),
        "provenance_limit": "independently SHA-pinned witness record; not cryptographic proof of physical provenance",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--physical-l5-record", type=Path)
    parser.add_argument("--physical-l5-sha256", default="")
    args = parser.parse_args()
    root = args.aggregate_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    clear_authorized_outputs(output)
    verdict_path = output / "final-verdict.json"

    missing_evidence: list[str] = []
    try:
        source = read_optional(root / "source" / "source-gate.json", missing_evidence)
        unit = read_optional(root / "unit" / "unit-matrix-verdict.json", missing_evidence)
        candidate = read_optional(root / "build" / "candidate-manifest.json", missing_evidence)
        reproducibility = read_optional(root / "build" / "reproducibility.json", missing_evidence)
        clean = read_optional(root / "clean" / "clean-install.json", missing_evidence)
        clean_pre = read_optional(root / "clean" / "preinstall-selftest.json", missing_evidence)
        clean_post = read_optional(root / "clean" / "postinstall-selftest.json", missing_evidence)
        ui = read_optional(root / "clean" / "ui-gate.json", missing_evidence)
        outputs = read_optional(root / "clean" / "output-validation.json", missing_evidence)
        baseline = read_optional(root / "update" / "baseline-verification.json", missing_evidence)
        update = read_optional(root / "update" / "update-test.json", missing_evidence)
        rollback = read_optional(root / "update" / "rollback-test.json", missing_evidence)
        independent = read_optional(root / "independent" / "independent-verification.json", missing_evidence)
        independent_pre = read_optional(root / "independent" / "preinstall-selftest.json", missing_evidence)
        independent_post = read_optional(root / "independent" / "postinstall-selftest.json", missing_evidence)
        independent_ui = read_optional(root / "independent" / "ui-gate.json", missing_evidence)
        independent_outputs = read_optional(root / "independent" / "output-validation.json", missing_evidence)
        physical_path = (
            args.physical_l5_record.resolve()
            if args.physical_l5_record is not None
            else root / "physical" / "physical-l5.json"
        )
        physical = read_physical(physical_path, missing_evidence)

        required = {
            "G0_source": source,
            "G1_unit_matrix": unit,
            "G2_candidate": candidate,
            "G2_reproducibility": reproducibility,
            "G3_clean_install": clean,
            "G3_preinstall_selftest": clean_pre,
            "G3_postinstall_selftest": clean_post,
            "G4_browser_ui": ui,
            "G5_output_validation": outputs,
            "G6_baseline_pinned": baseline,
            "G6_update": update,
            "G7_rollback": rollback,
            "G8_independent": independent,
            "G8_preinstall_selftest": independent_pre,
            "G8_postinstall_selftest": independent_post,
            "G8_independent_ui": independent_ui,
            "G8_independent_outputs": independent_outputs,
            "L5_physical_user_machine": physical,
        }
        failed = [name for name, data in required.items() if data.get("status") != "PASS"]
        if missing_evidence:
            failed.append("required_evidence_missing_or_malformed")

        installer_info = candidate.get("installer") if isinstance(candidate.get("installer"), dict) else {}
        installer_sha = str(installer_info.get("sha256", ""))
        installer_name = str(installer_info.get("name", "")).strip()
        if not valid_sha256(installer_sha):
            failed.append("candidate_installer_sha")
        if not installer_name or Path(installer_name).name != installer_name or not installer_name.endswith(".exe"):
            failed.append("candidate_installer_name")

        repro_sha = str(reproducibility.get("installer_sha256", ""))
        second_sha = str(reproducibility.get("second_build_sha256", ""))
        if installer_sha and (repro_sha != installer_sha or second_sha != installer_sha):
            failed.append("candidate_reproducibility_sha_mismatch")

        for name, data in required.items():
            observed = data.get("installer_sha256")
            if observed is not None and name != "G6_baseline_pinned" and observed != installer_sha:
                failed.append(f"sha_mismatch:{name}")

        baseline_sha = str(baseline.get("installer_sha256", ""))
        update_baseline_sha = str(update.get("baseline_installer_sha256", ""))
        if baseline.get("schema") != 3:
            failed.append("baseline_evidence_schema")
        if baseline.get("release_authorized") is not True:
            failed.append("baseline_not_release_authorized")
        if baseline.get("authorization_source") != "prior_finalizer_record":
            failed.append("baseline_authorization_source_invalid")
        if baseline.get("authorization_record_status") not in {
            "RELEASE_AUTHORIZED",
            "GENESIS_RELEASE_AUTHORIZED",
        }:
            failed.append("baseline_authorization_record_status")
        authorization_record_sha = str(baseline.get("authorization_record_sha256", ""))
        if not valid_sha256(authorization_record_sha):
            failed.append("baseline_authorization_record_sha")
        release_tag = str(baseline.get("release_tag", "")).strip()
        baseline_name = str(baseline.get("name", "")).strip()
        if not release_tag:
            failed.append("baseline_release_tag_missing")
        if "RELEASE_AUTHORIZED" not in baseline_name or not baseline_name.endswith("_Setup_x64.exe"):
            failed.append("baseline_authorized_asset_name_invalid")
        if baseline.get("authorization_record_installer_name") != baseline_name:
            failed.append("baseline_authorization_record_name_mismatch")
        if not valid_sha256(baseline_sha):
            failed.append("baseline_installer_sha")
        if baseline.get("authorization_record_installer_sha256") != baseline_sha:
            failed.append("baseline_authorization_record_installer_sha_mismatch")
        if baseline_sha and update_baseline_sha and baseline_sha != update_baseline_sha:
            failed.append("baseline_sha_mismatch:update")
        if baseline_sha and baseline_sha == installer_sha:
            failed.append("baseline_must_differ_from_candidate")

        candidate_identity = candidate.get("identity")
        if not isinstance(candidate_identity, dict):
            candidate_identity = {}
            failed.append("candidate_identity_missing")
        validate_selftest(
            "G3_preinstall_selftest",
            clean_pre,
            candidate_identity=candidate_identity,
            install_evidence=clean,
            failed=failed,
        )
        validate_selftest(
            "G3_postinstall_selftest",
            clean_post,
            candidate_identity=candidate_identity,
            install_evidence=clean,
            failed=failed,
        )
        validate_selftest(
            "G8_preinstall_selftest",
            independent_pre,
            candidate_identity=candidate_identity,
            install_evidence=independent,
            failed=failed,
        )
        validate_selftest(
            "G8_postinstall_selftest",
            independent_post,
            candidate_identity=candidate_identity,
            install_evidence=independent,
            failed=failed,
        )

        update_before, update_after = validate_project_transition(
            "update", update, failed=failed
        )
        rollback_before, rollback_after = validate_project_transition(
            "rollback", rollback, failed=failed
        )
        if update_after and rollback_before and update_after != rollback_before:
            failed.append("project_inventory_handoff_mismatch:update_rollback")
        if update_before and rollback_after and update_before != rollback_after:
            failed.append("project_inventory_end_to_end_mismatch")

        physical_summary = validate_physical_l5(
            physical,
            record_path=physical_path,
            expected_record_sha256=str(args.physical_l5_sha256).lower(),
            candidate=candidate,
            installer_name=installer_name,
            installer_sha256=installer_sha,
            clean_install_id=str(clean.get("install_id", "")),
            independent_install_id=str(independent.get("install_id", "")),
            failed=failed,
        )

        installer_candidates = list((root / "build").glob("*.exe")) if (root / "build").exists() else []
        if len(installer_candidates) != 1:
            failed.append("exact_installer_missing_or_ambiguous")
            installer = None
        else:
            installer = installer_candidates[0]
            if installer.name != installer_name:
                failed.append("exact_installer_binary_name_mismatch")
            if not installer_sha or sha256(installer) != installer_sha:
                failed.append("exact_installer_binary_sha_mismatch")

        evidence_files = [path for path in root.rglob("*") if path.is_file()] if root.exists() else []
        if physical_path.exists() and physical_path not in evidence_files:
            evidence_files.append(physical_path)
        if len(evidence_files) < 18:
            failed.append("evidence_bundle_incomplete")

        status = "RELEASE_AUTHORIZED" if not failed else "RELEASE_BLOCKED"
        verdict = {
            "schema": 5,
            "status": status,
            "installer_sha256": installer_sha,
            "identity": candidate.get("identity"),
            "source_sha256": candidate.get("source", {}).get("sha256")
            if isinstance(candidate.get("source"), dict)
            else None,
            "gates": {name: data.get("status") for name, data in required.items()},
            "physical_l5": physical_summary,
            "project_inventory": {
                "project_count": update_before.get("project_count"),
                "asset_count": update_before.get("asset_count"),
                "projects_sha256": update_before.get("projects_sha256"),
            },
            "failed_conditions": sorted(set(failed)),
            "missing_or_malformed_evidence": sorted(set(missing_evidence)),
            "evidence_file_count": len(evidence_files),
        }
        verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), "utf-8")

        archive_path = output / "release-evidence.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(set(evidence_files)):
                if path.is_relative_to(root):
                    archive_name = path.relative_to(root).as_posix()
                else:
                    archive_name = f"physical/{path.name}"
                archive.write(path, archive_name)
            archive.write(verdict_path, "final-verdict.json")

        if status == "RELEASE_AUTHORIZED" and installer is not None:
            authorized = output / installer.name.replace("ZERO_TRUST", "RELEASE_AUTHORIZED")
            shutil.copy2(installer, authorized)
            (output / "installer-sha256.txt").write_text(
                f"{installer_sha}  {authorized.name}\n", "utf-8"
            )
            authorization_record = {
                "schema": 3,
                "status": "RELEASE_AUTHORIZED",
                "authorization_source": "finalize_gate.py",
                "installer_name": authorized.name,
                "installer_sha256": installer_sha,
                "source_sha256": verdict.get("source_sha256"),
                "identity": candidate.get("identity"),
                "physical_l5_evidence_sha256": physical_summary.get("record_sha256"),
                "physical_l5_install_id": physical_summary.get("install_id"),
                "project_inventory_sha256": update_before.get("projects_sha256"),
                "final_verdict_sha256": sha256(verdict_path),
                "release_evidence_sha256": sha256(archive_path),
            }
            (output / "ImageLab-RELEASE-AUTHORIZATION.json").write_text(
                json.dumps(authorization_record, ensure_ascii=False, indent=2), "utf-8"
            )
        else:
            clear_authorized_outputs(output)
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return 0 if status == "RELEASE_AUTHORIZED" else 1
    except Exception as exc:
        clear_authorized_outputs(output)
        verdict = {
            "schema": 5,
            "status": "RELEASE_BLOCKED",
            "failed_conditions": [f"{type(exc).__name__}: {exc}"],
            "missing_or_malformed_evidence": sorted(set(missing_evidence)),
        }
        verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps(verdict, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
