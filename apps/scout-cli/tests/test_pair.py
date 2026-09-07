"""Unit tests for scout pair — jarvis-first with labeled filesystem fallback."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bigbang.plugins.pair import cli as pair_cli


class _FakeResp:
    def __init__(self, payload: dict[str, Any], status: int = 200):
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *args: object) -> None:
        return None


@pytest.fixture
def pair_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(pair_cli, "CONFIG_DIR", tmp_path / ".config" / "dottie")
    monkeypatch.setattr(pair_cli, "DATA_DIR", tmp_path / ".local" / "share" / "dottie")
    monkeypatch.setattr(pair_cli, "QUEUE_DIR", tmp_path / ".local" / "share" / "dottie" / "queue")
    monkeypatch.delenv("DOTTIE_WORKSPACE", raising=False)
    monkeypatch.setenv("JARVIS_URL", "http://127.0.0.1:8790")
    monkeypatch.setenv("JARVIS_BEARER", "test-bearer")
    return tmp_path


def test_create_prefers_jarvis(pair_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fake_urlopen(req: Any, timeout: float = 5):  # noqa: ARG001
        assert "8790" in req.full_url
        return _FakeResp({"ok": True, "code": "AB34XY", "exp": 9999999999, "created": 1, "agent": "scout"})

    monkeypatch.setattr(pair_cli.urllib.request, "urlopen", fake_urlopen)
    code = pair_cli.create(expire_min=10)
    assert code == "AB34XY"
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["source"] == "jarvis" and out["code"] == "AB34XY"


def test_create_file_fallback_when_jarvis_down(
    pair_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise OSError("down")

    monkeypatch.setattr(pair_cli.urllib.request, "urlopen", boom)
    code = pair_cli.create(expire_min=10)
    assert len(code) == 6
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["source"] == "file"
    assert out.get("jarvis_unreachable") is True
    pf = pair_cli._pair_file()
    assert pf.exists()
    saved = json.loads(pf.read_text())
    assert saved["code"] == code and saved.get("source") == "file"


def test_verify_unknown_via_jarvis_fails(
    pair_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_urlopen(req: Any, timeout: float = 5):  # noqa: ARG001
        return _FakeResp({"ok": False, "paired": False, "error": "unknown code", "code": "ZZZZZZ"})

    monkeypatch.setattr(pair_cli.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(pair_cli.typer.Exit):
        pair_cli.verify("ZZZZZZ")
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["source"] == "jarvis"
    assert "unknown" in (out.get("error") or "")


def test_verify_file_when_jarvis_unreachable(
    pair_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import time

    code = "AB34XY"
    exp = int(time.time()) + 600
    pair_cli._write_pair_file({"code": code, "exp": exp, "created": int(time.time()), "source": "file"})

    def boom(*args: Any, **kwargs: Any) -> None:
        raise OSError("down")

    monkeypatch.setattr(pair_cli.urllib.request, "urlopen", boom)
    pair_cli.verify(code)
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["source"] == "file" and out["paired"] is True


def test_status_labels_jarvis(pair_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[str] = []

    def fake_urlopen(req: Any, timeout: float = 5):  # noqa: ARG001
        calls.append(req.full_url)
        if "code=" in req.full_url:
            return _FakeResp({"ok": True, "paired": True, "code": "AB34XY", "exp": 9})
        return _FakeResp({"ok": True, "count": 1, "paired_count": 1})

    pair_cli._write_pair_file({"code": "AB34XY", "exp": 9, "created": 1, "source": "jarvis"})
    monkeypatch.setattr(pair_cli.urllib.request, "urlopen", fake_urlopen)
    pair_cli.status()
    out = json.loads(capsys.readouterr().out)
    assert out["source"] == "jarvis" and out["paired"] is True
