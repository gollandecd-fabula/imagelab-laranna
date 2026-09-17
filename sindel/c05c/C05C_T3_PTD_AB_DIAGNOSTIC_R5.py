#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import torch
from executorch.extension.pybindings.portable_lib import _load_for_executorch_from_buffer

import C05C_T3_SHARED_STORE_ISOLATED_R4 as r4
import C05C_T3_SHARED_STORE_ISOLATED_R5 as r5

BASE_OUT = Path(os.environ.get("SINDEL_C05C_SHARED_OUT", os.environ.get("RUNNER_TEMP", "/tmp"))) / "c05c_shared_store_isolated_r4"
OUT = Path(os.environ.get("SINDEL_C05C_A02_OUT", os.environ.get("RUNNER_TEMP", "/tmp"))) / "c05c_a02_ptd_ab_r5"
OUT.mkdir(parents=True, exist_ok=True)


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


def stage_result(name: str) -> dict[str, Any]:
    p = BASE_OUT / name / "stage_result.json"
    if not p.is_file():
        raise RuntimeError(f"missing prerequisite stage result: {p}")
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("status") != "PASS":
        raise RuntimeError(f"prerequisite stage not PASS: {name}: {d.get('status')}")
    return d


def run_prefill(which: str) -> dict[str, Any]:
    pre = stage_result("01_export_prefill")
    merged = stage_result("03_merge_store")
    pre_dir = BASE_OUT / "01_export_prefill"
    pte = pre_dir / "t3_prefill_shared_isolated_r4.pte"
    if which == "original":
        ptd = pre_dir / "t3_shared.ptd"
        expected_ptd_sha = r4.EXPECTED_PREFILL_PTD_SHA
    elif which == "union":
        ptd = BASE_OUT / "03_merge_store" / "t3_shared_union.ptd"
        expected_ptd_sha = merged["union_ptd"]["sha256"]
    else:
        raise ValueError(which)
    if sha_file(pte) != r4.EXPECTED_PREFILL_PTE_SHA:
        raise RuntimeError("prefill PTE drift")
    if sha_file(ptd) != expected_ptd_sha:
        raise RuntimeError(f"{which} prefill PTD drift")

    import C05C_T3_PREFILL_R3C as base
    ce = torch.zeros((1, base.COND_LEN, 1024), dtype=torch.float16)
    fixed = torch.zeros((2, base.TEXT_SLOTS), dtype=torch.long)
    text_len = torch.tensor([66], dtype=torch.long)
    pte_bytes = pte.read_bytes()
    ptd_bytes = ptd.read_bytes()
    mod = _load_for_executorch_from_buffer(pte_bytes, ptd_bytes)
    with torch.inference_mode():
        out = mod.forward((ce, fixed, text_len))
    expected = [
        [2, r4.SPEECH_VOCAB],
        [r4.N_LAYERS, 2, r4.N_HEADS, base.PHYS_PREFILL, r4.HD],
        [r4.N_LAYERS, 2, r4.N_HEADS, base.PHYS_PREFILL, r4.HD],
    ]
    shapes = [list(x.shape) for x in out]
    if shapes != expected or not all(bool(torch.isfinite(x).all()) for x in out):
        raise RuntimeError(f"prefill {which} output schema/finite failure")
    d = OUT / f"prefill_{which}"
    d.mkdir(parents=True, exist_ok=True)
    npz = d / "runtime_outputs.npz"
    np.savez(npz, logits=out[0].cpu().numpy(), k=out[1].cpu().numpy(), v=out[2].cpu().numpy())
    rep = {
        "schema": "sindel.cp034.c05c.a02-prefill-runtime-r5.v1",
        "variant": which,
        "pte_sha256": sha_file(pte),
        "ptd_sha256": sha_file(ptd),
        "ptd_size": ptd.stat().st_size,
        "runtime_outputs_npz_sha256": sha_file(npz),
        "input_fingerprint_sha256": r5._input_fingerprint(),
        "output_shapes": shapes,
        "all_finite": True,
        "fresh_process_real_executorch_forward": True,
    }
    write_json(d / "result.json", rep)
    return rep


def run_decode(which: str) -> dict[str, Any]:
    dec = stage_result("02_export_decode")
    merged = stage_result("03_merge_store")
    dec_dir = BASE_OUT / "02_export_decode"
    pte = dec_dir / "t3_decode_shared_isolated_r4.pte"
    if which == "original":
        ptd = dec_dir / "t3_shared.ptd"
    elif which == "union":
        ptd = BASE_OUT / "03_merge_store" / "t3_shared_union.ptd"
        if sha_file(ptd) != merged["union_ptd"]["sha256"]:
            raise RuntimeError("union decode PTD drift")
    else:
        raise ValueError(which)

    prev = torch.tensor([[int(dec["start_speech_token"])]], dtype=torch.long)
    spos = torch.tensor([1], dtype=torch.long)
    max_kv = int(dec["max_kv"])
    kv_k = torch.zeros((r4.N_LAYERS, 2, r4.N_HEADS, max_kv, r4.HD), dtype=torch.float16)
    kv_v = torch.zeros_like(kv_k)
    pte_bytes = pte.read_bytes()
    ptd_bytes = ptd.read_bytes()
    mod = _load_for_executorch_from_buffer(pte_bytes, ptd_bytes)
    with torch.inference_mode():
        out = mod.forward((prev, spos, kv_k, kv_v))
    delta = [r4.N_LAYERS, 2, r4.N_HEADS, 1, r4.HD]
    expected = [[2, r4.SPEECH_VOCAB], delta, delta]
    shapes = [list(x.shape) for x in out]
    if shapes != expected or not all(bool(torch.isfinite(x).all()) for x in out):
        raise RuntimeError(f"decode {which} output schema/finite failure")
    d = OUT / f"decode_{which}"
    d.mkdir(parents=True, exist_ok=True)
    npz = d / "runtime_outputs.npz"
    np.savez(npz, logits=out[0].cpu().numpy(), k_delta=out[1].cpu().numpy(), v_delta=out[2].cpu().numpy())
    rep = {
        "schema": "sindel.cp034.c05c.a02-decode-runtime-r5.v1",
        "variant": which,
        "pte_sha256": sha_file(pte),
        "ptd_sha256": sha_file(ptd),
        "ptd_size": ptd.stat().st_size,
        "runtime_outputs_npz_sha256": sha_file(npz),
        "input_fingerprint_sha256": r5._input_fingerprint(),
        "output_shapes": shapes,
        "all_finite": True,
        "fresh_process_real_executorch_forward": True,
    }
    write_json(d / "result.json", rep)
    return rep


def load_npz(path: Path) -> dict[str, np.ndarray]:
    if not path.is_file():
        raise RuntimeError(f"missing npz: {path}")
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def compare_group(group: str, src: dict[str, np.ndarray], orig: dict[str, np.ndarray], union: dict[str, np.ndarray]) -> dict[str, Any]:
    schema = r5.EXPECTED_SCHEMAS[group]
    keys = tuple(schema.keys())
    out: dict[str, Any] = {"source_vs_original": [], "source_vs_union": [], "original_vs_union": []}
    for key in keys:
        shape, dtype = schema[key]
        out["source_vs_original"].append(r5.compare_arrays(src[key], orig[key], key, expected_shape=shape, expected_dtype=dtype))
        out["source_vs_union"].append(r5.compare_arrays(src[key], union[key], key, expected_shape=shape, expected_dtype=dtype))
        out["original_vs_union"].append(r5.compare_arrays(orig[key], union[key], key, expected_shape=shape, expected_dtype=dtype))
    logits_key = "logits"
    out["cfg_top1"] = {
        "source_vs_original": r5.cfg_top1_check(src[logits_key], orig[logits_key], f"{group}_source_vs_original_cfg_top1"),
        "source_vs_union": r5.cfg_top1_check(src[logits_key], union[logits_key], f"{group}_source_vs_union_cfg_top1"),
        "original_vs_union": r5.cfg_top1_check(orig[logits_key], union[logits_key], f"{group}_original_vs_union_cfg_top1"),
    }
    for name in ("source_vs_original", "source_vs_union", "original_vs_union"):
        out[name + "_accepted"] = all(x.get("accepted") is True for x in out[name]) and out["cfg_top1"][name].get("accepted") is True
    return out


def analyze() -> dict[str, Any]:
    pre_src = load_npz(BASE_OUT / "01_export_prefill" / "source_outputs.npz")
    dec_src = load_npz(BASE_OUT / "02_export_decode" / "source_outputs.npz")
    pre_orig = load_npz(OUT / "prefill_original" / "runtime_outputs.npz")
    pre_union = load_npz(OUT / "prefill_union" / "runtime_outputs.npz")
    dec_orig = load_npz(OUT / "decode_original" / "runtime_outputs.npz")
    dec_union = load_npz(OUT / "decode_union" / "runtime_outputs.npz")

    pre = compare_group("prefill", pre_src, pre_orig, pre_union)
    dec = compare_group("decode_probe", dec_src, dec_orig, dec_union)

    pre_orig_ok = pre["source_vs_original_accepted"]
    pre_union_ok = pre["source_vs_union_accepted"]
    pre_ab_same = pre["original_vs_union_accepted"]
    dec_orig_ok = dec["source_vs_original_accepted"]
    dec_union_ok = dec["source_vs_union_accepted"]
    dec_ab_same = dec["original_vs_union_accepted"]

    if pre_orig_ok and not pre_union_ok:
        classification = "UNION_PTD_PATH_CAUSAL_FOR_PREFILL"
        localized = True
    elif pre_orig_ok and pre_union_ok and pre_ab_same:
        classification = "PREFILL_UNION_PATH_NOT_CAUSAL"
        localized = True
    elif (not pre_orig_ok) and (not pre_union_ok) and pre_ab_same:
        classification = "COMMON_PREFILL_EXPORT_OR_RUNTIME_PATH_NOT_UNION"
        localized = True
    elif (not pre_orig_ok) and (not pre_union_ok) and (not pre_ab_same):
        classification = "MULTIPLE_OR_COMPOUND_PREFILL_DEFECTS"
        localized = False
    else:
        classification = "PREFILL_RESULT_REQUIRES_FURTHER_LOCALIZATION"
        localized = False

    report = {
        "schema": "sindel.cp034.c05c.a02-ptd-ab-r5.v1",
        "status": "PASS_L2_DIAGNOSTIC_LOCALIZED" if localized else "PARTIAL_L2_DIAGNOSTIC",
        "localized": localized,
        "classification": classification,
        "scope": "A02 F01 localization only; same PTE/input/environment, original per-program PTD versus merged union PTD; thresholds unchanged",
        "frozen_thresholds_unchanged": r5.THRESHOLDS,
        "cfg_weight": r5.CFG_WEIGHT,
        "input_fingerprint_sha256": r5._input_fingerprint(),
        "prefill": pre,
        "decode_probe": dec,
        "summary": {
            "prefill_source_vs_original": pre_orig_ok,
            "prefill_source_vs_union": pre_union_ok,
            "prefill_original_vs_union": pre_ab_same,
            "decode_source_vs_original": dec_orig_ok,
            "decode_source_vs_union": dec_union_ok,
            "decode_original_vs_union": dec_ab_same,
        },
        "raw_output_sha256": {
            "prefill_source": sha_file(BASE_OUT / "01_export_prefill" / "source_outputs.npz"),
            "prefill_original": sha_file(OUT / "prefill_original" / "runtime_outputs.npz"),
            "prefill_union": sha_file(OUT / "prefill_union" / "runtime_outputs.npz"),
            "decode_source": sha_file(BASE_OUT / "02_export_decode" / "source_outputs.npz"),
            "decode_original": sha_file(OUT / "decode_original" / "runtime_outputs.npz"),
            "decode_union": sha_file(OUT / "decode_union" / "runtime_outputs.npz"),
        },
    }
    p = OUT / "C05C_A02_PTD_AB_EVIDENCE_R5.json"
    write_json(p, report)
    print(json.dumps({"status": report["status"], "localized": localized, "classification": classification, "summary": report["summary"], "evidence_sha256": sha_file(p)}, indent=2, sort_keys=True))
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=[
        "prefill-original", "prefill-union", "decode-original", "decode-union", "analyze"
    ])
    ns = ap.parse_args()
    if ns.command == "prefill-original": run_prefill("original")
    elif ns.command == "prefill-union": run_prefill("union")
    elif ns.command == "decode-original": run_decode("original")
    elif ns.command == "decode-union": run_decode("union")
    else: analyze()


if __name__ == "__main__":
    main()
