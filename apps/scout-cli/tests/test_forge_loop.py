# Solo personal project, no connection to employer, built with public/free-tier only
"""The self-evolution engine loop, end to end and REAL.

Mimics the task-inbox path: a synthetic task demands a capability scout does not have
(per-column CSV statistics), so the loop forges it — `forge new` scaffold, `forge edit`
with a contract-compliant implementation, `forge test` smoke, SKILL.md, `skill install
--target dottie` — then proves the registry updated and the new tool executes a REAL
second-pass computation on a real file. Every step is the actual CLI in a subprocess;
nothing is mocked, and the forged artifacts are removed again in the finally block.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SCOUT_ROOT = Path(__file__).resolve().parents[1]
TOOL = "csvstat_loop_test"

TOOL_CODE = '''# Solo personal project, no connection to employer, built with public/free-tier only
"""csvstat_loop_test — per-column numeric stats for a CSV (forged by the loop test)."""
import csv
import typer
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.cli_ux import examples_epilog

app = make_plugin_app("csvstat_loop_test", "CSV column statistics")


@app.command("hello", epilog=examples_epilog(["scout --json csvstat_loop_test hello"]))
def hello():
    emit(ok({"plugin": "csvstat_loop_test", "status": "alive"},
            command="csvstat_loop_test hello",
            example="scout --json csvstat_loop_test run --path data.csv"),
         command="csvstat_loop_test hello")


@app.command("run", epilog=examples_epilog(["scout --json csvstat_loop_test run --path data.csv"]))
def run(path: str = typer.Option(..., "--path", help="CSV file to analyse")):
    cols = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            for k, v in row.items():
                try:
                    cols.setdefault(k, []).append(float(v))
                except (TypeError, ValueError):
                    pass
    stats = {k: {"count": len(vs), "mean": sum(vs) / len(vs),
                 "min": min(vs), "max": max(vs)}
             for k, vs in cols.items() if vs}
    emit(ok({"path": path, "columns": stats},
            command="csvstat_loop_test run",
            example="scout --json csvstat_loop_test run --path data.csv"),
         command="csvstat_loop_test run")


def register(root):
    root.add_typer(app, name="csvstat_loop_test")
'''

def _cli(*args: str, timeout: int = 120) -> dict:
    """Run the real CLI, parse the JSON envelope."""
    p = subprocess.run([sys.executable, "-m", "bigbang.cli", "--json", *args],
                       capture_output=True, text=True, timeout=timeout,
                       cwd=str(SCOUT_ROOT))
    raw = p.stdout
    start = raw.find("{")
    assert start != -1, f"no JSON from {args}: stdout={raw[:300]!r} stderr={p.stderr[:300]!r}"
    return json.loads(raw[start:raw.rindex("}") + 1])


def _tool_names(listing: dict) -> list:
    data = listing.get("data", listing)
    plugins = data.get("plugins") or data.get("tools") or data.get("forged") or []
    if plugins and isinstance(plugins[0], dict):
        return [p.get("name") for p in plugins]
    return list(plugins)


def test_self_evolution_loop_forges_tests_installs_and_reexecutes(tmp_path):
    plugin_dir = SCOUT_ROOT / "bigbang" / "plugins" / TOOL
    packaged_skill = SCOUT_ROOT / "bigbang" / "skills" / TOOL
    installed_skill = Path.home() / ".dottie-claw" / "skills" / TOOL
    try:
        # 0. the synthetic task's capability is genuinely missing
        assert TOOL not in _tool_names(_cli("forge", "list")), \
            f"{TOOL} already exists — stale cleanup?"

        # 1. forge the scaffold — SKILL.md is scaffolded alongside (TODOS 6.4), so
        # `skill install` works with no manual authoring step
        new = _cli("forge", "new", TOOL, "--description", "CSV column statistics")
        assert (new.get("data", new)).get("status") == "scaffolded"
        assert packaged_skill.joinpath("SKILL.md").exists(), "forge new must scaffold SKILL.md"
        fm = packaged_skill.joinpath("SKILL.md").read_text(encoding="utf-8")
        assert f"name: {TOOL}" in fm and "triggers:" in fm

        # 2. implement for real (the LLM's `forge edit` step)
        edit = _cli("forge", "edit", TOOL, "--code", TOOL_CODE)
        assert edit.get("ok", True) is not False

        # 3. smoke-verify through forge's own test harness
        tested = _cli("forge", "test", TOOL)
        assert (tested.get("data", tested)).get("passes") is True, tested

        # 4. teach Dottie: real install into ~/.dottie-claw straight from the scaffold
        inst = _cli("skill", "install", TOOL, "--target", "dottie", "--force")
        assert installed_skill.joinpath("SKILL.md").exists(), inst

        # 5. registry sees it
        assert TOOL in _tool_names(_cli("forge", "list"))

        # 6. second pass: the new capability executes a REAL computation
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b\n1,10\n2,20\n3,30\n", encoding="utf-8")
        result = _cli(TOOL, "run", "--path", str(csv_file))
        cols = (result.get("data", result))["columns"]
        assert cols["a"] == {"count": 3, "mean": 2.0, "min": 1.0, "max": 3.0}
        assert cols["b"]["mean"] == 20.0
    finally:
        subprocess.run([sys.executable, "-m", "bigbang.cli", "forge", "rm", TOOL,
                        "--force"], capture_output=True, text=True, timeout=60,
                       cwd=str(SCOUT_ROOT))
        shutil.rmtree(packaged_skill, ignore_errors=True)
        shutil.rmtree(installed_skill, ignore_errors=True)
        shutil.rmtree(plugin_dir, ignore_errors=True)

    # gone again — the loop leaves no residue
    assert TOOL not in _tool_names(_cli("forge", "list"))
