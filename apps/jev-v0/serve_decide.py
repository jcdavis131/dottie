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

A fixed veto pre-filter runs on every ``/decide`` before the model. It is a
pure function (no network, no config, no env kill-switch). Matching input
returns Choice=halt with ``veto_rule`` and does not call the model. A veto
parse exception is logged and the model still answers; the handler never
turns that into HTTP 500. The veto can only add a halt.

``/reload`` (any method) is the control plane. It is localhost-bound by
default (``DEFAULT_HOST``) and requires a constant-time compare against
``DOTTIE_OS_ADMIN_TOKEN``. Unauthenticated callers get 401; a bad token
gets 403. Reload refreshes checkpoint identity metadata only — it does not
read CURRENT.json, champion weights, or trust/.

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

from admin_auth import (
    authorize_admin,
    bearer_from_headers,
    configured_secret,
    is_admin_path,
)
from decision_io import (
    SCHEMA_ID,
    SchemaError,
    answer_from_probabilities,
    checkpoint_identity,
    load_schema,
    untrained_answer,
    validate_request,
)
from veto import strengthen_choice, veto_body, veto_from_payload

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8771  # dottie-os owns 8770; see the module docstring
SIDECAR_PORT = 8770
MAX_BODY = 64 * 1024


def _log_veto_exception(exc: BaseException) -> None:
    sys.stderr.write("veto_error: %s: %s\n" % (type(exc).__name__, exc))


def decide(payload: Any, *, model: str, mode: str, predictor: Any = None) -> dict[str, Any]:
    """Answer every question. Veto runs first and, on a hit, skips ``predictor``."""
    request = validate_request(payload)
    rule: str | None = None
    try:
        rule = veto_from_payload(request)
    except Exception as exc:
        _log_veto_exception(exc)
        rule = None
    if rule:
        return veto_body(request, model=model, rule=rule)
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
    action = answers.get("action")
    if isinstance(action, dict) and "choice" in action:
        action["choice"] = strengthen_choice(action.get("choice"), None)
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

    def _consume_body(self) -> bytes | None:
        length_raw = self.headers.get("Content-Length", "")
        if length_raw == "":
            return b""
        try:
            length = int(length_raw)
        except ValueError:
            self.close_connection = True
            self._send(400, {"ok": False, "error": "Content-Length required"})
            return None
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            self._send(413, {"ok": False, "error": f"body exceeds {MAX_BODY} bytes"})
            return None
        return self.rfile.read(length)

    def _admin(self, method: str) -> None:
        raw = self._consume_body()
        if raw is None:
            return
        peer = self.client_address[0] if self.client_address else ""
        token = bearer_from_headers(
            self.headers.get("Authorization"),
            self.headers.get("X-Admin-Token"),
        )
        status, error = authorize_admin(peer=peer, token=token, secret=configured_secret())
        if status != 200:
            self._send(status, {"ok": False, "error": error})
            return
        info = self.server.reload_identity()
        self._send(
            200,
            {
                "ok": True,
                "method": method,
                "path": urlparse(self.path).path,
                "reloaded": bool(info.get("reloaded")),
                **{k: v for k, v in info.items() if k != "reloaded"},
            },
        )

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if is_admin_path(path):
            self._admin("GET")
            return
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
        if is_admin_path(path):
            self._admin("POST")
            return
        if path != "/decide":
            self.close_connection = True  # the unread body must not become the next request
            self._send(404, {"ok": False, "error": "not found"})
            return
        raw = self._consume_body()
        if raw is None:
            return
        if raw == b"" and self.headers.get("Content-Length", "") == "":
            self.close_connection = True
            self._send(400, {"ok": False, "error": "Content-Length required"})
            return
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
        except Exception as exc:
            # Veto parse errors are swallowed inside decide(). Anything else
            # still must not become an uncaught 500 from the veto path.
            _log_veto_exception(exc)
            self._send(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        self._send(200, body)

    def do_PUT(self) -> None:  # noqa: N802
        self._admin_or_404("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._admin_or_404("DELETE")

    def do_PATCH(self) -> None:  # noqa: N802
        self._admin_or_404("PATCH")

    def do_HEAD(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if is_admin_path(path):
            self._admin("HEAD")
            return
        if path in {"/", "/health"}:
            self.do_GET()
            return
        self._send(404, {"ok": False, "error": "not found"})

    def _admin_or_404(self, method: str) -> None:
        path = urlparse(self.path).path
        if is_admin_path(path):
            self._admin(method)
            return
        self.close_connection = True
        self._send(404, {"ok": False, "error": "not found"})


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
        checkpoint_path: Path | None = None,
    ) -> None:
        super().__init__((host, port), DecideHandler)
        self.decide_model = model
        self.decide_mode = mode
        self.predictor = predictor
        self.checkpoint_info = checkpoint_info or {}
        self.checkpoint_path = checkpoint_path

    def reload_identity(self) -> dict[str, Any]:
        """Refresh /health identity from the boot checkpoint path. No weight swap."""
        path = self.checkpoint_path
        if path is None:
            return {**self.checkpoint_info, "reloaded": False, "reason": "untrained"}
        self.checkpoint_info = checkpoint_info(path)
        return {**self.checkpoint_info, "reloaded": True}


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
    checkpoint_path = args.checkpoint
    if args.checkpoint is not None:
        from pointer_infer import load_checkpoint  # lazy: torch only on this path

        predictor = load_checkpoint(args.checkpoint)
        info = checkpoint_info(args.checkpoint)
        mode = "pointer-lora"
        model = args.model or args.checkpoint.name
    if args.port == SIDECAR_PORT:
        sys.stderr.write(f"port {SIDECAR_PORT} is the dottie-os sidecar's; serving there as the sidecar\n")
    server = DecideServer(
        args.host,
        args.port,
        model=model,
        mode=mode,
        predictor=predictor,
        checkpoint_info=info,
        checkpoint_path=checkpoint_path,
    )
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
