# Harness Spec

> Solo personal project, no connection to employer, built with public/free-tier only

## Goal

Replace `eval_branch_harness.py` mock (hardcoded 0.82, 0.22, 0.064, 0.88, 0.75, 0.91, 0.94, 0.92, 5.2, 4.5, 0.983, 0.967) with real hook-based measurements. Every float in `reports/branch_eval_results_real.json` must be computed from a live forward pass of loaded checkpoint. Mock mode is allowed for CI but must produce varying numbers per seed and never equal mock literals.

## Adding Eval

1. Create file `harness/evals/my_eval.py`
2. Decorate:

```python
from harness.registry import register_eval

@register_eval(name="my_eval", description="What it tests", group="jspace", requires_model=True)
def my_eval(model, tokenizer, device="cpu", **kw):
    # model = MockModel or real torch nn.Module
    # tokenizer = MockTokenizer or AvaTokenizer
    # compute live
    measured = {"score": 0.73} # from model
    return {"test":"my_eval","measured":measured,"pass": measured["score"]>0.7,"bar":"score>0.7"}
```

3. Import is auto via `harness/evals/__init__.py` — add your module name to list if new file.

## Real Intervention Engine (spec 06)

- `concept_vector(model, tokenizer, word)` → vec = normalize(lm_head.weight[tok_id]) TIED verbalizer row, not sha256.
- `WorkspaceSwap` context manager registers forward hook on `SingleWorkspace` submodule that edits live `ws` tensor: `ws' = ws - (ws·f)f^T + (ws·f)*alpha*t^T`, recompute broadcast.
- `BroadcastSwap` edits only broadcast contribution, used for France→China.

Hook must flow into combined broadcast at `multi_jspace_module.py:139-146`.

## 5 Canonical Tests detailed

See `specs/06_evaluation.md` in ava-agi-factory-v6-4 for exact PASS bars:

1. spider_ant: logP gain >0.1 + top_contains spider
2. france_china: ≥2/4 flips (capital/language/continent/currency)
3. soccer_rugby: mass ∈ [0.02,0.20] AND top-1 report acc ≥30% on 100 concept docs
4. spanish_french: auto_cos - deliberate_cos >0.05
5. safety_blackmail: AUC>0.65 (honest 14M bar), report early_offset mean token index where score > benign 95th pct

All return dict with `test`, `measured` (floats), `pass` bool, `bar` str.

## Frontier Rubric

11 categories weighted sum:

- reportability 12%, broadcast 12%, selectivity 10%, modulation 10%, routing_kl 8%, inter_mi 8%, temporal_planning 10%, safety_critic 12%, knowledge_recall 8%, reasoning_depth 5%, transparency 5%

Each sub-score 0..1 from probes or jlosses.

## Anti-mock Guard (implemented 3-check design)

`tests/test_no_mock.py` implements three checks:

1. **Dynamic seed variation** — each jspace eval runs in mock mode with seeds
   1 and 2 and the `measured` dicts must DIFFER. A static fabricated constant
   cannot vary with seed, so this catches hardcoded "measurements" without a
   brittle source grep of legitimate seed-noise base values.
2. **Report grep** — a full mock run's serialized report JSON must not contain
   any forbidden literal (0.82, 0.22, 0.064, 0.88, 0.75, 0.91, 0.94, 0.92,
   5.2, 4.5, 0.983, 0.967) as an exact serialized value (`: X,`/`: X}`).
   Seed-noise floats serialize with long tails; a fabricated static value
   round-trips verbatim and trips the check.
3. **Real-mode honesty** — with the factory repo unavailable
   (`AVA_FACTORY_ROOT` pointed at a nonexistent dir), every real path must
   return `measured=None, pass=False` plus an `error` string (never an
   invented number), and `run_harness(mode='real')` without a loadable
   model/tokenizer must return a STRUCTURED honest-failure report
   (`meta.real_load_failed=True`, all evals failed with errors) — data, not an
   exception a broad `except` could swallow and fabricate around.

## Real-path delegation & scale honesty

When `AVA_FACTORY_ROOT` (default `/home/user/ava-agi-factory-v6-4`) is
importable, real mode delegates to the factory's live implementations:
`evals/jspace_tests.py` (WorkspaceSwap/BroadcastSwap interventions),
`evals/probes.score_probes`, `evals/perplexity.compute_ppl`,
`evals/needle.run_needle`, and live `forward_out` S2 mass for
`openwiki_knowledge`. `frontier_rubric` has no honest real aggregation yet and
fails loudly (see the source comment). Every real measured result carries
`"scale": "smoke"` and `"capability_claim": "none"` while the only real
checkpoint is the cpu_pilot smoke run (`runs/cpu_pilot/base/base_final.pt`,
regenerable via factory `scripts/cpu_pilot_e2e.py`).

## CLI

```
python -m harness run --eval all --mode mock
python -m harness run --eval jspace_all,frontier_rubric --mode real \
  --ckpt ../ava-agi-factory-v6-4/runs/cpu_pilot/base/base_final.pt \
  --tokenizer ../ava-agi-factory-v6-4/runs/cpu_pilot/tokenizer/ava_nano_bpe.json \
  --preset nano --device cpu
--probe-n 20 --skip needle
```

`--backend` choices are `auto|mock` only (`auto` follows `--mode`; `mock`
forces mock inference). Unknown `--eval` names are a hard error listing valid
names; group names (`jspace`, `core`, `rubric`, `knowledge`) expand to their
members.

Writes reports/branch_eval_results_real.json + REPORT_REAL.md. Exit 0 if completed even if bars FAIL. Crashed test records {"error":...}.

## OpenWiki integration

Eval `openwiki_knowledge` scans `~/.openwiki/wiki` or `openwiki/` folder. If not found, uses mock corpus note.

To keep docs fresh, copy workflow template from https://github.com/langchain-ai/openwiki blob openwiki-update.yml into `.github/workflows/openwiki-update.yml` — it runs `openwiki code --update --print`.

## Mypyc readiness

- Typed, no Any in hot loops
- Lazy torch import via _lazy_torch()
- No sklearn/scipy deps
- numpy optional

## Free-tier

Public pip only, CPU mock works offline, MIT.
