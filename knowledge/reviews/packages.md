# Packages review

## Findings
- 🟡 packages/ava-open-harness/tests/test_no_mock.py:30 — Anti-mock guard has a mutation-verified blind spot: a fabricated per-field static constant with a value outside the FORBIDDEN list (e.g. 0.77) passes all 14 guard tests, because the dynamic check compares whole measured dicts and the grep only checks enumerated literals.
- 🟡 packages/ava-open-harness/harness/common.py:53 — Reverse packages→apps runtime coupling: harness probes ../../../apps/ava-factory (and harness/evals/dottie_assistant.py:35 probes apps/dottie) and sys.path-injects the factory root, exposing a generic top-level `evals` module name that can shadow/collide; guarded and honest-failing, but the package is not standalone in real mode.
- 🟡 packages/personal-graphify/src/personal_graphify/extract.py:266 — Nine bare `except:` clauses across src/ swallow all exceptions (including KeyboardInterrupt), silently dropping extraction failures into incomplete graphs.
- 🟢 packages/personal-graphify/pyproject.toml:9 — Comment claims python-frontmatter is a hard import, but extract.py:258 imports it inside try/except with fallback — the dep is actually optional; comment/tier is stale (harmless over-declaration).
- 🟢 packages/personal-graphify/graphify-out/graph.json:1 — 1.2M of generated graph artifacts committed inside the package tree; deliberate per .gitignore:1 ("commit for team") and excluded from the wheel (src layout), but it bloats the repo and can go stale silently.
- 🟢 packages/ava-open-harness/tests/test_no_mock.py:92 — Positive baseline: all three packages smoke-import cleanly (harness, skills, personal_graphify + all submodules), all script entry points resolve, suites are real (36+80+64 passed, no placeholder asserts), and the cross-package test dep on skills.state_store is safely optional via importorskip.

## Risk
- The anti-mock guard is the repo's core invariant; the per-field blind spot means a fabricated number with a novel value could reach reports/telemetry undetected — exactly what the guard exists to prevent.
- sys.path injection of the factory root can shadow any other `evals` package in-process, and harness real mode silently depends on monorepo layout — breaks quietly in a standalone checkout.
- Bare excepts in personal-graphify produce silently incomplete knowledge graphs with no error trail.

## Recommendation
1. Strengthen test_no_mock.py: assert every numeric leaf of each measured dict varies across seeds (per-field check), not just whole-dict inequality plus enumerated literals.
2. Isolate factory/dottie delegation (subprocess or importlib with a private module namespace) to remove the top-level `evals` collision; keep the honest-fail records.
3. Replace bare `except:` with `except Exception` plus a logged warning in personal_graphify src/, and fix the pyproject core-dep comment (frontmatter is optional).

## Evidence
Mutation test (scratchpad copy of ava-open-harness, guard run via repo venv):
- Inject `logp_base_8 = 0.82` (in FORBIDDEN) → caught:
  `FAILED tests/test_no_mock.py::TestReportGrep::test_mock_report_has_no_exact_forbidden_literals`
  `AssertionError: forbidden literal 0.82 appears verbatim in mock report`
- Inject `logp_base_8 = 0.77` (not in FORBIDDEN) → NOT caught:
  `14 passed in 0.07s`
Baseline suites: ava-open-harness `36 passed, 4 skipped` (skips = torch/checkpoint absent, honest);
ava-skills full testpaths `80 passed`; personal-graphify `64 passed`.
Smoke-import all three packages: `imports ok`.
