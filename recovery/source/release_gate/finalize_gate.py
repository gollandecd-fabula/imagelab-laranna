from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_optional(path: Path, missing: list[str]) -> dict[str, Any]:
    if not path.exists():
        missing.append(path.as_posix())
        return {"status": "MISSING", "evidence_path": path.as_posix()}
    try:
        return json.loads(path.read_text("utf-8-sig"))
    except Exception as exc:
        missing.append(f"{path.as_posix()}:malformed:{type(exc).__name__}")
        return {"status": "MALFORMED", "evidence_path": path.as_posix(), "error": str(exc)}


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
        ui = read_optional(root / "clean" / "ui-gate.json", missing_evidence)
        outputs = read_optional(root / "clean" / "output-validation.json", missing_evidence)
        baseline = read_optional(root / "update" / "baseline-verification.json", missing_evidence)
        update = read_optional(root / "update" / "update-test.json", missing_evidence)
        rollback = read_optional(root / "update" / "rollback-test.json", missing_evidence)
        independent = read_optional(root / "independent" / "independent-verification.json", missing_evidence)
        independent_ui = read_optional(root / "independent" / "ui-gate.json", missing_evidence)
        independent_outputs = read_optional(root / "independent" / "output-validation.json", missing_evidence)

        required = {
            "G0_source": source,
            "G1_unit_matrix": unit,
            "G2_candidate": candidate,
            "G2_reproducibility": reproducibility,
            "G3_clean_install": clean,
            "G4_browser_ui": ui,
            "G5_output_validation": outputs,
            "G6_baseline_pinned": baseline,
            "G6_update": update,
            "G7_rollback": rollback,
            "G8_independent": independent,
            "G8_independent_ui": independent_ui,
            "G8_independent_outputs": independent_outputs,
        }
        failed = [name for name, data in required.items() if data.get("status") != "PASS"]
        if missing_evidence:
            failed.append("required_evidence_missing_or_malformed")

        installer_sha = str(candidate.get("installer", {}).get("sha256", ""))
        if len(installer_sha) != 64 or any(ch not in "0123456789abcdef" for ch in installer_sha.lower()):
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
        if baseline_sha and update_baseline_sha and baseline_sha != update_baseline_sha:
            failed.append("baseline_sha_mismatch:update")
        if baseline_sha and baseline_sha == installer_sha:
            failed.append("baseline_must_differ_from_candidate")

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
            "schema": 2,
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
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return 0 if status == "RELEASE_AUTHORIZED" else 1
    except Exception as exc:
        verdict = {
            "schema": 2,
            "status": "RELEASE_BLOCKED",
            "failed_conditions": [f"{type(exc).__name__}: {exc}"],
            "missing_or_malformed_evidence": sorted(set(missing_evidence)),
        }
        verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps(verdict, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
