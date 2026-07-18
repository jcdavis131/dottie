# autoresearch — Authentic Writing track

> Goal: evolve bb write plugin — detector weights + fixes — to stay HUMAN_LIKE 0 and detect new slop.

## Context

- Goal: `build-authentic-feeling-content-generators-that-auto-scan-for-ai-slop`
- Current write plugin: `workspace/bigbang-cli/bigbang/plugins/write/cli.py`
- Research sources: ai-slop-detect 70+ patterns, slop-radar 245 buzzwords, slop-cop 36 rules, CMU PNAS 2025 participial 2-5x overuse, tapestry 150x, arXiv 2509.19163
- Current weights: participial 0.5, char 0.8, phrase 3.0 + soft <50w hits*6+0.9w
- Current fix: word-boundary phrase map, em-dash strip, participial comma strip `",\s+([a-z]+ing)" → " \1"` via re.sub — gets test sentence BEFORE STRONG_AI 100 → AFTER HUMAN_LIKE 0
- Problem: new LLMs produce new slop, detector needs autonomous hill-climb

## Setup

1. Tag: `write-jul15`
2. Branch: `autoresearch/write-<date>`
3. Read write cli.py if accessible (C:\Users\jcdav\workspace\bigbang-cli\bigbang\plugins\write\cli.py)
4. Verify data
5. Init results.tsv

## Experimentation — Write detector evolution via TinyStories proxy

You still edit only `train.py` but interpret as write detector training proxy:

**Mapping:**
- TinyStories next-token val_bpb proxy = ability to distinguish human vs AI slop? Lower bpb = better language model that still can detect over-polished text?
- Alternative proxy: train small classifier inside train.py that classifies text as HUMAN vs AI slop, using TinyStories as human baseline + synthetic slop injection
- Simplest: keep val_bpb but add second metric you log: scan test cases via your detector logic ported into train.py evaluate function

**Test cases you MUST evaluate each run (from write plugin tests):**
```
STRONG_AI case: "In today's digital landscape, it's important to note that our cutting-edge solution harnesses the power of AI — crafting a rich tapestry of innovation, leveraging holistic synergy."
Expected BEFORE: STRONG_AI score >=70, hits >=8
Expected AFTER fix: HUMAN_LIKE 0

HUMAN_LIKE case: "Hello world this is a simple note from Austin."
Expected: HUMAN_LIKE or TRACES, score <15

Generate fallback: "Trade Crew Turnover Shield launch email I kept seeing AI tells in our drafts. Words like mix and look at. For example crew turnover dropped 12 percent after text check-ins."
Expected: HUMAN_LIKE
```

**Ideas to test:**
1. Weight tuning: participial 0.3-0.8, char 0.6-1.0, phrase 2.5-4.0, short-text multiplier 5-8
2. Fix improvements: better word-boundary (`\b crafting \b`), handle "moreover/furthermore" leading connectors strip
3. New pattern lists: add emergent slop from 2026 LLMs (check ai-slop-detect repo updates)
4. Generate template: evolve fallback template to be more story-specific, include real numbers (12 percent, Austin), avoid buzzwords
5. Batch vs single: test detector speed — must be <0.8s like _ollama_base_fast
6. Triple encoding: like your Sunni SCAD design — shape+icon+text+pattern for slop viz

**Metric:** You still log val_bpb, but ALSO log custom write score in description: e.g. `write_scan 100→0, HUMAN_LIKE, fixes 10`

**Log to:** `results.tsv` + `bb-offload/results/write.jsonl`:
```
{"commit":"a1b2c3d","val_bpb":0.997,"write_before":100,"write_after":0,"verdict":"HUMAN_LIKE","fixes":10}
```

**Hardware:** RTX 4080/4090, but inference must stay CPU-fast (no GPU needed for detector). So reward small, fast models.

## Loop

Autonomous: edit train.py to include write detector proxy eval, commit, run, grep val_bpb + custom write metrics, keep if:
- val_bpb improved OR
- val_bpb same but write detector more accurate (BEFORE still STRONG_AI, AFTER still 0) + code simpler

## Never stop — hill-climb detector weights vs new slop.

Human wakes up to better `scan_text` weights to port back into `bigbang/plugins/write/cli.py`.
