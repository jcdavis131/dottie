#!/usr/bin/env python3
"""Typed System One ``POST /decide`` on 127.0.0.1:8770.

Validates every request against frozen ``jev-decision-schema-1.0.0``.
Without a pointer checkpoint this process answers in ``mode=untrained``
(uniform over the offered set). That is a wiring contract, not a model.

This is NOT TypeSafe ``/v1/systemone`` parity and it does not call
TypeSafe. Bind stays loopback unless ``--host`` is set.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_APP = Path(__file__).resolve().parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from decision_io import (
    SCHEMA_ID,
    SchemaError,
    load_schema,
    untrained_answer,
    validate_request,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8770
MAX_BODY = 64 * 1024


def decide(payload: Any, *, model: str, mode: str) -> dict[str, Any]:
    request = validate_request(payload)
    answers = {
        qid: untrained_answer(question) for qid, question in request["questions"].items()
    }
    return {
        "schema": SCHEMA_ID,
        "model": model,
        "mode": mode,
        "answers": answers,
    }


class DecideHandler(BaseHTTPRequestHandler):
    server_version = "jev-v0-decide/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path in {"/", "/health"}:
            self._send(
                200,
                {
                    "ok": True,
                    "schema": SCHEMA_ID,
                    "model": self.server.decide_model,
                    "mode": self.server.decide_mode,
                    "decide": "/decide",
                    "not": ["train_1b", "TypeSafe parity"],
                },
            )
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path != "/decide":
            self._send(404, {"ok": False, "error": "not found"})
            return
        length_raw = self.headers.get("Content-Length", "")
        try:
            length = int(length_raw)
        except ValueError:
            self._send(400, {"ok": False, "error": "Content-Length required"})
            return
        if length < 0 or length > MAX_BODY:
            self._send(413, {"ok": False, "error": f"body exceeds {MAX_BODY} bytes"})
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send(400, {"ok": False, "error": f"invalid JSON: {exc}"})
            return
        try:
            body = decide(
                payload,
                model=self.server.decide_model,
                mode=self.server.decide_mode,
            )
        except SchemaError as exc:
            self._send(422, {"ok": False, "error": str(exc)})
            return
        self._send(200, body)


class DecideServer(ThreadingHTTPServer):
    def __init__(self, host: str, port: int, *, model: str, mode: str) -> None:
        super().__init__((host, port), DecideHandler)
        self.decide_model = model
        self.decide_mode = mode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model", default="jev-v0-untrained")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_schema()
    if args.host not in {"127.0.0.1", "localhost", "::1"} and args.host != "0.0.0.0":
        # Still allowed, but say so. Loopback is the spike default.
        sys.stderr.write(f"binding {args.host}:{args.port} (not loopback)\n")
    server = DecideServer(args.host, args.port, model=args.model, mode="untrained")
    sys.stderr.write(
        f"jev-v0 /decide on http://{args.host}:{args.port}/decide "
        f"schema={SCHEMA_ID} mode=untrained (NOT train_1b, NOT TypeSafe parity)\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nstopped\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
