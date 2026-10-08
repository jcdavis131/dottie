# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Heuristic model: keyword/regex decisions, zero API keys, honest confidence.

Clean-room principle: the default model must work with no external services.
It returns deliberately LOW confidence scores — a heuristic knows it's a
heuristic. The harness treats uncalibrated scores conservatively, so honest
low confidence is a feature: it triggers escalation instead of silent guessing.
"""

from __future__ import annotations

import re
from typing import Any

from dottie_core.model import Model, QueryKind, ScoredAnswer, ScoredValue, TypedQuery
from dottie_core.state import WorldState


class HeuristicModel(Model):
    """Rule-based Model. Deterministic, offline, honest about its limits."""

    model_id = "heuristic-v0"
    # Uncalibrated: the harness caps effective confidence at 0.5 for routing.
    calibration = "uncalibrated"

    # Small built-in keyword sets. Domains extend via register_keywords().
    _KEYWORDS: dict[str, dict[str, list[str]]] = {
        "classify": {
            "code": [r"\bdef\b", r"\bclass\b", r"import\s+\w", r"\bfunction\b", r"=>", r"{\s*$"],
            "docs": [r"^#\s", r"\bREADME\b", r"```", r"\bexample\b", r"\btutorial\b"],
            "data": [r"^\s*[\w,]+\s*,\s*[\w,]+", r"\bcsv\b", r"\bjson\b", r"\b\d{4}-\d{2}-\d{2}\b"],
        }
    }

    @classmethod
    def register_keywords(cls, kind: str, label: str, patterns: list[str]) -> None:
        cls._KEYWORDS.setdefault(kind, {})[label] = patterns

    def decide(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        handler = {
            QueryKind.CLASSIFY: self._classify,
            QueryKind.SCORE: self._score,
            QueryKind.CHOOSE: self._choose,
            QueryKind.EXTRACT: self._extract,
            QueryKind.VERIFY: self._verify,
        }[query.kind]
        return handler(state, query)

    def _text_of(self, state: WorldState, query: TypedQuery) -> str:
        view = state.query(query.state_ref)
        parts: list[str] = []
        for v in view.values():
            if isinstance(v, dict) and "value" in v:
                parts.append(str(v["value"]))
            else:
                parts.append(str(v))
        return "\n".join(parts)

    def _classify(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        text = self._text_of(state, query)
        labels = query.options or tuple(self._KEYWORDS.get("classify", {}))
        scored: list[ScoredValue] = []
        for label in labels:
            patterns = self._KEYWORDS.get("classify", {}).get(label, [])
            hits = sum(1 for p in patterns if re.search(p, text, re.M | re.I))
            # Honest confidence: hits/(hits+2) caps low; never claims certainty.
            conf = hits / (hits + 2.0) * 0.6 if patterns else 0.1
            scored.append(ScoredValue(value=label, confidence=round(min(conf, 0.6), 3)))
        scored.sort(key=lambda s: s.confidence, reverse=True)
        best, rest = scored[0], tuple(scored[1:])
        return ScoredAnswer(best=best, alternatives=rest, model_id=self.model_id,
                            calibration=self.calibration)

    def _score(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        # Heuristic has no basis for absolute scores: return 0.5 with low confidence.
        return ScoredAnswer(
            best=ScoredValue(value=0.5, confidence=0.2),
            model_id=self.model_id, calibration=self.calibration,
        )

    def _choose(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        # Without domain signal, prefer the first option weakly (documented bias).
        scored = [ScoredValue(value=o, confidence=0.3 if i == 0 else 0.2)
                  for i, o in enumerate(query.options)]
        return ScoredAnswer(best=scored[0], alternatives=tuple(scored[1:]),
                            model_id=self.model_id, calibration=self.calibration)

    def _extract(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        view = state.query(query.state_ref)
        result: dict[str, Any] = {}
        for field_name in query.schema.get("fields", ()):
            result[field_name] = view.get(field_name, {}).get("value")
        return ScoredAnswer(
            best=ScoredValue(value=result, confidence=0.4),
            model_id=self.model_id, calibration=self.calibration,
        )

    def _verify(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        text = self._text_of(state, query).lower()
        claim = query.claim.lower()
        # Crude: claim supported if its distinctive words appear in state.
        words = [w for w in re.findall(r"\w{4,}", claim) if w not in
                 {"this", "that", "with", "from", "does", "have", "will"}]
        if not words:
            verdict, conf = "unknown", 0.2
        else:
            hit = sum(1 for w in words if w in text)
            ratio = hit / len(words)
            if ratio >= 0.6:
                verdict, conf = "supported", 0.5
            elif ratio <= 0.2:
                verdict, conf = "refuted", 0.4
            else:
                verdict, conf = "unknown", 0.3
        return ScoredAnswer(
            best=ScoredValue(value=verdict, confidence=conf),
            model_id=self.model_id, calibration=self.calibration,
        )
