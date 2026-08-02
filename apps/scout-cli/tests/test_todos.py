"""The todos plugin. 529 loc, no test file until 2026-08-02.

GOAT ranked todos LAST in the repo. Reading it rather than acting on the number found that
two of its three worst dimensions were mismeasurement (fixed in goat_audit.py, same commit)
and one was a real defect in the thing the plugin exists to do.

THE DEFECT. MARKER_RE anchored on the RIGHT only:

    (?P<marker>TODO|FIXME|HACK|XXX|BUG)\\b

so every DEBUG in the tree matched as a BUG marker, and re.IGNORECASE caught lowercase
`debug` too. Measured over bigbang/ before the fix:

    shipped regex : 85 markers
    with \\b       : 58 markers
    false         : 27  (31.8%)

`LEVEL_DEBUG = "debug"`, `logger.setLevel(DEBUG)`, `.lv-debug` inside a CSS string — all
reported as outstanding BUGs. A third of the output of the one plugin whose entire job is
counting markers accurately.

conftest.py redirects HOME, and every scan below runs against a tmp_path, so nothing here
depends on the developer's tree.
"""

from __future__ import annotations

import json

import pytest

from bigbang.core.output import set_json_mode
from bigbang.plugins.todos import cli as tc


@pytest.fixture(autouse=True)
def _json_mode():
    set_json_mode(True)
    yield
    set_json_mode(False)


def _emitted(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


# --- the regex, which is the whole product -------------------------------------------

@pytest.mark.parametrize(
    "line",
    [
        'LEVEL_DEBUG = "debug"',
        "logger.setLevel(DEBUG)",
        "if DEBUG:",
        "self.DEBUG = 1",
        ".lv-info, .lv-debug {{ background: #4a5b70; }}",
        "raise ValueError('DEBUG')",
    ],
)
def test_debug_is_not_a_bug_marker(line):
    """The defect. 27 of 85 markers reported over bigbang/ were this."""
    assert tc.MARKER_RE.search(line) is None, f"DEBUG matched as a marker: {line}"


@pytest.mark.parametrize(
    ("line", "marker"),
    [
        ("# TODO: wire this up", "TODO"),
        ("# FIXME broken on windows", "FIXME"),
        ("# HACK: works for now", "HACK"),
        ("# XXX revisit", "XXX"),
        ("# BUG: off by one", "BUG"),
        ("#TODO no space after the hash", "TODO"),
        ("    // TODO in a js file", "TODO"),
    ],
)
def test_real_markers_are_still_found(line, marker):
    """Non-vacuity for the tests above.

    A regex that matched nothing would satisfy every DEBUG case and destroy the plugin.
    `#TODO` is included deliberately: the fix adds a leading \\b, and `#` is a non-word
    character so the boundary still holds.
    """
    m = tc.MARKER_RE.search(line)
    assert m is not None, f"real marker missed: {line}"
    assert m.group("marker").upper() == marker


# --- scanning ------------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path):
    """A small tree with one real marker and one DEBUG decoy."""
    (tmp_path / "bigbang" / "plugins" / "demo").mkdir(parents=True)
    (tmp_path / "bigbang" / "cli.py").write_text("# TODO: root marker\n", encoding="utf-8")
    (tmp_path / "bigbang" / "plugins" / "demo" / "cli.py").write_text(
        'LEVEL_DEBUG = "debug"\n# FIXME: demo marker\n', encoding="utf-8"
    )
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.py").write_text("# TODO: vendored\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG not text")
    return tmp_path


def test_scan_counts_only_real_markers(tree):
    res = tc._scan_markers(tree)
    markers = {m["marker"].upper() for m in res["todos"]}
    assert markers == {"TODO", "FIXME"}, res["todos"]
    assert res["total_markers"] == 2, res["todos"]


def test_scan_skips_vendored_directories(tree):
    """node_modules is in SKIP_DIRS. A TODO in there is not the user's TODO."""
    files = {m["file"] for m in tc._scan_markers(tree)["todos"]}
    assert not any("node_modules" in f for f in files), files


def test_scan_skips_binary_suffixes(tree):
    assert not any(m["file"].endswith(".png") for m in tc._scan_markers(tree)["todos"])


def test_type_filter_narrows(tree):
    res = tc._scan_markers(tree, type_filter="FIXME")
    assert {m["marker"].upper() for m in res["todos"]} == {"FIXME"}


def test_max_items_is_respected(tree):
    assert len(tc._scan_markers(tree, max_items=1)["todos"]) <= 1


# --- helpers -------------------------------------------------------------------------


def test_derive_plugin_reads_the_plugins_directory(tree):
    name = tc._derive_plugin(tree / "bigbang" / "plugins" / "demo" / "cli.py", tree)
    assert name == "demo"


def test_derive_plugin_falls_back_to_core(tree):
    assert tc._derive_plugin(tree / "bigbang" / "cli.py", tree) == "core"


def test_should_confirm_is_false_inside_the_root(tmp_path):
    (tmp_path / "sub").mkdir()
    assert tc._should_confirm(tmp_path, tmp_path / "sub") is False


def test_should_confirm_is_true_outside_the_root(tmp_path):
    """Non-vacuity: the confirm gate must be capable of firing."""
    other = tmp_path.parent / (tmp_path.name + "-elsewhere")
    other.mkdir()
    assert tc._should_confirm(tmp_path, other) is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), ("YES", True), ("on", True),
     ("0", False), ("no", False), ("", False), (None, False)],
)
def test_truthy_env_parsing(value, expected):
    assert tc._is_truthy_env(value) is expected


# --- commands ------------------------------------------------------------------------


def test_list_cmd_emits_a_json_envelope(tree, capsys):
    tc.list_cmd(path=str(tree), type_filter=None, max_items=500, yes=True)
    payload = _emitted(capsys)
    assert payload["ok"] is True
    assert payload["data"]["total_markers"] == 2


def test_summary_cmd_emits_a_json_envelope(tree, capsys):
    tc.summary_cmd(path=str(tree), yes=True)
    payload = _emitted(capsys)
    assert payload["ok"] is True


def test_resolve_root_finds_the_package_without_any_env(monkeypatch):
    """_resolve_root is __file__-relative first; DOTTIE_ROOT and ~/workspace/dottie are
    guarded fallbacks that can only return paths that exist.

    GOAT scored todos D3 2 — lowest in the repo — largely for the expanduser() calls that
    honour `~` in USER-supplied --path values, which is correct behaviour, not a layout
    assumption. Pinned here so the real property is asserted rather than the score.
    """
    monkeypatch.delenv("DOTTIE_ROOT", raising=False)
    root = tc._resolve_root()
    assert (root / "bigbang" / "cli.py").exists(), root
