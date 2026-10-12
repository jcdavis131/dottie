# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Client for the served state-model. Stdlib only.

ServedModel implements the Model protocol by POSTing to the local server.
If the server is unreachable, it falls back to the local HomegrownModel —
EXPLICITLY, not silently: the returned ScoredAnswer carries
calibration="heuristic-fallback" and model_id="homegrown-v0" so the harness
knows the confidence is uncalibrated. Honest 503 over fake success.

Usage:
    model = ServedModel()  # tries 127.0.0.1:8766, falls back if down
    model = ServedModel(url="http://127.0.0.1:8766", strict=True)  # raise if down
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error

from dottie_core.homegrown import HomegrownModel
from dottie_core.model import ScoredAnswer, TypedQuery
from dottie_core.state import WorldState

DEFAULT_URL = "http://127.0.0.1:8766"


def _state_to_dict(state: WorldState) -> dict:
    return {
        "version": state.version,
        "goal_id": state.goal_id,
        "beliefs": [
            {"belief_id": b.belief_id, "key": b.key, "value": b.value,
             "confidence": b.confidence, "source": b.source,
             "at_version": b.at_version, "supersedes": b.supersedes}
            for b in state.beliefs.values()
        ],
        "constraints": {
            "max_cost_units": state.constraints.max_cost_units,
            "deadline_iso": state.constraints.deadline_iso,
            "side_effect_class": state.constraints.side_effect_class,
            "require_hitl_for": list(state.constraints.require_hitl_for),
        },
        "domain": dict(state.domain),
    }


def _query_to_dict(query: TypedQuery) -> dict:
    return {
        "kind": query.kind,
        "state_ref": {
            "belief_keys": list(query.state_ref.belief_keys),
            "include_actions": query.state_ref.include_actions,
            "include_constraints": query.state_ref.include_constraints,
            "domain_keys": list(query.state_ref.domain_keys),
        },
        "schema": dict(query.schema),
        "options": list(query.options),
        "claim": query.claim,
    }


def _answer_from_dict(d: dict, query_id: str = "") -> ScoredAnswer:
    from dottie_core.model import ScoredValue

    best = d["best"]
    return ScoredAnswer(
        best=ScoredValue(value=best["value"], confidence=float(best["confidence"])),
        alternatives=tuple(
            ScoredValue(value=a["value"], confidence=float(a["confidence"]))
            for a in d.get("alternatives", [])
        ),
        query_id=query_id,
        model_id=d.get("model_id", "served"),
        calibration=d.get("calibration", "served"),
    )


class ServedModel:
    """Model protocol over HTTP, with explicit heuristic fallback."""

    model_id = "served-v1"

    def __init__(self, url: str = DEFAULT_URL, timeout: float = 5.0,
                 strict: bool = False) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.strict = strict
        self._fallback = HomegrownModel()
        self._server_ok: bool | None = None  # None = untested

    @property
    def calibration(self) -> str:
        if self._server_ok:
            return "neural-ece-v1"
        return "heuristic-fallback"

    @property
    def confidence_floor(self) -> float:
        return 0.55

    @property
    def state_schema(self) -> dict:
        return self._fallback.state_schema

    def health(self) -> dict:
        """GET /health. Returns dict; never raises."""
        try:
            with urllib.request.urlopen(f"{self.url}/health", timeout=self.timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def decide(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        payload = json.dumps({
            "state": _state_to_dict(state),
            "query": _query_to_dict(query),
        }).encode()
        req = urllib.request.Request(
            f"{self.url}/decide", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                d = json.loads(r.read())
            if not d.get("ok"):
                raise RuntimeError(d.get("error", "server returned ok=false"))
            self._server_ok = True
            return _answer_from_dict(d)
        except Exception as e:
            self._server_ok = False
            if self.strict:
                # Honest 503: raise instead of faking a served answer.
                raise ConnectionError(
                    f"state-model server unreachable at {self.url}: {e}"
                ) from e
            # Explicit fallback: the answer is labeled heuristic, never served.
            ans = self._fallback.decide(state, query)
            return ScoredAnswer(
                best=ans.best, alternatives=ans.alternatives,
                query_id=ans.query_id, model_id="homegrown-v0",
                calibration="heuristic-fallback",
            )
