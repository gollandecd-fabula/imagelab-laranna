"""Diagnose XNNPACK partition-boundary rounding, without changing frozen candidates.
Uses the exact frozen model/wrapper and public export inputs. Not qualification.
"""
import argparse
import gc
import json
import os
from pathlib import Path
import C05C_T3_SHARED_STORE_ISOLATED_R4 as base

def export_probe():
    base.require_gate()
    np, torch, nn, F, Partitioner, Config, lower, tag, export = base.import_export_stack()
    model_base = base.load_base(torch)
    model = model_base.load_t3(torch.float16)
    wrapper = model_base.StaticPrefillInput(model).eval()
    inputs=(torch.zeros((1,model_base.COND_LEN,1024),dtype=torch.float16),torch.zeros((2,model_base.TEXT_SLOTS),dtype=torch.long),torch.tensor([66],dtype=torch.long))
    outdir=base.OUT/'partition_diagnostic_r5';outdir.mkdir(parents=True,exist_ok=True)
    with torch.inference_mode(): source=tuple(x.detach().cpu().numpy().copy() for x in wrapper(*inputs))
    captured=export(wrapper,inputs,strict=False)
    with torch.inference_mode(): captured_outputs=tuple(x.detach().cpu().numpy().copy() for x in captured.module()(*inputs))
    source_capture=[base.compare_arrays(a,b,k) for a,b,k in zip(source,captured_outputs,('logits','k','v'))]
    report={'schema':'sindel.partition-diagnostic.r5','scope':'diagnostic candidate only; frozen original hashes and thresholds unchanged','source_vs_capture':source_capture,'thresholds':base.THRESHOLDS,'status':'IN_PROGRESS'}
    path=outdir/'C05C_PARTITION_DIAGNOSTIC_R5.json';base.write_json(path,report)
    gm=captured.module()
    tag(module=gm,gen_tag_fn=lambda node:'t3_shared')
    tagged=export(gm,inputs,strict=False)
    edge=lower(tagged,compile_config=Config(_check_ir_validity=False),partitioner=[Partitioner(per_op_mode=True)])
    pte,ptd,manifest=base.write_program_and_store(edge,outdir,'prefill_per_op_diagnostic.pte')
    report.update(pte={'sha256':base.sha_file(pte),'size':pte.stat().st_size},ptd={'sha256':base.sha_file(ptd),'size':ptd.stat().st_size},store=manifest)
    # Avoid co-resident exporter/runtime peaks; disk outputs are the handoff.
    np.savez(outdir/'source_outputs.npz',**dict(zip(('logits','k','v'),source)))
    report['source_outputs_sha256']=base.sha_file(outdir/'source_outputs.npz')
    base.write_json(path,report)
    return report

def runtime_probe():
    import numpy as np
    import torch
    base.require_gate()
    outdir=base.OUT/'partition_diagnostic_r5'
    path=outdir/'C05C_PARTITION_DIAGNOSTIC_R5.json'
    report=json.loads(path.read_text())
    pte,ptd=outdir/'prefill_per_op_diagnostic.pte',outdir/'t3_shared.ptd'
    if base.sha_file(pte)!=report['pte']['sha256'] or base.sha_file(ptd)!=report['ptd']['sha256']:
        raise RuntimeError('diagnostic candidate changed')
    if base.sha_file(outdir/'source_outputs.npz')!=report['source_outputs_sha256']:
        raise RuntimeError('diagnostic source outputs changed')
    with np.load(outdir/'source_outputs.npz',allow_pickle=False) as z:
        source=tuple(z[k] for k in ('logits','k','v'))
    inputs=(torch.zeros((1,34,1024),dtype=torch.float16),torch.zeros((2,258),dtype=torch.long),torch.tensor([66],dtype=torch.long))
    from executorch.extension.pybindings.portable_lib import _load_for_executorch_from_buffer
    pte_bytes,ptd_bytes=pte.read_bytes(),ptd.read_bytes()
    module=_load_for_executorch_from_buffer(pte_bytes,ptd_bytes)
    with torch.inference_mode(): outputs=module.forward(inputs)
    comparison=[base.compare_arrays(a,b.cpu().numpy(),k) for a,b,k in zip(source,outputs,('logits','k','v'))]
    report.update(comparison=comparison,status='DIAGNOSTIC_MATCH' if len(outputs)==3 and all(c['accepted'] for c in comparison) else 'DIAGNOSTIC_MISMATCH',production_qualified=False)
    base.write_json(path,report)
    print(json.dumps({k:v for k,v in report.items() if k!='store'},indent=2))
    return report
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('export','runtime'))
    args=parser.parse_args()
    if args.command=='export':export_probe()
    else:
        result=runtime_probe()
        raise SystemExit(0 if result['status']=='DIAGNOSTIC_MATCH' else 2)
