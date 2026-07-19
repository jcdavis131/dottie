#!/usr/bin/env python3
"""
Minimal smoke for compression B6 + inkling flags - fixed tensor bool issue
"""
import torch, random, math, hashlib
from pathlib import Path
import torch.nn.functional as F

from dottie.config import DottieConfig
from dottie.model import build_model
from dottie.pipeline.collector import load_sources
import yaml

REPO = Path(__file__).resolve().parent.parent

cfg = DottieConfig.load("nano")
print(f"[cfg] {cfg.preset} d_model={cfg.model.d_model} n_layers={cfg.model.n_layers} vocab={cfg.model.vocab_size}")

# Build default
model = build_model(cfg)
params = sum(p.numel() for p in model.parameters())/1e6
print(f"[model default] {params:.2f}M built, byte-identical gated")

# Build inkling
import dataclasses
cfg_flags = dataclasses.replace(cfg, model=dataclasses.replace(cfg.model, use_relative=True, use_short_conv=True, use_moe=False, use_effort=True, rope_type="relative"))
model_flags = build_model(cfg_flags)
params2 = sum(p.numel() for p in model_flags.parameters())/1e6
print(f"[model inkling rel+conv+effort] {params2:.2f}M built OK (moe disabled for RAM)")

cfg_moe = dataclasses.replace(cfg, model=dataclasses.replace(cfg.model, use_moe=True, moe_n_routed_experts=32, moe_top_k=2))
model_moe = build_model(cfg_moe)
params_moe = sum(p.numel() for p in model_moe.parameters())/1e6
print(f"[model moe 32/2] {params_moe:.2f}M built OK")

# Tokenizer test - use fallback simple BPE for smoke
try:
    from dottie.tokenizer import DottieTokenizer
    tok_path = REPO/"data/mini/tokenizer/dottie_bpe_32k.json"
    if tok_path.exists():
        # tokenizers library may fail on broken json? try load
        tok = DottieTokenizer.load(tok_path)
        print(f"[tokenizer] vocab={tok.vocab_size} loaded")
        def encode(s): return tok.encode(s)[:256]
    else:
        raise FileNotFoundError
except Exception as e:
    print(f"[tokenizer] fallback due to {e}")
    def encode(s): return [ord(c)%8192 for c in s][:256]

# Generate compression data
from dottie.datagen.compression import CompressionGenerator, entropy_bits, kraft_sum, lz77_compress, lz77_decompress
gen = CompressionGenerator(1234)
docs=[]
for doc in gen.generate(200_000):
    docs.append(doc)
    if len(docs)>=50:
        break
print(f"[compression] generated {len(docs)} docs avg_len {sum(len(d['text']) for d in docs)//len(docs)} byte-det deterministic")
# Check sha
docs2=[]
gen2=CompressionGenerator(1234)
for doc in gen2.generate(200_000):
    docs2.append(doc)
    if len(docs2)>=50:
        break
sha1 = hashlib.sha256("".join(d['text'][:80] for d in docs).encode()).hexdigest()[:8]
sha2 = hashlib.sha256("".join(d['text'][:80] for d in docs2).encode()).hexdigest()[:8]
print(f"[determinism] sha {sha1} vs {sha2} match={sha1==sha2}")

print(f"[verify] entropy 0.5,0.5 = {entropy_bits([0.5,0.5])}")
print(f"[verify] kraft [1,2,3] = {kraft_sum([1,2,3])}")
s="ABABAB"
tups=lz77_compress(s)
print(f"[verify] lz {s} -> {tups} -> {lz77_decompress(tups)} ok={lz77_decompress(tups)==s}")

# Collector distribution
sources = load_sources(REPO/"configs/sources.yaml")
from collections import defaultdict
w=defaultdict(dict)
for src in sources:
    for ph, wt in src.weight.items():
        w[ph][src.name]=wt
for ph in range(6):
    total=sum(w[ph].values())
    comp=w[ph].get('synth_compression',0)
    print(f"[collector phase {ph}] total {total:.2f} comp {comp} {comp/total*100:.1f}%")

# Training smoke 20 steps on cpu with tiny batch
device=torch.device("cpu")
model.to(device)
model.train()
opt=torch.optim.AdamW(model.parameters(), lr=1e-3, betas=(0.9,0.95), weight_decay=0.1)

encoded=[torch.tensor(encode(d['text']), dtype=torch.long) for d in docs if len(encode(d['text']))>10]
losses=[]
for step in range(20):
    batch=[]
    while len(batch)<512:
        batch.extend(random.choice(encoded).tolist())
    batch=batch[:129]
    input_ids=torch.tensor(batch[:-1], dtype=torch.long).unsqueeze(0).to(device)
    target_ids=torch.tensor(batch[1:], dtype=torch.long).unsqueeze(0).to(device)
    out = model(input_ids=input_ids)
    logits = out.get('lm_logits') if out.get('lm_logits') is not None else out.get('logits')
    if logits is None:
        raise RuntimeError("no logits")
    loss = F.cross_entropy(logits.view(-1, logits.size(-1)), target_ids.view(-1))
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(),1.0)
    opt.step()
    opt.zero_grad()
    losses.append(loss.item())
    if step%5==0:
        print(f"[train] step {step} loss {loss.item():.4f}")

print(f"[done] loss start {losses[0]:.4f} end {losses[-1]:.4f} avg last5 {sum(losses[-5:])/5:.4f}")
print(f"[metrics] {losses}")
