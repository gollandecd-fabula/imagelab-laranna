#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GATE = ROOT / "C05C_T3_PREFILL_EXTERNAL_GATE_R4.json"
OUT = Path(os.environ.get("SINDEL_C05C_SHARED_OUT", os.environ.get("RUNNER_TEMP", "/tmp"))) / "c05c_shared_store_isolated_r4"
OUT.mkdir(parents=True, exist_ok=True)

EXPECTED_PREFILL_PTE_SHA = "7b957ceb1917f1f5332df96b44711096c02daed037d6fa460d0b0639b8d377d9"
EXPECTED_PREFILL_PTE_SIZE = 35317600
EXPECTED_PREFILL_PTD_SHA = "a92e69a80f25e304ebe4a50c9e55e5457e381d0048d8e51debdab5b4dd3a0ea9"
EXPECTED_PREFILL_PTD_SIZE = 1023446912
EXPECTED_COMPARATOR_SHA = "07edd15b3fcdf3af533b0b9090de8e20918997793b20a3b267665bcb09539c13"
THRESHOLDS = {"cosine_min": 0.9999, "mean_abs_max": 0.005, "max_abs_max": 0.05, "finite_required": True}

N_LAYERS = 30
N_HEADS = 16
HD = 64
DIM = 1024
SPEECH_VOCAB = 8194
MAX_SPEECH = 1000


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def require_gate() -> dict:
    if not GATE.is_file():
        raise RuntimeError("external-prefill qualification gate is absent")
    d = json.loads(GATE.read_text(encoding="utf-8"))
    errors = []
    if d.get("schema") != "sindel.cp034.c05c.external-prefill-gate-r4.v1": errors.append("schema")
    if d.get("status") != "PASS_L2": errors.append("status")
    if d.get("pte", {}).get("sha256") != EXPECTED_PREFILL_PTE_SHA: errors.append("pte.sha256")
    if d.get("pte", {}).get("size") != EXPECTED_PREFILL_PTE_SIZE: errors.append("pte.size")
    if d.get("ptd", {}).get("sha256") != EXPECTED_PREFILL_PTD_SHA: errors.append("ptd.sha256")
    if d.get("ptd", {}).get("size") != EXPECTED_PREFILL_PTD_SIZE: errors.append("ptd.size")
    if d.get("ptd", {}).get("external_tag") != "t3_shared": errors.append("ptd.external_tag")
    if d.get("real_executorch_forward") is not True: errors.append("real_executorch_forward")
    if d.get("comparator_sha256") != EXPECTED_COMPARATOR_SHA: errors.append("comparator_sha256")
    if d.get("thresholds") != THRESHOLDS: errors.append("thresholds")
    for p in ("P1", "P2", "P3"):
        rec = d.get("private_parity", {}).get(p, {})
        if rec.get("status") != "PASS_L2": errors.append(f"{p}.status")
        if not rec.get("evidence_sha256"): errors.append(f"{p}.evidence_sha256")
    if d.get("private_golden_published") is not False: errors.append("private_golden_published")
    if errors:
        raise RuntimeError("external-prefill gate invalid: " + ", ".join(errors))
    return d


def stage_dir(name: str) -> Path:
    p = OUT / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def rejected_result(value) -> bool:
    """Propagate explicit failed checks without treating forward completion as parity."""
    if isinstance(value, dict):
        if "accepted" in value and value["accepted"] is not True:
            return True
        if "status" in value and value["status"] not in ("PASS", "PASS_L2", "COMPLETED"):
            return True
        return any(rejected_result(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(rejected_result(v) for v in value)
    return False


def stage_guard(name: str, fn) -> None:
    d = stage_dir(name)
    started = time.time()
    # A failed retry must not leave an earlier result looking current.
    (d / "stage_result.json").unlink(missing_ok=True)
    write_json(d / "stage_start.json", {
        "stage": name, "status": "STARTED", "pid": os.getpid(),
        "started_unix": started, "python": sys.version,
    })
    result = {}
    completed = False
    try:
        result = dict(fn())
        completed = True
        failed = rejected_result(result)
        numerical = result.get("numerical_status", "NOT_EVALUATED")
        result.update({
            "stage": name, "status": "FAIL" if failed else "PASS",
            "execution_status": "COMPLETED", "numerical_status": numerical,
            "pid": os.getpid(), "elapsed_s": time.time() - started,
        })
        write_json(d / "stage_result.json", result)
        if failed:
            raise RuntimeError(f"stage {name} contains rejected checks")
    except BaseException as exc:
        result.update({
            "stage": name, "status": "FAIL",
            "execution_status": "COMPLETED" if completed else "FAILED",
            "pid": os.getpid(), "elapsed_s": time.time() - started,
            "exception_type": type(exc).__name__, "exception": str(exc)[:2000],
        })
        write_json(d / "stage_result.json", result)
        (d / "traceback.txt").write_text(traceback.format_exc()[-20000:], encoding="utf-8")
        raise


def import_export_stack():
    import numpy as np
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
    from executorch.exir import EdgeCompileConfig, to_edge_transform_and_lower
    from executorch.exir.passes.external_constants_pass import delegate_external_constants_pass_unlifted
    from torch.export import export
    return np, torch, nn, F, XnnpackPartitioner, EdgeCompileConfig, to_edge_transform_and_lower, delegate_external_constants_pass_unlifted, export


def load_base(torch):
    sys.path.insert(0, str(ROOT))
    import C05C_T3_PREFILL_R3C as base
    return base


def build_decode_classes(torch, nn, F, base):
    prefill_len = base.PHYS_PREFILL
    max_kv = prefill_len + MAX_SPEECH

    def rotate_half(x):
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
            pos = torch.arange(max_kv, dtype=torch.float32)
            freq = torch.outer(pos, inv)
            emb = torch.cat([freq, freq], -1)
            self.register_buffer("rcos", emb.cos())
            self.register_buffer("rsin", emb.sin())
            self.register_buffer("kvpos", torch.arange(max_kv))

        def rms(self, x, w):
            return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps) * w

        def forward(self, prev_token, speech_pos, kv_k, kv_v):
            sp = speech_pos[0]
            x = self.speech_emb(prev_token) + self.speech_pos.get_fixed_embedding(sp.reshape(1, 1))
            x = torch.cat([x, x], dim=0)
            write = torch.tensor(prefill_len, dtype=torch.long, device=x.device) + (sp - 1)
            valid = self.kvpos <= write
            bias = torch.where(
                valid,
                torch.zeros(max_kv, dtype=x.dtype, device=x.device),
                torch.full((max_kv,), float("-inf"), dtype=x.dtype, device=x.device),
            ).reshape(1, 1, 1, max_kv)
            wi = write.reshape(1)
            cw = torch.index_select(self.rcos, 0, wi).reshape(1, 1, 1, HD)
            sw = torch.index_select(self.rsin, 0, wi).reshape(1, 1, 1, HD)
            score_pm = (self.kvpos == write).reshape(1, 1, 1, max_kv)
            value_pm = (self.kvpos == write).reshape(1, 1, max_kv, 1)
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
                uv = torch.where(value_pm, v.expand(2, N_HEADS, max_kv, HD), kv_v[i])
                ao = torch.matmul(att, uv)
                ao = ao.permute(0, 2, 1, 3).reshape(2, 1, DIM)
                x = layer.o(ao) + r
                r = x
                xn = self.rms(x, layer.ln2)
                x = layer.d(F.silu(layer.g(xn)) * layer.u(xn)) + r
            x = self.rms(x, self.norm)
            return self.head(x[:, -1, :]), torch.stack(nks), torch.stack(nvs)

    return T3DecodeStorageProbe, prefill_len, max_kv


def make_tagged_edge(module, args, torch, XnnpackPartitioner, EdgeCompileConfig, to_edge_transform_and_lower, delegate_external_constants_pass_unlifted, export):
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
        raise RuntimeError("tagged zero delegate constants")
    ep = export(gm, args, strict=False)
    edge = to_edge_transform_and_lower(
        ep,
        compile_config=EdgeCompileConfig(_check_ir_validity=False),
        partitioner=[XnnpackPartitioner()],
    )
    return edge, tagged


def write_program_and_store(edge, outdir: Path, pte_name: str) -> tuple[Path, Path, dict]:
    et = edge.to_executorch()
    if sorted(et._tensor_data.keys()) != ["t3_shared"]:
        raise RuntimeError(f"expected one t3_shared store, got {sorted(et._tensor_data.keys())}")
    pte = outdir / pte_name
    ptd = outdir / "t3_shared.ptd"
    with pte.open("wb") as f:
        et.write_to_file(f)
    with ptd.open("wb") as f:
        et._tensor_data["t3_shared"].write_to_file(f)
    if not pte.is_file() or not ptd.is_file() or pte.stat().st_size == 0 or ptd.stat().st_size == 0:
        raise RuntimeError("PTE/PTD serialization produced an empty file")

    store = edge._named_data_store.get_named_data_store_output()
    tag = store.external_data.get("t3_shared", {})
    if not tag:
        raise RuntimeError("edge NamedDataStore has no t3_shared external data")
    by_buffer = {}
    entries = {}
    for key, de in sorted(tag.items()):
        if de.buffer_index not in by_buffer:
            buf = store.buffers[de.buffer_index]
            by_buffer[de.buffer_index] = {"sha256": sha_bytes(buf), "size": len(buf)}
        entries[key] = {
            "buffer_sha256": by_buffer[de.buffer_index]["sha256"],
            "size": by_buffer[de.buffer_index]["size"],
            "alignment": int(de.alignment),
            "tensor_layout_present": de.tensor_layout is not None,
        }
    manifest = {
        "external_tag": "t3_shared",
        "key_count": len(entries),
        "unique_buffer_count": len(by_buffer),
        "entries": entries,
    }
    write_json(outdir / "named_store_manifest.json", manifest)
    return pte, ptd, manifest


def export_prefill() -> dict:
    require_gate()
    np, torch, nn, F, XnnpackPartitioner, EdgeCompileConfig, to_edge_transform_and_lower, delegate_external_constants_pass_unlifted, export = import_export_stack()
    base = load_base(torch)
    model = base.load_t3(torch.float16)
    pre = base.StaticPrefillInput(model).eval()
    ce = torch.zeros((1, base.COND_LEN, 1024), dtype=torch.float16)
    fixed = torch.zeros((2, base.TEXT_SLOTS), dtype=torch.long)
    text_len = torch.tensor([66], dtype=torch.long)
    with torch.inference_mode():
        src = pre(ce, fixed, text_len)
    expected = [[2, SPEECH_VOCAB], [N_LAYERS, 2, N_HEADS, base.PHYS_PREFILL, HD], [N_LAYERS, 2, N_HEADS, base.PHYS_PREFILL, HD]]
    if [list(x.shape) for x in src] != expected:
        raise RuntimeError("source prefill output shape mismatch")
    d = stage_dir("01_export_prefill")
    np.savez(d / "source_outputs.npz", logits=src[0].cpu().numpy(), k=src[1].cpu().numpy(), v=src[2].cpu().numpy())
    edge, tagged = make_tagged_edge(pre, (ce, fixed, text_len), torch, XnnpackPartitioner, EdgeCompileConfig, to_edge_transform_and_lower, delegate_external_constants_pass_unlifted, export)
    pte, ptd, manifest = write_program_and_store(edge, d, "t3_prefill_shared_isolated_r4.pte")
    pte_sha, ptd_sha = sha_file(pte), sha_file(ptd)
    if pte_sha != EXPECTED_PREFILL_PTE_SHA or pte.stat().st_size != EXPECTED_PREFILL_PTE_SIZE:
        raise RuntimeError(f"prefill PTE drift: {pte_sha} size={pte.stat().st_size}")
    if ptd_sha != EXPECTED_PREFILL_PTD_SHA or ptd.stat().st_size != EXPECTED_PREFILL_PTD_SIZE:
        raise RuntimeError(f"prefill PTD drift: {ptd_sha} size={ptd.stat().st_size}")
    return {
        "qualified_prefill_bytes_reproduced": True,
        "tagged_get_attrs": tagged,
        "pte": {"path": pte.name, "sha256": pte_sha, "size": pte.stat().st_size},
        "ptd": {"path": ptd.name, "sha256": ptd_sha, "size": ptd.stat().st_size},
        "store": {"key_count": manifest["key_count"], "unique_buffer_count": manifest["unique_buffer_count"]},
        "source_output_shapes": expected,
    }


def export_decode() -> dict:
    require_gate()
    np, torch, nn, F, XnnpackPartitioner, EdgeCompileConfig, to_edge_transform_and_lower, delegate_external_constants_pass_unlifted, export = import_export_stack()
    base = load_base(torch)
    T3DecodeStorageProbe, prefill_len, max_kv = build_decode_classes(torch, nn, F, base)
    model = base.load_t3(torch.float16)
    dec = T3DecodeStorageProbe(model).eval().half()
    start_token = int(model.hp.start_speech_token)
    prev = torch.tensor([[start_token]], dtype=torch.long)
    spos = torch.tensor([1], dtype=torch.long)
    kv_k = torch.zeros((N_LAYERS, 2, N_HEADS, max_kv, HD), dtype=torch.float16)
    kv_v = torch.zeros_like(kv_k)
    with torch.inference_mode():
        src = dec(prev, spos, kv_k, kv_v)
    delta_shape = [N_LAYERS, 2, N_HEADS, 1, HD]
    expected = [[2, SPEECH_VOCAB], delta_shape, delta_shape]
    if [list(x.shape) for x in src] != expected:
        raise RuntimeError("source decode probe output shape mismatch")
    d = stage_dir("02_export_decode")
    np.savez(d / "source_outputs.npz", logits=src[0].cpu().numpy(), k_delta=src[1].cpu().numpy(), v_delta=src[2].cpu().numpy())
    edge, tagged = make_tagged_edge(dec, (prev, spos, kv_k, kv_v), torch, XnnpackPartitioner, EdgeCompileConfig, to_edge_transform_and_lower, delegate_external_constants_pass_unlifted, export)
    pte, ptd, manifest = write_program_and_store(edge, d, "t3_decode_shared_isolated_r4.pte")
    return {
        "scope": "storage/runtime feasibility probe only; not production decode acceptance",
        "tagged_get_attrs": tagged,
        "start_speech_token": start_token,
        "prefill_len": prefill_len,
        "max_kv": max_kv,
        "pte": {"path": pte.name, "sha256": sha_file(pte), "size": pte.stat().st_size},
        "ptd": {"path": ptd.name, "sha256": sha_file(ptd), "size": ptd.stat().st_size},
        "store": {"key_count": manifest["key_count"], "unique_buffer_count": manifest["unique_buffer_count"]},
        "source_output_shapes": expected,
    }


def load_stage_result(name: str, *, allow_completed: bool = False) -> dict:
    p = stage_dir(name) / "stage_result.json"
    if not p.is_file():
        raise RuntimeError(f"missing {p}")
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("status") != "PASS" and not (allow_completed and d.get("execution_status") == "COMPLETED"):
        raise RuntimeError(f"prerequisite stage {name} is not PASS")
    return d


def merge_store() -> dict:
    require_gate()
    pre = load_stage_result("01_export_prefill")
    dec = load_stage_result("02_export_decode")
    from executorch.exir._serialize._named_data_store import NamedDataStore
    from executorch.exir._serialize.data_serializer import DataPayload
    from executorch.extension.flat_tensor.serialize.serialize import FlatTensorSerializer

    pre_dir = stage_dir("01_export_prefill")
    dec_dir = stage_dir("02_export_decode")
    pre_ptd = pre_dir / "t3_shared.ptd"
    dec_ptd = dec_dir / "t3_shared.ptd"
    pre_manifest = json.loads((pre_dir / "named_store_manifest.json").read_text(encoding="utf-8"))
    dec_manifest = json.loads((dec_dir / "named_store_manifest.json").read_text(encoding="utf-8"))
    serializer = FlatTensorSerializer()
    pre_out = serializer.deserialize_to_named_data_store_output(pre_ptd.read_bytes(), "t3_shared")
    dec_out = serializer.deserialize_to_named_data_store_output(dec_ptd.read_bytes(), "t3_shared")

    def validate_and_add(merged, store_out, manifest, label):
        tag = store_out.external_data.get("t3_shared", {})
        if set(tag.keys()) != set(manifest.get("entries", {}).keys()):
            raise RuntimeError(f"{label} PTD keys differ from alignment manifest")
        for key, de in tag.items():
            meta = manifest["entries"][key]
            buf = store_out.buffers[de.buffer_index]
            if sha_bytes(buf) != meta["buffer_sha256"] or len(buf) != meta["size"]:
                raise RuntimeError(f"{label} PTD buffer identity mismatch for key {key}")
            try:
                merged.add_named_data(
                    key,
                    buf,
                    alignment=int(meta["alignment"]),
                    external_tag="t3_shared",
                    tensor_layout=de.tensor_layout,
                )
            except ValueError:
                raise RuntimeError(f"duplicate key with divergent bytes while merging {label}: {key}") from None

    merged = NamedDataStore()
    validate_and_add(merged, pre_out, pre_manifest, "prefill")
    pre_union = merged.get_named_data_store_output()
    pre_unique = len(pre_union.buffers)
    pre_keys = len(pre_union.external_data.get("t3_shared", {}))
    validate_and_add(merged, dec_out, dec_manifest, "decode")
    union = merged.get_named_data_store_output()
    union_map = union.external_data.get("t3_shared", {})
    if not union_map:
        raise RuntimeError("merged t3_shared store is empty")

    overlap = sorted(set(pre_manifest["entries"]) & set(dec_manifest["entries"]))
    overlap_identical = 0
    for key in overlap:
        if pre_manifest["entries"][key]["buffer_sha256"] != dec_manifest["entries"][key]["buffer_sha256"]:
            raise RuntimeError(f"overlapping key differs between prefill and decode: {key}")
        overlap_identical += 1

    payload = DataPayload(buffers=union.buffers, named_data=union_map)
    cord = serializer.serialize(payload)
    d = stage_dir("03_merge_store")
    union_ptd = d / "t3_shared_union.ptd"
    with union_ptd.open("wb") as f:
        cord.write_to_file(f)
    if union_ptd.stat().st_size == 0:
        raise RuntimeError("union PTD is empty")
    union_sha = sha_file(union_ptd)
    # Round-trip validates the file and all named keys before runtime stages.
    roundtrip = serializer.deserialize_to_named_data_store_output(union_ptd.read_bytes(), "t3_shared")
    rt_keys = set(roundtrip.external_data.get("t3_shared", {}).keys())
    if rt_keys != set(union_map.keys()):
        raise RuntimeError("union PTD round-trip key mismatch")
    return {
        "same_union_ptd_for_next_two_runtime_processes": True,
        "union_ptd": {"path": union_ptd.name, "sha256": union_sha, "size": union_ptd.stat().st_size},
        "prefill_keys": pre_keys,
        "prefill_unique_buffers": pre_unique,
        "decode_keys": dec_manifest["key_count"],
        "union_keys": len(union_map),
        "union_unique_buffers": len(union.buffers),
        "overlapping_keys": len(overlap),
        "overlapping_keys_byte_identical": overlap_identical,
        "roundtrip_keys": len(rt_keys),
    }


def runtime_prefill() -> dict:
    require_gate()
    load_stage_result("01_export_prefill")
    merged = load_stage_result("03_merge_store")
    import numpy as np
    import torch
    from executorch.extension.pybindings.portable_lib import _load_for_executorch_from_buffer
    sys.path.insert(0, str(ROOT))
    import C05C_T3_PREFILL_R3C as base
    pre_dir = stage_dir("01_export_prefill")
    union_ptd = stage_dir("03_merge_store") / "t3_shared_union.ptd"
    pte = pre_dir / "t3_prefill_shared_isolated_r4.pte"
    if sha_file(union_ptd) != merged["union_ptd"]["sha256"]:
        raise RuntimeError("union PTD changed before prefill runtime")
    ce = torch.zeros((1, base.COND_LEN, 1024), dtype=torch.float16)
    fixed = torch.zeros((2, base.TEXT_SLOTS), dtype=torch.long)
    text_len = torch.tensor([66], dtype=torch.long)
    ptd_bytes = union_ptd.read_bytes()
    pte_bytes = pte.read_bytes()
    mod = _load_for_executorch_from_buffer(pte_bytes, ptd_bytes)
    with torch.inference_mode():
        out = mod.forward((ce, fixed, text_len))
    shapes = [list(x.shape) for x in out]
    expected = [[2, SPEECH_VOCAB], [N_LAYERS, 2, N_HEADS, base.PHYS_PREFILL, HD], [N_LAYERS, 2, N_HEADS, base.PHYS_PREFILL, HD]]
    if shapes != expected or not all(bool(torch.isfinite(x).all()) for x in out):
        raise RuntimeError("prefill real forward output schema/finite check failed")
    d = stage_dir("04_runtime_prefill")
    np.savez(d / "runtime_outputs.npz", logits=out[0].cpu().numpy(), k=out[1].cpu().numpy(), v=out[2].cpu().numpy())
    return {
        "fresh_process_real_executorch_forward": True,
        "union_ptd_sha256": sha_file(union_ptd),
        "pte_sha256": sha_file(pte),
        "output_shapes": shapes,
        "all_finite": True,
    }


def runtime_decode() -> dict:
    require_gate()
    dec = load_stage_result("02_export_decode")
    merged = load_stage_result("03_merge_store")
    import numpy as np
    import torch
    from executorch.extension.pybindings.portable_lib import _load_for_executorch_from_buffer
    dec_dir = stage_dir("02_export_decode")
    union_ptd = stage_dir("03_merge_store") / "t3_shared_union.ptd"
    pte = dec_dir / "t3_decode_shared_isolated_r4.pte"
    if sha_file(union_ptd) != merged["union_ptd"]["sha256"]:
        raise RuntimeError("union PTD changed before decode runtime")
    prev = torch.tensor([[int(dec["start_speech_token"])]], dtype=torch.long)
    spos = torch.tensor([1], dtype=torch.long)
    max_kv = int(dec["max_kv"])
    kv_k = torch.zeros((N_LAYERS, 2, N_HEADS, max_kv, HD), dtype=torch.float16)
    kv_v = torch.zeros_like(kv_k)
    ptd_bytes = union_ptd.read_bytes()
    pte_bytes = pte.read_bytes()
    mod = _load_for_executorch_from_buffer(pte_bytes, ptd_bytes)
    with torch.inference_mode():
        out = mod.forward((prev, spos, kv_k, kv_v))
    delta = [N_LAYERS, 2, N_HEADS, 1, HD]
    expected = [[2, SPEECH_VOCAB], delta, delta]
    shapes = [list(x.shape) for x in out]
    if shapes != expected or not all(bool(torch.isfinite(x).all()) for x in out):
        raise RuntimeError("decode real forward output schema/finite check failed")
    d = stage_dir("05_runtime_decode")
    np.savez(d / "runtime_outputs.npz", logits=out[0].cpu().numpy(), k_delta=out[1].cpu().numpy(), v_delta=out[2].cpu().numpy())
    return {
        "fresh_process_real_executorch_forward": True,
        "scope": "storage/runtime feasibility probe only; not production decode acceptance",
        "union_ptd_sha256": sha_file(union_ptd),
        "pte_sha256": sha_file(pte),
        "output_shapes": shapes,
        "all_finite": True,
    }


def compare_arrays(a, b, name: str) -> dict:
    import numpy as np
    a, b = np.asarray(a), np.asarray(b)
    result = {"name": name, "accepted": False,
              "source_shape": list(a.shape), "runtime_shape": list(b.shape),
              "source_dtype": str(a.dtype), "runtime_dtype": str(b.dtype)}
    for invalid, reason in (
        (a.shape != b.shape, "shape_mismatch"),
        (a.dtype != b.dtype, "dtype_mismatch"),
        (a.size == 0 or b.size == 0, "empty_output"),
        (a.dtype.kind not in "fiu" or b.dtype.kind not in "fiu", "unsupported_dtype"),
    ):
        if invalid:
            return {**result, "reason": reason}
    if not (np.isfinite(a).all() and np.isfinite(b).all()):
        return {**result, "finite": False, "reason": "nonfinite_output"}
    if a.dtype.kind in "iu":
        equal = bool(np.array_equal(a, b))
        return {**result, "finite": True, "integer_exact": equal, "accepted": equal}
    aa, bb = a.astype(np.float64).reshape(-1), b.astype(np.float64).reshape(-1)
    with np.errstate(over="ignore", invalid="ignore"):
        na, nb = float(np.linalg.norm(aa)), float(np.linalg.norm(bb))
        cosine = 1.0 if na == nb == 0 else (0.0 if na == 0 or nb == 0 else float(np.dot(aa, bb) / (na * nb)))
        diff = np.abs(aa - bb)
        mean_abs, max_abs = float(diff.mean()), float(diff.max())
    if not all(np.isfinite(x) for x in (cosine, mean_abs, max_abs)):
        return {**result, "finite": True, "reason": "nonfinite_metrics"}
    accepted = cosine >= THRESHOLDS["cosine_min"] and mean_abs <= THRESHOLDS["mean_abs_max"] and max_abs <= THRESHOLDS["max_abs_max"]
    result.update(finite=True, cosine_raw=cosine, mean_abs=mean_abs, max_abs=max_abs, accepted=bool(accepted))
    if name == "logits":
        if a.ndim != 2 or a.shape[0] != 2:
            return {**result, "accepted": False, "reason": "cfg_logits_schema"}
        # Frozen T3 combines cond + cfg * (cond - uncond) in logits dtype.
        # V5B authority fixes cfg_weight=0.03. Do not compare raw-row top1.
        cfg = np.asarray(0.03, dtype=a.dtype)
        with np.errstate(over="ignore", invalid="ignore"):
            ac = a[0] + cfg * (a[0] - a[1])
            bc = b[0] + cfg * (b[0] - b[1])
        if not (np.isfinite(ac).all() and np.isfinite(bc).all()):
            return {**result, "accepted": False, "reason": "nonfinite_cfg"}
        at, bt = int(ac.argmax()), int(bc.argmax())
        result.update(cfg_weight=0.03, source_cfg_top1=at, runtime_cfg_top1=bt,
                      cfg_top1_match=at == bt, accepted=bool(accepted and at == bt))
    return result


def _verify() -> dict:
    require_gate()
    for name in ("01_export_prefill", "02_export_decode", "03_merge_store", "04_runtime_prefill", "05_runtime_decode"):
        load_stage_result(name, allow_completed=name.startswith(("04_", "05_")))
    import numpy as np
    pre_src = np.load(stage_dir("01_export_prefill") / "source_outputs.npz")
    pre_run = np.load(stage_dir("04_runtime_prefill") / "runtime_outputs.npz")
    dec_src = np.load(stage_dir("02_export_decode") / "source_outputs.npz")
    dec_run = np.load(stage_dir("05_runtime_decode") / "runtime_outputs.npz")
    pre_cmp = [compare_arrays(pre_src[k], pre_run[k], k) for k in ("logits", "k", "v")]
    dec_cmp = [compare_arrays(dec_src[k], dec_run[k], k) for k in ("logits", "k_delta", "v_delta")]
    pre_ok = all(x.get("accepted") is True for x in pre_cmp)
    dec_ok = all(x.get("accepted") is True for x in dec_cmp)
    pre_rt = load_stage_result("04_runtime_prefill", allow_completed=True)
    dec_rt = load_stage_result("05_runtime_decode", allow_completed=True)
    merged = load_stage_result("03_merge_store")
    same_sha = pre_rt["union_ptd_sha256"] == dec_rt["union_ptd_sha256"] == merged["union_ptd"]["sha256"]
    accepted = pre_ok and dec_ok and same_sha
    report = {
        "schema": "sindel.cp034.c05c.t3-shared-store-isolated-r4.v1",
        "status": "PASS_L2" if accepted else "FAIL",
        "accepted": accepted,
        "numerical_status": "PASS" if pre_ok and dec_ok else "FAIL",
        "comparator_sha256": sha_file(Path(__file__)),
        "scope": "shared external-store feasibility; decode remains a storage/runtime probe, not production decode acceptance",
        "process_isolation": {
            "export_prefill": "fresh_process",
            "export_decode": "fresh_process",
            "merge_store": "fresh_process",
            "runtime_prefill": "fresh_process",
            "runtime_decode": "fresh_process",
            "verify": "fresh_process"
        },
        "shared_ptd": {
            "sha256": merged["union_ptd"]["sha256"],
            "size": merged["union_ptd"]["size"],
            "same_exact_bytes_used_by_prefill_and_decode": same_sha
        },
        "prefill": {"real_forward": True, "comparison": pre_cmp},
        "decode_probe": {"real_forward": True, "comparison": dec_cmp},
        "thresholds": THRESHOLDS,
        "private_golden_published": False,
    }
    write_json(OUT / "C05C_T3_SHARED_STORE_ISOLATED_R4_FINAL.json", report)
    return report


def verify() -> dict:
    report_path = OUT / "C05C_T3_SHARED_STORE_ISOLATED_R4_FINAL.json"
    report_path.unlink(missing_ok=True)
    try:
        return _verify()
    except Exception as exc:
        report = {
            "schema": "sindel.cp034.c05c.t3-shared-store-isolated-r4.v1",
            "status": "FAIL", "accepted": False,
            "numerical_status": "NOT_EVALUATED",
            "exception_type": type(exc).__name__, "exception": str(exc)[:2000],
            "comparator_sha256": sha_file(Path(__file__)), "thresholds": THRESHOLDS,
            "scope": "incomplete verification; not production acceptance",
        }
        write_json(report_path, report)
        return report


COMMANDS = {
    "export-prefill": ("01_export_prefill", export_prefill),
    "export-decode": ("02_export_decode", export_decode),
    "merge-store": ("03_merge_store", merge_store),
    "runtime-prefill": ("04_runtime_prefill", runtime_prefill),
    "runtime-decode": ("05_runtime_decode", runtime_decode),
    "verify": ("06_verify", verify),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=sorted(COMMANDS))
    ns = ap.parse_args()
    name, fn = COMMANDS[ns.command]
    stage_guard(name, fn)


if __name__ == "__main__":
    main()
