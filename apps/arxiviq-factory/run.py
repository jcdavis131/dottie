"""Entry point: `python apps/arxiviq-factory/run.py <stage> [args]` from anywhere.

Stages, in order: harvest, enrich, skillify, teacher (prepare | prepare-fulltext | ingest), curate.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from arxiviq_factory import curate, enrich, harvest, skillify, teacher

STAGES = {"harvest": harvest.main, "enrich": enrich.main, "skillify": skillify.main, "teacher": teacher.main, "curate": curate.main}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in STAGES:
        raise SystemExit(f"usage: run.py {{{'|'.join(STAGES)}}} [args]")
    raise SystemExit(STAGES[sys.argv[1]](sys.argv[2:]))
