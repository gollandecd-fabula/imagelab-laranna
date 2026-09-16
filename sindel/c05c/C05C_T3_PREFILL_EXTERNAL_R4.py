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
    """Fail closed before torch/model work if C-05C parity+size evidence is absent."""
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
        if rec.get('status') != 'PASS_L2':
            errors.append(f'{probe}.status')
        if rec.get('fresh_process') is not True:
            errors.append(f'{probe}.fresh_process')
        if rec.get('real_executorch_forward') is not True:
            errors.append(f'{probe}.real_executorch_forward')
        if rec.get('outputs_compared') != ['logits', 'k', 'v']:
            errors.append(f'{probe}.outputs_compared')
        if not rec.get('evidence_sha256'):
            errors.append(f'{probe}.evidence_sha256')

    size_gate = d.get('size_gate', {})
    if size_gate.get('status') != 'OPEN':
        errors.append('size_gate.status')
    if not size_gate.get('evidence_sha256'):
        errors.append('size_gate.evidence_sha256')
    if d.get('golden_published') is not False:
        errors.append('golden_published')

    if errors:
        raise SystemExit('FAIL-CLOSED: invalid parity/size gate: ' + ', '.join(errors))


# Guard direct invocation as well as CI. Keep this before torch/model import.
require_protocol_gate()

import torch

sys.path.insert(0, str(ROOT))
import C05C_T3_PREFILL_R3C as base

# This is the byte-level SHA256 of the frozen R3C exporter. The repository
# workflow separately freezes the Git blob identity (1be8e697...). Keep the
# two identities distinct: Git blob SHA is not a file SHA256.
EXPECTED_BASE_SHA256 = '0b6e906bf4066606992f9b562989569567f623715ffe62f9b9a91b59fab44971'
OUT = Path(os.environ.get('SINDEL_C05C_EXTERNAL_OUT', os.environ.get('RUNNER_TEMP','/tmp'))) / 'c05c_external_r4'
OUT.mkdir(parents=True, exist_ok=True)


def sha256(p: Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024), b''): h.update(b)
    return h.hexdigest()


def main():
    base_path = ROOT/'C05C_T3_PREFILL_R3C.py'
    actual_base_sha256 = sha256(base_path)
    assert actual_base_sha256 == EXPECTED_BASE_SHA256, actual_base_sha256
    t0=time.time()
    m=base.load_t3(torch.float16)
    sta=base.StaticPrefillInput(m).eval()
    ce=torch.zeros((1,base.COND_LEN,1024),dtype=torch.float16)
    fixed=torch.zeros((2,base.TEXT_SLOTS),dtype=torch.long)
    L=torch.tensor([66],dtype=torch.long)
    with torch.no_grad():
        lo,k,v=sta(ce,fixed,L)
        assert torch.isfinite(lo).all() and torch.isfinite(k).all() and torch.isfinite(v).all()
    from torch.export import export
    from executorch.exir import to_edge_transform_and_lower, EdgeCompileConfig, ExecutorchBackendConfig
    from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
    ep=export(sta,(ce,fixed,L))
    edge=to_edge_transform_and_lower(ep,compile_config=EdgeCompileConfig(_check_ir_validity=False),partitioner=[XnnpackPartitioner()])
    cfg=ExecutorchBackendConfig(external_constants=lambda node: 't3_shared')
    et=edge.to_executorch(config=cfg)
    pte=OUT/'t3_prefill_external_r4.pte'
    with pte.open('wb') as f: et.write_to_file(f)
    et.write_tensor_data_to_file(str(OUT))
    ptd=OUT/'t3_shared.ptd'
    assert pte.is_file() and ptd.is_file() and pte.stat().st_size>0 and ptd.stat().st_size>0
    rep={
      'schema':'sindel.cp034.c05c.prefill-external-r4.v1',
      'status':'EXPORTED_NOT_YET_PRIVATE_PARITY',
      'base_exporter_sha256':actual_base_sha256,
      'pte':{'name':pte.name,'size':pte.stat().st_size,'sha256':sha256(pte)},
      'ptd':{'name':ptd.name,'size':ptd.stat().st_size,'sha256':sha256(ptd)},
      'total_bytes':pte.stat().st_size+ptd.stat().st_size,
      'input_shapes':[list(ce.shape),list(fixed.shape),list(L.shape)],
      'output_shapes':[list(lo.shape),list(k.shape),list(v.shape)],
      'external_tag':'t3_shared','dtype':'fp16','elapsed_s':time.time()-t0}
    (OUT/'C05C_T3_PREFILL_EXTERNAL_R4_EXPORT.json').write_text(json.dumps(rep,indent=2),encoding='utf-8')
    print(json.dumps(rep,indent=2))

if __name__=='__main__': main()
