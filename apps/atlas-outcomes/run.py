"""Entry point: `python3 apps/atlas-outcomes/run.py <stage> [args]` from anywhere.

Stages, in order: harvest, features, curate, baseline, train-command.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STAGES = {
    "harvest": "atlas_outcomes.harvest",
    "features": "atlas_outcomes.features",
    "curate": "atlas_outcomes.curate",
    "baseline": "atlas_outcomes.baseline",
    "train-command": "atlas_outcomes.train_command",
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in STAGES:
        raise SystemExit(f"usage: run.py {{{'|'.join(STAGES)}}} [args]")
    raise SystemExit(importlib.import_module(STAGES[sys.argv[1]]).main(sys.argv[2:]))
