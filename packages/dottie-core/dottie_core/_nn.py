# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Torch-free forward pass for the calibrator net.

The trained weights are plain JSON (see training/export.py). This module
evaluates 13 -> 64 -> 32 -> 16 -> 1(sigmoid) with numpy when available,
pure-python lists otherwise. Serving and TrainedModel use this — torch is
a training-only dependency.
"""

from __future__ import annotations

from typing import Any

try:
    import numpy as _np

    _NUMPY = True
except ImportError:  # pragma: no cover
    _np = None  # type: ignore
    _NUMPY = False


def _relu_list(xs: list[float]) -> list[float]:
    return [x if x > 0 else 0.0 for x in xs]


def _sigmoid_list(xs: list[float]) -> list[float]:
    import math

    out = []
    for x in xs:
        out.append(1.0 / (1.0 + math.exp(-x)) if x >= 0 else math.exp(x) / (1.0 + math.exp(x)))
    return out


def _linear_list(x: list[float], w: list[list[float]], b: list[float]) -> list[float]:
    return [sum(xi * wij for xi, wij in zip(x, row)) + bi for row, bi in zip(w, b)]


def forward(weights: dict[str, Any], x: list[float]) -> float:
    """P(correct) for one 13-dim feature vector. Returns float in [0, 1]."""
    w = weights["weights"]
    # torch Linear stores weight as [out, in]; bias as [out]
    if _NUMPY:
        a = _np.asarray(x, dtype=_np.float64)
        a = _np.maximum(0, a @ _np.asarray(w["net.0.weight"]).T + _np.asarray(w["net.0.bias"]))
        a = _np.maximum(0, a @ _np.asarray(w["net.2.weight"]).T + _np.asarray(w["net.2.bias"]))
        a = _np.maximum(0, a @ _np.asarray(w["net.4.weight"]).T + _np.asarray(w["net.4.bias"]))
        z = float(a @ _np.asarray(w["net.6.weight"]).T + _np.asarray(w["net.6.bias"]))
        return 1.0 / (1.0 + _np.exp(-z)) if z >= 0 else float(_np.exp(z) / (1.0 + _np.exp(z)))
    # pure-python fallback
    a = _relu_list(_linear_list(x, w["net.0.weight"], w["net.0.bias"]))
    a = _relu_list(_linear_list(a, w["net.2.weight"], w["net.2.bias"]))
    a = _relu_list(_linear_list(a, w["net.4.weight"], w["net.4.bias"]))
    z = _linear_list(a, w["net.6.weight"], w["net.6.bias"])[0]
    return _sigmoid_list([z])[0]


def batch_forward(weights: dict[str, Any], xs: list[list[float]]) -> list[float]:
    """Batched forward; falls back to per-row when numpy is missing."""
    if _NUMPY:
        import numpy as _n

        w = weights["weights"]
        a = _n.asarray(xs, dtype=_n.float64)
        a = _n.maximum(0, a @ _n.asarray(w["net.0.weight"]).T + _n.asarray(w["net.0.bias"]))
        a = _n.maximum(0, a @ _n.asarray(w["net.2.weight"]).T + _n.asarray(w["net.2.bias"]))
        a = _n.maximum(0, a @ _n.asarray(w["net.4.weight"]).T + _n.asarray(w["net.4.bias"]))
        z = a @ _n.asarray(w["net.6.weight"]).T + _n.asarray(w["net.6.bias"])
        sig = 1.0 / (1.0 + _n.exp(-_n.clip(z, -50, 50)))
        return [float(v) for v in sig.flat]
    return [forward(weights, x) for x in xs]
