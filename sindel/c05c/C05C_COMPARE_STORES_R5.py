"""Read-only A/B diagnosis; agreement between stores is not source parity."""
import json
import numpy as np
import C05C_T3_SHARED_STORE_ISOLATED_R4 as base

def diagnose():
    report={'schema':'sindel.c05c.original-union-ab.r5','scope':'diagnosis only; not production qualification','stages':{},'status':'COMPLETED'}
    for kind, original, union, keys in (
        ('prefill','04a_runtime_prefill_original','04_runtime_prefill',('logits','k','v')),
        ('decode_probe','05a_runtime_decode_original','05_runtime_decode',('logits','k_delta','v_delta'))):
        try:
            a=base.load_stage_result(original,allow_completed=True)
            b=base.load_stage_result(union,allow_completed=True)
            if a['pte_sha256']!=b['pte_sha256'] or a['input_fingerprint']!=b['input_fingerprint']:
                raise ValueError('A/B PTE or input identity mismatch')
            with np.load(base.stage_dir(original)/'runtime_outputs.npz',allow_pickle=False) as av, np.load(base.stage_dir(union)/'runtime_outputs.npz',allow_pickle=False) as bv:
                comparisons=[{**base.compare_arrays(av[k],bv[k],k),'bit_exact':av[k].dtype==bv[k].dtype and av[k].shape==bv[k].shape and av[k].tobytes()==bv[k].tobytes()} for k in keys]
            exact=all(c['bit_exact'] for c in comparisons)
            report['stages'][kind]={'pte_sha256':a['pte_sha256'],'input_fingerprint':a['input_fingerprint'],'original_ptd_sha256':a['union_ptd_sha256'],'union_ptd_sha256':b['union_ptd_sha256'],'original_source_parity':a['numerical_status'],'union_source_parity':b['numerical_status'],'original_vs_union':comparisons,'diagnosis':'STORE_MERGE_NOT_CAUSE_FOR_THIS_INPUT' if exact else 'STORE_DEPENDENT_DIFFERENCE_REQUIRES_INVESTIGATION'}
        except Exception as exc:
            report['stages'][kind]={'status':'BLOCKED','exception':str(exc)}
            report['status']='BLOCKED'
    base.write_json(base.OUT/'C05C_ORIGINAL_UNION_AB_R5.json',report)
    return report
if __name__=='__main__':
    r=diagnose()
    print(json.dumps(r,indent=2))
    raise SystemExit(0 if r['status']=='COMPLETED' else 2)
