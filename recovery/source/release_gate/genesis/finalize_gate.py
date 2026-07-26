from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from release_gate.finalize_gate import read_physical, validate_physical_l5, validate_project_transition

RULE = "GENESIS-FIRST-RELEASE-V1"
SELFTESTS = {"resize_ppi", "background", "halftone", "vector", "history_lineage", "export"}
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


def is_loopback_url(value: object) -> bool:
    try:
        parsed = urlsplit(str(value or ""))
        return (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            and parsed.port is not None
            and parsed.username is None
            and parsed.password is None
        )
    except (TypeError, ValueError):
        return False


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
        "schema": 3,
        "status": "PASS",
        "release_mode": "genesis_first_release",
        "protocol_rule": RULE,
        "repository": repository,
        "query_source": "github_api_releases_all_authorization_runs_artifacts_paginated",
        "query_complete": True,
        "current_run_id": genesis_run_id,
        "authorization_workflow_names": [
            "ImageLab Genesis First Release Gate",
            "ImageLab Genesis Request Gate",
            "ImageLab Zero-Trust Release Gate",
        ],
        "authorized_installer_asset_count": 0,
        "authorization_record_asset_count": 0,
        "prior_successful_authorization_run_count": 0,
        "prior_authorized_artifact_count": 0,
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            failed.append(f"genesis_absence_invalid:{key}")
    for key in (
        "matching_assets",
        "prior_successful_authorization_runs",
        "prior_authorized_artifacts",
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


def zip_json(archive: zipfile.ZipFile, member: str, failed: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(member).decode("utf-8-sig"))
        if not isinstance(value, dict):
            raise TypeError("JSON root is not an object")
        return value
    except Exception as exc:
        failed.append(f"g7_json_invalid:{PurePosixPath(member).name}:{type(exc).__name__}")
        return {}


def safe_zip_members(archive: zipfile.ZipFile, failed: list[str]) -> dict[str, str]:
    by_name: dict[str, str] = {}
    for member in [name for name in archive.namelist() if not name.endswith("/")]:
        path = PurePosixPath(member)
        if path.is_absolute() or ".." in path.parts or "\\" in member:
            failed.append(f"g7_bundle_unsafe_member:{member}")
            continue
        basename = path.name
        if basename in by_name:
            failed.append(f"g7_bundle_duplicate_basename:{basename}")
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
    initial_failure_count = len(failed)
    if not is_sha256(bundle_pin):
        failed.append("g7_bundle_pinned_sha_invalid")
    if not bundle.is_file():
        failed.append("g7_bundle_missing")
        return {"status": "FAIL"}
    if is_sha256(bundle_pin) and digest(bundle) != bundle_pin.lower():
        failed.append("g7_bundle_pinned_sha_mismatch")
        return {"status": "FAIL"}

    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    source_sha = str(source.get("sha256") or "")
    if not is_sha256(source_sha):
        failed.append("candidate_source_sha_missing")

    try:
        with zipfile.ZipFile(bundle) as archive:
            by_name = safe_zip_members(archive, failed)
            for name in REQUIRED_G7_ZIP - set(by_name):
                failed.append(f"g7_bundle_missing:{name}")
            if not REQUIRED_G7_ZIP.issubset(by_name):
                return {"status": "FAIL"}
            wrapper_member = by_name["g7-evidence.json"]
            update_member = by_name["update-test.json"]
            rollback_member = by_name["rollback-test.json"]
            wrapper = zip_json(archive, wrapper_member, failed)
            update = zip_json(archive, update_member, failed)
            rollback = zip_json(archive, rollback_member, failed)
            update_bytes = archive.read(update_member)
            rollback_bytes = archive.read(rollback_member)
    except (OSError, zipfile.BadZipFile) as exc:
        failed.append(f"g7_bundle_invalid:{type(exc).__name__}")
        return {"status": "FAIL"}

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
    if not is_loopback_url(update.get("second_url")):
        failed.append("g7_update_candidate_not_runnable")

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
    if not is_loopback_url(rollback.get("restored_url")):
        failed.append("g7_rollback_restored_candidate_not_runnable")

    validate_project_transition(update, rollback, failed)
    project_count = update.get("project_count")
    asset_count = update.get("asset_count")
    if isinstance(project_count, bool) or not isinstance(project_count, int) or project_count < 3:
        failed.append("g7_project_count_insufficient")
    if isinstance(asset_count, bool) or not isinstance(asset_count, int) or asset_count < 3:
        failed.append("g7_asset_count_insufficient")

    return {
        "status": "PASS" if len(failed) == initial_failure_count else "FAIL",
        "bundle_sha256": digest(bundle),
        "baseline_installer_sha256": baseline_sha,
        "source_sha256": source_sha,
        "installer_sha256": installer_sha,
    }


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
    parser.add_argument("--physical-l5-sha256", required=True)
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
            "QUALIFICATION_exact_run": root / "qualification/qualification-run.json",
        }
        data = {name: load(path, missing) for name, path in paths.items()}
        prior = load(root / "qualification-verdict/final-verdict.json", missing)
        physical_path = root / "physical/physical-l5.json"
        physical = read_physical(physical_path, missing)
        data["PHYSICAL_user_machine_L5"] = physical
        failed = [name for name, value in data.items() if value.get("status") != "PASS"]
        if missing:
            failed.append("required_evidence_missing_or_malformed")

        candidate = data["G2_candidate"]
        repro = data["G2_reproducibility"]
        installer_info = candidate.get("installer") if isinstance(candidate.get("installer"), dict) else {}
        installer_sha = str(installer_info.get("sha256") or "")
        installer_name = str(installer_info.get("name") or "")
        if not is_sha256(installer_sha):
            failed.append("candidate_installer_sha")
        if not installer_name or Path(installer_name).name != installer_name or not installer_name.endswith(".exe"):
            failed.append("candidate_installer_name")
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

        g7 = check_g7_bundle(
            root / "g7/ImageLab-GENESIS-G7-EVIDENCE.zip",
            bundle_pin=args.g7_bundle_sha256,
            candidate=candidate,
            installer_sha=installer_sha,
            failed=failed,
        )

        physical_summary = validate_physical_l5(
            physical,
            record_path=physical_path,
            expected_record_sha256=args.physical_l5_sha256,
            candidate=candidate,
            installer_name=installer_name,
            installer_sha256=installer_sha,
            clean_install_id=str(data["G3_clean_install"].get("install_id") or ""),
            independent_install_id=str(data["G8_independent"].get("install_id") or ""),
            failed=failed,
        )

        installers = list((root / "build").glob("*.exe")) if (root / "build").is_dir() else []
        installer = installers[0] if len(installers) == 1 else None
        if installer is None:
            failed.append("exact_installer_missing_or_ambiguous")
        elif digest(installer) != installer_sha:
            failed.append("exact_installer_binary_sha_mismatch")

        evidence = [path for path in root.rglob("*") if path.is_file()] if root.exists() else []
        if len(evidence) < 18:
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
            "physical_l5": physical_summary,
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
                "install_id": physical_summary.get("install_id"),
                "qualification_run_id": args.qualification_run_id,
                "qualification_head_sha": args.qualification_head_sha,
                "genesis_run_id": args.genesis_run_id,
                "g7_evidence_bundle_sha256": args.g7_bundle_sha256.lower(),
                "g7_baseline_installer_sha256": g7.get("baseline_installer_sha256"),
                "physical_l5_record_sha256": args.physical_l5_sha256.lower(),
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
