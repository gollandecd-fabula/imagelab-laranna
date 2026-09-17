#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

SCHEMA = "sindel.cp034.c05c.parity-gate-strict-r5.v1"
CFG_WEIGHT = 0.03
THRESHOLDS = {
    "cosine_min": 0.9999,
    "mean_abs_max": 0.005,
    "max_abs_max": 0.05,
    "finite_required": True,
}


class GateFailed(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def write_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_json_safe(dict(data)), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        finally:
            raise


def cfg_top1(logits: np.ndarray, cfg_weight: float = CFG_WEIGHT) -> int:
    arr = np.asarray(logits)
    if arr.ndim != 2 or arr.shape[0] != 2 or arr.shape[1] == 0:
        raise ValueError(f"CFG logits must have shape [2,V] with V>0, got {arr.shape}")
    if not np.issubdtype(arr.dtype, np.floating):
        raise TypeError(f"CFG logits must be floating, got {arr.dtype}")
    cond = arr[0].astype(np.float64, copy=False)
    uncond = arr[1].astype(np.float64, copy=False)
    combined = cond + float(cfg_weight) * (cond - uncond)
    if not np.isfinite(combined).all():
        raise ValueError("CFG logits contain NaN/Inf")
    return int(np.argmax(combined))


def compare_arrays(
    reference: np.ndarray,
    candidate: np.ndarray,
    name: str,
    *,
    thresholds: Mapping[str, float | bool] = THRESHOLDS,
    expected_shape: Sequence[int] | None = None,
    expected_dtype: str | np.dtype | None = None,
    cfg_top1_must_match: bool = False,
    cfg_weight: float = CFG_WEIGHT,
) -> dict[str, Any]:
    a = np.asarray(reference)
    b = np.asarray(candidate)
    result: dict[str, Any] = {
        "name": name,
        "reference_shape": list(a.shape),
        "candidate_shape": list(b.shape),
        "reference_dtype": str(a.dtype),
        "candidate_dtype": str(b.dtype),
        "accepted": False,
    }

    if a.shape != b.shape:
        result["reason"] = "shape_mismatch"
        return result
    if expected_shape is not None and tuple(a.shape) != tuple(int(x) for x in expected_shape):
        result["reason"] = "unexpected_shape"
        result["expected_shape"] = [int(x) for x in expected_shape]
        return result
    if a.dtype != b.dtype:
        result["reason"] = "dtype_mismatch"
        return result
    if expected_dtype is not None and a.dtype != np.dtype(expected_dtype):
        result["reason"] = "unexpected_dtype"
        result["expected_dtype"] = str(np.dtype(expected_dtype))
        return result
    if a.size == 0 or b.size == 0:
        result["reason"] = "empty_output"
        return result
    if not np.issubdtype(a.dtype, np.number):
        result["reason"] = "non_numeric_dtype"
        return result

    aa = a.astype(np.float64, copy=False).reshape(-1)
    bb = b.astype(np.float64, copy=False).reshape(-1)
    finite = bool(np.isfinite(aa).all() and np.isfinite(bb).all())
    result["finite"] = finite
    if bool(thresholds.get("finite_required", True)) and not finite:
        result["reason"] = "non_finite"
        return result

    na = float(np.linalg.norm(aa))
    nb = float(np.linalg.norm(bb))
    if na == 0.0 and nb == 0.0:
        cosine = 1.0
    elif na == 0.0 or nb == 0.0:
        cosine = 0.0
    else:
        cosine = float(np.dot(aa, bb) / (na * nb))
    diff = np.abs(aa - bb)
    mean_abs = float(diff.mean())
    max_abs = float(diff.max())
    result.update({"cosine_raw": cosine, "mean_abs": mean_abs, "max_abs": max_abs})

    numerical_ok = (
        cosine >= float(thresholds["cosine_min"])
        and mean_abs <= float(thresholds["mean_abs_max"])
        and max_abs <= float(thresholds["max_abs_max"])
    )
    result["numerical_ok"] = numerical_ok

    if cfg_top1_must_match:
        try:
            ref_top1 = cfg_top1(a, cfg_weight)
            cand_top1 = cfg_top1(b, cfg_weight)
        except (TypeError, ValueError) as exc:
            result["reason"] = "cfg_top1_invalid"
            result["cfg_top1_error"] = str(exc)
            return result
        result.update({
            "cfg_weight": float(cfg_weight),
            "reference_cfg_top1": ref_top1,
            "candidate_cfg_top1": cand_top1,
            "cfg_top1_match": ref_top1 == cand_top1,
        })
        if ref_top1 != cand_top1:
            result["reason"] = "cfg_top1_mismatch"
            return result

    if not numerical_ok:
        result["reason"] = "numerical_threshold_failed"
        return result

    result["accepted"] = True
    result["reason"] = "accepted"
    return result


def aggregate_checks(checks: Sequence[Mapping[str, Any]], required_names: Sequence[str]) -> dict[str, Any]:
    required = list(required_names)
    by_name: dict[str, Mapping[str, Any]] = {}
    duplicate_names: list[str] = []
    for check in checks:
        name = str(check.get("name", ""))
        if not name:
            continue
        if name in by_name:
            duplicate_names.append(name)
        by_name[name] = check

    missing = [name for name in required if name not in by_name]
    unexpected = sorted(name for name in by_name if name not in required)
    failed = [name for name in required if name in by_name and by_name[name].get("accepted") is not True]
    accepted = not missing and not unexpected and not duplicate_names and not failed
    return {
        "required_names": required,
        "observed_names": sorted(by_name),
        "missing": missing,
        "unexpected": unexpected,
        "duplicates": sorted(set(duplicate_names)),
        "failed": failed,
        "accepted": accepted,
        "numerical_status": "PASS" if accepted else "FAILED",
    }


def evaluate_output_sets(
    reference: Mapping[str, np.ndarray],
    candidate: Mapping[str, np.ndarray],
    required_names: Sequence[str],
    *,
    cfg_top1_names: Sequence[str] = ("logits",),
    expected_shapes: Mapping[str, Sequence[int]] | None = None,
    expected_dtypes: Mapping[str, str | np.dtype] | None = None,
    thresholds: Mapping[str, float | bool] = THRESHOLDS,
    cfg_weight: float = CFG_WEIGHT,
) -> dict[str, Any]:
    expected_shapes = expected_shapes or {}
    expected_dtypes = expected_dtypes or {}
    checks: list[dict[str, Any]] = []
    for name in required_names:
        if name not in reference or name not in candidate:
            checks.append({"name": name, "accepted": False, "reason": "missing_output"})
            continue
        checks.append(compare_arrays(
            reference[name],
            candidate[name],
            name,
            thresholds=thresholds,
            expected_shape=expected_shapes.get(name),
            expected_dtype=expected_dtypes.get(name),
            cfg_top1_must_match=name in set(cfg_top1_names),
            cfg_weight=cfg_weight,
        ))
    for name in sorted(set(reference) | set(candidate)):
        if name not in required_names:
            checks.append({"name": name, "accepted": False, "reason": "unexpected_output"})
    aggregate = aggregate_checks(checks, required_names)
    return {"checks": checks, "aggregate": aggregate}


def run_gate(
    reference_npz: Path,
    candidate_npz: Path,
    report_path: Path,
    required_names: Sequence[str],
    *,
    cfg_top1_names: Sequence[str] = ("logits",),
    expected_shapes: Mapping[str, Sequence[int]] | None = None,
    expected_dtypes: Mapping[str, str | np.dtype] | None = None,
    thresholds: Mapping[str, float | bool] = THRESHOLDS,
    cfg_weight: float = CFG_WEIGHT,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "execution_status": "STARTED",
        "numerical_status": "UNVERIFIED",
        "status": "FAILED",
        "thresholds": dict(thresholds),
        "cfg_weight": float(cfg_weight),
        "reference_npz": str(reference_npz),
        "candidate_npz": str(candidate_npz),
    }
    try:
        with np.load(reference_npz, allow_pickle=False) as zr, np.load(candidate_npz, allow_pickle=False) as zc:
            reference = {k: zr[k] for k in zr.files}
            candidate = {k: zc[k] for k in zc.files}
        evaluated = evaluate_output_sets(
            reference,
            candidate,
            required_names,
            cfg_top1_names=cfg_top1_names,
            expected_shapes=expected_shapes,
            expected_dtypes=expected_dtypes,
            thresholds=thresholds,
            cfg_weight=cfg_weight,
        )
        report.update(evaluated)
        report["execution_status"] = "PASS"
        report["numerical_status"] = evaluated["aggregate"]["numerical_status"]
        report["status"] = "PASS" if evaluated["aggregate"]["accepted"] else "FAILED"
    except BaseException as exc:
        report.update({
            "execution_status": "FAILED",
            "numerical_status": "FAILED",
            "status": "FAILED",
            "exception_type": type(exc).__name__,
            "exception": str(exc)[:4000],
        })

    write_json_atomic(report_path, report)
    report["report_sha256"] = sha256_file(report_path)
    if report["status"] != "PASS":
        raise GateFailed(f"C05C strict parity gate failed; report={report_path}")
    return report
