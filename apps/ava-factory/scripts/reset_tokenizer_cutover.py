#!/usr/bin/env python3
"""Tokenizer cutover helper: abandon claims, invalidate PACKED, clear freeze.

Workers (collector/curator/trainer/server) must be stopped before running.
Deletes packed files under AVA_PACKED_DIR after DB invalidation.

Usage (cpu image)::

    python scripts/reset_tokenizer_cutover.py
    python -m ava.tokenizer train --preset mini --corpus /raw --out /state/tokenizer.json --freeze
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from ava.pipeline.manifest import Manifest


def main() -> int:
    packed = Path(os.environ.get("AVA_PACKED_DIR", "/packed"))
    with Manifest() as m:
        abandoned = m.abandon_claims()
        stats = m.clear_tokenizer_for_retrain()
        print(json.dumps({"abandoned": len(abandoned), **stats}, indent=2))

    if packed.exists():
        removed = 0
        for child in packed.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
                removed += 1
            elif child.is_file():
                child.unlink()
                removed += 1
        print(json.dumps({"packed_dir": str(packed), "removed_entries": removed}))
    else:
        print(json.dumps({"packed_dir": str(packed), "removed_entries": 0, "note": "missing"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
