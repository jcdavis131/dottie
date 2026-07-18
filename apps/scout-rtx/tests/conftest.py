"""Shared fixtures for the CPU-only test suite.

prepare.py imports pyarrow/rustbpe/tiktoken at module level; those packages are
not installed in this environment, so we stub them in sys.modules before any
test imports train/prepare. The bigbang package (host CLI framework for
bigbang-bridge/cli.py) is stubbed the same way, with a recording `emit`.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = REPO_ROOT / "bigbang-bridge" / "cli.py"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# --- stub packages missing from this environment -------------------------

EMIT_RECORDS = []


def _recording_emit(payload, **kwargs):
    EMIT_RECORDS.append(payload)


def _install_stubs():
    for name in ("rustbpe", "tiktoken"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    if "pyarrow" not in sys.modules:
        pyarrow = types.ModuleType("pyarrow")
        parquet = types.ModuleType("pyarrow.parquet")
        pyarrow.parquet = parquet
        sys.modules["pyarrow"] = pyarrow
        sys.modules["pyarrow.parquet"] = parquet
    if "bigbang" not in sys.modules:
        bigbang = types.ModuleType("bigbang")
        core = types.ModuleType("bigbang.core")
        output = types.ModuleType("bigbang.core.output")
        output.emit = _recording_emit
        core.output = output
        bigbang.core = core
        sys.modules["bigbang"] = bigbang
        sys.modules["bigbang.core"] = core
        sys.modules["bigbang.core.output"] = output


_install_stubs()


@pytest.fixture
def emit_records():
    EMIT_RECORDS.clear()
    yield EMIT_RECORDS
    EMIT_RECORDS.clear()


@pytest.fixture
def cli_mod(tmp_path, monkeypatch):
    """Load bigbang-bridge/cli.py fresh, rooted at a temp SCOUT_RTX_ROOT."""
    root = tmp_path / "rtx-root"
    root.mkdir()
    monkeypatch.setenv("SCOUT_RTX_ROOT", str(root))
    spec = importlib.util.spec_from_file_location("scout_rtx_cli_under_test", CLI_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Keep MRR writes inside the sandbox.
    mod.MRR_FILE = tmp_path / "mrr" / "mrr.jsonl"
    return mod
