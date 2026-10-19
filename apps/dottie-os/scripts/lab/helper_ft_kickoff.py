#!/usr/bin/env python3
"""Forge-runner HELPER FT ``POST /train/kickoff`` handler (:8765).

Re-fetches the Cam-stamped pack-pin from Swarm HQ over HTTPS, then re-hashes
and re-counts run-private pack/train/holdout. ``stampVerified`` and
``pack_matches`` must both be true, but ``pack_matches`` is never sufficient:
the pin's pack_id, three shas, and three row counts are compared with this
handler's own hashes and counts of the copies plus the MANIFEST. A pin
carried only in the request body is not provenance. An evidence blob that
exists or says ``ok: true`` is not enough.

``inbox: latest`` and every other HELPER FT start route are refused. Stdlib
only. Does not promote, does not touch serve, :8770, or champion files.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
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
SWARM_HQ_URL_ENV = "SWARM_HQ_URL"
SWARM_HQ_AGENT_TOKEN_ENV = "SWARM_HQ_AGENT_TOKEN"
CAM_RECORDED_BY = "cam"
PIN_SOURCE = "swarm-hq-cam-pin"
HQ_PIN_REQUIRED_KEYS = (
    "pack_id",
    "sha256_pack",
    "sha256_train",
    "sha256_holdout",
    "rows_total",
    "rows_train",
    "rows_holdout",
    "pack_matches",
    "recordedBy",
    "recordedAt",
    "kid",
)
HQ_PIN_ALLOWED_KEYS = frozenset((*HQ_PIN_REQUIRED_KEYS, "stampVerified", "verified"))
# (sha field, paths key, MANIFEST row field, pin row field)
ARTIFACTS = (
    ("sha256_pack", "pack", "rows", "rows_total"),
    ("sha256_train", "train", "train_rows", "rows_train"),
    ("sha256_holdout", "holdout", "holdout_rows", "rows_holdout"),
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


def _require_int(field: str, value: object) -> int | dict[str, Any]:
    if type(value) is not int:
        label = "bool" if isinstance(value, bool) else type(value).__name__
        return _bad(field, "int", label)
    return value


def _count_rows(path: Path) -> int | dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except UnicodeDecodeError:
        return _bad(path.name, "utf-8 text", "invalid encoding")
    except OSError as exc:
        return _bad(path.name, "readable text file", f"OSError:{exc.errno}")


def _read_kickoff_manifest(paths: dict[str, Any]) -> dict[str, Any]:
    named = paths.get("manifest")
    if not isinstance(named, str) or not named:
        pack = paths.get("pack")
        if isinstance(pack, str) and pack:
            named = str(Path(pack).parent / "MANIFEST.json")
        else:
            return _bad("paths.manifest", "present", "missing")
    path = Path(named)
    if not path.is_file():
        return _bad("MANIFEST.json", "present", "missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return _bad("MANIFEST.json", "utf-8 text", "invalid encoding")
    except (OSError, ValueError) as exc:
        return _bad("MANIFEST.json", "readable JSON", type(exc).__name__)
    if not isinstance(payload, dict):
        return _bad("MANIFEST.json", "object", type(payload).__name__)
    return payload


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


def _parse_hq_pin_payload(payload: object) -> dict[str, Any]:
    """Parse Swarm HQ's flat pin JSON. Unknown or missing keys refuse."""
    if not isinstance(payload, dict) or not payload:
        return _bad("cam-pin", "present", "missing")
    unknown = [key for key in payload if key not in HQ_PIN_ALLOWED_KEYS]
    if unknown:
        return _bad("cam-pin", "HQ pin keys", f"unknown {unknown[0]}")
    for key in HQ_PIN_REQUIRED_KEYS:
        if key not in payload:
            return _bad(f"cam-pin.{key}", "present", "missing")
    recorded_at = payload.get("recordedAt")
    if not isinstance(recorded_at, str) or not recorded_at.strip():
        return _bad("cam-pin.recordedAt", "present", "missing")
    kid = payload.get("kid")
    if not isinstance(kid, str) or not kid.strip():
        return _bad("cam-pin.kid", "present", "missing")
    has_stamp = "stampVerified" in payload
    has_alias = "verified" in payload
    if not has_stamp and not has_alias:
        return _bad("cam-pin.stampVerified", "present", "missing")
    stamp = payload.get("stampVerified") if has_stamp else payload.get("verified")
    if has_stamp and has_alias and payload.get("stampVerified") is not payload.get("verified"):
        return _bad("cam-pin.stampVerified", payload.get("stampVerified"), payload.get("verified"))
    if type(stamp) is not bool:
        return _bad("cam-pin.stampVerified", "bool", type(stamp).__name__)
    matches = payload.get("pack_matches")
    if type(matches) is not bool:
        return _bad("cam-pin.pack_matches", "bool", type(matches).__name__)
    record = {key: payload[key] for key in HQ_PIN_REQUIRED_KEYS}
    record["stampVerified"] = stamp
    record["pack_matches"] = matches
    for row_key in ("rows_total", "rows_train", "rows_holdout"):
        typed = _require_int(f"cam-pin.{row_key}", payload.get(row_key))
        if isinstance(typed, dict):
            return typed
        record[row_key] = typed
    return record


def fetch_cam_pin(pack_id: str) -> dict[str, Any]:
    """GET ``{SWARM_HQ_URL}/api/packs/<pack_id>/pin`` over HTTPS. Never Redis."""
    if not isinstance(pack_id, str) or not pack_id.strip():
        return _bad("pack_id", "present", "missing")
    base = os.environ.get(SWARM_HQ_URL_ENV)
    if not isinstance(base, str) or not base.strip():
        return _bad(SWARM_HQ_URL_ENV, "present", "missing")
    base = base.strip()
    if not base.lower().startswith("https://"):
        return _bad(SWARM_HQ_URL_ENV, "https URL", base)
    token = os.environ.get(SWARM_HQ_AGENT_TOKEN_ENV)
    if not isinstance(token, str) or not token.strip():
        return _bad(SWARM_HQ_AGENT_TOKEN_ENV, "present", "missing")
    url = base.rstrip("/") + "/api/packs/" + urllib.parse.quote(pack_id.strip(), safe="") + "/pin"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "x-agent-token": token.strip(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            blob = response.read()
            status = getattr(response, "status", None) or response.getcode()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return _bad("cam-pin", "authorized", "HTTP 401")
        if exc.code == 404:
            return _bad("cam-pin", "present", "HTTP 404")
        return _bad("cam-pin", "HTTPS Swarm HQ pin", f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or exc
        return _bad("cam-pin", "HTTPS Swarm HQ pin", f"unreachable:{reason}")
    except OSError as exc:
        return _bad("cam-pin", "HTTPS Swarm HQ pin", f"OSError:{getattr(exc, 'errno', None)}")
    if status not in (200, None) and int(status) != 200:
        return _bad("cam-pin", "HTTPS Swarm HQ pin", f"HTTP {status}")
    try:
        raw = blob.decode("utf-8")
    except UnicodeDecodeError:
        return _bad("cam-pin", "utf-8 JSON", "invalid encoding")
    duplicates: list[str] = []

    def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                duplicates.append(key)
            seen[key] = value
        return seen

    try:
        payload = json.loads(raw, object_pairs_hook=_unique) if raw else None
    except ValueError:
        return _bad("cam-pin", "JSON object", "invalid JSON")
    if duplicates:
        return _bad("cam-pin", "unique keys", f"duplicate {duplicates[0]}")
    parsed = _parse_hq_pin_payload(payload)
    if parsed.get("ok") is False:
        return parsed
    return {"ok": True, "pin": parsed}


def require_hq_cam_pin(pack_id: str) -> dict[str, Any]:
    """Re-fetch the Cam pin. A request-body pin is not provenance."""
    fetched = fetch_cam_pin(pack_id)
    if fetched.get("ok") is not True:
        return fetched
    record = fetched.get("pin")
    if not isinstance(record, dict) or not record:
        return _bad("cam-pin", "present", "missing")
    if record.get("recordedBy") != CAM_RECORDED_BY:
        return _bad("cam-pin.recordedBy", CAM_RECORDED_BY, record.get("recordedBy"))
    if record.get("stampVerified") is not True:
        return _bad("cam-pin.stampVerified", True, record.get("stampVerified"))
    if record.get("pack_matches") is not True:
        return _bad("cam-pin.pack_matches", True, record.get("pack_matches"))
    pin_pack = record.get("pack_id")
    if not isinstance(pin_pack, str) or not pin_pack.strip():
        return _bad("cam-pin.pack_id", "present", "missing")
    if pin_pack.strip() != pack_id:
        return _bad("cam-pin.pack_id", pack_id, pin_pack)
    pin: dict[str, Any] = {
        "pack_id": pack_id,
        "recordedBy": CAM_RECORDED_BY,
        "stampVerified": True,
        "pack_matches": True,
        "source": PIN_SOURCE,
    }
    for sha_field, _path_key, _manifest_rows, pin_rows_field in ARTIFACTS:
        required = _require_sha(f"cam-pin.{sha_field}", record.get(sha_field))
        if isinstance(required, dict):
            return required
        pin[sha_field] = required
        rows = _require_int(f"cam-pin.{pin_rows_field}", record.get(pin_rows_field))
        if isinstance(rows, dict):
            return rows
        pin[pin_rows_field] = rows
    return {"ok": True, "pin": pin}


def handle_train_kickoff(
    body: dict[str, Any] | None,
    *,
    launch_trainer: LaunchTrainer | None = None,
) -> dict[str, Any]:
    """Refuse HELPER FT kickoff unless HQ pin matches re-hashed files.

    Re-fetches the Cam pin from Swarm HQ. A body-only pin is refused.
    ``pack_matches`` is necessary, never sufficient. ``inbox: latest`` is
    never accepted. Evidence ``ok: true`` is not trust.
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
    pin = body.get("pin")
    if not isinstance(pin, dict) or not pin:
        return _bad("pin", "present", "missing")
    if pin.get("recordedBy") != CAM_RECORDED_BY:
        return _bad("pin.recordedBy", CAM_RECORDED_BY, pin.get("recordedBy"))
    if pin.get("stampVerified") is not True:
        return _bad("pin.stampVerified", True, pin.get("stampVerified"))
    if pin.get("pack_matches") is not True:
        return _bad("pin.pack_matches", True, pin.get("pack_matches"))
    if pin.get("pack_id") != pack_id:
        return _bad("pin.pack_id", pack_id, pin.get("pack_id"))
    hq = require_hq_cam_pin(pack_id)
    if hq.get("ok") is not True:
        return hq
    hq_pin = hq["pin"]
    paths = body.get("paths")
    if not isinstance(paths, dict) or not paths:
        return _bad("paths", "present", "missing")
    manifest = _read_kickoff_manifest(paths)
    if manifest.get("ok") is False and "field" in manifest:
        return manifest
    ev_anchor = evidence.get("pin") if isinstance(evidence.get("pin"), dict) else evidence.get("expected_shas")
    if not isinstance(ev_anchor, dict) or not ev_anchor:
        return _bad("evidence.pin", "present", "missing")
    computed = evidence.get("computed_shas") if isinstance(evidence.get("computed_shas"), dict) else {}
    for sha_field, path_key, manifest_rows_field, pin_rows_field in ARTIFACTS:
        req = _require_sha(sha_field, body.get(sha_field))
        if isinstance(req, dict):
            return req
        hq_sha = hq_pin[sha_field]
        body_sha = _require_sha(f"pin.{sha_field}", pin.get(sha_field))
        if isinstance(body_sha, dict):
            return body_sha
        if body_sha != hq_sha:
            return _bad(sha_field, hq_sha, body_sha)
        ev_expected = _require_sha(f"evidence.pin.{sha_field}", ev_anchor.get(sha_field))
        if isinstance(ev_expected, dict):
            return ev_expected
        if req != hq_sha:
            return _bad(sha_field, hq_sha, req)
        if ev_expected != hq_sha:
            return _bad(sha_field, hq_sha, ev_expected)
        pin_rows = hq_pin[pin_rows_field]
        body_rows = _require_int(f"pin.{pin_rows_field}", pin.get(pin_rows_field))
        if isinstance(body_rows, dict):
            return body_rows
        if body_rows != pin_rows:
            return _bad(pin_rows_field, pin_rows, body_rows)
        if manifest_rows_field not in manifest:
            return _bad(manifest_rows_field, "present", "missing")
        expected_rows = _require_int(manifest_rows_field, manifest[manifest_rows_field])
        if isinstance(expected_rows, dict):
            return expected_rows
        if pin_rows != expected_rows:
            return _bad(pin_rows_field, pin_rows, expected_rows)
        named = paths.get(path_key)
        if not isinstance(named, str) or not named:
            return _bad(f"paths.{path_key}", "present", "missing")
        path = Path(named)
        if not path.is_file():
            return _bad(path_key, "present", "missing")
        counted = _count_rows(path)
        if isinstance(counted, dict):
            return counted
        if pin_rows != counted:
            return _bad(pin_rows_field, pin_rows, counted)
        try:
            actual = _sha256_file(path)
        except OSError as exc:
            return _bad(path_key, "readable regular file", f"OSError:{exc.errno}")
        if actual != req:
            return _bad(sha_field, req, actual)
        if actual != hq_sha:
            return _bad(sha_field, hq_sha, actual)
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
