#!/usr/bin/env python3
from __future__ import annotations

import json
import os
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

    # Metrics can pass while CFG top1 changes: make two close two-row logits with swapped combined maxima.
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

            # F08: a failed numerical verify must preserve a detailed machine-readable report before raising.
            old_schemas = gate.EXPECTED_SCHEMAS
            old_require_gate = gate.r4.require_gate
            old_load_stage_result = gate.r4.load_stage_result
            try:
                gate.EXPECTED_SCHEMAS = {
                    "prefill": {
                        "logits": ((2, 4), np.dtype("float16")),
                        "k": ((1, 1), np.dtype("float16")),
                        "v": ((1, 1), np.dtype("float16")),
                    },
                    "decode_probe": {
                        "logits": ((2, 4), np.dtype("float16")),
                        "k_delta": ((1, 1), np.dtype("float16")),
                        "v_delta": ((1, 1), np.dtype("float16")),
                    },
                }
                union_sha = "u" * 64
                stage_map = {
                    "01_export_prefill": {"status": "PASS"},
                    "02_export_decode": {"status": "PASS"},
                    "03_merge_store": {"status": "PASS", "union_ptd": {"sha256": union_sha, "size": 123}},
                    "04_runtime_prefill": {"status": "PASS", "union_ptd_sha256": union_sha},
                    "05_runtime_decode": {"status": "PASS", "union_ptd_sha256": union_sha},
                }
                gate.r4.require_gate = lambda: {}
                gate.r4.load_stage_result = lambda name: stage_map[name]

                good_logits = np.array([[1.0, 0.9, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]], dtype=np.float16)
                bad_logits = np.array([[0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]], dtype=np.float16)
                tiny = np.array([[1.0]], dtype=np.float16)
                np.savez(gate.stage_dir("01_export_prefill") / "source_outputs.npz", logits=good_logits, k=tiny, v=tiny)
                np.savez(gate.stage_dir("04_runtime_prefill") / "runtime_outputs.npz", logits=bad_logits, k=tiny, v=tiny)
                np.savez(gate.stage_dir("02_export_decode") / "source_outputs.npz", logits=good_logits, k_delta=tiny, v_delta=tiny)
                np.savez(gate.stage_dir("05_runtime_decode") / "runtime_outputs.npz", logits=good_logits, k_delta=tiny, v_delta=tiny)

                try:
                    gate.verify()
                    verify_failed = False
                except RuntimeError:
                    verify_failed = True
                final_report = Path(td) / "C05C_T3_SHARED_STORE_ISOLATED_R5_FINAL.json"
                report_data = json.loads(final_report.read_text(encoding="utf-8")) if final_report.is_file() else {}
                record(
                    "failed_verify_preserves_detailed_report",
                    verify_failed
                    and final_report.is_file()
                    and report_data.get("status") == "FAIL_L2"
                    and report_data.get("accepted") is False
                    and isinstance(report_data.get("prefill", {}).get("comparison"), list)
                    and report_data.get("raw_outputs", {}).get("prefill_source_npz_sha256") not in (None, "MISSING"),
                    report_data,
                )
            finally:
                gate.EXPECTED_SCHEMAS = old_schemas
                gate.r4.require_gate = old_require_gate
                gate.r4.load_stage_result = old_load_stage_result
        finally:
            gate.OUT = old_out
            gate.r4.OUT = old_r4_out

    out = {
        "schema": "sindel.cp034.c05c.parity-gate-selftest.r5.v1",
        "milestone": "C-05C/A01",
        "thresholds_unchanged": gate.THRESHOLDS,
        "cfg_weight": gate.CFG_WEIGHT,
        "case_count": len(cases),
        "verified_count": sum(1 for x in cases if x["passed"]),
        "failed_count": sum(1 for x in cases if not x["passed"]),
        "cases": [{"name": x["name"], "verified": x["passed"]} for x in cases],
        "status": "VERIFIED_L1" if not failures else "FAILED_L1",
        "failures": failures,
    }
    Path("PARITY_GATE_SELFTEST.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("schema", "case_count", "verified_count", "failed_count", "status")}, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
