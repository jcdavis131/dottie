"""Serverless HTTP entrypoint for the harness orchestration router.

Vercel Python runtime convention: this module exposes a class named
``handler`` subclassing ``http.server.BaseHTTPRequestHandler``. No web
framework — stdlib request handling plus the vendored numpy inference in
``lib/``.

Model loading is lazy and env-overridable:

* ``DOTTIE_HARNESS_WEIGHTS`` — path to a champion_weights.json (defaults to
  ``lib/weights/champion_weights.json``). Missing or invalid weights never
  crash the function: the API degrades to heuristic-only responses with
  ``model_loaded: false`` and ``learned: null``. Learned outputs are never
  fabricated when no weights are loaded.
* ``DOTTIE_HARNESS_META_DIR`` — directory holding vendored
  ``corpus_meta.json`` / ``eval_summary.json`` (defaults to ``lib/meta``).

Endpoints (all respond application/json):

* GET  /api/health — liveness + model/corpus status
* POST /api/route  — heuristic routing + learned prediction when loaded
* POST /api/plan   — deterministic DAG plan (static risk priors, labeled)
* GET  /api/stats  — vendored corpus meta + champion eval summary
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

_PKG_ROOT = Path(__file__).resolve().parents[1]
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from lib import heuristics, orch_infer

_DEFAULT_WEIGHTS = _PKG_ROOT / "lib" / "weights" / "champion_weights.json"
_DEFAULT_META_DIR = _PKG_ROOT / "lib" / "meta"

# Lazy caches — populated on first use, reset via _reset() (tests) and shared
# across warm invocations of the same serverless instance.
_CACHE: dict = {}


def _reset() -> None:
    """Clear the model/meta caches (test hook; also safe in production)."""
    _CACHE.clear()


# Fallback for deploys that ship without the 2.5 MB weights file: fetch the
# COMMITTED champion from the repository's raw URL once per cold start and
# cache it in /tmp. Same committed source, lazily materialized; override with
# DOTTIE_HARNESS_WEIGHTS_URL, disable by setting it empty.
_DEFAULT_WEIGHTS_URL = (
    "https://raw.githubusercontent.com/jcdavis131/dottie/"
    "claude/longcat-2-architecture-moxdny/"
    "apps/ava-factory/reports/orchestrator/champion_weights.json"
)


def _fetch_weights_to_tmp() -> str | None:
    url = os.environ.get("DOTTIE_HARNESS_WEIGHTS_URL", _DEFAULT_WEIGHTS_URL)
    if not url:
        return None
    import tempfile

    tmp = Path(tempfile.gettempdir()) / "champion_weights.json"
    if tmp.exists() and tmp.stat().st_size > 0:
        return str(tmp)
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310 — https URL, committed source
            body = resp.read()
        tmp.write_bytes(body)
        return str(tmp)
    except OSError:
        return None


def get_model() -> dict | None:
    """Load-and-cache champion weights; None when absent or invalid."""
    if "model" not in _CACHE:
        path = os.environ.get("DOTTIE_HARNESS_WEIGHTS") or str(_DEFAULT_WEIGHTS)
        try:
            _CACHE["model"] = orch_infer.load_weights(path)
        except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
            fetched = _fetch_weights_to_tmp()
            if fetched is not None:
                try:
                    _CACHE["model"] = orch_infer.load_weights(fetched)
                except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
                    _CACHE["model"] = None
            else:
                _CACHE["model"] = None
    return _CACHE["model"]


def _load_meta_file(name: str) -> dict | None:
    meta_dir = Path(os.environ.get("DOTTIE_HARNESS_META_DIR") or _DEFAULT_META_DIR)
    try:
        return json.loads((meta_dir / name).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None


def get_meta() -> dict:
    """Load-and-cache vendored metadata (corpus meta + eval summary)."""
    if "meta" not in _CACHE:
        _CACHE["meta"] = {
            "corpus_meta": _load_meta_file("corpus_meta.json"),
            "eval_summary": _load_meta_file("eval_summary.json"),
        }
    return _CACHE["meta"]


class handler(BaseHTTPRequestHandler):  # noqa: N801 — Vercel runtime convention
    def log_message(self, format: str, *args) -> None:
        # Quiet by default; serverless platform captures stdout/stderr anyway.
        pass

    # -- plumbing ---------------------------------------------------------

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> tuple[dict | None, str | None]:
        """Returns (doc, error). error is set on malformed input."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "invalid Content-Length"
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return None, "empty request body"
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, "malformed JSON body"
        if not isinstance(doc, dict):
            return None, "JSON body must be an object"
        return doc, None

    def _require_goal(self) -> str | None:
        """Parse the body and return a non-empty goal, or send a 400 and return None."""
        doc, err = self._read_json_body()
        if err is not None:
            self._send(400, {"ok": False, "error": err})
            return None
        goal = doc.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            self._send(400, {"ok": False, "error": "body must include a non-empty 'goal' string"})
            return None
        return goal

    # -- routes -----------------------------------------------------------

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            model = get_model()
            meta = get_meta()
            corpus_meta = meta["corpus_meta"]
            self._send(200, {
                "ok": True,
                "model_loaded": model is not None,
                "model_version": model["model_version"] if model else None,
                "gate_passed": model["gate_passed"] if model else None,
                "corpus_stats": (corpus_meta or {}).get("counts") if corpus_meta else None,
            })
        elif path == "/api/stats":
            meta = get_meta()
            self._send(200, {
                "ok": True,
                "corpus_meta": meta["corpus_meta"],
                "champion": meta["eval_summary"],
            })
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/route":
            goal = self._require_goal()
            if goal is None:
                return
            result = heuristics.route_goal(goal)
            model = get_model()
            # Provenance-honest: learned output exists only when real weights
            # are loaded — never fabricated.
            learned = orch_infer.predict(model, goal) if model is not None else None
            self._send(200, {
                "ok": True,
                **result,
                "learned": learned,
                "model_loaded": model is not None,
            })
        elif path == "/api/plan":
            goal = self._require_goal()
            if goal is None:
                return
            plan = heuristics.plan_goal(goal)
            self._send(200, {"ok": True, **plan})
        else:
            self._send(404, {"ok": False, "error": "not found"})
