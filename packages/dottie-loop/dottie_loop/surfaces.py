"""Surfaces that differ in ergonomics, never in authority (spec §06).

* :class:`SlackReporter` — fast acknowledgement, message-ID dedupe, one thread
  per run, posts only on meaningful state change, under the reporting line limit
  (RT-16). A mention or quoted text is never authorization.
* :class:`ApprovalBoard` — the minimum web approval board (§35 open decision):
  server-authoritative state, CSRF protection, immutable decision history, no
  client-only approval. stdlib ``http.server``; bind to loopback by default.
"""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

from dottie_loop.errors import (
    InvalidInputError,
    LoopError,
    PolicyDeniedError,
    UnauthenticatedError,
    error_envelope,
    ok_envelope,
)
from dottie_loop.hashing import new_id, now_iso

if TYPE_CHECKING:
    from collections.abc import Callable

    from dottie_loop.approvals import ApprovalStore
    from dottie_loop.intake import GoalStore

# --- Slack (§06 Slack contract, §30 Slack team view) ----------------------------------------

REPORT_LINE_LIMIT = 8
MEANINGFUL_STATES = frozenset({"received", "planned", "blocked", "failed", "verified", "completed", "cancelled", "rejected"})


@dataclass
class SlackReporter:
    sink: Callable[[dict[str, Any]], None] | None = None
    line_limit: int = REPORT_LINE_LIMIT
    seen_events: set[str] = field(default_factory=set)
    last_state: dict[str, str] = field(default_factory=dict)
    threads: dict[str, str] = field(default_factory=dict)
    posted: list[dict[str, Any]] = field(default_factory=list)

    def acknowledge(self, event_id: str, channel_id: str, goal_id: str) -> dict[str, Any] | None:
        """Fast ack reporting RECEIVED only; a replayed event id posts nothing."""
        if event_id in self.seen_events:
            return None
        self.seen_events.add(event_id)
        msg = {"channel_id": channel_id, "thread_ts": self.threads.setdefault(goal_id, new_id("ts_")), "text": f"received goal {goal_id}", "event_id": event_id, "at": now_iso()}
        self._deliver(msg)
        return msg

    def report(self, *, event_id: str, channel_id: str, run_id: str, state: str, verdict: str, evidence: list[str], blocker: str | None = None, next_decision: str | None = None) -> dict[str, Any] | None:
        """One post per STATE CHANGE, deduped by event id, threaded to the run, capped."""
        if event_id in self.seen_events:
            return None
        self.seen_events.add(event_id)
        if state not in MEANINGFUL_STATES or self.last_state.get(run_id) == state:
            return None  # heartbeat noise stays in machine logs
        self.last_state[run_id] = state
        lines = [f"[{state}] {verdict}", *[f"evidence: {e}" for e in evidence[:3]]]
        if blocker:
            lines.append(f"blocker: {blocker}")
        if next_decision:
            lines.append(f"next decision: {next_decision}")
        if len(lines) > self.line_limit:
            lines = [*lines[: self.line_limit - 1], f"(+{len(lines) - self.line_limit + 1} lines in the run log)"]
        msg = {"channel_id": channel_id, "thread_ts": self.threads.setdefault(run_id, new_id("ts_")), "text": "\n".join(lines), "lines": len(lines), "event_id": event_id, "run_id": run_id, "at": now_iso()}
        self._deliver(msg)
        return msg

    @staticmethod
    def is_authorization(_message_text: str) -> bool:
        """A mention or quoted text is never authorization: only a signed approval token is."""
        return False

    def _deliver(self, msg: dict[str, Any]) -> None:
        self.posted.append(msg)
        if self.sink is not None:
            self.sink(msg)


# --- web approval board (§06 Web row, §35 "minimum web approval board") ----------------------


class BoardState:
    """Server-authoritative state shared by handler instances; decisions are append-only."""

    def __init__(self, goals: GoalStore, approvals: ApprovalStore, *, approvers: dict[str, str]) -> None:
        self.goals = goals
        self.approvals = approvals
        self.approvers = dict(approvers)  # bearer token -> subject id
        self.csrf: dict[str, str] = {}  # subject -> token
        self.decisions: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def subject_for(self, bearer: str | None) -> str:
        if not bearer or bearer not in self.approvers:
            raise UnauthenticatedError()
        return self.approvers[bearer]

    def issue_csrf(self, subject: str) -> str:
        tok = secrets.token_urlsafe(24)
        with self.lock:
            self.csrf[subject] = tok
        return tok

    def check_csrf(self, subject: str, token: str | None) -> None:
        if not token or self.csrf.get(subject) != token:
            raise PolicyDeniedError("missing or invalid CSRF token", field="csrf")

    def snapshot(self) -> dict[str, Any]:
        goals = self.goals._read(self.goals.goals_path)
        return {"goals": [{"goal_id": g["goal_id"], "status": self.goals.status(g["goal_id"]), "side_effect_class": g["side_effect_class"], "intent_text": g["intent_text"][:200]} for g in goals], "decisions": list(self.decisions), "approvals": list(self.approvals.history)}

    def approve(self, subject: str, body: dict[str, Any]) -> dict[str, Any]:
        for k in ("action_type", "payload", "destination", "goal_id"):
            if k not in body:
                raise InvalidInputError(f"missing {k}", field=k)
        if self.goals.get(body["goal_id"]) is None:
            raise InvalidInputError("unknown goal", field="goal_id")
        rec = self.approvals.issue(approver_subject=subject, approver_role="board", action_type=body["action_type"], payload=body["payload"], destination=body["destination"], goal_id=body["goal_id"])
        decision = {"decision_id": new_id("dec_"), "kind": "approve", "approval_id": rec.approval_id, "approver": subject, "goal_id": body["goal_id"], "action": body["action_type"], "destination": body["destination"], "at": now_iso()}
        with self.lock:
            self.decisions.append(decision)
        return decision

    def deny(self, subject: str, body: dict[str, Any]) -> dict[str, Any]:
        decision = {"decision_id": new_id("dec_"), "kind": "deny", "approver": subject, "goal_id": body.get("goal_id"), "reason": str(body.get("reason", ""))[:500], "at": now_iso()}
        with self.lock:
            self.decisions.append(decision)
        return decision


def _handler(state: BoardState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "dottie-loop-board/0.1"

        def log_message(self, *_args: Any) -> None:  # quiet
            return

        def _send(self, obj: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(obj, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _bearer(self) -> str | None:
            auth = self.headers.get("Authorization", "")
            return auth[7:] if auth.startswith("Bearer ") else None

        def do_GET(self) -> None:
            try:
                subject = state.subject_for(self._bearer())
                if self.path == "/api/state":
                    self._send(ok_envelope(state.snapshot()))
                elif self.path == "/api/csrf":
                    self._send(ok_envelope({"csrf": state.issue_csrf(subject)}))
                else:
                    self._send(error_envelope(InvalidInputError("unknown route", field="path")), 404)
            except LoopError as e:
                self._send(error_envelope(e), e.status)

        def do_POST(self) -> None:
            try:
                subject = state.subject_for(self._bearer())
                length = int(self.headers.get("Content-Length", "0"))
                if length > 64 * 1024:
                    raise InvalidInputError("body too large", field="body")
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    raise InvalidInputError("body is not JSON", field="body") from e
                state.check_csrf(subject, self.headers.get("X-CSRF-Token"))
                if self.path == "/api/approve":
                    self._send(ok_envelope(state.approve(subject, body)), 201)
                elif self.path == "/api/deny":
                    self._send(ok_envelope(state.deny(subject, body)), 201)
                else:
                    self._send(error_envelope(InvalidInputError("unknown route", field="path")), 404)
            except LoopError as e:
                self._send(error_envelope(e), e.status)

    return Handler


class ApprovalBoard:
    def __init__(self, state: BoardState, host: str = "127.0.0.1", port: int = 0) -> None:
        self.state = state
        self.server = ThreadingHTTPServer((host, port), _handler(state))
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        return self.server.server_address[0], self.server.server_address[1]

    def start(self) -> None:
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
