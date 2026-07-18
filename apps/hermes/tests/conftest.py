# Solo personal project, no connection to employer, built with public/free-tier only
"""Shared fixtures: make the hermes package importable and give each test a private data dir."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP_ROOT = Path(__file__).resolve().parent.parent  # apps/hermes
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))


@pytest.fixture()
def data_dir(tmp_path):
    """A private hermes data dir per test — never the repo's apps/hermes/data."""
    d = tmp_path / "hermes-data"
    d.mkdir()
    return d


@pytest.fixture()
def engine(data_dir):
    from hermes.engine import HermesEngine

    return HermesEngine(data_dir)


# An unroutable/refused endpoint for honest-unavailability tests: TEST-NET-1 (192.0.2.0/24)
# is reserved (RFC 5737) and never assigned; connect fails fast or times out — no fabrication.
UNROUTABLE_OLLAMA = "http://127.0.0.1:9"  # port 9 (discard); nothing listens in CI


@pytest.fixture()
def echo_record(engine):
    """One completed real echo task (through the REAL CodeAct sandbox)."""
    return engine.run_task("conftest echo task", backend="echo")
