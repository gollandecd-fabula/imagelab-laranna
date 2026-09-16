#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import C05C_T3_SHARED_STORE_ISOLATED_R4 as base


def checkpoint(stage: str, name: str, **extra) -> None:
    payload = {"checkpoint": name, **extra}
    base.write_json(base.stage_dir(stage) / "runtime_checkpoint.json", payload)


def runtime_prefill() -> dict:
    base.require_gate()
    base.load_stage_result("01_export_prefill")
    merged = base.load_stage_result("03_merge_store")

    import numpy as np
    import torch
    from executorch.extension.pybindings.portable_lib import _load_for_executorch_from_buffer

    sys.path.insert(0, str(base.ROOT))
    import C05C_T3_PREFILL_R3C as model_base

    stage = "04_runtime_prefill"
    pre_dir = base.stage_dir("01_export_prefill")
    union_ptd = base.stage_dir("03_merge_store") / "t3_shared_union.ptd"
    pte = pre_dir / "t3_prefill_shared_isolated_r4.pte"

    union_sha = base.sha_file(union_ptd)
    if union_sha != merged["union_ptd"]["sha256"]:
        raise RuntimeError("union PTD changed before prefill runtime")

    ce = torch.zeros((1, model_base.COND_LEN, 1024), dtype=torch.float16)
    fixed = torch.zeros((2, model_base.TEXT_SLOTS), dtype=torch.long)
    text_len = torch.tensor([66], dtype=torch.long)

    # ExecuTorch's buffer loader may retain views into both supplied Python byte
    # buffers. Keep BOTH objects strongly referenced until forward has completed.
    pte_bytes = pte.read_bytes()
    ptd_bytes = union_ptd.read_bytes()
    checkpoint(
        stage,
        "BUFFERS_RETAINED",
        pte_sha256=base.sha_bytes(pte_bytes),
        pte_size=len(pte_bytes),
        ptd_sha256=base.sha_bytes(ptd_bytes),
        ptd_size=len(ptd_bytes),
    )

    mod = _load_for_executorch_from_buffer(pte_bytes, ptd_bytes)
    checkpoint(stage, "MODULE_LOADED")

    with torch.inference_mode():
        out = mod.forward((ce, fixed, text_len))
    checkpoint(stage, "FORWARD_RETURNED")

    shapes = [list(x.shape) for x in out]
    expected = [
        [2, base.SPEECH_VOCAB],
        [base.N_LAYERS, 2, base.N_HEADS, model_base.PHYS_PREFILL, base.HD],
        [base.N_LAYERS, 2, base.N_HEADS, model_base.PHYS_PREFILL, base.HD],
    ]
    if shapes != expected or not all(bool(torch.isfinite(x).all()) for x in out):
        raise RuntimeError("prefill real forward output schema/finite check failed")

    d = base.stage_dir(stage)
    np.savez(
        d / "runtime_outputs.npz",
        logits=out[0].cpu().numpy(),
        k=out[1].cpu().numpy(),
        v=out[2].cpu().numpy(),
    )
    checkpoint(stage, "OUTPUTS_SAVED", output_shapes=shapes, all_finite=True)

    # Diagnostic-only fact capture. Uses the unchanged base.compare_arrays and
    # therefore the same frozen thresholds as the original numerical final gate.
    src = np.load(pre_dir / "source_outputs.npz")
    run = np.load(d / "runtime_outputs.npz")
    comparison = [base.compare_arrays(src[k], run[k], k) for k in ("logits", "k", "v")]

    return {
        "fresh_process_real_executorch_forward": True,
        "runtime_buffer_lifetime_fix": "PTE_AND_PTD_BYTES_RETAINED_THROUGH_FORWARD",
        "union_ptd_sha256": union_sha,
        "pte_sha256": base.sha_file(pte),
        "output_shapes": shapes,
        "all_finite": True,
        "comparison_facts_only": comparison,
    }


def runtime_decode() -> dict:
    base.require_gate()
    dec = base.load_stage_result("02_export_decode")
    merged = base.load_stage_result("03_merge_store")

    import numpy as np
    import torch
    from executorch.extension.pybindings.portable_lib import _load_for_executorch_from_buffer

    stage = "05_runtime_decode"
    dec_dir = base.stage_dir("02_export_decode")
    union_ptd = base.stage_dir("03_merge_store") / "t3_shared_union.ptd"
    pte = dec_dir / "t3_decode_shared_isolated_r4.pte"

    union_sha = base.sha_file(union_ptd)
    if union_sha != merged["union_ptd"]["sha256"]:
        raise RuntimeError("union PTD changed before decode runtime")

    prev = torch.tensor([[int(dec["start_speech_token"])]], dtype=torch.long)
    spos = torch.tensor([1], dtype=torch.long)
    max_kv = int(dec["max_kv"])
    kv_k = torch.zeros(
        (base.N_LAYERS, 2, base.N_HEADS, max_kv, base.HD), dtype=torch.float16
    )
    kv_v = torch.zeros_like(kv_k)

    pte_bytes = pte.read_bytes()
    ptd_bytes = union_ptd.read_bytes()
    checkpoint(
        stage,
        "BUFFERS_RETAINED",
        pte_sha256=base.sha_bytes(pte_bytes),
        pte_size=len(pte_bytes),
        ptd_sha256=base.sha_bytes(ptd_bytes),
        ptd_size=len(ptd_bytes),
    )

    mod = _load_for_executorch_from_buffer(pte_bytes, ptd_bytes)
    checkpoint(stage, "MODULE_LOADED")

    with torch.inference_mode():
        out = mod.forward((prev, spos, kv_k, kv_v))
    checkpoint(stage, "FORWARD_RETURNED")

    delta = [base.N_LAYERS, 2, base.N_HEADS, 1, base.HD]
    expected = [[2, base.SPEECH_VOCAB], delta, delta]
    shapes = [list(x.shape) for x in out]
    if shapes != expected or not all(bool(torch.isfinite(x).all()) for x in out):
        raise RuntimeError("decode real forward output schema/finite check failed")

    d = base.stage_dir(stage)
    np.savez(
        d / "runtime_outputs.npz",
        logits=out[0].cpu().numpy(),
        k_delta=out[1].cpu().numpy(),
        v_delta=out[2].cpu().numpy(),
    )
    checkpoint(stage, "OUTPUTS_SAVED", output_shapes=shapes, all_finite=True)

    # Diagnostic-only fact capture. No threshold or gate behavior is changed.
    src = np.load(dec_dir / "source_outputs.npz")
    run = np.load(d / "runtime_outputs.npz")
    comparison = [
        base.compare_arrays(src[k], run[k], k)
        for k in ("logits", "k_delta", "v_delta")
    ]

    return {
        "fresh_process_real_executorch_forward": True,
        "scope": "storage/runtime feasibility probe only; not production decode acceptance",
        "runtime_buffer_lifetime_fix": "PTE_AND_PTD_BYTES_RETAINED_THROUGH_FORWARD",
        "union_ptd_sha256": union_sha,
        "pte_sha256": base.sha_file(pte),
        "output_shapes": shapes,
        "all_finite": True,
        "comparison_facts_only": comparison,
    }


COMMANDS = {
    "runtime-prefill": ("04_runtime_prefill", runtime_prefill),
    "runtime-decode": ("05_runtime_decode", runtime_decode),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=sorted(COMMANDS))
    ns = ap.parse_args()
    name, fn = COMMANDS[ns.command]
    base.stage_guard(name, fn)


if __name__ == "__main__":
    main()
