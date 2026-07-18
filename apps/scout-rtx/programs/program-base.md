# autoresearch — Base track for RTX 4080/4090

This is an experiment to have the LLM do its own research — BASELINE track, customized for Davis Alienware.

## Setup (your Alienware)

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date + gpu (e.g. `rtx4090-jul15`). The branch `autoresearch/<tag>` must not already exist.
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from current master.
3. **Read the in-scope files**: The repo is small. Read these files for full context:
   - `README.md` — custom Davis fork context, hardware profile RTX 4080 16GB / 4090 24GB.
   - `prepare.py` — fixed constants, data prep, tokenizer, dataloader, evaluation. Do not modify.
   - `train.py` — the file you modify. Model architecture, optimizer, training loop. This file already has RTX 4080/4090 tuning: ada-16gb batch 32, ada-24gb-plus batch 64, BF16, TF32, SDPA.
4. **Verify data exists**: Check that `%LOCALAPPDATA%\autoresearch\` (Windows) contains data shards and a tokenizer. If not, tell human to run `uv run prepare.py` or `.\scripts\setup-win.ps1`.
5. **Initialize results.tsv**: Create `results.tsv` with just the header row. The baseline will be recorded after the first run.
6. **Confirm and go**: Confirm setup looks good, print GPU profile detected.

Once you get confirmation, kick off the experimentation.

## Experimentation — RTX 4080/4090 optimized

Each experiment runs on a single GPU. Training runs for **fixed 5-min time budget** (wall clock training, excluding startup/compilation). You launch: `uv run train.py`

**Your hardware:** RTX 4080 16GB or RTX 4090 24GB, Ada 8.9, BF16, TF32, SDPA eager, no torch.compile, expandable_segments:True. You have 330 TFLOPS (4090) peak.

**What you CAN do:**
- Modify `train.py` — only file you edit. Architecture, optimizer, hyperparams, batch size, model size. For 16GB, prefer batch 16-32 + checkpoint True sometimes. For 24GB, prefer batch 32-64 + checkpoint False for MFU.

**What you CANNOT do:**
- Modify `prepare.py`. Read-only.
- Install new packages.
- Modify evaluation harness `evaluate_bpb`.

**Goal: lowest val_bpb.** 5-min fixed. VRAM soft constraint — 16GB box should stay <15.5GB, 24GB <23GB.

**Simplicity criterion:** simpler is better. Delete code if equal. Weigh complexity vs improvement.

**First run:** always baseline as-is.

## Output format

```
---
val_bpb:          0.997900
training_seconds: 300.1
total_seconds:    325.9
peak_vram_mb:     12000.2
mfu_percent:      39.80
total_tokens_M:   499.6
num_steps:        953
num_params_M:     50.3
depth:            8
```

Extract: `Select-String "val_bpb:" run.log` or `grep "^val_bpb:"`

## Logging results

Tab-separated TSV `results.tsv`:

```
commit	val_bpb	memory_gb	status	description
```

- commit short 7 chars
- val_bpb 1.234567 or 0.000000 crash
- memory_gb peak_vram_mb/1024 .1f or 0.0 crash
- status keep/discard/crash
- description short

Example:
```
a1b2c3d	0.997900	11.7	keep	baseline RTX4090 24GB batch64
```

## The experiment loop — AUTONOMOUS, NEVER STOP

LOOP FOREVER:

1. Look at git state
2. Tune `train.py` with idea (arch, LR, Muon, batch, RoPE YaRN, GQA, etc)
3. git commit
4. Run: `uv run train.py > run.log 2>&1` (redirect, no tee)
5. Read results: `Select-String "^val_bpb:|^peak_vram_mb:" run.log`
6. If empty → crash → `Get-Content run.log -Tail 50` → fix or log crash
7. Record TSV
8. If val_bpb improved (lower) → keep commit (advance)
9. If worse → git reset back

**Timeout:** ~5 min total. If >10 min, kill, discard, revert.

**Crashes:** fix typo if easy, else log crash 0.0 and move on.

**NEVER STOP:** Do NOT pause to ask human. If out of ideas, read papers referenced, try combining near-misses, try radical changes. Loop until human interrupts.

**RTX 4080/4090 specific ideas to try:**
- Batch 32 vs 64, grad accum, DEVICE_BATCH_SIZE candidates from profile
- Muon LR schedule WSD vs cosine
- Depth 4-8, width scaling, GQA
- WINDOW_PATTERN "L" vs "SSSL"
- RoPE YaRN if vocab allows
- Activation checkpointing False for MFU on 24GB, True for 16GB memory save
- BF16 vs FP16 amp_dtype (BF16 should win on Ada)
- SDPA flash vs eager (currently SDPA forced, but you can tune is_causal)
- Remove complexity: can you delete layers and keep same val_bpb?

**BigBang integration:** After each kept experiment, also append to `bb-offload/results/results.jsonl` via `bigbang-bridge` so Hatch cloud can see via `bb rtx results`.
