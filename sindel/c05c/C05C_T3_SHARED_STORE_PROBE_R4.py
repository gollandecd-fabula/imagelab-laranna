#!/usr/bin/env python3
from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GATE = ROOT / "C05C_T3_PREFILL_EXTERNAL_GATE_R4.json"
OUT = Path(os.environ.get("SINDEL_C05C_SHARED_OUT", os.environ.get("RUNNER_TEMP", "/tmp"))) / "c05c_shared_store_r4"
OUT.mkdir(parents=True, exist_ok=True)

EXPECTED_PREFILL_PTE_SHA = "7b957ceb1917f1f5332df96b44711096c02daed037d6fa460d0b0639b8d377d9"
EXPECTED_PREFILL_PTD_SHA = "a92e69a80f25e304ebe4a50c9e55e5457e381d0048d8e51debdab5b4dd3a0ea9"
THRESHOLDS = {"cosine_min": 0.9999, "mean_abs_max": 0.005, "max_abs_max": 0.05}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def require_gate() -> None:
    d = json.loads(GATE.read_text(encoding="utf-8"))
    errors = []
    if d.get("schema") != "sindel.cp034.c05c.external-prefill-gate-r4.v1": errors.append("schema")
    if d.get("status") != "PASS_L2": errors.append("status")
    if d.get("pte", {}).get("sha256") != EXPECTED_PREFILL_PTE_SHA: errors.append("pte.sha256")
    if d.get("ptd", {}).get("sha256") != EXPECTED_PREFILL_PTD_SHA: errors.append("ptd.sha256")
    if d.get("real_executorch_forward") is not True: errors.append("real_executorch_forward")
    for p in ("P1", "P2", "P3"):
        if d.get("private_parity", {}).get(p, {}).get("status") != "PASS_L2": errors.append(f"{p}.status")
        if not d.get("private_parity", {}).get(p, {}).get("evidence_sha256"): errors.append(f"{p}.evidence")
    if d.get("private_golden_published") is not False: errors.append("private_golden_published")
    if errors:
        raise SystemExit("FAIL-CLOSED: external prefill gate invalid: " + ", ".join(errors))


require_gate()

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
from executorch.exir import EdgeCompileConfig, to_edge_transform_and_lower
from executorch.exir._serialize._named_data_store import NamedDataStore
from executorch.exir.passes.external_constants_pass import delegate_external_constants_pass_unlifted
from executorch.extension.pybindings.portable_lib import _load_for_executorch_from_buffer
from torch.export import export

sys.path.insert(0, str(ROOT))
import C05C_T3_PREFILL_R3C as base

N_LAYERS = 30
N_HEADS = 16
HD = 64
DIM = 1024
SPEECH_VOCAB = 8194
MAX_SPEECH = 1000
PREFILL_LEN = base.PHYS_PREFILL
MAX_KV = PREFILL_LEN + MAX_SPEECH
DELTA_SHAPE = (N_LAYERS, 2, N_HEADS, 1, HD)


def rotate_half(x: torch.Tensor) -> torch.Tensor:
    half = x.shape[-1] // 2
    return torch.cat([-x[..., half:], x[..., :half]], dim=-1)


class Layer(nn.Module):
    def __init__(self, h):
        super().__init__()
        def lin(src):
            z = nn.Linear(src.in_features, src.out_features, bias=False)
            z.weight = nn.Parameter(src.weight.data.clone(), requires_grad=False)
            return z
        self.q = lin(h.self_attn.q_proj)
        self.k = lin(h.self_attn.k_proj)
        self.v = lin(h.self_attn.v_proj)
        self.o = lin(h.self_attn.o_proj)
        self.g = lin(h.mlp.gate_proj)
        self.u = lin(h.mlp.up_proj)
        self.d = lin(h.mlp.down_proj)
        self.register_buffer("ln1", h.input_layernorm.weight.data.clone())
        self.register_buffer("ln2", h.post_attention_layernorm.weight.data.clone())


class T3DecodeStorageProbe(nn.Module):
    """R29 compact-delta decode math, used only to prove shared external storage feasibility."""
    def __init__(self, model):
        super().__init__()
        self.speech_emb = model.speech_emb
        self.speech_pos = model.speech_pos_emb
        self.layers = nn.ModuleList([Layer(x) for x in model.tfmr.layers])
        self.head = nn.Linear(DIM, SPEECH_VOCAB, bias=False)
        self.head.weight = nn.Parameter(model.speech_head.weight.data.clone(), requires_grad=False)
        self.register_buffer("norm", model.tfmr.norm.weight.data.clone())
        self.eps = float(model.cfg.rms_norm_eps)
        inv = model.tfmr.rotary_emb.inv_freq.float()
        pos = torch.arange(MAX_KV, dtype=torch.float32)
        freq = torch.outer(pos, inv)
        emb = torch.cat([freq, freq], -1)
        self.register_buffer("rcos", emb.cos())
        self.register_buffer("rsin", emb.sin())
        self.register_buffer("kvpos", torch.arange(MAX_KV))

    def rms(self, x, w):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps) * w

    def forward(self, prev_token, speech_pos, kv_k, kv_v):
        sp = speech_pos[0]
        x = self.speech_emb(prev_token) + self.speech_pos.get_fixed_embedding(sp.reshape(1, 1))
        x = torch.cat([x, x], dim=0)
        write = torch.tensor(PREFILL_LEN, dtype=torch.long, device=x.device) + (sp - 1)
        valid = self.kvpos <= write
        bias = torch.where(
            valid,
            torch.zeros(MAX_KV, dtype=x.dtype, device=x.device),
            torch.full((MAX_KV,), float("-inf"), dtype=x.dtype, device=x.device),
        ).reshape(1, 1, 1, MAX_KV)
        wi = write.reshape(1)
        cw = torch.index_select(self.rcos, 0, wi).reshape(1, 1, 1, HD)
        sw = torch.index_select(self.rsin, 0, wi).reshape(1, 1, 1, HD)
        score_pm = (self.kvpos == write).reshape(1, 1, 1, MAX_KV)
        value_pm = (self.kvpos == write).reshape(1, 1, MAX_KV, 1)
        nks, nvs = [], []
        for i, layer in enumerate(self.layers):
            r = x
            xn = self.rms(x, layer.ln1)
            q = layer.q(xn).view(2, 1, N_HEADS, HD).permute(0, 2, 1, 3)
            k = layer.k(xn).view(2, 1, N_HEADS, HD).permute(0, 2, 1, 3)
            v = layer.v(xn).view(2, 1, N_HEADS, HD).permute(0, 2, 1, 3)
            q = q * cw + rotate_half(q) * sw
            k = k * cw + rotate_half(k) * sw
            nks.append(k); nvs.append(v)
            base_scores = torch.matmul(q, kv_k[i].transpose(-2, -1)) * (HD ** -0.5) + bias
            current_score = torch.matmul(q, k.transpose(-2, -1)) * (HD ** -0.5)
            scores = torch.where(score_pm, current_score, base_scores)
            att = F.softmax(scores, dim=-1)
            uv = torch.where(value_pm, v.expand(2, N_HEADS, MAX_KV, HD), kv_v[i])
            ao = torch.matmul(att, uv)
            ao = ao.permute(0, 2, 1, 3).reshape(2, 1, DIM)
            x = layer.o(ao) + r
            r = x
            xn = self.rms(x, layer.ln2)
            x = layer.d(F.silu(layer.g(xn)) * layer.u(xn)) + r
        x = self.rms(x, self.norm)
        return self.head(x[:, -1, :]), torch.stack(nks), torch.stack(nvs)


def make_tagged_edge(module: nn.Module, args):
    first = export(module, args, strict=False)
    gm = first.module()
    delegate_external_constants_pass_unlifted(gm, gen_tag_fn=lambda node: "t3_shared")
    tagged = 0
    for sub in gm.modules():
        if isinstance(sub, torch.fx.GraphModule):
            for n in sub.graph.nodes:
                if n.op == "get_attr" and n.meta.get("custom", {}).get("delegate_constant_tag") == "t3_shared":
                    tagged += 1
    if tagged == 0:
        raise SystemExit("FAIL-CLOSED: storage probe tagged zero delegate constants")
    ep = export(gm, args, strict=False)
    edge = to_edge_transform_and_lower(
        ep,
        compile_config=EdgeCompileConfig(_check_ir_validity=False),
        partitioner=[XnnpackPartitioner()],
    )
    return edge, tagged


def compare(a: torch.Tensor, b: torch.Tensor, name: str) -> dict:
    aa = a.detach().cpu().numpy().astype(np.float64, copy=False).reshape(-1)
    bb = b.detach().cpu().numpy().astype(np.float64, copy=False).reshape(-1)
    finite = bool(np.isfinite(aa).all() and np.isfinite(bb).all())
    na = float(np.linalg.norm(aa)); nb = float(np.linalg.norm(bb))
    cosine = 1.0 if na == 0.0 and nb == 0.0 else float(np.dot(aa, bb) / (na * nb))
    diff = np.abs(aa - bb)
    mean_abs = float(diff.mean())
    max_abs = float(diff.max())
    accepted = finite and cosine >= THRESHOLDS["cosine_min"] and mean_abs <= THRESHOLDS["mean_abs_max"] and max_abs <= THRESHOLDS["max_abs_max"]
    return {"name": name, "finite": finite, "cosine_raw": cosine, "mean_abs": mean_abs, "max_abs": max_abs, "accepted": accepted}


def main() -> None:
    t0 = time.time()
    model = base.load_t3(torch.float16)
    pre = base.StaticPrefillInput(model).eval()
    dec = T3DecodeStorageProbe(model).eval().half()

    ce = torch.zeros((1, base.COND_LEN, 1024), dtype=torch.float16)
    fixed = torch.zeros((2, base.TEXT_SLOTS), dtype=torch.long)
    text_len = torch.tensor([66], dtype=torch.long)
    prev = torch.tensor([[int(model.hp.start_speech_token)]], dtype=torch.long)
    spos = torch.tensor([1], dtype=torch.long)
    kv_k = torch.zeros((N_LAYERS, 2, N_HEADS, MAX_KV, HD), dtype=torch.float16)
    kv_v = torch.zeros_like(kv_k)

    with torch.inference_mode():
        src_pre = pre(ce, fixed, text_len)
        src_dec = dec(prev, spos, kv_k, kv_v)
    if [list(x.shape) for x in src_pre] != [[2, SPEECH_VOCAB], [N_LAYERS,2,N_HEADS,PREFILL_LEN,HD], [N_LAYERS,2,N_HEADS,PREFILL_LEN,HD]]:
        raise SystemExit("FAIL-CLOSED: source prefill probe shape mismatch")
    if [list(x.shape) for x in src_dec] != [[2, SPEECH_VOCAB], list(DELTA_SHAPE), list(DELTA_SHAPE)]:
        raise SystemExit("FAIL-CLOSED: source decode probe shape mismatch")

    edge_pre, tagged_pre = make_tagged_edge(pre, (ce, fixed, text_len))
    edge_dec, tagged_dec = make_tagged_edge(dec, (prev, spos, kv_k, kv_v))

    merged = NamedDataStore()
    merged.merge_named_data_store(edge_pre._named_data_store.get_named_data_store_output())
    pre_store = merged.get_named_data_store_output()
    pre_unique_buffers = len(pre_store.buffers)
    merged.merge_named_data_store(edge_dec._named_data_store.get_named_data_store_output())
    union_store = merged.get_named_data_store_output()
    union_unique_buffers = len(union_store.buffers)
    union_keys = len(union_store.external_data.get("t3_shared", {}))
    if union_keys == 0:
        raise SystemExit("FAIL-CLOSED: merged t3_shared store is empty")

    # Both independent programs serialize exactly the same merged external store.
    edge_pre._named_data_store = merged
    edge_dec._named_data_store = merged
    et_pre = edge_pre.to_executorch()
    et_dec = edge_dec.to_executorch()
    if sorted(et_pre._tensor_data.keys()) != ["t3_shared"] or sorted(et_dec._tensor_data.keys()) != ["t3_shared"]:
        raise SystemExit("FAIL-CLOSED: merged programs did not expose one t3_shared external store")

    pre_pte = OUT / "t3_prefill_shared_probe_r4.pte"
    dec_pte = OUT / "t3_decode_shared_probe_r4.pte"
    pre_ptd = OUT / "t3_shared_from_prefill.ptd"
    dec_ptd = OUT / "t3_shared_from_decode.ptd"
    with pre_pte.open("wb") as f: et_pre.write_to_file(f)
    with dec_pte.open("wb") as f: et_dec.write_to_file(f)
    pre_ptd.write_bytes(bytes(et_pre._tensor_data["t3_shared"]))
    dec_ptd.write_bytes(bytes(et_dec._tensor_data["t3_shared"]))

    pre_ptd_sha = sha_file(pre_ptd); dec_ptd_sha = sha_file(dec_ptd)
    if pre_ptd_sha != dec_ptd_sha or pre_ptd.stat().st_size != dec_ptd.stat().st_size:
        raise SystemExit("FAIL-CLOSED: prefill/decode did not serialize a byte-identical shared PTD")

    # Free compiler/model structures before real runtime loading.
    del et_pre, et_dec, edge_pre, edge_dec, merged, pre, dec, model
    gc.collect()

    ptd_bytes = pre_ptd.read_bytes()
    pre_mod = _load_for_executorch_from_buffer(pre_pte.read_bytes(), ptd_bytes)
    with torch.inference_mode(): et_pre_out = pre_mod.forward((ce, fixed, text_len))
    del pre_mod
    gc.collect()
    dec_mod = _load_for_executorch_from_buffer(dec_pte.read_bytes(), ptd_bytes)
    with torch.inference_mode(): et_dec_out = dec_mod.forward((prev, spos, kv_k, kv_v))

    pre_cmp = [compare(src_pre[i], et_pre_out[i], n) for i,n in enumerate(("logits","k","v"))]
    dec_cmp = [compare(src_dec[i], et_dec_out[i], n) for i,n in enumerate(("logits","k_delta","v_delta"))]
    pre_ok = all(x["accepted"] for x in pre_cmp)
    dec_ok = all(x["accepted"] for x in dec_cmp)
    runtime_ok = all(torch.isfinite(x).all() for x in et_pre_out) and all(torch.isfinite(x).all() for x in et_dec_out)

    result = {
        "schema": "sindel.cp034.c05c.t3-shared-store-probe-r4.v1",
        "status": "PASS_L2" if pre_ok and dec_ok and runtime_ok else "FAIL",
        "scope": "storage/runtime feasibility probe; not production decode acceptance",
        "external_tag": "t3_shared",
        "tagged_get_attrs": {"prefill": tagged_pre, "decode": tagged_dec},
        "store": {
            "prefill_unique_buffers_before_union": pre_unique_buffers,
            "union_unique_buffers": union_unique_buffers,
            "union_external_keys": union_keys,
            "shared_ptd_size": pre_ptd.stat().st_size,
            "shared_ptd_sha256": pre_ptd_sha,
            "byte_identical_from_both_programs": True,
        },
        "pte": {
            "prefill": {"size": pre_pte.stat().st_size, "sha256": sha_file(pre_pte)},
            "decode_probe": {"size": dec_pte.stat().st_size, "sha256": sha_file(dec_pte)},
        },
        "runtime": {
            "same_ptd_bytes_used_for_both": True,
            "prefill_real_forward": True,
            "decode_real_forward": True,
            "all_finite": runtime_ok,
            "prefill_comparisons": pre_cmp,
            "decode_comparisons": dec_cmp,
        },
        "max_kv": MAX_KV,
        "elapsed_s": time.time() - t0,
        "golden_used": False,
        "private_golden_published": False,
    }
    (OUT / "C05C_T3_SHARED_STORE_PROBE_R4.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "PASS_L2":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
