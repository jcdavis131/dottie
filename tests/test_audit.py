
"""Tests for audit — log_event and tail"""
import importlib.util, pathlib, json, sys, os
MOD_PATH = "/home/hatch/workspace/dottie/apps/scout-cli/bigbang/core/audit.py"
spec = importlib.util.spec_from_file_location("audit", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

def test_log_event_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "AUDIT_DIR", tmp_path)
    monkeypatch.setattr(mod, "AUDIT_FILE", tmp_path / "audit.jsonl")
    mod.log_event("test_cmd", {"arg":1}, status="ok", duration_ms=123)
    f = tmp_path / "audit.jsonl"
    assert f.exists()
    line = f.read_text().strip().split("\n")[-1]
    entry = json.loads(line)
    assert entry["command"] == "test_cmd"
    assert entry["args"]["arg"] == 1
    assert entry["status"] == "ok"

def test_tail_events_returns_list(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "AUDIT_DIR", tmp_path)
    monkeypatch.setattr(mod, "AUDIT_FILE", tmp_path / "audit.jsonl")
    # empty file case
    if (tmp_path / "audit.jsonl").exists():
        (tmp_path / "audit.jsonl").unlink()
    assert mod.tail_events(5) == []
    mod.log_event("cmd1", {}, status="ok")
    mod.log_event("cmd2", {}, status="ok")
    tail = mod.tail_events(n=1)
    assert len(tail) == 1
    assert tail[0]["command"] == "cmd2"

def test_log_event_handles_unserializable_args_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "AUDIT_DIR", tmp_path)
    monkeypatch.setattr(mod, "AUDIT_FILE", tmp_path / "audit.jsonl")
    # default=str should handle non-serializable
    mod.log_event("cmd", {"obj": set([1,2])})
    assert (tmp_path / "audit.jsonl").exists()
