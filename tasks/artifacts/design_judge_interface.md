# Design: Dottie-as-judge against the agent-eval judge contract (one page)

Status: L2 design only. `C:\Users\jcdav\agent-eval` treated read-only. **Explicit up front:
no servable judge model exists this cycle** — this doc specifies the plug-in point so the
adapter is a 15-line change when one does.

## The contract as implemented (`agent-eval/scripts/judge.py`, verified 2026-07-23)

- **Factory**: `create_judge(complete, *, criterion, key, few_shot=None, judge_model="unknown")`
  (judge.py:65) returns `judge(*, inputs, outputs, reference=None) -> dict`.
- **Model plug**: the model is a plain `complete(prompt: str) -> str` callable — provider-
  agnostic by construction (judge.py docstring:6-9: "same judge runs against Ollama today and
  a Dottie checkpoint later with zero changes here").
- **Return shape**: `{key, score, comment, judge_model}`; `score` is `True/False`, a float in
  `[0,1]`, or `None`.
- **Prompt shape** (build_judge_prompt, :31-46): `JUDGE_INSTRUCTIONS` (criterion + "reply with
  ONLY a JSON object {score, comment}") → optional few-shot blocks (`INPUT/OUTPUT/VERDICT`
  with JSON verdicts) → `INPUT:` → optional `REFERENCE (ground truth):` → `OUTPUT:` →
  terminal `VERDICT:`.
- **Parsing** (parse_judge_reply, :49-62): first `{...}` blob, strict JSON, score must be bool
  or in-range number; anything else → `{"score": None, "comment": "unparseable judge reply: <raw…>"}`.
- **Honesty rules** (docstring:11-16, enforced): unparseable ⇒ `score=None` never a guessed
  verdict; backend exception ⇒ `score=None` with `"judge backend error: <type>: <msg>"`
  (:76-81); results always carry `judge_model` provenance.
- **Tests**: `scripts/test_judge.py` — 9 bare-python checks (parse, prompt assembly, e2e via a
  fake `complete`, honest backend failure). Run: `python scripts/test_judge.py` from the repo.
- **Current wiring**: none. `run_eval.py` scores tasks deterministically
  (`shell`/`regex`/`tool_and_regex` success checks) and `trajectory.py:7` is explicitly
  "no judge model involved". The judge is a ready-but-unwired quality layer.

## What a Dottie-as-judge implementation needs

1. **Adapter** (new file, `agent-eval/scripts/dottie_backend.py`): `make_dottie_complete(url, timeout_s=120)`
   returning a closure that POSTs `{"text": prompt, ...}` to the factory serve endpoint
   (`apps/ava-factory/server.py`, `/generate` on :8000, engine reads `AVA_CKPT=/ckpt/latest`)
   and returns the generated string. Raise on HTTP/timeout errors — never return a fabricated
   reply; `create_judge` already converts exceptions into honest `score=None` rows.
2. **Provenance**: `judge_model=f"dottie:{ckpt_name}@{git_sha}"` — ckpt name read from the
   `ckpt/latest` pointer text, so a scoreboard row is attributable to an exact checkpoint.
3. **Prompt-shape reality check**: the contract requires the model to emit a JSON verdict.
   The current mini checkpoint has zero instruction-following (exact-match probes 0/200 —
   documented honest baseline; weighted heldout ppl is the only graded signal). It will fail
   `parse_judge_reply` essentially always, producing all-`None` scores. That is the correct,
   honest outcome under this contract — not a crash — and is exactly why:
4. **No servable judge model this cycle**: the live mini run cannot judge, and standing up an
   Ollama judge (qwen3:8b) is barred while the trainer holds the box (16GB-RAM incident
   history in agent-eval/README; this cycle's no-model-load guardrail). The gate for flipping
   this on is a chat/tool SFT Dottie checkpoint that can follow the JSON-verdict instruction.
5. **Failure handling downstream** (the only real new logic): scoreboard integration must
   render `score=None` as **"unjudged"**, never as 0/fail; a run where >50% of judge rows are
   `None` should be marked `judge_invalid` (the judge can't hold the pen). Surfacing `key` +
   `comment` beside every score is already required by the contract's honesty rules.
6. **Calibration set**: 5-10 hand-labeled `few_shot` examples per criterion (start with the
   grounding criterion — the repo's stated north star is factual correctness), stored beside
   the tasks (e.g. `tasks/_calibration/<criterion>.json`) so Ollama-judge and Dottie-judge
   runs are calibrated identically and scores stay comparable across brain swaps.

**Acceptance test for the adapter** (no model needed): reuse test_judge.py's fake-backend
pattern against a stub HTTP server; assert timeout/connection errors surface as
`judge backend error` rows and that `judge_model` carries the pointer-derived ckpt name.
