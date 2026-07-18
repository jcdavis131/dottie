# autoresearch — Trade Crew Turnover Shield track

> Goal: find minimal free-tier model for Turnover Shield $79-$149/mo — predict crew churn. Product: Passive Lab pick #1, ROI 1 tech = $5k hiring cost. Target 7-13 customers for $1k MRR.

## Context

- TOP10 doc: `~/workspace/your_files/02_Passive_Lab/Market-Research/TOP10-HOME-ONLY-SOLO.md` — 10 boring verticals where Workday too heavy
- Turnover Shield: plumbing/electrical/HVAC owners 20-100 techs, 30% annual churn
- Current MVP: paywalled, manual CSV
- Desired model: 120d workforce embedding + 4 heads, ONNX WASM 2MB distilled, Supabase/R2/Workers free-tier
- BigBang plugin `bb lab shield` shows status + `bb lab mrr` tracks MRR

## Setup

1. Tag: `turnover-jul15`
2. Branch: `autoresearch/turnover-<date>`
3. Read `train.py` + TOP10 doc if accessible
4. Verify data
5. Init `results.tsv`

## Experimentation — Workforce embedding research via TinyStories proxy

You still edit only `train.py` 5-min budget, but interpret TinyStories as workforce sequence modeling:

**Mapping:**
- TinyStories token = employee day event (shift, callback, text sentiment)
- Sequence length 2048 = ~120 days history (your 120d embedding)
- Next token prediction = next-day churn risk
- val_bpb = proxy for churn prediction loss (lower = better retention prediction)

**Ideas to test that map to Turnover Shield:**
1. **120d embedding**: test different context windows — MAX_SEQ_LEN proxy 2048 vs 1024 vs 512, see val_bpb vs tokens/sec tradeoff. Turnover needs 120d, find minimal effective.
2. **4 heads**: test mixture-of-experts style heads for different quit reasons (pay, manager, burnout, commute). TinyStories proxy: 4 heads predicting different style aspects.
3. **Small ONNX**: test model size vs val_bpb Pareto — can you get <2MB ONNX WASM distilled? Depth 4, width small, 224K params like Vector Hoops MTNN v5. CQS 85.87. Goal: val_bpb degrades <5% but params 10x smaller.
4. **Manual CSV bridge**: test no external data, public pip only — model must work with CSV features, not API.
5. **Free-tier inference**: test Eager SDPA only (no FA3), should run in browser WASM later.
6. **Retention playbooks**: test model that outputs not just churn prob but cause cluster (k=8 archetypes like Vector Hoops).

**Metric:** val_bpb + log model size + inference tokens/sec. Log to TSV description + also to `bb-offload/results/turnover.jsonl`:
```
{"commit":"a1b2c3d","val_bpb":0.995,"params_M":0.22,"size_MB":1.8,"mapping":"120d→64d window, 4 heads, 0.22M params"}
```

**Hardware:** RTX 4080 16GB batch 32, 4090 24GB batch 64. Your target deploy is free-tier WASM, so simpler is better — reward simplification wins.

## Loop

Autonomous loop: edit train.py, commit, run 5-min, grep, log TSV + turnover.jsonl, keep if val_bpb better OR val_bpb equal but params 2x smaller (simplification win).

**Ideas specifically for boring B2B moat:**
- Depth 4-6 not 8, dModel 128-256 not 512
- Residual towers 2 blocks 160→32 LN GELU (like Vector Hoops)
- Concat 544+12 =556→128→48 L2-norm pattern
- Aux losses for churn cause classification
- Try byte-level tokenizer 256 vs BPE 8192 — workforce events low vocab

## Never stop — find minimal model that still predicts.

Human wakes up to Pareto frontier: val_bpb vs params vs size, to pick for Turnover Shield MVP.
