"""Unit tests for dashboard status helpers (no Docker / no live DB)."""

from __future__ import annotations

from ava.pipeline_status import _SERIES_FIELDS, current_run_series, full_run_series


def test_current_run_series_drops_pre_restart_history():
    metrics = [
        {"event": "step", "step": 450, "lm": 0.12, "tok_s": 12000, "phase": 0},
        {"event": "step", "step": 460, "lm": 0.11, "tok_s": 12100, "phase": 0},
        {"event": "step", "step": 470, "lm": 0.10, "tok_s": 12000, "phase": 0},
        # CUDA restart — step resets
        {"event": "step", "step": 1, "lm": 10.5, "tok_s": None, "phase": 0},
        {"event": "step", "step": 10, "lm": 8.0, "tok_s": 11000, "phase": 0},
        {"event": "step", "step": 100, "lm": 0.30, "tok_s": 11200, "phase": 0},
    ]
    series = current_run_series(metrics)
    assert series["step"] == [1, 10, 100]
    assert series["lm_loss"][0] == 10.5
    assert series["lm_loss"][-1] == 0.30
    assert len(series["tok_s"]) == 3


def test_current_run_series_empty():
    assert current_run_series([]) == {
        "step": [],
        "lm_loss": [],
        "phase": [],
        "total": [],
        **{k: [] for k in _SERIES_FIELDS},
    }


def test_current_run_series_carries_aux_loss_and_optimizer_fields():
    metrics = [
        {
            "event": "step",
            "step": 1,
            "lm": 9.0,
            "total": 9.4,
            "phase": 0,
            "grad_norm": 0.8,
            "lr": 1e-4,
            "report": 0.2,
            "broadcast": 0.1,
            "selectivity": 0.05,
            "modulation": 0.03,
            "half_life": 0.02,
            "inter_mi": 0.01,
            "routing": 0.09,
            "verbalizable_mass": 0.06,
            "broadcast_strength": 0.2,
        },
    ]
    series = current_run_series(metrics)
    assert series["grad_norm"] == [0.8]
    assert series["lr"] == [1e-4]
    assert series["routing"] == [0.09]
    assert series["verbalizable_mass"] == [0.06]


def test_every_series_is_index_aligned_with_step():
    """All series must be EXACTLY as long as `step`, including sparse fields.

    The dashboard chart pairs x and y BY INDEX, and it slices them independently:
    webapp/js/views/ops.js takes `series.step.slice(-120)` and `series[key].slice(-120)`
    as separate expressions. If a sparse field were compacted instead of padded with None,
    the two windows would begin at different rows and every point would be plotted against
    the WRONG STEP -- a chart that is confidently, silently mislabelled rather than empty
    or broken.

    current_run_series gets this right by construction (`row.get(k)` appends None for a
    missing key), so this test does not fix anything. It pins the property the chart
    depends on, which was previously only implied -- and only for tok_s, in one case
    (TODOS 5.3.R82).
    """
    metrics = [
        # Deliberately ragged: tok_s missing on the 1st and 3rd rows, grad_norm only on
        # the 2nd, lr only on the last. This is the shape that breaks index pairing if
        # anything ever "helpfully" drops the empties.
        {"event": "step", "step": 1, "lm": 9.0, "phase": 0},
        {"event": "step", "step": 2, "lm": 8.0, "tok_s": 100, "grad_norm": 0.5, "phase": 0},
        {"event": "step", "step": 3, "lm": 7.0, "phase": 0},
        {"event": "step", "step": 4, "lm": 6.0, "tok_s": 120, "lr": 1e-4, "phase": 0},
    ]
    series = current_run_series(metrics)
    n = len(series["step"])
    assert n == 4
    ragged = {k: len(v) for k, v in series.items() if len(v) != n}
    assert not ragged, (
        f"these series are not index-aligned with step (len {n}): {ragged}. "
        "The dashboard pairs x/y by index after slicing each independently, so a shorter "
        "array silently shifts every point onto the wrong step."
    )
    # The padding must be None, not a fabricated 0 -- a gap is a gap, and chart.js drops
    # non-finite pairs on purpose. A 0 here would render as a real measured trough.
    assert series["tok_s"] == [None, 100, None, 120]
    assert series["grad_norm"] == [None, 0.5, None, None]


def test_current_run_series_ignores_non_step_events():
    metrics = [
        {"event": "model_built", "preset": "mini"},
        {"event": "step", "step": 1, "lm": 9.0, "phase": 0},
        {"event": "checkpoint", "step": 100, "path": "/ckpt/step_100.pt"},
        {"event": "step", "step": 100, "lm": 0.3, "tok_s": 10000, "phase": 0},
    ]
    series = current_run_series(metrics)
    assert series["step"] == [1, 100]


def test_full_run_series_keeps_pre_restart_history_and_flags_restarts():
    """Unlike current_run_series, full_run_series must NOT drop the segment
    before a restart — that's the whole point of the "loss landscape doesn't
    show the full timeline" fix. cum_step keeps counting up across the
    restart instead of jumping backward (raw step resets to 1), so a chart
    plotting cum_step never has to draw a line that jumps backward."""
    metrics = [
        {"event": "step", "step": 450, "lm": 0.12, "ts": 100.0, "phase": 0},
        {"event": "step", "step": 460, "lm": 0.11, "ts": 110.0, "phase": 0},
        # CUDA restart — step resets
        {"event": "step", "step": 1, "lm": 10.5, "ts": 200.0, "phase": 0},
        {"event": "step", "step": 10, "lm": 8.0, "ts": 210.0, "phase": 0},
    ]
    result = full_run_series(metrics)
    assert result["series"]["step"] == [450, 460, 1, 10]
    assert result["series"]["ts"] == [100.0, 110.0, 200.0, 210.0]
    assert result["series"]["cum_step"] == [450, 460, 461, 470]
    assert result["series"]["cum_step"] == sorted(result["series"]["cum_step"]), (
        "cum_step must be non-decreasing"
    )
    assert result["restarts"] == [{"cum_step": 461, "ts": 200.0}]


def test_full_run_series_empty():
    result = full_run_series([])
    assert result["series"]["step"] == []
    assert result["series"]["cum_step"] == []
    assert result["series"]["ts"] == []
    assert result["restarts"] == []


def test_full_run_series_downsamples_but_keeps_latest_point():
    metrics = [
        {"event": "step", "step": i, "lm": 1.0, "ts": float(i)} for i in range(1, 2001)
    ]
    result = full_run_series(metrics)
    n = len(result["series"]["step"])
    assert n <= 610, (
        f"expected downsampling to roughly _FULL_SERIES_MAX_POINTS, got {n}"
    )
    assert result["series"]["step"][-1] == 2000, (
        "must always keep the most recent point"
    )
