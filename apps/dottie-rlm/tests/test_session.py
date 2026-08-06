"""Tests for dottie_rlm.session — Session save/load, trajectory, corrupt-loud.

SPEC floor covered: save→load round-trip; corrupt session.json preserved
loudly (bytes intact, stderr announce, raise); kernel not persisted (reload =
fresh kernel, history intact); trajectory is append-only with no duplication;
missing trajectory is empty history; anti-vacuity (trajectory NON-EMPTY after
activity). No network, no real kernel — stub factories only.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

# dottie_rlm may still be a bare namespace dir while other waves land their
# files; make the package importable regardless of pytest's rootdir handling.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dottie_rlm.session import (
    ROLES,
    TRAJECTORY_NAME,
    TURN_KINDS,
    CorruptStateError,
    Session,
    SessionError,
)


class FakeKernel:
    """Stands in for PersistentKernel (kernel.py is another wave's file)."""


def fake_factory() -> FakeKernel:
    return FakeKernel()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_new_session_defaults() -> None:
    s = Session()
    assert len(s.id) == 12
    int(s.id, 16)  # uuid4 hex12
    assert s.role == "root"
    assert s.parent_id is None
    assert s.history == []
    assert s.kernel is None
    datetime.fromisoformat(s.created_utc)  # parseable UTC timestamp


def test_invalid_role_rejected() -> None:
    with pytest.raises(ValueError, match="role"):
        Session(role="overlord")
    assert set(ROLES) == {"root", "sub"}


@pytest.mark.parametrize("bad_id", ["", "a/b", "a\\b", "..", "x" * 65])
def test_invalid_id_rejected(bad_id: str) -> None:
    # ids double as directory names — path separators/dot-dot must be rejected
    with pytest.raises(ValueError, match="session id"):
        Session(id=bad_id)


# ---------------------------------------------------------------------------
# Turns
# ---------------------------------------------------------------------------


def test_record_turn_shape_and_validation() -> None:
    s = Session()
    turn = s.record_turn("model", text="hello")
    assert turn["kind"] == "model"
    assert turn["text"] == "hello"
    datetime.fromisoformat(turn["t"])
    assert s.history == [turn]
    with pytest.raises(ValueError, match="turn kind"):
        s.record_turn("thought", text="nope")
    with pytest.raises(ValueError, match="reserved"):
        s.record_turn("model", t="2020-01-01T00:00:00+00:00")
    with pytest.raises(TypeError):
        # "kind" collides with the positional parameter — Python enforces it.
        s.record_turn("model", **{"kind": "exec"})
    assert set(TURN_KINDS) == {"model", "exec", "message", "system"}


# ---------------------------------------------------------------------------
# Save: layout + anti-vacuity
# ---------------------------------------------------------------------------


def test_save_layout_and_trajectory_nonempty(tmp_path: Path) -> None:
    s = Session(base_prompt="be useful")
    s.record_turn("system", text="boot")
    s.record_turn("model", text="hi")
    sdir = s.save(tmp_path)
    assert sdir == tmp_path / s.id
    meta = json.loads((sdir / "session.json").read_text(encoding="utf-8"))
    assert meta["id"] == s.id
    assert meta["turns"] == 2
    traj = sdir / TRAJECTORY_NAME
    # Anti-vacuity: after activity the trajectory file is NON-EMPTY.
    assert traj.stat().st_size > 0
    lines = traj.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(ln)["kind"] for ln in lines] == ["system", "model"]


def test_resave_and_live_append_never_duplicate(tmp_path: Path) -> None:
    s = Session()
    s.record_turn("system", text="boot")
    s.save(tmp_path)
    # Bound now: record_turn appends to the trajectory immediately.
    s.record_turn("model", text="hi")
    traj = tmp_path / s.id / TRAJECTORY_NAME
    assert len(traj.read_text(encoding="utf-8").splitlines()) == 2
    # A second save reconciles by line count — no duplicates.
    s.save(tmp_path)
    s.save(tmp_path)
    assert len(traj.read_text(encoding="utf-8").splitlines()) == 2


def test_save_refuses_longer_trajectory_on_disk(tmp_path: Path) -> None:
    s = Session()
    s.record_turn("model", text="one")
    s.save(tmp_path)
    stale = Session(id=s.id)  # same id, empty history — a stale object
    with pytest.raises(SessionError, match="refusing"):
        stale.save(tmp_path)


# ---------------------------------------------------------------------------
# Load: round-trip, fresh kernel, missing/corrupt
# ---------------------------------------------------------------------------


def test_save_load_round_trip_history_intact_kernel_not_persisted(
    tmp_path: Path,
) -> None:
    s = Session(
        role="sub",
        parent_id="abc123abc123",
        model_spec="ollama:qwen3:8b",
        base_prompt="child prompt",
        kernel_factory=fake_factory,
    )
    first_kernel = s.ensure_kernel()
    assert isinstance(first_kernel, FakeKernel)
    s.record_turn("message", text="from parent")
    s.record_turn("exec", stdout="42")
    s.save(tmp_path)

    loaded = Session.load(tmp_path, s.id, kernel_factory=fake_factory)
    assert loaded.id == s.id
    assert loaded.parent_id == "abc123abc123"
    assert loaded.role == "sub"
    assert loaded.model_spec == "ollama:qwen3:8b"
    assert loaded.base_prompt == "child prompt"
    assert loaded.created_utc == s.created_utc
    assert loaded.history == s.history  # full history, intact
    # The KERNEL namespace is NOT persisted: reload = fresh kernel.
    assert loaded.kernel is None
    fresh = loaded.ensure_kernel()
    assert isinstance(fresh, FakeKernel)
    assert fresh is not first_kernel


def test_loaded_session_is_bound_and_appends_live(tmp_path: Path) -> None:
    s = Session()
    s.record_turn("model", text="a")
    s.save(tmp_path)
    loaded = Session.load(tmp_path, s.id)
    loaded.record_turn("model", text="b")
    traj = tmp_path / s.id / TRAJECTORY_NAME
    lines = traj.read_text(encoding="utf-8").splitlines()
    assert [json.loads(ln)["text"] for ln in lines] == ["a", "b"]


def test_missing_trajectory_is_empty_history(tmp_path: Path) -> None:
    s = Session()
    s.save(tmp_path)  # zero turns → no trajectory file written
    assert not (tmp_path / s.id / TRAJECTORY_NAME).exists()
    loaded = Session.load(tmp_path, s.id)
    assert loaded.history == []  # missing is empty ...


def test_load_missing_session_raises_filenotfound(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="no session"):
        Session.load(tmp_path, "deadbeef0000")


def test_corrupt_session_json_preserved_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s = Session()
    s.record_turn("model", text="keep me")
    s.save(tmp_path)
    meta_path = tmp_path / s.id / "session.json"
    garbage = b"\x00{this is not json"
    meta_path.write_bytes(garbage)

    with pytest.raises(CorruptStateError, match="preserved"):
        Session.load(tmp_path, s.id)

    # ... but unreadable is NOT: the exact bytes are preserved + announced.
    preserved = list((tmp_path / s.id).glob("session.json.corrupt-*"))
    assert len(preserved) == 1
    assert preserved[0].read_bytes() == garbage
    assert "CORRUPT" in capsys.readouterr().err


def test_corrupt_trajectory_line_preserved_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s = Session()
    s.record_turn("model", text="fine")
    s.save(tmp_path)
    traj = tmp_path / s.id / TRAJECTORY_NAME
    original = traj.read_bytes()
    traj.write_bytes(original + b"}}}not json\n")

    with pytest.raises(CorruptStateError, match="line 2"):
        Session.load(tmp_path, s.id)
    preserved = list((tmp_path / s.id).glob(f"{TRAJECTORY_NAME}.corrupt-*"))
    assert len(preserved) == 1
    assert preserved[0].read_bytes() == original + b"}}}not json\n"
    assert "CORRUPT" in capsys.readouterr().err


def test_meta_id_mismatch_is_corrupt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sdir = tmp_path / "aaaaaaaaaaaa"
    sdir.mkdir(parents=True)
    (sdir / "session.json").write_text(
        json.dumps(
            {
                "id": "bbbbbbbbbbbb",
                "role": "root",
                "created_utc": "2026-08-06T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CorruptStateError, match=r"does not match|!="):
        Session.load(tmp_path, "aaaaaaaaaaaa")
    assert list(sdir.glob("session.json.corrupt-*"))
    assert "CORRUPT" in capsys.readouterr().err


def test_default_kernel_factory_error_is_actionable() -> None:
    # kernel.py is another wave's file; if it has not landed, ensure_kernel()
    # without an injected factory must refuse with actionable text, never
    # fabricate. If kernel.py HAS landed, ensure_kernel() must return a real
    # kernel. Either way: no silent None.
    s = Session()
    try:
        kernel = s.ensure_kernel()
    except SessionError as exc:
        assert "kernel_factory" in str(exc)
    else:
        assert kernel is not None
