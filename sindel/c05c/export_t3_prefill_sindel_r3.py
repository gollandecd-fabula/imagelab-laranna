#!/usr/bin/env python3
import gc, hashlib, json, math, os, sys, time
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from safetensors.torch import load_file as load_safetensors
from torch.export import export
from executorch.exir import to_edge_transform_and_lower, EdgeCompileConfig
from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
from executorch.runtime import Runtime

ROOT = Path(__file__).resolve().parent
OUT = Path(os.environ.get('SINDEL_C05C_OUT', ROOT / 'out' / 'T3_PREFILL_R3'))
OUT.mkdir(parents=True, exist_ok=True)
CKPT = Path(os.environ['SINDEL_CKPT_DIR'])
SRC = Path(os.environ['SINDEL_CHATTERBOX_SRC'])
sys.path.insert(0, str(SRC / 'src'))

TOL_PATH = ROOT / 'C05C_NUMERICAL_TOLERANCE_R3.json'
CONTRACT_PATH = ROOT / 'C05C_T3_STATIC_CONTRACT_R3.json'
TOL = json.loads(TOL_PATH.read_text())
CONTRACT = json.loads(CONTRACT_PATH.read_text())

COND_LEN = 34
MAX_RAW_TEXT = 256
TEXT_SEQ = 258
PREFILL_LEN = 294
MAX_NEW = 1000
MAX_KV = 1294
N_LAYERS = 30
N_HEADS = 16
HEAD_DIM = 64
DIM = 1024
TEXT_VOCAB = 2454
SPEECH_VOCAB = 8194
SOT_TEXT = 255
EOT_TEXT = 0
SOT_SPEECH = 6561
CFG_WEIGHT = 0.03

EXPECTED_T3_SHA = '5abca8321ede76f8e61f1cc0d19aea6c946b28871017ce8726f8a69203f05953'
EXPECTED_COMMIT = '5de7a54aa4e5e2baadb0182dde554908b48b85c2'


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def cosine(a: torch.Tensor, b: torch.Tensor):
    a = a.detach().float().reshape(-1)
    b = b.detach().float().reshape(-1)
    return float(F.cosine_similarity(a, b, dim=0).item())


def metrics(a, b):
    af, bf = a.detach().float(), b.detach().float()
    d = (af - bf).abs()
    return {
        'max_abs': float(d.max().item()),
        'mean_abs': float(d.mean().item()),
        'cosine': cosine(af, bf),
    }


def assert_metric(m, lim, prefix):
    if m['max_abs'] > lim[prefix + '_max_abs']:
        raise RuntimeError(f"{prefix} max_abs {m['max_abs']} > {lim[prefix + '_max_abs']}")
    if m['mean_abs'] > lim[prefix + '_mean_abs']:
        raise RuntimeError(f"{prefix} mean_abs {m['mean_abs']} > {lim[prefix + '_mean_abs']}")
    cos_key = prefix + '_cosine_min'
    if m['cosine'] < lim[cos_key]:
        raise RuntimeError(f"{prefix} cosine {m['cosine']} < {lim[cos_key]}")


def layer_kv(cache, idx):
    layer = cache.layers[idx]
    return layer.keys, layer.values


def source_inputs(t3, cond_emb, valid_tokens):
    # Exact frozen V3 inference semantics after conditioning has already been prepared.
    text = valid_tokens.expand(2, -1)
    text_emb = t3.text_emb(text)
    # Source does this before adding learned position embeddings.
    branch = torch.tensor([1.0, 0.0], dtype=text_emb.dtype, device=text_emb.device).reshape(2, 1, 1)
    text_emb = text_emb * branch
    text_emb = text_emb + t3.text_pos_emb(text)
    cond2 = cond_emb.expand(2, -1, -1)

    initial = torch.full((2, 1), SOT_SPEECH, dtype=torch.long, device=text.device)
    initial_emb = t3.speech_emb(initial) + t3.speech_pos_emb(initial)
    embeds = torch.cat([cond2, text_emb, initial_emb], dim=1)

    bos = torch.full((1, 1), SOT_SPEECH, dtype=torch.long, device=text.device)
    bos_emb = t3.speech_emb(bos) + t3.speech_pos_emb.get_fixed_embedding(0)
    bos_emb = bos_emb.expand(2, -1, -1)
    return torch.cat([embeds, bos_emb], dim=1)


class SindelT3Prefill(nn.Module):
    def __init__(self, t3):
        super().__init__()
        self.text_emb = t3.text_emb
        self.text_pos_emb = t3.text_pos_emb
        self.speech_emb = t3.speech_emb
        self.speech_pos_emb = t3.speech_pos_emb
        self.tfmr = t3.tfmr
        self.speech_head = t3.speech_head
        self.register_buffer('cond_pos', torch.arange(COND_LEN, dtype=torch.long))
        self.register_buffer('text_phys', torch.arange(TEXT_SEQ, dtype=torch.long))

    def forward(self, cond_emb, text_tokens, text_len):
        # text_tokens is fixed [1,258], valid prefix includes SOT/EOT.
        text2 = text_tokens.expand(2, -1)
        te = self.text_emb(text2)
        branch = torch.tensor([1.0, 0.0], dtype=te.dtype, device=te.device).reshape(2, 1, 1)
        te = te * branch
        te = te + self.text_pos_emb(text2)
        cond2 = cond_emb.expand(2, -1, -1)

        initial = torch.full((2, 1), SOT_SPEECH, dtype=torch.long, device=text_tokens.device)
        initial_emb = self.speech_emb(initial) + self.speech_pos_emb(initial)
        bos = torch.full((1, 1), SOT_SPEECH, dtype=torch.long, device=text_tokens.device)
        bos_emb = self.speech_emb(bos) + self.speech_pos_emb.get_fixed_embedding(0)
        bos_emb = bos_emb.expand(2, -1, -1)
        inputs = torch.cat([cond2, te, initial_emb, bos_emb], dim=1)

        valid_text = self.text_phys < text_len
        mask1 = torch.cat([
            torch.ones(COND_LEN, dtype=torch.long, device=text_tokens.device),
            valid_text.to(torch.long),
            torch.ones(2, dtype=torch.long, device=text_tokens.device),
        ], dim=0).reshape(1, PREFILL_LEN)
        attention_mask = mask1.expand(2, -1)

        # Physical cache is fixed, but RoPE positions preserve the source logical sequence.
        text_pos = COND_LEN + self.text_phys
        speech_pos = torch.stack([COND_LEN + text_len, COND_LEN + text_len + 1])
        position_ids = torch.cat([self.cond_pos, text_pos, speech_pos], dim=0).reshape(1, PREFILL_LEN).expand(2, -1)

        from transformers import DynamicCache
        cache = DynamicCache()
        out = self.tfmr(
            inputs_embeds=inputs,
            attention_mask=attention_mask,
            position_ids=position_ids,
            past_key_values=cache,
            use_cache=True,
            output_hidden_states=True,
            return_dict=True,
        )
        hidden = out.hidden_states[-1]
        logits = self.speech_head(hidden[:, -1, :])

        k_layers, v_layers = [], []
        for i in range(N_LAYERS):
            k, v = layer_kv(out.past_key_values, i)
            pad = MAX_KV - k.shape[2]
            if pad > 0:
                k = F.pad(k, (0, 0, 0, pad))
                v = F.pad(v, (0, 0, 0, pad))
            k_layers.append(k)
            v_layers.append(v)
        return logits, torch.stack(k_layers), torch.stack(v_layers)


def make_fixture(valid_len, offset):
    if valid_len < 4 or valid_len > TEXT_SEQ:
        raise ValueError(valid_len)
    inner = valid_len - 2
    seq = ((torch.arange(inner, dtype=torch.long) * 37 + 17 + offset) % (TEXT_VOCAB - 2)) + 1
    valid = torch.cat([torch.tensor([SOT_TEXT]), seq, torch.tensor([EOT_TEXT])]).reshape(1, -1)
    padded = torch.zeros(1, TEXT_SEQ, dtype=torch.long)
    padded[:, :valid_len] = valid
    return valid, padded


def make_cond():
    x = torch.arange(COND_LEN * DIM, dtype=torch.float32).reshape(1, COND_LEN, DIM)
    return (torch.sin(x * 0.00037) * 0.075 + torch.cos(x * 0.00011) * 0.025).contiguous()


def compare_source_adapted(t3, wrapper):
    lim = TOL['t3_source_vs_adapted_fp32']
    report = []
    cond = make_cond()
    for valid_len, offset in [(66, 3), (71, 11), (67, 29)]:
        valid, padded = make_fixture(valid_len, offset)
        with torch.inference_mode():
            src_in = source_inputs(t3, cond, valid)
            src_out = t3.tfmr(
                inputs_embeds=src_in,
                use_cache=True,
                output_hidden_states=True,
                return_dict=True,
            )
            src_logits = t3.speech_head(src_out.hidden_states[-1][:, -1, :])
            ad_logits, ad_k, ad_v = wrapper(cond, padded, torch.tensor(valid_len, dtype=torch.long))

        lm = metrics(src_logits, ad_logits)
        assert_metric(lm, lim, 'logits')
        src_cfg = src_logits[0:1] + CFG_WEIGHT * (src_logits[0:1] - src_logits[1:2])
        ad_cfg = ad_logits[0:1] + CFG_WEIGHT * (ad_logits[0:1] - ad_logits[1:2])
        if int(src_cfg.argmax(-1)) != int(ad_cfg.argmax(-1)):
            raise RuntimeError(f'CFG top1 mismatch at text_len={valid_len}')

        # Map fixed physical cache back to the source logical valid positions:
        # cond+valid text are already at the same physical positions; the two speech-start slots
        # are physically 292/293 in fixed layout.
        km, vm = [], []
        for i in range(N_LAYERS):
            sk, sv = layer_kv(src_out.past_key_values, i)
            ak = torch.cat([ad_k[i, :, :, :COND_LEN + valid_len, :], ad_k[i, :, :, TEXT_SEQ + COND_LEN:TEXT_SEQ + COND_LEN + 2, :]], dim=2)
            av = torch.cat([ad_v[i, :, :, :COND_LEN + valid_len, :], ad_v[i, :, :, TEXT_SEQ + COND_LEN:TEXT_SEQ + COND_LEN + 2, :]], dim=2)
            km.append(metrics(sk, ak))
            vm.append(metrics(sv, av))
        kv = {
            'max_abs': max(max(x['max_abs'] for x in km), max(x['max_abs'] for x in vm)),
            'mean_abs': max(max(x['mean_abs'] for x in km), max(x['mean_abs'] for x in vm)),
            'cosine': min(min(x['cosine'] for x in km), min(x['cosine'] for x in vm)),
        }
        assert_metric(kv, lim, 'valid_kv')
        report.append({'text_len': valid_len, 'logits': lm, 'valid_kv_worst': kv, 'cfg_top1': int(src_cfg.argmax(-1))})
    return report


def export_and_pte_parity(wrapper):
    cond = make_cond().half()
    _, padded = make_fixture(66, 3)
    text_len = torch.tensor(66, dtype=torch.long)
    w16 = wrapper.half().eval()
    with torch.inference_mode():
        ref = w16(cond, padded, text_len)

    ep = export(w16, (cond, padded, text_len))
    edge = to_edge_transform_and_lower(
        ep,
        compile_config=EdgeCompileConfig(_check_ir_validity=False),
        partitioner=[XnnpackPartitioner()],
    )
    et = edge.to_executorch()
    pte = OUT / 't3_prefill.pte'
    pte.write_bytes(et.buffer)

    rt = Runtime.get()
    prog = rt.load_program(str(pte))
    method = prog.load_method('forward')
    got = method.execute([cond.contiguous(), padded.contiguous(), text_len.contiguous()])
    if len(got) != 3:
        raise RuntimeError(f'Expected 3 PTE outputs, got {len(got)}')
    got_logits, got_k, got_v = got
    lim = TOL['t3_pytorch_fp16_vs_pte_fp16']
    lm = metrics(ref[0], got_logits)
    assert_metric(lm, lim, 'logits')
    ref_cfg = ref[0][0:1].float() + CFG_WEIGHT * (ref[0][0:1].float() - ref[0][1:2].float())
    got_cfg = got_logits[0:1].float() + CFG_WEIGHT * (got_logits[0:1].float() - got_logits[1:2].float())
    if int(ref_cfg.argmax(-1)) != int(got_cfg.argmax(-1)):
        raise RuntimeError('PTE CFG top1 mismatch')

    # Check only populated prefill cache; future static region is zero by contract.
    populated = PREFILL_LEN
    km = metrics(ref[1][..., :populated, :], got_k[..., :populated, :])
    vm = metrics(ref[2][..., :populated, :], got_v[..., :populated, :])
    kv = {
        'max_abs': max(km['max_abs'], vm['max_abs']),
        'mean_abs': max(km['mean_abs'], vm['mean_abs']),
        'cosine': min(km['cosine'], vm['cosine']),
    }
    assert_metric(kv, lim, 'valid_kv')
    return pte, {'logits': lm, 'valid_kv': kv, 'cfg_top1': int(ref_cfg.argmax(-1))}


def main():
    t3_path = CKPT / 't3_mtl23ls_v3.safetensors'
    actual_sha = sha256(t3_path)
    if actual_sha != EXPECTED_T3_SHA:
        raise SystemExit(f'T3 SHA mismatch {actual_sha}')
    if os.environ.get('SINDEL_CHATTERBOX_COMMIT') != EXPECTED_COMMIT:
        raise SystemExit('Chatterbox commit environment mismatch')

    from chatterbox.models.t3 import T3
    from chatterbox.models.t3.modules.t3_config import T3Config
    t3 = T3(T3Config.multilingual())
    state = load_safetensors(t3_path)
    if 'model' in state:
        state = state['model'][0]
    t3.load_state_dict(state)
    del state
    t3.eval().cpu()
    wrapper = SindelT3Prefill(t3).eval()

    t0 = time.time()
    fp32_report = compare_source_adapted(t3, wrapper)
    parity_pre = {
        'schema': 'sindel.cp034.c05c.t3-prefill-source-parity.r3',
        'status': 'PASS',
        'tolerance_sha256': sha256(TOL_PATH),
        'contract_sha256': sha256(CONTRACT_PATH),
        't3_sha256': actual_sha,
        'fixtures': fp32_report,
        'elapsed_s': time.time() - t0,
    }
    (OUT / 'T3_PREFILL_SOURCE_PARITY_R3.json').write_text(json.dumps(parity_pre, indent=2), encoding='utf-8')

    # Export only after exact source-vs-fixed-layout parity has passed.
    t1 = time.time()
    pte, pte_report = export_and_pte_parity(wrapper)
    final = {
        'schema': 'sindel.cp034.c05c.t3-prefill-pte.r3',
        'status': 'PASS',
        'pte': {'name': pte.name, 'size': pte.stat().st_size, 'sha256': sha256(pte)},
        'tolerance_sha256': sha256(TOL_PATH),
        'contract_sha256': sha256(CONTRACT_PATH),
        'pytorch_fp16_vs_pte': pte_report,
        'elapsed_export_and_pte_test_s': time.time() - t1,
        'environment': {
            'python': sys.version,
            'torch': torch.__version__,
        },
    }
    (OUT / 'T3_PREFILL_PTE_REPORT_R3.json').write_text(json.dumps(final, indent=2), encoding='utf-8')
    print(json.dumps(final, indent=2))

if __name__ == '__main__':
    main()
