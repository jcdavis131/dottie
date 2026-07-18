# Spec 08 — Alienware GPU Training Runbook + mini/base1b Presets

- **Spec ID:** 08_alienware_runbook
- **Worker tier:** Sonnet
- **Dependencies:** Spec 01 (`ava/config.py` AvaConfig + preset loader, Makefile); the training
  spec's `ava/train.py` (`--preset`, `--resume`, metrics.jsonl writer); Spec 07
  (`scripts/make_report.py` referenced by the ops section). GPU steps are executed BY THE USER on
  their machine — the container only validates that the documents and configs are correct and load.
- **Target machine:** Alienware m16 laptop, RTX 4080 Laptop GPU 12GB VRAM, Windows 11 + WSL2
  (Ubuntu). Network is unrestricted there (unlike the build container).

## Purpose

Give the user a copy-paste-safe runbook to take the validated nano recipe to GPU scale on their
own laptop: WSL2 setup, two new presets (`mini` ~160M, `base1b` ~1.0–1.2B) with HONEST arithmetic
they can recompute, a milestone schedule that is stop-anytime under WSD, and laptop-specific ops
(thermals, resume, disk). The presets are consumed by the SAME `ava/train.py` used for nano.

## Deliverable files (exact paths, repo-relative)

1. `docs/ALIENWARE_RUNBOOK.md` (the runbook; 300–600 lines)
2. `configs/mini.yaml`
3. `configs/base1b.yaml`
4. Minimal ADDITIVE edits to `ava/config.py` / `ava/train.py` ONLY if the new config keys below
   are not yet supported (new optional fields with nano-preserving defaults; `make smoke` must
   stay green). No renames, no behavior change for existing presets.

## Detailed requirements

### (a) Runbook section 1 — WSL2 + CUDA setup

- Windows side: install ONLY the NVIDIA Windows driver (Game Ready/Studio ≥ 551.xx). NO CUDA
  toolkit inside WSL is needed for torch wheels (they bundle CUDA runtime).
- `wsl --install Ubuntu-24.04`, then inside WSL: verify `nvidia-smi` works (driver is passed
  through via `/usr/lib/wsl/lib` — never `apt install nvidia-driver-*` inside WSL).
- `python3.11 -m venv ~/ava-venv && source ~/ava-venv/bin/activate`, repo clone,
  `pip install torch --index-url https://download.pytorch.org/whl/cu124` (note: default PyPI also
  ships a cu-enabled wheel; either is fine — verify with the check below), `pip install
  bitsandbytes`, then the repo's spec-01 deps.
- Verification block (must appear verbatim as runnable commands):
  `nvidia-smi` and
  `python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"`
  → expect `True` and `NVIDIA GeForce RTX 4080 Laptop GPU`.
- WSL2 quirks callout box: (1) `nvidia-smi` inside WSL reports the Windows driver's view of VRAM;
  per-process memory numbers can be blank — trust `torch.cuda.memory_allocated()`. (2) libcuda
  lives at `/usr/lib/wsl/lib`; do not shadow it with conda cudatoolkit. (3) If hitting OOM near
  the 12GB limit or seeing stutter, disable Windows "Hardware-accelerated GPU scheduling" and
  close DWM-heavy apps; Windows itself reserves ~0.5–1GB VRAM. (4) Set `~/.wslconfig` with
  `memory=24GB` and swap so the dataloader has RAM.

### (b) Runbook section 2 — Presets with honest arithmetic

Every estimate MUST show its formula so the user can recompute. Required formulas (verbatim in
the runbook): params `P ≈ V·d (tied embed) + L·(attn + mlp) + verbalizer + Σslots·d`;
compute `FLOPs/token ≈ 6P × 3` (the ×3 is a conservative planning factor covering attention at
ctx ≥ 512, Multi-J-Space aux losses, and recompute overhead); time `= token_budget / tok_s`.

- **configs/mini.yaml — ALREADY COMMITTED, authoritative** (nested `model:`/`jspace:`/`training:`/
  `phases:` schema, space keys `system1..planner`). Headline values: d768, 12 heads × 64,
  layers 3/6/3, vocab 32000 `tie_lm_head: true` `tie_verbalizer: false`, `mlp: swiglu`
  `mlp_ratio: 4.0`, half-lives 8/300/30/150, bf16, `compile: true`, 2.5B-token 6-phase
  curriculum (seq 512→4096), WSD warmup 300 / stable_frac 0.92 / lr 6e-4→6e-5. The worker only
  amends it if `--count-params` lands outside the acceptance band (record any change as a
  comment in the yaml).
  - Arithmetic to print in the runbook: embed 32000×768 = 24.6M; per layer 4d² attn + 12d²
    SwiGLU(4x, 3 mats) ≈ 9.4M × 12 layers = 113M; untied verbalizer 24.6M; slots 144×768 ≈ 0.1M
    → **P ≈ 162M**. FLOPs/token ≈ 6×1.6e8×3 ≈ **2.9e9**. RTX 4080 Laptop ≈ 25–40 effective
    TFLOPS bf16 (peak dense tensor 60–90 clock/power dependent, at 35–45% MFU) → **est 6–10k
    tok/s** measured → 2.5B tokens ≈ **3–5 days**. VRAM: weights bf16 0.32GB + grads 0.32GB +
    AdamW fp32 states ~1.3GB + activations @ctx512×mb16 → ~5–7GB total: fits 12GB easily, NO
    gradient checkpointing needed until ctx 2048+.
- **configs/base1b.yaml — ALREADY COMMITTED, authoritative** (same nested schema). Headline
  values: vocab 32000 TIED (deliberately trims the blueprint's accidental ~2.9B from untied
  128k-vocab embeddings + 4x MLP at d2048×48), d2048, 16 heads × 128, `n_kv_heads: 4` (GQA),
  layers 12/28/8, `mlp: swiglu` `mlp_ratio: 1.0` (hidden 2048 — the blueprint's 4x MLP at this
  depth/width alone is 2.4B), `tie_verbalizer: true`, half-lives 8/300/30/150, bf16,
  `gradient_checkpointing: true`, `optimizer: adamw8bit` (bitsandbytes), WSD warmup 2000 /
  stable_frac 0.92 / lr 2e-4→2e-5 (blueprint values), `milestones:` M1 2B / M2 10B / M3 30B+
  with per-phase `frac:` proportions, and a `branches:` section (code/math/chat). The worker
  only amends it if `--count-params` lands outside the acceptance band (record as yaml comment).
  - Arithmetic: embed 65.5M tied; per layer GQA attn (q 4.19M + k,v 2×1.05M + o 4.19M = 10.5M) +
    SwiGLU h=2048 (3×2048² = 12.6M) = 23.1M × 48 = 1.109B; verbalizer tied (+0); slots ~0.3M →
    **P ≈ 1.17B** (target band 1.0–1.2B). FLOPs/token ≈ 6×1e9×3 ≈ **1.8e10**. VRAM: bf16 weights
    2.3GB + bf16 grads 2.3GB + bitsandbytes 8-bit AdamW ~2.3GB + activations with FULL gradient
    checkpointing at ctx 2048 micro-batch 1–2 ≈ 1–2GB + CUDA context ~1GB → **~9–10GB, fits
    12GB**. Throughput: 25–40 TFLOPS / 1.8e10 minus recompute → **~1.0–1.5k tok/s ≈ 100M
    tokens/day** → 1B tokens ≈ **9–12 days**. Chinchilla-optimal ~20B tokens ≈ **6 months** —
    hence milestones, not one run.
  - MILESTONE schedule (WSD stable checkpoints at every phase boundary make this stop-anytime):
    **M1** 2B tokens (Phase 0–1 logic/math, ~3 weeks) → DECISION GATE on eval results (5-test
    harness + mini-extrapolated loss; verbalizable_mass 0.05–0.08, broadcast 0.18–0.24, hl within
    30% of targets); **M2** 10B (through Phase 2 foundation); **M3** 30B+ (Phases 3–5 + branches).
    Branch fine-tunes (code/math/chat per `train_1b_deepspeed.py` `BRANCH_CONFIGS` — freeze sets,
    router biases, per-branch LR 1e-4/8e-5/5e-5) fork from ANY stable checkpoint.
- **Sequencing (required diagram/paragraph):** nano (CPU sanity — also runs on the Alienware in
  minutes–hours) → mini (validates curriculum + J-losses at GPU scale; the GO/NO-GO gate for
  base1b) → base1b M1 → gate → M2 → M3.

### (c) Runbook section 3 — Ops

- Long runs under `tmux` (session `ava`) or `nohup python -m ava.train --preset base1b >
  runs/base1b/train.log 2>&1 &`; laptop sleep/reboot recovery via
  `python -m ava.train --preset base1b --resume` (latest checkpoint in `run_dir`).
- Monitoring: `runs/<preset>/metrics.jsonl` rendered locally with
  `python scripts/make_report.py --runs runs --out reports/index.html`; wandb is fine on the
  Alienware — document `WANDB_MODE=offline` + `wandb sync` as the default (opt-in online).
- Thermals (laptop GPU): sustained clocks will be below spec sheet; if thermal throttling
  (`nvidia-smi -q -d PERFORMANCE` shows SW Thermal Slowdown), cap power:
  `sudo nvidia-smi -pl 120` (range to try: 100–140W) — a 10–20% tok/s haircut is normal and the
  time estimates above already assume it. Watch with
  `nvidia-smi --query-gpu=temperature.gpu,power.draw,clocks.sm --format=csv -l 5`.
- Disk sizing: a base1b checkpoint with optimizer state included is ~6GB (bf16 weights 2.3GB +
  8-bit optim 2.3GB + fp32 master/metadata); keep-last-3 rotation + one stable checkpoint per
  phase boundary → budget **≥ 100GB free** in the WSL ext4 volume (not /mnt/c — 5–10x slower IO).

### (d) Runbook section 4 — torch.compile + SDPA

- Enable `--compile` on mini FIRST (WSL2-supported); document the fallback `--no-compile` (or
  `TORCHDYNAMO_DISABLE=1`) if graph breaks appear in the J-space routing code; expect 1.2–1.5x.
- Attention MUST go through `torch.nn.functional.scaled_dot_product_attention` so the flash
  backend engages on CUDA automatically. Do NOT require the `flash-attn` pip package (fragile on
  WSL2); note `torch.backends.cuda.sdp_kernel` / `sdpa_kernel` for forcing backends when
  debugging.

### Trainer capability check (top of the runbook, and gate for the additive-edit clause)

List the flags/keys the presets rely on: `--preset`, `--resume`, `--compile/--no-compile`,
`precision: bf16` autocast, `grad_checkpoint`, `optimizer: adamw8bit` (import bitsandbytes lazily;
on CPU/no-bnb fall back to torch AdamW with a printed warning), `mlp_ratio`, `n_kv_heads`,
`tie_verbalizer`, `micro_batch`, `grad_accum`. Any missing key/flag is added per Deliverable 4
with defaults that reproduce current nano behavior exactly.

## Interfaces

- `AvaConfig.load("mini")` / `AvaConfig.load("base1b")` return the values above — frozen contract
  for later branch/eval specs. New AvaConfig fields are optional-with-defaults; spec-01 field
  names are unchanged.
- `python -m ava.train --preset mini|base1b` is the ONLY entry point the runbook may instruct
  (plus `--resume`, `--compile`). No new training scripts.

## Acceptance criteria (foreman runs in the CPU container; GPU steps are user-executed)

1. `python -m ava.config --preset mini --count-params` → exit 0, count in
   [140,000,000, 175,000,000].
2. `python -m ava.config --preset base1b --count-params` → exit 0, count in
   [1,000,000,000, 1,250,000,000].
3. `python -c "from ava.config import AvaConfig; c=AvaConfig.load('base1b'); assert c.vocab_size==32000 and c.d_model==2048"` → exit 0.
4. `make smoke` (nano_quick, CPU) still green — proves any additive trainer edits didn't regress.
5. `grep -c 'nvidia-smi' docs/ALIENWARE_RUNBOOK.md` ≥ 4; `grep -c 'whl/cu124\|bitsandbytes\|scaled_dot_product_attention\|nvidia-smi -pl\|--resume\|/usr/lib/wsl/lib' docs/ALIENWARE_RUNBOOK.md` ≥ 6
   (all six topics present).
6. Every throughput/VRAM/day estimate in the runbook is adjacent to its formula (spot-checked:
   the strings `6P`, `FLOPs/token`, and at least three explicit multiplications like `× 48`
   appear).
7. `git status --porcelain` → only new `docs/ALIENWARE_RUNBOOK.md`, `configs/mini.yaml`,
   `configs/base1b.yaml`, plus (if needed) modified `ava/config.py` / `ava/train.py`.

## Out of scope

- Actually running mini/base1b training (no GPU in the container). Multi-GPU, deepspeed, FSDP.
- Data generation at mini/base1b scale (curriculum data spec owns `data/mini`, `data/base1b`).
- Windows-native (non-WSL) training, macOS, cloud GPUs. flash-attn pip package.
- The 15T-token blueprint schedule — milestones above supersede it for this hardware.
- Modifying blueprint files (`train_1b_deepspeed.py` etc.); committing to git.
