#!/usr/bin/env python3
"""Forge-runner HELPER FT ``POST /train/kickoff`` handler (:8765).

Re-hashes run-private pack/train/holdout itself and compares those digests
with the request shas and with the CLI/HQ anchors. An evidence blob that
exists or says ``ok: true`` is not enough.

``inbox: latest`` and every other HELPER FT start route are refused. Stdlib
only. Does not promote, does not touch serve, :8770, or champion files.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from wsgiref.simple_server import make_server

CHUNK = 1 << 20
SHA256_LEN = 64
_HEX = frozenset("0123456789abcdef")
MAX_EVIDENCE_AGE_SECONDS = 15 * 60
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SHA_FIELDS = (
    ("sha256_pack", "pack"),
    ("sha256_train", "train"),
    ("sha256_holdout", "holdout"),
)
# Every HELPER FT start path other than POST /train/kickoff.
OTHER_HELPER_FT_START_PATHS = frozenset(
    {
        "/train/start",
        "/train/run",
        "/train/helper",
        "/train/helper-ft",
        "/train/inbox-validate",
        "/train/inbox",
        "/train/kick",
        "/inbox/latest",
        "/train/kickoff/latest",
    }
)
LaunchTrainer = Callable[[dict[str, Any]], dict[str, Any]]


def _bad(field: str, expected: object, actual: object) -> dict[str, Any]:
    return {
        "ok": False,
        "field": field,
        "expected": expected,
        "actual": actual,
        "error": f"HELPER FT kickoff refused: {field}: expected {expected} actual {actual}",
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                break
            digest.update(block)
    finally:
        os.close(fd)
    return digest.hexdigest()


def _require_sha(field: str, value: object) -> str | dict[str, Any]:
    if not isinstance(value, str) or not value:
        return _bad(field, "present", "missing")
    lowered = value.strip().lower()
    if len(lowered) != SHA256_LEN or any(ch not in _HEX for ch in lowered):
        return _bad(field, "64-char hex", value)
    return lowered


def _parse_checked_at(value: object) -> datetime | dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        return _bad("checked_at", "present", "missing")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return _bad("checked_at", "ISO-8601 UTC", value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def default_launch_trainer(body: dict[str, Any]) -> dict[str, Any]:
    """Below-gate launch hook. This tree does not run GPU training."""
    del body
    return {"ok": True, "checkpoint_id": None, "launched": True}


def handle_train_kickoff(
    body: dict[str, Any] | None,
    *,
    launch_trainer: LaunchTrainer | None = None,
) -> dict[str, Any]:
    """Refuse HELPER FT kickoff unless re-hashed files match request + anchor.

    ``inbox: latest`` is never accepted. Evidence ``ok: true`` is not trust.
    """
    if not isinstance(body, dict):
        return _bad("body", "object", type(body).__name__)
    inbox = body.get("inbox")
    mode = body.get("mode")
    if isinstance(inbox, str) and inbox.strip().lower() == "latest":
        return _bad("inbox", "named pack_id", "latest")
    if mode == "inbox-validate":
        return _bad("mode", "helper-ft", "inbox-validate")
    if mode != "helper-ft":
        return _bad("mode", "helper-ft", mode)
    evidence = body.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        return _bad("evidence", "present", "missing")
    if evidence.get("ok") is not True:
        return _bad("evidence.ok", True, evidence.get("ok"))
    pack_id = body.get("pack_id")
    if not isinstance(pack_id, str) or not pack_id:
        return _bad("pack_id", "present", "missing")
    if evidence.get("pack_id") != pack_id:
        return _bad("pack_id", pack_id, evidence.get("pack_id"))
    run_id = body.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return _bad("run_id", "present", "missing")
    ev_run = evidence.get("run_id")
    if ev_run != run_id:
        return _bad("evidence.run_id", run_id, ev_run)
    checked = _parse_checked_at(evidence.get("checked_at") or body.get("checked_at"))
    if isinstance(checked, dict):
        return checked
    age = (datetime.now(timezone.utc) - checked).total_seconds()
    if age > MAX_EVIDENCE_AGE_SECONDS or age < -60:
        return _bad("checked_at", f"age<={MAX_EVIDENCE_AGE_SECONDS}s", f"age={int(age)}s")
    evidence_path = body.get("evidence_path") or evidence.get("evidence_path")
    if isinstance(evidence_path, str) and evidence_path:
        disk_path = Path(evidence_path)
        if not disk_path.is_file():
            return _bad("evidence_path", "present", "missing")
        try:
            disk_ev = json.loads(disk_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return _bad("evidence_path", "readable JSON", type(exc).__name__)
        if not isinstance(disk_ev, dict):
            return _bad("evidence_path", "object", type(disk_ev).__name__)
        if disk_ev.get("run_id") != run_id:
            return _bad("evidence.run_id", run_id, disk_ev.get("run_id"))
        if disk_ev.get("ok") is False:
            return _bad("evidence.ok", True, False)
    paths = body.get("paths")
    if not isinstance(paths, dict) or not paths:
        return _bad("paths", "present", "missing")
    body_anchor = body.get("expected_shas")
    if not isinstance(body_anchor, dict) or not body_anchor:
        return _bad("expected_shas", "present", "missing")
    ev_anchor = evidence.get("expected_shas")
    if not isinstance(ev_anchor, dict) or not ev_anchor:
        return _bad("evidence.expected_shas", "present", "missing")
    computed = evidence.get("computed_shas") if isinstance(evidence.get("computed_shas"), dict) else {}
    for sha_field, path_key in SHA_FIELDS:
        req = _require_sha(sha_field, body.get(sha_field))
        if isinstance(req, dict):
            return req
        anchor = _require_sha(f"expected_shas.{sha_field}", body_anchor.get(sha_field))
        if isinstance(anchor, dict):
            return anchor
        ev_expected = _require_sha(f"evidence.expected_shas.{sha_field}", ev_anchor.get(sha_field))
        if isinstance(ev_expected, dict):
            return ev_expected
        if req != anchor:
            return _bad(sha_field, anchor, req)
        if ev_expected != anchor:
            return _bad(sha_field, anchor, ev_expected)
        named = paths.get(path_key)
        if not isinstance(named, str) or not named:
            return _bad(f"paths.{path_key}", "present", "missing")
        path = Path(named)
        if not path.is_file():
            return _bad(path_key, "present", "missing")
        try:
            actual = _sha256_file(path)
        except OSError as exc:
            return _bad(path_key, "readable regular file", f"OSError:{exc.errno}")
        if actual != req:
            return _bad(sha_field, req, actual)
        if actual != anchor:
            return _bad(sha_field, anchor, actual)
        ev_computed = computed.get(sha_field)
        if ev_computed is not None and actual != ev_computed:
            return _bad(sha_field, ev_computed, actual)
    launcher = launch_trainer if launch_trainer is not None else default_launch_trainer
    launched = launcher(body)
    if not isinstance(launched, dict) or launched.get("ok") is not True:
        return _bad("trainer", "ok", launched)
    result = {"ok": True, "pack_id": pack_id, "run_id": run_id, "launched": True}
    if launched.get("checkpoint_id"):
        result["checkpoint_id"] = launched["checkpoint_id"]
    return result


def _json_status(payload: dict[str, Any]) -> str:
    return "200 OK" if payload.get("ok") is True else "400 Bad Request"


def dispatch(
    method: str,
    path: str,
    body: dict[str, Any] | None,
    *,
    launch_trainer: LaunchTrainer | None = None,
    query: str = "",
) -> tuple[str, dict[str, Any]]:
    """Route table for :8765. Only POST /train/kickoff can start HELPER FT."""
    method = (method or "").upper()
    path = path or "/"
    if "inbox=latest" in (query or "").lower():
        payload = _bad("inbox", "named pack_id", "latest")
        return _json_status(payload), payload
    if path.rstrip("/").endswith("/latest"):
        payload = _bad("inbox", "named pack_id", "latest")
        return _json_status(payload), payload
    if path.rstrip("/") in OTHER_HELPER_FT_START_PATHS or path in OTHER_HELPER_FT_START_PATHS:
        payload = _bad("route", "POST /train/kickoff", f"{method} {path}")
        return _json_status(payload), payload
    if path.rstrip("/") != "/train/kickoff":
        payload = _bad("route", "POST /train/kickoff", f"{method} {path}")
        return _json_status(payload), payload
    if method != "POST":
        payload = _bad("method", "POST", method)
        return _json_status(payload), payload
    payload = handle_train_kickoff(body, launch_trainer=launch_trainer)
    return _json_status(payload), payload


def make_app(*, launch_trainer: LaunchTrainer | None = None):
    """WSGI app for ``POST http://127.0.0.1:8765/train/kickoff``."""

    def app(environ: dict[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
        method = str(environ.get("REQUEST_METHOD") or "GET")
        path = str(environ.get("PATH_INFO") or "/")
        query = str(environ.get("QUERY_STRING") or "")
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        raw = environ.get("wsgi.input").read(length) if length else b""
        parsed: dict[str, Any] | None
        if not raw:
            parsed = None
        else:
            try:
                loaded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                payload = _bad("body", "JSON object", "invalid JSON")
                blob = json.dumps(payload).encode("utf-8")
                start_response(
                    "400 Bad Request",
                    [("Content-Type", "application/json"), ("Content-Length", str(len(blob)))],
                )
                return [blob]
            parsed = loaded if isinstance(loaded, dict) else None
            if parsed is None:
                payload = _bad("body", "object", type(loaded).__name__)
                blob = json.dumps(payload).encode("utf-8")
                start_response(
                    "400 Bad Request",
                    [("Content-Type", "application/json"), ("Content-Length", str(len(blob)))],
                )
                return [blob]
        status, payload = dispatch(
            method, path, parsed, launch_trainer=launch_trainer, query=query
        )
        blob = json.dumps(payload).encode("utf-8")
        start_response(
            status,
            [("Content-Type", "application/json"), ("Content-Length", str(len(blob)))],
        )
        return [blob]

    return app


class TestResponse:
    """Minimal response object for :class:`TestClient`."""

    def __init__(self, status: str, body: bytes) -> None:
        self.status = status
        self.status_code = int(status.split()[0])
        self.body = body

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else {}


class TestClient:
    """In-process WSGI test client for the real :8765 handler. No GPU, no TCP."""

    def __init__(self, *, launch_trainer: LaunchTrainer | None = None) -> None:
        self.app = make_app(launch_trainer=launch_trainer)

    def post(self, path: str, json: dict[str, Any] | None = None) -> TestResponse:
        return self.request("POST", path, body=json)

    def get(self, path: str) -> TestResponse:
        return self.request("GET", path)

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> TestResponse:
        route, _, query = path.partition("?")
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": route,
            "QUERY_STRING": query,
            "wsgi.input": BytesIO(payload),
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.errors": sys.stderr,
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": True,
        }
        captured: dict[str, Any] = {"status": "500 Internal Server Error"}

        def start_response(status: str, _headers: list[tuple[str, str]], exc_info: Any = None) -> None:
            del exc_info
            captured["status"] = status

        parts = self.app(environ, start_response)
        return TestResponse(captured["status"], b"".join(parts))


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    launch_trainer: LaunchTrainer | None = None,
) -> None:
    httpd = make_server(host, port, make_app(launch_trainer=launch_trainer))
    httpd.serve_forever()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--serve":
        serve()
        return 0
    raise SystemExit(
        "helper_ft_kickoff is the :8765 HELPER FT handler; factory-trainer POSTs JSON "
        "to POST /train/kickoff (or pass --serve)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
