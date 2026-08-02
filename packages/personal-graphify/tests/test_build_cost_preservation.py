# Solo personal project, no connection to employer, built with public/free-tier only
"""`cmd_build` must not destroy the cost log it claims to preserve.

The block was already commented "cost.json — preserve existing queries if present", and its
`except` branch did the opposite: on ANY parse failure it wrote a fresh default over the
file, discarding `queries` and `total_saved_tokens`. cost.json is append-only history — the
record of what every query saved — not a cache that can be rebuilt.

query.py::log_query_cost writes THIS SAME FILE and had the identical bug, fixed 2026-07-31
in e933ad7 (see tests/test_query_cost.py). That sweep fixed one writer and missed this one,
which is why these tests mirror those: two writers of one file must not drift.
"""

import argparse
import json

from personal_graphify.cli import cmd_build

COST_KEYS = {"nodes", "edges", "queries", "total_saved_tokens",
             "total_naive", "total_scoped", "mode"}


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "alpha.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (repo / "notes.md").write_text("# Notes\nSee [alpha](alpha.py).\n", encoding="utf-8")
    return repo


def _build_args(repo, out):
    return argparse.Namespace(path=str(repo), roots=[], out=str(out),
                              max_files=100, cluster="auto", update=False)


def _seed_cost(out, payload):
    out.mkdir(parents=True, exist_ok=True)
    (out / "cost.json").write_text(payload, encoding="utf-8")
    return out / "cost.json"


def test_existing_queries_survive_a_rebuild(tmp_path):
    repo, out = _repo(tmp_path), tmp_path / "out"
    _seed_cost(out, json.dumps({
        "nodes": 1, "edges": 0, "queries": [{"question": "q1", "saved": 40}],
        "total_saved_tokens": 40, "total_naive": 100, "total_scoped": 60,
        "mode": "ollama-first local",
    }))
    cmd_build(_build_args(repo, out))
    data = json.loads((out / "cost.json").read_text(encoding="utf-8"))
    assert data["queries"] == [{"question": "q1", "saved": 40}]
    assert data["total_saved_tokens"] == 40
    assert data["nodes"] > 0 and data["edges"] >= 0  # refreshed, not reset


def test_a_corrupt_cost_log_is_preserved_and_announced_not_silently_wiped(tmp_path, capsys):
    """The actual defect. A truncated file used to be replaced with zeros, no trace."""
    repo, out = _repo(tmp_path), tmp_path / "out"
    corrupt = '{"queries": [{"question": "q1", "saved": 40}], "total_saved'
    cost = _seed_cost(out, corrupt)

    cmd_build(_build_args(repo, out))

    backups = list(out.glob("cost.json.corrupt-*"))
    assert backups, "the unreadable bytes were discarded instead of preserved"
    assert backups[0].read_text(encoding="utf-8") == corrupt
    assert "unreadable" in capsys.readouterr().err
    # And the rebuilt file is usable rather than half-written.
    assert COST_KEYS <= set(json.loads(cost.read_text(encoding="utf-8")))


def test_every_path_writes_the_same_key_set(tmp_path):
    """The two former branches disagreed — the except path omitted total_naive/total_scoped.

    A reset therefore produced a dict shaped differently from a fresh one, which query.py
    then had to backfill. Pinning all three paths against one key set stops that drifting
    back.
    """
    repo = _repo(tmp_path)

    fresh = tmp_path / "out_fresh"
    cmd_build(_build_args(repo, fresh))
    assert COST_KEYS <= set(json.loads((fresh / "cost.json").read_text(encoding="utf-8")))

    existing = tmp_path / "out_existing"
    _seed_cost(existing, json.dumps({"queries": [], "total_saved_tokens": 0}))
    cmd_build(_build_args(repo, existing))
    assert COST_KEYS <= set(json.loads((existing / "cost.json").read_text(encoding="utf-8")))

    broken = tmp_path / "out_broken"
    _seed_cost(broken, "{not json")
    cmd_build(_build_args(repo, broken))
    assert COST_KEYS <= set(json.loads((broken / "cost.json").read_text(encoding="utf-8")))


def test_a_corrupt_cost_log_never_fails_the_build(tmp_path):
    """Non-negotiable: logging cost must not be able to break building the graph."""
    repo, out = _repo(tmp_path), tmp_path / "out"
    _seed_cost(out, "\x00\x01 not even text")
    stats = cmd_build(_build_args(repo, out))
    assert stats["nodes"] > 0


def test_unrelated_keys_are_not_dropped(tmp_path):
    """update() over a default, not a hand-picked copy — future keys must survive."""
    repo, out = _repo(tmp_path), tmp_path / "out"
    _seed_cost(out, json.dumps({"queries": [], "total_saved_tokens": 0,
                                "some_future_field": "keep me"}))
    cmd_build(_build_args(repo, out))
    data = json.loads((out / "cost.json").read_text(encoding="utf-8"))
    assert data["some_future_field"] == "keep me"
