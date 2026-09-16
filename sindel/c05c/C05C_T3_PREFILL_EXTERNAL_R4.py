#!/usr/bin/env python3
from pathlib import Path
import hashlib, json, os, sys, time
import torch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import C05C_T3_PREFILL_R3C as base

EXPECTED_BASE_SHA = '1be8e6975c68ae6f2111b481a5ba6f5e305717ae'
OUT = Path(os.environ.get('SINDEL_C05C_EXTERNAL_OUT', os.environ.get('RUNNER_TEMP','/tmp'))) / 'c05c_external_r4'
OUT.mkdir(parents=True, exist_ok=True)


def sha(p: Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024), b''): h.update(b)
    return h.hexdigest()


def main():
    base_path = ROOT/'C05C_T3_PREFILL_R3C.py'
    assert sha(base_path) == EXPECTED_BASE_SHA, sha(base_path)
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
      'base_exporter_sha256':EXPECTED_BASE_SHA,
      'pte':{'name':pte.name,'size':pte.stat().st_size,'sha256':sha(pte)},
      'ptd':{'name':ptd.name,'size':ptd.stat().st_size,'sha256':sha(ptd)},
      'total_bytes':pte.stat().st_size+ptd.stat().st_size,
      'input_shapes':[list(ce.shape),list(fixed.shape),list(L.shape)],
      'output_shapes':[list(lo.shape),list(k.shape),list(v.shape)],
      'external_tag':'t3_shared','dtype':'fp16','elapsed_s':time.time()-t0}
    (OUT/'C05C_T3_PREFILL_EXTERNAL_R4_EXPORT.json').write_text(json.dumps(rep,indent=2),encoding='utf-8')
    print(json.dumps(rep,indent=2))

if __name__=='__main__': main()
