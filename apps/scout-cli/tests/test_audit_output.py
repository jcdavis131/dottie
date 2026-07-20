"""Tests for the emit() -> audit.jsonl pipeline (findings #1/#2)."""

import json

import pytest

from bigbang.core import audit, output


@pytest.fixture()
def audit_file(tmp_path, monkeypatch):
    f = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_FILE", f)
    return f


def _last_entry(audit_file):
    lines = audit_file.read_text().strip().splitlines()
    return json.loads(lines[-1])


def test_emit_writes_audit_line(audit_file, capsys):
    output.set_json_mode(True)
    output.emit({"status": "ok", "count": 3}, command="tools list")
    assert audit_file.exists(), "emit() must write an audit line"
    entry = _last_entry(audit_file)
    assert entry["command"] == "tools list"
    assert entry["args"] == {"status": "ok", "count": 3}
    assert entry["status"] == "ok"
    # stdout still carries valid JSON
    assert json.loads(capsys.readouterr().out) == {"status": "ok", "count": 3}


def test_emit_redacts_secret_bearing_keys(audit_file, capsys):
    output.set_json_mode(True)
    payload = {
        "name": "OPENAI_API_KEY",
        "value": "sk-live-abcdef1234567890",
        "token": "ghp_ABCDEFGHIJKLMNOP",
        "secret": "hunter2",
        "password": "p4ssw0rd",
        "credential": "top",
        "nested": {"api_key": "sk-nested-1234567890", "safe": "hello"},
        "listed": [{"token": "xoxb-1234-abcdefgh"}],
    }
    output.emit(payload, command="secrets get")
    capsys.readouterr()
    entry = _last_entry(audit_file)
    raw = json.dumps(entry)
    for leaked in (
        "sk-live-abcdef1234567890",
        "ghp_ABCDEFGHIJKLMNOP",
        "hunter2",
        "p4ssw0rd",
        "sk-nested-1234567890",
        "xoxb-1234-abcdefgh",
    ):
        assert leaked not in raw, f"secret {leaked!r} leaked into audit.jsonl"
    assert entry["args"]["value"] == "[REDACTED]"
    assert entry["args"]["nested"]["safe"] == "hello"


def test_emit_redacts_secret_substrings_in_plain_keys(audit_file, capsys):
    output.set_json_mode(True)
    output.emit(
        {"cmd": "curl -H 'Authorization: Bearer sk-abc123456789'"}, command="tools call"
    )
    capsys.readouterr()
    raw = audit_file.read_text()
    assert "sk-abc123456789" not in raw


def test_audit_io_errors_tolerated_but_others_loud(tmp_path, monkeypatch, capsys):
    # OSError path: unwritable audit target must not crash emit()
    monkeypatch.setattr(
        audit, "AUDIT_FILE", tmp_path / "no" / "such" / "dir" / "a.jsonl"
    )
    output.set_json_mode(True)
    output.emit({"ok": True}, command="x")  # should not raise
    capsys.readouterr()

    # Non-IO errors inside logging must propagate (no silent swallowing)
    def boom(*a, **kw):
        raise ValueError("bug in audit path")

    monkeypatch.setattr(audit, "log_event", boom)
    monkeypatch.setattr("bigbang.core.audit.log_event", boom)
    with pytest.raises(ValueError):
        output.emit({"ok": True}, command="x")
    capsys.readouterr()
