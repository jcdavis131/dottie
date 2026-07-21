# Solo personal project, no connection to employer, built with public/free-tier only
"""Shared test setup: make src/ importable without installing the package."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
