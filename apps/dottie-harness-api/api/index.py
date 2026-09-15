"""Fail-closed production HTTP boundary for the Dottie harness router."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlsplit

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from lib import production_routing

SERVICE_VERSION = "1"
MAX_BODY_BYTES = 64 * 1024
ARTIFACT_REQUIREMENTS = [
    "production-derived artifact bundle with synthetic=false",
    "signed manifest naming the schema version and source run IDs",
    "SHA-256 checksum for every artifact verified before serving",
    "owner-approved production loader or dispatcher with no mock fallback",
]
DISABLED_ARTIFACT_ROUTES = {
    "/api/analytics",
    "/api/corpus",
    "/api/meter",
    "/api/retrain",
    "/api/stats",
    "/api/vector",
}
DISABLED_TOOL_NAMES = {
    "dottie",
    "dottie__retrain_trigger",
    "mcp:dottie__retrain_trigger",
    "mcp:vector-hub__embedding_lookup",
    "vector-hub",
    "vector-hub__embedding_lookup",
}
POLICY_UNAVAILABLE_REASON = "deployment_policy_unavailable"
CONSERVATIVE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
HOSTNAME = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def _is_disabled_artifact_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in DISABLED_ARTIFACT_ROUTES
    )


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _valid_hostname(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return HOSTNAME.fullmatch(host) is not None


def _valid_exact_origin(origin: str, *, require_https: bool = False) -> bool:
    if origin in {"", "*", "null"} or any(
        character.isspace() or ord(character) == 127 for character in origin
    ):
        return False
    try:
        parsed = urlsplit(origin)
        parsed.port
    except ValueError:
        return False
    if (
        parsed.hostname is None
        or not _valid_hostname(parsed.hostname)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != ""
        or parsed.query != ""
        or parsed.fragment != ""
    ):
        return False
    if parsed.scheme == "https":
        return True
    return (
        not require_https
        and parsed.scheme == "http"
        and _is_loopback_host(parsed.hostname)
    )


def _allowed_origins() -> set[str]:
    raw = os.environ.get("HARNESS_API_ALLOWED_ORIGINS", "")
    return {
        origin
        for value in raw.split(",")
        if (origin := value.strip()) and _valid_exact_origin(origin)
    }


def _configured_bearer() -> str:
    return (os.environ.get("HARNESS_API_BEARER") or "").strip()


def _header_value(headers: object, name: str) -> str:
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    return (getter(name) or getter(name.lower()) or "").strip()


def _bearer_is_distinct() -> bool:
    bearer = _configured_bearer()
    if not bearer:
        return False
    jarvis_bearer = (os.environ.get("JARVIS_BEARER") or "").strip()
    if not jarvis_bearer:
        return True
    bearer_digest = hashlib.sha256(bearer.encode("utf-8")).digest()
    jarvis_digest = hashlib.sha256(jarvis_bearer.encode("utf-8")).digest()
    return not hmac.compare_digest(bearer_digest, jarvis_digest)


def _deployment_ready(headers: object, client_host: str) -> bool:
    if not _bearer_is_distinct():
        return False

    local_only = os.environ.get("HARNESS_API_LOCAL_ONLY") == "1"
    on_vercel = os.environ.get("VERCEL") == "1"
    if local_only:
        return not on_vercel and _is_loopback_host(client_host)
    if not on_vercel:
        return False

    vercel_id = _header_value(headers, "x-vercel-id")
    forwarded_for = _header_value(headers, "x-vercel-forwarded-for")
    owner = (os.environ.get("HARNESS_API_DEPLOYMENT_OWNER") or "").strip()
    policy_id = (os.environ.get("HARNESS_API_RATE_LIMIT_POLICY_ID") or "").strip()
    canonical_origin = (os.environ.get("HARNESS_API_CANONICAL_ORIGIN") or "").strip()
    try:
        ipaddress.ip_address(forwarded_for)
    except ValueError:
        return False
    if (
        CONSERVATIVE_ID.fullmatch(vercel_id) is None
        or CONSERVATIVE_ID.fullmatch(owner) is None
        or CONSERVATIVE_ID.fullmatch(policy_id) is None
        or not _valid_exact_origin(canonical_origin, require_https=True)
    ):
        return False

    configured_origins = os.environ.get("HARNESS_API_ALLOWED_ORIGINS", "").strip()
    return not configured_origins or canonical_origin in _allowed_origins()


def _normalized_path(target: str) -> str:
    return unquote(urlsplit(target).path)


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def log_message(self, format: str, *args: object) -> None:
        """Keep serverless logs free of token-adjacent request metadata."""

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        if code == HTTPStatus.NOT_IMPLEMENTED:
            self._method_not_allowed()
            return
        try:
            safe_message = HTTPStatus(code).phrase
        except ValueError:
            safe_message = "HTTP request rejected"
        self._error(code, "http_error", safe_message)

    def _cors_origin(self) -> str | None:
        origin = getattr(self, "headers", {}).get("Origin")
        if origin and self._deployment_ready() and origin in _allowed_origins():
            return origin
        return None

    def _deployment_ready(self) -> bool:
        client_address = getattr(self, "client_address", ("", 0))
        client_host = client_address[0] if client_address else ""
        return _deployment_ready(getattr(self, "headers", {}), client_host)

    def _send_common_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if getattr(self, "_force_connection_close", False):
            self.send_header("Connection", "close")
        cors_origin = self._cors_origin()
        if cors_origin is not None:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Vary", "Origin")

    def _send(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_common_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self._send_common_headers()
        self.end_headers()

    def _error(self, status: int, code: str, message: str) -> None:
        self._send(
            status,
            {"ok": False, "error": {"code": code, "message": message}},
        )

    def _reject_routing(self, exc: production_routing.RoutingRejected, path: str, goal: str) -> None:
        """Fail-closed 400 for routing rejections: structured response, quarantine, alert.

        The rejection is quarantined to a JSONL log (best-effort: a read-only
        filesystem must not turn the quarantine into a second failure) and also
        emitted as a structured stderr line — the alert surface on serverless.
        """
        record = {
            "event": "routing_rejected",
            "path": path,
            "field": exc.field,
            "value": exc.value,
            "expected": exc.expected,
            "goal_preview": goal[:200],
        }
        print(json.dumps(record, ensure_ascii=False), file=sys.stderr, flush=True)
        try:
            quarantine_path = PACKAGE_ROOT / "lib" / "routing_quarantine.jsonl"
            quarantine_path.parent.mkdir(parents=True, exist_ok=True)
            with open(quarantine_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass
        self._error(400, "routing_rejected", f"unknown routing {exc.field}: {exc.value!r}")

    def _consume_rejected_body(self) -> None:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else 0
        except ValueError:
            return
        if 0 < length <= MAX_BODY_BYTES:
            self.rfile.read(length)

    def _reject_oversized_declared_body(self) -> bool:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else 0
        except ValueError:
            return False
        if length <= MAX_BODY_BYTES:
            return False
        self.close_connection = True
        self._force_connection_close = True
        self._error(
            413,
            "request_too_large",
            f"request body exceeds the {MAX_BODY_BYTES}-byte limit",
        )
        return True

    def _require_auth(self, *, consume_rejected_body: bool = False) -> bool:
        expected = _configured_bearer()
        if not expected:
            if consume_rejected_body:
                self._consume_rejected_body()
            self._error(
                503,
                "configuration_error",
                "HARNESS_API_BEARER must be configured for protected API routes",
            )
            return False

        authorization = self.headers.get("Authorization") or ""
        scheme, separator, supplied = authorization.partition(" ")
        valid_shape = bool(
            separator
            and scheme.lower() == "bearer"
            and supplied
            and not any(character.isspace() for character in supplied)
        )
        supplied_bytes = supplied.encode("utf-8") if valid_shape else b""
        expected_bytes = expected.encode("utf-8")
        supplied_digest = hashlib.sha256(supplied_bytes).digest()
        expected_digest = hashlib.sha256(expected_bytes).digest()
        token_matches = hmac.compare_digest(supplied_digest, expected_digest)
        if not valid_shape or not token_matches:
            if consume_rejected_body:
                self._consume_rejected_body()
            self._error(401, "unauthorized", "valid Harness API Bearer token required")
            return False
        return True

    def _require_deployment(self, *, consume_rejected_body: bool = False) -> bool:
        if self._deployment_ready():
            return True
        if consume_rejected_body:
            self._consume_rejected_body()
        self._error(
            503,
            "configuration_error",
            "deployment policy unavailable",
        )
        return False

    def _read_json_body(self) -> dict[str, object] | None:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            self._error(411, "length_required", "Content-Length is required")
            return None
        try:
            length = int(raw_length)
        except ValueError:
            self._error(400, "invalid_content_length", "Content-Length must be an integer")
            return None
        if length < 0:
            self._error(400, "invalid_content_length", "Content-Length cannot be negative")
            return None
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            self._force_connection_close = True
            self._error(
                413,
                "request_too_large",
                f"request body exceeds the {MAX_BODY_BYTES}-byte limit",
            )
            return None

        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(400, "invalid_json", "request body must be valid UTF-8 JSON")
            return None
        if not isinstance(value, dict):
            self._error(400, "invalid_json", "JSON request body must be an object")
            return None
        return value

    def _send_artifact_unavailable(self) -> None:
        self._send(
            503,
            {
                "ok": False,
                "error": {
                    "code": "artifact_unavailable",
                    "message": "production artifacts are unavailable; synthetic fallbacks are disabled",
                },
                "requirements": ARTIFACT_REQUIREMENTS,
            },
        )

    def _require_goal(self, document: dict[str, object]) -> str | None:
        goal = document.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            self._error(400, "invalid_request", "body must include a non-empty goal string")
            return None
        return goal

    def do_OPTIONS(self) -> None:
        if not self._require_deployment():
            return
        origin = self.headers.get("Origin")
        requested_method = (self.headers.get("Access-Control-Request-Method") or "").upper()
        requested_headers = {
            item.strip().lower()
            for item in (self.headers.get("Access-Control-Request-Headers") or "").split(",")
            if item.strip()
        }
        if (
            origin not in _allowed_origins()
            or requested_method != "POST"
            or not requested_headers.issubset({"authorization", "content-type"})
        ):
            self._error(403, "cors_origin_denied", "CORS preflight is not allowed")
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._send_common_headers()
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:
        path = _normalized_path(self.path)
        if path == "/api/health":
            ready = self._deployment_ready()
            payload: dict[str, object] = {
                "service": "dottie-harness-api",
                "version": SERVICE_VERSION,
                "ready": ready,
            }
            if not ready:
                payload["reason"] = POLICY_UNAVAILABLE_REASON
            self._send(
                200,
                payload,
            )
            return
        if not self._require_deployment():
            return
        if not self._require_auth():
            return
        if _is_disabled_artifact_path(path):
            self._send_artifact_unavailable()
            return
        self._error(404, "not_found", "route not found")

    def do_POST(self) -> None:
        path = _normalized_path(self.path)
        if self._reject_oversized_declared_body():
            return
        if not self._require_deployment(consume_rejected_body=True):
            return
        if not self._require_auth(consume_rejected_body=True):
            return
        document = self._read_json_body()
        if document is None:
            return
        if _is_disabled_artifact_path(path):
            self._send_artifact_unavailable()
            return
        if path not in {"/api/route", "/api/plan"}:
            self._error(404, "not_found", "route not found")
            return

        tools = document.get("tools")
        if isinstance(tools, list) and any(
            isinstance(tool, str) and tool in DISABLED_TOOL_NAMES for tool in tools
        ):
            self._send_artifact_unavailable()
            return
        goal = self._require_goal(document)
        if goal is None:
            return

        if path == "/api/route":
            try:
                result = production_routing.route_goal(goal)
            except production_routing.RoutingRejected as exc:
                self._reject_routing(exc, path, goal)
                return
        else:
            try:
                result = production_routing.plan_goal(goal)
            except production_routing.RoutingRejected as exc:
                self._reject_routing(exc, path, goal)
                return
        self._send(
            200,
            {
                "ok": True,
                **result,
                "learned": None,
                "model_status": "unavailable",
            },
        )

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_HEAD(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        if not self._require_deployment():
            return
        if not self._require_auth():
            return
        self._error(405, "method_not_allowed", "method not allowed")
