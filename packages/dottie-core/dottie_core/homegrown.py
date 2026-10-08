# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Homegrown state-model: our implementation of the state-model pattern.

Clean-room principle: state in, typed answers out, calibrated probabilities.
Our code, our patterns — inspired by the state-model paradigm (typed queries
over shared world-state), not by any vendor's product or API.

Design:
- `encode_state()` turns WorldState beliefs into a fixed-size feature vector
  (belief count, mean confidence, provenance diversity, recency weighting,
  revision/contradiction signals, low-confidence mass, model-source fraction,
  empty-state flag). Pure Python, stdlib only.
- Per query kind, a logistic scorer maps (evidence + features) to a raw
  confidence. Evidence comes from content signals (token overlap, field
  presence); the logistic keeps outputs in (0, 1).
- Calibration is a per-kind bias correction learned from a local ledger of
  (predicted, outcome) pairs at `~/.dottie/calibration.json`. If the model is
  systematically overconfident on VERIFY, future VERIFY scores are dampened.
  Honest uncertainty, not fake precision.
- `decide()` stays pure: no I/O, deterministic given (state, query). The
  ledger is loaded at construction; `record_outcome()` / `calibrate()` persist.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dottie_core.jev_protocol import JevModel
from dottie_core.model import QueryKind, ScoredAnswer, ScoredValue, TypedQuery
from dottie_core.state import WorldState

_LEDGER_PATH = Path(os.environ.get("DOTTIE_HOME", Path.home() / ".dottie")) / "calibration.json"
_LEDGER_CAP = 500
_BIAS_CLIP = 0.3
_N_BINS = 5


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", s.lower()))


def encode_state(state: WorldState) -> list[float]:
    """Fixed-size feature vector from a WorldState. All features in [0, 1].

    0. belief_count:    beliefs / 10, capped at 1
    1. mean_confidence: mean belief confidence (0 when empty)
    2. prov_diversity:  unique sources / belief count (0 when empty)
    3. recency_weight:  version-weighted mean confidence (fresh beliefs count more)
    4. revision_rate:   fraction of beliefs that supersede another belief —
                        our observable proxy for contradiction/revision
    5. lowconf_mass:    fraction of beliefs below 0.5 confidence
    6. model_fraction:  fraction sourced from 'model:*' (self-referential signal)
    7. empty_flag:      1.0 when the state has no beliefs at all
    """
    beliefs = list(state.beliefs.values())
    n = len(beliefs)
    if n == 0:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    denom = state.version + 1
    return [
        min(n / 10.0, 1.0),
        sum(b.confidence for b in beliefs) / n,
        len({b.source for b in beliefs}) / n,
        sum(b.confidence * (b.at_version + 1) / denom for b in beliefs) / n,
        sum(1 for b in beliefs if b.supersedes) / n,
        sum(1 for b in beliefs if b.confidence < 0.5) / n,
        sum(1 for b in beliefs if b.source.startswith("model:")) / n,
        0.0,
    ]


def _state_text(state: WorldState, query: TypedQuery) -> str:
    view = state.query(query.state_ref)
    parts: list[str] = []
    for v in view.values():
        if isinstance(v, dict) and "value" in v:
            parts.append(str(v["value"]))
        else:
            parts.append(str(v))
    return "\n".join(parts)


def expected_calibration_error(
    predicted: list[float], outcomes: list[float], n_bins: int = _N_BINS
) -> float:
    """ECE: mean |accuracy - confidence| over equal-width bins, weighted by bin mass."""
    if not predicted:
        return 0.0
    ece = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        idx = [i for i, p in enumerate(predicted) if (lo <= p < hi) or (b == n_bins - 1 and p == hi)]
        if not idx:
            continue
        acc = sum(outcomes[i] for i in idx) / len(idx)
        conf = sum(predicted[i] for i in idx) / len(idx)
        ece += abs(acc - conf) * (len(idx) / len(predicted))
    return round(ece, 4)


class HomegrownModel(JevModel):
    """Our state-model. State in, typed answers out, ledger-calibrated confidence.

    Implements the `JevModel` protocol with our own code: a feature-encoder +
    per-kind logistic scorer, plus a persistent (predicted, outcome) ledger that
    corrects systematic over/under-confidence per query kind.
    """

    model_id = "homegrown-v0"

    # Logistic weights: evidence dominates; features nudge; bias starts mildly
    # optimistic so the calibration ledger has something honest to correct.
    _W_EVIDENCE = 1.5
    _W_FEATURES = 0.05
    _BIAS = 0.2

    def __init__(self, ledger_path: Path | None = None) -> None:
        self._ledger_path = ledger_path or _LEDGER_PATH
        self._records: list[dict[str, Any]] = []
        self._bias: dict[str, float] = {}
        self._load_ledger()

    # -- JevModel protocol -------------------------------------------------

    @property
    def state_schema(self) -> dict[str, Any]:
        return {
            "belief_keys": "any",
            "value_types": ["str", "int", "float", "bool", "list", "dict"],
            "provenance_required": True,
            "constraints": "read-only",
        }

    @property
    def confidence_floor(self) -> float:
        return 0.55

    @property
    def calibration(self) -> str:
        n = len(self._records)
        return f"ledger-bias(n={n})" if n else "uncalibrated"

    def calibrate(
        self, validation: list[tuple[WorldState, TypedQuery, Any]]
    ) -> dict[str, float]:
        """Refit per-kind bias on labeled (state, query, correct_answer) triples.

        Grading: CLASSIFY/CHOOSE/VERIFY/EXTRACT score 1.0 on exact match else 0.0;
        SCORE scores 1 - |predicted - correct| (closeness as soft correctness).
        Returns {"n", "ece_before", "ece_after", "method"} — ECE must drop, and
        if it doesn't we say so (the harness keeps the old mapping).
        """
        if not validation:
            return {"n": 0, "ece_before": 0.0, "ece_after": 0.0, "method": "ledger-bias"}
        preds: list[float] = []
        outs: list[float] = []
        for state, query, correct in validation:
            # Ledger learns the raw->outcome mapping; decide() would double-apply bias.
            raw = self.raw_confidence(state, query)
            ans = self._decide_raw(state, query)
            preds.append(raw)
            outs.append(self._grade(query, ans.best.value, correct))
        ece_before = expected_calibration_error(preds, outs)
        for (state, query, correct), p, o in zip(validation, preds, outs):
            self._append({"kind": query.kind, "predicted": p, "outcome": o,
                          "at": self._now(), "source": "calibrate"})
        self._refit_bias()
        self._persist()
        preds2 = [self._apply_bias(query.kind, p) for (_, query, _), p in zip(validation, preds)]
        ece_after = expected_calibration_error(preds2, outs)
        return {"n": len(validation), "ece_before": ece_before,
                "ece_after": ece_after, "method": "ledger-bias"}

    # -- online learning ----------------------------------------------------

    def record_outcome(self, kind: str, predicted: float, outcome: float) -> None:
        """Log one (predicted confidence, 0/1 outcome) pair; refits the bias.

        Call this after the ground truth of a decision is known. Pure
        bookkeeping — `decide()` itself never touches the disk.
        """
        if kind not in QueryKind.ALL:
            raise ValueError(f"unknown query kind {kind!r}")
        if not 0.0 <= outcome <= 1.0:
            raise ValueError("outcome must be in [0, 1]")
        self._append({"kind": kind, "predicted": float(predicted),
                      "outcome": float(outcome), "at": self._now(), "source": "online"})
        self._refit_bias()
        self._persist()

    def bias_report(self) -> dict[str, Any]:
        """Current per-kind corrections and ledger size. For demos and audits."""
        per_kind: dict[str, int] = {}
        for r in self._records:
            per_kind[r["kind"]] = per_kind.get(r["kind"], 0) + 1
        return {"bias": dict(self._bias), "n_records": len(self._records),
                "per_kind": per_kind}

    # -- pure decision function ----------------------------------------------

    def decide(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        """Calibrated answer. Pure: no I/O, deterministic given (state, query).

        Applies the ledger-learned bias to the raw model output. The harness
        always sees calibrated confidence; use `raw_confidence()` for the
        uncorrected score (learning, diagnostics).
        """
        raw = self._decide_raw(state, query)
        kind = query.kind

        def cal(sv: ScoredValue) -> ScoredValue:
            return ScoredValue(value=sv.value,
                               confidence=round(self._apply_bias(kind, sv.confidence), 3))

        return ScoredAnswer(best=cal(raw.best),
                            alternatives=tuple(cal(a) for a in raw.alternatives),
                            query_id=raw.query_id, model_id=raw.model_id,
                            calibration=self.calibration)

    def raw_confidence(self, state: WorldState, query: TypedQuery) -> float:
        """Raw (uncalibrated) confidence. For learning and diagnostics."""
        return round(self._decide_raw(state, query).best.confidence, 3)

    def _decide_raw(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        handler = {
            QueryKind.CLASSIFY: self._classify,
            QueryKind.SCORE: self._score,
            QueryKind.CHOOSE: self._choose,
            QueryKind.EXTRACT: self._extract,
            QueryKind.VERIFY: self._verify,
        }[query.kind]
        return handler(state, query)

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _raw_confidence(self, evidence: float, features: list[float]) -> float:
        logit = self._W_EVIDENCE * evidence + self._W_FEATURES * sum(features) + self._BIAS
        return _sigmoid(logit)

    def _apply_bias(self, kind: str, raw: float) -> float:
        return min(0.99, max(0.01, raw + self._bias.get(kind, 0.0)))

    def _raw_conf(self, evidence: float, features: list[float]) -> float:
        """Raw confidence from the logistic scorer. No ledger bias applied."""
        return round(self._raw_confidence(evidence, features), 3)

    def _ranked_options(self, options: tuple[str, ...], state_text: str,
                        kind: str, features: list[float]) -> list[ScoredValue]:
        text_toks = _tokens(state_text)
        scored = []
        for opt in options:
            opt_toks = _tokens(opt)
            evidence = len(opt_toks & text_toks) / len(opt_toks) if opt_toks else 0.0
            scored.append(ScoredValue(value=opt, confidence=self._raw_conf(evidence, features)))
        scored.sort(key=lambda s: s.confidence, reverse=True)
        return scored

    def _classify(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        text = _state_text(state, query)
        features = encode_state(state)
        options = query.options or ("code", "docs", "data")
        ranked = self._ranked_options(options, text, QueryKind.CLASSIFY, features)
        return ScoredAnswer(best=ranked[0], alternatives=tuple(ranked[1:3]),
                            model_id=self.model_id, calibration=self.calibration)

    def _score(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        features = encode_state(state)
        # The state's own mean belief confidence is the evidence for a score.
        evidence = features[1]
        value = round(self._raw_confidence(evidence, features), 3)
        return ScoredAnswer(
            best=ScoredValue(value=value, confidence=self._raw_conf(evidence, features)),
            model_id=self.model_id, calibration=self.calibration)

    def _choose(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        text = _state_text(state, query)
        features = encode_state(state)
        ranked = self._ranked_options(query.options, text, QueryKind.CHOOSE, features)
        return ScoredAnswer(best=ranked[0], alternatives=tuple(ranked[1:]),
                            model_id=self.model_id, calibration=self.calibration)

    def _extract(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        view = state.query(query.state_ref)
        features = encode_state(state)
        fields = query.schema.get("fields", ())
        result: dict[str, Any] = {}
        present = 0
        confs: list[float] = []
        for f in fields:
            cell = view.get(f)
            if isinstance(cell, dict) and "value" in cell:
                result[f] = cell["value"]
                present += 1
                confs.append(cell.get("confidence", 0.5))
        evidence = present / len(fields) if fields else 0.0
        conf = self._raw_conf(evidence, features)
        if confs:
            conf = round(min(0.99, max(0.01, conf * 0.5 + sum(confs) / len(confs) * 0.5)), 3)
        return ScoredAnswer(best=ScoredValue(value=result, confidence=conf),
                            model_id=self.model_id, calibration=self.calibration)

    def _verify(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        text_toks = _tokens(_state_text(state, query))
        claim_toks = _tokens(query.claim)
        features = encode_state(state)
        if not claim_toks:
            return ScoredAnswer(best=ScoredValue(value="unknown", confidence=0.2),
                                model_id=self.model_id, calibration=self.calibration)
        ratio = len(claim_toks & text_toks) / len(claim_toks)
        if ratio >= 0.6:
            verdict, evidence = "supported", ratio
        elif ratio <= 0.25:
            verdict, evidence = "refuted", 1.0 - ratio
        else:
            verdict, evidence = "unknown", 0.5
        conf = self._raw_conf(evidence, features)
        if verdict == "unknown":
            conf = round(min(conf, 0.5), 3)
        return ScoredAnswer(best=ScoredValue(value=verdict, confidence=conf),
                            model_id=self.model_id, calibration=self.calibration)

    @staticmethod
    def _grade(query: TypedQuery, predicted_value: Any, correct: Any) -> float:
        if query.kind == QueryKind.SCORE:
            try:
                return round(1.0 - min(abs(float(predicted_value) - float(correct)), 1.0), 3)
            except (TypeError, ValueError):
                return 0.0
        return 1.0 if predicted_value == correct else 0.0

    # -- ledger ---------------------------------------------------------------

    def _load_ledger(self) -> None:
        try:
            data = json.loads(self._ledger_path.read_text(encoding="utf-8"))
            self._records = list(data.get("records", []))[-_LEDGER_CAP:]
            self._bias = {k: float(v) for k, v in data.get("bias", {}).items()}
        except (OSError, ValueError, AttributeError):
            self._records, self._bias = [], {}

    def _persist(self) -> None:
        try:
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            self._ledger_path.write_text(
                json.dumps({"records": self._records[-_LEDGER_CAP:], "bias": self._bias},
                           indent=1),
                encoding="utf-8",
            )
        except OSError:
            pass  # read-only FS degrades to in-memory; decide() stays pure

    def _append(self, record: dict[str, Any]) -> None:
        self._records.append(record)
        if len(self._records) > _LEDGER_CAP:
            self._records = self._records[-_LEDGER_CAP:]

    def _refit_bias(self) -> None:
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for r in self._records:
            by_kind.setdefault(r["kind"], []).append(r)
        for kind, recs in by_kind.items():
            recent = recs[-50:]
            mean_pred = sum(r["predicted"] for r in recent) / len(recent)
            mean_out = sum(r["outcome"] for r in recent) / len(recent)
            self._bias[kind] = round(
                max(-_BIAS_CLIP, min(_BIAS_CLIP, mean_out - mean_pred)), 4)
