"""Tests for dottie_rlm.registry — index, idle eviction, scope enforcement.

SPEC floor covered: idle eviction unloads (kernel dropped, turns flushed) and
reload-on-address works (fresh kernel + full history); the FOUR-WAY scope
matrix (parent ok / sibling ok / child ok / stranger raises) all asserted;
corrupt registry.json preserved loudly; anti-vacuity (index NON-EMPTY after
activity). No network, no real kernel — stub factories only.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# dottie_rlm may still be a bare namespace dir while other waves land their
# files; make the package importable regardless of pytest's rootdir handling.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dottie_rlm.registry import (
    RegistryError,
    ScopeError,
    SessionRegistry,
    default_root,
)
from dottie_rlm.session import CorruptStateError, Session

T0 = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


class FakeKernel:
    """Stands in for PersistentKernel (kernel.py is another wave's file)."""


@pytest.fixture()
def registry(tmp_path: Path) -> SessionRegistry:
    return SessionRegistry(tmp_path / "sessions", kernel_factory=FakeKernel)


# ---------------------------------------------------------------------------
# Root + index basics
# ---------------------------------------------------------------------------


def test_default_root_shape_without_touching_disk() -> None:
    # Pure path computation — no mkdir side effects from calling it.
    root = default_root()
    assert root.name == "sessions"
    assert "dottie-rlm" in root.parts


def test_add_indexes_live_and_index_nonempty(registry: SessionRegistry) -> None:
    s = registry.create(role="root", now=T0)
    # Anti-vacuity: after activity the index file is NON-EMPTY and parseable.
    assert registry.index_path.stat().st_size > 0
    raw = json.loads(registry.index_path.read_text(encoding="utf-8"))
    entry = raw["sessions"][s.id]
    assert entry["state"] == "live"
    assert entry["parent_id"] is None
    assert entry["last_active_utc"] == T0.isoformat(timespec="seconds")
    assert registry.loaded_ids() == {s.id}
    # The session itself was persisted under root at add time.
    assert (registry.root / s.id / "session.json").exists()


def test_duplicate_add_raises(registry: SessionRegistry) -> None:
    s = registry.create(now=T0)
    with pytest.raises(RegistryError, match="already registered"):
        registry.add(Session(id=s.id))


def test_create_child_requires_known_parent(registry: SessionRegistry) -> None:
    with pytest.raises(RegistryError, match="unknown session"):
        registry.create(role="sub", parent_id="deadbeef0000", now=T0)


def test_get_unknown_raises(registry: SessionRegistry) -> None:
    with pytest.raises(RegistryError, match="unknown session"):
        registry.get("deadbeef0000")


def test_missing_index_is_empty(registry: SessionRegistry) -> None:
    assert registry.entries() == []  # missing is empty ...


def test_corrupt_index_preserved_loudly(
    registry: SessionRegistry, capsys: pytest.CaptureFixture[str]
) -> None:
    registry.create(now=T0)
    garbage = b"** not json **"
    registry.index_path.write_bytes(garbage)
    with pytest.raises(CorruptStateError, match="preserved"):
        registry.entries()
    # ... but unreadable is NOT: exact bytes preserved + stderr announce.
    preserved = list(registry.root.glob("registry.json.corrupt-*"))
    assert len(preserved) == 1
    assert preserved[0].read_bytes() == garbage
    assert "CORRUPT" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Addressing, touch, done
# ---------------------------------------------------------------------------


def test_get_live_returns_same_object_and_touches(registry: SessionRegistry) -> None:
    s = registry.create(now=T0)
    later = T0 + timedelta(minutes=5)
    assert registry.get(s.id, now=later) is s
    entry = registry.entries()[0]
    assert entry["last_active_utc"] == later.isoformat(timespec="seconds")


def test_touch_updates_last_active(registry: SessionRegistry) -> None:
    s = registry.create(now=T0)
    later = T0 + timedelta(minutes=7)
    registry.touch(s.id, now=later)
    assert registry.entries()[0]["last_active_utc"] == later.isoformat(
        timespec="seconds"
    )


def test_mark_done_persists_and_refuses_reload(registry: SessionRegistry) -> None:
    s = registry.create(now=T0)
    s.record_turn("model", text="finished")
    registry.mark_done(s.id, now=T0 + timedelta(minutes=1))
    assert registry.loaded_ids() == set()
    assert registry.entries()[0]["state"] == "done"
    # Turns were flushed before unload.
    traj = registry.root / s.id / "trajectory.jsonl"
    assert traj.stat().st_size > 0
    with pytest.raises(RegistryError, match="done"):
        registry.get(s.id)


# ---------------------------------------------------------------------------
# Idle eviction + reload-on-address
# ---------------------------------------------------------------------------


def test_evict_idle_unloads_stale_keeps_fresh(registry: SessionRegistry) -> None:
    stale = registry.create(now=T0)
    fresh = registry.create(now=T0)
    registry.touch(fresh.id, now=T0 + timedelta(minutes=20))
    evicted = registry.evict_idle(now=T0 + timedelta(minutes=31), idle_minutes=30)
    assert evicted == [stale.id]
    assert registry.loaded_ids() == {fresh.id}
    states = {e["id"]: e["state"] for e in registry.entries()}
    assert states[stale.id] == "idle"
    assert states[fresh.id] == "live"


def test_evict_skips_done_and_already_idle(registry: SessionRegistry) -> None:
    a = registry.create(now=T0)
    b = registry.create(now=T0)
    registry.mark_done(b.id, now=T0)
    assert registry.evict_idle(now=T0 + timedelta(hours=2)) == [a.id]
    # A second sweep finds nothing live — idle/done are not re-evicted.
    assert registry.evict_idle(now=T0 + timedelta(hours=4)) == []


def test_eviction_flushes_turns_and_drops_kernel(registry: SessionRegistry) -> None:
    s = registry.create(now=T0)
    kernel_before = s.ensure_kernel()
    assert isinstance(kernel_before, FakeKernel)
    s.record_turn("model", text="unsaved-in-memory")
    registry.evict_idle(now=T0 + timedelta(hours=1))
    assert s.kernel is None  # kernel dropped on unload
    lines = (
        (registry.root / s.id / "trajectory.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert json.loads(lines[-1])["text"] == "unsaved-in-memory"  # flushed first


def test_reload_on_address_fresh_kernel_full_history(
    registry: SessionRegistry,
) -> None:
    s = registry.create(now=T0)
    old_kernel = s.ensure_kernel()
    s.record_turn("system", text="boot")
    s.record_turn("model", text="working")
    assert registry.evict_idle(now=T0 + timedelta(hours=1)) == [s.id]
    assert registry.loaded_ids() == set()

    reload_t = T0 + timedelta(hours=2)
    reloaded = registry.get(s.id, now=reload_t)
    assert reloaded is not s  # a fresh object, reloaded from disk
    assert [t["text"] for t in reloaded.history] == ["boot", "working"]  # intact
    assert reloaded.kernel is None
    new_kernel = reloaded.ensure_kernel()
    assert isinstance(new_kernel, FakeKernel)
    assert new_kernel is not old_kernel  # fresh kernel, not the evicted one
    entry = registry.entries()[0]
    assert entry["state"] == "live"
    assert entry["last_active_utc"] == reload_t.isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Scope matrix — parent ok / sibling ok / child ok / stranger raises
# ---------------------------------------------------------------------------


@pytest.fixture()
def family(registry: SessionRegistry) -> dict[str, str]:
    root = registry.create(role="root", now=T0)
    b = registry.create(role="sub", parent_id=root.id, now=T0)
    c = registry.create(role="sub", parent_id=root.id, now=T0)
    d = registry.create(role="sub", parent_id=b.id, now=T0)
    stranger = registry.create(role="root", now=T0)  # an independent tree
    return {"A": root.id, "B": b.id, "C": c.id, "D": d.id, "E": stranger.id}


def test_scope_matrix_four_way(
    registry: SessionRegistry, family: dict[str, str]
) -> None:
    b = family["B"]
    # 1) parent: OK
    registry.check_scope(b, family["A"])
    # 2) sibling (same parent): OK
    registry.check_scope(b, family["C"])
    # 3) direct child: OK
    registry.check_scope(b, family["D"])
    # 4) stranger: raises — enforced, not advisory.
    with pytest.raises(ScopeError, match="may not message"):
        registry.check_scope(b, family["E"])
    assert registry.allowed_targets(b) == {family["A"], family["C"], family["D"]}


def test_scope_excludes_self_and_grandchildren(
    registry: SessionRegistry, family: dict[str, str]
) -> None:
    assert family["A"] not in registry.allowed_targets(family["A"])
    with pytest.raises(ScopeError):
        registry.check_scope(family["A"], family["A"])
    # D is A's grandchild — out of scope in both directions.
    with pytest.raises(ScopeError):
        registry.check_scope(family["A"], family["D"])
    with pytest.raises(ScopeError):
        registry.check_scope(family["D"], family["A"])


def test_two_roots_are_strangers_not_siblings(
    registry: SessionRegistry, family: dict[str, str]
) -> None:
    # Documented resolution: parent_id=None sessions share NO parent, so they
    # are not siblings — independent session trees stay isolated.
    assert registry.allowed_targets(family["E"]) == set()
    with pytest.raises(ScopeError, match="may not message"):
        registry.check_scope(family["E"], family["A"])


def test_allowed_targets_unknown_sender_raises(registry: SessionRegistry) -> None:
    with pytest.raises(ScopeError, match="unknown sender"):
        registry.allowed_targets("deadbeef0000")
