# Hardware Profile — Davis Alienware RTX 4080/4090

## Detected from memory

- Machine: Alienware Windows box, Chrome Windows device_id 3de351a2-90b6-47e6-8c6f-755be480367c online at 2026-07-15T00:54:38Z, plus Android
- Path: `C:\Users\jcdav\workspace\vector-hoops` etc, training log `pipeline/cache/train_full.log`
- GPU: RTX 4080/4090 — user says RTX 4080/4090, CUDA local training at C:\Users\jcdav\...
- Docker: pytorch:2.4.0-cuda12.4-cudnn9, compose gpus all, extra_hosts host.docker.internal:host-gateway, WANDB offline
- Ollama: Ollama+Docker on personal machine, qwen3:32b ~20GB Q4, deepseek-r1:32b, llama3.3:70b ~40GB optional, glm4:9b-chat
- Ollama install Windows PowerShell: winget, ollama serve, ollama pull qwen3:32b deepseek-r1:32b glm4:9b-chat

## Upstream GPU profile logic (from train.py)

In `train.py` _resolve_gpu_profile:

- Architecture detection via torch.cuda.get_device_capability()
- Turing (7,5) >=8GB VRAM
- Ampere (8,6) >=10GB
- Ada (8,9) >=10GB
- Blackwell (12,0) >=10GB

Profiles:
- Turing 8-11GB: batch (8,4,2,1), checkpoint True, eval cap 4
- Mid-tier 10-15GB: batch (16,8,4), checkpoint True, eval cap 16 (profile default)
- 16GB: batch (32,16,8,4), checkpoint modes (False,True), default False, eval cap 16
- 24GB+: batch (64,32,16,8,4), checkpoint False, eval cap 16

Tier boundaries apply a ~0.5 GB tolerance (`VRAM_TIER_TOLERANCE_GB`) because real cards
under-report total VRAM (a 16 GB card shows ~15.99 GB); so >=15.5 GB lands in the 16GB
tier and >=23.5 GB in the 24GB+ tier.

A **desktop** RTX 4080 16GB → `ada-16gb`: batch candidates 32,16,8,4, checkpoint modes (False,True), default False, eval cap 16. Autotune usually picks 32, maybe 16 with checkpointing.
A **desktop** RTX 4090 24GB → `ada-24gb-plus`: batch 64,32,16,8,4, checkpoint False, eval cap 16, autotune picks 64.

### What THIS machine actually resolves to (measured 2026-08-01)

The two rows above are the desktop tiers. They are **not** what the dev box gets, and this
section used to say they were — it read "Your RTX 4080 16GB → `ada-16gb` batch 32", which
was wrong in four places at once.

`nvidia-smi` on this machine reports **`NVIDIA GeForce RTX 4080 Laptop GPU, 12282 MiB`**
(11.99 GB). Feeding exactly that through `_resolve_gpu_profile` gives:

| | doc used to claim | actually resolves |
|---|---|---|
| profile | `ada-16gb` | **`compatibility`** |
| max batch | 32 | **16** |
| default checkpointing | False | **True** |
| supported tier | yes | **no** — `is_supported_consumer=False` |

`_compatibility_warning` states the reason plainly: *"laptop GPUs are outside the supported
desktop matrix"*. The code is right and `test_laptop_falls_to_compatibility` already pins
it; only this document was wrong. A mobile 4080 is AD104 at a laptop power budget, not the
desktop AD103, so the exclusion is correct behaviour rather than a limitation to work
around — do not "fix" it by deleting the `is_laptop` check to unlock batch 32.

**Plan against batch 16 with checkpointing on**, not batch 32. Any throughput target on
this page derived from batch 32 (see the 300-500M tokens / 5 min figures below) was written
for a desktop card and has never been measured here.

**MFU on this box is measured against the wrong ceiling.** `_get_gpu_peak_flops` matches by
substring and has no laptop rows, so this card is credited the desktop 4080's 242.5 TFLOPS
— a peak it cannot reach. MFU is achieved/peak, so the reported figure reads LOW rather
than high, which is the quiet direction: the box looks inefficient instead of mismeasured.
Pinned by `test_laptop_peak_flops_collides_with_desktop_KNOWN_WRONG`. It is deliberately
not "fixed" by typing in a plausible mobile TFLOPS number — that would be a fabricated
constant, which is precisely what this repo's numbers rule forbids. It needs a measured
benchmark on the card. **Until then, treat MFU percentages from this machine as a lower
bound of unknown tightness, not as a number.**

## Custom tuning for Davis

We keep upstream profile logic but pre-document optimal candidates per card.

> **These are DESKTOP cards.** The dev box is a 4080 *Laptop* and gets `compatibility`,
> batch 16, checkpointing on — see "What THIS machine actually resolves to" above. The
> recommendations below have not been measured on it. This block previously introduced
> itself as "optimal candidates for your box", which is how a desktop spec sheet came to
> be read as a description of the machine actually running the trainer.

### RTX 4080 16GB (Ada, 9728 cores, 16GB GDDR6X, 320W) — desktop

- Peak FLOPS used for MFU: `_get_gpu_peak_flops` in train.py returns 242.5e12 (242.5 TFLOPS)
  for "4080" — the dense BF16 tensor-core figure the fork's MFU math is calibrated against
  (the "4080 super" entry is 260e12, matched first by substring order).
- Recommended batch: 32 without checkpoint for MFU ~40%
- If OOM near 16GB, fallback to 16 + checkpoint True
- BF16 amp_dtype (torch.cuda.is_bf16_supported includes emulation false → true on Ada ≥8.0)
- TF32 enabled: torch.backends.cuda.matmul.allow_tf32 = True
- SDPA backend: PyTorch SDPA run in eager mode — torch.compile is disabled in this fork's
  runtime path, so there is no compiled/FA3 fast path; the SDPA kernel dispatch (flash/mem-efficient/math)
  is left to PyTorch at runtime.
- `PYTORCH_ALLOC_CONF=expandable_segments:True` mitigates fragmentation on Windows.

### RTX 4090 24GB (Ada, 16384 cores, 24GB GDDR6X, 450W, peak BF16 ~330 TFLOPS) — desktop

- Recommended batch: 64 without checkpoint, eval batch cap 16
- Can handle 64+32+16+8+4 candidates
- Same BF16, TF32, SDPA
- Can get ~500M tokens / 5min vs ~300M on 4080

### Optimizations for this fork

- No torch.compile (disabled in this fork runtime path) to keep stability on Windows consumer GPUs. Original upstream had FA3/fast path on H100 but removed for Windows.
- Autotune: short eager-mode pass with 2 warmup + 3 measure steps, 90% memory fraction, caches per GPU fingerprint to `%LOCALAPPDATA%\autoresearch\gpu-profile-v2.json`. Use `AUTORESEARCH_DISABLE_AUTOTUNE=1` to skip, `AUTORESEARCH_AUTOTUNE_REFRESH=1` to refresh.
- Windows-specific: LOCALAPPDATA cache, not .cache.

## How autoresearch finds best model for your platform

Because time budget fixed 5-min, batch size directly trades tokens vs steps. Larger batch → more tokens per step but fewer steps. Autotune probes candidates and picks max tokens without OOM.

For your 4080/4090, you will see after smoke test:

```
val_bpb: 0.99...
peak_vram_mb: ~12000 for 4080 / ~18000 for 4090 depending batch
mfu_percent: 30-45%
total_tokens_M: 300-500M
num_steps: 500-1000
```

Lower val_bpb is better, vocab-independent.

## Recommendations for offloading

- **Turnover Shield research**: depth 4-6, width small, batch 32, no checkpoint, target params 0.2-0.5M. Fits your 4080 easily, can run 100 exps overnight.
- **Ava research**: depth 6-8, GQA 4, YaRN, WSD, batch 32/64, params 50M. Your 4090 can handle.
- **Write research**: depth 4, small, batch 16, params 0.1M, detector logic inside train.py, fast.

## Comparison to your Ava Docker stack

Your Ava Docker pytorch:2.4.0-cuda12.4-cudnn9 is slightly older than this fork's torch 2.9.1 cu128. For consistency, you can either:

- Use uv native (this fork's recommended) for fast 5-min loops
- Or port wins into Ava Docker for longer runs: copy train.py idea into Ava model_1b.py

Both share same CUDA driver, so VRAM usage comparable.

## Verifying your setup

In PowerShell:

```powershell
nvidia-smi
# should show RTX 4080 or 4090, driver >= 560, CUDA 12.8 etc
uv run python -c "import torch; print(torch.cuda.get_device_name(), torch.cuda.get_device_capability(), torch.cuda.is_bf16_supported())"
```

Expected: `NVIDIA GeForce RTX 4090 (8, 9) True` or similar.

If BF16 false, fallback FP16 still works but slower.

## Notes for future Blackwell

If you upgrade to RTX 5090 32GB Blackwell (12,0): Blackwell has capability (12,0) with the same >=10GB floor, so `_resolve_gpu_profile` yields the `blackwell-24gb-plus` profile — same batch candidates (64,32,16,8,4) and no default checkpointing as ada-24gb-plus. Peak FLOPS 360e12 for "5090" per the lookup table.

## Solo disclaimer

Solo personal project, no connection to employer, built with public/free-tier only. No work data.
