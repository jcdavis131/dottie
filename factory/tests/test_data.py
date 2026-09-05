from __future__ import annotations

import json

import pytest

from factory import data
from factory.config import Factory, FactoryError


def test_check_reports_missing_required(ws: Factory):
    rows = {r["id"]: r for r in data.check(ws)}
    assert rows["d-report"]["problem"] == "missing" and rows["d-report"]["required"]
    assert rows["d-cache"]["problem"] == "missing"
    assert rows["d-static"]["problem"] is None and rows["d-static"]["sha16"]
    text = data.render_check(data.check(ws))
    assert "2 with a problem (2 required)" in text


def test_restore_copies_and_writes_manifest(ws: Factory):
    out = data.restore(ws, "d-cache")
    assert "restored from r1/src/x.bin" in out
    dest = ws.workspace / "r1" / "data" / "x.bin"
    assert dest.read_bytes() == b"cache-bytes"
    manifest = json.loads(dest.with_name("x.bin.manifest.json").read_text())
    assert manifest["restored_from"] == "r1/src/x.bin" and len(manifest["sha256"]) == 64
    with pytest.raises(FactoryError, match="--force"):
        data.restore(ws, "d-cache")
    assert "restored" in data.restore(ws, "d-cache", force=True)


def test_restore_without_sources(ws: Factory):
    with pytest.raises(FactoryError, match="no restore_from"):
        data.restore(ws, "d-static")
    d = json.loads(ws.datasets_path.read_text())
    d["datasets"][1]["restore_from"] = ["r1/nope.bin"]
    ws.datasets_path.write_text(json.dumps(d))
    with pytest.raises(FactoryError, match="no restore source present"):
        data.restore(ws, "d-cache")


def test_refresh_runs_then_freshness_from_json_key(ws: Factory, capsys):
    assert data.refresh(ws, "d-report") == 0
    assert "[d-report] $" in capsys.readouterr().out
    assert (ws.workspace / "r1" / "out" / "report.json").is_file()
    row = {r["id"]: r for r in data.check(ws)}["d-report"]
    assert row["present"] and row["age_days"] is not None
    # generated_at is fixed at 2026-09-05 in the fixture; cadence 7 days.
    assert row["problem"] in (None, "stale")


def test_stale_and_unreadable_freshness(ws: Factory):
    report = ws.workspace / "r1" / "out" / "report.json"
    report.parent.mkdir()
    report.write_text(
        json.dumps({"m": {"value": 1}, "generated_at": "2020-01-01T00:00:00Z"})
    )
    assert {r["id"]: r for r in data.check(ws)}["d-report"]["problem"] == "stale"
    report.write_text(json.dumps({"m": {"value": 1}}))
    assert {r["id"]: r for r in data.check(ws)}["d-report"][
        "problem"
    ] == "freshness unreadable"


def test_sha_mismatch(ws: Factory):
    d = json.loads(ws.datasets_path.read_text())
    d["datasets"][2]["expected_sha256"] = "0" * 64
    ws.datasets_path.write_text(json.dumps(d))
    assert {r["id"]: r for r in data.check(ws)}["d-static"]["problem"] == "sha mismatch"


def test_refresh_without_command(ws: Factory):
    with pytest.raises(FactoryError, match="no refresh command"):
        data.refresh(ws, "d-static")


def test_list(ws: Factory):
    assert "d-cache" in data.list_datasets(ws)
