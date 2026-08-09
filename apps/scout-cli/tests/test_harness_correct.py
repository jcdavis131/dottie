"""`harness correct` writes miner-valid operator corrections, fail-closed."""

import json

import pytest
from typer.testing import CliRunner

from bigbang.plugins.harness.cli import app

runner = CliRunner()


@pytest.fixture()
def real_run(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    run_id = "harness-run-test123"
    cp = tmp_path / ".cache" / "scout" / "checkpoints" / run_id
    cp.mkdir(parents=True)
    (cp / "checkpoint.json").write_text("{}")
    return run_id


def _correct(*args):
    return runner.invoke(app, ["correct", *args, "--json"])


def test_appends_miner_valid_line(real_run, tmp_path):
    target = tmp_path / "corrections.jsonl"
    res = _correct(real_run, "action_operator", "--reason", "executed tier was right", "--file", str(target))
    assert res.exit_code == 0
    out = json.loads(res.stdout)
    assert out["ok"] is True
    line = json.loads(target.read_text().strip())
    assert set(line) == {"run_id", "tier", "reason", "corrected_by", "date"}
    assert line["tier"] == "action_operator"
    assert line["run_id"] == real_run


def test_rejects_unknown_tier(real_run, tmp_path):
    res = _correct(real_run, "warp_drive", "--reason", "x", "--file", str(tmp_path / "c.jsonl"))
    out = json.loads(res.stdout)
    assert out["ok"] is False
    assert "unknown tier" in out["error"]


def test_rejects_missing_run(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    res = _correct("harness-run-ghost", "llm", "--reason", "x", "--file", str(tmp_path / "c.jsonl"))
    out = json.loads(res.stdout)
    assert out["ok"] is False
    assert "no checkpoint found" in out["error"]


def test_rejects_path_shaped_run_id(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    res = _correct("../etc/passwd", "llm", "--reason", "x", "--file", str(tmp_path / "c.jsonl"))
    out = json.loads(res.stdout)
    assert out["ok"] is False
    assert "invalid run id" in out["error"]


def test_rejects_duplicate_and_empty_reason(real_run, tmp_path):
    target = tmp_path / "c.jsonl"
    assert json.loads(_correct(real_run, "llm", "--reason", "first", "--file", str(target)).stdout)["ok"]
    dup = json.loads(_correct(real_run, "llm", "--reason", "second", "--file", str(target)).stdout)
    assert dup["ok"] is False
    assert "already has a correction" in dup["error"]
    empty = json.loads(_correct(real_run, "llm", "--reason", "   ", "--file", str(tmp_path / "c2.jsonl")).stdout)
    assert empty["ok"] is False


def test_dry_run_writes_nothing(real_run, tmp_path):
    target = tmp_path / "c.jsonl"
    res = json.loads(_correct(real_run, "llm", "--reason", "check", "--file", str(target), "--dry-run").stdout)
    assert res["ok"] is True and res["dry_run"] is True
    assert not target.exists()


def test_written_line_passes_the_miner_loader(real_run, tmp_path):
    # The load-bearing promise: what this command writes, the miner accepts.
    import importlib.util
    import sys

    target = tmp_path / "label_corrections.jsonl"
    assert json.loads(
        _correct(real_run, "deep_research", "--reason", "needed sources", "--file", str(target)).stdout
    )["ok"]

    miner_path = None
    for parent in __import__("pathlib").Path(__file__).resolve().parents:
        cand = parent / "apps" / "ava-factory" / "scripts" / "build_orchestration_corpus.py"
        if cand.exists():
            miner_path = cand
            break
    if miner_path is None:
        pytest.skip("monorepo miner not present in this layout")
    spec = importlib.util.spec_from_file_location("bc_for_correct_test", miner_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bc_for_correct_test"] = mod
    spec.loader.exec_module(mod)
    loaded = mod.load_corrections(target)
    assert loaded[real_run]["tier"] == "deep_research"
