#!/usr/bin/env python3
from __future__ import annotations

import gc
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.export import export
from executorch.exir import EdgeCompileConfig, to_edge, to_edge_transform_and_lower
from executorch.exir.passes.external_constants_pass import delegate_external_constants_pass_unlifted
from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
from executorch.extension.pybindings.portable_lib import _load_for_executorch_from_buffer

import C05C_T3_SHARED_STORE_ISOLATED_R5 as r5

OUT = Path(os.environ.get('SINDEL_C05C_A03_OUT', os.environ.get('RUNNER_TEMP', '/tmp'))) / 'c05c_a03_first_divergence_r6'
OUT.mkdir(parents=True, exist_ok=True)


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def write_json(p: Path, d: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(p.suffix + '.tmp')
    t.write_text(json.dumps(d, indent=2, sort_keys=True), encoding='utf-8')
    t.replace(p)


def arrs(out) -> dict[str, np.ndarray]:
    return {
        'logits': out[0].detach().cpu().numpy(),
        'k': out[1].detach().cpu().numpy(),
        'v': out[2].detach().cpu().numpy(),
    }


def save_npz(name: str, d: dict[str, np.ndarray]) -> str:
    p = OUT / (name + '.npz')
    np.savez(p, **d)
    return sha_file(p)


def compare(ref: dict[str, np.ndarray], got: dict[str, np.ndarray], label: str) -> dict[str, Any]:
    rows = []
    for k in ('logits', 'k', 'v'):
        shape, dtype = r5.EXPECTED_SCHEMAS['prefill'][k]
        rows.append(r5.compare_arrays(ref[k], got[k], k, expected_shape=shape, expected_dtype=dtype))
    top = r5.cfg_top1_check(ref['logits'], got['logits'], label + '_cfg_top1')
    return {
        'label': label,
        'accepted': all(x.get('accepted') is True for x in rows) and top.get('accepted') is True,
        'comparison': rows,
        'cfg_top1': top,
    }


def run_portable_embedded(et, args) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    # Diagnostic control: plain to_edge may legitimately embed constants and expose no
    # external tensor-data tag. That is expected here and must not be treated as failure.
    if sorted(et._tensor_data.keys()):
        raise RuntimeError(f'portable control unexpectedly externalized tensors: {sorted(et._tensor_data.keys())}')
    d = OUT / '04_portable_edge_embedded'
    d.mkdir(parents=True, exist_ok=True)
    pte = d / 'portable_embedded.pte'
    with pte.open('wb') as f:
        f.write(et.buffer)
    mod = _load_for_executorch_from_buffer(et.buffer)
    with torch.inference_mode():
        out = mod.forward(args)
    got = arrs(out)
    npz_sha = save_npz('04_portable_edge_runtime', got)
    return got, {
        'storage': 'embedded',
        'pte_sha256': sha_file(pte),
        'pte_size': pte.stat().st_size,
        'runtime_npz_sha256': npz_sha,
    }


def run_xnnpack_external(et, args) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    tags = sorted(et._tensor_data.keys())
    if tags != ['t3_shared']:
        raise RuntimeError(f'xnnpack path external tensor tags invalid: {tags}')
    d = OUT / '05_xnnpack_edge_external'
    d.mkdir(parents=True, exist_ok=True)
    pte = d / 'xnnpack_external.pte'
    ptd = d / 't3_shared.ptd'
    with pte.open('wb') as f:
        et.write_to_file(f)
    with ptd.open('wb') as f:
        et._tensor_data['t3_shared'].write_to_file(f)
    pte_b = pte.read_bytes()
    ptd_b = ptd.read_bytes()
    mod = _load_for_executorch_from_buffer(pte_b, ptd_b)
    with torch.inference_mode():
        out = mod.forward(args)
    got = arrs(out)
    npz_sha = save_npz('05_xnnpack_edge_runtime', got)
    return got, {
        'storage': 'external_t3_shared',
        'pte_sha256': hashlib.sha256(pte_b).hexdigest(),
        'pte_size': len(pte_b),
        'ptd_sha256': hashlib.sha256(ptd_b).hexdigest(),
        'ptd_size': len(ptd_b),
        'runtime_npz_sha256': npz_sha,
    }


def main() -> None:
    import C05C_T3_PREFILL_R3C as base

    model = base.load_t3(torch.float16)
    pre = base.StaticPrefillInput(model).eval()
    ce = torch.zeros((1, base.COND_LEN, 1024), dtype=torch.float16)
    fixed = torch.zeros((2, base.TEXT_SLOTS), dtype=torch.long)
    text_len = torch.tensor([66], dtype=torch.long)
    args = (ce, fixed, text_len)

    with torch.inference_mode():
        eager = arrs(pre(*args))
    eager_sha = save_npz('00_eager_source', eager)

    first_ep = export(pre, args, strict=False)
    first_mod = first_ep.module()
    with torch.inference_mode():
        first = arrs(first_mod(*args))
    first_sha = save_npz('01_first_export_module', first)

    tagged_gm = first_ep.module()
    delegate_external_constants_pass_unlifted(tagged_gm, gen_tag_fn=lambda node: 't3_shared')
    with torch.inference_mode():
        tagged = arrs(tagged_gm(*args))
    tagged_sha = save_npz('02_tagged_graph_module', tagged)

    tagged_ep = export(tagged_gm, args, strict=False)
    tagged_ep_mod = tagged_ep.module()
    with torch.inference_mode():
        reexp = arrs(tagged_ep_mod(*args))
    reexp_sha = save_npz('03_reexport_module', reexp)

    early_checks = {
        'eager_vs_first_export': compare(eager, first, 'eager_vs_first_export'),
        'eager_vs_tagged_graph': compare(eager, tagged, 'eager_vs_tagged_graph'),
        'eager_vs_reexport': compare(eager, reexp, 'eager_vs_reexport'),
    }
    if not all(v['accepted'] for v in early_checks.values()):
        first_failure = next(k for k, v in early_checks.items() if not v['accepted'])
        classification = {
            'eager_vs_first_export': 'TORCH_EXPORT_BOUNDARY_CAUSAL',
            'eager_vs_tagged_graph': 'EXTERNAL_CONSTANT_TAGGING_BOUNDARY_CAUSAL',
            'eager_vs_reexport': 'REEXPORT_BOUNDARY_CAUSAL',
        }[first_failure]
        report = {
            'schema': 'sindel.cp034.c05c.a03-first-divergence-r6.v1',
            'status': 'VERIFIED_L2_LOCALIZED',
            'localized': True,
            'classification': classification,
            'first_failure': first_failure,
            'scope': 'A03 prefill first-divergence diagnostic; frozen thresholds unchanged',
            'frozen_thresholds_unchanged': r5.THRESHOLDS,
            'cfg_weight': r5.CFG_WEIGHT,
            'input_fingerprint_sha256': r5._input_fingerprint(),
            'raw_npz_sha256': {'eager': eager_sha, 'first_export': first_sha, 'tagged_graph': tagged_sha, 'reexport': reexp_sha},
            'checks': early_checks,
        }
        p = OUT / 'C05C_A03_FIRST_DIVERGENCE_EVIDENCE_R6.json'
        write_json(p, report)
        print(json.dumps({'status': report['status'], 'classification': classification, 'first_failure': first_failure, 'evidence_sha256': sha_file(p)}, indent=2, sort_keys=True))
        return

    # Free the original model and transient graph modules before the ~1 GiB portable
    # control program is materialized. Keep only tagged_ep plus compact raw outputs.
    del model, pre, first_mod, first_ep, tagged_gm, tagged_ep_mod
    gc.collect()

    cfg = EdgeCompileConfig(_check_ir_validity=False)
    portable_edge = to_edge(tagged_ep, compile_config=cfg)
    portable_et = portable_edge.to_executorch()
    portable, portable_meta = run_portable_embedded(portable_et, args)
    del portable_edge, portable_et
    gc.collect()

    xnn_edge = to_edge_transform_and_lower(tagged_ep, compile_config=cfg, partitioner=[XnnpackPartitioner()])
    xnn_et = xnn_edge.to_executorch()
    xnn, xnn_meta = run_xnnpack_external(xnn_et, args)

    checks = dict(early_checks)
    checks.update({
        'eager_vs_portable_pte': compare(eager, portable, 'eager_vs_portable_pte'),
        'eager_vs_xnnpack_pte': compare(eager, xnn, 'eager_vs_xnnpack_pte'),
        'portable_vs_xnnpack': compare(portable, xnn, 'portable_vs_xnnpack'),
    })

    if not checks['eager_vs_portable_pte']['accepted']:
        classification = 'EDGE_OR_PORTABLE_EXECUTORCH_BOUNDARY_CAUSAL'
        first_failure = 'eager_vs_portable_pte'
        localized = True
    elif not checks['eager_vs_xnnpack_pte']['accepted']:
        classification = 'XNNPACK_LOWERING_OR_DELEGATE_CAUSAL'
        first_failure = 'eager_vs_xnnpack_pte'
        localized = True
    else:
        classification = 'NO_DIVERGENCE_ON_A03_ZERO_INPUT'
        first_failure = None
        localized = False

    report = {
        'schema': 'sindel.cp034.c05c.a03-first-divergence-r6.v1',
        'status': 'VERIFIED_L2_LOCALIZED' if localized else 'PARTIAL_L2',
        'localized': localized,
        'classification': classification,
        'first_failure': first_failure,
        'scope': 'A03 prefill first-divergence diagnostic; source/export/tag/reexport -> portable Edge ExecuTorch -> XNNPACK ExecuTorch; frozen thresholds unchanged',
        'frozen_thresholds_unchanged': r5.THRESHOLDS,
        'cfg_weight': r5.CFG_WEIGHT,
        'input_fingerprint_sha256': r5._input_fingerprint(),
        'raw_npz_sha256': {
            'eager': eager_sha,
            'first_export': first_sha,
            'tagged_graph': tagged_sha,
            'reexport': reexp_sha,
            'portable_runtime': portable_meta['runtime_npz_sha256'],
            'xnnpack_runtime': xnn_meta['runtime_npz_sha256'],
        },
        'portable': portable_meta,
        'xnnpack': xnn_meta,
        'checks': checks,
    }
    p = OUT / 'C05C_A03_FIRST_DIVERGENCE_EVIDENCE_R6.json'
    write_json(p, report)
    print(json.dumps({'status': report['status'], 'classification': classification, 'first_failure': first_failure, 'evidence_sha256': sha_file(p), 'checks': {k: v['accepted'] for k, v in checks.items()}}, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
