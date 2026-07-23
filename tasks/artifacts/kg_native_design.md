# KG-native: a knowledge-graph layer over Dottie's own substrate

2026-07-23. Stdlib-only (sqlite3/json/re/argparse), zero new dependencies, zero
network, zero docker. Package: `apps/dottie/dottie/kg/` (new files only; the
contested research files were not touched — validate.py changes appear below
strictly as a patch PROPOSAL).

---

## 1. Sources distilled

### graphify.com — codebase → knowledge graph for AI assistants
What it is: an open-source (MIT) CLI (`uv tool install graphifyy`) that maps a
repository into a knowledge graph so assistants answer via graph traversal
instead of embeddings; "answers are explicit graph paths with real file:line
citations"; "runs on-device: no account, no API keys, no telemetry".

**Adopted**
1. *Citations as a schema invariant* — every node/edge in our store carries
   `source` + `source_ref` (`CURSOR_HANDOFF.md:L7`, `ledger:experiments:<id>`,
   `dottie_live_status.json:pipeline.trainer.series[141]`). Query output prints
   the citation next to every hop. This is also the org's confirm-why doctrine
   expressed as a data model.
2. *Graph traversal over embeddings* — no vectors, no model loads; queries are
   typed-edge walks (`preceded_by` chains, `struggled_with` aggregation) in
   sqlite. Computationally near-free.
3. *On-device, no accounts* — the graph is a local gitignored sqlite file
   built from local files only.

**Rejected**
- The `graphifyy` package itself: pip install is out (stdlib-only guardrail),
  and its LLM-extraction path needs API keys/SaaS models. We keep the shape of
  the idea, not the dependency. (Note: the repo already has its own
  `personal_graphify` fork elsewhere; this task's package is independent.)
- Code-structure graphing (functions/imports): our highest-value graph-worthy
  data is *operational* (incidents/experiments/telemetry), not code topology.

### rootly.com blog — "Turning your incident data into a knowledge graph"
What it is: Rootly (incident-management SaaS) showing Graphify pointed at
incident data: an LLM extracts "entities, relationships, and communities" so
teams stop re-discovering patterns; example asks: "what happened last time
this service went down?", "common threads across our SEV1s".

**Adopted**
1. *Incidents as first-class nodes* linked to the thing they hit (container),
   where they hit (phase/checkpoint), what fixed them (fix + commit), what
   FAILED to fix them (`fix_attempt_failed` — mb=1 is preserved as a
   documented anti-pattern), and the operator channel (`steered_by`).
2. *"What happened last time X broke?"* as a query primitive — `incidents`,
   `preceded`, and per-site probe history answer exactly this.
3. *Policies in the graph* — standing orders ("p5 anneal crashes >2x => HOLD",
   "max 2 heavyweight builders") are `policy` nodes with `governs` edges, so a
   future automation can ask "what rules govern phase p5?" before acting.

**Rejected**
- Rootly the SaaS and the `pip install "graphifyy[rootly]"` integration: SaaS
  API tether + pip dependency, both out by guardrail.
- LLM entity extraction: our substrate is already structured (JSONL/sqlite/
  markdown with stable phrasing); regex + curated seeds with re-verified doc
  anchors get provenance-perfect nodes for zero compute. An LLM pass would add
  cost and fabrication risk for negative provenance value.

### github.com/HKUST-KnowComp/DeepRefine-Skill — test-time KG refinement
What it is: an agent skill (paper-backed) that refines a Graphify-style
knowledge base at test time: sync query logs → judge which queries need graph
refinement → abduction (candidate node/edge actions) → review with
HIGH/MEDIUM/LOW evidence confidence → dry-run pause for approval → apply →
verify. "Dry-run-first behavior"; LOW-confidence actions refused by default.

**Adopted**
1. *The refinement loop shape* applied to our repair-hint layer: mine real
   failure→fix trajectories (already persisted in
   `implementation.validation.history`, 99/100 ledger rows) → judge hint
   efficacy per class (`hints <class>` clearance rates) → abduction of NEW
   hint classes from unclassified signature clusters (`refine` query) →
   confidence labels by cluster size → apply ONLY as an operator-approved
   patch to validate.py (§5 below).
2. *Dry-run-first / propose-only* — `refine` prints proposals; nothing ever
   edits validate.py automatically. Matches the org's propose-first standing
   order.
3. *Evidence-graded review* — HIGH (>=5 experiments), MEDIUM (>=3), LOW; LOW
   is shown but below the default threshold.

**Rejected**
- `deeprefine-cli` + `graphify` deps, `gpt-4.1-mini` default judge,
  `text-embedding-3-small`: pip + OpenAI API keys + paid SaaS — all three
  guardrails at once. The loop's judgment steps run as deterministic queries
  over real trajectories instead; where a human judgment is needed, the
  operator is the judge (which the skill itself endorses via its approval
  pause).

---

## 2. Substrate map (idea → concrete local source)

| Adopted idea | Substrate (all read-only) |
|---|---|
| Trainer event graph, `preceded_by` chains | `apps/ava-factory/runs/cpu_pilot/reports/{base,agentic}/metrics_nano.jsonl` (real event streams: model_built/phase_enter/checkpoint/branch_forked/done) |
| Live-run anomaly events (resume spikes, restart boundaries) | `apps/ava-factory/reports/dottie_live_status.json` → `pipeline.trainer.series` (LIVE mini run, step 2670, phase 5 — host-side, no docker needed) |
| Incident nodes + fixes + anti-patterns + policies | `CURSOR_HANDOFF.md`, `HANDOFF.md` via curated seed `dottie/kg/data/incidents_seed.json`; every anchor re-verified against the doc at ingest (10/10 verified) |
| Experiment/failure-class/hint subgraph + failure→fix trajectories | ledger COPY `tasks/artifacts/ledger_copy.sqlite3` (the LIVE ledger is refused by path identity) |
| Site probe history | `dottie_live_status.json` → `hub.sites` + `hub.site_history` (8 sites × 115 probes) |
| Fleet containers | `dottie_live_status.json` → `hub.fleet.containers` (14) |
| Steer directives/acks | `apps/bluehenre/data/steer_audit.jsonl` — currently ABSENT on disk (steer_poll writes it on first act); ingester reports `skipped_missing:1` honestly and picks it up when it appears. The 07-22 disk incident's pending steer choice is meanwhile graphed from its doc citation |
| Research baseline + promotions | `dottie_live_status.json` → `research.{baseline,sota_history}`; promotion nodes join onto the SAME `experiment:<id>` nodes the ledger created (cross-source join). Caveat carried from the research memory: the 3 recorded sota rows are artifacts (one retracted by paired-seed testing); the graph stores what the source states — interpretation stays with the reader |

Location decision: `apps/dottie/dottie/kg/` (not `scripts/kg/`) because (a) the
ledger + research loop this layer serves live in apps/dottie, (b) it gets the
app's venv/pytest infrastructure for free, (c) `apps/dottie` permits NEW
packages under the concurrency rule, and (d) `apps/dottie/data/` is already
gitignored — the right home for a derived graph artifact.

## 3. What was built

```
apps/dottie/dottie/kg/
  __init__.py                  package doc + exports
  taxonomy.py                  failure classes (MIRROR of validate._HINTS as of
                               54c43f4 — drift risk stated; §5 removes it),
                               salient-line + signature normalization
  store.py                     GraphStore: sqlite property graph, provenance
                               columns mandatory, read-only source opener
  ingest.py                    5 read-only ingesters (trainer JSONL, live
                               status + series-anomaly mining, ledger COPY +
                               per-attempt trajectories, steer audit, incident
                               seed + doc-anchor verification)
  build.py                     python -m dottie.kg.build  (defaults to the real
                               sources; REFUSES the live ledger by path)
  query.py                     python -m dottie.kg.query  stats|classes|hints|
                               incidents|preceded|sites|node|find|refine
  data/incidents_seed.json     curated incidents/policies with exact doc quotes
apps/dottie/tests/test_kg.py   16 offline-fixture tests
```

Graph file: `apps/dottie/data/kg/graph.sqlite3` (derived, rebuildable,
gitignored).

**SECURITY**
- Ingest is strictly read-only: sqlite sources open via URI `mode=ro`; all
  JSON/JSONL/markdown via plain reads. The graph DB is the only write target.
- The LIVE ledger (`apps/dottie/data/research/ledger.sqlite3`) is refused by
  resolved-path identity in `build.refuse_live_ledger` BEFORE any open —
  a daemon owns that file and even ro opens touch its WAL. Covered by test.
- No network anywhere: no imports of httpx/urllib usage; sources are local
  files (site *probe results* come from the already-published local feed).
- No secrets in the graph: sources carry none (telemetry numbers, doc quotes,
  experiment metadata); no env vars, tokens, or gist ids are ingested. Steer
  ingestion keeps comment ids/status only.
- Graph lives inside the app's gitignored `data/` dir → cannot leak through a
  commit; rebuild-from-source is the recovery story (nothing is authoritative
  in the graph itself).

## 4. Run outputs (real, this box, 2026-07-23)

Build (`.venv\Scripts\python.exe -m dottie.kg.build`):

```
total_nodes 208, total_edges 504
nodes: experiment 100, event 20, container 14, failure_class 9, fix 8, hint 8,
       site 8, incident 7, vlevel 6, state 5, checkpoint 4, phase 3, policy 3,
       promotion 3, run 3, verdict 2, baseline 1, outcome 1, resource 1,
       snapshot 1, steer_directive 1
edges: struggled_with 120, in_state 100, died_at 76, classified_as 76,
       evaluated 23, preceded_by 16, observed 16, emitted 16, in_phase 9,
       probed 8, hinted_by 8, resolved_by 7, resolved_by_correction 4,
       reported 4, governs 4, promoted 3, moved_baseline 3, affects 3,
       saved 2, entered_phase 2, steered_by 1, parked_at 1, forked_from 1,
       fix_attempt_failed 1
sources: metrics base {events 4, steps 90} · agentic {events 5, steps 25} ·
         live_status {sites 8, containers 14, anomalies 7, promotions 3} ·
         ledger {experiments 100, failures 76, resolved_after_correction 4} ·
         steer {skipped_missing 1} · incidents {7 + 3 policies, 10/10 anchors
         verified}
```

Q1 — "what preceded the trainer restart in p5?" (step 2510 IS in p5; p5 starts
~step 2097):

```
> python -m dottie.kg.query preceded event:mini_live:series_141:step_reemitted -k 6
target: event:mini_live:series_141:step_reemitted  step_reemitted @step 2510  [dottie_live_status.json:pipeline.trainer.series[141]]
  -1 before: event:mini_live:series_122:loss_spike  kind=loss_spike index=122 step=2330 lm_loss=3.694 recent_min=0.1488  [...series[122]]
  -2 before: event:mini_live:series_41:loss_spike   kind=loss_spike index=41 step=1520 lm_loss=2.908 recent_min=0.1508  [...series[41]]
  -3 before: event:mini_live:series_40:loss_spike   kind=loss_spike index=40 step=1510 lm_loss=3.355 ...
  -4 before: event:mini_live:series_39:loss_spike   kind=loss_spike index=39 step=1500 lm_loss=3.458 ...
  -5 before: event:mini_live:series_38:loss_spike   kind=loss_spike index=38 step=1490 lm_loss=5.441 recent_min=0.1508  [...series[38]]
  -6 before: event:mini_live:series_3:step_reemitted kind=step_reemitted step=20 ...
```
(The 1490–1520 spike cluster is the documented resume-spike pattern; policy
node `policy:resume-loss-spike-is-normal` sits in the same graph, cited to
CURSOR_HANDOFF.md:L72.)

Q2 — "does the einsum hint class actually resolve einsum failures?":

```
> python -m dottie.kg.query hints einsum --limit 3
failure class : einsum  (pattern: einsum\(\))
repair hint   : replace einsum with explicit reshape/matmul/transpose ops + shape asserts
encounters    : 16 correction trajectories hit this class; 6 cleared it (clearance rate 0.375)
    cleared: experiment:321710c7ddfc
    cleared: experiment:aea41c349279
    cleared: experiment:af0a34115956
died matching : 10 experiments (final failure in this class)
    experiment:2b75f1526c68  state=failed_validation attempts=5  [ledger:experiments:2b75f1526c68]
      sig: RuntimeError: einsum(): output subscript n does not appear in the equation for any input operand
    ...
```

Q3 — "OOM incidents with fixes, containers, phases, doc-cited":

```
> python -m dottie.kg.query incidents oom
incident:2026-07-22-p4-oom-crash-loop  [major/oom]  cited HANDOFF.md:L30 (anchor_verified=True)
  p4 OOM crash-loop on the mini tool-branch trainer
  root cause: p4_long seq 4096 GPU memory pressure at checkpoint saves and phase transitions
  -[affects]-> container:dottie-factory-trainer-1
  -[fix_attempt_failed]-> fix:...:failed  (mb=1 was a FAILED experiment (GPU-starved, 0 steps/40min) — never repeat)
  -[in_phase]-> phase:p4_long
  -[resolved_by]-> fix:...  (mb=2 + torch.cuda.empty_cache() at ckpt saves + phase transitions in dottie/train.py)
```

Q4 — DeepRefine judge+abduction over real trajectories:

```
> python -m dottie.kg.query refine --min-count 5
[HIGH] 19 experiments, 11 self-cleared, levels=['static']
  signature: FN Undefined name `X`                       (ruff F821)
[HIGH] 10 experiments, 4 self-cleared, levels=['contract']
  signature: no 'X' method found on any class
[HIGH] 7 experiments, 0 self-cleared, levels=['dry_run']
  signature: RuntimeError: element N of tensors does not require grad and does not have a grad_fn
```

Also available: `classes` (per-class histogram: shape_algebra 15, einsum 10,
ctor_missing_arg 7, no_attribute 6, ... unclassified 34 — classification reads
per_level details because the ledger's `failure` column is head-truncated),
`sites` (8/8 up across 115 probes; hub avg 824.7 ms is the slow outlier,
max 32.7 s), `stats`, `node`, `find`.

Tests (memory gate checked ≥900 MB first):

```
> .venv\Scripts\python.exe -m pytest tests/test_kg.py -q
16 passed in 0.93s
```

## 5. DeepRefine patch PROPOSAL for the research repair loop

Owned files untouched; this section is the diff-shaped proposal for the lane
that owns `dottie/research/validate.py`.

**Finding that shaped the proposal (verified):** `implementation.py:165`
already persists `validation.history` per attempt — 99/100 ledger rows carry
full failure→fix trajectories. So the KG can mine efficacy TODAY (§4 Q2/Q4)
by re-deriving which hint fired via a regex mirror. The proposal makes the
loop first-class and drift-proof, in three steps:

**(a) Name the hints; log `hint_id` per attempt** — `validate.py`:

```diff
--- a/apps/dottie/dottie/research/validate.py
+++ b/apps/dottie/dottie/research/validate.py
@@
-_HINTS: tuple = (
-    (r"einsum\(\)",
+#: (hint_id, pattern, hint). hint_id is STABLE: the kg layer and the ledger's
+#: per-attempt history key hint-efficacy stats on it.
+_HINTS: tuple = (
+    ("einsum", r"einsum\(\)",
      "EINSUM REPAIR: the equation does not match the operands. ..."),
-    (r"must match the size of tensor|Expected size for first two dimensions|mat1 and mat2 shapes",
+    ("shape_algebra",
+     r"must match the size of tensor|Expected size for first two dimensions|mat1 and mat2 shapes",
      "SHAPE-ALGEBRA REPAIR: ..."),
     ...same for the remaining six: ctor_missing_arg, no_attribute,
     ...name_error, nan_inf, degenerate, output_shape_contract
 )
@@
-def diagnose_failure(level: str, detail: str) -> str:
-    """Targeted repair hint for a known failure class, or '' when unknown."""
-    for pattern, hint in _HINTS:
-        if re.search(pattern, detail):
-            return hint
+def diagnose_failure_id(level: str, detail: str) -> tuple[str, str]:
+    """(hint_id, hint) for a known failure class, or ("", "")."""
+    for hint_id, pattern, hint in _HINTS:
+        if re.search(pattern, detail):
+            return hint_id, hint
     if level == "dry_run" and "Traceback" in detail:
-        return ("GENERAL DRY-RUN REPAIR: ...")
-    return ""
+        return "general_dry_run", ("GENERAL DRY-RUN REPAIR: ...")
+    return "", ""
+
+
+def diagnose_failure(level: str, detail: str) -> str:
+    """Back-compat wrapper (as_feedback and tests keep working unchanged)."""
+    return diagnose_failure_id(level, detail)[1]
@@ def validate_with_correction(...)   # BOTH history.append sites
-        history.append({"attempt": attempts, "ok": result.ok, "level": result.level,
-                        "status": result.status, "detail": result.detail[:2000]})
+        history.append({"attempt": attempts, "ok": result.ok, "level": result.level,
+                        "status": result.status, "detail": result.detail[:2000],
+                        "hint_id": diagnose_failure_id(result.level, result.detail)[0]})
```

No ledger/schema change needed: history already flows into
`implementation.validation` via `implementation.py:162-166` (verified). The kg
ingester already reads `history[*].hint_id` the moment it appears (it falls
back to the regex mirror when absent), and `dottie.kg.taxonomy` then imports
`validate._HINTS` as the single source of truth instead of mirroring it.

**(b) KG-driven hint refinement cadence (no validate.py involvement).**
`python -m dottie.kg.build && python -m dottie.kg.query refine` after each
ledger copy refresh = DeepRefine's sync→judge→abduction. Output is a ranked,
evidence-cited proposal list; apply = a reviewed edit to `_HINTS`.

**(c) Three concrete candidate hints from today's HIGH clusters** (evidence in
§4 Q4; drafted for the owning lane / operator to accept, edit, or reject):

```python
# 7 experiments, 0/7 ever self-cleared — the corrector NEVER fixes this class
# unaided; strongest case for a new hint:
("autograd_grad_fn", r"does not require grad and does not have a grad_fn",
 "AUTOGRAD REPAIR: you called backward()/grad() on a tensor that has no "
 "graph. Do not compute gradients in forward with no_grad inputs — if you "
 "need gradient-like signals, derive them from tensors YOU create with "
 "requires_grad=True inside forward, or restructure so the LM loss trains "
 "your parameters instead."),
# 10 experiments, 4/10 self-cleared:
("no_forward_method", r"no 'forward' method found on any class",
 "CONTRACT REPAIR: the block must be an nn.Module subclass whose method is "
 "named exactly `forward(self, hidden_states)`. Rename __call__/apply/run "
 "to forward; do not wrap the model in a function."),
# 19 experiments, 11/19 self-cleared (F821 at the static level — the existing
# name_error hint never fires because ruff output says 'F821 Undefined name',
# not 'NameError'):
("undefined_name_static", r"F821|Undefined name",
 "UNDEFINED NAME: a name is used but never defined/imported. Define every "
 "helper before use and import only torch / torch.nn / math."),
```

Everything stays inside validate.py's existing philosophy: pure, no I/O, an
unknown failure gets no hint rather than a wrong one, and hints change ONLY by
reviewed diff — the DeepRefine "apply after approval" gate, natively.

## 6. How to extend (5 lines)

1. New source: add `ingest_<source>(store, path) -> counts` in `ingest.py` (read-only, absent-tolerant, cite `source_ref` on every write), call it from `build.build_graph`.
2. New incident/policy: append to `dottie/kg/data/incidents_seed.json` with an EXACT quote from the doc — ingest verifies the anchor and flags drift.
3. New query: add `cmd_<name>` + subparser in `query.py`; compose from `GraphStore.edges_to/edges_from/chain_back/nodes_by_type`.
4. New failure class: land it in `validate._HINTS` (per §5 the taxonomy mirror follows; until §5a merges, also mirror it in `taxonomy.FAILURE_CLASSES`).
5. Rebuild anytime: `.venv\Scripts\python.exe -m dottie.kg.build` (idempotent, seconds); tests: `-m pytest tests/test_kg.py -q` after the ≥900 MB memory gate.
