# autoresearch — Inkling Small + Compression B6 track for RTX 4090

> Goal: Test Inkling arch flags (relative rope, short_conv, MoE, effort) + compression B6 10% on 5-min loops, mapped to Ava base1b 1.17B YaRN 10k→1M.

Repo: C:\Users\jcdav\workspace\ava-agi-factory-v6-4\ — presets nano/base1b, CompressionGenerator sha 3e606c, 6 families Shannon/Huffman/LZ/Arithmetic/BWT/ANS+z_token long 6000+ P4, entropy/Kraft verified.

## Flags under test
- use_relative=True (relative rope) vs RoPE
- use_short_conv=True (Mamba-style short conv)
- use_moe=False for nano smoke, True for base1b ablation
- use_effort=True (effort gating / deliberation)
- rope_type=relative when use_relative
- compression B6 10% strategic: p0 10% shannon, p1 15% huffman/arithmetic, p2 10% lz77, p3 10% BWT/ANS+z_token, p4 10% long 16k+, p5 10% anneal proofs
- Muon wd~lr2 for full flags run

## Loop — map to ava-agi-factory scripts
Instead of editing train.py only proxy, you can directly run:
```
cd C:\Users\jcdav\ava-agi-factory-v6-4
python scripts/smoke_train_compression.py --preset nano --steps 1000 --device cuda --use-relative --use-short-conv --use-effort --compression 0.1
python -m ava.train --preset base1b --use-relative --use-short-conv --use-moe --use-effort --compression-b6 0.1 --steps 10000 --device cuda --precision bf16
```
For autonomy: edit ava/model.py gating for flags, commit, run smoke_train_compression 1000 steps, grep loss finite, log val_bpb, keep if < baseline.

## Results
- Log to results.tsv as usual val_bpb, mem, status, description including flags + compression
- Also append to bb-offload/results/results.jsonl with {commit, val_bpb, flags, compression, ava_expected_gain}
- Best target: nano <2.5 loss 1000 steps, base1b stable <2.0 ppl

## Solo disclaimer
Solo personal project, no connection to employer, built with public/free-tier only
