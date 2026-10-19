"""Auth for the serve's control-plane routes (``/reload`` and other admin paths).

Fail closed. No hardcoded secret. Loopback is the default bind; any caller
still needs a bearer compared with ``hmac.compare_digest``. Non-loopback
callers are refused unless that compare succeeds.
"""

from __future__ import annotations

import hmac
import ipaddress
import os

ADMIN_TOKEN_ENV = "DOTTIE_OS_ADMIN_TOKEN"
ADMIN_PATHS = frozenset({"/reload", "/admin", "/admin/reload", "/swap"})

# 401 = unauthenticated (missing/empty token or secret unset)
# 403 = authenticated-but-forbidden (wrong token, or non-loopback without a match)
STATUS_OK = 200
STATUS_UNAUTHENTICATED = 401
STATUS_FORBIDDEN = 403


def is_admin_path(path: str) -> bool:
    if path in ADMIN_PATHS:
        return True
    return path.endswith("/reload")


def is_loopback_peer(peer: str) -> bool:
    host = (peer or "").split("%", 1)[0].strip().lower()
    if host in {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}:
        return True
    if host.startswith("::ffff:"):
        host = host[7:]
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def bearer_from_headers(authorization: str | None, admin_token: str | None = None) -> str:
    """Pull the presented secret. Prefer ``Authorization: Bearer``, then ``X-Admin-Token``."""
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        if len(parts) == 1:
            return parts[0].strip()
    if admin_token:
        return admin_token.strip()
    return ""


def configured_secret(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return (env.get(ADMIN_TOKEN_ENV) or "").strip()


def tokens_match(presented: str, expected: str) -> bool:
    """Constant-time compare. Different lengths return False; never raise."""
    if not presented or not expected:
        return False
    left = presented.encode("utf-8")
    right = expected.encode("utf-8")
    if len(left) != len(right):
        hmac.compare_digest(right, right)
        return False
    return hmac.compare_digest(left, right)


def authorize_admin(
    *,
    peer: str,
    token: str,
    secret: str,
) -> tuple[int, str]:
    """Return ``(status, error)``. 200/empty means the caller may hit /reload.

    Unauthenticated (no secret configured, or no token): 401.
    Wrong token: 403.
    Matching token: 200 for loopback and for non-loopback (the token is the
    remote gate). The process still binds loopback by default.
    """
    if not secret:
        return STATUS_UNAUTHENTICATED, "admin token is not configured"
    if not token:
        return STATUS_UNAUTHENTICATED, "unauthorized"
    if not tokens_match(token, secret):
        return STATUS_FORBIDDEN, "forbidden"
    # Matching token admits the caller. Loopback is the default bind
    # (serve_decide.DEFAULT_HOST); non-loopback still had to present this token.
    if not is_loopback_peer(peer) and not tokens_match(token, secret):
        return STATUS_FORBIDDEN, "forbidden"
    return STATUS_OK, ""
