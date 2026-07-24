from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED: dict[str, str] = {
    "a0": "tests/test_a0.py",
    "a1": "tests/test_a1.py",
    "a2-a4": "tests/test_a2_a4.py",
    "ai-contours": "tests/test_ai_contours.py",
    "bootstrap": "tests/test_bootstrap.py",
    "core-failure": "tests/test_core_failure_regression.py",
    "installer-lock": "tests/test_installer_update_lock.py",
    "l5-iz017": "tests/test_l5_iz017_regression.py",
    "m1-ui": "tests/test_m1_ui.py",
    "print-extraction": "tests/test_print_extraction.py",
    "redteam": "tests/test_redteam_adversarial.py",
    "second-core": "tests/test_second_core_failure_regression.py",
    "slu-m1": "tests/test_slu_m1_units.py",
    "slu-m2-m5": "tests/test_slu_m2_m5.py",
    "slu-m3": "tests/test_slu_m3_segmentation.py",
    "slu-m5-e2e": "tests/test_slu_m5_e2e.py",
    "windows-packaging": "tests/test_windows_packaging_config.py",
    "zero-trust": "tests/test_zero_trust_release_gate.py",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    discovered: dict[str, dict[str, Any]] = {}
    malformed: list[str] = []
    duplicates: list[str] = []
    for path in sorted(input_dir.rglob("*.json")) if input_dir.exists() else []:
        try:
            data = load(path)
            case_id = str(data.get("case_id", ""))
            if not case_id:
                malformed.append(str(path))
                continue
            if case_id in discovered:
                duplicates.append(case_id)
                continue
            discovered[case_id] = data
        except Exception:
            malformed.append(str(path))

    missing = sorted(set(EXPECTED) - set(discovered))
    unexpected = sorted(set(discovered) - set(EXPECTED))
    mismatched_files = sorted(
        case_id
        for case_id, expected_file in EXPECTED.items()
        if case_id in discovered and discovered[case_id].get("test_file") != expected_file
    )
    failed_cases = sorted(
        case_id
        for case_id, data in discovered.items()
        if case_id in EXPECTED and data.get("status") != "PASS"
    )
    failed_conditions = []
    if missing:
        failed_conditions.append("missing_cases")
    if unexpected:
        failed_conditions.append("unexpected_cases")
    if mismatched_files:
        failed_conditions.append("test_file_mismatch")
    if failed_cases:
        failed_conditions.append("failed_cases")
    if malformed:
        failed_conditions.append("malformed_results")
    if duplicates:
        failed_conditions.append("duplicate_cases")

    status = "PASS" if not failed_conditions else "FAIL"
    result = {
        "schema": 1,
        "status": status,
        "expected_case_count": len(EXPECTED),
        "observed_case_count": len(discovered),
        "passed_case_count": sum(1 for case_id in EXPECTED if discovered.get(case_id, {}).get("status") == "PASS"),
        "missing_cases": missing,
        "unexpected_cases": unexpected,
        "mismatched_files": mismatched_files,
        "failed_cases": failed_cases,
        "malformed_results": malformed,
        "duplicate_cases": duplicates,
        "failed_conditions": failed_conditions,
        "cases": {case_id: discovered.get(case_id, {"status": "MISSING", "test_file": test_file}) for case_id, test_file in EXPECTED.items()},
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
