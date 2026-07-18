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

Your RTX 4080 16GB → `ada-16gb` profile: batch candidates 32,16,8,4, checkpoint modes (False,True), default False, eval cap 16. Autotune will pick 32 usually, maybe 16 if using checkpoint.
Your RTX 4090 24GB → `ada-24gb-plus`: batch 64,32,16,8,4, checkpoint False, eval cap 16, autotune picks 64.

## Custom tuning for Davis

We keep upstream profile logic but pre-document optimal candidates for your box:

### RTX 4080 16GB (Ada, 9728 cores, 16GB GDDR6X, 320W)

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

### RTX 4090 24GB (Ada, 16384 cores, 24GB GDDR6X, 450W, peak BF16 ~330 TFLOPS)

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
