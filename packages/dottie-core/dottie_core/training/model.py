# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Calibrator net: P(heuristic answer is correct | state features, query kind).

Architecture: 13 -> 64 -> 32 -> 16 -> 1 (sigmoid). ~3.6k parameters, <100KB
exported. This is a state-scorer, not a language model — it fits in L2 cache.

Input: 8 state features (from encode_state) + 5-dim query-kind one-hot.
Output: calibrated probability the heuristic's answer is correct.

Requires torch for training. Inference uses dottie_core/_nn.py (stdlib/numpy)
so serving never needs torch.
"""

from __future__ import annotations

from typing import Any

INPUT_DIM = 13   # 8 state features + 5 query-kind one-hot
HIDDEN = (64, 32, 16)

try:
    import torch
    import torch.nn as nn

    _TORCH = True
except ImportError:  # pragma: no cover
    torch = None  # type: ignore
    nn = None  # type: ignore
    _TORCH = False


def torch_available() -> bool:
    return _TORCH


if _TORCH:

    class CalibratorNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(INPUT_DIM, HIDDEN[0]),
                nn.ReLU(),
                nn.Linear(HIDDEN[0], HIDDEN[1]),
                nn.ReLU(),
                nn.Linear(HIDDEN[1], HIDDEN[2]),
                nn.ReLU(),
                nn.Linear(HIDDEN[2], 1),
            )

        def forward(self, x):  # type: ignore[no-untyped-def]
            return torch.sigmoid(self.net(x)).squeeze(-1)

else:  # pragma: no cover

    class CalibratorNet:  # type: ignore[no-redef]
        def __init__(self) -> None:
            raise ImportError("torch is required to train; install torch or use the heuristic")


def count_params(model) -> int:  # type: ignore[no-untyped-def]
    return sum(p.numel() for p in model.parameters())


def export_weights(model) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Plain-python weight dict: JSON-serializable, torch-free to load."""
    sd = model.state_dict()
    return {
        "arch": {"input_dim": INPUT_DIM, "hidden": list(HIDDEN)},
        "weights": {k: v.detach().cpu().tolist() for k, v in sd.items()},
    }


def load_weights(model, weights: dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
    """Load a plain-python weight dict into a CalibratorNet."""
    import torch as _torch

    sd = {k: _torch.tensor(v, dtype=_torch.float32) for k, v in weights["weights"].items()}
    model.load_state_dict(sd)
