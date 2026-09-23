#!/usr/bin/env python3
"""Typed System One ``POST /decide`` dev server (default 127.0.0.1:8771).

Port ownership: dottie-os, the local sidecar that serves System One on your
machine or tailnet, owns ``:8770``. This jev-v0 dev server defaults to
``:8771`` so both can run on one box; pass ``--port 8770`` only when this
process IS the sidecar.

Validates every request against frozen ``jev-decision-schema-1.0.0``.
Without ``--checkpoint`` it answers in ``mode=untrained`` (uniform over the
offered set): a wiring contract, not a model, and the router treats it as no
signal. With ``--checkpoint <dir>`` (a ``train_pointer_lora.py --go`` output)
it lazy-imports torch, answers in ``mode=pointer-lora``, and reports the
checkpoint's identity hash and its ``eval_summary.json`` gate in ``/health``.

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
    answer_from_probabilities,
    checkpoint_identity,
    load_schema,
    untrained_answer,
    validate_request,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8771  # dottie-os owns 8770; see the module docstring
SIDECAR_PORT = 8770
MAX_BODY = 64 * 1024


def decide(payload: Any, *, model: str, mode: str, predictor: Any = None) -> dict[str, Any]:
    """Answer every question. ``predictor`` (a loaded checkpoint) or uniform."""
    request = validate_request(payload)
    if predictor is None:
        answers = {
            qid: untrained_answer(question) for qid, question in request["questions"].items()
        }
    elif hasattr(predictor, "probabilities_many"):
        # one pass over the shared state prefix for every question (pointer_infer.SharedPrefixScorer)
        probs = predictor.probabilities_many(request["state"], request["questions"])
        answers = {
            qid: answer_from_probabilities(question, probs[qid])
            for qid, question in request["questions"].items()
        }
    else:
        answers = {
            qid: answer_from_probabilities(question, predictor.probabilities(request["state"], question))
            for qid, question in request["questions"].items()
        }
    return {
        "schema": SCHEMA_ID,
        "model": model,
        "mode": mode,
        "answers": answers,
    }


class DecideHandler(BaseHTTPRequestHandler):
    server_version = "jev-v0-decide/1.0"
    # HTTP/1.1: a client (the router's System One backend) keeps one connection
    # open across requests. Every response carries Content-Length, so this is safe.
    protocol_version = "HTTP/1.1"
    # headers and body go out in separate writes; with Nagle on, the body waits
    # for the client's delayed ACK (~40 ms per request on a kept-alive socket)
    disable_nagle_algorithm = True

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if self.close_connection:
            self.send_header("Connection", "close")
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
                    **self.server.checkpoint_info,
                    "not": ["train_1b", "TypeSafe parity"],
                },
            )
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path != "/decide":
            self.close_connection = True  # the unread body must not become the next request
            self._send(404, {"ok": False, "error": "not found"})
            return
        length_raw = self.headers.get("Content-Length", "")
        try:
            length = int(length_raw)
        except ValueError:
            self.close_connection = True
            self._send(400, {"ok": False, "error": "Content-Length required"})
            return
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
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
                predictor=self.server.predictor,
            )
        except SchemaError as exc:
            self._send(422, {"ok": False, "error": str(exc)})
            return
        self._send(200, body)


class DecideServer(ThreadingHTTPServer):
    def __init__(
        self,
        host: str,
        port: int,
        *,
        model: str,
        mode: str,
        predictor: Any = None,
        checkpoint_info: dict[str, Any] | None = None,
    ) -> None:
        super().__init__((host, port), DecideHandler)
        self.decide_model = model
        self.decide_mode = mode
        self.predictor = predictor
        self.checkpoint_info = checkpoint_info or {}


def checkpoint_info(checkpoint: Path) -> dict[str, Any]:
    """Identity + gate for ``/health``. Torch-free; the router's authority check reads it."""
    info: dict[str, Any] = {
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": checkpoint_identity(checkpoint),
        "gate_passed": False,
        "eval_summary": None,
    }
    summary_path = checkpoint / "eval_summary.json"
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            summary = {}
        same_bytes = summary.get("artifact_sha256") == info["checkpoint_sha256"]
        info["gate_passed"] = bool(summary.get("gate_passed") is True and same_bytes)
        info["eval_summary"] = {"present": True, "names_these_bytes": same_bytes}
    return info


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model", default=None, help="model label (default: jev-v0-untrained, or the checkpoint dir name)")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="train_pointer_lora.py --go output dir; serves mode=pointer-lora (needs torch)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_schema()
    if args.host not in {"127.0.0.1", "localhost", "::1"} and args.host != "0.0.0.0":
        # Still allowed, but say so. Loopback is the spike default.
        sys.stderr.write(f"binding {args.host}:{args.port} (not loopback)\n")
    predictor = None
    info: dict[str, Any] = {}
    mode = "untrained"
    model = args.model or "jev-v0-untrained"
    if args.checkpoint is not None:
        from pointer_infer import load_checkpoint  # lazy: torch only on this path

        predictor = load_checkpoint(args.checkpoint)
        info = checkpoint_info(args.checkpoint)
        mode = "pointer-lora"
        model = args.model or args.checkpoint.name
    if args.port == SIDECAR_PORT:
        sys.stderr.write(f"port {SIDECAR_PORT} is the dottie-os sidecar's; serving there as the sidecar\n")
    server = DecideServer(args.host, args.port, model=model, mode=mode, predictor=predictor, checkpoint_info=info)
    sys.stderr.write(
        f"jev-v0 /decide on http://{args.host}:{args.port}/decide "
        f"schema={SCHEMA_ID} mode={mode} (NOT train_1b, NOT TypeSafe parity)\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nstopped\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
