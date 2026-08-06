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


class TestBusySessionsSurviveEviction:
    """evict_idle must never unload a session whose turn is in flight.

    last_active_utc is stamped only AFTER a turn completes, so a turn slower
    than idle_minutes -- routine with qwen3:8b on CPU -- looked idle and had
    its kernel dropped mid-execution, destroying the namespace the model had
    spent the whole turn building (review finding registry.py:276).
    """

    def test_a_busy_session_is_not_evicted(self, tmp_path) -> None:
        from datetime import UTC, datetime, timedelta

        reg = SessionRegistry(tmp_path / "s", kernel_factory=FakeKernel)
        s = reg.create(role="root", model_spec="fake:")
        long_ago = datetime.now(UTC) - timedelta(hours=5)
        # Backdate so it is unambiguously past the idle window.
        with reg._lock:
            idx = reg._read_index()
            idx[s.id]["last_active_utc"] = long_ago.isoformat(timespec="seconds")
            reg._write_index(idx)
        with reg.busy(s.id):
            assert reg.evict_idle(idle_minutes=30) == []
            assert s.id in reg.loaded_ids()  # still in memory, kernel intact
        # Once the turn ends it is evictable again.
        assert reg.evict_idle(idle_minutes=30) == [s.id]

    def test_busy_is_reentrant_by_refcount(self, tmp_path) -> None:
        reg = SessionRegistry(tmp_path / "s", kernel_factory=FakeKernel)
        s = reg.create(role="root", model_spec="fake:")
        with reg.busy(s.id):
            with reg.busy(s.id):
                assert reg.is_busy(s.id)
            # inner exit must NOT clear the flag the outer block still holds
            assert reg.is_busy(s.id)
        assert not reg.is_busy(s.id)

    def test_busy_clears_even_when_the_turn_raises(self, tmp_path) -> None:
        reg = SessionRegistry(tmp_path / "s", kernel_factory=FakeKernel)
        s = reg.create(role="root", model_spec="fake:")
        with pytest.raises(ValueError):
            with reg.busy(s.id):
                raise ValueError("turn blew up")
        assert not reg.is_busy(s.id)


class TestCrossProcessIndexSafety:
    """Two OS processes must not clobber each other's registry writes.

    self._lock is process-local: two `dottie-rlm run` invocations in separate
    terminals both read the index, both add their session, and the second
    write erases the first (review finding registry.py:184). The guard is an
    O_CREAT|O_EXCL lock file around the read-modify-write.
    """

    def test_two_real_processes_both_survive_registration(self, tmp_path) -> None:
        import subprocess
        import sys
        import textwrap

        root = tmp_path / "sessions"
        prog = textwrap.dedent(
            f"""
            import sys, time
            sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})
            from dottie_rlm.registry import SessionRegistry

            class K:
                def inject(self, *a, **k): pass
                def run(self, *a, **k): raise AssertionError("no exec in this test")

            reg = SessionRegistry({str(root)!r}, kernel_factory=K)
            for _ in range(15):
                reg.create(role="root", model_spec="fake:")
                time.sleep(0.005)
            print("OK")
            """
        )
        script = tmp_path / "spawn.py"
        script.write_text(prog, encoding="utf-8")
        procs = [
            subprocess.Popen(
                [sys.executable, str(script)], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            )
            for _ in range(2)
        ]
        outs = [p.communicate(timeout=180) for p in procs]
        for rc, (out, err) in zip([p.returncode for p in procs], outs, strict=True):
            assert rc == 0, f"child failed: {err[-800:]}"
            assert "OK" in out
        # 2 processes x 15 sessions: every one must be in the index. Without
        # the cross-process lock this lands well short.
        reg = SessionRegistry(root, kernel_factory=FakeKernel)
        assert len(reg.entries()) == 30, len(reg.entries())

    def test_no_lock_file_survives_a_clean_run(self, tmp_path) -> None:
        reg = SessionRegistry(tmp_path / "s", kernel_factory=FakeKernel)
        reg.create(role="root", model_spec="fake:")
        assert list((tmp_path / "s").glob("*.lock")) == []

    def test_a_stale_lock_is_broken_not_deadlocked(self, tmp_path, capsys) -> None:
        reg = SessionRegistry(tmp_path / "s", kernel_factory=FakeKernel)
        stale = reg.index_path.with_suffix(".lock")
        stale.write_text("99999", encoding="utf-8")  # holder that never released
        with reg._file_lock(timeout_s=0.2):
            pass
        assert "breaking stale registry lock" in capsys.readouterr().err
        assert not stale.exists()

    def test_the_lock_is_reentrant_within_one_process(self, tmp_path) -> None:
        """create() calls add(); a non-reentrant lock would break its own."""
        reg = SessionRegistry(tmp_path / "s", kernel_factory=FakeKernel)
        with reg._file_lock(timeout_s=1.0), reg._file_lock(timeout_s=1.0):
            assert reg._flock_depth == 2
        assert reg._flock_depth == 0
