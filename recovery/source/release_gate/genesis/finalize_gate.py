from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

RULE = "GENESIS-FIRST-RELEASE-V1"
SELFTESTS = {"resize_ppi", "background", "halftone", "vector", "history_lineage", "export"}
PHYSICAL_TESTS = SELFTESTS | {"installed_launch", "browser_ui_path", "output_file_validation"}
QUALIFIED = {
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
REQUIRED_PHYSICAL_ZIP = {
    "clean-install.json",
    "preinstall-selftest.json",
    "postinstall-selftest.json",
    "ui-gate.json",
    "output-validation.json",
}
REQUIRED_G7_ZIP = {"g7-evidence.json", "update-test.json", "rollback-test.json"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def is_sha256(value: object) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def load(path: Path, missing: list[str]) -> dict[str, Any]:
    if not path.is_file():
        missing.append(path.as_posix())
        return {"status": "MISSING"}
    try:
        value = json.loads(path.read_text("utf-8-sig"))
        if not isinstance(value, dict):
            raise TypeError("JSON root is not an object")
        return value
    except Exception as exc:
        missing.append(f"{path.as_posix()}:malformed:{type(exc).__name__}")
        return {"status": "MALFORMED"}


def utc(value: object) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return str(value).endswith("Z")
    except ValueError:
        return False


def check_selftest(
    label: str,
    value: dict[str, Any],
    identity: dict[str, Any],
    install: dict[str, Any],
    failed: list[str],
) -> None:
    if value.get("schema") != 1:
        failed.append(f"selftest_schema:{label}")
    expected_identity = {
        "app": identity.get("app"),
        "version": identity.get("version"),
        "build_id": identity.get("build_id"),
        "install_id": install.get("install_id"),
    }
    for key, expected in expected_identity.items():
        if not expected or value.get(key) != expected:
            failed.append(f"selftest_identity_mismatch:{label}:{key}")
    tests = value.get("tests")
    if not isinstance(tests, dict) or set(tests) != SELFTESTS:
        failed.append(f"selftest_case_set_mismatch:{label}")
        tests = tests if isinstance(tests, dict) else {}
    for name in SELFTESTS:
        if not isinstance(tests.get(name), dict) or tests[name].get("status") != "PASS":
            failed.append(f"selftest_case_failed:{label}:{name}")


def check_absence(
    value: dict[str, Any], repository: str, genesis_run_id: int, failed: list[str]
) -> None:
    expected = {
        "schema": 2,
        "status": "PASS",
        "release_mode": "genesis_first_release",
        "protocol_rule": RULE,
        "repository": repository,
        "query_source": "github_api_releases_actions_paginated",
        "query_complete": True,
        "current_run_id": genesis_run_id,
        "authorized_installer_asset_count": 0,
        "authorization_record_asset_count": 0,
        "prior_successful_genesis_run_count": 0,
        "prior_authorized_genesis_artifact_count": 0,
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            failed.append(f"genesis_absence_invalid:{key}")
    for key in (
        "matching_assets",
        "prior_successful_genesis_run_ids",
        "prior_authorized_genesis_artifacts",
    ):
        if value.get(key) != []:
            failed.append(f"genesis_absence_invalid:{key}")
    for key in ("release_count_scanned", "workflow_run_count_scanned", "artifact_count_scanned"):
        count = value.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            failed.append(f"genesis_absence_invalid:{key}")


def check_qualification(
    value: dict[str, Any],
    verdict: dict[str, Any],
    *,
    repository: str,
    run_id: int,
    head_sha: str,
    installer_sha: str,
    failed: list[str],
) -> None:
    expected = {
        "schema": 1,
        "status": "PASS",
        "repository": repository,
        "run_id": run_id,
        "head_sha": head_sha,
        "workflow_name": "ImageLab Zero-Trust Release Gate",
        "event": "workflow_dispatch",
        "conclusion": "failure",
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            failed.append(f"qualification_run_invalid:{key}")
    required_artifacts = {
        "ztr-source-evidence",
        "ztr-unit-verdict",
        "UNVERIFIED_INTERNAL_EXACT_CANDIDATE",
        "ztr-clean-install-evidence",
        "ztr-independent-evidence",
        "ImageLab-RELEASE-VERDICT",
    }
    if not required_artifacts.issubset(set(value.get("artifact_names") or [])):
        failed.append("qualification_run_artifacts_incomplete")
    if (
        verdict.get("schema") != 3
        or verdict.get("status") != "RELEASE_BLOCKED"
        or verdict.get("installer_sha256") != installer_sha
    ):
        failed.append("qualification_verdict_identity_or_status")
    gates = verdict.get("gates")
    if not isinstance(gates, dict):
        failed.append("qualification_verdict_gates_missing")
        return
    for gate in QUALIFIED:
        if gates.get(gate) != "PASS":
            failed.append(f"qualification_gate_not_pass:{gate}")
    for gate in ("G6_baseline_pinned", "G6_update", "G7_rollback"):
        if gates.get(gate) == "PASS":
            failed.append(f"qualification_genesis_gate_unexpected_pass:{gate}")


def zip_json(archive: zipfile.ZipFile, member: str, prefix: str, failed: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(member).decode("utf-8-sig"))
        if not isinstance(value, dict):
            raise TypeError("JSON root is not an object")
        return value
    except Exception as exc:
        failed.append(f"{prefix}_json_invalid:{PurePosixPath(member).name}:{type(exc).__name__}")
        return {}


def safe_zip_members(archive: zipfile.ZipFile, prefix: str, failed: list[str]) -> dict[str, str]:
    members = [name for name in archive.namelist() if not name.endswith("/")]
    by_name: dict[str, str] = {}
    for member in members:
        path = PurePosixPath(member)
        if path.is_absolute() or ".." in path.parts or "\\" in member:
            failed.append(f"{prefix}_unsafe_member:{member}")
            continue
        basename = path.name
        if basename in by_name:
            failed.append(f"{prefix}_duplicate_basename:{basename}")
            continue
        by_name[basename] = member
    return by_name


def check_g7_bundle(
    bundle: Path,
    *,
    bundle_pin: str,
    candidate: dict[str, Any],
    installer_sha: str,
    failed: list[str],
) -> dict[str, Any]:
    if not is_sha256(bundle_pin):
        failed.append("g7_bundle_pinned_sha_invalid")
    if not bundle.is_file():
        failed.append("g7_bundle_missing")
        return {}
    if is_sha256(bundle_pin) and digest(bundle) != bundle_pin.lower():
        failed.append("g7_bundle_pinned_sha_mismatch")
        return {}

    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    source_sha = str(source.get("sha256") or "")
    if not is_sha256(source_sha):
        failed.append("candidate_source_sha_missing")

    try:
        with zipfile.ZipFile(bundle) as archive:
            by_name = safe_zip_members(archive, "g7_bundle", failed)
            for name in REQUIRED_G7_ZIP - set(by_name):
                failed.append(f"g7_bundle_missing:{name}")
            if not REQUIRED_G7_ZIP.issubset(by_name):
                return {}
            wrapper_member = by_name["g7-evidence.json"]
            update_member = by_name["update-test.json"]
            rollback_member = by_name["rollback-test.json"]
            wrapper = zip_json(archive, wrapper_member, "g7", failed)
            update = zip_json(archive, update_member, "g7", failed)
            rollback = zip_json(archive, rollback_member, "g7", failed)
            update_bytes = archive.read(update_member)
            rollback_bytes = archive.read(rollback_member)
    except (OSError, zipfile.BadZipFile) as exc:
        failed.append(f"g7_bundle_invalid:{type(exc).__name__}")
        return {}

    expected_wrapper = {
        "schema": 1,
        "status": "PASS",
        "evidence_mode": "non_authorizing_diagnostic_baseline",
        "source_sha256": source_sha,
        "installer_sha256": installer_sha,
        "update_test_sha256": digest_bytes(update_bytes),
        "rollback_test_sha256": digest_bytes(rollback_bytes),
    }
    for key, expected in expected_wrapper.items():
        if not expected or wrapper.get(key) != expected:
            failed.append(f"g7_wrapper_invalid:{key}")
    baseline_sha = str(wrapper.get("baseline_installer_sha256") or "")
    if not is_sha256(baseline_sha):
        failed.append("g7_wrapper_invalid:baseline_installer_sha256")
    elif baseline_sha == installer_sha:
        failed.append("g7_self_baseline_forbidden")

    for label, value in (("update", update), ("rollback", rollback)):
        if value.get("schema") != 3:
            failed.append(f"g7_{label}_schema")
        if value.get("status") != "PASS":
            failed.append(f"g7_{label}_status")
        if value.get("installer_sha256") != installer_sha:
            failed.append(f"g7_{label}_installer_sha_mismatch")

    if update.get("baseline_installer_sha256") != baseline_sha:
        failed.append("g7_update_baseline_sha_mismatch")
    if update.get("old_process_stopped") is not True:
        failed.append("g7_update_old_process_not_stopped")
    if update.get("project_data_preserved") is not True:
        failed.append("g7_update_project_data_not_preserved")
    if update.get("sentinel_preserved") is not True:
        failed.append("g7_update_sentinel_not_preserved")

    first_install_id = str(update.get("first_install_id") or "")
    second_install_id = str(update.get("second_install_id") or "")
    if not first_install_id or not second_install_id or first_install_id == second_install_id:
        failed.append("g7_update_install_identity_invalid")
    if rollback.get("restored_install_id") != second_install_id:
        failed.append("g7_rollback_restored_install_id_mismatch")
    if rollback.get("expected_install_id") != second_install_id:
        failed.append("g7_rollback_expected_install_id_mismatch")
    fault_exit = rollback.get("fault_exit_code")
    if isinstance(fault_exit, bool) or not isinstance(fault_exit, int) or fault_exit == 0:
        failed.append("g7_rollback_fault_not_observed")
    if rollback.get("critical_hashes_restored") is not True:
        failed.append("g7_rollback_critical_hashes_not_restored")
    if rollback.get("project_data_preserved") is not True:
        failed.append("g7_rollback_project_data_not_preserved")
    if rollback.get("sentinel_preserved") is not True:
        failed.append("g7_rollback_sentinel_not_preserved")

    project_count = update.get("project_count")
    asset_count = update.get("asset_count")
    if isinstance(project_count, bool) or not isinstance(project_count, int) or project_count < 3:
        failed.append("g7_project_count_insufficient")
    if isinstance(asset_count, bool) or not isinstance(asset_count, int) or asset_count < 3:
        failed.append("g7_asset_count_insufficient")
    if rollback.get("project_count") != project_count or rollback.get("asset_count") != asset_count:
        failed.append("g7_inventory_counts_mismatch")

    before = update.get("project_inventory_before")
    after_update = update.get("project_inventory_after_update")
    rollback_before = rollback.get("project_inventory_before")
    after_rollback = rollback.get("project_inventory_after_rollback")
    if not all(isinstance(value, dict) for value in (before, after_update, rollback_before, after_rollback)):
        failed.append("g7_inventory_missing")
    elif not (before == after_update == rollback_before == after_rollback):
        failed.append("g7_inventory_content_mismatch")

    return {
        "status": "PASS" if not any(item.startswith("g7_") for item in failed) else "FAIL",
        "bundle_sha256": digest(bundle),
        "baseline_installer_sha256": baseline_sha,
        "source_sha256": source_sha,
        "installer_sha256": installer_sha,
    }


def check_physical(
    manifest: dict[str, Any],
    manifest_path: Path,
    bundle: Path,
    *,
    manifest_pin: str,
    bundle_pin: str,
    identity: dict[str, Any],
    installer_sha: str,
    failed: list[str],
) -> None:
    if not manifest_path.is_file() or digest(manifest_path) != manifest_pin:
        failed.append("physical_manifest_pinned_sha_mismatch")
    if not bundle.is_file() or digest(bundle) != bundle_pin:
        failed.append("physical_bundle_pinned_sha_mismatch")
        return
    expected = {
        "schema": 1,
        "status": "PASS",
        "evidence_level": "L5",
        "execution_environment": "physical_user_machine",
        "installer_sha256": installer_sha,
        "app": identity.get("app"),
        "version": identity.get("version"),
        "build_id": identity.get("build_id"),
        "evidence_bundle_sha256": bundle_pin,
    }
    for key, wanted in expected.items():
        if not wanted or manifest.get(key) != wanted:
            failed.append(f"physical_manifest_invalid:{key}")
    if not utc(manifest.get("observed_at_utc")) or not str(manifest.get("install_id") or "").strip():
        failed.append("physical_manifest_invalid:observation_or_install_id")
    witness = manifest.get("witness")
    machine = manifest.get("machine")
    if not isinstance(witness, dict) or witness.get("role") != "product_owner" or not str(witness.get("name") or "").strip():
        failed.append("physical_manifest_invalid:witness")
    if not isinstance(machine, dict) or not str(machine.get("windows_version") or "").strip():
        failed.append("physical_manifest_invalid:machine")
    tests = manifest.get("tests")
    if (
        not isinstance(tests, dict)
        or set(tests) != PHYSICAL_TESTS
        or any(not isinstance(tests.get(name), dict) or tests[name].get("status") != "PASS" for name in PHYSICAL_TESTS)
    ):
        failed.append("physical_manifest_invalid:test_case_set")
    if not isinstance(manifest.get("evidence_files"), list) or not manifest["evidence_files"]:
        failed.append("physical_manifest_invalid:evidence_files")

    try:
        with zipfile.ZipFile(bundle) as archive:
            by_name = safe_zip_members(archive, "physical_bundle", failed)
            members = [name for name in archive.namelist() if not name.endswith("/")]
            if set(manifest.get("evidence_files") or []) != set(members):
                failed.append("physical_manifest_evidence_files_mismatch")
            for name in REQUIRED_PHYSICAL_ZIP - set(by_name):
                failed.append(f"physical_bundle_missing:{name}")
            if not any(name.lower().endswith(".png") for name in members):
                failed.append("physical_bundle_missing:png_evidence")
            if not any(name.lower().endswith(".svg") for name in members):
                failed.append("physical_bundle_missing:svg_evidence")
            if not any("trace" in PurePosixPath(name).name.lower() for name in members):
                failed.append("physical_bundle_missing:browser_trace")
            values = {
                name: zip_json(archive, member, "physical_bundle", failed)
                for name, member in by_name.items()
                if name in REQUIRED_PHYSICAL_ZIP
            }
            install = values.get("clean-install.json", {})
            for label in ("clean-install.json", "ui-gate.json", "output-validation.json"):
                value = values.get(label, {})
                if value.get("status") != "PASS" or value.get("installer_sha256") != installer_sha:
                    failed.append(f"physical_bundle_invalid:{label}")
            if (
                install.get("install_id") != manifest.get("install_id")
                or install.get("version") != identity.get("version")
                or install.get("build_id") != identity.get("build_id")
            ):
                failed.append("physical_bundle_identity_mismatch")
            check_selftest("physical_preinstall", values.get("preinstall-selftest.json", {}), identity, install, failed)
            check_selftest("physical_postinstall", values.get("postinstall-selftest.json", {}), identity, install, failed)
    except (OSError, zipfile.BadZipFile) as exc:
        failed.append(f"physical_bundle_invalid:{type(exc).__name__}")


def cleanup_authorized(output: Path) -> None:
    candidates = list(output.glob("*RELEASE_AUTHORIZED*.exe"))
    candidates.extend(
        [
            output / "ImageLab-RELEASE-AUTHORIZATION.json",
            output / "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json",
            output / "installer-sha256.txt",
            output / ".authorized-installer.tmp",
            output / ".authorization-record.tmp",
            output / ".installer-sha.tmp",
        ]
    )
    for path in candidates:
        if path.exists():
            path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--genesis-run-id", type=int, required=True)
    parser.add_argument("--qualification-run-id", type=int, required=True)
    parser.add_argument("--qualification-head-sha", required=True)
    parser.add_argument("--g7-bundle-sha256", required=True)
    parser.add_argument("--physical-manifest-sha256", required=True)
    parser.add_argument("--physical-bundle-sha256", required=True)
    args = parser.parse_args()

    root = args.aggregate_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cleanup_authorized(output)
    verdict_path = output / "final-verdict.json"
    missing: list[str] = []

    try:
        paths = {
            "G0_source": root / "source/source-gate.json",
            "G1_unit_matrix": root / "unit/unit-matrix-verdict.json",
            "G2_candidate": root / "build/candidate-manifest.json",
            "G2_reproducibility": root / "build/reproducibility.json",
            "G3_clean_install": root / "clean/clean-install.json",
            "G3_preinstall_selftest": root / "clean/preinstall-selftest.json",
            "G3_postinstall_selftest": root / "clean/postinstall-selftest.json",
            "G4_browser_ui": root / "clean/ui-gate.json",
            "G5_output_validation": root / "clean/output-validation.json",
            "G8_independent": root / "independent/independent-verification.json",
            "G8_preinstall_selftest": root / "independent/preinstall-selftest.json",
            "G8_postinstall_selftest": root / "independent/postinstall-selftest.json",
            "G8_independent_ui": root / "independent/ui-gate.json",
            "G8_independent_outputs": root / "independent/output-validation.json",
            "GENESIS_no_prior_authorized_release": root / "genesis/genesis-baseline-verification.json",
            "PHYSICAL_user_machine_L5": root / "physical/ImageLab-PHYSICAL-L5.json",
            "QUALIFICATION_exact_run": root / "qualification/qualification-run.json",
        }
        data = {name: load(path, missing) for name, path in paths.items()}
        prior = load(root / "qualification-verdict/final-verdict.json", missing)
        failed = [name for name, value in data.items() if value.get("status") != "PASS"]
        if missing:
            failed.append("required_evidence_missing_or_malformed")

        candidate = data["G2_candidate"]
        repro = data["G2_reproducibility"]
        installer_sha = str((candidate.get("installer") or {}).get("sha256") or "")
        if not is_sha256(installer_sha):
            failed.append("candidate_installer_sha")
        if repro.get("installer_sha256") != installer_sha or repro.get("second_build_sha256") != installer_sha:
            failed.append("candidate_reproducibility_sha_mismatch")
        for name, value in data.items():
            seen = value.get("installer_sha256")
            if seen is not None and seen != installer_sha:
                failed.append(f"sha_mismatch:{name}")

        identity = candidate.get("identity") if isinstance(candidate.get("identity"), dict) else {}
        if not identity:
            failed.append("candidate_identity_missing")
        for label, install in (
            ("G3_clean_install", data["G3_clean_install"]),
            ("G8_independent", data["G8_independent"]),
        ):
            if (
                install.get("version") != identity.get("version")
                or install.get("build_id") != identity.get("build_id")
                or not str(install.get("install_id") or "").strip()
            ):
                failed.append(f"installed_identity_mismatch:{label}")

        check_selftest("G3_preinstall_selftest", data["G3_preinstall_selftest"], identity, data["G3_clean_install"], failed)
        check_selftest("G3_postinstall_selftest", data["G3_postinstall_selftest"], identity, data["G3_clean_install"], failed)
        check_selftest("G8_preinstall_selftest", data["G8_preinstall_selftest"], identity, data["G8_independent"], failed)
        check_selftest("G8_postinstall_selftest", data["G8_postinstall_selftest"], identity, data["G8_independent"], failed)
        check_absence(data["GENESIS_no_prior_authorized_release"], args.repository, args.genesis_run_id, failed)
        check_qualification(
            data["QUALIFICATION_exact_run"],
            prior,
            repository=args.repository,
            run_id=args.qualification_run_id,
            head_sha=args.qualification_head_sha,
            installer_sha=installer_sha,
            failed=failed,
        )

        g7_bundle = root / "g7/ImageLab-GENESIS-G7-EVIDENCE.zip"
        g7 = check_g7_bundle(
            g7_bundle,
            bundle_pin=args.g7_bundle_sha256,
            candidate=candidate,
            installer_sha=installer_sha,
            failed=failed,
        )

        physical_manifest_path = root / "physical/ImageLab-PHYSICAL-L5.json"
        physical_bundle = root / "physical/ImageLab-PHYSICAL-L5-EVIDENCE.zip"
        if not is_sha256(args.physical_manifest_sha256):
            failed.append("physical_manifest_pinned_sha_invalid")
        if not is_sha256(args.physical_bundle_sha256):
            failed.append("physical_bundle_pinned_sha_invalid")
        check_physical(
            data["PHYSICAL_user_machine_L5"],
            physical_manifest_path,
            physical_bundle,
            manifest_pin=args.physical_manifest_sha256.lower(),
            bundle_pin=args.physical_bundle_sha256.lower(),
            identity=identity,
            installer_sha=installer_sha,
            failed=failed,
        )

        installers = list((root / "build").glob("*.exe")) if (root / "build").is_dir() else []
        installer = installers[0] if len(installers) == 1 else None
        if installer is None:
            failed.append("exact_installer_missing_or_ambiguous")
        elif digest(installer) != installer_sha:
            failed.append("exact_installer_binary_sha_mismatch")

        evidence = [path for path in root.rglob("*") if path.is_file()] if root.exists() else []
        if len(evidence) < 19:
            failed.append("evidence_bundle_incomplete")

        status = "GENESIS_RELEASE_AUTHORIZED" if not failed else "RELEASE_BLOCKED"
        gates = {name: value.get("status") for name, value in data.items()}
        gates["G6_update_from_prior_authorized_release"] = "NOT_APPLICABLE_FIRST_RELEASE"
        gates["G7_rollback_to_prior_authorized_release"] = g7.get("status", "FAIL")
        verdict = {
            "schema": 5,
            "status": status,
            "release_mode": "genesis_first_release",
            "protocol_rule": RULE,
            "installer_sha256": installer_sha,
            "source_sha256": str((candidate.get("source") or {}).get("sha256") or ""),
            "identity": identity,
            "qualification_run_id": args.qualification_run_id,
            "qualification_head_sha": args.qualification_head_sha,
            "genesis_run_id": args.genesis_run_id,
            "g7_evidence": g7,
            "gates": gates,
            "failed_conditions": sorted(set(failed)),
            "missing_or_malformed_evidence": sorted(set(missing)),
            "evidence_file_count": len(evidence),
        }
        verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), "utf-8")

        archive_path = output / "release-evidence.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(evidence):
                archive.write(path, path.relative_to(root).as_posix())
            archive.write(verdict_path, "final-verdict.json")

        if status == "GENESIS_RELEASE_AUTHORIZED" and installer is not None:
            authorized = output / installer.name.replace("ZERO_TRUST", "GENESIS_RELEASE_AUTHORIZED")
            if authorized.name == installer.name or not authorized.name.endswith("_Setup_x64.exe"):
                raise ValueError("invalid Genesis-authorized installer name")
            installer_tmp = output / ".authorized-installer.tmp"
            record_tmp = output / ".authorization-record.tmp"
            sha_tmp = output / ".installer-sha.tmp"
            shutil.copy2(installer, installer_tmp)
            sha_tmp.write_text(f"{installer_sha}  {authorized.name}\n", "utf-8")
            physical_manifest = data["PHYSICAL_user_machine_L5"]
            record = {
                "schema": 2,
                "status": status,
                "authorization_source": "finalize_gate.py",
                "authorization_source_path": "release_gate/genesis/finalize_gate.py",
                "release_mode": "genesis_first_release",
                "protocol_rule": RULE,
                "installer_name": authorized.name,
                "installer_sha256": installer_sha,
                "source_sha256": str((candidate.get("source") or {}).get("sha256") or ""),
                "identity": identity,
                "install_id": physical_manifest.get("install_id"),
                "qualification_run_id": args.qualification_run_id,
                "qualification_head_sha": args.qualification_head_sha,
                "genesis_run_id": args.genesis_run_id,
                "g7_evidence_bundle_sha256": args.g7_bundle_sha256.lower(),
                "g7_baseline_installer_sha256": g7.get("baseline_installer_sha256"),
                "physical_l5_manifest_sha256": args.physical_manifest_sha256.lower(),
                "physical_l5_bundle_sha256": args.physical_bundle_sha256.lower(),
                "final_verdict_sha256": digest(verdict_path),
                "release_evidence_sha256": digest(archive_path),
            }
            record_tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
            installer_tmp.replace(authorized)
            sha_tmp.replace(output / "installer-sha256.txt")
            record_tmp.replace(output / "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json")

        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return 0 if status == "GENESIS_RELEASE_AUTHORIZED" else 1
    except Exception as exc:
        cleanup_authorized(output)
        verdict = {
            "schema": 5,
            "status": "RELEASE_BLOCKED",
            "release_mode": "genesis_first_release",
            "protocol_rule": RULE,
            "failed_conditions": [f"{type(exc).__name__}: {exc}"],
            "missing_or_malformed_evidence": sorted(set(missing)),
        }
        verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps(verdict, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
