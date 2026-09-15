"""Slack ingress: a goal typed in Slack becomes a goal in the daemon.

This is the one v1 done-criterion the daemon shipped without. Everything else it
needs already exists — `Jarvis.goal()` writes the row, `/api/goals` reads it back.
This module is the doorway, and the doorway is the part that has to be paranoid.

WHY THIS PATH IS EXEMPT FROM BEARER AUTH. Slack cannot send our bearer; it signs
each request instead, with HMAC-SHA256 over `v0:<timestamp>:<raw body>` keyed by
the app's signing secret. So `/api/slack/events` is exempt from `AuthMiddleware`'s
bearer check and enforces the Slack signature itself. Exempt from *that* check, not
from authentication or the IP rate limiter: an unsigned request never reaches a
handler, and a flood still counts against the IP bucket.

FAIL-CLOSED, DELIBERATELY, AT EVERY BRANCH. The repo's doctrine is that an
unrecognised input is refused rather than waved through, and `verify()` returns a
reason for every rejection instead of a bare bool so the refusal is auditable:

  - no signing secret configured  -> 503. The endpoint is off, not open. This is
    the branch that matters most: an operator who has not finished setup gets a
    closed door, never an open one.
  - missing / malformed headers   -> 401
  - timestamp outside the window  -> 401 (replay)
  - signature mismatch            -> 401
  - signature already seen        -> 409 (Slack retries; a retry must not open a
                                    second goal for the same message)
  - payload shape not recognised  -> 400, never a silent 200. Returning ok to
                                    something we did not understand is exactly the
                                    fail-open this codebase keeps finding.

NO OUTBOUND CALLS, SO NO BOT TOKEN. A slash command's HTTP response *is* the reply
Slack shows the user, so `/jarvis ship the thing` opens a goal and confirms it with
no token anywhere. Posting unprompted messages back into a channel would need
`SLACK_BOT_TOKEN`; that is deliberately not done here and is the operator's step.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "MAX_BODY_BYTES",
    "MAX_SKEW_SECONDS",
    "SLACK_PATH",
    "ReplayGuard",
    "SlackRefusalError",
    "goal_text_from",
    "parse_payload",
    "sign",
    "verify",
]

SLACK_PATH = "/api/slack/events"

# Slack's own guidance is to reject anything older than five minutes. The window is
# two-sided: a timestamp far in the future is as suspect as one far in the past.
MAX_SKEW_SECONDS = 60 * 5

# Slack caps a slash command at 4000 characters; anything larger is not from Slack.
MAX_BODY_BYTES = 64 * 1024

_VERSION = "v0"


class SlackRefusalError(Exception):
    """A request that will not be processed, with the status it earns.

    Carries a `reason` short enough to log and vague enough not to help an attacker
    tell "wrong signature" from "wrong secret" — both are just `bad signature`.
    """

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


class ReplayGuard:
    """Remembers recently accepted signatures so a Slack retry cannot double-post.

    Slack retries a delivery up to three times when it does not see a 200 quickly,
    and a retry carries the *same* signature. Without this, one message typed once
    opens three goals. Bounded and FIFO-evicting: this is a doorway, not a store.
    """

    def __init__(self, capacity: int = 2048) -> None:
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._capacity = capacity

    def check_and_record(self, signature: str, now: float | None = None) -> None:
        """Raise `SlackRefusalError(409)` if this signature was already accepted."""
        moment = time.time() if now is None else now
        self._evict(moment)
        if signature in self._seen:
            raise SlackRefusalError(409, "replayed signature")
        self._seen[signature] = moment
        while len(self._seen) > self._capacity:
            self._seen.popitem(last=False)

    def _evict(self, now: float) -> None:
        cutoff = now - MAX_SKEW_SECONDS
        while self._seen:
            _, stamped = next(iter(self._seen.items()))
            if stamped >= cutoff:
                break
            self._seen.popitem(last=False)

    def __len__(self) -> int:
        return len(self._seen)


def sign(secret: str, timestamp: str | int, body: bytes) -> str:
    """The `v0=<hex>` signature Slack would send for this body at this timestamp.

    Exported because the tests need to produce real signatures, and because a
    hand-rolled equivalent in a test file is a second implementation that can drift
    away from this one and start agreeing with a bug.
    """
    basestring = f"{_VERSION}:{timestamp}:".encode() + body
    digest = hmac.new(secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
    return f"{_VERSION}={digest}"


def verify(
    secret: str | None,
    headers: Mapping[str, str],
    body: bytes,
    *,
    now: float | None = None,
) -> str:
    """Authenticate a Slack request. Returns the signature; raises `SlackRefusalError`.

    Returning the signature rather than `True` is what lets the caller hand it to a
    `ReplayGuard` without re-reading a header it already validated.
    """
    if len(body) > MAX_BODY_BYTES:
        raise SlackRefusalError(413, "body too large for a slack payload")
    if not secret:
        raise SlackRefusalError(503, "slack ingress not configured")

    lower = {k.lower(): v for k, v in headers.items()}
    signature = lower.get("x-slack-signature", "")
    raw_ts = lower.get("x-slack-request-timestamp", "")
    if not signature or not raw_ts:
        raise SlackRefusalError(401, "missing slack signature headers")
    try:
        timestamp = int(raw_ts)
    except ValueError as exc:
        raise SlackRefusalError(401, "malformed slack timestamp") from exc

    moment = time.time() if now is None else now
    # Two-sided on purpose. A one-sided check accepts a timestamp from next year.
    if abs(moment - timestamp) > MAX_SKEW_SECONDS:
        raise SlackRefusalError(401, "slack timestamp outside the replay window")

    expected = sign(secret, raw_ts, body)
    # compare_digest, not ==: a short-circuiting comparison leaks the prefix length.
    if not hmac.compare_digest(expected, signature):
        raise SlackRefusalError(401, "bad signature")
    return signature


def parse_payload(content_type: str, body: bytes) -> dict[str, Any]:
    """Decode the two shapes Slack actually posts, and refuse a third.

    Events API sends JSON; slash commands send form-encoded. Anything else is not
    something we know how to read, and guessing is how a doorway becomes a hole.
    """
    kind = (content_type or "").split(";")[0].strip().lower()
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SlackRefusalError(400, "body is not utf-8") from exc

    if kind == "application/json":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SlackRefusalError(400, "malformed json") from exc
        if not isinstance(doc, dict):
            raise SlackRefusalError(400, "payload must be a JSON object")
        return doc

    if kind == "application/x-www-form-urlencoded":
        # A slash command is flat: keep_blank_values so an empty `text` is present
        # and reaches the "say what you want" branch instead of vanishing.
        return {k: v[0] for k, v in parse_qs(text, keep_blank_values=True).items()}

    raise SlackRefusalError(400, f"unsupported content-type: {kind or 'none'}")


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def goal_text_from(doc: dict[str, Any]) -> tuple[str, str, str]:
    """Pull (kind, who, text) out of a verified payload, or refuse it.

    `kind` is one of `url_verification`, `slash`, `event`. The caller decides what
    to do with each; this function's job is to refuse anything that is none of them
    rather than return an empty tuple that reads as success.
    """
    if _clean(doc.get("type")) == "url_verification":
        challenge = _clean(doc.get("challenge"))
        if not challenge:
            raise SlackRefusalError(400, "url_verification without a challenge")
        return ("url_verification", "", challenge)

    # Slash command: form-encoded, carries `command` and `text`.
    command = _clean(doc.get("command"))
    if command:
        who = _clean(doc.get("user_name")) or _clean(doc.get("user_id")) or "slack"
        return ("slash", who, _clean(doc.get("text")))

    if _clean(doc.get("type")) == "event_callback":
        event = doc.get("event")
        if not isinstance(event, dict):
            raise SlackRefusalError(400, "event_callback without an event object")
        etype = _clean(event.get("type"))
        if etype not in {"app_mention", "message"}:
            raise SlackRefusalError(400, f"unhandled slack event: {etype or 'none'}")
        # Never act on our own output, or on edits/joins//deletions that carry a
        # subtype. A bot replying to itself is the classic Slack integration loop.
        if event.get("bot_id") or _clean(event.get("subtype")):
            raise SlackRefusalError(400, "ignoring bot or subtyped message")
        who = _clean(event.get("user")) or "slack"
        return ("event", who, _strip_mentions(_clean(event.get("text"))))

    raise SlackRefusalError(400, "unrecognised slack payload")


def _strip_mentions(text: str) -> str:
    """Drop leading `<@U123>` mentions so "@jarvis ship it" opens "ship it"."""
    out = text
    while out.startswith("<@"):
        close = out.find(">")
        if close < 0:
            break
        out = out[close + 1 :].lstrip()
    return out.strip()
