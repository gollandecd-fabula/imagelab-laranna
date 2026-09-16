#!/usr/bin/env python3
from pathlib import Path
import hashlib, json, os, sys, time

ROOT = Path(__file__).resolve().parent
GATE = ROOT / 'C05C_T3_PREFILL_PARITY_GATE_R4.json'
EXPECTED_CANDIDATE_PTE_SHA256 = '967728e7cda4b0f636f9813d288dafe0759216f17b6c690063397b3b4d1ad459'
EXPECTED_COMPARATOR_SHA256 = '07edd15b3fcdf3af533b0b9090de8e20918997793b20a3b267665bcb09539c13'
EXPECTED_THRESHOLDS = {
    'cosine_min': 0.9999,
    'mean_abs_max': 0.005,
    'max_abs_max': 0.05,
    'finite_required': True,
}


def require_protocol_gate() -> None:
    if not GATE.is_file():
        raise SystemExit('FAIL-CLOSED: C05C parity/size gate evidence is absent')
    try:
        d = json.loads(GATE.read_text(encoding='utf-8'))
    except Exception as exc:
        raise SystemExit(f'FAIL-CLOSED: unreadable parity/size gate: {exc}') from exc
    errors = []
    if d.get('schema') != 'sindel.cp034.c05c.t3-prefill-parity-gate-r4.v1':
        errors.append('schema')
    if d.get('candidate_pte_sha256') != EXPECTED_CANDIDATE_PTE_SHA256:
        errors.append('candidate_pte_sha256')
    if d.get('comparator_sha256') != EXPECTED_COMPARATOR_SHA256:
        errors.append('comparator_sha256')
    if d.get('thresholds') != EXPECTED_THRESHOLDS:
        errors.append('thresholds')
    parity = d.get('parity', {})
    for probe in ('P1', 'P2', 'P3'):
        rec = parity.get(probe, {})
        if rec.get('status') != 'PASS_L2': errors.append(f'{probe}.status')
        if rec.get('fresh_process') is not True: errors.append(f'{probe}.fresh_process')
        if rec.get('real_executorch_forward') is not True: errors.append(f'{probe}.real_executorch_forward')
        if rec.get('outputs_compared') != ['logits', 'k', 'v']: errors.append(f'{probe}.outputs_compared')
        if not rec.get('evidence_sha256'): errors.append(f'{probe}.evidence_sha256')
    size_gate = d.get('size_gate', {})
    if size_gate.get('status') != 'OPEN': errors.append('size_gate.status')
    if not size_gate.get('evidence_sha256'): errors.append('size_gate.evidence_sha256')
    if d.get('golden_published') is not False: errors.append('golden_published')
    if errors:
        raise SystemExit('FAIL-CLOSED: invalid parity/size gate: ' + ', '.join(errors))


# Fail before importing torch/model code when qualification evidence is absent.
require_protocol_gate()

import torch
from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
from executorch.exir import EdgeCompileConfig, to_edge_transform_and_lower
from executorch.exir.passes.external_constants_pass import delegate_external_constants_pass_unlifted
from torch.export import export

sys.path.insert(0, str(ROOT))
import C05C_T3_PREFILL_R3C as base

EXPECTED_BASE_SHA256 = '0b6e906bf4066606992f9b562989569567f623715ffe62f9b9a91b59fab44971'
ACCEPTED_EMBEDDED_PTE_BYTES = 1_058_764_416
OUT = Path(os.environ.get('SINDEL_C05C_EXTERNAL_OUT', os.environ.get('RUNNER_TEMP','/tmp'))) / 'c05c_external_r4'
OUT.mkdir(parents=True, exist_ok=True)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def main() -> None:
    base_path = ROOT / 'C05C_T3_PREFILL_R3C.py'
    actual_base_sha256 = sha256(base_path)
    assert actual_base_sha256 == EXPECTED_BASE_SHA256, actual_base_sha256
    t0 = time.time()

    m = base.load_t3(torch.float16)
    sta = base.StaticPrefillInput(m).eval()
    ce = torch.zeros((1, base.COND_LEN, 1024), dtype=torch.float16)
    fixed = torch.zeros((2, base.TEXT_SLOTS), dtype=torch.long)
    L = torch.tensor([66], dtype=torch.long)
    with torch.no_grad():
        lo, k, v = sta(ce, fixed, L)
        assert torch.isfinite(lo).all() and torch.isfinite(k).all() and torch.isfinite(v).all()

    # Match the already accepted R3C capture semantics.  The frozen exporter
    # calls torch.export.export without strict=True.  Forcing strict=True here
    # rejects the same inline DynamicCache import, so R4 must not silently
    # change capture semantics while testing storage externalization.
    first_ep = export(sta, (ce, fixed, L), strict=False)
    tagged_module = first_ep.module()
    delegate_external_constants_pass_unlifted(
        module=tagged_module,
        gen_tag_fn=lambda node: 't3_shared',
    )
    tagged_get_attrs = [
        n.name
        for mod in tagged_module.modules()
        if isinstance(mod, torch.fx.GraphModule)
        for n in mod.graph.nodes
        if n.op == 'get_attr'
        and n.meta.get('custom', {}).get('delegate_constant_tag') == 't3_shared'
    ]
    if not tagged_get_attrs:
        raise SystemExit('FAIL-CLOSED: no delegate constants were tagged before lowering')

    # Preserve the same non-strict capture semantics for the tagged graph.
    tagged_ep = export(tagged_module, (ce, fixed, L), strict=False)
    edge = to_edge_transform_and_lower(
        tagged_ep,
        compile_config=EdgeCompileConfig(_check_ir_validity=False),
        partitioner=[XnnpackPartitioner()],
    )
    et = edge.to_executorch()

    tags = sorted(et._tensor_data.keys())
    if tags != ['t3_shared']:
        raise SystemExit(f'FAIL-CLOSED: unexpected external tensor-data tags: {tags}')

    pte = OUT / 't3_prefill_external_r4.pte'
    pte.write_bytes(et.buffer)
    et.write_tensor_data_to_file(str(OUT))
    ptd = OUT / 't3_shared.ptd'
    if not pte.is_file() or not ptd.is_file() or pte.stat().st_size <= 0 or ptd.stat().st_size <= 0:
        raise SystemExit('FAIL-CLOSED: expected PTE/PTD pair was not produced')

    separation = {
        'embedded_candidate_bytes': ACCEPTED_EMBEDDED_PTE_BYTES,
        'external_pte_bytes': pte.stat().st_size,
        'external_ptd_bytes': ptd.stat().st_size,
        'pair_total_bytes': pte.stat().st_size + ptd.stat().st_size,
        'pte_fraction_of_embedded': pte.stat().st_size / ACCEPTED_EMBEDDED_PTE_BYTES,
        'ptd_fraction_of_embedded': ptd.stat().st_size / ACCEPTED_EMBEDDED_PTE_BYTES,
    }
    structural_ok = (
        separation['external_pte_bytes'] < ACCEPTED_EMBEDDED_PTE_BYTES
        and separation['external_ptd_bytes'] > separation['external_pte_bytes']
        and separation['external_ptd_bytes'] > 100 * 1024 * 1024
    )
    if not structural_ok:
        raise SystemExit('FAIL-CLOSED: external constants did not materially separate T3 storage')

    rep = {
        'schema': 'sindel.cp034.c05c.prefill-external-r4.v3',
        'status': 'EXPORTED_STRUCTURAL_PASS_PRIVATE_PARITY_REQUIRED',
        'base_exporter_sha256': actual_base_sha256,
        'capture_strict': False,
        'tagging_order': 'export -> unlift -> delegate tag -> re-export -> XNNPACK lower',
        'tagged_get_attr_count': len(tagged_get_attrs),
        'tensor_data_tags': tags,
        'pte': {'name': pte.name, 'size': pte.stat().st_size, 'sha256': sha256(pte)},
        'ptd': {'name': ptd.name, 'size': ptd.stat().st_size, 'sha256': sha256(ptd)},
        'separation': separation,
        'input_shapes': [list(ce.shape), list(fixed.shape), list(L.shape)],
        'output_shapes': [list(lo.shape), list(k.shape), list(v.shape)],
        'dtype': 'fp16',
        'elapsed_s': time.time() - t0,
        'golden_used': False,
        'private_parity_required': True,
    }
    (OUT / 'C05C_T3_PREFILL_EXTERNAL_R4_EXPORT.json').write_text(
        json.dumps(rep, indent=2, sort_keys=True), encoding='utf-8'
    )
    print(json.dumps(rep, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
