from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
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
PROJECT_EVIDENCE_FIELDS = (
    "project_id",
    "title",
    "asset_id",
    "stored_name",
    "asset_record_sha256",
    "asset_file_sha256",
    "asset_size_bytes",
    "project_file_sha256",
    "active_asset_id",
)


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
        return {"status": "MALFORMED", "evidence_path": path.as_posix(), "error": str(exc)}


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


def validate_project_snapshot(
    name: str,
    snapshot: object,
    *,
    expected_asset_sha256: str,
    failed: list[str],
) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        failed.append(f"project_snapshot_missing:{name}")
        return {}

    for field in ("project_id", "title", "asset_id", "stored_name", "active_asset_id"):
        if not isinstance(snapshot.get(field), str) or not str(snapshot.get(field)).strip():
            failed.append(f"project_snapshot_field:{name}:{field}")
    for field in ("asset_record_sha256", "asset_file_sha256", "project_file_sha256"):
        if not valid_sha256(snapshot.get(field)):
            failed.append(f"project_snapshot_sha:{name}:{field}")
    size = snapshot.get("asset_size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        failed.append(f"project_snapshot_size:{name}")
    if snapshot.get("asset_record_sha256") != expected_asset_sha256:
        failed.append(f"project_asset_record_sha_mismatch:{name}")
    if snapshot.get("asset_file_sha256") != expected_asset_sha256:
        failed.append(f"project_asset_file_sha_mismatch:{name}")
    if snapshot.get("active_asset_id") != snapshot.get("asset_id"):
        failed.append(f"project_active_asset_mismatch:{name}")
    return snapshot


def validate_project_transition(
    name: str,
    data: dict[str, Any],
    *,
    failed: list[str],
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    if data.get("schema") != 2:
        failed.append(f"project_transition_schema:{name}")
    if data.get("project_data_preserved") is not True:
        failed.append(f"project_data_not_preserved:{name}")

    original_sha = str(data.get("original_fixture_sha256", ""))
    canonical_sha = str(data.get("canonical_uploaded_sha256", ""))
    if not valid_sha256(original_sha):
        failed.append(f"original_fixture_sha:{name}")
    if not valid_sha256(canonical_sha):
        failed.append(f"canonical_uploaded_sha:{name}")

    before = validate_project_snapshot(
        f"{name}:before",
        data.get("project_evidence_before"),
        expected_asset_sha256=canonical_sha,
        failed=failed,
    )
    after = validate_project_snapshot(
        f"{name}:after",
        data.get("project_evidence_after_update") if name == "update" else data.get("project_evidence_after_rollback"),
        expected_asset_sha256=canonical_sha,
        failed=failed,
    )
    for field in PROJECT_EVIDENCE_FIELDS:
        if before.get(field) != after.get(field):
            failed.append(f"project_transition_mismatch:{name}:{field}")

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

    return before, after, original_sha, canonical_sha


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.aggregate_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
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
        }
        failed = [name for name, data in required.items() if data.get("status") != "PASS"]
        if missing_evidence:
            failed.append("required_evidence_missing_or_malformed")

        installer_sha = str(candidate.get("installer", {}).get("sha256", ""))
        if not valid_sha256(installer_sha):
            failed.append("candidate_installer_sha")

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
        if baseline.get("authorization_record_status") != "RELEASE_AUTHORIZED":
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

        update_before, update_after, update_original_sha, update_canonical_sha = validate_project_transition(
            "update", update, failed=failed
        )
        rollback_before, rollback_after, rollback_original_sha, rollback_canonical_sha = validate_project_transition(
            "rollback", rollback, failed=failed
        )
        if update_original_sha != rollback_original_sha:
            failed.append("project_fixture_sha_mismatch:update_rollback")
        if update_canonical_sha != rollback_canonical_sha:
            failed.append("project_canonical_sha_mismatch:update_rollback")
        for field in PROJECT_EVIDENCE_FIELDS:
            if update_after.get(field) != rollback_before.get(field):
                failed.append(f"project_handoff_mismatch:update_rollback:{field}")
            if update_before.get(field) != rollback_after.get(field):
                failed.append(f"project_end_to_end_mismatch:{field}")

        installer_candidates = list((root / "build").glob("*.exe")) if (root / "build").exists() else []
        if len(installer_candidates) != 1:
            failed.append("exact_installer_missing_or_ambiguous")
            installer = None
        else:
            installer = installer_candidates[0]
            if not installer_sha or sha256(installer) != installer_sha:
                failed.append("exact_installer_binary_sha_mismatch")

        evidence_files = [path for path in root.rglob("*") if path.is_file()] if root.exists() else []
        if len(evidence_files) < 15:
            failed.append("evidence_bundle_incomplete")

        status = "RELEASE_AUTHORIZED" if not failed else "RELEASE_BLOCKED"
        verdict = {
            "schema": 3,
            "status": status,
            "installer_sha256": installer_sha,
            "identity": candidate.get("identity"),
            "gates": {name: data.get("status") for name, data in required.items()},
            "failed_conditions": sorted(set(failed)),
            "missing_or_malformed_evidence": sorted(set(missing_evidence)),
            "evidence_file_count": len(evidence_files),
        }
        verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), "utf-8")

        archive_path = output / "release-evidence.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(evidence_files):
                archive.write(path, path.relative_to(root).as_posix())
            archive.write(verdict_path, "final-verdict.json")

        if status == "RELEASE_AUTHORIZED" and installer is not None:
            authorized = output / installer.name.replace("ZERO_TRUST", "RELEASE_AUTHORIZED")
            shutil.copy2(installer, authorized)
            (output / "installer-sha256.txt").write_text(f"{installer_sha}  {authorized.name}\n", "utf-8")
            authorization_record = {
                "schema": 1,
                "status": "RELEASE_AUTHORIZED",
                "authorization_source": "finalize_gate.py",
                "installer_name": authorized.name,
                "installer_sha256": installer_sha,
                "identity": candidate.get("identity"),
                "final_verdict_sha256": sha256(verdict_path),
                "release_evidence_sha256": sha256(archive_path),
            }
            (output / "ImageLab-RELEASE-AUTHORIZATION.json").write_text(
                json.dumps(authorization_record, ensure_ascii=False, indent=2), "utf-8"
            )
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return 0 if status == "RELEASE_AUTHORIZED" else 1
    except Exception as exc:
        verdict = {
            "schema": 3,
            "status": "RELEASE_BLOCKED",
            "failed_conditions": [f"{type(exc).__name__}: {exc}"],
            "missing_or_malformed_evidence": sorted(set(missing_evidence)),
        }
        verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps(verdict, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
