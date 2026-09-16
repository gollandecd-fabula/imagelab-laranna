#!/usr/bin/env python3
import argparse, gc, hashlib, json, os, sys, unicodedata
from pathlib import Path
import numpy as np
import torch
import torch.nn as nn
from safetensors.torch import load_file as load_safetensors

W=Path(os.environ.get('SINDEL_C05C_WORK','/mnt/data/sindel_c05c_work'))
SRC=W/'source'
# Import the frozen T3 subpackage without executing chatterbox/__init__.py,
# whose unrelated top-level TTS imports pull librosa. This is import plumbing only.
import types
_pkg=types.ModuleType('chatterbox'); _pkg.__path__=[str(SRC/'chatterbox')]; sys.modules['chatterbox']=_pkg
sys.path.insert(0,str(SRC))
from chatterbox.models.t3 import T3
from chatterbox.models.t3.modules.t3_config import T3Config
from tokenizers import Tokenizer

GOLDEN_SHA='a204d69807fbf8605157fcd045cfdba2bee9002396baeb633f613065fdf1e5e0'
T3_SHA='5abca8321ede76f8e61f1cc0d19aea6c946b28871017ce8726f8a69203f05953'
TOK_SHA='df81a7ca7c31796cbe97f7a7142d5a53b12e88e12417ebe98f66602cafaf0461'
MAX_TEXT=256
TEXT_SLOTS=MAX_TEXT+2
COND_LEN=34
BOS_COUNT=2
PHYS_PREFILL=COND_LEN+TEXT_SLOTS+BOS_COUNT
MAX_SPEECH=1000
MAX_KV=PHYS_PREFILL+MAX_SPEECH

def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
 return h.hexdigest()

def load_cond():
 p=W/'golden/SINDEL_V5B_GOLDEN_CONDITIONING.npz'; assert sha(p)==GOLDEN_SHA
 with np.load(p,allow_pickle=False) as z: return torch.from_numpy(z['cond_emb']).float()

def load_t3(dtype=torch.float32):
 p=W/'model/t3_mtl23ls_v3.safetensors'; assert sha(p)==T3_SHA
 m=T3(T3Config.multilingual()); st=load_safetensors(p)
 if 'model' in st: st=st['model'][0]
 m.load_state_dict(st); m.eval().cpu(); del st; gc.collect()
 if dtype==torch.float16: m=m.half()
 return m

def tokenize_norm(text,m):
 p=W/'model/grapheme_mtl_merged_expanded_v1.json'; assert sha(p)==TOK_SHA
 tok=Tokenizer.from_file(str(p))
 # C05B frozen corpus already contains approved stress/normalization text;
 # reproduce MTLTokenizer preprocess with RU stresser bypassed exactly as C05B.
 s=unicodedata.normalize('NFKD',text.lower())
 s='[ru]'+s.replace(' ','[SPACE]')
 ids=tok.encode(s).ids
 ids=[int(m.hp.start_text_token)]+ids+[int(m.hp.stop_text_token)]
 if len(ids)>TEXT_SLOTS: raise ValueError(f'text too long: {len(ids)}>{TEXT_SLOTS}')
 return ids

class SourcePrefill(nn.Module):
 def __init__(self,m,ce):
  super().__init__(); self.text_emb=m.text_emb; self.text_pos=m.text_pos_emb; self.speech_emb=m.speech_emb; self.speech_pos=m.speech_pos_emb; self.tfmr=m.tfmr; self.head=m.speech_head; self.sot=int(m.hp.start_speech_token); self.register_buffer('cond',ce)
 def forward(self,text_tokens):
  te=self.text_emb(text_tokens)
  te=te*torch.tensor([1.0,0.0],dtype=te.dtype,device=te.device).reshape(2,1,1)
  te=te+self.text_pos(text_tokens)
  ce=self.cond.expand(2,-1,-1)
  bos=torch.tensor([[self.sot]],dtype=torch.long,device=text_tokens.device)
  be=self.speech_emb(bos)+self.speech_pos.get_fixed_embedding(torch.tensor([[0]],dtype=torch.long,device=text_tokens.device)); be=be.expand(2,-1,-1)
  inp=torch.cat([ce,te,be,be],1)
  from transformers import DynamicCache
  cache=DynamicCache()
  o=self.tfmr(inputs_embeds=inp,past_key_values=cache,use_cache=True,return_dict=True)
  logits=self.head(o.last_hidden_state[:,-1,:])
  ks=[];vs=[]
  for layer in o.past_key_values.layers:
   ks.append(layer.keys);vs.append(layer.values)
  return logits,torch.stack(ks),torch.stack(vs)

class StaticPrefillInput(nn.Module):
 """Fixed physical prefix. Golden cond_emb is an explicit input, never embedded in PTE."""
 def __init__(self,m):
  super().__init__(); self.text_emb=m.text_emb; self.text_pos=m.text_pos_emb; self.speech_emb=m.speech_emb; self.speech_pos=m.speech_pos_emb; self.tfmr=m.tfmr; self.head=m.speech_head; self.sot=int(m.hp.start_speech_token)
  self.register_buffer('text_idx',torch.arange(TEXT_SLOTS,dtype=torch.long))
  self.register_buffer('tail_idx',torch.arange(TEXT_SLOTS+BOS_COUNT,dtype=torch.long))
  self.register_buffer('all_idx',torch.arange(PHYS_PREFILL,dtype=torch.long))
  self.register_buffer('cfg_mask',torch.tensor([1.0,0.0],dtype=m.text_emb.weight.dtype).reshape(2,1,1))
 def forward(self,cond_emb,text_tokens_fixed,text_len):
  L=text_len[0]
  te=self.text_emb(text_tokens_fixed)*self.cfg_mask
  te=te+self.text_pos(text_tokens_fixed)
  ce=cond_emb.expand(2,-1,-1)
  bos=torch.tensor([[self.sot]],dtype=torch.long,device=text_tokens_fixed.device)
  be=self.speech_emb(bos)+self.speech_pos.get_fixed_embedding(torch.tensor([[0]],dtype=torch.long,device=text_tokens_fixed.device)); be=be.expand(2,-1,-1)
  text_mask=(self.tail_idx < L).reshape(1,-1,1)
  bos1=(self.tail_idx == L).reshape(1,-1,1)
  bos2=(self.tail_idx == (L+1)).reshape(1,-1,1)
  te_ext=torch.cat([te,torch.zeros((2,BOS_COUNT,te.shape[-1]),dtype=te.dtype,device=te.device)],1)
  tail=torch.where(text_mask,te_ext,torch.zeros_like(te_ext))
  tail=torch.where(bos1,be.expand(-1,tail.shape[1],-1),tail)
  tail=torch.where(bos2,be.expand(-1,tail.shape[1],-1),tail)
  inp=torch.cat([ce,tail],1)
  valid_len=torch.tensor(COND_LEN,dtype=L.dtype,device=L.device)+L+BOS_COUNT
  attn=(self.all_idx < valid_len).reshape(1,-1).expand(2,-1)
  pos=self.all_idx.reshape(1,-1).expand(2,-1)
  from transformers import DynamicCache
  cache=DynamicCache()
  o=self.tfmr(inputs_embeds=inp,attention_mask=attn,position_ids=pos,past_key_values=cache,use_cache=True,return_dict=True)
  last=(valid_len-1).reshape(1)
  h=torch.index_select(o.last_hidden_state,1,last).squeeze(1)
  logits=self.head(h)
  ks=[];vs=[]
  for layer in o.past_key_values.layers:
   ks.append(layer.keys);vs.append(layer.values)
  return logits,torch.stack(ks),torch.stack(vs)

def fixed_tokens(ids,eot):
 a=torch.full((2,TEXT_SLOTS),int(eot),dtype=torch.long)
 t=torch.tensor(ids,dtype=torch.long); a[:, :len(ids)]=t
 return a,torch.tensor([len(ids)],dtype=torch.long)

def metrics(a,b):
 af=a.float().reshape(-1); bf=b.float().reshape(-1); d=(af-bf).abs()
 cos=torch.nn.functional.cosine_similarity(af.unsqueeze(0),bf.unsqueeze(0)).item()
 return {'cosine':cos,'mean_abs':d.mean().item(),'max_abs':d.max().item()}

def source_static_parity(dtype, phrases):
 m=load_t3(dtype); ce=load_cond().to(dtype)
 src=SourcePrefill(m,ce).eval(); sta=StaticPrefillInput(m).eval()
 rows=[]
 with torch.no_grad():
  for pid,text in phrases:
   ids=tokenize_norm(text,m); actual=torch.tensor([ids,ids],dtype=torch.long)
   fixed,L=fixed_tokens(ids,m.hp.stop_text_token)
   slo,sk,sv=src(actual); wlo,wk,wv=sta(ce,fixed,L)
   sem=COND_LEN+len(ids)+BOS_COUNT
   row={'id':pid,'text_len':len(ids),'semantic_prefill_len':sem,'logits':metrics(slo,wlo),'k':metrics(sk,wk[:,:,:,:sem,:]),'v':metrics(sv,wv[:,:,:,:sem,:])}
   rows.append(row); print(json.dumps(row))
 return rows,m,sta

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--mode',choices=['parity-fp32','export','pte-parity'],required=True); ap.add_argument('--out',default=str(W/'out/t3_prefill.pte')); args=ap.parse_args()
 phrases=[]
 if args.mode!='export':
  corpus=json.loads((W/'golden/evidence/V5B_VOICE_GATE_CORPUS_FREEZE_R3.json').read_text())
  for x in corpus['phrases']:
   phrases.append((x['id'],x.get('pronunciation_text') or x.get('normalized') or x['text']))
 if args.mode=='parity-fp32':
  rows,_,_=source_static_parity(torch.float32,phrases)
  thr=json.loads((W/'evidence/C05C_EXPORT_CONTRACT_FREEZE_R3.json').read_text())['parity_thresholds_frozen_before_candidate']['source_fp32_vs_static_wrapper_fp32']
  ok=all(r['logits']['cosine']>=thr['logits_cosine_min'] and r['logits']['mean_abs']<=thr['logits_mean_abs_max'] and r['logits']['max_abs']<=thr['logits_max_abs_max'] and r['k']['mean_abs']<=thr['kv_mean_abs_max'] and r['k']['max_abs']<=thr['kv_max_abs_max'] and r['v']['mean_abs']<=thr['kv_mean_abs_max'] and r['v']['max_abs']<=thr['kv_max_abs_max'] for r in rows)
  report={'schema':'sindel.cp034.c05c.t3-prefill-source-static-parity.r3','dtype':'float32','thresholds':thr,'phrases':rows,'status':'PASS' if ok else 'FAIL'}
  p=W/'evidence/C05C_T3_PREFILL_SOURCE_STATIC_PARITY_R3.json'; p.write_text(json.dumps(report,indent=2),encoding='utf-8'); print('REPORT',p,sha(p),report['status']); raise SystemExit(0 if ok else 2)
 if args.mode=='export':
  m=load_t3(torch.float16); sta=StaticPrefillInput(m).eval()
  ce=torch.zeros((1,COND_LEN,1024),dtype=torch.float16)
  fixed=torch.zeros((2,TEXT_SLOTS),dtype=torch.long); L=torch.tensor([66],dtype=torch.long)
  with torch.no_grad():
   lo,k,v=sta(ce,fixed,L); assert torch.isfinite(lo).all() and torch.isfinite(k).all() and torch.isfinite(v).all()
  from torch.export import export
  from executorch.exir import to_edge_transform_and_lower, EdgeCompileConfig
  from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
  ep=export(sta,(ce,fixed,L))
  edge=to_edge_transform_and_lower(ep,compile_config=EdgeCompileConfig(_check_ir_validity=False),partitioner=[XnnpackPartitioner()])
  et=edge.to_executorch(); out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(et.buffer)
  rep={'schema':'sindel.cp034.c05c.t3-prefill-export.r3c','path':str(out),'sha256':sha(out),'size':out.stat().st_size,'input_shapes':[list(ce.shape),list(fixed.shape),list(L.shape)],'output_shapes':[list(lo.shape),list(k.shape),list(v.shape)],'dtype':'fp16','status':'EXPORTED_NOT_YET_PTE_PARITY'}
  rp=W/'evidence/C05C_T3_PREFILL_EXPORT_R3.json'; rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(rep,indent=2),encoding='utf-8'); print(json.dumps(rep)); return
 if args.mode=='pte-parity':
  m=load_t3(torch.float16); ce=load_cond().half(); sta=StaticPrefillInput(m).eval()
  from executorch.runtime import Runtime
  prog=Runtime.get().load_program(args.out); method=prog.load_method('forward')
  rows=[]
  with torch.no_grad():
   for pid,text in phrases:
    ids=tokenize_norm(text,m); fixed,L=fixed_tokens(ids,m.hp.stop_text_token)
    wlo,wk,wv=sta(ce,fixed,L)
    po=method.execute([ce.contiguous(),fixed.contiguous(),L.contiguous()])
    plo,pk,pv=po[0],po[1],po[2]
    row={'id':pid,'text_len':len(ids),'logits':metrics(wlo,plo),'k':metrics(wk,pk),'v':metrics(wv,pv),'finite':bool(torch.isfinite(plo).all() and torch.isfinite(pk).all() and torch.isfinite(pv).all())}
    rows.append(row); print(json.dumps(row))
  thr=json.loads((W/'evidence/C05C_EXPORT_CONTRACT_FREEZE_R3.json').read_text())['parity_thresholds_frozen_before_candidate']['wrapper_fp16_vs_pte_fp16']
  ok=all(r['finite'] and r['logits']['cosine']>=thr['logits_cosine_min'] and r['logits']['mean_abs']<=thr['logits_mean_abs_max'] and r['logits']['max_abs']<=thr['logits_max_abs_max'] and r['k']['mean_abs']<=thr['kv_mean_abs_max'] and r['k']['max_abs']<=thr['kv_max_abs_max'] and r['v']['mean_abs']<=thr['kv_mean_abs_max'] and r['v']['max_abs']<=thr['kv_max_abs_max'] for r in rows)
  report={'schema':'sindel.cp034.c05c.t3-prefill-pte-parity.r3c','pte_sha256':sha(Path(args.out)),'thresholds':thr,'phrases':rows,'status':'PASS' if ok else 'FAIL'}
  rp=W/'evidence/C05C_T3_PREFILL_PTE_PARITY_R3.json'; rp.write_text(json.dumps(report,indent=2),encoding='utf-8'); print('REPORT',rp,sha(rp),report['status']); raise SystemExit(0 if ok else 3)

if __name__=='__main__': main()
