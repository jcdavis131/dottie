"""Tests for dottie_rlm.harness — H = (rho, G, K, M) + refinement ledger.

SPEC floor covered: rho immutable (edit attempt rejected); refine writes a
ledger entry; rollback reverses and is idempotent; effective_prompt contains
an added skill; anti-vacuity (ledger file NON-EMPTY after refine); corrupt
ledger preserved loudly; missing ledger is empty. No network, no backend.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# dottie_rlm may still be a bare namespace dir while other waves land their
# files; make the package importable regardless of pytest's rootdir handling.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dottie_rlm.harness import (
    DEFAULT_RHO,
    Harness,
    HarnessError,
    LedgerCorruptError,
    Refinement,
    RefinementOrderError,
    RhoImmutableError,
    UnknownRefinementError,
)

RHO = "RHO-TEST-PROMPT v1: one kernel, everything is a function call inside it.\n"

SKILL_EDIT = {
    "target": "skills",
    "op": "add",
    "name": "retry-timeouts",
    "content": "Retry a timed-out kernel call once with backoff.\n\nDetails here.\n",
}


@pytest.fixture()
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path / "harness", base_prompt=RHO)


# ---------------------------------------------------------------------------
# rho: storage, hash, immutability
# ---------------------------------------------------------------------------


def test_layout_created_and_hash_recorded(harness: Harness) -> None:
    assert harness.rho == RHO
    assert harness.rho_path.read_text(encoding="utf-8") == RHO
    recorded = harness.rho_hash_path.read_text(encoding="utf-8").strip()
    assert recorded == harness.rho_hash
    assert len(recorded) == 64  # sha256 hex
    assert harness.skills_dir.is_dir()
    assert harness.memory_dir.is_dir()


def test_default_rho_used_when_none_given(tmp_path: Path) -> None:
    h = Harness(tmp_path / "h")
    assert h.rho == DEFAULT_RHO
    # Reload without an argument keeps the stored rho.
    assert Harness(tmp_path / "h").rho == DEFAULT_RHO


def test_reinit_with_same_prompt_ok_but_different_rejected(tmp_path: Path) -> None:
    root = tmp_path / "harness"
    Harness(root, base_prompt=RHO)
    assert Harness(root, base_prompt=RHO).rho == RHO  # same text is fine
    assert Harness(root).rho == RHO  # None is fine
    with pytest.raises(RhoImmutableError, match="immutable"):
        Harness(root, base_prompt="a different prompt\n")


def test_rho_tamper_detected_on_reload(tmp_path: Path) -> None:
    root = tmp_path / "harness"
    Harness(root, base_prompt=RHO)
    (root / "base_prompt.md").write_text("HACKED\n", encoding="utf-8")
    with pytest.raises(RhoImmutableError, match="hash"):
        Harness(root)


def test_refine_targeting_rho_rejected_and_no_ledger_entry(harness: Harness) -> None:
    for alias in ("rho", "base_prompt", "prompt"):
        with pytest.raises(RhoImmutableError, match="IMMUTABLE"):
            harness.refine(
                "tail", "sneaky", edit={"target": alias, "op": "update", "name": "x", "content": "HACK"}
            )
    assert harness.rho_path.read_text(encoding="utf-8") == RHO  # untouched
    assert harness.ledger() == []  # rejected edits append NOTHING
    assert not harness.ledger_path.exists()


# ---------------------------------------------------------------------------
# refine: apply + ledger
# ---------------------------------------------------------------------------


def test_refine_add_skill_applies_and_ledgers(harness: Harness) -> None:
    ref = harness.refine("...exec: TimeoutError...", "kernel timeouts flaking", edit=SKILL_EDIT)
    assert isinstance(ref, Refinement)
    assert ref.id == "r-1"
    assert ref.outcome is None
    assert ref.rolled_back is False
    assert (harness.skills_dir / "retry-timeouts.md").read_text(encoding="utf-8") == SKILL_EDIT["content"]
    entries = harness.ledger()
    assert len(entries) == 1
    e = entries[0]
    assert e["id"] == "r-1"
    assert e["trigger"] == "kernel timeouts flaking"
    assert e["edit"]["target"] == "skills"
    assert e["edit"]["op"] == "add"
    assert e["edit"]["name"] == "retry-timeouts"
    assert e["rolled_back"] is False


def test_refinement_ids_increment(harness: Harness) -> None:
    r1 = harness.refine("t", "first", edit=SKILL_EDIT)
    r2 = harness.refine(
        "t", "second", edit={"target": "memory", "op": "add", "name": "n1", "content": "note\n"}
    )
    assert (r1.id, r2.id) == ("r-1", "r-2")


def test_anti_vacuity_ledger_nonempty_after_refine(harness: Harness) -> None:
    harness.refine("tail text", "trigger text", edit=SKILL_EDIT)
    # The file itself is NON-EMPTY — a ceiling on nothing is satisfied by nothing.
    assert harness.ledger_path.exists()
    assert harness.ledger_path.stat().st_size > 0
    lines = [
        ln
        for ln in harness.ledger_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(lines) >= 1
    assert json.loads(lines[0])["id"] == "r-1"
    assert len(harness.ledger()) >= 1


def test_default_refine_derives_smallest_memory_note(harness: Harness) -> None:
    ref = harness.refine("exec 3 failed: ScopeError", "scope errors on messaging")
    assert ref.edit["target"] == "memory"
    assert ref.edit["op"] == "add"
    notes = harness.memory()
    assert ref.edit["name"] in notes
    assert "ScopeError" in notes[ref.edit["name"]]
    assert "scope errors on messaging" in harness.effective_prompt()
    # Same trigger again: updates the same note (still the smallest edit).
    ref2 = harness.refine("another tail", "scope errors on messaging")
    assert ref2.edit["op"] == "update"
    assert ref2.edit["name"] == ref.edit["name"]
    assert len(harness.memory()) == 1


# ---------------------------------------------------------------------------
# effective_prompt: rebuilt, never mutated
# ---------------------------------------------------------------------------


def test_effective_prompt_contains_added_skill_and_rho(harness: Harness) -> None:
    harness.refine("tail", "trigger", edit=SKILL_EDIT)
    p = harness.effective_prompt()
    assert RHO.strip() in p
    assert "retry-timeouts" in p
    assert "Retry a timed-out kernel call once with backoff." in p  # description line
    assert harness.rho_path.read_text(encoding="utf-8") == RHO  # rho file untouched


def test_effective_prompt_is_rebuilt_each_call(harness: Harness) -> None:
    before = harness.effective_prompt()
    assert before == harness.effective_prompt()  # stable when state is stable
    ref = harness.refine("tail", "trigger", edit=SKILL_EDIT)
    after = harness.effective_prompt()
    assert after != before
    assert "retry-timeouts" in after
    harness.rollback(ref.id)
    assert harness.effective_prompt() == before  # rebuilt from disk, not mutated
    assert harness.rho == RHO


# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------


def test_record_outcome_folds_into_ledger(harness: Harness) -> None:
    ref = harness.refine("tail", "trigger", edit=SKILL_EDIT)
    harness.record_outcome(ref.id, "helped: retries stopped the flake")
    entries = harness.ledger()
    assert entries[0]["outcome"] == "helped: retries stopped the flake"
    assert entries[0]["rolled_back"] is False


def test_record_outcome_unknown_id_raises(harness: Harness) -> None:
    with pytest.raises(UnknownRefinementError, match="r-99"):
        harness.record_outcome("r-99", "whatever")


# ---------------------------------------------------------------------------
# rollback: reverses, idempotent
# ---------------------------------------------------------------------------


def test_rollback_add_reverses_skill(harness: Harness) -> None:
    ref = harness.refine("tail", "trigger", edit=SKILL_EDIT)
    assert (harness.skills_dir / "retry-timeouts.md").exists()
    result = harness.rollback(ref.id)
    assert result["rolled_back"] is True
    assert result["no_op"] is False
    assert not (harness.skills_dir / "retry-timeouts.md").exists()
    assert harness.ledger()[0]["rolled_back"] is True
    assert "retry-timeouts" not in harness.effective_prompt()


def test_rollback_is_idempotent_no_op(harness: Harness) -> None:
    ref = harness.refine("tail", "trigger", edit=SKILL_EDIT)
    harness.rollback(ref.id)
    raw_lines_after_first = harness.ledger_path.read_text(encoding="utf-8").splitlines()
    second = harness.rollback(ref.id)
    assert second["no_op"] is True
    assert "no-op" in second["message"]
    # No extra marker appended; nothing reversed twice.
    assert (
        harness.ledger_path.read_text(encoding="utf-8").splitlines()
        == raw_lines_after_first
    )
    assert harness.ledger()[0]["rolled_back"] is True


def test_rollback_update_restores_previous_content(harness: Harness) -> None:
    harness.refine(
        "t", "seed", edit={"target": "memory", "op": "add", "name": "ops", "content": "v1 content\n"}
    )
    ref2 = harness.refine(
        "t", "revise", edit={"target": "memory", "op": "update", "name": "ops", "content": "v2 content\n"}
    )
    assert harness.memory()["ops"] == "v2 content\n"
    harness.rollback(ref2.id)
    assert harness.memory()["ops"] == "v1 content\n"
    entries = {e["id"]: e for e in harness.ledger()}
    assert entries[ref2.id]["rolled_back"] is True
    assert entries["r-1"]["rolled_back"] is False


def test_rollback_remove_restores_file(harness: Harness) -> None:
    harness.refine("t", "seed", edit=SKILL_EDIT)
    ref2 = harness.refine(
        "t", "drop it", edit={"target": "skills", "op": "remove", "name": "retry-timeouts", "content": None}
    )
    assert not (harness.skills_dir / "retry-timeouts.md").exists()
    harness.rollback(ref2.id)
    assert (harness.skills_dir / "retry-timeouts.md").read_text(encoding="utf-8") == SKILL_EDIT["content"]


def test_rollback_unknown_id_raises(harness: Harness) -> None:
    with pytest.raises(UnknownRefinementError, match="r-7"):
        harness.rollback("r-7")


# ---------------------------------------------------------------------------
# G: agents target
# ---------------------------------------------------------------------------


def test_agents_target_add_and_rollback(harness: Harness) -> None:
    assert harness.agents() == {}  # missing file is empty, not an error
    ref = harness.refine(
        "t", "subs need a default", edit={"target": "agents", "op": "add", "name": "sub", "content": "ollama:qwen3:8b"}
    )
    assert harness.agents() == {"sub": "ollama:qwen3:8b"}
    assert harness.model_for("sub") == "ollama:qwen3:8b"
    assert harness.agents_path.exists()
    harness.rollback(ref.id)
    assert harness.agents() == {}
    assert harness.model_for("sub") is None


def test_agents_update_rollback_restores_previous_spec(harness: Harness) -> None:
    harness.refine(
        "t", "seed", edit={"target": "agents", "op": "add", "name": "sub", "content": "ollama:qwen3:8b"}
    )
    ref2 = harness.refine(
        "t", "try bigger", edit={"target": "agents", "op": "update", "name": "sub", "content": "ollama:qwen3:14b"}
    )
    assert harness.model_for("sub") == "ollama:qwen3:14b"
    harness.rollback(ref2.id)
    assert harness.model_for("sub") == "ollama:qwen3:8b"


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_invalid_edits_rejected(harness: Harness) -> None:
    with pytest.raises(ValueError, match="target"):
        harness.refine("t", "x", edit={"target": "nonsense", "op": "add", "name": "a", "content": "c"})
    with pytest.raises(ValueError, match="op"):
        harness.refine("t", "x", edit={"target": "skills", "op": "destroy", "name": "a", "content": "c"})
    with pytest.raises(ValueError, match="name"):
        harness.refine("t", "x", edit={"target": "skills", "op": "add", "name": "..\\evil", "content": "c"})
    with pytest.raises(ValueError, match="name"):
        harness.refine("t", "x", edit={"target": "skills", "op": "add", "name": "a/b", "content": "c"})
    with pytest.raises(ValueError, match="content"):
        harness.refine("t", "x", edit={"target": "skills", "op": "add", "name": "a", "content": None})
    with pytest.raises(ValueError, match="does not exist"):
        harness.refine("t", "x", edit={"target": "skills", "op": "update", "name": "ghost", "content": "c"})
    with pytest.raises(ValueError, match="does not exist"):
        harness.refine("t", "x", edit={"target": "memory", "op": "remove", "name": "ghost", "content": None})
    harness.refine("t", "seed", edit=SKILL_EDIT)
    with pytest.raises(ValueError, match="already exists"):
        harness.refine("t", "x", edit=SKILL_EDIT)
    # Failed validations appended nothing beyond the one good refine.
    assert [e["id"] for e in harness.ledger()] == ["r-1"]


# ---------------------------------------------------------------------------
# no fail-silent reads
# ---------------------------------------------------------------------------


def test_missing_ledger_reads_empty(harness: Harness) -> None:
    assert harness.ledger() == []  # missing is empty ...


def test_corrupt_ledger_preserved_loudly(harness: Harness, capsys: pytest.CaptureFixture) -> None:
    harness.refine("t", "seed", edit=SKILL_EDIT)
    with harness.ledger_path.open("a", encoding="utf-8") as fh:
        fh.write("{this is not json\n")
    with pytest.raises(LedgerCorruptError, match="preserved"):
        harness.ledger()
    err = capsys.readouterr().err
    assert "CORRUPT" in err
    preserved = list(harness.root.glob("refinements.jsonl.corrupt-*"))
    assert len(preserved) == 1
    assert "{this is not json" in preserved[0].read_text(encoding="utf-8")
    # ... and refine on a corrupt ledger must also refuse, not overwrite.
    with pytest.raises(LedgerCorruptError):
        harness.refine("t", "again", edit={"target": "memory", "op": "add", "name": "n", "content": "c"})


def test_corrupt_agents_json_preserved_loudly(harness: Harness, capsys: pytest.CaptureFixture) -> None:
    harness.agents_path.write_text("[not, an, object", encoding="utf-8")
    with pytest.raises(HarnessError, match="corrupt"):
        harness.agents()
    assert "CORRUPT" in capsys.readouterr().err
    assert list(harness.root.glob("agents.json.corrupt-*"))


# ---------------------------------------------------------------------------
# hygiene
# ---------------------------------------------------------------------------


def test_no_stray_tmp_files(harness: Harness) -> None:
    ref = harness.refine("t", "seed", edit=SKILL_EDIT)
    harness.record_outcome(ref.id, "fine")
    harness.rollback(ref.id)
    harness.refine("t2", "derived note")
    assert list(harness.root.rglob("*.tmp")) == []


class TestOutOfOrderRollbackIsRefused:
    """Reversing an OLDER refinement on top of a newer one destroys the newer.

    Reproduced by review (harness.py:615): r-1 adds skills/foo "A", r-2 updates
    it to "B", rollback('r-1') saw op="add", unlinked foo.md, and took B with
    it. Rollback is now refused out of order, naming what must go first.
    """

    def _h(self, tmp_path):
        return Harness(tmp_path / "harness")

    def test_older_rollback_is_refused_while_a_newer_edit_lives(self, tmp_path) -> None:
        h = self._h(tmp_path)
        r1 = h.refine("t", "add foo", edit={
            "target": "skills", "op": "add", "name": "foo", "content": "A"})
        r2 = h.refine("t", "update foo", edit={
            "target": "skills", "op": "update", "name": "foo", "content": "B"})
        with pytest.raises(RefinementOrderError) as ei:
            h.rollback(r1.id)
        assert r2.id in str(ei.value)
        # The newer content survived the refusal.
        assert "B" in (tmp_path / "harness" / "skills" / "foo.md").read_text(
            encoding="utf-8"
        )

    def test_reverse_order_rollback_works(self, tmp_path) -> None:
        h = self._h(tmp_path)
        r1 = h.refine("t", "add foo", edit={
            "target": "skills", "op": "add", "name": "foo", "content": "A"})
        r2 = h.refine("t", "update foo", edit={
            "target": "skills", "op": "update", "name": "foo", "content": "B"})
        h.rollback(r2.id)  # newest first
        assert "A" in (tmp_path / "harness" / "skills" / "foo.md").read_text(
            encoding="utf-8"
        )
        h.rollback(r1.id)  # now the older one is unblocked
        assert not (tmp_path / "harness" / "skills" / "foo.md").exists()

    def test_a_different_target_does_not_block(self, tmp_path) -> None:
        """Only the SAME target blocks — an unrelated newer edit must not."""
        h = self._h(tmp_path)
        r1 = h.refine("t", "add foo", edit={
            "target": "skills", "op": "add", "name": "foo", "content": "A"})
        h.refine("t", "add bar", edit={
            "target": "skills", "op": "add", "name": "bar", "content": "Z"})
        h.rollback(r1.id)  # must not raise
        assert not (tmp_path / "harness" / "skills" / "foo.md").exists()
        assert (tmp_path / "harness" / "skills" / "bar.md").exists()

    def test_a_rolled_back_newer_edit_does_not_block(self, tmp_path) -> None:
        h = self._h(tmp_path)
        r1 = h.refine("t", "add foo", edit={
            "target": "skills", "op": "add", "name": "foo", "content": "A"})
        r2 = h.refine("t", "update foo", edit={
            "target": "skills", "op": "update", "name": "foo", "content": "B"})
        h.rollback(r2.id)
        h.rollback(r1.id)  # r2 no longer applies, so r1 is free
        assert not (tmp_path / "harness" / "skills" / "foo.md").exists()
