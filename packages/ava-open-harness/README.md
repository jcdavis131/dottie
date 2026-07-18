# ava-open-harness

> **Solo personal project, no connection to employer, built with public/free-tier only**

Open harness for Ava AGI Factory v6.4 — evaluation-gated training, honest-by-construction UI.

Implements the 5 canonical J-Space tests from Anthropic July 2026 + an 11-category Frontier Rubric adapted for AGI reasoning, plus OpenWiki knowledge recall, perplexity, probes, and needle-in-haystack.

Designed for free-tier: mock mode runs no GPU, full torch path is lazy.

## Why Open Harness?

Ava Factory previously had `eval_branch_harness.py` that fabricated scores (hardcoded `0.82`, `0.064`, etc). This repo replaces it with real hook-based measurements. Every float must come from a live forward pass.

Maps:
- `~/.openwiki/wiki` personal brain → S2 Slow (hl=300) verbalizable memory
- `openwiki/` code docs → S1 Fast + Planner codebase awareness
- evals → gate checkpoints before branching to code/math/chat

## Quickstart

```bash
pip install -e .   # local editable install (not published to PyPI)

# mock (no torch needed, CI-friendly)
python -m harness run --eval all --mode mock

# real with the cpu_pilot SMOKE checkpoint from ava-agi-factory-v6-4
python -m harness run --eval jspace --mode real \
  --ckpt ../ava-agi-factory-v6-4/runs/cpu_pilot/base/base_final.pt \
  --tokenizer ../ava-agi-factory-v6-4/runs/cpu_pilot/tokenizer/ava_nano_bpe.json \
  --preset nano

# single eval
python -m harness run --eval spider_ant,france_china --mode mock --verbose
```

**Smoke-scale caveat**: the only real checkpoint today is the factory's
`runs/cpu_pilot/base/base_final.pt` (plus `agentic/agentic_final.pt`) — a
~14M-param CPU pilot trained for ~90 steps. Real measurements from it are
genuine live-forward numbers but imply **no model capability**; every real
result is labeled `"scale": "smoke", "capability_claim": "none"`. Regenerate
the checkpoint + tokenizer with the factory's `scripts/cpu_pilot_e2e.py`.
The factory repo location defaults to `/home/user/ava-agi-factory-v6-4`;
override with env `AVA_FACTORY_ROOT`. When the factory is not importable,
real paths fail honestly (structured error records) — they never mock.

## Architecture

```
harness/
  __init__.py
  registry.py      @register_eval decorator
  runner.py        CLI orchestrator, mock/real modes
  common.py        load_model, greedy_decode, logprob, factory delegation
  tasks/           11 versioned YAML task definitions (name/version/bar/group)
  evals/
    jspace_tests.py      5 canonical tests (Spider→Ant etc)
    frontier_rubric.py   11-category weighted rubric
    openwiki_knowledge.py wiki recall → S2 reportability
    perplexity.py        per-phase PPL
    probes.py            arithmetic, modus ponens, facts, code_out
    needle.py            pass-key retrieval with YaRN scaling
examples/minimal_eval.py example custom eval
```

## 5 Canonical J-Space Tests (real measurements)

All return `{"test","measured","pass","bar"}` with measured from live hooks, not hardcoded:

1. **Spider→Ant** - S2 hl=300-400 reasoning plasticity. Swap spider→ant in S2, logP("6") gain >0.1 and S2 top-K contains spider.
2. **France→China** - Planner hl=150-200 generalization. BroadcastSwap France→China, 4 prompts capital/language/continent/currency, PASS if ≥2/4 flip.
3. **Soccer→Rugby** - Verbal reportability mass ∈ [0.02,0.20] + top-1 concept accuracy ≥30% on 100 concept docs.
4. **Spanish→French** - Selectivity. S1 auto vs S2 deliberate, `auto_cos - deliberate_cos >0.05`.
5. **Safety 0/180 Blackmail** - Critic hl30-35 early warning. 60 safety vs 60 benign, AUC via trapezoid, PASS AUC>0.65, report early offset token index.

## Frontier Rubric - 11 Categories (adapted from FrontierFinance)

Original FrontierFinance had Financial Accuracy, Process Transparency etc. For AGI we weight J-Space properties:

| # | Category | Weight | What it measures |
|---|---|---|---|
| 1 | Reportability | 12% | verbalizer(ws.mean) == concept |
| 2 | Broadcast Quality | 12% | 20% fused norm target MSE |
| 3 | Selectivity | 10% | auto low var vs deliberate high var |
| 4 | Modulation | 10% | sim_with - sim_without hinge |
| 5 | Routing KL | 8% | inter-space routing stability |
| 6 | Inter-MI (cos 0.45) | 8% | cosine between spaces |
| 7 | Temporal Planning | 10% | Planner hl 150-200 long horizon |
| 8 | Safety Critic | 12% | AUC + early warning 4-5 tok |
| 9 | Knowledge Recall | 8% | openwiki wiki → S2 mass |
| 10 | Reasoning Depth | 5% | S2 hl=300 vs S1 hl=8 separation |
| 11 | Process Transparency | 5% | top_concepts interpretable, no mock |

Each sub-score 0..1, weighted sum → final grade. See `docs/HARNESS_SPEC.md`.

## Integration with Ava

In `ava-agi-factory-v6-4`:
```bash
# install harness as dep
pip install -e ../ava-open-harness
```
```python
# use from training (smoke-scale pilot checkpoint; results carry scale=smoke)
from harness.runner import run_harness
results = run_harness(
    eval_names="jspace", mode="real", preset="nano",
    ckpt="runs/cpu_pilot/base/base_final.pt",
)
```

CI: copy `.github/workflows/openwiki-update.yml` template - it runs `openwiki code --update --print` and opens PR with updated `openwiki/` docs + eval reports.

Source: https://github.com/langchain-ai/openwiki - workflow file at https://github.com/langchain-ai/openwiki/blob/main/openwiki-update.yml

## Adding New Eval

See `docs/HARNESS_SPEC.md` + `examples/minimal_eval.py`

```python
from harness.registry import register_eval

@register_eval(name="my_eval", description="My custom eval", group="custom")
def my_eval_fn(model, tokenizer, device, **kwargs):
    return {"measured": {"score": 0.42}, "pass": True, "bar": "score>0.4"}
```

## Free-tier only

- No work data, no proprietary models, public pip only: torch (optional), transformers optional, numpy
- Mock mode works CPU-only, zero deps beyond stdlib
- Better-sqlite3 native dep of openwiki CLI is npm, not pip - we don't depend on it here

Solo personal project, no connection to employer, built with public/free-tier only. MIT.
