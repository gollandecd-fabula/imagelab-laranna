#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

import C05C_T3_SHARED_STORE_ISOLATED_R4 as r4

# A01 / C-05C: parity-gate reliability repair. Frozen numerical thresholds are unchanged.
THRESHOLDS = dict(r4.THRESHOLDS)
CFG_WEIGHT = 0.03
OUT = Path(os.environ.get("SINDEL_C05C_SHARED_OUT", os.environ.get("RUNNER_TEMP", "/tmp"))) / "c05c_shared_store_isolated_r5"
OUT.mkdir(parents=True, exist_ok=True)

EXPECTED_SCHEMAS = {
    "prefill": {
        "logits": ((2, r4.SPEECH_VOCAB), np.dtype("float16")),
        "k": ((r4.N_LAYERS, 2, r4.N_HEADS, 294, r4.HD), np.dtype("float16")),
        "v": ((r4.N_LAYERS, 2, r4.N_HEADS, 294, r4.HD), np.dtype("float16")),
    },
    "decode_probe": {
        "logits": ((2, r4.SPEECH_VOCAB), np.dtype("float16")),
        "k_delta": ((r4.N_LAYERS, 2, r4.N_HEADS, 1, r4.HD), np.dtype("float16")),
        "v_delta": ((r4.N_LAYERS, 2, r4.N_HEADS, 1, r4.HD), np.dtype("float16")),
    },
}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def stage_dir(name: str) -> Path:
    path = OUT / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _comparison_records(result: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key in ("comparison", "comparison_facts_only", "comparisons"):
        value = result.get(key)
        if isinstance(value, list):
            records.extend(x for x in value if isinstance(x, dict))
        elif isinstance(value, dict):
            records.append(value)
    return records


def evaluate_stage_result(result: dict[str, Any]) -> tuple[str, list[str]]:
    """Return numerical status and fail-closed reasons without changing frozen thresholds."""
    reasons: list[str] = []
    if "accepted" in result and result.get("accepted") is not True:
        reasons.append("accepted_not_true")

    records = _comparison_records(result)
    if records:
        for idx, rec in enumerate(records):
            if rec.get("accepted") is not True:
                reasons.append(f"comparison[{idx}].accepted_not_true")

    mandatory = result.get("mandatory_checks")
    if mandatory is not None:
        if not isinstance(mandatory, dict) or not mandatory:
            reasons.append("mandatory_checks_missing_or_empty")
        else:
            for key, value in mandatory.items():
                if value is not True:
                    reasons.append(f"mandatory_checks.{key}_not_true")

    if result.get("mandatory_checks_complete") is False:
        reasons.append("mandatory_checks_incomplete")

    declared = result.get("numerical_status")
    if declared in {"FAIL", "FAILED", False}:
        reasons.append("declared_numerical_failure")

    if reasons:
        return "FAIL", reasons
    if records or "accepted" in result or mandatory is not None or declared is not None:
        return "PASS", []
    return "NOT_APPLICABLE", []


def stage_guard(name: str, fn) -> None:
    d = stage_dir(name)
    started = time.time()
    write_json(d / "stage_start.json", {
        "stage": name,
        "status": "STARTED",
        "pid": os.getpid(),
        "started_unix": started,
        "python": sys.version,
        "gate_revision": "R5_A01",
    })
    try:
        raw = fn()
        result = dict(raw)
        numerical_status, reasons = evaluate_stage_result(result)
        execution_status = "PASS"
        overall_status = "FAIL" if numerical_status == "FAIL" else "PASS"
        payload = dict(result)
        payload.update({
            "stage": name,
            "status": overall_status,
            "execution_status": execution_status,
            "numerical_status": numerical_status,
            "gate_failure_reasons": reasons,
            "pid": os.getpid(),
            "elapsed_s": time.time() - started,
            "gate_revision": "R5_A01",
        })
        write_json(d / "stage_result.json", payload)
        if overall_status != "PASS":
            raise RuntimeError("stage returned but mandatory numerical checks failed: " + ", ".join(reasons))
    except BaseException as exc:
        existing: dict[str, Any] = {}
        result_path = d / "stage_result.json"
        if result_path.is_file():
            try:
                existing = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        failure = {
            **existing,
            "stage": name,
            "status": "FAIL",
            "execution_status": existing.get("execution_status", "FAIL"),
            "numerical_status": existing.get("numerical_status", "UNVERIFIED"),
            "pid": os.getpid(),
            "elapsed_s": time.time() - started,
            "exception_type": type(exc).__name__,
            "exception": str(exc)[:2000],
            "gate_revision": "R5_A01",
        }
        write_json(result_path, failure)
        (d / "traceback.txt").write_text(traceback.format_exc()[-20000:], encoding="utf-8")
        raise


def compare_arrays(
    a,
    b,
    name: str,
    *,
    expected_shape: tuple[int, ...] | None = None,
    expected_dtype: np.dtype | str | None = None,
) -> dict[str, Any]:
    aa0 = np.asarray(a)
    bb0 = np.asarray(b)
    result: dict[str, Any] = {
        "name": name,
        "a_shape": list(aa0.shape),
        "b_shape": list(bb0.shape),
        "a_dtype": str(aa0.dtype),
        "b_dtype": str(bb0.dtype),
    }

    if aa0.shape != bb0.shape:
        return {**result, "accepted": False, "reason": "shape_mismatch"}
    if expected_shape is not None and aa0.shape != tuple(expected_shape):
        return {
            **result,
            "accepted": False,
            "reason": "schema_shape_mismatch",
            "expected_shape": list(expected_shape),
        }

    if aa0.dtype != bb0.dtype:
        return {**result, "accepted": False, "reason": "dtype_mismatch"}
    if expected_dtype is not None:
        exp_dtype = np.dtype(expected_dtype)
        if aa0.dtype != exp_dtype:
            return {
                **result,
                "accepted": False,
                "reason": "schema_dtype_mismatch",
                "expected_dtype": str(exp_dtype),
            }

    if aa0.size == 0:
        return {**result, "accepted": False, "reason": "empty_output"}

    aa = aa0.astype(np.float64, copy=False).reshape(-1)
    bb = bb0.astype(np.float64, copy=False).reshape(-1)
    finite = bool(np.isfinite(aa).all() and np.isfinite(bb).all())
    if not finite:
        return {
            **result,
            "finite": False,
            "cosine_raw": None,
            "mean_abs": None,
            "max_abs": None,
            "accepted": False,
            "reason": "non_finite",
        }

    na = float(np.linalg.norm(aa))
    nb = float(np.linalg.norm(bb))
    if na == 0.0 and nb == 0.0:
        cosine = 1.0
    elif na == 0.0 or nb == 0.0:
        cosine = 0.0
    else:
        cosine = float(np.dot(aa, bb) / (na * nb))
    # Numerical round-off must never create a raw cosine outside its mathematical domain.
    cosine = min(1.0, max(-1.0, cosine))

    diff = np.abs(aa - bb)
    mean_abs = float(diff.mean())
    max_abs = float(diff.max())
    accepted = (
        cosine >= THRESHOLDS["cosine_min"]
        and mean_abs <= THRESHOLDS["mean_abs_max"]
        and max_abs <= THRESHOLDS["max_abs_max"]
    )
    return {
        **result,
        "finite": True,
        "cosine_raw": cosine,
        "mean_abs": mean_abs,
        "max_abs": max_abs,
        "accepted": bool(accepted),
        "reason": None if accepted else "numerical_threshold_failure",
    }


def cfg_top1(logits) -> int:
    x = np.asarray(logits)
    if x.ndim != 2 or x.shape[0] != 2 or x.shape[1] == 0:
        raise ValueError(f"CFG logits must have shape [2,V], got {x.shape}")
    if not np.isfinite(x).all():
        raise ValueError("CFG logits contain non-finite values")
    xf = x.astype(np.float64, copy=False)
    cond = xf[0]
    uncond = xf[1]
    combined = cond + CFG_WEIGHT * (cond - uncond)
    return int(np.argmax(combined))


def cfg_top1_check(a, b, name: str) -> dict[str, Any]:
    try:
        a_top1 = cfg_top1(a)
        b_top1 = cfg_top1(b)
    except Exception as exc:
        return {
            "name": name,
            "cfg_weight": CFG_WEIGHT,
            "accepted": False,
            "reason": "cfg_top1_invalid_input",
            "exception": str(exc),
        }
    return {
        "name": name,
        "cfg_weight": CFG_WEIGHT,
        "a_top1": a_top1,
        "b_top1": b_top1,
        "accepted": a_top1 == b_top1,
        "reason": None if a_top1 == b_top1 else "cfg_top1_mismatch",
    }


def _npz_sha(path: Path) -> str:
    return sha_file(path) if path.is_file() else "MISSING"


def _input_fingerprint() -> str:
    descriptor = {
        "cond_emb": [1, 34, 1024, "float16", "zeros"],
        "text_tokens_fixed": [2, 258, "int64", "zeros"],
        "text_len": [66],
        "decode_prev": "start_speech_token",
        "decode_speech_pos": [1],
        "decode_kv": "zeros",
    }
    return sha_bytes(json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def verify() -> dict[str, Any]:
    r4.require_gate()
    for name in ("01_export_prefill", "02_export_decode", "03_merge_store", "04_runtime_prefill", "05_runtime_decode"):
        r4.load_stage_result(name)

    pre_src_path = stage_dir("01_export_prefill") / "source_outputs.npz"
    pre_run_path = stage_dir("04_runtime_prefill") / "runtime_outputs.npz"
    dec_src_path = stage_dir("02_export_decode") / "source_outputs.npz"
    dec_run_path = stage_dir("05_runtime_decode") / "runtime_outputs.npz"

    pre_src = np.load(pre_src_path)
    pre_run = np.load(pre_run_path)
    dec_src = np.load(dec_src_path)
    dec_run = np.load(dec_run_path)

    pre_cmp = []
    for key in ("logits", "k", "v"):
        shape, dtype = EXPECTED_SCHEMAS["prefill"][key]
        pre_cmp.append(compare_arrays(pre_src[key], pre_run[key], key, expected_shape=shape, expected_dtype=dtype))
    dec_cmp = []
    for key in ("logits", "k_delta", "v_delta"):
        shape, dtype = EXPECTED_SCHEMAS["decode_probe"][key]
        dec_cmp.append(compare_arrays(dec_src[key], dec_run[key], key, expected_shape=shape, expected_dtype=dtype))

    cfg_checks = {
        "prefill": cfg_top1_check(pre_src["logits"], pre_run["logits"], "prefill_cfg_top1"),
        "decode_probe": cfg_top1_check(dec_src["logits"], dec_run["logits"], "decode_probe_cfg_top1"),
    }

    pre_ok = all(x.get("accepted") is True for x in pre_cmp)
    dec_ok = all(x.get("accepted") is True for x in dec_cmp)
    cfg_ok = all(x.get("accepted") is True for x in cfg_checks.values())
    pre_rt = r4.load_stage_result("04_runtime_prefill")
    dec_rt = r4.load_stage_result("05_runtime_decode")
    merged = r4.load_stage_result("03_merge_store")
    same_sha = pre_rt["union_ptd_sha256"] == dec_rt["union_ptd_sha256"] == merged["union_ptd"]["sha256"]

    mandatory_checks = {
        "prefill_numerical": pre_ok,
        "decode_probe_numerical": dec_ok,
        "cfg_top1": cfg_ok,
        "shared_ptd_same_sha": same_sha,
        "all_expected_outputs_present": len(pre_cmp) == 3 and len(dec_cmp) == 3,
    }
    overall = all(mandatory_checks.values())

    report = {
        "schema": "sindel.cp034.c05c.t3-shared-store-isolated-r5-a01.v1",
        "status": "PASS_L2" if overall else "FAIL_L2",
        "accepted": overall,
        "mandatory_checks_complete": True,
        "mandatory_checks": mandatory_checks,
        "scope": "A01 parity-gate reliability repair; shared-store feasibility only; decode probe is not production decode acceptance",
        "frozen_thresholds_unchanged": THRESHOLDS,
        "cfg_top1": cfg_checks,
        "cfg_weight": CFG_WEIGHT,
        "input_fingerprint_sha256": _input_fingerprint(),
        "raw_outputs": {
            "prefill_source_npz_sha256": _npz_sha(pre_src_path),
            "prefill_runtime_npz_sha256": _npz_sha(pre_run_path),
            "decode_source_npz_sha256": _npz_sha(dec_src_path),
            "decode_runtime_npz_sha256": _npz_sha(dec_run_path),
        },
        "shared_ptd": {
            "sha256": merged["union_ptd"]["sha256"],
            "size": merged["union_ptd"]["size"],
            "same_exact_bytes_used_by_prefill_and_decode": same_sha,
        },
        "prefill": {"real_forward": True, "comparison": pre_cmp},
        "decode_probe": {"real_forward": True, "comparison": dec_cmp},
        "private_golden_published": False,
    }
    final_path = OUT / "C05C_T3_SHARED_STORE_ISOLATED_R5_FINAL.json"
    write_json(final_path, report)
    report["final_report_sha256"] = sha_file(final_path)
    report["final_report_path"] = str(final_path)
    if not overall:
        raise RuntimeError("isolated shared-store R5 final gate failed; detailed report saved")
    return report


# Bind the R4 implementation to the repaired gate/output paths without altering frozen model/export logic.
r4.OUT = OUT
r4.stage_dir = stage_dir
r4.compare_arrays = compare_arrays

COMMANDS = {
    "export-prefill": ("01_export_prefill", r4.export_prefill),
    "export-decode": ("02_export_decode", r4.export_decode),
    "merge-store": ("03_merge_store", r4.merge_store),
    "runtime-prefill": ("04_runtime_prefill", r4.runtime_prefill),
    "runtime-decode": ("05_runtime_decode", r4.runtime_decode),
    "verify": ("06_verify", verify),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=sorted(COMMANDS))
    ns = ap.parse_args()
    name, fn = COMMANDS[ns.command]
    stage_guard(name, fn)


if __name__ == "__main__":
    main()
