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
    "G0_source", "G1_unit_matrix", "G2_candidate", "G2_reproducibility",
    "G3_clean_install", "G3_preinstall_selftest", "G3_postinstall_selftest",
    "G4_browser_ui", "G5_output_validation", "G8_independent",
    "G8_preinstall_selftest", "G8_postinstall_selftest", "G8_independent_ui",
    "G8_independent_outputs",
}
REQUIRED_ZIP = {
    "clean-install.json", "preinstall-selftest.json", "postinstall-selftest.json",
    "ui-gate.json", "output-validation.json",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha(value: object) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(c in "0123456789abcdef" for c in text)


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


def check_selftest(label: str, value: dict[str, Any], identity: dict[str, Any], install: dict[str, Any], failed: list[str]) -> None:
    if value.get("schema") != 1:
        failed.append(f"selftest_schema:{label}")
    for key, expected in {"app": identity.get("app"), "version": identity.get("version"), "build_id": identity.get("build_id"), "install_id": install.get("install_id")}.items():
        if not expected or value.get(key) != expected:
            failed.append(f"selftest_identity_mismatch:{label}:{key}")
    tests = value.get("tests")
    if not isinstance(tests, dict) or set(tests) != SELFTESTS:
        failed.append(f"selftest_case_set_mismatch:{label}")
        tests = tests if isinstance(tests, dict) else {}
    for name in SELFTESTS:
        if not isinstance(tests.get(name), dict) or tests[name].get("status") != "PASS":
            failed.append(f"selftest_case_failed:{label}:{name}")


def check_absence(value: dict[str, Any], repository: str, failed: list[str]) -> None:
    expected = {
        "schema": 1, "status": "PASS", "release_mode": "genesis_first_release",
        "protocol_rule": RULE, "repository": repository,
        "query_source": "github_api_releases_paginated", "query_complete": True,
        "authorized_installer_asset_count": 0, "authorization_record_asset_count": 0,
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            failed.append(f"genesis_absence_invalid:{key}")
    if value.get("matching_assets") != []:
        failed.append("genesis_absence_invalid:matching_assets")
    count = value.get("release_count_scanned")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        failed.append("genesis_absence_invalid:release_count_scanned")


def check_qualification(value: dict[str, Any], verdict: dict[str, Any], *, repository: str, run_id: int, head_sha: str, installer_sha: str, failed: list[str]) -> None:
    expected = {
        "schema": 1, "status": "PASS", "repository": repository, "run_id": run_id,
        "head_sha": head_sha, "workflow_name": "ImageLab Zero-Trust Release Gate",
        "event": "workflow_dispatch", "conclusion": "failure",
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            failed.append(f"qualification_run_invalid:{key}")
    required_artifacts = {
        "ztr-source-evidence", "ztr-unit-verdict", "UNVERIFIED_INTERNAL_EXACT_CANDIDATE",
        "ztr-clean-install-evidence", "ztr-independent-evidence", "ImageLab-RELEASE-VERDICT",
    }
    if not required_artifacts.issubset(set(value.get("artifact_names") or [])):
        failed.append("qualification_run_artifacts_incomplete")
    if verdict.get("schema") != 3 or verdict.get("status") != "RELEASE_BLOCKED" or verdict.get("installer_sha256") != installer_sha:
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


def utc(value: object) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return str(value).endswith("Z")
    except ValueError:
        return False


def zip_json(archive: zipfile.ZipFile, member: str, failed: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(member).decode("utf-8-sig"))
        if not isinstance(value, dict):
            raise TypeError
        return value
    except Exception as exc:
        failed.append(f"physical_bundle_json_invalid:{PurePosixPath(member).name}:{type(exc).__name__}")
        return {}


def check_physical(manifest: dict[str, Any], manifest_path: Path, bundle: Path, *, manifest_pin: str, bundle_pin: str, identity: dict[str, Any], installer_sha: str, failed: list[str]) -> None:
    if not manifest_path.is_file() or digest(manifest_path) != manifest_pin:
        failed.append("physical_manifest_pinned_sha_mismatch")
    if not bundle.is_file() or digest(bundle) != bundle_pin:
        failed.append("physical_bundle_pinned_sha_mismatch")
        return
    expected = {
        "schema": 1, "status": "PASS", "evidence_level": "L5",
        "execution_environment": "physical_user_machine", "installer_sha256": installer_sha,
        "app": identity.get("app"), "version": identity.get("version"),
        "build_id": identity.get("build_id"), "evidence_bundle_sha256": bundle_pin,
    }
    for key, wanted in expected.items():
        if not wanted or manifest.get(key) != wanted:
            failed.append(f"physical_manifest_invalid:{key}")
    if not utc(manifest.get("observed_at_utc")) or not str(manifest.get("install_id") or "").strip():
        failed.append("physical_manifest_invalid:observation_or_install_id")
    witness, machine = manifest.get("witness"), manifest.get("machine")
    if not isinstance(witness, dict) or witness.get("role") != "product_owner" or not str(witness.get("name") or "").strip():
        failed.append("physical_manifest_invalid:witness")
    if not isinstance(machine, dict) or not str(machine.get("windows_version") or "").strip():
        failed.append("physical_manifest_invalid:machine")
    tests = manifest.get("tests")
    if not isinstance(tests, dict) or set(tests) != PHYSICAL_TESTS or any(not isinstance(tests.get(n), dict) or tests[n].get("status") != "PASS" for n in PHYSICAL_TESTS):
        failed.append("physical_manifest_invalid:test_case_set")
    if not isinstance(manifest.get("evidence_files"), list) or not manifest["evidence_files"]:
        failed.append("physical_manifest_invalid:evidence_files")

    try:
        with zipfile.ZipFile(bundle) as archive:
            members = [n for n in archive.namelist() if not n.endswith("/")]
            by_name = {PurePosixPath(n).name: n for n in members}
            for name in REQUIRED_ZIP - set(by_name):
                failed.append(f"physical_bundle_missing:{name}")
            if not any(n.lower().endswith(".png") for n in members): failed.append("physical_bundle_missing:png_evidence")
            if not any(n.lower().endswith(".svg") for n in members): failed.append("physical_bundle_missing:svg_evidence")
            if not any("trace" in PurePosixPath(n).name.lower() for n in members): failed.append("physical_bundle_missing:browser_trace")
            values = {name: zip_json(archive, member, failed) for name, member in by_name.items() if name in REQUIRED_ZIP}
            install = values.get("clean-install.json", {})
            for label in ("clean-install.json", "ui-gate.json", "output-validation.json"):
                value = values.get(label, {})
                if value.get("status") != "PASS" or value.get("installer_sha256") != installer_sha:
                    failed.append(f"physical_bundle_invalid:{label}")
            if install.get("install_id") != manifest.get("install_id") or install.get("version") != identity.get("version") or install.get("build_id") != identity.get("build_id"):
                failed.append("physical_bundle_identity_mismatch")
            check_selftest("physical_preinstall", values.get("preinstall-selftest.json", {}), identity, install, failed)
            check_selftest("physical_postinstall", values.get("postinstall-selftest.json", {}), identity, install, failed)
    except (OSError, zipfile.BadZipFile) as exc:
        failed.append(f"physical_bundle_invalid:{type(exc).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--qualification-run-id", type=int, required=True)
    parser.add_argument("--qualification-head-sha", required=True)
    parser.add_argument("--physical-manifest-sha256", required=True)
    parser.add_argument("--physical-bundle-sha256", required=True)
    args = parser.parse_args()
    root, output = args.aggregate_dir.resolve(), args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    verdict_path = output / "final-verdict.json"
    missing: list[str] = []
    try:
        paths = {
            "G0_source": root/"source/source-gate.json", "G1_unit_matrix": root/"unit/unit-matrix-verdict.json",
            "G2_candidate": root/"build/candidate-manifest.json", "G2_reproducibility": root/"build/reproducibility.json",
            "G3_clean_install": root/"clean/clean-install.json", "G3_preinstall_selftest": root/"clean/preinstall-selftest.json",
            "G3_postinstall_selftest": root/"clean/postinstall-selftest.json", "G4_browser_ui": root/"clean/ui-gate.json",
            "G5_output_validation": root/"clean/output-validation.json", "G8_independent": root/"independent/independent-verification.json",
            "G8_preinstall_selftest": root/"independent/preinstall-selftest.json", "G8_postinstall_selftest": root/"independent/postinstall-selftest.json",
            "G8_independent_ui": root/"independent/ui-gate.json", "G8_independent_outputs": root/"independent/output-validation.json",
            "GENESIS_no_prior_authorized_release": root/"genesis/genesis-baseline-verification.json",
            "PHYSICAL_user_machine_L5": root/"physical/ImageLab-PHYSICAL-L5.json",
            "QUALIFICATION_exact_run": root/"qualification/qualification-run.json",
        }
        data = {name: load(path, missing) for name, path in paths.items()}
        prior = load(root/"qualification-verdict/final-verdict.json", missing)
        failed = [name for name, value in data.items() if value.get("status") != "PASS"]
        if missing: failed.append("required_evidence_missing_or_malformed")
        candidate, repro = data["G2_candidate"], data["G2_reproducibility"]
        installer_sha = str((candidate.get("installer") or {}).get("sha256") or "")
        if not sha(installer_sha): failed.append("candidate_installer_sha")
        if repro.get("installer_sha256") != installer_sha or repro.get("second_build_sha256") != installer_sha:
            failed.append("candidate_reproducibility_sha_mismatch")
        for name, value in data.items():
            seen = value.get("installer_sha256")
            if seen is not None and seen != installer_sha: failed.append(f"sha_mismatch:{name}")
        identity = candidate.get("identity") if isinstance(candidate.get("identity"), dict) else {}
        if not identity: failed.append("candidate_identity_missing")
        check_selftest("G3_preinstall_selftest", data["G3_preinstall_selftest"], identity, data["G3_clean_install"], failed)
        check_selftest("G3_postinstall_selftest", data["G3_postinstall_selftest"], identity, data["G3_clean_install"], failed)
        check_selftest("G8_preinstall_selftest", data["G8_preinstall_selftest"], identity, data["G8_independent"], failed)
        check_selftest("G8_postinstall_selftest", data["G8_postinstall_selftest"], identity, data["G8_independent"], failed)
        check_absence(data["GENESIS_no_prior_authorized_release"], args.repository, failed)
        check_qualification(data["QUALIFICATION_exact_run"], prior, repository=args.repository, run_id=args.qualification_run_id, head_sha=args.qualification_head_sha, installer_sha=installer_sha, failed=failed)
        manifest_path, bundle = root/"physical/ImageLab-PHYSICAL-L5.json", root/"physical/ImageLab-PHYSICAL-L5-EVIDENCE.zip"
        if not sha(args.physical_manifest_sha256): failed.append("physical_manifest_pinned_sha_invalid")
        if not sha(args.physical_bundle_sha256): failed.append("physical_bundle_pinned_sha_invalid")
        check_physical(data["PHYSICAL_user_machine_L5"], manifest_path, bundle, manifest_pin=args.physical_manifest_sha256.lower(), bundle_pin=args.physical_bundle_sha256.lower(), identity=identity, installer_sha=installer_sha, failed=failed)
        installers = list((root/"build").glob("*.exe")) if (root/"build").is_dir() else []
        installer = installers[0] if len(installers) == 1 else None
        if installer is None: failed.append("exact_installer_missing_or_ambiguous")
        elif digest(installer) != installer_sha: failed.append("exact_installer_binary_sha_mismatch")
        evidence = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
        if len(evidence) < 18: failed.append("evidence_bundle_incomplete")
        status = "RELEASE_AUTHORIZED" if not failed else "RELEASE_BLOCKED"
        gates = {name: value.get("status") for name, value in data.items()}
        gates["G6_update_from_prior_authorized_release"] = "NOT_APPLICABLE_FIRST_RELEASE"
        gates["G7_rollback_to_prior_authorized_release"] = "NOT_APPLICABLE_FIRST_RELEASE"
        verdict = {"schema": 4, "status": status, "release_mode": "genesis_first_release", "protocol_rule": RULE, "installer_sha256": installer_sha, "identity": identity, "qualification_run_id": args.qualification_run_id, "qualification_head_sha": args.qualification_head_sha, "gates": gates, "failed_conditions": sorted(set(failed)), "missing_or_malformed_evidence": sorted(set(missing)), "evidence_file_count": len(evidence)}
        verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), "utf-8")
        archive_path = output/"release-evidence.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(evidence): archive.write(path, path.relative_to(root).as_posix())
            archive.write(verdict_path, "final-verdict.json")
        if status == "RELEASE_AUTHORIZED" and installer is not None:
            authorized = output/installer.name.replace("ZERO_TRUST", "RELEASE_AUTHORIZED")
            if authorized.name == installer.name or not authorized.name.endswith("_Setup_x64.exe"): raise ValueError("invalid authorized installer name")
            shutil.copy2(installer, authorized)
            (output/"installer-sha256.txt").write_text(f"{installer_sha}  {authorized.name}\n", "utf-8")
            record = {"schema": 1, "status": status, "authorization_source": "finalize_gate.py", "authorization_source_path": "release_gate/genesis/finalize_gate.py", "release_mode": "genesis_first_release", "protocol_rule": RULE, "installer_name": authorized.name, "installer_sha256": installer_sha, "identity": identity, "qualification_run_id": args.qualification_run_id, "qualification_head_sha": args.qualification_head_sha, "physical_l5_manifest_sha256": args.physical_manifest_sha256.lower(), "physical_l5_bundle_sha256": args.physical_bundle_sha256.lower(), "final_verdict_sha256": digest(verdict_path), "release_evidence_sha256": digest(archive_path)}
            (output/"ImageLab-RELEASE-AUTHORIZATION.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return 0 if status == "RELEASE_AUTHORIZED" else 1
    except Exception as exc:
        verdict = {"schema": 4, "status": "RELEASE_BLOCKED", "release_mode": "genesis_first_release", "protocol_rule": RULE, "failed_conditions": [f"{type(exc).__name__}: {exc}"], "missing_or_malformed_evidence": sorted(set(missing))}
        verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps(verdict, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
