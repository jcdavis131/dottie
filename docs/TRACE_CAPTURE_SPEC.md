# TRACE_CAPTURE_SPEC — real pair-programming trace capture

**Status:** implemented on branch `scout/dottie-trace-capture` (not merged).
**Module:** `pipeline/session_capture.py` (stdlib-only). **Hook:** `dottie run --capture`.
**Schema:** `pair-session-1.0.0`. **Default sink:** `reports/pair_sessions.jsonl`.

This is the data-flywheel entry point for Dottie's closed loop: the bridge between
*what the user actually did with the pair programmer* and the training pipeline
(`collector.py` → `grpo_collect.py` → GRPO). No real sessions captured = no real
preference signal = the loop trains on lab data forever.

---

## 1. Design principles

| Principle | How it is enforced |
|---|---|
| Opt-in only | `capture_enabled()` is false unless `DOTTIE_TRACE_CAPTURE=1` or `--capture`. Default = read-only, zero behavior change, nothing written. |
| Privacy-first | PII redaction runs before persistence (email, bearer/token/api-key, long secrets, IPv4). `register_redactor()` adds project-specific patterns. |
| Never fabricate | `rl_return` is set ONLY from recorded signals (accepted/rejected/verdict). Unknown → `None`, and the row is *skipped* from telemetry export. No invented rewards. |
| Honest 503 | If the harness is unreachable, the session closes with `status="error"`, `errorClass="harness_unreachable"` and the original exception is re-raised. Same honesty contract as the rest of Dottie. |
| Capture never breaks the flow | All write paths are fail-open for capture (exceptions logged to stderr, record dropped), fail-closed for data (nothing half-written or invented). |
| 7-field checkpoint compatible | Every record carries `nodeId, agentId, attempt, latency_ms, tokens_est, status, errorClass` — same convention as the timeline triple-write. |

---

## 2. Schema (`pair-session-1.0.0`)

One JSON object per line, append-only:

```jsonc
{
  "session_id": "a3f9c1d2e4b5",          // uuid12, groups multi-turn sessions
  "trace_id": "sess-a3f9c1d2e4b5-9f2c…", // dedup/grouping key
  "schema_version": "pair-session-1.0.0",
  "ts": 1789079000.0,
  "user_id_hash": "7c9e…",               // sha16(USER), never raw identity
  "consent": true,
  "consent_source": "env | cli-flag | none",
  "prompt": "refactor login.py…",        // REDACTED before write
  "assistant_actions": [
    {"action": "edit|tool|message|run",
     "summary": "edited login.py",       // redacted
     "tool_calls": [{"tool": "edit_file", "args": {...}}]}  // redacted
  ],
  "tool_calls": [/* flattened, redacted */],
  "user_corrections": ["no, keep the old auth flow"],  // redacted
  "signals": {
    "accepted": true, "rejected": false, "edited_after": false,
    "correction_count": 1, "followup": false
  },
  "final_outcome": "success|partial|abandoned|error|unknown",
  "verdict": "pass|fail|unknown",        // recorded, never invented
  "rl_return": 1.0,                      // from signals only; null = unknown
  "nodeId": "dottie-cli", "agentId": "session_capture", "attempt": 1,
  "latency_ms": 1234, "tokens_est": 567,
  "status": "ok|error", "errorClass": null,
  "extra": {"redactors": ["email","bearer","long_secret","ipv4"]}
}
```

`rl_return` derivation (in `SessionCapture._derive_return`):
- `signals.accepted == true` → `1.0`
- `signals.rejected == true` → `0.0`
- else `verdict == "pass"` → `1.0`, `verdict == "fail"` → `0.0`
- otherwise → `None` (honest unknown)

---

## 3. API

```python
from session_capture import (
    SessionCapture, capture_session, run_with_capture,
    export_to_telemetry, register_redactor, redact,
)

# One-shot wrapper (used by the CLI hook)
record = run_with_capture(prompt, run_fn, opt_in=True)

# Interactive / multi-turn sessions
with capture_session("help me refactor X", opt_in=True) as cap:
    rec = cap.begin("help me refactor X")
    cap.log_action(rec, "edit", "edited foo.py", [{"tool": "edit_file", "args": {...}}])
    cap.log_correction(rec, "no, use the old helper")
    cap.log_signal(rec, accepted=True)
    cap.end(rec, outcome="success", verdict="pass", latency_ms=2100, tokens_est=800)

# Feed-forward into training
export_to_telemetry("reports/pair_sessions.jsonl", "reports/dottie_telemetry.jsonl")
```

CLI:

```bash
# default: no capture, existing behavior unchanged
python -m dottie run "explain this traceback"

# opt-in capture of this session
DOTTIE_TRACE_CAPTURE=1 python -m dottie run "explain this traceback" --capture

# inspect / export
python pipeline/session_capture.py --stats
python pipeline/session_capture.py --export
```

---

## 4. Feed-forward into the training pipeline

```
reports/pair_sessions.jsonl            (append-only, consented, redacted)
        │ export_to_telemetry()
        ▼
reports/dottie_telemetry.jsonl         (rows: prompt, completion, trace_id,
                                        rl_return, entropy, verdict,
                                        source="pair_session_real")
        │  existing pipeline/grpo_collect.py  (unchanged)
        ▼
runs/grpo_pref/{trace_bank.jsonl, pref_pairs.jsonl, grpo_group_stats.jsonl}
        │  existing TraceFactory.emit_pref_pairs()  (unchanged)
        ▼
GRPO update (Forge GPU lane)
```

Only rows with a recorded `rl_return` are exported — sessions with unknown
outcome stay in `pair_sessions.jsonl` for audit but never become training data.

---

## 5. Privacy & retention

- Capture is opt-in per session; `consent` + `consent_source` are stored with
  every record so downstream can prove provenance.
- User identity is stored as a hash only. Prompts, actions, corrections, and
  tool args pass through redaction before anything hits disk.
- Deletion: records are one-per-line JSONL; a session can be purged by
  `session_id` with a line filter — no index to rebuild, no side effects.
- Do NOT lower the bar: adding new fields requires the same redaction pass and
  an explicit schema-version bump (`SCHEMA_VERSION`).

---

## 6. What's next (not in this branch)

- Multi-turn capture in `repl` / `agent` commands (session API already supports it).
- Accept/reject wiring from the real UX surface (thumbs up/down, "apply" vs
  "dismiss") → `log_signal`.
- Retention cron: age-out raw sessions after N days, keep aggregates.
