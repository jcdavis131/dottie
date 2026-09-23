"""Two-arm experiment evidence (research learning, JustVugg/colibri)."""

from __future__ import annotations

import pytest

from dottie_loop import errors
from dottie_loop.manifest import ExperimentArm, ExperimentManifest, order_kind


def _arm(samples, *, passed=True, config=None, commit="a" * 40, dirty=False):
    return ExperimentArm(
        commit=commit,
        config=config if config is not None else {"x": 1},
        raw_samples=tuple(samples),
        quality_method="oracle",
        quality_passed=passed,
        evidence_uri="file:///e",
        evidence_sha256="b" * 64,
        dirty_tree=dirty,
    )


INTERLEAVED = ("baseline", "trial") * 4


def test_arm_rejects_short_commit_and_non_hex_and_dirty_tree():
    with pytest.raises(errors.InvalidInputError, match="commit"):
        _arm([1.0, 1.1, 1.2], commit="short")
    with pytest.raises(errors.InvalidInputError, match="hexadecimal"):
        _arm([1.0, 1.1, 1.2], commit="z" * 40)
    with pytest.raises(errors.InvalidInputError, match="dirty"):
        _arm([1.0, 1.1, 1.2], dirty=True)


def test_arm_rejects_fewer_than_three_samples_and_non_positive_or_bool():
    with pytest.raises(errors.InvalidInputError, match="raw_samples"):
        _arm([1.0, 1.1])
    with pytest.raises(errors.InvalidInputError, match="finite and positive"):
        _arm([1.0, 1.1, 0.0])
    with pytest.raises(errors.InvalidInputError, match="finite and positive"):
        _arm([1.0, 1.1, -1.0])
    with pytest.raises(errors.InvalidInputError, match="numbers"):
        _arm([1.0, 1.1, True])
    with pytest.raises(errors.InvalidInputError, match="finite and positive"):
        _arm([1.0, 1.1, float("nan")])


def test_arm_rejects_short_evidence_hash_and_empty_method():
    good = _arm([1.0, 1.1, 1.2]).__class__
    with pytest.raises(errors.InvalidInputError, match="evidence_sha256"):
        good(
            commit="a" * 40, config={}, raw_samples=(1.0, 1.1, 1.2),
            quality_method="oracle", quality_passed=True,
            evidence_uri="u", evidence_sha256="short",
        )
    with pytest.raises(errors.InvalidInputError, match="quality_method"):
        good(
            commit="a" * 40, config={}, raw_samples=(1.0, 1.1, 1.2),
            quality_method="", quality_passed=True,
            evidence_uri="u", evidence_sha256="b" * 64,
        )


def test_arm_median_and_n_are_computed_never_stored():
    a = _arm([3.0, 1.0, 2.0])
    assert a.n == 3
    assert a.median == 2.0
    assert "median" not in a.__dataclass_fields__


def test_manifest_rejects_a_failed_baseline_but_admits_a_failed_trial():
    baseline_fail = _arm([1.0, 1.1, 1.2], passed=False)
    trial_ok = _arm([0.9, 1.0, 1.1], config={"x": 2})
    with pytest.raises(errors.InvalidInputError, match="baseline"):
        ExperimentManifest(hypothesis="h", baseline=baseline_fail, trial=trial_ok)

    baseline_ok = _arm([1.0, 1.1, 1.2])
    trial_fail = _arm([0.9, 1.0, 1.1], config={"x": 2}, passed=False)
    m = ExperimentManifest(hypothesis="h", baseline=baseline_ok, trial=trial_fail)
    assert m.quality_ok is False
    assert m.gate_eligible is False  # correctness first, mechanically


def test_changed_variables_is_computed_never_declared():
    baseline = _arm([1.0, 1.1, 1.2], config={"x": 1, "y": "same"})
    trial = _arm([0.9, 1.0, 1.1], config={"x": 2, "y": "same"})
    m = ExperimentManifest(hypothesis="h", baseline=baseline, trial=trial)
    assert m.changed_variables == ("x",)
    assert not hasattr(m, "changed_variables_declared")
    # a key present on only one side counts as changed too
    baseline2 = _arm([1.0, 1.1, 1.2], config={"x": 1})
    trial2 = _arm([0.9, 1.0, 1.1], config={"x": 1, "extra": True})
    m2 = ExperimentManifest(hypothesis="h", baseline=baseline2, trial=trial2)
    assert m2.changed_variables == ("extra",)


def test_median_is_recomputed_not_trusted_even_if_a_caller_tries_to_pass_one():
    baseline = _arm([1.0, 1.1, 1.2])
    trial = _arm([0.9, 1.0, 1.1], config={"x": 2})
    m = ExperimentManifest(hypothesis="h", baseline=baseline, trial=trial)
    assert m.baseline.median == 1.1
    # no constructor parameter exists to inject a false median
    with pytest.raises(TypeError):
        ExperimentManifest(hypothesis="h", baseline=baseline, trial=trial, median=999)  # type: ignore[call-arg]


def test_order_kind_classifies_interleaved_blocked_and_not_recorded():
    assert order_kind(()) == "not_recorded"
    assert order_kind(("baseline", "trial", "baseline", "trial")) == "interleaved"
    assert order_kind(("baseline", "trial", "trial", "baseline")) == "interleaved"  # ABBA
    assert order_kind(("baseline", "baseline", "baseline", "trial", "trial", "trial")) == "blocked"


def test_run_order_must_match_arm_sample_counts_and_names():
    baseline = _arm([1.0, 1.1, 1.2])
    trial = _arm([0.9, 1.0, 1.1], config={"x": 2})
    with pytest.raises(errors.InvalidInputError, match="run_order"):
        ExperimentManifest(
            hypothesis="h", baseline=baseline, trial=trial,
            run_order=("baseline", "trial"),  # only 2, arms have 3 each
        )
    with pytest.raises(errors.InvalidInputError, match="run_order"):
        ExperimentManifest(
            hypothesis="h", baseline=baseline, trial=trial,
            run_order=("baseline",) * 3 + ("nope",) * 3,
        )


def test_blocked_or_unrecorded_order_is_filed_but_never_gate_eligible():
    baseline = _arm([1.0, 1.1, 1.2])
    trial = _arm([0.5, 0.6, 0.55], config={"x": 2})
    unrecorded = ExperimentManifest(hypothesis="h", baseline=baseline, trial=trial)
    assert unrecorded.order_kind == "not_recorded"
    assert unrecorded.gate_eligible is False  # filed (no raise), just ineligible
    assert unrecorded.direction == "trial_better"  # direction is still visible

    blocked = ExperimentManifest(
        hypothesis="h", baseline=baseline, trial=trial,
        run_order=("baseline", "baseline", "baseline", "trial", "trial", "trial"),
    )
    assert blocked.order_kind == "blocked"
    assert blocked.gate_eligible is False


def test_interleaved_and_correct_arms_are_gate_eligible():
    baseline = _arm([1.0, 1.1, 0.95, 1.05])
    trial = _arm([0.5, 0.6, 0.45, 0.55], config={"x": 2})
    m = ExperimentManifest(hypothesis="h", baseline=baseline, trial=trial, run_order=INTERLEAVED)
    assert m.gate_eligible is True
    assert m.direction == "trial_better"


def test_pair_wins_none_when_not_pairable_never_a_fabricated_zero():
    baseline = _arm([1.0, 1.1, 1.2])
    trial = _arm([0.5, 0.6, 0.55], config={"x": 2})
    unrecorded = ExperimentManifest(hypothesis="h", baseline=baseline, trial=trial)
    assert unrecorded.pair_wins is None
    unequal_trial = _arm([0.5, 0.6, 0.55, 0.5], config={"x": 2})
    m = ExperimentManifest(
        hypothesis="h", baseline=baseline, trial=unequal_trial,
        run_order=("baseline", "trial") * 3 + ("trial",),
    )
    assert m.pair_wins is None  # unequal n even though interleaved


def test_pair_wins_counts_from_recorded_order():
    # pairwise (baseline, trial), lower_is_better: (1.0,0.9)->trial, (1.1,1.2)->baseline,
    # (0.95,0.90)->trial, (1.05,1.10)->baseline: trial wins 2, loses 2, no ties.
    baseline = _arm([1.0, 1.1, 0.95, 1.05])
    trial = _arm([0.9, 1.2, 0.90, 1.10], config={"x": 2})
    m = ExperimentManifest(hypothesis="h", baseline=baseline, trial=trial, run_order=INTERLEAVED)
    pw = m.pair_wins
    assert pw == {"wins": 2, "losses": 2, "ties": 0, "n_pairs": 4}


def test_higher_is_better_flips_direction_and_pair_wins():
    baseline = _arm([1.0, 1.1, 0.95, 1.05])
    trial = _arm([0.5, 0.6, 0.45, 0.55], config={"x": 2})
    m = ExperimentManifest(
        hypothesis="h", baseline=baseline, trial=trial,
        lower_is_better=False, run_order=INTERLEAVED,
    )
    assert m.direction == "baseline_better"
    assert m.pair_wins["wins"] == 0


def test_version_and_hypothesis_are_validated():
    baseline = _arm([1.0, 1.1, 1.2])
    trial = _arm([0.9, 1.0, 1.1], config={"x": 2})
    with pytest.raises(errors.InvalidInputError, match="hypothesis"):
        ExperimentManifest(hypothesis="  ", baseline=baseline, trial=trial)
    with pytest.raises(errors.InvalidInputError, match="version"):
        ExperimentManifest(hypothesis="h", baseline=baseline, trial=trial, version=2)


def test_to_dict_is_content_addressed_and_schema_stamped():
    baseline = _arm([1.0, 1.1, 1.2])
    trial = _arm([0.9, 1.0, 1.1], config={"x": 2})
    m = ExperimentManifest(hypothesis="h", baseline=baseline, trial=trial)
    body = m.to_dict()
    assert body["schema"] == "experiment-manifest-1.0.0"
    assert len(body["content_sha256"]) == 64
    # identical evidence (ignoring created_at/manifest_id) hashes identically
    m2 = ExperimentManifest(hypothesis="h", baseline=baseline, trial=trial)
    assert m2.to_dict()["content_sha256"] == body["content_sha256"]


def test_cli_research_manifest_round_trips(tmp_path, capsys):
    import json

    from dottie_loop.cli import EXIT_INVALID, EXIT_OK, main

    good = {
        "hypothesis": "x=2 is faster",
        "baseline": {
            "commit": "a" * 40, "config": {"x": 1}, "raw_samples": [1.0, 1.1, 0.95, 1.05],
            "quality": {"method": "oracle", "passed": True},
            "evidence": {"uri": "file:///a", "sha256": "b" * 64},
        },
        "trial": {
            "commit": "a" * 40, "config": {"x": 2}, "raw_samples": [0.5, 0.6, 0.45, 0.55],
            "quality": {"method": "oracle", "passed": True},
            "evidence": {"uri": "file:///b", "sha256": "c" * 64},
        },
        "run_order": ["baseline", "trial"] * 4,
    }
    f = tmp_path / "m.json"
    f.write_text(json.dumps(good))
    rc = main(["research", "manifest", "--file", str(f)])
    env = json.loads(capsys.readouterr().out.strip())
    assert rc == EXIT_OK and env["data"]["gate_eligible"] is True

    bad = dict(good)
    bad["baseline"] = dict(good["baseline"])
    bad["baseline"]["quality"] = {"method": "oracle", "passed": False}
    f2 = tmp_path / "m2.json"
    f2.write_text(json.dumps(bad))
    rc2 = main(["research", "manifest", "--file", str(f2)])
    env2 = json.loads(capsys.readouterr().out.strip())
    assert rc2 == EXIT_INVALID and "baseline" in json.dumps(env2)
