#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

import C05C_T3_SHARED_STORE_ISOLATED_R5 as gate


def expect(cond: bool, name: str, failures: list[str]) -> None:
    if not cond:
        failures.append(name)


def main() -> int:
    failures: list[str] = []
    cases: list[dict] = []

    def record(name: str, passed: bool, detail=None):
        cases.append({"name": name, "passed": bool(passed), "detail": detail})
        expect(passed, name, failures)

    base = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float16)
    same = base.copy()
    r = gate.compare_arrays(base, same, "positive", expected_shape=(2, 2), expected_dtype=np.float16)
    record("positive_equal_arrays_pass", r["accepted"] is True, r)

    r = gate.compare_arrays(np.arange(6, dtype=np.float16).reshape(2, 3), np.arange(6, dtype=np.float16).reshape(3, 2), "shape")
    record("axis_permutation_same_size_fails", r["accepted"] is False and r.get("reason") == "shape_mismatch", r)

    r = gate.compare_arrays(base, base.astype(np.float32), "dtype")
    record("dtype_mismatch_fails", r["accepted"] is False and r.get("reason") == "dtype_mismatch", r)

    r = gate.compare_arrays(np.array([], dtype=np.float16), np.array([], dtype=np.float16), "empty")
    record("empty_output_fails", r["accepted"] is False and r.get("reason") == "empty_output", r)

    nan = base.copy(); nan[0, 0] = np.nan
    r = gate.compare_arrays(nan, base, "nan")
    record("nan_fails", r["accepted"] is False and r.get("reason") == "non_finite", r)

    inf = base.copy(); inf[0, 0] = np.inf
    r = gate.compare_arrays(inf, base, "inf")
    record("inf_fails", r["accepted"] is False and r.get("reason") == "non_finite", r)

    a = np.zeros((2, 4), dtype=np.float16)
    b = np.zeros((2, 4), dtype=np.float16)
    a[0, 0], a[0, 1] = np.float16(1.0), np.float16(0.999)
    b[0, 0], b[0, 1] = np.float16(0.999), np.float16(1.0)
    top = gate.cfg_top1_check(a, b, "cfg")
    record("cfg_top1_mismatch_fails", top["accepted"] is False and top.get("reason") == "cfg_top1_mismatch", top)

    top = gate.cfg_top1_check(a, a.copy(), "cfg_positive")
    record("cfg_top1_match_passes", top["accepted"] is True, top)

    status, reasons = gate.evaluate_stage_result({"accepted": False})
    record("stage_result_accepted_false_fails", status == "FAIL" and bool(reasons), {"status": status, "reasons": reasons})

    status, reasons = gate.evaluate_stage_result({"comparison_facts_only": [{"accepted": True}, {"accepted": False}]})
    record("stage_result_comparison_false_fails", status == "FAIL" and bool(reasons), {"status": status, "reasons": reasons})

    status, reasons = gate.evaluate_stage_result({"mandatory_checks": {"a": True, "b": False}})
    record("missing_mandatory_success_fails", status == "FAIL" and bool(reasons), {"status": status, "reasons": reasons})

    status, reasons = gate.evaluate_stage_result({"mandatory_checks": {}})
    record("empty_mandatory_set_fails", status == "FAIL" and bool(reasons), {"status": status, "reasons": reasons})

    status, reasons = gate.evaluate_stage_result({"mandatory_checks": {"a": True, "b": True}})
    record("all_mandatory_true_passes", status == "PASS" and not reasons, {"status": status, "reasons": reasons})

    with tempfile.TemporaryDirectory() as td:
        old_out = gate.OUT
        old_r4_out = gate.r4.OUT
        try:
            gate.OUT = Path(td)
            gate.r4.OUT = gate.OUT
            try:
                gate.stage_guard("negative_status", lambda: {"accepted": False})
                stage_failed = False
            except RuntimeError:
                stage_failed = True
            p = Path(td) / "negative_status" / "stage_result.json"
            data = json.loads(p.read_text(encoding="utf-8"))
            record("stage_guard_false_return_is_failed", stage_failed and data.get("status") == "FAIL" and data.get("numerical_status") == "FAIL", data)

            try:
                gate.stage_guard("exception", lambda: (_ for _ in ()).throw(ValueError("boom")))
                exc_failed = False
            except ValueError:
                exc_failed = True
            p2 = Path(td) / "exception" / "stage_result.json"
            data2 = json.loads(p2.read_text(encoding="utf-8"))
            record("stage_guard_exception_is_failed", exc_failed and data2.get("status") == "FAIL" and data2.get("exception_type") == "ValueError", data2)
        finally:
            gate.OUT = old_out
            gate.r4.OUT = old_r4_out

    out = {
        "schema": "sindel.cp034.c05c.parity-gate-selftest.r5.v1",
        "milestone": "C-05C/A01",
        "thresholds_unchanged": gate.THRESHOLDS,
        "cfg_weight": gate.CFG_WEIGHT,
        "case_count": len(cases),
        "pass_count": sum(1 for x in cases if x["passed"]),
        "fail_count": sum(1 for x in cases if not x["passed"]),
        "cases": cases,
        "status": "PASS_L1" if not failures else "FAIL_L1",
        "failures": failures,
    }
    Path("PARITY_GATE_SELFTEST.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("schema", "case_count", "pass_count", "fail_count", "status")}, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
