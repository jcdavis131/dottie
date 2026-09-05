"""Auth middleware (spec §2), ported once from the heredoc in docker-compose.dottie.yml.

- Static bearer compared with `hmac.compare_digest`.
- Ephemeral token `<sig16>:<unix_ts>:<nonce>` where
  `sig16 = HMAC-SHA256(bearer, f"{ts}:{nonce}").hexdigest()[:16]`, valid ±90 s,
  single-use (256-entry LRU).
- Rate limits per minute: per IP, per key (last 4 chars), per `X-Agent-Id`.
- Security headers on every response. Audit line per authenticated request.

`mint_token()` is the one minting function; the CLI `token` command calls it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from starlette.types import ASGIApp, Message, Receive, Scope, Send

TOKEN_TTL_S = 90
SINGLE_USE_LRU = 256
AGENT_HEADER = "x-agent-id"
DEFAULT_AGENT = "anon"
DEFAULT_EXEMPT: tuple[str, ...] = ("/", "/api/health")

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
)


# -- tokens ---------------------------------------------------------------


def _sig16(bearer: str, ts: int, nonce: str) -> str:
    return hmac.new(
        bearer.encode("utf-8"), f"{ts}:{nonce}".encode(), hashlib.sha256
    ).hexdigest()[:16]


def mint_token(bearer: str, ts: int | None = None, nonce: str | None = None) -> str:
    """Mint an ephemeral `<sig16>:<ts>:<nonce>` token from the static bearer."""
    if not bearer:
        raise ValueError("bearer is empty")
    ts = int(time.time()) if ts is None else int(ts)
    nonce = nonce or secrets.token_hex(8)
    if ":" in nonce:
        raise ValueError("nonce must not contain ':'")
    return f"{_sig16(bearer, ts, nonce)}:{ts}:{nonce}"


def verify_ephemeral(bearer: str, token: str, now: float | None = None) -> bool:
    """True when `token` is a well-formed, in-window, correctly signed ephemeral token.

    Single-use is enforced by the middleware, not here.
    """
    parts = token.split(":")
    if len(parts) != 3:
        return False
    sig, ts_raw, nonce = parts
    try:
        ts = int(ts_raw)
    except ValueError:
        return False
    now = time.time() if now is None else now
    if abs(now - ts) > TOKEN_TTL_S:
        return False
    return hmac.compare_digest(sig, _sig16(bearer, ts, nonce))


def agent_from_headers(headers: Headers | dict[str, str]) -> str:
    """`X-Agent-Id` or `anon`. Trimmed to 64 chars, never empty."""
    raw = headers.get(AGENT_HEADER, "") if headers is not None else ""
    raw = (raw or "").strip()[:64]
    return raw or DEFAULT_AGENT


# -- rate limiting --------------------------------------------------------


class RateLimiter:
    """Fixed one-minute windows per bucket key. Thread-safe."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[int, int]] = {}

    def check(self, key: str, limit: int) -> bool:
        """Count one hit on `key`; False when the minute's `limit` is exceeded."""
        window = int(self._clock() // 60)
        with self._lock:
            w, c = self._buckets.get(key, (window, 0))
            if w != window:
                self._buckets[key] = (window, 1)
                return True
            if c >= limit:
                return False
            self._buckets[key] = (w, c + 1)
            # keep memory bounded across many idle keys
            if len(self._buckets) > 10_000:
                stale = [k for k, (ww, _) in self._buckets.items() if ww != window]
                for k in stale:
                    del self._buckets[k]
            return True


# -- audit ----------------------------------------------------------------


class AuditLog:
    """Append-only `audit.jsonl`: `{ts, agent, path, status, key_last4}`. Never the key."""

    def __init__(self, path: Path | None):
        self.path = path
        self._lock = threading.Lock()

    def write(self, agent: str, path: str, status: int, key_last4: str) -> None:
        """Append one line; a write failure is swallowed so it never blocks a request."""
        if self.path is None:
            return
        line = json.dumps(
            {
                "ts": int(time.time()),
                "agent": agent,
                "path": path,
                "status": status,
                "key_last4": key_last4,
            }
        )
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            pass


# -- middleware -----------------------------------------------------------


class AuthMiddleware:
    """Pure-ASGI bearer/ephemeral auth + rate limits + security headers + audit.

    `bearer=None` disables auth entirely (loopback-only; `Config.validate` guards
    that). Headers and audit still apply. `exempt` paths are matched exactly.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        bearer: str | None,
        audit_path: Path | None = None,
        exempt: Iterable[str] = DEFAULT_EXEMPT,
        rate_ip: int = 1000,
        rate_key: int = 60,
        rate_agent: int = 20,
        clock: Callable[[], float] = time.time,
    ):
        self.app = app
        self.bearer = bearer or None
        self.exempt = frozenset(exempt)
        self.rate_ip = rate_ip
        self.rate_key = rate_key
        self.rate_agent = rate_agent
        self._clock = clock
        self._limiter = RateLimiter(clock)
        self._audit = AuditLog(audit_path)
        self._used: OrderedDict[str, None] = OrderedDict()
        self._used_lock = threading.Lock()

    # -- token bookkeeping --------------------------------------------------

    def _consume_once(self, token: str) -> bool:
        """Record an ephemeral token; False if it was already used."""
        with self._used_lock:
            if token in self._used:
                return False
            self._used[token] = None
            while len(self._used) > SINGLE_USE_LRU:
                self._used.popitem(last=False)
            return True

    def authenticate(self, token: str) -> tuple[bool, str]:
        """(ok, reason). Static bearer first, then ephemeral single-use."""
        assert self.bearer is not None
        if hmac.compare_digest(token, self.bearer):
            return True, "static"
        if not verify_ephemeral(self.bearer, token, self._clock()):
            return False, "invalid bearer"
        if not self._consume_once(token):
            return False, "single-use reused"
        return True, "ephemeral"

    # -- ASGI ---------------------------------------------------------------

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "") or "/"
        headers = Headers(scope=scope)
        agent = agent_from_headers(headers)
        status_holder = {"status": 0}

        async def send_wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message["status"])
                raw = [
                    (k, v)
                    for (k, v) in message.get("headers", [])
                    if k.lower() not in {h for h, _ in SECURITY_HEADERS}
                ]
                raw.extend(SECURITY_HEADERS)
                message["headers"] = raw
            await send(message)

        if path in self.exempt or self.bearer is None:
            await self.app(scope, receive, send_wrapped)
            self._audit.write(agent, path, status_holder["status"], "")
            return

        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.startswith("Bearer ") else ""
        last4 = token[-4:] if token else ""
        if not token:
            await self._reject(scope, send_wrapped, 401, "bearer required")
            self._audit.write(agent, path, 401, last4)
            return
        ok, reason = self.authenticate(token)
        if not ok:
            await self._reject(scope, send_wrapped, 401, reason)
            self._audit.write(agent, path, 401, last4)
            return

        client = scope.get("client")
        ip = client[0] if client else "unknown"
        if not (
            self._limiter.check(f"ip:{ip}", self.rate_ip)
            and self._limiter.check(f"agent:{agent}", self.rate_agent)
            and self._limiter.check(f"key:{last4}", self.rate_key)
        ):
            await self._reject(scope, send_wrapped, 429, "rate limited")
            self._audit.write(agent, path, 429, last4)
            return

        await self.app(scope, receive, send_wrapped)
        self._audit.write(agent, path, status_holder["status"], last4)

    @staticmethod
    async def _reject(scope: Scope, send: Send, status: int, error: str) -> None:
        body: dict[str, Any] = {"ok": False, "error": error}
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        response = JSONResponse(body, status_code=status, headers=headers)
        await response(scope, _noop_receive, send)


async def _noop_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


__all__ = [
    "AGENT_HEADER",
    "DEFAULT_AGENT",
    "DEFAULT_EXEMPT",
    "SINGLE_USE_LRU",
    "TOKEN_TTL_S",
    "AuditLog",
    "AuthMiddleware",
    "RateLimiter",
    "agent_from_headers",
    "mint_token",
    "verify_ephemeral",
]
