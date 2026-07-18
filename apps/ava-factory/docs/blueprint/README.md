# docs/blueprint/ — unwired blueprint scaffolding & mock outputs

Solo personal project, no connection to employer, built with public/free-tier only.

Everything in this directory is **blueprint material**: aspirational sketches
and mock outputs from the design phase. Nothing here is imported by the real
`ava/` stack, nothing here is covered by tests, and **no number in these files
is a measurement**.

## Mock eval reports (moved from repo root)

- `BRANCH_EVAL_REPORT.md`, `FRONTIER_EVAL_REPORT.md` — **MOCK BLUEPRINT
  OUTPUT, not measurements** (each carries an explicit header). Real,
  checkpoint-derived evals: `python -m evals.run_harness` →
  `reports/branch_eval_results_real.json` + `reports/REPORT_REAL.md`.
- The matching `branch_eval_results.json` / `frontier_eval_results.json` stay
  at the repo root because external tooling (e.g. `scripts/dataset_discovery.py`,
  scout-cli's arxiviq `generate_data.py`) reads them from there; both carry a
  top-level `"disclaimer": "MOCK BLUEPRINT OUTPUT ..."` field.

## Unwired blueprint scripts (moved from repo root; zero inbound code references)

- `branch_anneal.py` — branch anneal sketch
- `trainer_agent.py`, `data_builder_agent.py` — the CURRICULUM_LOOP_PLAN.md
  producer/consumer agent sketches (never wired; the real loop is
  `ava/pipeline/` + `python -m ava.train`)
- `j_space_eval.py`, `j_space_eval_expanded.py` — early J-Space eval sketches
  (superseded by `evals/jspace_tests.py` and `evals/run_harness.py`)
- `wandb_dashboard.py` — W&B dashboard sketch (real report:
  `scripts/make_report.py`)
- `network_init_sota.py` — init-scheme notes (referenced descriptively by
  `model_1b.py` comments and TODOS.md)

Kept at root on purpose (still referenced by real code): `j_space_module.py`
(imported by `model_1b.py`'s legacy branch), `multi_jspace_module.py`,
`model_1b.py`, `train_1b_deepspeed.py` (blueprint trainer, labeled).
