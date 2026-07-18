# Ecosystem audit — architectural stubs & doc–code mismatches (2026-07-17)

**Solo personal project, no connection to employer, built with public/free-tier only**

> Full-ecosystem sweep (6 repos) for concepts conceptualized but not operationalized:
> TODO markers, placeholder bodies, fabricated "real" measurements, and dangling doc
> references. Items marked ✅ were fixed in this pass; ⬜ are filed with implementation
> notes. Deliberately-gated factory items (TODOS.md stages, spec 12 RL blocks) are NOT
> defects and are listed at the end for completeness.

## Headline finding

The factory repo's *internal* `evals/` tree is genuinely real (hook-based, anti-mock
tested, 200+ passing tests) — but the fabrication antipattern its PLAN.md documents
eliminating had migrated outward into the two open companion repos: **every real-mode
path in ava-open-harness and several in ava-skills returned invented constants labeled
as live measurements.** The fix policy applied: a real path that isn't wired **fails
loudly with an explanation**; it never invents a float. Full real-mode implementations
remain filed (below) because they need the factory checkpoint on a GPU box to verify.

## Fixed in this pass ✅

### ava-open-harness
- ✅ `python -m harness run` **had never worked** — `__main__.py` imported `main` without
  calling it (exit 0 no-op), and `main()` rejected the documented `run` subcommand. Fixed;
  verified live (11 evals run in mock mode). The CI workflow's harness gate was silently
  `echo skip`-ing forever; it now actually runs.
- ✅ `perplexity.py`/`probes.py`/`needle.py` were **byte-identical triplicates**, each
  registering all three evals → duplicate-registration errors printed on every import.
  Split to one eval per file; error noise gone (verified: 0 occurrences).
- ✅ **Fabricated real-mode paths** in `jspace_tests.py` (all 5 canonical tests — random
  "swap effects", hardcoded 0.86/0.71 cosines, seed-0 scenario scores, `top_contains_spider:
  True`), `frontier_rubric.py` (flat 0.75s), `openwiki_knowledge.py` (constant 0.08),
  and the perplexity/probes/needle trio (formula constants) → all now return an honest
  `real mode not implemented: <what's needed>` failure via new `common.real_unimplemented()`.
- ✅ `common.logprob_of` silently returned **-2.5** on any exception → now raises.
- ✅ **`--mode real` silently downgraded to MockModel** when torch/ckpt was missing, so a
  "real" report contained mock numbers. `run_harness` now raises RuntimeError in that case.

### ava-skills
- ✅ `code-bench` real mode returned hardcoded `{pass_rate: 0.8}, pass: True` → honest failure
  pointing at the existing `exec_verify()` loop to reuse with model generations.
- ✅ `openwiki-sync` real mode returned constant mass `0.072` → now computes a concept-density
  proxy from the actually-scanned wiki, labeled `mass_basis: density proxy`.
- ✅ `family-brain-wiki` passed `mode` through, so mode="real" returned `0.06+uniform(0,0.08)`
  labeled real → real mode now fails honestly; simulation is labeled mock.
- ✅ `memory-router` placed the paper target `f1_improvement: 6.87` inside `measured` →
  renamed `target_f1_improvement` with a not-a-measurement comment.
- ✅ README "8 Starter Skills" → 9 (memory-mint added, the only skill with tests).

### scout-cli
- ✅ `core/discovery.py:discover_mcp_tools()` returned a hardcoded fake tool (an agent
  planning against it would believe a capability that doesn't exist) → now delegates to
  the real `mcp_client.list_mcp_tools_sync`, returns `[]` on failure.
- ✅ README "14 tests passing" → 35 (18 CLI + 17 RFT ETL); `docs/SECURITY.md` corrected:
  network enforcement IS wired; fs/secret enforcement is engine-supported but never invoked.

### personal-graphify
- ✅ `analyze.token_stats()` and `query.py` token economics were **placeholder formulas**
  (`nodes*50`, constant 1500) rendered in reports as "×reduction (mirrors upstream 71.5×)"
  → now **measured**: naive = real bytes of indexed files /4; scoped = serialized size of
  the payload actually returned; output carries a `basis` field, and the report template
  prints that basis instead of the upstream-mirror claim.

## Filed — larger items with implementation notes ⬜

| Item | Where | Note |
|---|---|---|
| ⬜ Real J-test interventions | ava-open-harness `jspace_tests.py` | Wire `WorkspaceSwap`/`BroadcastSwap` from `ava-agi-factory-v6-4/evals/interventions.py` (the import path `ava.agi_factory` never existed); CPU nano ckpt suffices for shape-correct wiring; verify vs factory `evals/run_harness.py` outputs |
| ⬜ safety-scanner real ONNX inference | ava-skills `safety-scanner/skill.py:184` | Loaded ONNX session exists but `_guard3_mock_score` is still called and labeled `llama-guard-3-1b-onnx`; hardcoded f1/auprc/fpr at `:109`; mock AUC ignores its own scored scenarios (`:149`). No GPU needed, model download required |
| ⬜ fs/secret policy enforcement | scout-cli `core/policy.py:39-45` | Engine supports both actions; zero call sites. Add `enforce_or_raise("fs_write"/"secret", …)` in write-capable plugins (tasks, rft, graphify, rtx) — highest security value in the repo |
| ⬜ `bb agent run` executor | scout-cli `plugins/agent/cli.py:356-411` | Plans but never executes ("Would run plan…"); `bus`/`teach` are static emits. Executor = loop over plan steps → policy check → subprocess → audit; README oversells until then |
| ⬜ `bb ava train/eval` execution | scout-cli `plugins/ava/cli.py:506-527` | Emits the docker command string without running it; either subprocess+confirm or relabel "print instructions" |
| ⬜ family/vector/tennis plugins | scout-cli | Informational stubs presented as functional in README; wire or mark as bookmarks |
| ⬜ vLLM backend | ava-open-harness `runner.py:161-164` | `--backend vllm` only writes `wall_s * 0.89` as "theoretical"; report text claims batched generate. Implement or drop the claim |
| ⬜ `harness/tasks/*.yaml` | ava-open-harness | Directory referenced by loader + report text, doesn't exist; ship YAMLs or drop |
| ⬜ Per-skill tests | ava-skills | 8 of 9 skills have no tests/ (spec section "Testing" points at a nonexistent path); memory-mint's suite is the template |
| ⬜ scout-rtx `bigbang-bridge/cli.py` | scout-rtx | `sync` never writes the MRR_FILE it documents; file duplicates an older scout-cli rtx plugin — deduplicate or delete |
| ⬜ Factory orphaned speculative modules | ava-agi-factory `ava/attention/*, ava/embeddings/per_layer.py, ava/decoding/diffusion_gemma.py, ava/audio/, ava/mobile/` | Untested, never imported, contradict TODOS "do not build speculatively"; delete or quarantine to `experimental/` |
| ⬜ Factory dangling docs | `docs/OPENWIKI_INTEGRATION.md` (3 missing files), `specs/11:51,102,108` (stale `ava/j_space_module.py`, stub `eval_harness.py` gate), `docs/LOCAL_MAX_SETUP.md:416`, root `BRANCH_EVAL_REPORT.md` (mock PASS table with no mock label) | Doc-only fixes; root report needs a MOCK banner or deletion |

## Gated by design (tracked, no action)

Factory blueprint-era root files (PLAN.md:13-27 table), `sft_sota_2025.py` (T9.3/T9.5),
absent RL code (spec 12 contract, T12R.1 GPU-free may start anytime), Stage 10 pacer/
compactor, spec 08/09 future deliverables, T11.2 GPU measurement deferred behind the live
mini run, harness/skills mock mode itself (a feature, honestly labeled), scout-cli heuristic
router (self-labeled "stub", Ollama path preferred).

## Method

Ecosystem-wide grep sweep (TODO/FIXME/NotImplemented/placeholder/hardcoded-literal
patterns) + doc-claim cross-check (every "X exists/works" README claim executed or
traced to code) + live execution of entrypoints (`python -m harness run` verified
broken, then verified fixed). Classification rule: an item is a defect only if it is
(a) untracked and (b) presents invented data as measured or promises capability that
silently no-ops; tracked gates are design.
