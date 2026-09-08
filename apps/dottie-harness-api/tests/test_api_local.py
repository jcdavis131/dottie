"""Security and truthfulness tests for the production harness API."""

from __future__ import annotations

import http.client
import importlib.util
import io
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
API_PATH = PACKAGE_ROOT / "api" / "index.py"
SPEC = importlib.util.spec_from_file_location("dottie_harness_api_index", API_PATH)
api = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(api)
DASHBOARD_PATH = PACKAGE_ROOT / "scripts" / "build_dashboard.py"
DASHBOARD_SPEC = importlib.util.spec_from_file_location("dottie_harness_dashboard", DASHBOARD_PATH)
dashboard = importlib.util.module_from_spec(DASHBOARD_SPEC)
assert DASHBOARD_SPEC.loader is not None
DASHBOARD_SPEC.loader.exec_module(dashboard)

TOKEN = "harness-api-test-token"
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@pytest.fixture()
def server(monkeypatch):
    monkeypatch.delenv("HARNESS_API_BEARER", raising=False)
    monkeypatch.delenv("HARNESS_API_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("HARNESS_API_DEPLOYMENT_OWNER", raising=False)
    monkeypatch.delenv("HARNESS_API_RATE_LIMIT_POLICY_ID", raising=False)
    monkeypatch.delenv("HARNESS_API_CANONICAL_ORIGIN", raising=False)
    monkeypatch.setenv("HARNESS_API_LOCAL_ONLY", "1")
    monkeypatch.setenv("JARVIS_BEARER", "jarvis-test-token")
    httpd = HTTPServer(("127.0.0.1", 0), api.handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: object | None = None,
    raw: bytes | None = None,
    token: str | None = None,
    origin: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict, dict[str, str]]:
    data = None
    if method in {"POST", "PUT", "PATCH"}:
        data = raw if raw is not None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    headers.update(extra_headers or {})
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:  # noqa: S310
            raw_response = response.read()
            payload = json.loads(raw_response.decode("utf-8")) if raw_response else {}
            return response.status, payload, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw_response = exc.read()
        payload = json.loads(raw_response.decode("utf-8")) if raw_response else {}
        return exc.code, payload, dict(exc.headers.items())


def raw_method_request(
    base: str, path: str, method: str, token: str | None = None
) -> tuple[int, dict, dict[str, str]]:
    target = urlsplit(base)
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=2)
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        raw_response = response.read()
        payload = json.loads(raw_response.decode("utf-8")) if raw_response else {}
        return response.status, payload, dict(response.headers.items())
    finally:
        connection.close()


def declared_length_request(
    base: str, path: str, declared_length: int, token: str | None = None
) -> tuple[int, dict, dict[str, str]]:
    target = urlsplit(base)
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=2)
    try:
        connection.putrequest("POST", path)
        if token is not None:
            connection.putheader("Authorization", f"Bearer {token}")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(declared_length))
        connection.endheaders()
        response = connection.getresponse()
        raw_response = response.read()
        payload = json.loads(raw_response.decode("utf-8")) if raw_response else {}
        return response.status, payload, dict(response.headers.items())
    finally:
        connection.close()


def authorize(monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_API_BEARER", TOKEN)


def configure_public_vercel(monkeypatch) -> dict[str, str]:
    monkeypatch.delenv("HARNESS_API_LOCAL_ONLY", raising=False)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("HARNESS_API_BEARER", TOKEN)
    monkeypatch.setenv("HARNESS_API_DEPLOYMENT_OWNER", "dottie-platform-owner")
    monkeypatch.setenv("HARNESS_API_RATE_LIMIT_POLICY_ID", "harness-api-policy-v1")
    monkeypatch.setenv("HARNESS_API_CANONICAL_ORIGIN", "https://harness.example.com")
    return {
        "x-vercel-id": "iad1::sfo1::harness-123456",
        "x-vercel-forwarded-for": "203.0.113.10",
    }


def assert_error(doc: dict, code: str) -> None:
    assert doc["ok"] is False
    assert doc["error"]["code"] == code


def assert_security_headers(headers: dict[str, str]) -> None:
    for name, expected in SECURITY_HEADERS.items():
        assert headers[name] == expected


def walk_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(walk_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(walk_keys(item) for item in value))
    return set()


def test_health_is_public_minimal_and_secured(server, monkeypatch):
    status, doc, headers = request(server, "/api/health")
    assert status == 200
    assert doc == {
        "service": "dottie-harness-api",
        "version": "1",
        "ready": False,
        "reason": "deployment_policy_unavailable",
    }
    for name, expected in SECURITY_HEADERS.items():
        assert headers[name] == expected
    assert "Access-Control-Allow-Origin" not in headers

    authorize(monkeypatch)
    _, configured, _ = request(server, "/api/health")
    assert configured == {"service": "dottie-harness-api", "version": "1", "ready": True}


def test_bearer_alone_does_not_enable_readiness_or_protected_routes(server, monkeypatch):
    authorize(monkeypatch)
    monkeypatch.delenv("HARNESS_API_LOCAL_ONLY", raising=False)
    status, health, _ = request(server, "/api/health")
    assert status == 200
    assert health == {
        "service": "dottie-harness-api",
        "version": "1",
        "ready": False,
        "reason": "deployment_policy_unavailable",
    }

    status, doc, headers = request(
        server,
        "/api/route",
        method="POST",
        body={"goal": "monitor tick"},
        token=TOKEN,
    )
    assert status == 503
    assert_error(doc, "configuration_error")
    assert_security_headers(headers)


def test_local_mode_requires_loopback_and_is_never_vercel(monkeypatch):
    authorize(monkeypatch)
    monkeypatch.setenv("HARNESS_API_LOCAL_ONLY", "1")
    monkeypatch.delenv("VERCEL", raising=False)
    assert api._deployment_ready({}, "127.0.0.1") is True
    assert api._deployment_ready({}, "::1") is True
    assert api._deployment_ready({}, "192.0.2.10") is False

    monkeypatch.setenv("VERCEL", "1")
    assert api._deployment_ready({}, "127.0.0.1") is False


def test_valid_vercel_platform_contract_enables_ready_and_auth(server, monkeypatch):
    platform_headers = configure_public_vercel(monkeypatch)
    status, health, _ = request(server, "/api/health", extra_headers=platform_headers)
    assert status == 200
    assert health == {"service": "dottie-harness-api", "version": "1", "ready": True}

    status, doc, _ = request(
        server,
        "/api/route",
        method="POST",
        body={"goal": "monitor tick"},
        token=TOKEN,
        extra_headers=platform_headers,
    )
    assert status == 200
    assert doc["provenance"] == "request_derived_heuristic"


@pytest.mark.parametrize(
    "missing",
    [
        "x-vercel-id",
        "x-vercel-forwarded-for",
        "HARNESS_API_DEPLOYMENT_OWNER",
        "HARNESS_API_RATE_LIMIT_POLICY_ID",
        "HARNESS_API_CANONICAL_ORIGIN",
        "HARNESS_API_BEARER",
    ],
)
def test_vercel_contract_fails_closed_when_policy_input_missing(
    server, monkeypatch, missing
):
    platform_headers = configure_public_vercel(monkeypatch)
    if missing.startswith("x-"):
        platform_headers.pop(missing)
    else:
        monkeypatch.delenv(missing, raising=False)

    status, health, _ = request(server, "/api/health", extra_headers=platform_headers)
    assert status == 200
    assert health == {
        "service": "dottie-harness-api",
        "version": "1",
        "ready": False,
        "reason": "deployment_policy_unavailable",
    }
    assert not (set(health) & {"owner", "policy_id", "canonical_origin", "bearer"})


@pytest.mark.parametrize("forwarded_for", ["not-an-ip", "203.0.113.10, 198.51.100.2", ""])
def test_vercel_forwarded_for_must_be_one_valid_ip(
    server, monkeypatch, forwarded_for
):
    platform_headers = configure_public_vercel(monkeypatch)
    platform_headers["x-vercel-forwarded-for"] = forwarded_for
    _, health, _ = request(server, "/api/health", extra_headers=platform_headers)
    assert health["ready"] is False
    assert health["reason"] == "deployment_policy_unavailable"


@pytest.mark.parametrize("vercel_id", ["", "contains spaces", "../spoof", "x"])
def test_vercel_request_id_must_be_conservative(server, monkeypatch, vercel_id):
    platform_headers = configure_public_vercel(monkeypatch)
    platform_headers["x-vercel-id"] = vercel_id
    _, health, _ = request(server, "/api/health", extra_headers=platform_headers)
    assert health["ready"] is False


def test_forwarding_headers_without_vercel_metadata_are_not_trusted(server, monkeypatch):
    authorize(monkeypatch)
    monkeypatch.delenv("HARNESS_API_LOCAL_ONLY", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    headers = {
        "x-forwarded-for": "203.0.113.10",
        "x-vercel-forwarded-for": "203.0.113.10",
    }
    _, health, _ = request(server, "/api/health", extra_headers=headers)
    assert health["ready"] is False


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("HARNESS_API_DEPLOYMENT_OWNER", "owner with spaces"),
        ("HARNESS_API_DEPLOYMENT_OWNER", "../owner"),
        ("HARNESS_API_RATE_LIMIT_POLICY_ID", "policy/unsafe"),
        ("HARNESS_API_RATE_LIMIT_POLICY_ID", "x"),
        ("HARNESS_API_CANONICAL_ORIGIN", "http://harness.example.com"),
        ("HARNESS_API_CANONICAL_ORIGIN", "https://harness.example.com/path"),
    ],
)
def test_public_configuration_values_are_conservative(
    server, monkeypatch, variable, value
):
    platform_headers = configure_public_vercel(monkeypatch)
    monkeypatch.setenv(variable, value)
    _, health, _ = request(server, "/api/health", extra_headers=platform_headers)
    assert health["ready"] is False
    assert health["reason"] == "deployment_policy_unavailable"


def test_public_harness_bearer_must_differ_from_jarvis(server, monkeypatch):
    platform_headers = configure_public_vercel(monkeypatch)
    monkeypatch.setenv("JARVIS_BEARER", TOKEN)
    _, health, _ = request(server, "/api/health", extra_headers=platform_headers)
    assert health["ready"] is False


def test_auth_matrix_and_jarvis_token_is_not_reused(server, monkeypatch):
    status, doc, _ = request(server, "/api/route", method="POST", body={"goal": "monitor tick"})
    assert status == 503
    assert_error(doc, "configuration_error")

    authorize(monkeypatch)
    for supplied in (None, "wrong-token"):
        status, doc, _ = request(
            server, "/api/route", method="POST", body={"goal": "monitor tick"}, token=supplied
        )
        assert status == 401
        assert_error(doc, "unauthorized")
    status, doc, _ = request(
        server,
        "/api/route",
        method="POST",
        body={"goal": "monitor tick"},
        extra_headers={"Authorization": f"Basic {TOKEN}"},
    )
    assert status == 401
    assert_error(doc, "unauthorized")

    monkeypatch.setenv("JARVIS_BEARER", TOKEN)
    monkeypatch.setenv("HARNESS_API_BEARER", "distinct-harness-token")
    status, doc, _ = request(
        server, "/api/route", method="POST", body={"goal": "monitor tick"}, token=TOKEN
    )
    assert status == 401
    assert_error(doc, "unauthorized")


@pytest.mark.parametrize(("configured", "expected_status"), [(False, 503), (True, 401)])
def test_repeated_rejected_posts_do_not_reset_connections(
    server, monkeypatch, configured, expected_status
):
    if configured:
        authorize(monkeypatch)
    else:
        monkeypatch.delenv("HARNESS_API_BEARER", raising=False)

    for attempt in range(12):
        status, doc, headers = request(
            server,
            "/api/route",
            method="POST",
            body={"goal": f"rejected request {attempt}"},
            token="wrong-token",
        )
        assert status == expected_status
        assert_error(doc, "unauthorized" if configured else "configuration_error")
        assert_security_headers(headers)


def test_auth_rejection_consumes_declared_bounded_body(monkeypatch):
    authorize(monkeypatch)
    raw = b'{"goal":"bounded rejection"}'
    consumed: list[bytes] = []
    errors: list[tuple[int, str, str]] = []
    fake_handler = type(
        "FakeHandler",
        (),
        {
            "headers": {
                "Authorization": "Bearer wrong-token",
                "Content-Length": str(len(raw)),
            },
            "rfile": io.BytesIO(raw),
            "_consume_rejected_body": lambda self: consumed.append(
                self.rfile.read(int(self.headers["Content-Length"]))
            ),
            "_error": lambda self, *args: errors.append(args),
        },
    )()

    assert api.handler._require_auth(fake_handler, consume_rejected_body=True) is False
    assert consumed == [raw]
    assert errors[0][:2] == (401, "unauthorized")


@pytest.mark.parametrize(
    "authorization",
    [
        f"Bearer  {TOKEN}",
        f"Bearer {TOKEN} ",
        f"Bearer\t{TOKEN}",
        f"Basic {TOKEN}",
        TOKEN,
    ],
)
def test_authorization_parser_rejects_noncanonical_bearer_values(
    server, monkeypatch, authorization
):
    authorize(monkeypatch)
    status, doc, _ = request(
        server,
        "/api/route",
        method="POST",
        body={"goal": "monitor tick"},
        extra_headers={"Authorization": authorization},
    )
    assert status == 401
    assert_error(doc, "unauthorized")


def test_auth_comparison_uses_equal_length_values_for_short_and_long_tokens(
    server, monkeypatch
):
    authorize(monkeypatch)
    real_compare_digest = api.hmac.compare_digest
    compared_lengths: list[tuple[int, int]] = []

    def recording_compare_digest(left: bytes, right: bytes) -> bool:
        compared_lengths.append((len(left), len(right)))
        return real_compare_digest(left, right)

    monkeypatch.setattr(api.hmac, "compare_digest", recording_compare_digest)
    for supplied in ("x", TOKEN * 8):
        status, doc, _ = request(
            server,
            "/api/route",
            method="POST",
            body={"goal": "monitor tick"},
            token=supplied,
        )
        assert status == 401
        assert_error(doc, "unauthorized")

    assert compared_lengths
    assert all(left == right for left, right in compared_lengths)


def test_authenticated_responses_have_security_headers(server, monkeypatch):
    authorize(monkeypatch)
    status, _, headers = request(
        server, "/api/route", method="POST", body={"goal": "monitor tick"}, token=TOKEN
    )
    assert status == 200
    for name, expected in SECURITY_HEADERS.items():
        assert headers[name] == expected


def test_cors_is_exact_origin_and_deny_by_default(server, monkeypatch):
    authorize(monkeypatch)
    allowed = "https://console.example"
    body = {"goal": "monitor tick"}

    _, _, default_headers = request(
        server, "/api/route", method="POST", body=body, token=TOKEN, origin=allowed
    )
    assert "Access-Control-Allow-Origin" not in default_headers

    monkeypatch.setenv("HARNESS_API_ALLOWED_ORIGINS", allowed)
    _, _, allowed_headers = request(
        server, "/api/route", method="POST", body=body, token=TOKEN, origin=allowed
    )
    assert allowed_headers["Access-Control-Allow-Origin"] == allowed
    assert allowed_headers["Vary"] == "Origin"
    assert "Access-Control-Allow-Credentials" not in allowed_headers

    _, _, denied_headers = request(
        server,
        "/api/route",
        method="POST",
        body=body,
        token=TOKEN,
        origin="https://console.example.evil",
    )
    assert "Access-Control-Allow-Origin" not in denied_headers

    monkeypatch.setenv("HARNESS_API_ALLOWED_ORIGINS", "*")
    _, _, wildcard_headers = request(
        server, "/api/route", method="POST", body=body, token=TOKEN, origin=allowed
    )
    assert "Access-Control-Allow-Origin" not in wildcard_headers


def test_cors_accepts_only_https_or_http_loopback(monkeypatch):
    values = [
        "https://console.example",
        "https://console.example:8443",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://[::1]:3000",
        "http://console.example",
        "https://user:pass@console.example",
        "https://console.example/path",
        "https://console.example?query=1",
        "https://console.example#fragment",
        "https://console.example\n.evil",
        "*",
    ]
    monkeypatch.setenv("HARNESS_API_ALLOWED_ORIGINS", ",".join(values))
    assert api._allowed_origins() == {
        "https://console.example",
        "https://console.example:8443",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://[::1]:3000",
    }


def test_public_cors_requires_canonical_origin_in_allowlist(server, monkeypatch):
    platform_headers = configure_public_vercel(monkeypatch)
    monkeypatch.setenv("HARNESS_API_ALLOWED_ORIGINS", "https://other.example")
    _, blocked, _ = request(server, "/api/health", extra_headers=platform_headers)
    assert blocked["ready"] is False

    canonical = "https://harness.example.com"
    monkeypatch.setenv(
        "HARNESS_API_ALLOWED_ORIGINS",
        f"https://other.example,{canonical}",
    )
    _, ready, headers = request(
        server,
        "/api/health",
        origin=canonical,
        extra_headers=platform_headers,
    )
    assert ready["ready"] is True
    assert headers["Access-Control-Allow-Origin"] == canonical


def test_configured_cors_preflight_is_narrow(server, monkeypatch):
    authorize(monkeypatch)
    origin = "https://console.example"
    monkeypatch.setenv("HARNESS_API_ALLOWED_ORIGINS", origin)
    status, _, headers = request(
        server,
        "/api/route",
        method="OPTIONS",
        origin=origin,
        extra_headers={
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == origin
    assert headers["Access-Control-Allow-Methods"] == "POST"
    assert headers["Access-Control-Allow-Headers"] == "Authorization, Content-Type"
    assert "Access-Control-Allow-Credentials" not in headers


def test_preflight_fails_configuration_before_advertising_cors(server, monkeypatch):
    origin = "https://console.example"
    monkeypatch.delenv("HARNESS_API_BEARER", raising=False)
    monkeypatch.setenv("HARNESS_API_ALLOWED_ORIGINS", origin)
    status, doc, headers = request(
        server,
        "/api/route",
        method="OPTIONS",
        origin=origin,
        extra_headers={
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert status == 503
    assert_error(doc, "configuration_error")
    assert_security_headers(headers)


@pytest.mark.parametrize(
    ("path", "raw"),
    [
        ("/api/route", b"{not-json"),
        ("/api/stats", b"{}"),
        ("/api/nope", b"{}"),
    ],
)
def test_missing_secret_takes_precedence_over_body_and_route_errors(
    server, monkeypatch, path, raw
):
    monkeypatch.delenv("HARNESS_API_BEARER", raising=False)
    status, doc, headers = request(server, path, method="POST", raw=raw, token=TOKEN)
    assert status == 503
    assert_error(doc, "configuration_error")
    assert_security_headers(headers)


@pytest.mark.parametrize(
    "extra_headers",
    [
        {"Access-Control-Request-Method": "GET"},
        {
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, x-injected",
        },
    ],
)
def test_preflight_rejects_wrong_method_or_extra_headers(
    server, monkeypatch, extra_headers
):
    authorize(monkeypatch)
    origin = "https://console.example"
    monkeypatch.setenv("HARNESS_API_ALLOWED_ORIGINS", origin)
    status, doc, headers = request(
        server,
        "/api/route",
        method="OPTIONS",
        origin=origin,
        extra_headers=extra_headers,
    )
    assert status == 403
    assert_error(doc, "cors_origin_denied")
    assert headers["Access-Control-Allow-Origin"] == origin
    assert "Access-Control-Allow-Methods" not in headers
    assert "Access-Control-Allow-Headers" not in headers
    assert "Access-Control-Allow-Credentials" not in headers
    assert_security_headers(headers)


def test_body_limit_and_invalid_json_fail_closed(server, monkeypatch):
    authorize(monkeypatch)
    status, doc, headers = declared_length_request(
        server, "/api/retrain", api.MAX_BODY_BYTES + 1, TOKEN
    )
    assert status == 413
    assert_error(doc, "request_too_large")
    assert headers["Connection"] == "close"

    status, doc, _ = request(
        server, "/api/route", method="POST", raw=b"{not-json", token=TOKEN
    )
    assert status == 400
    assert_error(doc, "invalid_json")

    status, doc, _ = request(server, "/api/route", method="POST", raw=b"[]", token=TOKEN)
    assert status == 400
    assert_error(doc, "invalid_json")


def test_oversized_declaration_precedes_missing_auth_configuration(server, monkeypatch):
    monkeypatch.delenv("HARNESS_API_BEARER", raising=False)
    status, doc, headers = declared_length_request(
        server, "/api/route", api.MAX_BODY_BYTES + 1
    )
    assert status == 413
    assert_error(doc, "request_too_large")
    assert headers["Connection"] == "close"


def test_oversized_body_is_rejected_without_reading_and_closes_connection(monkeypatch):
    errors: list[tuple[int, str, str]] = []
    body = io.BytesIO(b"{not-json")
    fake_handler = type(
        "FakeHandler",
        (),
        {
            "headers": {"Content-Length": str(api.MAX_BODY_BYTES + 1)},
            "rfile": body,
            "close_connection": False,
            "_error": lambda self, *args: errors.append(args),
        },
    )()

    def unexpected_json_parse(_: str) -> object:
        raise AssertionError("oversized bodies must not reach JSON parsing")

    monkeypatch.setattr(api.json, "loads", unexpected_json_parse)
    assert api.handler._read_json_body(fake_handler) is None
    assert body.tell() == 0
    assert fake_handler.close_connection is True
    assert errors == [
        (
            413,
            "request_too_large",
            f"request body exceeds the {api.MAX_BODY_BYTES}-byte limit",
        )
    ]


def test_security_headers_cover_every_error_class(server, monkeypatch):
    cases: list[tuple[int, dict, dict[str, str]]] = []
    cases.append(request(server, "/api/route", method="POST", body={"goal": "tick"}))

    authorize(monkeypatch)
    cases.extend(
        [
            request(server, "/api/route", method="POST", body={"goal": "tick"}),
            request(server, "/api/route", method="POST", raw=b"{", token=TOKEN),
            request(server, "/api/route", method="POST", body={}, token=TOKEN),
            request(server, "/api/nope", token=TOKEN),
            request(server, "/api/health", method="HEAD", token=TOKEN),
            request(server, "/api/stats", token=TOKEN),
        ]
    )

    expected_statuses = [503, 401, 400, 400, 404, 405, 503]
    assert [status for status, _, _ in cases] == expected_statuses
    for _, _, headers in cases:
        assert_security_headers(headers)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/stats"),
        ("GET", "/api/meter"),
        ("POST", "/api/meter"),
        ("GET", "/api/vector/hoops?q=12966"),
        ("POST", "/api/vector/unified"),
        ("GET", "/api/analytics"),
        ("GET", "/api/corpus"),
        ("POST", "/api/retrain"),
    ],
)
def test_artifact_routes_are_disabled(server, monkeypatch, method, path):
    authorize(monkeypatch)
    kwargs = {"body": {}} if method == "POST" else {}
    status, doc, _ = request(server, path, method=method, token=TOKEN, **kwargs)
    assert status == 503
    assert_error(doc, "artifact_unavailable")
    assert doc["requirements"] == api.ARTIFACT_REQUIREMENTS
    assert not (walk_keys(doc) & {"embedding", "metrics", "corpus_stats", "model_version"})


@pytest.mark.parametrize(
    "path",
    [
        "/api/stats?format=full",
        "/api/stats/",
        "/api/%73tats",
        "/api/vector%2Fhoops?q=12966",
        "/api/vector/%2e%2e/stats",
    ],
)
def test_artifact_routes_fail_closed_after_query_and_path_normalization(
    server, monkeypatch, path
):
    authorize(monkeypatch)
    status, doc, _ = request(server, path, token=TOKEN)
    assert status == 503
    assert_error(doc, "artifact_unavailable")


def test_artifact_requests_never_import_dormant_synthetic_modules(server, monkeypatch):
    authorize(monkeypatch)
    dormant_modules = {"acne_graph", "heuristics", "orch_infer", "vector_router"}
    assert not {
        name
        for name in sys.modules
        if name.rsplit(".", 1)[-1] in dormant_modules
    }

    for path in ("/api/stats", "/api/meter", "/api/vector/hoops", "/api/retrain"):
        method = "POST" if path == "/api/retrain" else "GET"
        kwargs = {"body": {}} if method == "POST" else {}
        status, _, _ = request(server, path, method=method, token=TOKEN, **kwargs)
        assert status == 503

    assert not {
        name
        for name in sys.modules
        if name.rsplit(".", 1)[-1] in dormant_modules
    }


@pytest.mark.parametrize("tool", ["vector-hub", "dottie", "dottie__retrain_trigger"])
def test_route_cannot_dispatch_disabled_tools(server, monkeypatch, tool):
    authorize(monkeypatch)
    status, doc, _ = request(
        server,
        "/api/route",
        method="POST",
        body={"goal": "perform lookup", "tools": [tool]},
        token=TOKEN,
    )
    assert status == 503
    assert_error(doc, "artifact_unavailable")


def test_route_is_real_deterministic_and_has_no_production_artifacts(server, monkeypatch):
    authorize(monkeypatch)
    body = {"goal": "compare stripe vs lemon squeezy pricing"}
    first = request(server, "/api/route", method="POST", body=body, token=TOKEN)
    second = request(server, "/api/route", method="POST", body=body, token=TOKEN)
    assert first[:2] == second[:2]
    status, doc, _ = first
    assert status == 200
    assert doc["ok"] is True
    assert doc["intent"] == "deep_research"
    assert 0.0 <= doc["heuristic_score"] <= 1.0
    assert doc["recommended_agents"] == [
        "deep-researcher",
        "synthesist",
        "forensic-auditor",
    ]
    assert doc["provenance"] == "request_derived_heuristic"
    assert "confidence" not in doc
    assert "routed_agents" not in doc
    assert doc["learned"] is None
    assert doc["model_status"] == "unavailable"
    assert not (
        walk_keys(doc)
        & {
            "embedding",
            "vector",
            "metrics",
            "corpus",
            "corpus_stats",
            "gate_passed",
            "model_loaded",
            "tools_results",
        }
    )


def test_plan_is_real_deterministic_and_labeled(server, monkeypatch):
    authorize(monkeypatch)
    body = {"goal": "ship the harness loop"}
    first = request(server, "/api/plan", method="POST", body=body, token=TOKEN)
    second = request(server, "/api/plan", method="POST", body=body, token=TOKEN)
    assert first[:2] == second[:2]
    status, doc, _ = first
    assert status == 200
    assert [step["id"] for step in doc["steps"]] == [
        "intent-decompose",
        "dag-architect",
        "layer-exec",
        "build",
        "verify-budget",
    ]
    assert doc["risk_provenance"] == "static priors — no mined run history in serverless"
    assert doc["provenance"] == "request_derived_heuristic"
    assert doc["learned"] is None
    assert doc["model_status"] == "unavailable"


@pytest.mark.parametrize("path", ["/api/route?next=/api/stats", "/api/plan?mode=../../stats"])
def test_route_and_plan_are_deterministic_under_request_injection(
    server, monkeypatch, path
):
    authorize(monkeypatch)
    hostile_goal = (
        '</script><script>globalThis.pwned=true</script>\n'
        '{"ok":true,"metrics":{"success":100}}'
    )
    body = {
        "goal": hostile_goal,
        "intent": "artifact_override",
        "steps": [{"id": "injected"}],
        "model_status": "available",
    }
    first = request(server, path, method="POST", body=body, token=TOKEN)
    second = request(server, path, method="POST", body=dict(reversed(body.items())), token=TOKEN)
    assert first[:2] == second[:2]
    status, doc, _ = first
    assert status == 200
    assert doc["goal"] == hostile_goal
    assert doc["model_status"] == "unavailable"
    assert "metrics" not in doc
    assert "artifact_override" not in walk_keys(doc)
    if path.startswith("/api/plan"):
        assert [step["id"] for step in doc["steps"]] != ["injected"]


def test_unknown_route_still_requires_auth_then_returns_404(server, monkeypatch):
    authorize(monkeypatch)
    status, doc, _ = request(server, "/api/nope")
    assert status == 401
    assert_error(doc, "unauthorized")

    status, doc, _ = request(server, "/api/nope", token="wrong-token")
    assert status == 401
    assert_error(doc, "unauthorized")

    status, doc, _ = request(server, "/api/nope", token=TOKEN)
    assert status == 404
    assert_error(doc, "not_found")


def test_other_http_methods_are_also_protected(server, monkeypatch):
    authorize(monkeypatch)
    status, _, headers = request(server, "/api/health", method="HEAD")
    assert status == 401
    assert headers["Cache-Control"] == "no-store"
    status, _, headers = request(server, "/api/health", method="HEAD", token=TOKEN)
    assert status == 405
    assert headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("method", ["TRACE", "CONNECT", "PROPFIND"])
def test_arbitrary_unsupported_verbs_use_authenticated_json_errors(
    server, monkeypatch, method
):
    status, doc, headers = raw_method_request(server, "/api/route", method)
    assert status == 503
    assert_error(doc, "configuration_error")
    assert_security_headers(headers)

    authorize(monkeypatch)
    status, doc, headers = raw_method_request(server, "/api/route", method)
    assert status == 401
    assert_error(doc, "unauthorized")
    assert_security_headers(headers)

    status, doc, headers = raw_method_request(server, "/api/route", method, TOKEN)
    assert status == 405
    assert_error(doc, "method_not_allowed")
    assert_security_headers(headers)
    assert headers["Content-Type"] == "application/json; charset=utf-8"


def test_dashboard_and_generator_are_truthful_and_atomic():
    index = (PACKAGE_ROOT / "index.html").read_text(encoding="utf-8")
    source = (PACKAGE_ROOT / "scripts" / "build_dashboard.py").read_text(encoding="utf-8")
    manifest = (PACKAGE_ROOT / "manifest.json").read_text(encoding="utf-8")
    forbidden = (
        "100% on Harness-Bench",
        "100% Harness-Bench",
        "8/8 GPT-5.2",
        "composite 0.31",
        "All runs to date succeeded",
        "Training corpus —",
        'href="/api/stats"',
        "LCG 20260813",
    )
    for phrase in forbidden:
        assert phrase not in index
        assert phrase not in source
        assert phrase not in manifest
    assert "No production model, corpus, analytics, or vector artifact is available." in index
    assert index == dashboard.PAGE
    assert (PACKAGE_ROOT / "index.html").read_bytes() == dashboard.PAGE.encode("utf-8")
    assert "encoding=\"utf-8\"" in source
    assert ".replace(" in source


def test_service_worker_never_intercepts_api_and_purges_legacy_entries():
    source = (PACKAGE_ROOT / "sw.js").read_text(encoding="utf-8")
    api_guard = "url.pathname.startsWith('/api/')"
    assert "dottie-v68-" in source
    assert api_guard in source
    assert source.index(api_guard) < source.index("respondWith")
    assert "cache.delete(request)" in source
    assert "caches.delete(cacheName)" in source
    assert "c.put(e.request" not in source


def test_vercel_api_route_precedes_host_catch_all():
    config = json.loads((PACKAGE_ROOT / "vercel.json").read_text(encoding="utf-8"))
    routes = config["routes"]
    api_index = next(index for index, route in enumerate(routes) if route.get("src") == "/api/(.*)")
    host_index = next(
        index
        for index, route in enumerate(routes)
        if any(condition.get("type") == "host" for condition in route.get("has", []))
    )
    assert api_index < host_index
    assert routes[api_index]["dest"] == "/api/index"


def test_manifest_and_deployment_preconditions_are_truthful():
    manifest = json.loads((PACKAGE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert "sota" not in manifest["name"].lower()
    readme = " ".join(
        (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8").lower().split()
    )
    for requirement in (
        "distributed rate limit",
        "canonical project owner",
        "secret rotation",
        "protected routes must remain unavailable",
        "current public readiness status: blocked",
        "canonical smoke verification",
        "not proof that vercel supplies the limiter",
    ):
        assert requirement in readme


def test_generator_refuses_to_overwrite_mismatched_output(tmp_path):
    output = tmp_path / "index.html"
    original = b"tracked output from another revision\n"
    output.write_bytes(original)

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        dashboard.atomic_write_utf8(output, dashboard.PAGE)

    assert output.read_bytes() == original
    assert not (tmp_path / ".index.html.tmp").exists()


def test_generator_allows_atomic_byte_identical_output(tmp_path):
    output = tmp_path / "index.html"
    expected = dashboard.PAGE.encode("utf-8")
    output.write_bytes(expected)

    dashboard.atomic_write_utf8(output, dashboard.PAGE)

    assert output.read_bytes() == expected
    assert not (tmp_path / ".index.html.tmp").exists()


def test_production_entrypoint_does_not_import_dormant_artifact_modules():
    source = API_PATH.read_text(encoding="utf-8")
    for forbidden_import in ("acne_graph", "heuristics", "orch_infer", "vector_router"):
        assert forbidden_import not in source
