# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""TrainedModel: heuristic answer selection + neural calibration.

Division of labor, stated plainly:
- HomegrownModel (heuristic) chooses WHAT the answer is — evidence matching
  is its strength.
- The calibrator net predicts P(that answer is correct | state features) —
  calibration is the net's strength.

`decide()` runs the heuristic, then overwrites `best.confidence` (and the
alternatives') with the net's calibrated probability. The `calibration`
field reports which backend produced the confidence so the harness can
audit it.

If weights are missing or unloadable, TrainedModel refuses to silently fall
back — construct with `allow_fallback=True` to get explicit heuristic
behavior instead. Silent fallback is how miscalibration hides.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dottie_core import _nn
from dottie_core.homegrown import HomegrownModel, encode_state
from dottie_core.model import QueryKind, ScoredAnswer, ScoredValue, TypedQuery
from dottie_core.state import WorldState

_KINDS = QueryKind.ALL


class TrainedModel:
    """Model protocol implementation with neural-calibrated confidence."""

    model_id = "homegrown-v1"

    def __init__(self, weights_path: str | Path | None = None,
                 weights: dict[str, Any] | None = None,
                 allow_fallback: bool = False) -> None:
        self._heuristic = HomegrownModel()
        self._weights: dict[str, Any] | None = None
        self._fallback = False
        if weights is not None:
            self._weights = weights
        elif weights_path is not None:
            p = Path(weights_path)
            if p.exists():
                self._weights = json.loads(p.read_text())
        if self._weights is None:
            if not allow_fallback:
                raise FileNotFoundError(
                    "no calibrator weights (pass weights= or weights_path=, "
                    "or allow_fallback=True for explicit heuristic mode)"
                )
            self._fallback = True

    @property
    def calibration(self) -> str:
        if self._fallback or self._weights is None:
            return "uncalibrated"
        return "neural-ece-v1"

    @property
    def confidence_floor(self) -> float:
        return 0.55

    @property
    def state_schema(self) -> dict[str, Any]:
        return self._heuristic.state_schema

    def _p_correct(self, state: WorldState, query: TypedQuery) -> float:
        feats = encode_state(state)
        onehot = [1.0 if k == query.kind else 0.0 for k in _KINDS]
        p = _nn.forward(self._weights, feats + onehot)  # type: ignore[arg-type]
        return max(0.0, min(1.0, float(p)))

    def decide(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        ans = self._heuristic.decide(state, query)
        if self._fallback or self._weights is None:
            return ans
        p = self._p_correct(state, query)
        best = ScoredValue(value=ans.best.value, confidence=p)
        alts = tuple(ScoredValue(value=a.value, confidence=p * 0.9) for a in ans.alternatives)
        return ScoredAnswer(best=best, alternatives=alts, query_id=ans.query_id,
                            model_id=self.model_id, calibration=self.calibration)
