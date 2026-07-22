# Fixes follow-up — 2026-07-22

Second pass on the monorepo-review findings (after PR #2). Distinguishes **applied+verified** (this branch), **design-only** (factory code — torch/fastapi absent on the review box, cannot runtime-verify here), and **rejected/tracked**.

## Applied + gated green (this branch)

| Finding | Fix | Gate |
|---|---|---|
| agent-os 🟡 state_store race | atomic UPSERT+RETURNING under txn, busy_timeout, typed StateStoreCorruptError | ava-skills 83 passed (incl 24-writer concurrency + corruption) |
| agent-os 🟡 _run_in_factory hang | env-overridable timeout + TimeoutExpired handling | scout-cli 157 passed |
| packages 🟡 bare excepts | 5× `except:`→`except Exception`+log | personal-graphify 68 passed |
| packages 🟡 anti-mock blind spot | per-field seed-variance check | ava-open-harness 44 passed |
| docs 🔴🟡 CI decorative / apps/dottie unlisted | real pytest gates, apps/dottie→workspace, 2 dead steps repaired | YAML valid, frozen sync clean |

## Rejected — false positive (verified, NO change made)

**agent-os 🟡 resolve.py factory-code marker.** The original review claimed the marker probes `ava/rl/codeact_loop.py` while the real file is `dottie/rl/codeact_loop.py`, implying a silent external-checkout dependency. An adversarial verifier reproduced the runtime and found the premise **inverted**: the monorepo `ava/` is a compat shim (`ava/rl/__init__.py` does `from dottie.rl import *`) that collides with the *app's own* `dottie` package, so `import ava.rl.codeact_loop` only works against the standalone real-`ava` checkout — which is exactly the one the current marker selects. Widening the marker to accept `dottie/rl/...` would make apps/ava-factory resolve FIRST and raise ModuleNotFoundError deep in engine.py — a regression. **Left unchanged by design.**

## Tracked debt (surfaced, not addressed here)

- **apps/ava-factory ruff: ~1139 errors repo-wide** (was 685 on 07-22 review; repo is a firehose). CI ruff step keeps `|| true` with a comment until this is a dedicated cleanup. 468 auto-fixable.
- **apps/dottie: ~20 pre-existing test failures** (test_research/test_api, TypeErrors) — surfaced once the app joined the workspace. CI runs the suite non-blocking; triage is its own task.

## Factory patches — DESIGN ONLY (apply + verify on a box with torch + fastapi)

> These touch training/serving code that cannot be runtime-verified on the review box (no torch/fastapi). Each carries a concrete change + the exact verify commands for the factory box. Do NOT merge unverified.

### train.py — eval-gate checkpoint promotion (🔴 architectural)

**File(s):** `apps/ava-factory/dottie/train.py`

**Finding:** apps/ava-factory/dottie/train.py promotes EVERY checkpoint to the live-served pointer with no eval gate. `_point_latest_at(ckpt_dir, p)` runs unconditionally after each rotating checkpoint (line 630) and after the final checkpoint (line 645); serve_engine.py's hot-reload loop (_maybe_reload, ~5s poll) reloads whatever `ckpt/latest` names. The eval verdict machinery already exists and is unused: efficiency_gain.eg_trend (apps/ava-factory/efficiency_gain.py:125) returns {"verdict": "promote"|"hold"|"insufficient", ...}, and rl/codeact_eg_gate.py adapts it. So a regressed checkpoint reaches production within one hot-reload interval and the harness verdict changes nothing. FIX (design only; torch absent so not run here): split the pointer into an ungated training-frontier pointer `latest_candidate` (advanced for every checkpoint — nothing is ever lost, manual promote always possible) and the served pointer `latest`, which is repointed only on a fresh "promote" verdict for that exact checkpoint. Gating is opt-in via $AVA_PROMOTE_GATE and fail-closed when on; with it off, today's behavior is bit-for-bit preserved. A companion resume fix reads the candidate frontier so enabling the gate cannot rewind training.

**Rationale:** Minimal and additive: the promotion primitive is generalized to write any pointer name; two call sites (630, 645) swap one function name; a resume pointer is redirected. No checkpoint saving, no phase/stable-ckpt logic, no serve_engine code changes. serve_engine only ever reads `latest` (serve_engine.py:220 checks pointer.name == "latest"), so `latest_candidate` is inert to the live server -- it is purely an audit / manual-promote / resume pointer. Opt-in-safe on both sides: with $AVA_PROMOTE_GATE off (default) _promote_ok returns True immediately, so `latest` and `latest_candidate` advance together to the exact same target on every checkpoint -- byte-identical to today. With it on, the gate is fail-closed: only a fresh verdict naming THIS checkpoint promotes; hold/insufficient/missing/stale/unreadable all keep serving the last blessed checkpoint (stale-but-good strictly beats serving a regression). The for_ckpt identity check defeats the real trap -- a leftover "promote" file from step_1000 must not bless step_1250. Bootstrap (`latest` absent) promotes so a cold start / branch fork is never starved. Reusing eg_trend's own dict as the on-disk contract means no new verdict logic and no re-implementation of the rank-invariance rule; the honest-fail refusal in codeact_eg_gate_from_eval naturally yields "no file -> hold." The companion resume fix is required for safety: without it, enabling the gate would make `latest` lag and a --resume would rewind training to the last promoted step, silently re-training and re-consuming shards -- so resume must follow latest_candidate (the training frontier), falling back to `latest` for pre-upgrade run dirs.

**Risk:** Low, and concentrated in the opt-in path. (1) When the gate is ON and the harness is never wired to write promote_verdict.json, `latest` pins at the first (bootstrap) checkpoint forever while training advances -- the served model goes stale rather than regressed. This is the intended fail-closed posture, but operators must know to wire the harness or leave the gate off; the promote_held log line (with gate reason) makes the hold visible. (2) A lagging `latest` points at an older step_N.pt; the train.py docstring mentions a keep-last-N janitor for step_*.pt (no active implementation found in-tree today). If such a janitor is later added it MUST treat both the `latest` and `latest_candidate` targets as pinned, or it could delete the served file. Worth a one-line note where the janitor lands. (3) Behavior change to resume even with the gate OFF: resume now prefers latest_candidate over latest. When the gate is off these two always name the same file, so the loaded checkpoint is identical; the only observable delta is the added frontier= field in the "resumed" log. (4) Not addressed by design intent: the gate governs what is SERVED, not what is TRAINED -- training legitimately continues from unblessed candidate weights. That is correct (you don't want to roll back optimizer state), but reviewers should confirm that expectation. No change to concurrency: pointer writes remain atomic os.replace of a *.tmp, and serve_engine already never opens *.tmp.

**Proposed change:**

```diff
Four hunks in apps/ava-factory/dottie/train.py. `json` (line 24) and `os` (line 26) are already imported; no new imports. `_point_latest_at` is kept as a back-compat shim (serve_engine.py:13 and tests/test_server_endpoints.py:399 reference it in prose).

--- HUNK 1: replace the def at lines 165-169 ---
-def _point_latest_at(ckpt_dir: Path, target: Path) -> None:
-    latest = ckpt_dir / "latest"
-    tmp = ckpt_dir / "latest.tmp"
-    tmp.write_text(target.name)
-    os.replace(tmp, latest)  # a file, not a symlink: Windows volumes
+def _point_pointer_at(ckpt_dir: Path, name: str, target: Path) -> None:
+    """Atomically repoint a pointer file (`latest`, `latest_candidate`) at
+    `target` by filename. A file, not a symlink: Windows volumes."""
+    pointer = ckpt_dir / name
+    tmp = ckpt_dir / f"{name}.tmp"
+    tmp.write_text(target.name)
+    os.replace(tmp, pointer)
+
+
+def _point_latest_at(ckpt_dir: Path, target: Path) -> None:
+    # Back-compat shim: unconditional repoint of the *served* pointer.
+    _point_pointer_at(ckpt_dir, "latest", target)
+
+
+def _promote_ok(ckpt_dir: Path, target: Path) -> tuple[bool, str]:
+    """Fail-closed gate over the EXISTING eval verdict for the *served* pointer.
+
+    The eval harness (scripts/run_eval.py -> efficiency_gain.eg_trend /
+    rl.codeact_eg_gate) scores the candidate out-of-band and drops its verdict
+    dict at ckpt_dir/promote_verdict.json (override: $AVA_PROMOTE_VERDICT),
+    naming the checkpoint it blessed:
+        {"verdict": "promote", "for_ckpt": "step_1000.pt", ...}
+
+    Rules:
+      * gate OFF (default; $AVA_PROMOTE_GATE unset/0): promote -- today's
+        behavior, unchanged. Nothing is ripped out.
+      * `latest` absent (fresh run / branch fork): promote -- no live model to
+        protect, so the gate never starves the server at cold start.
+      * gate ON: promote ONLY on a *fresh* verdict that names THIS checkpoint
+        and reads "promote". hold / insufficient / missing / stale (names a
+        different ckpt) / unreadable all HOLD the served pointer at the last
+        blessed checkpoint. The candidate pointer still advances (caller), so
+        nothing is lost and an operator can promote by hand.
+    """
+    flag = os.environ.get("AVA_PROMOTE_GATE", "0").strip().lower()
+    if flag not in ("1", "true", "yes", "on"):
+        return True, "gate_off"
+    if not (ckpt_dir / "latest").exists():
+        return True, "bootstrap_no_latest"
+    env_v = os.environ.get("AVA_PROMOTE_VERDICT")
+    vpath = Path(env_v) if env_v else (ckpt_dir / "promote_verdict.json")
+    try:
+        v = json.loads(vpath.read_text(encoding="utf-8"))
+    except FileNotFoundError:
+        return False, "hold_no_verdict"
+    except (ValueError, OSError) as exc:
+        return False, f"hold_bad_verdict:{type(exc).__name__}"
+    if v.get("for_ckpt") != target.name:
+        return False, f"hold_stale_verdict:{v.get('for_ckpt')!r}"
+    if v.get("verdict") != "promote":
+        return False, f"hold_verdict:{v.get('verdict')!r}"
+    return True, "promote"
+
+
+def _publish_ckpt(ckpt_dir: Path, target: Path, *, step: int, log) -> None:
+    """Advance the ungated candidate pointer for EVERY checkpoint, then gate the
+    served `latest` pointer behind the eval verdict (fail-closed when gate on)."""
+    _point_pointer_at(ckpt_dir, "latest_candidate", target)
+    ok, why = _promote_ok(ckpt_dir, target)
+    if ok:
+        _point_pointer_at(ckpt_dir, "latest", target)
+    log("promote" if ok else "promote_held",
+        path=str(target), step=step, gate=why, served=ok)

--- HUNK 2: resume frontier. After line 434 (`latest = ckpt_dir / "latest"`) insert: ---
         step, tokens_done = 0, 0
         latest = ckpt_dir / "latest"
+        # Resume from the *training* frontier (latest_candidate -- advanced for
+        # every checkpoint), not the *served* frontier (latest -- gated). With the
+        # gate off the two are identical; with it on, `latest` can lag the newest
+        # checkpoint and resuming from it would rewind training to the last
+        # promoted step. Fall back to `latest` for runs predating latest_candidate.
+        candidate_ptr = ckpt_dir / "latest_candidate"
+        resume_ptr = candidate_ptr if candidate_ptr.exists() else latest

--- and change the resume block at lines 449-454: ---
-        if args.resume and latest.exists():
-            target = ckpt_dir / latest.read_text().strip()
+        if args.resume and resume_ptr.exists():
+            target = ckpt_dir / resume_ptr.read_text().strip()
             step, tokens_done = load_ckpt(
                 target, model=model, opt=opt, sampler=sampler, device=device
             )
-            log("resumed", ckpt=str(target), step=step, tokens_done=tokens_done)
+            log("resumed", ckpt=str(target), step=step, tokens_done=tokens_done,
+                frontier=resume_ptr.name)

--- HUNK 3: line 630 ---
-                _point_latest_at(ckpt_dir, p)
+                _publish_ckpt(ckpt_dir, p, step=step, log=log)

--- HUNK 4: line 645 ---
-        _point_latest_at(ckpt_dir, final)
+        _publish_ckpt(ckpt_dir, final, step=step, log=log)

Harness side (one-line wiring, not a train.py change): scripts/run_eval.py already computes eg_trend(...)/codeact_eg_gate(...); persist that dict plus "for_ckpt": <candidate filename> to $AVA_CKPT_DIR/promote_verdict.json after scoring latest_candidate. codeact_eg_gate_from_eval intentionally RAISES rather than fabricate rates when the capability numbers don't exist -- in that state no verdict file is written, so the gate simply holds (correct fail-closed behavior).
```

**Verify on factory box:**

```bash
Run on a box WITH torch + fastapi, from apps/ava-factory (train.py top-level `import torch` and `from model_1b import ...` require this cwd):

cd /home/user/dottie/apps/ava-factory

# 0. parse + import (import pulls torch through train.py's module-level import)
python -c "import ast; ast.parse(open('dottie/train.py').read()); print('parse ok')"
python -c "from dottie import train; print('import ok', hasattr(train,'_publish_ckpt'), hasattr(train,'_promote_ok'), hasattr(train,'_point_pointer_at'))"

# 1. existing verdict machinery still green (proves the eg_trend contract we consume)
python -m pytest -q tests/test_efficiency_gain.py tests/test_codeact_eg_gate.py tests/test_server_endpoints.py

# 2. DETERMINISTIC proof of gate semantics (pure-python helpers; import needs torch)
python - <<'PY'
import os, json, tempfile
from pathlib import Path
from dottie import train
d = Path(tempfile.mkdtemp()); nolog = lambda e, **k: None
os.environ["AVA_PROMOTE_GATE"] = "1"
(d/"step_10.pt").write_text("x")
train._publish_ckpt(d, d/"step_10.pt", step=10, log=nolog)   # bootstrap: no latest -> promote
assert (d/"latest").read_text() == "step_10.pt"
assert (d/"latest_candidate").read_text() == "step_10.pt"
(d/"step_20.pt").write_text("x")
train._publish_ckpt(d, d/"step_20.pt", step=20, log=nolog)   # no verdict -> HOLD served, advance candidate
assert (d/"latest").read_text() == "step_10.pt"
assert (d/"latest_candidate").read_text() == "step_20.pt"
(d/"promote_verdict.json").write_text(json.dumps({"verdict":"promote","for_ckpt":"step_10.pt"}))
train._publish_ckpt(d, d/"step_20.pt", step=20, log=nolog)   # stale verdict (names step_10) -> HOLD
assert (d/"latest").read_text() == "step_10.pt"
(d/"promote_verdict.json").write_text(json.dumps({"verdict":"promote","for_ckpt":"step_20.pt"}))
train._publish_ckpt(d, d/"step_20.pt", step=20, log=nolog)   # fresh promote for step_20 -> PROMOTE
assert (d/"latest").read_text() == "step_20.pt"
(d/"step_30.pt").write_text("x")
(d/"promote_verdict.json").write_text(json.dumps({"verdict":"hold","for_ckpt":"step_30.pt"}))
train._publish_ckpt(d, d/"step_30.pt", step=30, log=nolog)   # hold verdict -> HOLD served
assert (d/"latest").read_text() == "step_20.pt"
assert (d/"latest_candidate").read_text() == "step_30.pt"
os.environ["AVA_PROMOTE_GATE"] = "0"
train._publish_ckpt(d, d/"step_30.pt", step=30, log=nolog)   # gate off -> unconditional promote (today's behavior)
assert (d/"latest").read_text() == "step_30.pt"
print("GATE SEMANTICS OK")
PY

# 3. E2E smoke, gate OFF must reproduce today's behavior (CPU nano preset).
#    nano checkpoint_every_steps=250 but line 618 also fires at step==total_steps,
#    so a 20-step run yields step_20.pt + base_final.pt; both pointers must match.
python -m dottie.train --preset nano --device cpu --max-steps 20 --run /tmp/ckpt_off > /tmp/off.log 2>&1
test "$(cat /tmp/ckpt_off/latest)" = "$(cat /tmp/ckpt_off/latest_candidate)" && echo "E2E gate-off parity OK"

# 4. E2E gate ON, no verdict wired: candidate advances past served; served pinned at bootstrap ckpt.
AVA_PROMOTE_GATE=1 python -m dottie.train --preset nano --device cpu --max-steps 40 --run /tmp/ckpt_on > /tmp/on.log 2>&1
echo "served=$(cat /tmp/ckpt_on/latest)  frontier=$(cat /tmp/ckpt_on/latest_candidate)"
grep -q '"event": "promote_held"' /tmp/on.log && echo "HOLD path exercised OK"
# resume must follow the candidate frontier (not rewind to served):
AVA_PROMOTE_GATE=1 python -m dottie.train --preset nano --device cpu --max-steps 60 --resume --run /tmp/ckpt_on > /tmp/on2.log 2>&1
grep -o '"frontier": "latest_candidate"' /tmp/on2.log && echo "RESUME uses candidate frontier OK"
```

### server.py — input validation / DoS caps (🟡)

**File(s):** `apps/ava-factory/server.py`

**Finding:** apps/ava-factory/server.py accepts unbounded, unconstrained input on /generate, /chat, /assistant, /jspace/inspect, /jspace/safety, /jspace/intervene and the /jspace/stream WebSocket. Two distinct problems: (1) INPUT VALIDATION — every request model (GenerateReq, ChatReq, AssistantReq, InspectReq, InterveneReq, ChatMessage) declares bare `str`/`int`/`float` fields with no Field() constraints. A tiny positive temperature crashes generation with a 500, and unbounded text/message length lets one request queue an arbitrarily large forward pass. (2) DoS — ServeEngine.generate() re-runs a full forward per token with NO KV cache and holds an engine-wide threading.RLock (self._lock) for the entire multi-token loop; every other engine method — stats() [/health], generate() [/generate,/chat], inspect() [/jspace/inspect,/jspace/safety], intervene(), block_stream() [WS] — also takes that same lock, so a single large-prompt request serializes and blocks liveness and all other routes (single-request DoS). Part (1) is fixed by the mechanical Pydantic diff below; part (2) is a design recommendation, NOT in this diff.

**Rationale:** Why the temperature bound closes the 500: generate() branches `temperature <= 0` to a safe argmax, so the crash is reachable only via a tiny POSITIVE temperature. torch's F.softmax is max-subtracted (numerically stable) for any FINITE input, so the NaN appears only when the division `logits / temperature` itself overflows float32 to +inf (then inf - max(inf) = NaN); torch.multinomial rejects NaN with RuntimeError -> unhandled -> 500. Overflow needs temperature < |logits|/3.4e38 (roughly < 1e-37 for logits ~O(100)). gt=0.01 rejects everything below 0.01 with a ~35-order-of-magnitude margin, so the division stays finite and softmax stays stable. le=4 additionally rejects degenerate near-uniform sampling. Client-compatibility checked: the shipped chat UI (dottie/chat_html.py) slider is min=0.1/max=1.5 and sends max_tokens=256, all inside [gt=0.01, le=4] and le=256. The only temperature=0.0 (greedy) callers are the RL/codeact path (dottie/rl/codeact_policy.py) and its tests, which call the model directly and never traverse these HTTP models, so gt=0.01 does not break them.

Why the length caps matter: text/content/messages are the DoS knobs. tokenizer.encode(text) grows linearly with input; the engine then runs a full O(L^2) forward per generated token with no KV cache while holding self._lock, so an unbounded prompt lets one request pin the single engine lock and starve /health and every other route. Bounding text to ~16k chars (~4k tokens, the max trained mini context) and total chat/assistant content via the model_validator caps that worst-case work; per-message + message-count caps prevent assembling a giant prompt from many small messages. These constraints run in FastAPI's validation phase BEFORE the handler calls get_engine(), so bad input is rejected with 422 without ever loading the model — which is also why the verify steps below work with AVA_SKIP_ENGINE_BOOT=1 and no checkpoint. This is the safe, mechanical half; the lock/KV-cache rework (items a-d above) is the real DoS fix and is intentionally left as a design recommendation, not code, because it changes concurrency semantics and needs the engine + a checkpoint to test.

**Risk:** Low, but three behavior changes to flag. (1) temperature=0 (greedy via the HTTP API) is no longer accepted — gt=0.01 rejects it with 422; no shipped HTTP client uses it (only the direct-call RL path), greedy stays reachable in-engine, and an explicit greedy flag is the clean way to re-expose it. (2) Out-of-range max_tokens/max_steps now return 422 instead of being silently clamped by the route-level min(...) — stricter but more correct; shipped clients send 256/200/within-range so are unaffected. (3) role is length-capped but still not restricted to a literal set, preserving the tolerant `_ROLE_TAGS.get(m.role,'<|user|>')` fallback. The 16_000-char / 32-message / 256-token defaults are conservative and exposed as named constants for operator tuning. image is deliberately left uncapped (unused by inspect, possible future multimodal) with a request-body size limit at uvicorn/proxy as the correct guard. Pydantic v2 assumed and confirmed (ConfigDict/model_config/alias already used).

**Proposed change:**

```diff
MECHANICAL VALIDATION DIFF (server.py only; safe part). Pydantic v2 is already in use (ConfigDict/model_config/Field/alias), so Field(min_length=…, max_length=…, ge=…, gt=…, le=…) and @model_validator are all available.

--- 1. import: add model_validator (line 21)
- from pydantic import BaseModel, ConfigDict, Field
+ from pydantic import BaseModel, ConfigDict, Field, model_validator

--- 2. request-size budget constants: insert immediately before `class InspectReq(BaseModel):` (line 142)
+ # Request-size guards. Bound worst-case work per request so no single prompt
+ # can monopolise the engine-wide RLock (see the DoS note). Operator-tunable;
+ # defaults track max trained context (nano seq<=1024, mini seq<=4096 -> ~16k
+ # chars at ~4 chars/token). Route-level min(...,256)/min(...,200)/min(...,6)
+ # clamps stay as belt-and-suspenders.
+ MAX_TEXT_CHARS = 16_000
+ MAX_INSTRUCTION_CHARS = 4_000
+ MAX_CONCEPT_CHARS = 128
+ MAX_MESSAGES = 32
+ MAX_TOKENS_CAP = 256
+ MAX_ASSISTANT_TOKENS_CAP = 200
+ MAX_STEPS_CAP = 6
+ TEMP_FLOOR = 0.01   # gt: below this the float32 logits/temp division can overflow to inf -> NaN -> 500
+ TEMP_CEIL = 4.0
+
+

--- 3. InspectReq (lines 142-145)
  class InspectReq(BaseModel):
-     text: str
-     instruction: str | None = None
-     image: str | None = None
+     text: str = Field(..., min_length=1, max_length=MAX_TEXT_CHARS)
+     instruction: str | None = Field(default=None, max_length=MAX_INSTRUCTION_CHARS)
+     # image is currently unused by /jspace/inspect + /jspace/safety; a request-body
+     # size limit (uvicorn/proxy, see DoS note) is the right guard for a base64 blob.
+     image: str | None = None

--- 4. InterveneReq fields (lines 151-157) — keep model_config + both @property methods unchanged
-     from_: str | None = Field(default=None, alias="from")
-     to: str | None = None
-     branch: str = "base"
-     text: str | None = None
-     space: str = "system2"
-     from_c: str | None = None
-     to_c: str | None = None
+     from_: str | None = Field(default=None, alias="from", max_length=MAX_CONCEPT_CHARS)
+     to: str | None = Field(default=None, max_length=MAX_CONCEPT_CHARS)
+     branch: str = Field("base", max_length=64)
+     text: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
+     space: str = Field("system2", max_length=32)
+     from_c: str | None = Field(default=None, max_length=MAX_CONCEPT_CHARS)
+     to_c: str | None = Field(default=None, max_length=MAX_CONCEPT_CHARS)

--- 5. GenerateReq (lines 168-172)
  class GenerateReq(BaseModel):
-     text: str
-     max_tokens: int = 64
-     temperature: float = 0.8
-     task_type: str = "chat"
+     text: str = Field(..., min_length=1, max_length=MAX_TEXT_CHARS)
+     max_tokens: int = Field(64, ge=1, le=MAX_TOKENS_CAP)
+     temperature: float = Field(0.8, gt=TEMP_FLOOR, le=TEMP_CEIL)
+     task_type: str = Field("chat", max_length=32)

--- 6. ChatMessage (lines 175-180) — keep the role comment block verbatim
  class ChatMessage(BaseModel):
-     role: str  # "user" or "assistant" — matches ava/tokenizer.py's frozen
+     role: str = Field(..., max_length=32)  # "user" or "assistant" — matches ava/tokenizer.py's frozen
      #            <|user|>/<|assistant|> specials (ids 0-5); no <|tool|> special
      #            exists, so tool results are also sent as role="user" (see
      #            AgenticOS/ava_bridge.py, which owns that convention).
-     content: str
+     content: str = Field(..., max_length=MAX_TEXT_CHARS)

--- 7. ChatReq (lines 183-186)
  class ChatReq(BaseModel):
-     messages: list[ChatMessage]
-     max_tokens: int = 256
-     temperature: float = 0.8
+     messages: list[ChatMessage] = Field(..., min_length=1, max_length=MAX_MESSAGES)
+     max_tokens: int = Field(256, ge=1, le=MAX_TOKENS_CAP)
+     temperature: float = Field(0.8, gt=TEMP_FLOOR, le=TEMP_CEIL)
+
+     @model_validator(mode="after")
+     def _bound_total_prompt(self) -> "ChatReq":
+         total = sum(len(m.content) for m in self.messages)
+         if total > MAX_TEXT_CHARS:
+             raise ValueError(f"combined message content {total} chars > {MAX_TEXT_CHARS}")
+         return self

--- 8. AssistantReq (lines 189-193)
  class AssistantReq(BaseModel):
-     messages: list[ChatMessage]
-     max_steps: int = 4
-     max_tokens: int = 160
-     temperature: float = 0.7
+     messages: list[ChatMessage] = Field(..., min_length=1, max_length=MAX_MESSAGES)
+     max_steps: int = Field(4, ge=1, le=MAX_STEPS_CAP)
+     max_tokens: int = Field(160, ge=1, le=MAX_ASSISTANT_TOKENS_CAP)
+     temperature: float = Field(0.7, gt=TEMP_FLOOR, le=TEMP_CEIL)
+
+     @model_validator(mode="after")
+     def _bound_total_prompt(self) -> "AssistantReq":
+         total = sum(len(m.content) for m in self.messages)
+         if total > MAX_TEXT_CHARS:
+             raise ValueError(f"combined message content {total} chars > {MAX_TEXT_CHARS}")
+         return self

--- 9. WebSocket raw-text guard (Pydantic can't reach it; mechanical + safe). ws_stream, after `raw = await ws.receive_text()` (line 653)
      raw = await ws.receive_text()
+     if len(raw) > MAX_TEXT_CHARS:
+         await ws.close(code=1009, reason="prompt too large")  # 1009 = message too big
+         return
      prompt = (...)

Existing runtime checks stay: the `if not req.text or not req.text.strip()` / `if not req.messages` guards in /generate, /chat, /assistant still catch whitespace-only input (min_length=1 only rejects the truly empty string). The route-level min(req.max_tokens, 256/200) and min(req.max_steps, 6) clamps are now redundant but harmless — leave them.

NOT IN THIS DIFF — DoS mitigation (design recommendation for the RLock + no-KV-cache stall):
  a) Decouple liveness from the engine lock: make ServeEngine.stats() (and hence /health) read the cached ints/strings WITHOUT taking self._lock (a torn read across a hot-reload swap is harmless for a probe), or have /health return a static literal. Today /health blocks behind any in-flight generate.
  b) Don't hold self._lock for the whole token loop. Hot-reload rebinds self.model to a NEW object (it never mutates in place), so a generation can snapshot `model = self.model` under the lock, release it, and run the forward loop on that stable reference; the swap only needs the lock to rebind the attribute. Alternatively use a read/write lock (many concurrent reads = generations; exclusive write = weight swap).
  c) Add a KV cache to generate() so per-token cost is O(1) in sequence length instead of an O(L^2) full re-forward per token.
  d) Infra guards: a bounded concurrency semaphore around generation, a per-request wall-clock timeout, and a request-body size limit at uvicorn/reverse-proxy (bounds the base64 `image` blob and any body before Pydantic buffers it).
```

**Verify on factory box:**

```bash
Run on a box with torch + fastapi + pydantic (v2) installed. Validation is rejected BEFORE get_engine() runs, so no checkpoint is needed for the 422 tests.

  cd apps/ava-factory
  # 1. syntax + lint
  python -m py_compile server.py
  ruff check server.py            # if ruff is configured for the repo

  # 2. functional: assert the new 422s and that valid bodies still pass validation
  AVA_SKIP_ENGINE_BOOT=1 python - <<'PY'
  from fastapi.testclient import TestClient
  import server
  with TestClient(server.app) as c:
      # tiny positive temperature (the 500 crash) now rejected
      assert c.post('/generate', json={'text':'hi','temperature':1e-9}).status_code == 422
      # temperature <= 0 and > ceil rejected
      assert c.post('/generate', json={'text':'hi','temperature':0}).status_code == 422
      assert c.post('/generate', json={'text':'hi','temperature':9}).status_code == 422
      # oversized text rejected
      assert c.post('/generate', json={'text':'x'*20000}).status_code == 422
      # bad max_tokens rejected
      assert c.post('/generate', json={'text':'hi','max_tokens':10000}).status_code == 422
      assert c.post('/generate', json={'text':'hi','max_tokens':0}).status_code == 422
      # empty text rejected
      assert c.post('/generate', json={'text':''}).status_code == 422
      # chat: per-message and total-content caps
      assert c.post('/chat', json={'messages':[{'role':'user','content':'x'*20000}]}).status_code == 422
      assert c.post('/chat', json={'messages':[{'role':'user','content':'x'*9000}]*3}).status_code == 422  # total>16k
      assert c.post('/chat', json={'messages':[]}).status_code == 422
      # assistant: step/token caps
      assert c.post('/assistant', json={'messages':[{'role':'user','content':'hi'}],'max_steps':99}).status_code == 422
      # inspect: empty + oversized text
      assert c.post('/jspace/inspect', json={'text':''}).status_code == 422
      assert c.post('/jspace/inspect', json={'text':'x'*20000}).status_code == 422
      # VALID body passes validation (reaches the engine). Without a checkpoint this
      # 500s from get_engine(); the point is it is NOT a 422.
      assert c.post('/generate', json={'text':'hi','temperature':0.8,'max_tokens':16}).status_code != 422
      print('OK: all validation constraints enforced')
  PY

  # 3. (optional, needs a real AVA_CKPT) confirm the pre-fix crash is gone at the engine layer:
  #    before the fix, engine.generate('hi', temperature=1e-40) raises RuntimeError from torch.multinomial;
  #    after the fix the API layer returns 422 for that value so the engine is never reached.
```

### server.py — /jspace/intervene auth (🟡)

**File(s):** `/home/user/dottie/apps/ava-factory/server.py`

**Finding:** apps/ava-factory/server.py's mutating POST /jspace/intervene (line 518) is gated only by a client-supplied ?mode=research query param plus the server-wide ENABLE_JSPACE_WRITE env flag. With ENABLE_JSPACE_WRITE=1 and bind 0.0.0.0 (server.py:667 uvicorn.run host="0.0.0.0"), any unauthenticated network client can run interventions that mutate the model's internal workspace, causally change outputs, and append to runs/serve_audit.jsonl. A bearer dependency already exists in the same file — _require_assistant_token (lines 230-237) — but is attached ONLY to POST /assistant (line 396). It is the single mutating jspace route: /jspace/inspect, /jspace/safety, WS /jspace/stream, and the GET /jspace/eval_* routes are all read-only and out of scope for this finding.

**Rationale:** see proposed_change; Option B recommended

**Risk:** Low code risk, moderate operational/test risk. (1) Auth now runs before the write-gate, so an unauthenticated request to an intervene server returns 401/403 for the token instead of the old ENABLE_JSPACE_WRITE 403 message — anything asserting on that exact detail string for a write-ENABLED, no-token call breaks (test_intervene_403_without_research_mode still passes since it only checks status==403; the write-DISABLED path is unchanged). (2) Option B changes existing behavior: enabling writes without a token now fails closed, so test_intervene_ok_with_gate and the write-enabled branch of scripts/smoke_live_checks.py must be updated to set AVA_JSPACE_TOKEN and send the Bearer header, or CI/smoke will 403. (3) The dashboard viewer JS (server.py:132) calls /jspace/intervene with no Authorization header — the in-browser intervene buttons will 401 once a token is set; that UI is unchanged by this diff and would need a follow-up (prompt for/inject the token) if browser-driven interventions are still wanted. (4) Option A carries residual risk: default-OFF means forgetting the token leaves the route open — do not consider the finding closed under Option A unless deployment guarantees AVA_ASSISTANT_TOKEN is always set whenever writes are enabled. (5) No change to bind address; if the box must also be network-isolated, binding 127.0.0.1 is a complementary defense, not a substitute. Regressions are compile/lint clean: Depends/Header/HTTPException already imported; only `import hmac` is added for Option B.

**Proposed change:**

```diff
Two variants. Depends/Header/HTTPException are already imported (server.py:19). Option B additionally needs `import hmac` at the top (add beside `import json`/`import os`/`import re`).

========================================================================
OPTION A — literal reuse of the exact same /assistant dependency (minimal)
========================================================================
Only change the decorator on the intervene route:

--- server.py  (line 518)
-@app.post("/jspace/intervene")
+@app.post("/jspace/intervene", dependencies=[Depends(_require_assistant_token)])
 def intervene(req: InterveneReq, mode: str = Query("audit")):

Behavior: when AVA_ASSISTANT_TOKEN is set, /jspace/intervene requires
`Authorization: Bearer <token>` (401 missing, 403 wrong) BEFORE the write-gate
runs. Zero new env vars, zero test churn (existing tests set no token, so the
dependency no-ops and they still hit the ENABLE_JSPACE_WRITE 403). LIMITATION:
inherits the default-OFF behavior — if the operator sets ENABLE_JSPACE_WRITE=1
but forgets AVA_ASSISTANT_TOKEN, the route is still open to the network, i.e.
the finding's exact failure state is only partially closed.

========================================================================
OPTION B — RECOMMENDED: dedicated, fail-closed bearer dependency
========================================================================
Add `import hmac` at top, then add this function right after
_require_assistant_token (after line 238):

def _require_jspace_write_token(authorization: str | None = Header(None)) -> None:
    """Bearer auth for the MUTATING POST /jspace/intervene route.

    Mirrors _require_assistant_token's scheme but is FAIL-CLOSED for the write
    path: a dedicated AVA_JSPACE_TOKEN (falling back to AVA_ASSISTANT_TOKEN for
    single-token deployments) is REQUIRED whenever ENABLE_JSPACE_WRITE=1. If
    writes are enabled but no token is configured, the route refuses rather
    than accepting unauthenticated interventions. When writes are disabled the
    handler 403s anyway, so this dependency is a no-op there.
    """
    if os.getenv("ENABLE_JSPACE_WRITE", "0") != "1":
        return  # writes disabled; the handler will 403 on its own gate
    expected = os.environ.get("AVA_JSPACE_TOKEN") or os.environ.get(
        "AVA_ASSISTANT_TOKEN", ""
    )
    if not expected:
        raise HTTPException(
            status_code=403,
            detail="jspace write enabled but no AVA_JSPACE_TOKEN/AVA_ASSISTANT_TOKEN "
            "configured; refusing unauthenticated interventions",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="intervene requires a bearer token")
    if not hmac.compare_digest(authorization.split(" ", 1)[1].strip(), expected):
        raise HTTPException(status_code=403, detail="invalid jspace token")

Then change the route decorator (line 518):
-@app.post("/jspace/intervene")
+@app.post("/jspace/intervene", dependencies=[Depends(_require_jspace_write_token)])
 def intervene(req: InterveneReq, mode: str = Query("audit")):

Document the new var in apps/ava-factory/.env.example (append near ENABLE_JSPACE_WRITE):
# Bearer token required for POST /jspace/intervene when ENABLE_JSPACE_WRITE=1
# (falls back to AVA_ASSISTANT_TOKEN). With writes enabled and NO token, the
# route refuses (fail-closed). Send as: Authorization: Bearer <token>
AVA_JSPACE_TOKEN=

Test updates required by Option B (tests/test_server_endpoints.py):
 - test_intervene_ok_with_gate (line 173): add
     monkeypatch.setenv("AVA_JSPACE_TOKEN", "t")
   and pass headers={"Authorization": "Bearer t"} on the POST.
 - test_intervene_403_without_write_flag (154) and _without_research_mode (164)
   still assert status 403 and continue to pass (no token set: the first hits
   the writes-disabled early-return then the handler's ENABLE_JSPACE_WRITE 403;
   the second now 403s at the dependency for the missing token — status is
   still 403). Add three new tests: missing-token->401, wrong-token->403,
   valid-token->200, and write-enabled+no-token->403 (fail-closed).
 - scripts/smoke_live_checks.py: the WRITE-ENABLED intervene probe (around
   line 507, sets ENABLE_JSPACE_WRITE=1) must send Authorization: Bearer
   $AVA_JSPACE_TOKEN; the write-DISABLED intervene-403 probe is unaffected.
```

**Verify on factory box:**

```bash
Run from apps/ava-factory/. torch is NOT needed — the endpoint suite runs with AVA_SKIP_ENGINE_BOOT=1 and a fake engine; only fastapi is required.

# 0. Syntax/AST check (works even with no deps installed):
python -c "import ast; ast.parse(open('server.py').read()); print('parse ok')"

# 1. Endpoint regression suite (needs fastapi; no checkpoint, no torch):
AVA_SKIP_ENGINE_BOOT=1 python -m pytest tests/test_server_endpoints.py -q
# Expect the intervene tests green after applying the Option B test edits above.

# 2. Auth-only curl checks (no checkpoint needed — the Depends runs before the
#    handler, so 401/403 are returned regardless of engine availability).
#    Boot a write-enabled server with a token:
AVA_SKIP_ENGINE_BOOT=1 ENABLE_JSPACE_WRITE=1 AVA_JSPACE_TOKEN=secret \
  python -m uvicorn server:app --host 127.0.0.1 --port 8000 &
sleep 2
# a) missing token -> 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  'http://127.0.0.1:8000/jspace/intervene?mode=research' \
  -H 'Content-Type: application/json' -d '{"from":"spider","to":"ant","text":"legs"}'   # expect 401
# b) wrong token -> 403
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  'http://127.0.0.1:8000/jspace/intervene?mode=research' \
  -H 'Authorization: Bearer wrong' -H 'Content-Type: application/json' \
  -d '{"from":"spider","to":"ant","text":"legs"}'                                        # expect 403
# c) correct token -> passes auth (200 with a real AVA_CKPT; ~503/500 engine
#    error under SKIP_ENGINE_BOOT — the point is it is NO LONGER 401/403):
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  'http://127.0.0.1:8000/jspace/intervene?mode=research' \
  -H 'Authorization: Bearer secret' -H 'Content-Type: application/json' \
  -d '{"from":"spider","to":"ant","text":"legs"}'
kill %1

# 3. Fail-closed check (Option B): writes enabled, NO token configured -> 403.
AVA_SKIP_ENGINE_BOOT=1 ENABLE_JSPACE_WRITE=1 \
  python -m uvicorn server:app --host 127.0.0.1 --port 8001 & sleep 2
curl -s -X POST 'http://127.0.0.1:8001/jspace/intervene?mode=research' \
  -H 'Content-Type: application/json' -d '{"from":"spider","to":"ant"}'   # expect 403 + "no AVA_JSPACE_TOKEN" detail
kill %1

# 4. Full 200 path (needs a real nano checkpoint / AVA_CKPT):
AVA_CKPT=runs/chat/ava_nano_chat.pt ENABLE_JSPACE_WRITE=1 AVA_JSPACE_TOKEN=secret \
  python -m uvicorn server:app --host 127.0.0.1 --port 8002 & sleep 5
curl -s -X POST 'http://127.0.0.1:8002/jspace/intervene?mode=research' \
  -H 'Authorization: Bearer secret' -H 'Content-Type: application/json' \
  -d '{"from":"spider","to":"ant","text":"webs"}' | python -m json.tool   # expect changed:true, audit_logged:true
kill %1
```

### Dockerfile + requirements — shipable slim image + pin convergence (🔴🟡)

**File(s):** `apps/ava-factory/Dockerfile (primary, slim serve image); apps/ava-factory/docker/requirements.cpu.txt + docker/requirements.gpu.txt (exact-pin sources); apps/ava-factory/requirements.txt (loose, to be demoted); new apps/ava-factory/docker/requirements.serve.txt; .github/workflows/ci.yml (add smoke job)`

**Finding:** TWO coupled defects in apps/ava-factory that ship a slim serve image that cannot boot, plus dependency drift across 4 universes.

(a) MISSING COPY (boot crash, red). apps/ava-factory/Dockerfile (the slim two-stage "ava serve" image, header "Stage 8 self-host package") COPYs ava/ (line 38) but never dottie/. Since the Ava->Dottie rename, ava/__init__.py is a pure compat shim whose FIRST executable line is `from dottie import *` — so ava/ without dottie/ is a dangling shim that itself ImportErrors. Independently, server.py:23 does a top-level `from dottie.serve_engine import get_engine`, so `uvicorn server:app` dies at boot with `ModuleNotFoundError: No module named 'dottie'` before it ever binds :8000. The sibling docker/Dockerfile.cpu (line 22) and docker/Dockerfile.gpu (line 30) both COPY dottie/ *before* ava/ and even carry a comment ("without dottie/ every service dies at import") — the slim Dockerfile simply never got that line. IMPORTANT (beyond the stated finding): dottie/ alone is necessary but NOT sufficient. Boot chain is server.py:23 -> dottie/serve_engine.py:41 `from dottie.model import build_model` -> dottie/model.py:12 `from model_1b import DottieModel1B, apply_rope_scaling`. model_1b.py is a TOP-LEVEL module the GPU image copies (docker/Dockerfile.gpu:34) but the slim Dockerfile omits — so the image needs BOTH `COPY dottie/` AND `COPY model_1b.py` to import. (evals/ at line 39 is already copied and reaches ava.config/ava.model/multi_jspace_module — all satisfied once dottie/ + the already-present ava/ + multi_jspace_module.py exist.)

(b) FOUR dependency universes (yellow). Root pyproject.toml explicitly excludes apps/ava-factory from the uv workspace ("requirements.txt/Docker-driven install, no pyproject; untouched"), so the only pins are whatever each file hardcodes — and four sets disagree: (1) apps/ava-factory/requirements.txt = loose `>=` bounds, full training+curation+serve kitchen-sink, referenced by NO Dockerfile (a dangling dev manifest); (2) docker/requirements.cpu.txt = exact pins, curation subset, "verified on host", consumed by Dockerfile.cpu; (3) docker/requirements.gpu.txt = exact pins, trainer/server subset, consumed by Dockerfile.gpu; (4) the slim Dockerfile's inline `pip install fastapi>=0.110 uvicorn[standard]>=0.27 pydantic>=2 numpy pyyaml safetensors tokenizers httpx` (lines 27-29) = a FOURTH loose universe hardcoded in a RUN layer. Concrete conflicts on shared packages: fastapi (gpu 0.111.0 / slim >=0.110 / req.txt >=0.110.0), uvicorn (gpu 0.30.1 / slim >=0.27), pydantic (gpu 2.7.4 / slim >=2 / req.txt >=2.6.0), tokenizers (cpu+gpu 0.19.1 / slim unpinned / req.txt >=0.15.0), numpy (cpu+gpu 1.26.4 / slim unpinned), PyYAML (cpu+gpu 6.0.1 / slim unpinned), safetensors (gpu 0.4.3 / slim unpinned). httpx is requested ONLY by the slim inline block and is absent from every pinned file (a pin gap). A slim image built today resolves fastapi/uvicorn/pydantic to whatever PyPI serves that day, silently diverging from the pinned trainer/server image the checkpoints were validated against.

**Rationale:** DIFF 1 (COPY): server.py:23 is a module-top-level import, executed during `uvicorn server:app` app-loading before the socket binds — the image is 100% dead-on-arrival, not degraded. The fix is exactly the pattern the two sibling Dockerfiles already use and comment on; the slim one is the outlier that missed the rename. Adding model_1b.py too is not gold-plating: dottie/model.py:12 hard-imports it at module load and dottie.model is on serve_engine's import path, so an image with dottie/ but no model_1b.py still ModuleNotFounds one frame deeper. Placing `COPY dottie/` before `COPY ava/` matters because ava/__init__.py runs `from dottie import *` at import; source order dottie->ava mirrors Dockerfile.gpu. Build context is the ava-factory root (Dockerfile header: `docker build -t ava-serve .`) and dottie/ + model_1b.py both exist there, so the COPYs resolve.

DIFFs 2-4 (convergence): the design names the exact-pin docker/requirements.*.txt files as the single source of truth for versions and makes every other consumer REFERENCE them instead of re-declaring versions. The slim Dockerfile stops being a 4th universe (DIFF 3 turns its inline loose block into `-r requirements.serve.txt`, matching how Dockerfile.cpu/gpu already install). requirements.serve.txt (DIFF 2) reuses the *exact same* pins already host-verified in gpu.txt/cpu.txt so a shared package has one value repo-wide (fastapi 0.111.0 everywhere, tokenizers 0.19.1 everywhere) — the reproducibility property the checkpoints were validated under. The dangling top-level requirements.txt (DIFF 4) is demoted from a competing loose universe to an additive dev manifest that `-r`-includes the pinned files, so it can no longer silently disagree on fastapi/numpy/pydantic. cpu.txt stays the canonical registry and its verified pins (numpy==1.26.4, PyYAML==6.0.1, tokenizers==0.19.1, tqdm==4.66.4, pytest==8.2.2) are the values every other file aligns to. DIFF 5 gives it teeth: a build-the-image smoke would have caught the missing COPY, whereas the existing `python -c import` CI step tests the source tree, not the shipped image.

**Risk:** - model_1b.py is a large torch module; confirm no further top-level import of a file the slim image still omits. I traced serve_engine -> dottie.model -> model_1b; grep shows dottie/* also references j_space_module and multi_jspace_module — multi_jspace_module IS copied (Dockerfile:40), j_space_module is NOT but is not on the serve boot path today. If any lazy route handler imports dottie.grow/dottie.jlosses/dottie.train, those pull model_1b/multi_jspace_module (both then present) — re-verify the full route set on a box.
- torch==2.4.0 in DIFF 3: the cu124 index has it (gpu.txt uses it) but the CPU index build tag must be confirmed; if it fails to resolve on the cpu index, fall back to unpinned `torch` for the cpu variant. Cross-index exact-pinning is the one thing the pinned-file model can't fully guarantee.
- httpx==0.27.0 is the only NET-NEW pin (was unpinned, only in the slim inline block); 0.27.0 is plausible but NOT host-verified like the others — resolve the exact patch on the factory box. Also confirm httpx is actually needed (server.py uses urllib.request at line 444; httpx may be transitive/optional) — if unused, drop it rather than pin it.
- DIFF 4's `-r docker/requirements.gpu.txt` drags bitsandbytes (a CUDA-oriented wheel) into a plain `pip install -r requirements.txt` on a CPU-only dev box; it installs on CPU but is inert. If objectionable, split into requirements-dev-cpu.txt / requirements-dev-gpu.txt each including the matching pinned file.
- Do NOT make the slim serve image `-r docker/requirements.cpu.txt` directly: cpu.txt carries datasets/pyarrow/fsspec (curation universe) which would bloat the deliberately-slim serve image and defeat specs/07. That is why DIFF 2 introduces a scoped serve pin-file sharing cpu/gpu's values rather than including cpu.txt wholesale.
- /health calls get_engine().stats() which loads the checkpoint; the CI /health step needs a nano ckpt fixture (AVA_CKPT default /app/runs/chat/ava_nano_chat.pt, not baked in). If no fixture in CI, keep only the `python -c "import server"` import-smoke — it already fails on the missing COPY without a checkpoint.
- I could not build the image or run pip here (no torch/fastapi/docker in this env; ava-factory is uv-workspace-excluded) — all version-resolution and boot claims must be confirmed on a box with torch+fastapi+docker.

**Proposed change:**

```diff
=== DIFF 1: apps/ava-factory/Dockerfile — ship dottie/ (named fix) + model_1b.py (required companion). Insert BEFORE the `COPY ava/` line so the shim's target exists, mirroring docker/Dockerfile.gpu:30. ===
  WORKDIR /app
  COPY --from=builder /opt/venv /opt/venv
+ # dottie/ is the real package (Ava->Dottie rename); ava/ is a `from dottie import *`
+ # shim — without dottie/ server.py:23 dies with ModuleNotFoundError at boot.
+ COPY dottie/ /app/dottie/
  COPY ava/ /app/ava/
  COPY evals/ /app/evals/
+ # dottie/model.py imports top-level model_1b (build_model -> DottieModel1B); required to boot.
+ COPY model_1b.py /app/model_1b.py
  COPY multi_jspace_module.py /app/multi_jspace_module.py
  COPY server.py /app/server.py
(Optional parity with Dockerfile.gpu:34: also `COPY j_space_module.py /app/j_space_module.py` — not on the serve boot path today but cheap insurance if a route lazy-imports it.)

=== DIFF 2: new file apps/ava-factory/docker/requirements.serve.txt — the slim serve image's pinned deps, every shared pin IDENTICAL to the exact-pin universe so no version is declared twice with different values. ===
# Slim single-process serve image (specs/07). Pins are the single source of truth;
# they MUST match docker/requirements.cpu.txt / docker/requirements.gpu.txt.
# torch is installed separately from ${TORCH_INDEX} (cpu default, cu124 opt-in) — see Dockerfile.
fastapi==0.111.0          # == gpu.txt
uvicorn[standard]==0.30.1 # == gpu.txt
pydantic==2.7.4           # == gpu.txt
safetensors==0.4.3        # == gpu.txt
tokenizers==0.19.1        # == cpu.txt & gpu.txt (hash-compatible packed shards)
numpy==1.26.4             # == cpu.txt & gpu.txt
PyYAML==6.0.1             # == cpu.txt & gpu.txt
httpx==0.27.0             # NET-NEW pin (was only in the slim inline block, unpinned everywhere) — confirm on factory box

=== DIFF 3: apps/ava-factory/Dockerfile — stop inlining the 4th universe; reference the pinned file (mirrors Dockerfile.cpu:17-18 / Dockerfile.gpu:24-26). torch stays a separate layer from the index. ===
  # Torch from the chosen index; remaining deps pinned via requirements.serve.txt.
- RUN pip install --no-cache-dir \
-         "torch" --index-url "${TORCH_INDEX}" \
-  && pip install --no-cache-dir \
-         "fastapi>=0.110" "uvicorn[standard]>=0.27" "pydantic>=2" \
-         "numpy" "pyyaml" "safetensors" "tokenizers" "httpx"
+ COPY docker/requirements.serve.txt /tmp/requirements.serve.txt
+ RUN pip install --no-cache-dir "torch==2.4.0" --index-url "${TORCH_INDEX}" \
+  && pip install --no-cache-dir -r /tmp/requirements.serve.txt
(torch==2.4.0 matches docker/requirements.gpu.txt's cu124 pin so cpu/gpu serve share one torch minor; drop ==2.4.0 back to "torch" if the cpu index lacks that exact build — verify on box. NOTE build context: the slim image's context is the ava-factory root, so `COPY docker/requirements.serve.txt` resolves as apps/ava-factory/docker/requirements.serve.txt.)

=== DIFF 4: apps/ava-factory/requirements.txt — demote from a parallel version universe to an additive dev/full-install manifest that INCLUDES the pinned files, so it can no longer drift on shared packages. Replace the head of the file: ===
+ # Single source of truth for pinned versions lives in docker/requirements.*.txt.
+ # This file only ADDS the heavier training/curation deps needed on a full dev box.
+ -r docker/requirements.cpu.txt      # datasets/pyarrow/hf-hub/tokenizers/numpy/pyyaml/regex/... (exact)
+ -r docker/requirements.gpu.txt      # fastapi/uvicorn/pydantic/safetensors/bitsandbytes/... (exact)
+ # torch: install from the appropriate index out-of-band (cpu or cu124), not pinned here.
+ # --- training/curation-only extras (still to be exact-pinned; keep >= until host-verified) ---
  deepspeed>=0.14.0
  transformers>=4.40.0
  accelerate>=0.28.0
  wandb>=0.16.0
  dolma
  nemo-curator
  einops
  chonkie>=1.4.1
  tiktoken>=0.6.0
  psutil>=5.9.0
  webdataset>=0.2.62
  prefect==3.4.0
  pandas>=2.0.0
  boto3>=1.34.0
  scikit-learn>=1.3.0
  # REMOVED from this file (now inherited from the pinned -r includes, no longer re-declared loose):
  #   torch, tokenizers, datasets, huggingface_hub, fastapi, uvicorn, numpy, pyyaml,
  #   regex, datasketch, pydantic, safetensors, websockets, pyarrow, tqdm

=== DIFF 5 (CI SMOKE SUGGESTION): .github/workflows/ci.yml — add a slim-image build + boot/health smoke job. CI today only does `python -c import` (ci.yml:47-49) against the SOURCE TREE, which passes despite the bug because it never builds the image. ===
+  slim-serve-image-smoke:
+    runs-on: ubuntu-latest
+    steps:
+      - uses: actions/checkout@v4
+      - name: Build slim serve image (cpu)
+        run: docker build -t ava-serve -f apps/ava-factory/Dockerfile apps/ava-factory
+      - name: Boot import smoke (catches ModuleNotFoundError, no ckpt needed)
+        run: docker run --rm ava-serve python -c "import server; print('server import ok')"
+      - name: /health smoke (needs a nano ckpt fixture mounted at AVA_CKPT)
+        run: |
+          docker run --rm -d --name ava-serve-smoke -p 8000:8000 \
+            -v "$PWD/apps/ava-factory/runs:/app/runs" ava-serve
+          ok=""; for i in $(seq 1 30); do curl -fsS http://localhost:8000/health && { ok=1; break; }; sleep 2; done
+          docker logs ava-serve-smoke | tail -30
+          docker rm -f ava-serve-smoke
+          test -n "$ok"
(Gate on `paths: ['apps/ava-factory/**']` so it only runs when factory image inputs change. The import-smoke step alone is the high-value guard — it fails fast on any missing COPY without needing a checkpoint.)
```

**Verify on factory box:**

```bash
cd apps/ava-factory

# --- 1. Reproduce the current bug (expect FAILURE on unpatched tree) ---
docker build -t ava-serve-broken -f Dockerfile .
docker run --rm ava-serve-broken python -c "import server"
#   EXPECT (before fix): ModuleNotFoundError: No module named 'dottie'

# --- 2. After applying DIFFs 1-3, rebuild (cpu default index) ---
docker build -t ava-serve -f Dockerfile .
# CUDA variant:
# docker build -t ava-serve-cu124 --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124 -f Dockerfile .

# --- 3. Boot import smoke: exercises server.py:23 -> dottie.serve_engine -> dottie.model -> model_1b, NO checkpoint needed ---
docker run --rm ava-serve python -c "import server; print('server import ok')"
#   EXPECT: 'server import ok', zero ModuleNotFoundError

# --- 4. Full boot + /health (needs a nano ckpt at AVA_CKPT) ---
docker run --rm -d --name ava-serve-smoke -p 8000:8000 \
  -v "$PWD/runs:/app/runs" -e AVA_CKPT=/app/runs/chat/ava_nano_chat.pt ava-serve
for i in $(seq 1 30); do curl -fsS http://localhost:8000/health && break; sleep 2; done
#   EXPECT: JSON {"status":"ok","ckpt":...,"params":...,"vocab":...}
docker logs ava-serve-smoke | tail -30   # must contain NO ModuleNotFoundError / ImportError
docker rm -f ava-serve-smoke

# --- 5. Convergence checks: pinned files agree on shared packages, and requirements.txt resolves ---
grep -E '^(fastapi|uvicorn|pydantic|tokenizers|numpy|PyYAML|safetensors)' \
  docker/requirements.cpu.txt docker/requirements.gpu.txt docker/requirements.serve.txt
#   EXPECT: identical version for every package appearing in more than one file
python -m venv /tmp/req-check && /tmp/req-check/bin/pip install --dry-run -r requirements.txt
#   EXPECT: pip resolves with NO version-conflict error (proves the -r includes are compatible)

# --- 6. Confirm the torch pin exists on the CPU index (see risk note) ---
pip index versions torch --index-url https://download.pytorch.org/whl/cpu | grep -q 2.4.0 \
  && echo "torch==2.4.0 available on cpu index" || echo "FALL BACK to unpinned torch for cpu variant"

# --- 7. Confirm httpx pin / need ---
pip index versions httpx | head -3                 # pick the exact patch for requirements.serve.txt
docker run --rm ava-serve python -c "import httpx; print(httpx.__version__)"   # confirm it installed
```

