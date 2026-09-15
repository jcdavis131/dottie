"""Stage 2: correctness-gated code-optimization lane."""

from __future__ import annotations

import json

import pytest

from dottie_loop import errors, opt_lane
from dottie_loop.cli import EXIT_INVALID, EXIT_OK, main
from dottie_loop.schema import active


class SeqClock:
    def __init__(self, values: list[float]) -> None:
        self.values = list(values)
        self.i = 0

    def __call__(self) -> float:
        v = self.values[self.i]
        self.i += 1
        return v


def _sandbox() -> opt_lane.SandboxProvenance:
    return opt_lane.SandboxProvenance(
        kind="recorded",
        python="3.11.0",
        platform="linux",
        hostname_hash="abcd1234abcd1234",
        env_names=["DOTTIE_LOOP"],
        extra={"image": "none"},
    )


def _timing(samples: list[float] | None = None) -> dict:
    return opt_lane.calibrate_timing(samples or [0.4, 0.5, 0.6, 0.5], warmup_n=2)


def test_rejects_one_shot_wall_clock():
    with pytest.raises(errors.InvalidInputError, match="one-shot"):
        opt_lane.calibrate_timing([0.1], warmup_n=2)
    with pytest.raises(errors.InvalidInputError, match="one-shot"):
        opt_lane.calibrate_timing([0.1, 0.2, 0.3], warmup_n=0)
    with pytest.raises(errors.InvalidInputError, match="one-shot"):
        opt_lane.run_calibrated(lambda: None, warmup=0, repeats=3)
    with pytest.raises(errors.InvalidInputError, match="one-shot"):
        opt_lane.run_calibrated(lambda: None, warmup=1, repeats=1)


def test_calibrated_median_and_quantile_are_robust():
    samples = [10.0, 0.4, 0.5, 0.45]  # outlier does not become the report
    med = opt_lane.calibrate_timing(samples, warmup_n=1, statistic="median")
    assert med["value_s"] == opt_lane.median(samples)
    assert med["warmup_discarded"] and med["measured_n"] == 4
    q = opt_lane.calibrate_timing(samples, warmup_n=1, statistic="quantile", q=0.5)
    assert q["value_s"] == med["value_s"]
    clock = SeqClock([0.0, 1.0, 1.0, 2.5, 2.5, 4.0, 4.0, 6.0])
    live = opt_lane.run_calibrated(lambda: None, warmup=1, repeats=3, clock=clock)
    assert live == [1.5, 1.5, 2.0]
    assert opt_lane.median(live) == 1.5


def test_speed_zeroed_when_correctness_fails():
    timing = _timing()
    ok = opt_lane.build_report(
        task_ok=True, timing=timing, sandbox=_sandbox(), baseline_s=[1.0, 0.9, 0.8, 0.2]
    )
    bad = opt_lane.build_report(
        task_ok=False, timing=timing, sandbox=_sandbox(), baseline_s=[1.0, 0.9, 0.8, 0.2]
    )
    assert ok["schema"] == active("opt-lane-report")
    assert ok["correctness"] == 1.0 and ok["speed_rejected"] is False
    assert ok["speed_credit"] == ok["speed_percentile"] == ok["factory"]["speed_credit"]
    assert ok["speed_credit"] > 0
    assert bad["correctness"] == 0.0 and bad["speed_rejected"] is True
    assert bad["speed_credit"] == 0.0 and bad["factory"]["speed_credit"] == 0.0
    assert "correctness failed" in bad["reason"]
    # the same (fast) timing cannot earn speed credit after a fail
    assert bad["timing"]["value_s"] == ok["timing"]["value_s"]
    assert opt_lane.factory_pass(bad)["outcome"] == "fail"
    assert opt_lane.factory_pass(ok, speed_threshold=0.0)["outcome"] == "pass"
    missing_speed = dict(ok, speed_credit=None)
    missing_speed["task_ok"] = True
    missing_speed["correctness"] = 1.0
    assert opt_lane.factory_pass(missing_speed)["outcome"] == "no_metric"


def test_sandbox_provenance_does_not_dump_env_values(monkeypatch):
    monkeypatch.setenv("DOTTIE_SECRET", "must-not-appear")
    monkeypatch.setenv("DOTTIE_LOOP", "1")
    sb = opt_lane.capture_sandbox("local")
    d = sb.to_dict()
    blob = json.dumps(d)
    assert "must-not-appear" not in blob
    assert "DOTTIE_LOOP" in d["env_names"]
    assert d["hostname_hash"] and d["env_names_digest"]
    with pytest.raises(errors.InvalidInputError):
        opt_lane.SandboxProvenance("cloud", "3", "x", "h", [])


def test_opt_lane_cli(tmp_path, capsys):
    payload = {
        "task_ok": False,
        "warmup_n": 2,
        "samples_s": [0.1, 0.1, 0.1],
        "baseline_s": [1.0, 1.0, 1.0],
        "sandbox": _sandbox().to_dict(),
    }
    p = tmp_path / "t.json"
    p.write_text(json.dumps(payload))
    rc = main(["research", "opt-lane", "--file", str(p)])
    out = json.loads(capsys.readouterr().out)
    assert rc == EXIT_OK
    assert out["data"]["speed_credit"] == 0.0
    assert out["data"]["factory_gate"]["outcome"] == "fail"
    p.write_text(json.dumps({**payload, "samples_s": [0.1]}))
    rc = main(["research", "opt-lane", "--file", str(p)])
    assert rc == EXIT_INVALID
