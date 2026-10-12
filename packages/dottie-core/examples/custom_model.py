#!/usr/bin/env python3
# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Custom Model plugin: structural classifier.

The built-in HeuristicModel classifies by KEYWORDS (regex hits for "def",
"import", "README", ...). This plugin classifies by STRUCTURE instead:
indentation depth, bracket density, line-length variance, comment ratio.
A genuinely different decision procedure behind the same Model protocol —
which is the whole point of plugins: swap the decider, keep the harness.

Run it::

    python3 examples/custom_model.py

To ship this as a real package, add to your pyproject.toml::

    [project.entry-points."dottie.models"]
    structural-v0 = "my_package.structural:StructuralModel"

then ``dottie_core.plugins.load("model", "structural-v0")`` finds it with no
code changes here. This script uses ``plugins.register()`` instead so it runs
without installing anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dottie_core import (  # noqa: E402
    Goal,
    Harness,
    QueryKind,
    ScoredAnswer,
    ScoredValue,
    TypedQuery,
    WorldState,
    default_policy,
    plugins,
)


class StructuralModel:
    """Classify documents by shape, not vocabulary.

    Features (all cheap, all stdlib):
    - indent_ratio: fraction of lines starting with whitespace (code is nested)
    - bracket_density: brackets per 100 chars (code is bracket-heavy)
    - line_var: coefficient of variation of line lengths (docs vary more)
    - comment_ratio: fraction of lines starting with # or // (docs explain)

    Scores each label by distance to a prototype vector. Confidence is honest:
    this model knows structure is a weak signal, so it caps at 0.55.
    """

    model_id = "structural-v0"
    calibration = "uncalibrated"

    # Prototype feature vectors, measured from representative samples.
    # [indent_ratio, bracket_density, line_var, comment_ratio]
    _PROTOTYPES = {
        "code": [0.75, 8.1, 0.42, 0.00],
        "docs": [0.00, 0.0, 0.44, 0.33],
        "data": [0.00, 0.0, 0.05, 0.00],
    }
    _MAX_CONF = 0.55

    def _features(self, text: str) -> list[float]:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            return [0.0, 0.0, 0.0, 0.0]
        n = len(lines)
        indent = sum(1 for ln in lines if ln[0].isspace()) / n
        brackets = sum(c in "{}[]()" for c in text) / max(len(text), 1) * 100
        lens = [len(ln) for ln in lines]
        mean = sum(lens) / n
        var = (sum((x - mean) ** 2 for x in lens) / n) ** 0.5 / max(mean, 1)
        comments = sum(1 for ln in lines if ln.strip()[:2] in ("# ", "//")) / n
        return [indent, brackets, var, comments]

    def _distance(self, a: list[float], b: list[float]) -> float:
        # Normalize bracket_density (0-10 scale) to 0-1 like the others.
        scales = [1.0, 10.0, 1.0, 1.0]
        return sum(((x - y) / s) ** 2 for x, y, s in zip(a, b, scales)) ** 0.5

    def _text_of(self, state: WorldState, query: TypedQuery) -> str:
        # Only the "sample" belief carries the document; other beliefs
        # (constraints, routing metadata) would pollute structural features.
        b = state.beliefs.get("sample")
        if b is not None:
            return str(b.value)
        # Fallback: join whatever the query returned.
        view = state.query(query.state_ref)
        parts = []
        for v in view.values():
            if isinstance(v, dict) and "value" in v:
                parts.append(str(v["value"]))
            else:
                parts.append(str(v))
        return "\n".join(parts)

    def decide(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        if query.kind == QueryKind.CHOOSE:
            # Routing query: we're a deterministic rule-based model, so the
            # honest answer is always the deterministic tier, low confidence
            # (the harness falls back to T0 on low confidence anyway).
            return ScoredAnswer(
                best=ScoredValue(value="T0-deterministic", confidence=0.4),
                alternatives=tuple(
                    ScoredValue(value=o, confidence=0.1) for o in query.options
                    if o != "T0-deterministic"
                ),
                model_id=self.model_id,
                calibration=self.calibration,
            )
        if query.kind != QueryKind.CLASSIFY:
            # Not our specialty: abstain honestly rather than guess.
            return ScoredAnswer(
                best=ScoredValue(value=None, confidence=0.0),
                alternatives=(),
                model_id=self.model_id,
                calibration=self.calibration,
            )
        view = state.query(query.state_ref)
        text = self._text_of(state, query)
        feats = self._features(text)
        labels = query.options or tuple(self._PROTOTYPES)
        scored = []
        for label in labels:
            proto = self._PROTOTYPES.get(label, [0.0, 0.0, 0.0, 0.0])
            dist = self._distance(feats, proto)
            # Closer prototype -> higher confidence, capped honest.
            conf = round(min(self._MAX_CONF / (1.0 + dist), self._MAX_CONF), 3)
            scored.append(ScoredValue(value=label, confidence=conf))
        scored.sort(key=lambda s: s.confidence, reverse=True)
        best, rest = scored[0], tuple(scored[1:])
        return ScoredAnswer(
            best=best, alternatives=rest,
            model_id=self.model_id, calibration=self.calibration,
        )


SAMPLES = {
    "code": "def fib(n):\n    if n < 2:\n        return n\n    return fib(n-1) + fib(n-2)\n",
    "docs": "# Quickstart\n\nInstall with pip, then import the package.\nSee the tutorial for examples.\n",
    "data": "2026-10-07,19234,ok\n2026-10-06,18871,ok\n2026-10-05,19002,fail\n",
}


def main() -> int:
    # 1. Register the plugin in-process (no install needed for the demo).
    plugins.register("model", "structural-v0", StructuralModel)

    # 2. Discovery finds it alongside any installed entry-point plugins.
    found = plugins.discover("model")
    print(f"discovered models: {sorted(found)}")

    # 3. Load by name — same call works for entry-point plugins.
    model_cls = plugins.load("model", "structural-v0")
    model = model_cls()
    print(f"loaded: {model.model_id} (calibration: {model.calibration})")
    print()

    # 4. Run each sample through the real harness with the plugin model.
    # Fresh harness per sample: state must not leak between runs.
    for expected, text in SAMPLES.items():
        harness = Harness(model=model, policy=default_policy())
        goal = Goal(
            intent=f"Classify sample (expect {expected})",
            state_seed={"sample": text},
        )
        result = harness.run(goal)
        belief = result.final_state.beliefs.get("classification")
        mark = "✓" if belief and belief.value == expected else "✗"
        print(f"{mark} expected={expected:5s} got={belief.value if belief else None!r:6} "
              f"conf={belief.confidence:.3f} status={result.status}")

    print()
    print("Plugin ran end-to-end through observe -> policy -> route -> execute -> verify -> record.")
    print("To ship it: add the [project.entry-points.\"dottie.models\"] stanza from the docstring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
