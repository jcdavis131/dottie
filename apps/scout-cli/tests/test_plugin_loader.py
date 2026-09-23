"""Lazy plugin loading: `scout --help` lists every plugin without importing any;
a command imports only its own plugin; failures stay silent but are visible via
SCOUT_DEBUG_PLUGINS=1 and `scout doctor`; the entry table matches the plugins."""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from bigbang.core import plugin_loader


def _py(code: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    import os

    # Deterministic help rendering: CI runners force colour (FORCE_COLOR,
    # GITHUB_ACTIONS) and an 80-column width, which wraps and wraps names in
    # ANSI codes. Pin a wide, colourless terminal; _probe also strips ANSI.
    env = {k: v for k, v in os.environ.items() if k not in ("FORCE_COLOR", "GITHUB_ACTIONS", "TTY_COMPATIBLE")}
    env.update({"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200", "TERMINAL_WIDTH": "200"})
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120, env=env)


_PROBE = """
import json, sys
sys.argv = ["scout", *{argv!r}]
from bigbang.cli import app
try:
    app(standalone_mode=False)
except SystemExit:
    pass
loaded = sorted({{m.split(".")[2] for m in sys.modules if m.startswith("bigbang.plugins.") and m.endswith(".cli")}})
print("\\n@@" + json.dumps({{"plugins": loaded, "mcp": "mcp" in sys.modules}}))
"""


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _probe(*argv: str) -> tuple[str, dict]:
    r = _py(_PROBE.format(argv=list(argv)))
    assert r.returncode == 0, r.stderr[-2000:]
    out, _, tail = r.stdout.rpartition("\n@@")
    return _ANSI.sub("", out), json.loads(tail)


def test_help_lists_every_plugin_and_imports_none():
    out, seen = _probe("--help")
    assert seen["plugins"] == [] and seen["mcp"] is False
    for name in plugin_loader.list_plugin_names():
        assert f" {name} " in out, name


def test_route_imports_only_the_harness_plugin_and_not_the_mcp_sdk():
    # (core helpers may import a plugin's library module, e.g. output.py -> rft.etl;
    # what must not happen is loading other plugins' CLIs)
    _out, seen = _probe("--json", "route", "heartbeat tick")
    assert seen["plugins"] == ["harness"]
    assert seen["mcp"] is False


def test_a_plugin_command_still_resolves():
    out, seen = _probe("--json", "harness", "agents", "list")
    assert "harness" in seen["plugins"] and '"ok": true' in out.lower()


def test_entry_table_matches_the_plugins():
    built = plugin_loader.build_entries()
    assert built == plugin_loader.load_entries(), (
        "bigbang/core/plugin_entries.py is stale: run "
        "`python -m bigbang.core.plugin_loader --write-entries`"
    )


def test_import_failure_is_silent_but_recorded(monkeypatch, capsys):
    def boom(name):
        raise ImportError(f"no module for {name}")

    monkeypatch.setattr(plugin_loader, "_import_plugin", boom)
    monkeypatch.delenv("SCOUT_DEBUG_PLUGINS", raising=False)
    assert plugin_loader._sub_app("a11y") is None
    assert plugin_loader.LOAD_FAILURES["a11y"].startswith("ImportError")
    assert capsys.readouterr().err == ""
    monkeypatch.setenv("SCOUT_DEBUG_PLUGINS", "1")
    plugin_loader._sub_app("a11y")
    err = capsys.readouterr().err
    assert "plugin 'a11y' failed to import" in err and "Traceback" in err
    report = plugin_loader.check_plugins()
    assert report["importable"] == 0 and "a11y" in report["failures"]


def test_doctor_reports_plugins():
    r = subprocess.run([sys.executable, "-m", "bigbang.cli", "--json", "doctor"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stderr[-1000:]
    doc = json.loads(r.stdout)
    data = doc.get("data", doc)
    check = next(c for c in data["checks"] if c["check"] == "plugins")
    assert check["ok"] is True and check["failures"] == {} and check["stale_entries"] == []


@pytest.mark.parametrize("flag", ["1"])
def test_eager_mode_still_works(flag):
    tail = _py(_PROBE.format(argv=["--help"]), {"SCOUT_EAGER_PLUGINS": flag}).stdout.rpartition("\n@@")[2]
    assert len(json.loads(tail)["plugins"]) == len(plugin_loader.list_plugin_names())
