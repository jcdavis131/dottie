"""`scout forge` path handling. 509 loc, no test file until 2026-08-02.

forge GENERATES other plugins, so it was picked by blast radius rather than by GOAT score
(7.83, mid-table). Reading it found a destructive path traversal.

    forge rm ../victim --force
    -> {"ok": true, "removed": "../victim", "dir": ".../plugins/../victim"}
    victim directory: GONE

Proven in an isolated sandbox with PLUGIN_ROOT redirected — never against the real tree.
`PLUGIN_ROOT / name` follows `..`, and an absolute path discards PLUGIN_ROOT entirely, so
in this repo `scout forge rm ../core --force` was an rmtree of bigbang/core reported as a
success.

_valid_name existed and guarded new_plugin and from_openapi. The four commands that take
the name of an EXISTING plugin never called it:

    cat_cmd    reads   -> arbitrary file read
    edit_cmd   writes  -> arbitrary file write
    test_cmd   runs    -> subprocess against an arbitrary dir
    rm_cmd     deletes -> rmtree of an arbitrary dir

The guard now lives in _plugin_dir, so a fifth caller cannot miss it.
"""

from __future__ import annotations

import pytest
import typer

from bigbang.core.output import set_json_mode
from bigbang.plugins.forge import cli as fc


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """PLUGIN_ROOT redirected BEFORE any command runs. Nothing here touches the real tree."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    monkeypatch.setattr(fc, "PLUGIN_ROOT", plugins)
    monkeypatch.setattr(fc, "SKILLS_ROOT", tmp_path / "skills")
    set_json_mode(True)
    yield tmp_path
    set_json_mode(False)


@pytest.mark.parametrize(
    "name",
    ["../victim", "../../cli.py", "C:/Windows/Temp/x", "/etc/passwd", "..", "a/b"],
)
def test_traversing_names_are_refused(name):
    """The defect. Each of these escaped PLUGIN_ROOT before the guard existed."""
    with pytest.raises(typer.Exit):
        fc._plugin_dir(name)


def test_rm_cannot_delete_outside_the_plugin_root(sandbox):
    """End-to-end on the destructive command, which is how the bug was found."""
    victim = sandbox / "victim"
    victim.mkdir()
    (victim / "important.py").write_text("core code", encoding="utf-8")

    with pytest.raises(typer.Exit):
        fc.rm_cmd(name="../victim", force=True)

    assert victim.exists(), "rm escaped the plugin root"
    assert (victim / "important.py").read_text(encoding="utf-8") == "core code"


def test_a_legitimate_name_still_resolves(sandbox):
    """Non-vacuity. A guard that rejected everything would pass every test above and
    break the plugin entirely."""
    got = fc._plugin_dir("mytool")
    assert got == sandbox / "plugins" / "mytool"


def test_rm_still_removes_a_real_plugin(sandbox):
    """The destructive path must remain capable of destroying the right thing."""
    pdir = sandbox / "plugins" / "mytool"
    pdir.mkdir(parents=True)
    (pdir / "cli.py").write_text("x", encoding="utf-8")

    fc.rm_cmd(name="mytool", force=True)
    assert not pdir.exists()


def test_rm_without_force_refuses_and_does_not_delete(sandbox):
    """--force is the guard on the guard. fail_agent raises typer.Exit, so execution must
    not reach rmtree — verified rather than assumed."""
    pdir = sandbox / "plugins" / "mytool"
    pdir.mkdir(parents=True)

    with pytest.raises(typer.Exit):
        fc.rm_cmd(name="mytool", force=False)
    assert pdir.exists(), "deleted without --force"


def test_the_name_pattern_and_the_containment_check_are_both_present():
    """Two checks, not one. The pattern alone suffices today and is one loosened regex
    away from not doing; containment is the property actually wanted."""
    import inspect

    src = inspect.getsource(fc._plugin_dir)
    assert "_valid_name" in src
    assert "parents" in src or "resolve" in src


# --- skills root, same guard as the plugin root -------------------------------------
#
# _scaffold_skill_md's only caller (new_plugin) validates first, so this was not a live
# hole. It is guarded anyway because "the caller happens to validate" is exactly the
# property that failed for _plugin_dir: _valid_name guarded two commands while four
# others, added later, used it directly.


@pytest.mark.parametrize("name", ["../victim", "C:/Windows/Temp/x", "a/b"])
def test_skill_dir_refuses_traversal(name, tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "SKILLS_ROOT", tmp_path / "skills")
    with pytest.raises(typer.Exit):
        fc._skill_dir(name)


def test_skill_dir_allows_a_legitimate_name(tmp_path, monkeypatch):
    """Non-vacuity: forging a real tool must still write its SKILL.md."""
    monkeypatch.setattr(fc, "SKILLS_ROOT", tmp_path / "skills")
    assert fc._skill_dir("mytool") == tmp_path / "skills" / "mytool"


def test_scaffold_skill_md_cannot_write_outside_the_skills_root(tmp_path, monkeypatch):
    """End-to-end through the writer, not just the path helper."""
    monkeypatch.setattr(fc, "SKILLS_ROOT", tmp_path / "skills")
    victim = tmp_path / "victim"
    victim.mkdir()

    with pytest.raises(typer.Exit):
        fc._scaffold_skill_md("../victim", "desc")

    assert not (victim / "SKILL.md").exists()
