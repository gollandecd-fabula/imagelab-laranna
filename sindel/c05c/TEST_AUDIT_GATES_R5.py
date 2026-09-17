"""L1 regression tests; synthetic arrays do not qualify model/runtime output."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import C05C_T3_SHARED_STORE_ISOLATED_R4 as gate

class ComparatorTests(unittest.TestCase):
    def test_equal_and_zero(self):
        for a in (np.ones((2,3),dtype=np.float16),np.zeros((2,3),dtype=np.float16)):
            self.assertTrue(gate.compare_arrays(a,a,'k')['accepted'])
    def test_shape(self):
        self.assertFalse(gate.compare_arrays(np.ones((2,3)),np.ones((3,2)),'k')['accepted'])
    def test_dtype(self):
        self.assertFalse(gate.compare_arrays(np.ones(3,dtype=np.float16),np.ones(3,dtype=np.float32),'k')['accepted'])
    def test_empty(self):
        self.assertFalse(gate.compare_arrays(np.array([]),np.array([]),'k')['accepted'])
    def test_nonfinite(self):
        for x in (np.nan,np.inf,-np.inf):
            r=gate.compare_arrays(np.array([x]),np.array([x]),'k')
            self.assertFalse(r['accepted']); json.dumps(r,allow_nan=False)
    def test_integer_exact(self):
        a=np.array([2**62,2**62+1],dtype=np.int64)
        self.assertFalse(gate.compare_arrays(a,a[::-1],'k')['accepted'])
        self.assertTrue(gate.compare_arrays(a,a,'k')['accepted'])
    def test_cfg_top1(self):
        a=np.array([[1.001,1.0],[1.0,1.0]],dtype=np.float32)
        b=a[:,::-1].copy()
        self.assertTrue(gate.compare_arrays(a,b,'k')['accepted'])
        self.assertFalse(gate.compare_arrays(a,b,'logits')['accepted'])
    def test_cfg_combined_not_raw(self):
        a=np.array([[1.0,1.00001],[0.0,0.001]],dtype=np.float32)
        b=np.array([[1.0,1.00001],[0.001,0.0]],dtype=np.float32)
        self.assertEqual(a[0].argmax(),b[0].argmax())
        self.assertFalse(gate.compare_arrays(a,b,'logits')['accepted'])
    def test_large_finite_overflow(self):
        r=gate.compare_arrays(np.array([1e308]),np.array([1e308]),'k')
        self.assertFalse(r['accepted']); json.dumps(r,allow_nan=False)
    def test_threshold_failure(self):
        self.assertFalse(gate.compare_arrays(np.ones(4),np.ones(4)*1.1,'k')['accepted'])

class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.out=patch.object(gate,'OUT',Path(self.tmp.name));self.out.start();self.addCleanup(self.out.stop)
    def result(self): return json.loads((gate.OUT/'test/stage_result.json').read_text())
    def test_rejection_retained(self):
        with self.assertRaises(RuntimeError):
            gate.stage_guard('test',lambda:{'comparison':[{'accepted':False,'max_abs':0.3}]})
        r=self.result();self.assertEqual(r['status'],'FAIL');self.assertEqual(r['comparison'][0]['max_abs'],0.3)
        self.assertEqual(r['execution_status'],'COMPLETED')
    def test_explicit_fail_not_overwritten(self):
        with self.assertRaises(RuntimeError):gate.stage_guard('test',lambda:{'status':'FAIL'})
        self.assertEqual(self.result()['status'],'FAIL')
    def test_forward_scope(self):
        gate.stage_guard('test',lambda:{'fresh_process_real_executorch_forward':True})
        self.assertEqual(self.result()['numerical_status'],'NOT_EVALUATED')
    def test_retry_failure_replaces_success(self):
        gate.stage_guard('test',lambda:{'accepted':True})
        def fail(): raise ValueError('injected')
        with self.assertRaises(ValueError):gate.stage_guard('test',fail)
        self.assertEqual(self.result()['execution_status'],'FAILED')
    def test_missing_prerequisite_replaces_final(self):
        path=gate.OUT/'C05C_T3_SHARED_STORE_ISOLATED_R4_FINAL.json'
        gate.write_json(path,{'status':'PASS_L2'})
        with patch.object(gate,'require_gate',return_value={}):
            with self.assertRaises(RuntimeError):gate.stage_guard('06_verify',gate.verify)
        self.assertEqual(json.loads(path.read_text())['status'],'FAIL')
    def test_failed_final_report_saved(self):
        for stage in ('01_export_prefill','02_export_decode','03_merge_store','04_runtime_prefill','05_runtime_decode'):
            gate.write_json(gate.stage_dir(stage)/'stage_result.json',{'status':'PASS','union_ptd_sha256':'test','union_ptd':{'sha256':'test','size':1}})
        a=np.ones((2,3),dtype=np.float16)
        for stage,keys,delta in [('01_export_prefill',('logits','k','v'),0),('02_export_decode',('logits','k_delta','v_delta'),0),('04_runtime_prefill',('logits','k','v'),1),('05_runtime_decode',('logits','k_delta','v_delta'),1)]:
            np.savez(gate.stage_dir(stage)/('source_outputs.npz' if stage[:2] in ('01','02') else 'runtime_outputs.npz'),**{k:a+delta for k in keys})
        with patch.object(gate,'require_gate',return_value={}):
            with self.assertRaises(RuntimeError):gate.stage_guard('06_verify',gate.verify)
        r=json.loads((gate.OUT/'C05C_T3_SHARED_STORE_ISOLATED_R4_FINAL.json').read_text())
        self.assertEqual(r['status'],'FAIL');self.assertEqual(len(r['prefill']['comparison']),3)
        self.assertEqual(len(r['decode_probe']['comparison']),3)

class StoreDiagnosisTests(unittest.TestCase):
    setUp = StageTests.setUp
    def make_ab(self, mismatch=False):
        for stage,kind in [('04a_runtime_prefill_original','original'),('04_runtime_prefill','union'),('05a_runtime_decode_original','original'),('05_runtime_decode','union')]:
            base={'status':'FAIL','execution_status':'COMPLETED','numerical_status':'FAIL','pte_sha256':'same-pte','input_fingerprint':'same-input','union_ptd_sha256':kind}
            if mismatch and kind=='union':base['input_fingerprint']='other-input'
            gate.write_json(gate.stage_dir(stage)/'stage_result.json',base)
            keys=('logits','k','v') if 'prefill' in stage else ('logits','k_delta','v_delta')
            np.savez(gate.stage_dir(stage)/'runtime_outputs.npz',**{k:np.ones((2,3),dtype=np.float16) for k in keys})
    def test_store_agreement_does_not_qualify_source(self):
        import C05C_COMPARE_STORES_R5 as ab
        self.make_ab();r=ab.diagnose()
        self.assertEqual(r['status'],'COMPLETED')
        self.assertEqual(r['stages']['prefill']['original_source_parity'],'FAIL')
        self.assertEqual(r['stages']['prefill']['diagnosis'],'STORE_MERGE_NOT_CAUSE_FOR_THIS_INPUT')
    def test_different_inputs_block_ab(self):
        import C05C_COMPARE_STORES_R5 as ab
        self.make_ab(mismatch=True);self.assertEqual(ab.diagnose()['status'],'BLOCKED')
    def test_missing_outputs_block_ab(self):
        import C05C_COMPARE_STORES_R5 as ab
        self.make_ab();(gate.stage_dir('04_runtime_prefill')/'runtime_outputs.npz').unlink()
        self.assertEqual(ab.diagnose()['status'],'BLOCKED')

if __name__=='__main__':unittest.main(verbosity=2)
