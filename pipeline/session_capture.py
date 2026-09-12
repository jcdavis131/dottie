"""dottie/pipeline/session_capture.py — REAL pair-programming session capture.

The data-flywheel entry point: captures REAL interactive sessions (user prompt,
assistant actions, tool calls, user corrections like "no, do X", accept/reject
signals, final outcome, latency, tokens) into append-only JSONL.

Privacy-first rules (hard):
- OPT-IN ONLY. Capture is disabled unless DOTTIE_TRACE_CAPTURE=1 in the
  environment OR --capture is passed on the CLI. Default is read-only: nothing
  is written, nothing changes.
- PII redaction hooks run before anything is persisted. Secrets are redacted
  by default; callers can register extra redactors.
- NEVER fabricate. If the harness/backend is unreachable the record is marked
  status="error", errorClass="harness_unreachable" (honest 503 semantics) and
  rl_return stays None. No invented rewards.
- Capture failures must never break the user flow: use capture_session() as a
  context manager; on any internal error the record is dropped and the error is
  surfaced on stderr only.

Stdlib-only. Feeds forward into:
  reports/pair_sessions.jsonl -> export_to_telemetry() ->
  reports/dottie_telemetry.jsonl (consumed by pipeline/grpo_collect.py)

Timeline compatibility: every persisted record carries the mandatory 7-field
checkpoint {nodeId, agentId, attempt, latency_ms, tokens_est, status,
errorClass}.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

SCHEMA_VERSION = "pair-session-1.0.0"
DEFAULT_OUT = "reports/pair_sessions.jsonl"
ENV_FLAG = "DOTTIE_TRACE_CAPTURE"

# 7-field checkpoint keys required by the timeline triple-write convention
CHECKPOINT_FIELDS = (
    "nodeId", "agentId", "attempt", "latency_ms", "tokens_est", "status",
    "errorClass",
)


# ---------------------------------------------------------------------------
# PII redaction
# ---------------------------------------------------------------------------

# Default redactors: (name, compiled regex, replacement). Applied in order.
_DEFAULT_REDACTORS: List[tuple] = [
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    ("bearer", re.compile(r"(?i)\b(bearer|token|api[_-]?key|secret|passwd|password)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    ("long_secret", re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "[SECRET?]"),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP]"),
]

# Extra redactors registered by the caller (name -> (regex, replacement)).
_extra_redactors: Dict[str, tuple] = {}


def register_redactor(name: str, pattern: str, replacement: str = "[REDACTED]") -> None:
    """Register an additional PII redactor applied to all text fields."""
    _extra_redactors[name] = (re.compile(pattern), replacement)


def _contract_redact(text: str) -> str | None:
    """Stronger redactor from the dottie-loop contract (spec §16/§17), best-effort.

    Returns the redacted text, or None when the contract package is not
    importable — the lane then falls back to its own default patterns below.
    Never a hard dependency: no ImportError escapes at module load or at call.
    """
    try:
        from dottie_loop.capture import redact_text
    except ImportError:
        try:
            sys.path.insert(
                0, str(Path(__file__).resolve().parent.parent / "packages" / "dottie-loop"))
            from dottie_loop.capture import redact_text
        except ImportError:
            return None
    return redact_text(text)[0]


def redact(text: str) -> str:
    """Run every registered redactor over text. Non-str input passes through.

    When the dottie-loop contract package is importable its redactor runs first
    (email / bearer / key-shaped / IPv4 / IPv6 / entropy-checked long tokens,
    with a per-detector report); caller-registered hooks still apply after.
    Otherwise the lane's own default patterns are used — same behavior as before.
    """
    if not isinstance(text, str):
        return text
    contracted = _contract_redact(text)
    if contracted is not None:
        out = contracted
    else:
        out = text
        for _name, rx, repl in _DEFAULT_REDACTORS:
            out = rx.sub(repl, out)
    for _name, (rx, repl) in _extra_redactors.items():
        out = rx.sub(repl, out)
    return out


def _redact_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: _redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_redact_obj(v) for v in obj]
    return obj


def sha16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Consent gate
# ---------------------------------------------------------------------------

def capture_enabled(flag: Optional[bool] = None) -> bool:
    """True only with explicit opt-in: CLI --capture flag or env var."""
    if flag is not None:
        return bool(flag)
    return os.environ.get(ENV_FLAG, "") in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Record schema
# ---------------------------------------------------------------------------

@dataclass
class SessionRecord:
    """One real pair-programming session, append-only."""

    session_id: str
    trace_id: str
    schema_version: str = SCHEMA_VERSION
    ts: float = 0.0
    user_id_hash: str = "anon"
    consent: bool = False
    consent_source: str = "none"          # "env" | "cli-flag" | "none"
    prompt: str = ""                       # redacted
    assistant_actions: List[Dict[str, Any]] = field(default_factory=list)
    # assistant_actions entries: {"action": "edit"|"tool"|"message"|"run",
    #   "summary": <redacted>, "tool_calls": [{"tool", "args"}] (redacted)}
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    user_corrections: List[str] = field(default_factory=list)  # redacted, e.g. "no, do X"
    signals: Dict[str, Any] = field(default_factory=dict)
    # signals: {"accepted": bool, "rejected": bool, "edited_after": bool,
    #           "correction_count": int, "followup": bool}
    final_outcome: str = "unknown"         # "success"|"partial"|"abandoned"|"error"|"unknown"
    verdict: str = "unknown"               # "pass"|"fail"|"unknown" (recorded, never invented)
    rl_return: Optional[float] = None      # set ONLY from recorded signals; None = unknown
    # 7-field checkpoint (mandatory)
    nodeId: str = ""
    agentId: str = ""
    attempt: int = 1
    latency_ms: int = 0
    tokens_est: int = 0
    status: str = "unknown"                # "ok" | "error"
    errorClass: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)


class SessionCapture:
    """Append-only writer. Use capture_session() context manager in practice."""

    def __init__(self, out: Path | str = DEFAULT_OUT, enabled: Optional[bool] = None,
                 node_id: str = "dottie-cli", agent_id: str = "session_capture"):
        self.enabled = capture_enabled(enabled)
        self.consent_source = (
            "cli-flag" if enabled else ("env" if self.enabled else "none")
        )
        self.out = Path(out)
        self.node_id = node_id
        self.agent_id = agent_id

    # -- lifecycle ---------------------------------------------------------
    def begin(self, prompt: str, user: Optional[str] = None) -> SessionRecord:
        now = time.time()
        sid = uuid.uuid4().hex[:12]
        return SessionRecord(
            session_id=sid,
            trace_id=f"sess-{sid}-{sha16(prompt or '')}",
            ts=now,
            user_id_hash=sha16(user or os.environ.get("USER", "anon"))[:12],
            consent=self.enabled,
            consent_source=self.consent_source,
            prompt=redact(prompt or ""),
            nodeId=self.node_id,
            agentId=self.agent_id,
            status="ok",
        )

    def log_action(self, rec: SessionRecord, action: str,
                   summary: str = "", tool_calls: Optional[List[Dict[str, Any]]] = None) -> None:
        rec.assistant_actions.append({
            "action": action,
            "summary": redact(summary),
            "tool_calls": _redact_obj(tool_calls or []),
        })
        rec.tool_calls.extend(_redact_obj(tool_calls or []))

    def log_correction(self, rec: SessionRecord, text: str) -> None:
        rec.user_corrections.append(redact(text))
        n = rec.signals.get("correction_count", 0)
        rec.signals["correction_count"] = n + 1

    def log_signal(self, rec: SessionRecord, **signals: Any) -> None:
        rec.signals.update(signals)

    def end(self, rec: SessionRecord, outcome: str = "unknown",
            verdict: str = "unknown", latency_ms: int = 0,
            tokens_est: int = 0, status: str = "ok",
            error_class: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Finalize and append the record. Returns the persisted dict or None.

        Never raises for capture-internal reasons; returns None and logs to
        stderr on write failure so the user flow is never broken.
        """
        if not self.enabled:
            return None  # read-only by default
        rec.final_outcome = outcome
        rec.verdict = verdict
        rec.latency_ms = latency_ms
        rec.tokens_est = tokens_est
        rec.status = status
        rec.errorClass = error_class
        rec.rl_return = self._derive_return(rec)
        rec.extra["redactors"] = (
            [n for n, _, _ in _DEFAULT_REDACTORS] + list(_extra_redactors.keys())
        )
        payload = rec.to_json()
        # checkpoint sanity: all 7 fields present
        for k in CHECKPOINT_FIELDS:
            if k not in payload:
                payload[k] = None
        try:
            self.out.parent.mkdir(parents=True, exist_ok=True)
            # O_APPEND write is atomic per-line for readers; fsync for durability
            with open(self.out, "ab") as f:
                line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:  # fail-open for capture, fail-closed for data
            print(f"[session_capture] dropped record (write failed): {e}", file=sys.stderr)
            return None
        return payload

    # -- reward derivation (honest: recorded signals only) ------------------
    @staticmethod
    def _derive_return(rec: SessionRecord) -> Optional[float]:
        """Map RECORDED signals to an rl_return. None when unknown — never invented."""
        sig = rec.signals
        if sig.get("accepted") is True:
            return 1.0
        if sig.get("rejected") is True:
            return 0.0
        if rec.verdict == "pass":
            return 1.0
        if rec.verdict == "fail":
            return 0.0
        return None


# ---------------------------------------------------------------------------
# Feed-forward: pair sessions -> dottie_telemetry.jsonl (for grpo_collect.py)
# ---------------------------------------------------------------------------

def export_to_telemetry(sessions_path: Path | str = DEFAULT_OUT,
                        telemetry_path: Path | str = "reports/dottie_telemetry.jsonl") -> Dict[str, Any]:
    """Convert consented session records into grpo_collect-ready telemetry rows.

    Row schema matches grpo_collect input contract:
      {prompt, completion, trace_id, rl_return, entropy, verdict, source}
    Rows with rl_return=None are SKIPPED (honesty: no invented reward).
    """
    sessions_path = Path(sessions_path)
    telemetry_path = Path(telemetry_path)
    rows: List[Dict[str, Any]] = []
    seen = 0
    if sessions_path.exists():
        for line in sessions_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("schema_version") != SCHEMA_VERSION:
                continue
            if not rec.get("consent"):
                continue
            seen += 1
            rl = rec.get("rl_return")
            if rl is None:
                continue  # honest: skip rows without a recorded reward
            completion_parts = [a.get("summary", "") for a in rec.get("assistant_actions", [])]
            rows.append({
                "prompt": rec.get("prompt", ""),
                "completion": "\n".join(completion_parts)[:4000],
                "trace_id": rec.get("trace_id", ""),
                "rl_return": float(rl),
                "entropy": None,
                "verdict": rec.get("verdict", "unknown"),
                "source": "pair_session_real",
                "session_id": rec.get("session_id", ""),
            })
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    with open(telemetry_path, "ab") as f:
        for r in rows:
            f.write((json.dumps(r, ensure_ascii=False) + "\n").encode("utf-8"))
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    return {"sessions_seen": seen, "rows_exported": len(rows),
            "sessions_path": str(sessions_path), "telemetry_path": str(telemetry_path)}


# ---------------------------------------------------------------------------
# Harness hook helper (honest 503)
# ---------------------------------------------------------------------------

def run_with_capture(prompt: str, run_fn: Callable[[str], Dict[str, Any]],
                     capture: Optional[SessionCapture] = None,
                     opt_in: Optional[bool] = None) -> Dict[str, Any]:
    """Wrap a harness run_fn with session capture.

    run_fn(prompt) -> record dict (the engine's trace record).
    If the harness is unreachable (run_fn raises), the session is closed with
    status="error", errorClass="harness_unreachable", rl_return=None — the
    honest-503 equivalent for trace data. The exception is re-raised so the
    caller keeps its own error semantics.
    """
    cap = capture or SessionCapture(enabled=opt_in)
    if not cap.enabled:
        return run_fn(prompt)  # read-only by default: zero behavior change
    rec = cap.begin(prompt)
    t0 = time.time()
    try:
        record = run_fn(prompt)
    except Exception as e:
        cap.log_signal(rec, harness_error=str(e)[:200])
        cap.end(rec, outcome="error", verdict="unknown",
                latency_ms=int((time.time() - t0) * 1000),
                status="error", error_class="harness_unreachable")
        raise
    actions = record.get("actions") or record.get("steps") or []
    for a in actions if isinstance(actions, list) else []:
        if isinstance(a, dict):
            cap.log_action(rec, a.get("action", "step"),
                           summary=str(a.get("summary", a.get("state", "")))[:500],
                           tool_calls=a.get("tool_calls"))
    cap.log_signal(rec, accepted=bool(record.get("accepted", False)) or None,
                   rejected=bool(record.get("rejected", False)) or None)
    verdict = record.get("verdict", "unknown")
    cap.end(rec,
            outcome="success" if verdict == "pass" else ("error" if verdict == "fail" else "unknown"),
            verdict=verdict,
            latency_ms=int(record.get("latency_ms", (time.time() - t0) * 1000)),
            tokens_est=int(record.get("tokens_est", 0)),
            status="ok")
    return record


@contextmanager
def capture_session(prompt: str, out: Path | str = DEFAULT_OUT,
                    opt_in: Optional[bool] = None, **kw: Any) -> Iterator[SessionCapture]:
    """Context manager form for interactive (multi-turn) sessions.

    Usage:
        with capture_session("help me refactor X", opt_in=True) as cap:
            rec = cap.begin("help me refactor X")
            ... cap.log_action / cap.log_correction / cap.log_signal ...
            cap.end(rec, outcome="success", verdict="pass")
    """
    cap = SessionCapture(out=out, enabled=opt_in, **kw)
    yield cap


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="session_capture — inspect/export pair sessions")
    ap.add_argument("--in", dest="inp", default=DEFAULT_OUT)
    ap.add_argument("--out", dest="out", default="reports/dottie_telemetry.jsonl")
    ap.add_argument("--export", action="store_true", help="export to telemetry jsonl")
    ap.add_argument("--stats", action="store_true", help="print schema/counts summary")
    args = ap.parse_args()
    if args.export:
        print(json.dumps(export_to_telemetry(args.inp, args.out), indent=2))
    elif args.stats:
        n = consented = 0
        p = Path(args.inp)
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                n += 1
                try:
                    if json.loads(line).get("consent"):
                        consented += 1
                except Exception:
                    pass
        print(json.dumps({"path": args.inp, "records": n, "consented": consented,
                          "schema": SCHEMA_VERSION}, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
