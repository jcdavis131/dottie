# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Minimal HTTP server for the trained state-model. Stdlib only (no Flask).

Endpoints:
    GET  /health   -> {"ok": true, "model_id": ..., "calibration": ...}
    POST /decide   -> {"state": {...}, "query": {...}}
                      -> {"best": {"value":..., "confidence":...},
                          "alternatives": [...], "model_id": ..., "calibration": ...}

Run on nugatron:
    python3 -m dottie_core.serving.server --weights training/out/weights.json --port 8766

The server reconstructs WorldState from the posted belief list. State and
query schemas match dottie_core.state / dottie_core.model dataclasses.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dottie_core.state import Belief, Constraints, StateRef, WorldState  # noqa: E402
from dottie_core.model import TypedQuery  # noqa: E402
from dottie_core.trained import TrainedModel  # noqa: E402


def _state_from_dict(d: dict) -> WorldState:
    beliefs = {}
    for b in d.get("beliefs", []):
        belief = Belief(
            belief_id=b["belief_id"], key=b["key"], value=b["value"],
            confidence=float(b["confidence"]), source=b["source"],
            at_version=int(b.get("at_version", 0)), supersedes=b.get("supersedes"),
        )
        beliefs[belief.key] = belief
    c = d.get("constraints", {})
    constraints = Constraints(
        max_cost_units=float(c.get("max_cost_units", 100.0)),
        deadline_iso=c.get("deadline_iso"),
        side_effect_class=c.get("side_effect_class", "read_only"),
        require_hitl_for=tuple(c.get("require_hitl_for", ())),
    )
    return WorldState(
        version=int(d.get("version", 0)),
        goal_id=str(d.get("goal_id", "served")),
        beliefs=beliefs,
        actions_taken=tuple(),
        constraints=constraints,
        domain=dict(d.get("domain", {})),
    )


def _query_from_dict(d: dict) -> TypedQuery:
    return TypedQuery(
        kind=d["kind"],
        state_ref=StateRef(
            belief_keys=tuple(d.get("state_ref", {}).get("belief_keys", ())),
            include_actions=bool(d.get("state_ref", {}).get("include_actions", False)),
            include_constraints=bool(d.get("state_ref", {}).get("include_constraints", True)),
            domain_keys=tuple(d.get("state_ref", {}).get("domain_keys", ())),
        ),
        schema=dict(d.get("schema", {})),
        options=tuple(d.get("options", ())),
        claim=str(d.get("claim", "")),
    )


def _answer_to_dict(ans) -> dict:
    return {
        "best": {"value": ans.best.value, "confidence": ans.best.confidence},
        "alternatives": [{"value": a.value, "confidence": a.confidence}
                         for a in ans.alternatives],
        "query_id": ans.query_id,
        "model_id": ans.model_id,
        "calibration": ans.calibration,
    }


class Handler(BaseHTTPRequestHandler):
    model: TrainedModel | None = None  # set by serve()

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            m = self.model
            self._send(200, {"ok": True, "model_id": m.model_id if m else None,
                             "calibration": m.calibration if m else None})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/decide":
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            state = _state_from_dict(body["state"])
            query = _query_from_dict(body["query"])
            ans = self.model.decide(state, query)  # type: ignore[union-attr]
            self._send(200, {"ok": True, **_answer_to_dict(ans)})
        except Exception as e:
            traceback.print_exc()
            self._send(400, {"ok": False, "error": f"{type(e).__name__}: {e}"})


def serve(weights: str, port: int = 8766) -> None:
    Handler.model = TrainedModel(weights_path=weights)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"dottie-serve: model={Handler.model.model_id} "
          f"calibration={Handler.model.calibration} port={port}", flush=True)
    srv.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve the trained state-model")
    ap.add_argument("--weights", required=True)
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args()
    serve(args.weights, args.port)


if __name__ == "__main__":
    main()
