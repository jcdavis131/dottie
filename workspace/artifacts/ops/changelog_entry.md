---
generated_by: scripts/business/generators/changelog.py
generated_at: "2026-08-10T02:28:02+00:00"
classification: REAL
method: "Commit subject lines listed verbatim from read-only git history between the merge base and HEAD; subjects matching the naming policy are withheld."
measured: true
sources:
  - ref: "merge-base main..HEAD"
    sha: "6d7391f4c4934a5842fe6670dbd2ddef906a56fb"
  - ref: "HEAD"
    sha: "cc01c6cddcadb1acf05c2c59ac1871454da5c464"
---

# Change log

- cc01c6c (2026-08-09) feat(factory): P2 flywheel bridge — one fail-closed command from runs to dashboard
- bbd70b5 (2026-08-09) feat(factory): P2 flywheel bridge — one deterministic nightly cycle, fail-closed
- 96f1ade (2026-08-09) feat(mcp): first external MCP downstream live — DeepWiki; two transport bugs found and fixed
- f6c890f (2026-08-09) fix(harness): consolidate store paths into call-time helpers — GOAT regression cleared
- 82c1892 (2026-08-09) feat: operator corrections queue — harness correct command + dashboard review panel
- 95698e5 (2026-08-09) chore(api): weights URL default now points at main — post-merge follow-up for PR #11
- 812af3a (2026-08-09) (subject withheld: naming policy)
- 66886a7 (2026-08-09) fix(policy): track contacts in the ungated-write set — acne go-live follow-through
- 329ed04 (2026-08-09) feat(contacts): the acne integration goes live — honest manifest, tests, people-memory in the loop
- 69a8f9b (2026-08-09) docs: README as the platform front page; ECOSYSTEM.md metrics refreshed to current cycle
- dbece01 (2026-08-09) docs: HANDOFF refresh — flywheel closed, one full cycle run, gate now winnable
- c8db8ed (2026-08-09) chore(data): first flywheel cycle — live MCP runs, outcome labels in corpus, retrained ladder
- ede8c29 (2026-08-09) fix(harness): honor MCP in-band isError — a successful round-trip can still be a failed call
- b59c510 (2026-08-09) feat(dashboard): derived Label-sources panel + by_label_tier on /api/health
- 9922c02 (2026-08-09) feat(factory): outcome-adjusted labels + operator corrections — P1 label-ceiling breakers
- 397ad0e (2026-08-09) feat(harness): MCP action executor — mcp: goals route to action_operator with measured provenance
- bbca936 (2026-08-09) docs: ECOSYSTEM.md — the closed loop, repo roles, and the label-ceiling unlock
- 9b34eb7 (2026-08-09) feat(scout-cli): meta-MCP aggregation — namespaces, tool filtering, unified proxy serve
- c151ab2 (2026-08-09) fix(ci): drive the full pipeline green — gate judgments, honest manifests, path guard, refreshed ledgers
- ff15efb (2026-08-09) chore(api): sync vendored champion weights with the full-budget run
- 1ae3362 (2026-08-09) fix(dashboard): derive gate panel and counts from the eval report, never hardcode
- 2371c91 (2026-08-09) feat(training): full-budget champion on measured corpus + platform improvement plan
- 91c6d3a (2026-08-09) feat(training): measured harness traces feed the router corpus — 704 measured records
- 84d518d (2026-08-09) fix(api): use tempfile.gettempdir() for the weights cache path
- b75559d (2026-08-09) feat(api): validation-lab dashboard + host-routed static surface + committed-weights URL fallback
- f4ef74e (2026-08-09) fix(factory): skip corpus tests when scout-cli harness deps absent
- 7a56281 (2026-08-09) feat(api): self-contained hostable harness surface (stdlib + numpy only)
- a368af1 (2026-08-09) feat(factory): orchestration corpus + engram-featurized router model + hill-climb champion
- 71eab10 (2026-08-09) feat(harness): end-to-end run loop + learned routing
- 0839b26 (2026-08-09) feat(business): playbooks-as-config execution layer — 4 ventures, provenance-honest generators, executed artifacts
- dcd8575 (2026-08-09) docs(consolidation): dottie primary monorepo doctrine, bhenre surface retired, salvage staged
- c770fc6 (2026-08-09) docs(curriculum): measured sizing of self-labeling training material in the monorepo
- b153d4a (2026-08-09) fix(factory): distill model-load bug + gated multi-tier distillation ladder
- a64e9d8 (2026-08-09) feat(memory): coarse-to-fine shard retrieval — lazy per-scope inverted index in mint, scope passthrough in router
- a5e84fb (2026-08-09) feat(harness): streaming timeline store — offset-indexed G_history stats feed graph-plan failure risk
- 9ef2762 (2026-08-09) docs(spec): LongCat 2.0 adoption spec — map sparse-attention/engram/muP/MOPD insights onto Dottie
