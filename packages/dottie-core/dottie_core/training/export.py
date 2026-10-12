# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Weight export utilities.

Primary format is plain JSON (see training/model.py::export_weights) — the
serving path loads it with dottie_core/_nn.py and never needs torch.

Optional: torchscript export for environments that want a single artifact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def save_weights_json(weights: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(weights))
    return path


def load_weights_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def export_torchscript(weights: dict[str, Any], path: str | Path) -> Path:
    """Rebuild the net in torch, script it, save. Training-env only."""
    from dottie_core.training.model import CalibratorNet, load_weights

    model = CalibratorNet()
    load_weights(model, weights)
    model.eval()
    import torch

    example = torch.randn(1, 13)
    scripted = torch.jit.trace(model, example)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scripted.save(str(path))
    return path
