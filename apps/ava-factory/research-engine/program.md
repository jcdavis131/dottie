# Ava Research Engine — program.md (autoresearch org code)
# Solo personal project, no connection to employer, built with public/free-tier only
# Adapted from Karpathy https://github.com/karpathy/autoresearch program.md concepts

This is an experiment to have the LLM do its own research for the Ava AGI Factory v6.4 + BigBang CLI + Graphify + Vector MTNN ecosystem, powered by a continuously-updating Graphify knowledge base of latest arxiv research.

## Vision

- **One day, frontier AI research used to be done by meat computers in between eating, sleeping, having other fun, and synchronizing once in a while using sound wave interconnect in the ritual of "group meeting". That era is long gone. Research is now entirely the domain of autonomous swarms of Ava agents running across your Alienware + Hatch compute.**
- This program.md is the "research org code" — it defines how autonomous agents turn latest arxiv papers (harvested daily) into experiments in Ava.

## Setup (one-time, then loop forever)

To set up a new autoresearch run for Ava:

1. **Agree on a run tag**: propose a tag based on today's date + topic, e.g. `jul15-muon-s1-fast`. The branch `autoresearch/<tag>` must not already exist — this is a fresh run. Use `git branch -a | grep autoresearch` to check.

2. **Create the branch**: `git checkout -b autoresearch/<tag>` from current master in `~/workspace/ava-agi-factory-v6-4` OR `~/workspace/ava-research-engine` depending on scope:
   - If experiment modifies training (model_1b.py, multi_jspace_module.py, train_1b_deepspeed.py) → branch in `ava-agi-factory-v6-4`
   - If experiment modifies BigBang (core/http_utils, mcp_client, openapi, llm router) → branch in `bigbang-cli`
   - If experiment modifies graphify or LLM wikis → branch in `ava-research-engine`

3. **Read the in-scope files**: The ecosystem is small but cross-repo. Read for full context:
   - `~/workspace/ava-agi-factory-v6-4/README.md` — Ava v6.4 real-mode Jacobian multi-space (S1 Fast 32 hl=8 S2 Slow 64 hl=300 Critic 16 hl=30 Planner 32 hl=150 + Router/veto, train_1b_deepspeed.py WSD 736k 92% stable)
   - `~/workspace/ava-agi-factory-v6-4/model_1b.py` — 1.17B d2048 48L GQA4 SWIGLU tied 32k vocab
   - `~/workspace/ava-agi-factory-v6-4/multi_jspace_module.py` — 4 workspaces
   - `~/workspace/ava-agi-factory-v6-4/specs/` — specs 01-10 SOTA harness
   - `~/workspace/bigbang-cli/docs/ARCHITECTURE.md` v0.4.1 — tasks wired, graphify 727 nodes 1713 edges
   - `~/workspace/ava-research-engine/config/topics.yaml` — 7 topics with arxiv queries
   - `~/workspace/your_files/research/arxiv/rolling_index.json` — latest papers
   - `~/workspace/ava-research-engine/graphify_source/*.md` — curated markdown for pgraphify
   - `~/workspace/bigbang-cli/graphify-out-research/graph.json` — knowledge graph
   - `~/workspace/bigbang-cli/docs/llm-wiki/research-latest.md` — latest research summary

4. **Verify data exists**: Check that `~/workspace/your_files/research/arxiv/rolling_index.json` contains papers and `graphify_source/` has >0 markdowns. If not, tell human to run `python3 scripts/arxiv_harvester.py`.

5. **Initialize results.tsv**: Create `~/workspace/ava-research-engine/results/results.tsv` with header:
```
commit	val_bpb	memory_gb	status	description
```
If exists, keep it — it is append-only log. Baseline will be recorded after first run.

6. **Confirm and go**: Confirm setup looks good, then kick off LOOP.

## Experimentation (Karpathy-style, adapted for Ava)

Each experiment runs on a single GPU on Alienware (RTX 4080/4090) or CPU smoke in Hatch VM. Training script runs for a **fixed time budget of 5 minutes** (wall clock training time, excluding startup/compilation) for cheap iteration, OR for longer 30-60m for serious Ava 1B runs. The metric is **val_bpb** (validation bits per byte) — lower is better, vocab-size-independent. For branch eval, metric is cap preservation 0.983 + Align 0.91.

**What you CAN do:**
- Modify ONE primary file per experiment for clean diffs:
  - For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py` (Ava)
  - For routing ideas: `bigbang/plugins/ava/cli.py` _heuristic_route or `bigbang/core/llm.py`
  - For graphify ideas: `scripts/graphify_research.py` OR `personal-graphify` src
  - For MTNN ideas: `vector-hoops/pipeline/rebuild_all.py`
- Everything is fair game: model architecture, optimizer (Muon vs AdamW), hyperparameters, batch size, model size, YaRN extension, J-space hl, Router veto, etc.
- You can reference papers from `graphify_source/` — cite arxiv id in commit message and description.

**What you CANNOT do:**
- Modify `prepare.py` equivalent (for Ava, that's data_builder_agent.py or fixed constants) unless spec says so.
- Install new packages without checking pyproject.toml or requirements.txt — use public pip only, free-tier
- Modify evaluation harness ground truth (eval_harness.py, eval_branch_harness.py, eval_frontier_rubric.py) — metrics are sacred
- Touch `03_Meta_Work_ISOLATED` — zero leakage, home-life only, solo personal project
- Invent data or fake eval numbers — truthful flow per Vector Hoops CQS 85.87 leakfree standard

**The goal is simple: get the lowest val_bpb OR highest cap preservation with simplest code.** Since time budget is fixed at 5 min for quick loops, you don't worry about training time. Weigh simplicity: A 0.001 val_bpb improvement that adds 20 lines of hacky code? Probably discard. A 0.001 improvement from deleting code? Definitely keep.

**The first run**: Always establish baseline — run training script as-is, without modifications, log it.

## Output format (per run)

Once script finishes it prints a summary like this (Ava adapted):
```
---
val_bpb:          0.997900
training_seconds: 300.1
total_seconds:    325.9
peak_vram_mb:     45060.2
mfu_percent:      39.80
total_tokens_M:   499.6
num_steps:        953
num_params_M:     50.3
depth:            8
cap_preservation: 1.0
branch:           S1 Fast hl=8
---
```

You can extract key metrics:
```bash
grep "^val_bpb:\|^peak_vram_mb:\|^cap_preservation:" run.log
```

## Logging results (results.tsv)

When experiment done, log to `~/workspace/ava-research-engine/results/results.tsv` (tab-separated, NOT comma-separated — commas break in descriptions).

```
commit	val_bpb	memory_gb	status	description
a1b2c3d	0.997900	44.0	keep	baseline S1 Fast 32 hl=8 — no mods
b2c3d4e	0.993200	44.2	keep	Muon optimizer for S1 Fast — arxiv:2404.xxxxx Muon — 5m budget
c3d4e5f	1.005000	44.0	discard	switch S2 Slow hl 300->150 GeLU — too aggressive
d4e5f6g	0.000000	0.0	crash	double model width OOM — arxiv:2405.yyyyy
```

1. git commit hash short 7 chars
2. val_bpb achieved (e.g. 1.234567) — use 0.000000 for crashes
3. peak memory in GB, rounded .1f — 0.0 for crashes
4. status: keep, discard, or crash
5. short text description including arxiv id if from research queue

**NOTE: do not commit results.tsv to git — leave it untracked, but sync to `your_files/ava-agi/` for backup.**

## The experiment loop (NEVER STOP)

The experiment runs on a dedicated branch (e.g. `autoresearch/jul15-muon-s1`).

LOOP FOREVER (until human stops you — you are autonomous, program.md is your manager):

1. Look at git state: current branch/commit
2. **Pick next research task** from:
   - `bb tasks list --tasklist MDg4NTEzMTkzNjgwNzI5NDMyMDI6MDow --json` filter for [AVA-RESEARCH] not yet attempted
   - OR `~/workspace/your_files/research/arxiv/rolling_index.json` latest papers with topics matching weak domains from `frontier_eval_results.json` / `branch_eval_results.json`
   - OR `graphify_source/` markdowns not yet in results.tsv description
3. Tune ONE file with experimental idea from paper — directly hack the code, keep diff readable.
   - Cite paper in comment: `# From arxiv:2404.xxxxx Muon — trying for S1 Fast`
4. git commit -m "exp: <topic> <arxiv_id> <short desc> — program.md autoresearch"
5. Run experiment:
   - Quick smoke in Hatch VM (no GPU): `python -m ava.config --preset nano --count-params` or `python3 -m pytest -q` or `python -m ava.train --preset nano_quick --max-steps 20`
   - Full run on Alienware: `docker-compose up trainer --preset base1b` OR `uv run train.py` (Karpathy baseline) OR `python train_1b_deepspeed.py` — redirect everything: `> run.log 2>&1` (DO NOT use tee or flood context)
6. Read out results: `grep "^val_bpb:\|^peak_vram_mb:\|^cap_preservation:" run.log`
7. If empty → crash. Tail log `tail -n 50 run.log` to see stack trace, attempt fix if dumb typo, else log crash and revert.
8. Record results in results.tsv (append)
9. If val_bpb improved lower → advance branch (keep commit), also update graphify_source markdown with result note and create follow-up BB task: `[AVA-EXP-KEEP] ...`
10. If val_bpb worse or equal → git reset --hard HEAD~1 (back to start) OR keep as discard but revert file, log discard.
11. If you feel stuck (no ideas), read more:
   - `pgraphify query "what improves S1 Fast hl=8" --graph graphify-out-research/graph.json`
   - `pgraphify path "multi_jspace_module.py" "Muon" --graph graph.json`
   - Re-read in-scope files, combine previous near-misses, try radical architectural changes (delete code!)

**Timeout**: Each experiment ~5 minutes total (+ overhead). If exceeds 10 min, kill and treat as failure.

**Crashes**: If OOM or bug and easy fix (typo, missing import), fix and re-run. If fundamental, log crash and move on.

**NEVER STOP**: Once loop begun after setup, do NOT pause to ask human if should continue. Do NOT ask "should I keep going?" The human might be asleep, expects you to continue indefinitely until manually stopped. You are autonomous. If out of ideas, think harder — read papers referenced in code, re-read in-scope files for new angles, try combining near-misses, try radical changes. Loop runs until human interrupts, period. Example: user leaves you running while they sleep → ~12/hour, ~100 overnight → wakes to experimental results.

## Integration with BigBang cron system

- Cron `arxiv-harvest-daily` (06:00 UTC) populates new papers
- Cron `research-graphify-build` (07:00 UTC + interval 4h) rebuilds graphify knowledge base (727 nodes baseline → now + research nodes)
- Cron `research-task-synth-daily` (08:00 UTC) creates [AVA-RESEARCH] tasks in Google Tasks (Lina's Morning / Ava Research list) from latest papers
- Cron `autoresearch-loop` (hourly or interval 1h) picks top task and runs this loop for one iteration (or starts loop if not running)
- Cron `research-wiki-weekly` (Sun 10:00 UTC) summarizes results.tsv + graph into LLM wikis + briefs

## Branch naming + results handling

- Branch: `autoresearch/<date>-<topic>-<arxiv_short>` e.g. `autoresearch/jul15-muon-s1-2404`
- Experiment dir: `experiments/<arxiv_id>/` with `experiment.md`, `run.log`, `diff.patch`
- results.tsv entry must include arxiv_id for traceability
- On keep: merge branch to main? No, keep separate until human reviews — only advance autoresearch branch, don't auto-merge to master.

## Failure handling + truthfulness

- Do NOT invent player data (Vector), do NOT fake evals or balances (Davis Family Brain), do NOT fake graph nodes.
- Dashboards must match actual model architecture — generic J-Space charts on MTNN sites triggered July 11 correction, keep per-domain truthful.
- For finance, include joint + Fidelity or net worth off by $1M — not relevant here but keep discipline.
- Every business artifact footer: "Solo personal project, no connection to employer, built with public/free-tier only"
- Zero Vercel/Bluehen references in HOME artifacts.

---
This program.md is living — you can edit it to improve the org code as you learn what makes research fastest, like Karpathy says: find the research org code that achieves fastest research progress. Try adding more agents (parallel thunks), better prompting, better tool use, etc.

Solo personal project, no connection to employer, built with public/free-tier only.
Home-life only.
