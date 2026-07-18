"""Tests for bigbang-bridge/cli.py via typer's CliRunner with emit stubbed."""

import json

import httpx
import pytest
from typer.testing import CliRunner

runner = CliRunner()


# --- CUSTOM_ROOT resolution ------------------------------------------------

def test_custom_root_env_override(cli_mod, tmp_path):
    assert cli_mod.CUSTOM_ROOT == tmp_path / "rtx-root"


def test_custom_root_fallback_order(cli_mod, monkeypatch, tmp_path):
    monkeypatch.delenv("SCOUT_RTX_ROOT", raising=False)
    fake_home = tmp_path / "home"
    monkeypatch.setattr(cli_mod.Path, "home", classmethod(lambda cls: fake_home))
    # neither checkout exists -> scout-rtx fallback
    assert cli_mod._resolve_custom_root() == fake_home / "workspace" / "scout-rtx"
    # legacy checkout exists -> preferred
    legacy = fake_home / "workspace" / "autoresearch-rtx-custom"
    legacy.mkdir(parents=True)
    assert cli_mod._resolve_custom_root() == legacy


# --- queue add / list / clear ----------------------------------------------

def test_queue_add_list_clear(cli_mod, emit_records):
    result = runner.invoke(cli_mod.app, ["queue", "add", "--task", "tune router entropy", "--program", "programs/program-ava.md"])
    assert result.exit_code == 0
    added = emit_records[-1]
    assert added["added"]["task"] == "tune router entropy"
    assert added["added"]["status"] == "pending"
    assert cli_mod.QUEUE_FILE.exists()

    result = runner.invoke(cli_mod.app, ["queue", "list"])
    assert result.exit_code == 0
    listed = emit_records[-1]
    assert len(listed["tasks"]) == 1
    assert listed["tasks"][0]["program"] == "programs/program-ava.md"

    result = runner.invoke(cli_mod.app, ["queue", "clear"])
    assert result.exit_code == 0
    assert emit_records[-1]["cleared"] is True
    assert json.loads(cli_mod.QUEUE_FILE.read_text()) == {"tasks": []}


def test_queue_add_without_task_errors(cli_mod, emit_records):
    result = runner.invoke(cli_mod.app, ["queue", "add"])
    assert result.exit_code == 1
    assert "error" in emit_records[-1]


def test_queue_unknown_action(cli_mod, emit_records):
    result = runner.invoke(cli_mod.app, ["queue", "bogus"])
    assert result.exit_code == 0
    assert emit_records[-1]["valid"] == ["add", "list", "clear"]


# --- results TSV fallback returns LAST n rows ------------------------------

def test_results_tsv_fallback_returns_last_n(cli_mod, emit_records):
    header = "commit\tval_bpb\tmemory_gb\tstatus\tdescription"
    rows = [f"c{i}\t1.{i:02d}\t10\tkeep\trow{i}" for i in range(10)]
    cli_mod.RESULTS_TSV.parent.mkdir(parents=True, exist_ok=True)
    cli_mod.RESULTS_TSV.write_text("\n".join([header] + rows) + "\n")

    result = runner.invoke(cli_mod.app, ["results", "--n", "3"])
    assert result.exit_code == 0
    payload = emit_records[-1]
    assert payload["source"] == "results.tsv"
    assert payload["lines"][0] == header
    assert payload["lines"][1:] == rows[-3:]  # last 3, not first 3
    assert payload["count"] == 3


# --- sync actually writes the MRR record (no longer a stub) ----------------

def test_sync_appends_mrr_record(cli_mod, emit_records):
    cli_mod.RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {"ts": "t1", "commit": "aaa", "val_bpb": 1.02, "program": "program-ava.md"},
        {"ts": "t2", "commit": "bbb", "val_bpb": 0.98, "program": "program-ava.md"},
        {"ts": "t3", "commit": "ccc", "val_bpb": 1.10, "program": "program-base.md"},
    ]
    cli_mod.RESULTS_FILE.write_text("\n".join(json.dumps(l) for l in lines) + "\n")

    result = runner.invoke(cli_mod.app, ["sync"])
    assert result.exit_code == 0
    payload = emit_records[-1]
    assert payload["synced"] is True
    assert payload["best"]["commit"] == "bbb"

    written = [json.loads(l) for l in cli_mod.MRR_FILE.read_text().strip().splitlines()]
    assert len(written) == 1
    record = written[0]
    assert record["best"] == 0.98
    assert record["program"] == "program-ava.md"
    assert "ts" in record and "note" in record


def test_sync_without_results_is_honest(cli_mod, emit_records):
    result = runner.invoke(cli_mod.app, ["sync"])
    assert result.exit_code == 0
    assert emit_records[-1]["synced"] is False
    assert not cli_mod.MRR_FILE.exists()


# --- releases subcommand offline behavior ----------------------------------

def _raise_connect_error(*args, **kwargs):
    raise httpx.ConnectError("network unreachable")


def test_releases_list_offline_is_honest_nonzero(cli_mod, emit_records, monkeypatch):
    monkeypatch.setattr(cli_mod.httpx, "get", _raise_connect_error)
    result = runner.invoke(cli_mod.app, ["releases", "list"])
    assert result.exit_code == 1
    payload = emit_records[-1]
    assert payload["offline"] is True
    assert "api.github.com" in payload["error"]


def test_releases_sync_offline_is_honest_nonzero(cli_mod, emit_records, monkeypatch):
    monkeypatch.setattr(cli_mod.httpx, "get", _raise_connect_error)
    result = runner.invoke(cli_mod.app, ["releases", "sync", "--tag", "v0.6.0-ava-0716"])
    assert result.exit_code == 1
    assert emit_records[-1]["offline"] is True


def test_releases_list_parses_api_payload(cli_mod, emit_records, monkeypatch):
    fake_payload = [
        {
            "tag_name": "v0.6.0-ava-0716",
            "name": "v0.6.0-ava-0716 best 0.98",
            "published_at": "2026-07-16T00:00:00Z",
            "html_url": "https://github.com/jcdavis131/scout-rtx/releases/tag/v0.6.0-ava-0716",
            "assets": [{"name": "results.tsv", "size": 337, "browser_download_url": "https://example.invalid/results.tsv"}],
        }
    ]

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return fake_payload

    monkeypatch.setattr(cli_mod.httpx, "get", lambda *a, **k: FakeResponse())
    result = runner.invoke(cli_mod.app, ["releases", "list"])
    assert result.exit_code == 0
    payload = emit_records[-1]
    assert payload["count"] == 1
    assert payload["releases"][0]["tag"] == "v0.6.0-ava-0716"
    assert payload["releases"][0]["assets"][0]["name"] == "results.tsv"


def test_releases_sync_404_reports_missing_tag(cli_mod, emit_records, monkeypatch):
    request = httpx.Request("GET", "https://api.github.com/x")
    response = httpx.Response(404, request=request)

    def raise_404(*args, **kwargs):
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr(cli_mod.httpx, "get", raise_404)
    result = runner.invoke(cli_mod.app, ["releases", "sync", "--tag", "v0.0.0-nope"])
    assert result.exit_code == 1
    assert "not found" in emit_records[-1]["error"]
