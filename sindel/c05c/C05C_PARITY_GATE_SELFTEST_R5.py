#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import numpy as np

import C05C_PARITY_GATE_STRICT_R5 as gate


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def case(name, passed, detail=""):
    return {"name": name, "passed": bool(passed), "detail": detail}


def main() -> int:
    rows = []
    f16 = np.dtype("float16")

    # Positive baseline, including all-zero but NON-empty tensors.
    z = np.zeros((2, 4), dtype=f16)
    r = gate.compare_arrays(z, z.copy(), "logits", expected_shape=(2, 4), expected_dtype=f16, cfg_top1_must_match=True)
    rows.append(case("positive_nonempty_zero", r["accepted"] is True, json.dumps(r, sort_keys=True)))

    # F03: same flattened values but different shape must fail.
    a = np.arange(6, dtype=f16).reshape(2, 3)
    b = np.arange(6, dtype=f16).reshape(3, 2)
    r = gate.compare_arrays(a, b, "k")
    rows.append(case("shape_mismatch", r["accepted"] is False and r["reason"] == "shape_mismatch", json.dumps(r, sort_keys=True)))

    # F04: numerically equal FP16/FP32 must fail.
    r = gate.compare_arrays(a, a.astype(np.float32), "k")
    rows.append(case("dtype_mismatch", r["accepted"] is False and r["reason"] == "dtype_mismatch", json.dumps(r, sort_keys=True)))

    # F05: empty outputs must never compare equal.
    empty = np.array([], dtype=f16)
    r = gate.compare_arrays(empty, empty.copy(), "k")
    rows.append(case("empty_output", r["accepted"] is False and r["reason"] == "empty_output", json.dumps(r, sort_keys=True)))

    # Non-finite values must fail closed.
    nf = np.array([1.0, np.nan], dtype=f16)
    r = gate.compare_arrays(nf, nf.copy(), "k")
    rows.append(case("nan_inf", r["accepted"] is False and r["reason"] == "non_finite", json.dumps(r, sort_keys=True)))

    # Missing output must fail aggregate completeness.
    evaluated = gate.evaluate_output_sets(
        {"logits": z, "k": a, "v": a},
        {"logits": z.copy(), "k": a.copy()},
        ("logits", "k", "v"),
        cfg_top1_names=("logits",),
    )
    rows.append(case("missing_output", evaluated["aggregate"]["accepted"] is False and "v" in evaluated["aggregate"]["failed"], json.dumps(evaluated["aggregate"], sort_keys=True)))

    # F06: tiny changes that stay inside numeric thresholds but change CFG top1 must fail.
    ref_logits = np.array([[1.0000, 0.9997], [0.0, 0.0]], dtype=f16)
    cand_logits = np.array([[0.9997, 1.0000], [0.0, 0.0]], dtype=f16)
    r = gate.compare_arrays(ref_logits, cand_logits, "logits", cfg_top1_must_match=True)
    rows.append(case("cfg_top1_mismatch", r["accepted"] is False and r["reason"] == "cfg_top1_mismatch" and r.get("numerical_ok") is True, json.dumps(r, sort_keys=True)))

    # F02: a single numerical false must make overall status FAILED.
    bad = a.copy(); bad[0, 0] = np.float16(9.0)
    evaluated = gate.evaluate_output_sets(
        {"k": a, "v": a},
        {"k": a.copy(), "v": bad},
        ("k", "v"),
        cfg_top1_names=(),
    )
    rows.append(case("one_numerical_false", evaluated["aggregate"]["accepted"] is False and evaluated["aggregate"]["numerical_status"] == "FAILED", json.dumps(evaluated["aggregate"], sort_keys=True)))

    # F08: failed run must persist machine-readable detail BEFORE raising.
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        ref = td / "ref.npz"; cand = td / "cand.npz"; report = td / "failure.json"
        np.savez(ref, k=a)
        np.savez(cand, k=bad)
        raised = False
        try:
            gate.run_gate(ref, cand, report, ("k",), cfg_top1_names=())
        except gate.GateFailed:
            raised = True
        saved = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
        rows.append(case(
            "failure_report_before_raise",
            raised and saved.get("status") == "FAILED" and saved.get("numerical_status") == "FAILED" and bool(saved.get("checks")),
            json.dumps(saved, sort_keys=True),
        ))

    # Report/JSON write failure itself must not be converted to PASS.
    with tempfile.TemporaryDirectory() as td:
        bad_path = Path(td) / "occupied"
        bad_path.mkdir()
        failed_closed = False
        try:
            gate.write_json_atomic(bad_path, {"status": "PASS"})
        except BaseException:
            failed_closed = True
        rows.append(case("report_write_error_fail_closed", failed_closed, "write_json_atomic raised as required"))

    all_pass = all(r["passed"] for r in rows)
    out = Path(__file__).resolve().parent / "PARITY_GATE_SELFTEST.json"
    result = {
        "schema": "sindel.cp034.c05c.parity-gate-selftest-r5.v1",
        "test": "T01",
        "requirements": ["F02", "F03", "F04", "F05", "F06", "F08"],
        "evidence_level": "L1",
        "gate_module": "C05C_PARITY_GATE_STRICT_R5.py",
        "gate_module_sha256": sha256_file(Path(gate.__file__)),
        "cases": rows,
        "case_count": len(rows),
        "passed_count": sum(1 for r in rows if r["passed"]),
        "status": "PASS_L1" if all_pass else "FAILED",
    }
    gate.write_json_atomic(out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
