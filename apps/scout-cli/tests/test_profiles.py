# Solo personal project, no connection to employer, built with public/free-tier only
"""Hermes / OpenClaw dynamic profiles — registry, prompt shaping, real persistence.

The persistence tests run against a REAL JSpaceStateStore on a tmp database (via
DOTTIE_STATE_DB) — no mocks; a second store instance re-reads the file to prove the
cross-loop property the OpenClaw profile exists for.
"""
from __future__ import annotations

import pytest

from bigbang.core.profiles import (
    HERMES_SYSTEM_ROLE, OPENCLAW_SYSTEM_ROLE, PROFILES,
    after_run, build_system_prompt, get_profile,
)

skills_store = pytest.importorskip(
    "skills.state_store", reason="ava-skills workspace member not installed")


def test_registry_carries_the_mandated_system_roles():
    assert set(PROFILES) == {"hermes", "openclaw"}
    assert "Hermes runtime loop within Dottie" in HERMES_SYSTEM_ROLE
    assert "scout forge forge" in HERMES_SYSTEM_ROLE
    assert "OpenClaw orchestration loop within Dottie" in OPENCLAW_SYSTEM_ROLE
    assert "scout --json forge list" in OPENCLAW_SYSTEM_ROLE
    assert PROFILES["hermes"].refine_after_success
    assert PROFILES["openclaw"].persist_context


def test_get_profile_resolution(monkeypatch):
    assert get_profile("hermes").name == "hermes"
    monkeypatch.setenv("DOTTIE_PROFILE", "openclaw")
    assert get_profile().name == "openclaw"
    monkeypatch.delenv("DOTTIE_PROFILE")
    assert get_profile() is None
    with pytest.raises(KeyError, match="unknown profile"):
        get_profile("zeus")


def test_openclaw_prompt_reenters_with_real_session_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DOTTIE_STATE_DB", str(tmp_path / "state.sqlite3"))
    with skills_store.JSpaceStateStore() as st:
        st.set_context("sess-p3", "deploy_stage", "canary")
    p = build_system_prompt(PROFILES["openclaw"], session_id="sess-p3")
    assert p["persistence"] == "on"
    assert p["context"] == {"default": {"deploy_stage": "canary"}}
    assert "deploy_stage" in p["system"] and "canary" in p["system"]
    assert "scout --json forge list" in p["system"]      # discover-first directive


def test_hermes_after_run_registers_routine_and_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("DOTTIE_STATE_DB", str(tmp_path / "state.sqlite3"))
    out = after_run(PROFILES["hermes"], session_id="sess-h", task="index the repo",
                    outcome="ok", plan=["bb reviewgraph index", "bb reviewgraph risks"])
    assert out["persistence"] == "on"
    assert out["skill_registered_version"] == 1
    with skills_store.JSpaceStateStore() as st:          # fresh instance, same file
        skills = st.list_skills(source="hermes")
        assert len(skills) == 1 and skills[0]["name"].startswith("routine-")
        logged = st.recent_tasks(5, session_id="sess-h")
        assert logged[0]["task"] == "index the repo" and logged[0]["outcome"] == "ok"
        assert logged[0]["eval_score"] is None           # no eval ran — stays NULL


def test_hermes_does_not_register_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("DOTTIE_STATE_DB", str(tmp_path / "state.sqlite3"))
    out = after_run(PROFILES["hermes"], session_id="s", task="t", outcome="failed",
                    plan=["bb x"])
    assert "skill_registered_version" not in out
    with skills_store.JSpaceStateStore() as st:
        assert st.list_skills(source="hermes") == []


def test_openclaw_after_run_updates_context_across_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("DOTTIE_STATE_DB", str(tmp_path / "state.sqlite3"))
    after_run(PROFILES["openclaw"], session_id="s2", task="step one", outcome="ok")
    after_run(PROFILES["openclaw"], session_id="s2", task="step two", outcome="planned")
    with skills_store.JSpaceStateStore() as st:
        assert st.get_context("s2", "last_task") == "step two"
        assert st.get_context("s2", "last_outcome") == "planned"
        assert len(st.recent_tasks(10, session_id="s2")) == 2
