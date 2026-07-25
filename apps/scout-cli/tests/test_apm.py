"""APM — openswap #26 (New Relic APM -> stdlib perf_counter/contextvars span
recorder + sqlite span store + static waterfall/flame report). Pure-logic core
tests, the anti-fabrication invariant (a span has a duration OR a labelled
reason, never both, never neither), the aggregates, the store, capability
detection and the subprocess envelope.

Deterministic and offline by construction: every tracer under test gets an
INJECTED clock, so no assertion races a real one. The two tests that do use the
real clock are the ones whose whole point is that time.perf_counter can resolve
a sub-millisecond call that time.time would have reported as a fabricated 0.0 —
and they assert only "> 0", never a specific duration.
"""

from __future__ import annotations

import inspect
import itertools
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bigbang.core import apm, openswap

ROOT = Path(__file__).resolve().parents[1]

WALL = 1_700_000_000.0


@pytest.fixture(autouse=True)
def _clean_span_context():
    """Start every test with no span live in this context.

    Not a test smell — a real property of a ContextVar recorder: a test (or a
    daemon) that starts a span without ending it leaves it live, and everything
    afterwards parents onto the dead span. test_a_leaked_span_keeps_parenting
    documents that behaviour deliberately; every other test wants a clean slate.
    """
    apm.clear_context()
    yield
    apm.clear_context()


# ---- helpers ----------------------------------------------------------------


def _tracer(*, step: float = 0.001, ticks=None, service: str = "demo") -> apm.Tracer:
    """A tracer on a PINNED clock: `step` seconds per clock read, or a fixed list."""
    seq = iter(ticks) if ticks is not None else None
    counter = itertools.count(0.0, step)
    ids = (f"t{i}" for i in itertools.count(1))
    return apm.Tracer(
        service=service,
        clock=(lambda: next(seq)) if seq is not None else (lambda: next(counter)),
        wall=lambda: WALL,
        trace_id_factory=lambda: next(ids),
    )


def _span(
    name: str,
    *,
    trace_id: str = "t1",
    span_id: int = 1,
    parent_id: int | None = None,
    depth: int | None = None,
    offset: float = 0.0,
    duration: float | None = 1.0,
    status: str | None = None,
    error: str | None = None,
    service: str = "demo",
    attrs: dict | None = None,
    wall: float | None = WALL,
) -> dict:
    """A VALID span row (built through check_span, so fixtures cannot lie either)."""
    if status is None:
        status = apm.STATUS_OK if duration is not None else apm.STATUS_UNFINISHED
    if duration is None and error is None:
        error = apm.ABANDONED_REASON
    return apm.check_span(
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_id": parent_id,
            "name": name,
            "service": service,
            "depth": (0 if parent_id is None else 1) if depth is None else depth,
            "start_offset_ms": offset,
            "duration_ms": duration,
            "status": status,
            "error": error,
            "attrs": attrs or {},
            "wall_start": wall,
        }
    )


# ---- the clock (the whole reason this module exists) ------------------------


def test_default_clock_is_perf_counter_and_wall_time_is_refused():
    default = inspect.signature(apm.Tracer.__init__).parameters["clock"].default
    assert default is time.perf_counter  # monotonic, ns-resolution
    with pytest.raises(ValueError, match="monotonic"):
        apm.Tracer(clock=time.time)  # ~15.6ms granular on Windows -> fake zeros
    with pytest.raises(ValueError, match="callables"):
        apm.Tracer(clock=123)


def test_real_clock_measures_a_sub_millisecond_call_as_nonzero():
    # The anti-time.time proof: a few-hundred-microsecond call must NOT read 0.0.
    tracer = apm.Tracer(service="real")
    with tracer.span("work"):
        assert sum(range(200_000)) > 0
    span = tracer.spans()[0]
    assert span["status"] == "ok"
    assert span["duration_ms"] is not None and span["duration_ms"] > 0.0
    assert span["wall_start"] is not None  # wall clock still answers "when"


# ---- nesting via contextvars ------------------------------------------------


def test_spans_nest_via_contextvars_with_exact_offsets():
    tracer = _tracer()  # 1ms per clock read
    with tracer.span("root"):
        with tracer.span("child", table="spans"):
            pass
        with tracer.span("child"):
            pass
    rows = tracer.spans()
    assert [r["name"] for r in rows] == ["root", "child", "child"]
    assert [r["span_id"] for r in rows] == [1, 2, 3]
    assert [r["parent_id"] for r in rows] == [None, 1, 1]
    assert [r["depth"] for r in rows] == [0, 1, 1]
    assert {r["trace_id"] for r in rows} == {"t1"}  # one trace, one root
    # reads: root start 0, c1 start 1, c1 end 2, c2 start 3, c2 end 4, root end 5
    assert [r["start_offset_ms"] for r in rows] == [0.0, 1.0, 3.0]
    assert [r["duration_ms"] for r in rows] == [5.0, 1.0, 1.0]
    assert rows[1]["attrs"] == {"table": "spans"}
    assert all(r["wall_start"] == WALL for r in rows)  # stamped once per trace


def test_three_deep_nesting_and_context_restored_between_traces():
    tracer = _tracer()
    with tracer.span("a"), tracer.span("b"), tracer.span("c"):
        live = tracer.open_spans()
        assert [s["name"] for s in live] == ["a", "b", "c"]
        assert [s["depth"] for s in live] == [0, 1, 2]
    with tracer.span("second"):
        pass
    rows = {r["name"]: r for r in tracer.spans()}
    assert rows["c"]["parent_id"] == rows["b"]["span_id"]
    assert rows["b"]["parent_id"] == rows["a"]["span_id"]
    # the context was restored, so the next span is a NEW root in a NEW trace
    assert rows["second"]["parent_id"] is None and rows["second"]["depth"] == 0
    assert rows["second"]["trace_id"] != rows["a"]["trace_id"]
    assert tracer.open_spans() == []


def test_decorator_names_by_qualname_and_preserves_the_function():
    tracer = _tracer()

    @tracer.trace(kind="unit")
    def add(a, b):
        """docstring survives."""
        return a + b

    @tracer.trace("explicit.name")
    def named():
        return add(1, 2)  # nested call -> nested span

    assert named() == 3
    assert add.__doc__ == "docstring survives."  # functools.wraps
    rows = tracer.spans()
    assert rows[0]["name"] == "explicit.name"  # explicit label wins
    assert rows[1]["name"].endswith("<locals>.add")  # __qualname__ default
    assert rows[1]["parent_id"] == rows[0]["span_id"]
    assert rows[1]["attrs"] == {"kind": "unit"}


def test_start_rejects_an_empty_name():
    tracer = _tracer()
    for bad in ("", "   "):
        with pytest.raises(ValueError, match="non-empty"):
            tracer.start(bad)


# ---- failure paths ----------------------------------------------------------


def test_exception_is_recorded_reraised_and_unwinds_the_context():
    tracer = _tracer()
    with pytest.raises(RuntimeError, match="boom"), tracer.span("outer"):
        with tracer.span("inner"):
            raise RuntimeError("boom")
    rows = {r["name"]: r for r in tracer.spans()}
    assert rows["inner"]["status"] == "error"
    assert rows["inner"]["error"] == "RuntimeError: boom"
    assert rows["outer"]["status"] == "error"  # propagated through the parent too
    assert rows["inner"]["duration_ms"] is not None  # it ran; it has a duration
    with tracer.span("after"):
        pass
    assert {r["name"]: r for r in tracer.spans()}["after"]["parent_id"] is None


def test_end_rejects_double_end_foreign_spans_and_synthetic_statuses():
    tracer = _tracer()
    span = tracer.start("once")
    tracer.end(span)
    with pytest.raises(ValueError, match="not open"):
        tracer.end(span)
    with pytest.raises(ValueError, match="not open"):
        tracer.end(_tracer().start("other"))
    live = tracer.start("live")
    for bad in (apm.STATUS_UNFINISHED, apm.STATUS_UNMEASURED, "made-up"):
        with pytest.raises(ValueError, match="status must be"):
            tracer.end(live, status=bad)


def test_abandon_open_records_a_reason_never_a_zero():
    tracer = _tracer()
    tracer.start("root")
    tracer.start("child")
    closed = tracer.abandon_open()
    assert [c["name"] for c in closed] == ["child", "root"]  # innermost first
    for row in closed:
        assert row["duration_ms"] is None  # NOT 0.0 — it was never measured
        assert row["status"] == apm.STATUS_UNFINISHED
        assert "never ended" in row["error"]
    assert tracer.open_spans() == []
    # the context unwound all the way, so the next span is a root again
    with tracer.span("next"):
        pass
    assert {r["name"]: r for r in tracer.spans()}["next"]["parent_id"] is None


def test_a_leaked_span_keeps_parenting_until_recovered():
    # documented consequence of a ContextVar recorder: an unended span stays live
    tracer = _tracer()
    leaked = tracer.start("leaked")
    assert apm.current_span()["name"] == "leaked"
    with tracer.span("victim"):
        pass
    victim = {r["name"]: r for r in tracer.spans()}["victim"]
    assert victim["parent_id"] == leaked["span_id"]  # parented onto a dead span
    assert victim["depth"] == 1
    apm.clear_context()
    assert apm.current_span() is None
    with tracer.span("clean"):
        pass
    assert {r["name"]: r for r in tracer.spans()}["clean"]["parent_id"] is None


def test_backwards_clock_records_unmeasured_instead_of_a_negative_latency():
    # start reads 10.0, end reads 5.0 — a non-monotonic clock, not a -5s call
    tracer = _tracer(ticks=[10.0, 5.0])
    with tracer.span("reversed"):
        pass
    row = tracer.spans()[0]
    assert row["duration_ms"] is None
    assert row["status"] == apm.STATUS_UNMEASURED
    assert "backwards" in row["error"]


# ---- check_span: the anti-fabrication gate ----------------------------------


def test_check_span_rejects_every_fabricated_shape():
    base = _span("ok.span")
    bad_rows = [
        ({**base, "duration_ms": None}, "requires duration_ms"),
        ({**base, "status": apm.STATUS_UNFINISHED}, "must not carry a duration_ms"),
        ({**base, "duration_ms": None, "status": apm.STATUS_UNFINISHED, "error": None},
         "must name WHY"),
        ({**base, "error": "leftover"}, "must not also carry an error"),
        ({**base, "status": apm.STATUS_ERROR, "error": None}, "must name the failure"),
        ({**base, "status": "green"}, "status must be one of"),
        ({**base, "duration_ms": -1.0}, "must be >= 0"),
        ({**base, "duration_ms": float("nan")}, "must be finite"),
        ({**base, "duration_ms": "12ms"}, "must be a number"),
        ({**base, "depth": 3}, "must have depth 0"),
        ({**base, "parent_id": 7, "depth": 0}, "needs depth >= 1"),
        ({**base, "span_id": True}, "must be an integer"),
        ({**base, "span_id": None}, "is required"),
        ({**base, "name": "  "}, "non-empty"),
        ({**base, "trace_id": ""}, "non-empty"),
        ({**base, "start_offset_ms": -0.5}, "must be >= 0"),
        ({**base, "attrs": [1, 2]}, "attrs must be an object"),
        ({**base, "attrs": {"f": {1, 2}}}, "JSON-serializable"),
        ("not a dict", "must be a JSON object"),
    ]
    for row, message in bad_rows:
        with pytest.raises(ValueError, match=message):
            apm.check_span(row)


def test_check_span_normalizes_and_accepts_both_honest_shapes():
    measured = apm.check_span(
        {
            "trace_id": " t9 ",
            "span_id": 4,
            "parent_id": 1,
            "name": " db.query ",
            "depth": 2,
            "duration_ms": 3,
            "status": "ok",
        }
    )
    assert measured["trace_id"] == "t9" and measured["name"] == "db.query"
    assert measured["service"] == "app"  # documented default
    assert measured["duration_ms"] == 3.0 and measured["start_offset_ms"] == 0.0
    assert measured["attrs"] == {} and measured["wall_start"] is None
    assert list(measured) == list(apm.SPAN_FIELDS)  # stable key order
    unmeasured = apm.check_span(
        {"trace_id": "t9", "span_id": 5, "name": "gone", "status": "unfinished",
         "error": "process exited"}
    )
    assert unmeasured["duration_ms"] is None and unmeasured["error"] == "process exited"


def test_jsonl_round_trip_is_byte_stable_and_rejects_junk():
    rows = [_span("a", span_id=1), _span("b", span_id=2, parent_id=1, duration=None)]
    lines = apm.to_jsonl_lines(rows)
    assert lines == apm.to_jsonl_lines(rows)  # deterministic (sorted keys)
    assert all("\n" not in ln for ln in lines)
    assert [apm.parse_span_line(ln) for ln in lines] == rows
    with pytest.raises(ValueError, match="not JSON"):
        apm.parse_span_line("{oops")
    with pytest.raises(ValueError, match="requires duration_ms"):
        apm.parse_span_line(json.dumps({**rows[0], "duration_ms": None}))


# ---- percentiles ------------------------------------------------------------


def test_percentile_is_nearest_rank_and_validates_q():
    vals = [10.0, 1.0, 5.0, 2.0, 9.0, 3.0, 8.0, 4.0, 7.0, 6.0]  # unsorted on purpose
    assert apm.percentile(vals, 50) == 5.0
    assert apm.percentile(vals, 95) == 10.0
    assert apm.percentile(vals, 10) == 1.0
    assert apm.percentile(vals, 100) == 10.0
    assert apm.percentile([42.0], 50) == 42.0
    assert apm.percentile([], 50) is None  # no sample -> no number invented
    for bad in (0, -5, 101):
        with pytest.raises(ValueError, match="must be in"):
            apm.percentile(vals, bad)


# ---- operation stats --------------------------------------------------------


def test_operation_stats_percentiles_errors_and_slowest_first_ordering():
    spans = [
        _span("fast", span_id=1, duration=1.0),
        _span("fast", span_id=2, duration=3.0),
        _span("slow", span_id=3, duration=100.0),
        _span("slow", span_id=4, duration=300.0, status=apm.STATUS_ERROR, error="TimeoutError: x"),
    ]
    rows = apm.operation_stats(spans)
    assert [r["name"] for r in rows] == ["slow", "fast"]  # biggest total first
    slow, fast = rows
    assert slow["calls"] == 2 and slow["measured"] == 2 and slow["errors"] == 1
    assert slow["p50_ms"] == 100.0 and slow["p95_ms"] == 300.0 and slow["max_ms"] == 300.0
    assert slow["mean_ms"] == 200.0 and slow["total_ms"] == 400.0
    assert slow["error_rate"] == 0.5
    assert fast["error_rate"] == 0.0 and fast["unmeasured_reason"] is None
    assert fast["total_ms"] == 4.0


def test_operation_stats_never_averages_over_an_unmeasured_span():
    spans = [
        _span("mixed", span_id=1, duration=10.0),
        _span("mixed", span_id=2, duration=20.0),
        _span("mixed", span_id=3, duration=None),  # crashed mid-span
    ]
    row = apm.operation_stats(spans)[0]
    assert row["calls"] == 3 and row["measured"] == 2 and row["unmeasured"] == 1
    assert row["mean_ms"] == 15.0  # 30/2, NOT 30/3 — a gap is not a zero
    assert row["total_ms"] == 30.0 and row["max_ms"] == 20.0
    assert "1 of 3 calls carried no duration" in row["unmeasured_reason"]
    assert "unfinished" in row["unmeasured_reason"]


def test_operation_stats_with_nothing_measured_reports_why_not_zeros():
    spans = [_span("dark", span_id=1, duration=None, error="clock broke")]
    row = apm.operation_stats(spans)[0]
    for field in ("p50_ms", "p95_ms", "p99_ms", "max_ms", "mean_ms", "total_ms",
                  "error_rate"):
        assert row[field] is None, field
    assert "none of 1 calls carried a duration" in row["unmeasured_reason"]
    assert "clock broke" in row["unmeasured_reason"]


def test_operation_stats_separates_services_with_the_same_name():
    spans = [
        _span("shared", span_id=1, service="a", duration=5.0),
        _span("shared", span_id=2, service="b", duration=50.0),
    ]
    rows = apm.operation_stats(spans)
    assert [(r["service"], r["total_ms"]) for r in rows] == [("b", 50.0), ("a", 5.0)]


# ---- apdex ------------------------------------------------------------------


def test_apdex_bands_count_errors_as_frustrated():
    spans = [
        _span("t", trace_id="a", span_id=1, duration=50.0),    # <= T -> satisfied
        _span("t", trace_id="b", span_id=1, duration=100.0),   # == T -> satisfied
        _span("t", trace_id="c", span_id=1, duration=250.0),   # <= 4T -> tolerating
        _span("t", trace_id="d", span_id=1, duration=401.0),   # > 4T -> frustrated
        _span("t", trace_id="e", span_id=1, duration=1.0,
              status=apm.STATUS_ERROR, error="ValueError: x"),  # fast but failed
    ]
    score = apm.apdex(spans, t_ms=100.0)
    assert (score["satisfied"], score["tolerating"], score["frustrated"]) == (2, 1, 2)
    assert score["measured"] == 5 and score["unmeasured"] == 0
    assert score["score"] == round((2 + 0.5) / 5, 4) == 0.5
    assert score["score_error"] is None


def test_apdex_counts_transactions_only_unless_told_otherwise():
    spans = [
        _span("root", span_id=1, duration=10.0),
        _span("child", span_id=2, parent_id=1, duration=9000.0),  # a slow segment
    ]
    roots = apm.apdex(spans, t_ms=100.0)
    assert roots["transactions"] == 1 and roots["score"] == 1.0
    everything = apm.apdex(spans, t_ms=100.0, roots_only=False)
    assert everything["transactions"] == 2 and everything["frustrated"] == 1
    assert everything["score"] == 0.5


def test_apdex_without_a_measured_transaction_has_no_score_and_says_why():
    spans = [_span("root", span_id=1, duration=None, error="process exited")]
    score = apm.apdex(spans, t_ms=100.0)
    assert score["score"] is None and score["measured"] == 0
    assert score["unmeasured"] == 1
    assert "no measured transactions" in score["score_error"]
    assert "process exited" in score["score_error"]
    empty = apm.apdex([], t_ms=100.0)
    assert empty["score"] is None and "none recorded" in empty["score_error"]
    with pytest.raises(ValueError, match="must be > 0"):
        apm.apdex(spans, t_ms=0)


# ---- slowest ----------------------------------------------------------------


def test_slowest_ranks_measured_spans_only():
    spans = [
        _span("a", span_id=1, duration=5.0),
        _span("b", span_id=2, duration=50.0),
        _span("c", span_id=3, duration=None),  # unranked: it has no reading
    ]
    ranked = apm.slowest(spans, limit=10)
    assert [r["name"] for r in ranked] == ["b", "a"]
    assert apm.slowest(spans, limit=1)[0]["name"] == "b"
    assert apm.slowest(spans, limit=0) == []


# ---- trace rollup / tree ----------------------------------------------------


def test_trace_rollup_prefers_the_root_measurement_and_labels_fallbacks():
    rows = apm.trace_rollup(
        [
            _span("root", trace_id="t1", span_id=1, duration=40.0, wall=WALL),
            _span("kid", trace_id="t1", span_id=2, parent_id=1, offset=5.0, duration=10.0),
        ]
    )
    assert rows[0]["duration_ms"] == 40.0 and rows[0]["duration_from"] == "root-span"
    assert rows[0]["root"] == "root" and rows[0]["spans"] == 2
    assert rows[0]["wall_start"] == WALL and rows[0]["duration_error"] is None
    # no root in the window: fall back to the measured extent and SAY so
    orphaned = apm.trace_rollup(
        [_span("kid", trace_id="t2", span_id=2, parent_id=1, offset=5.0, duration=10.0)]
    )
    assert orphaned[0]["duration_ms"] == 15.0
    assert orphaned[0]["duration_from"] == "measured-span-extent"
    assert orphaned[0]["root"] is None and "no root span" in orphaned[0]["root_error"]
    # nothing measured at all: no number, and the reason
    dark = apm.trace_rollup([_span("x", trace_id="t3", span_id=1, duration=None)])
    assert dark[0]["duration_ms"] is None and dark[0]["duration_from"] is None
    assert "no measured span" in dark[0]["duration_error"]


def test_trace_rollup_orders_newest_first_and_counts_problems():
    rows = apm.trace_rollup(
        [
            _span("old", trace_id="old", span_id=1, duration=1.0, wall=WALL),
            _span("new", trace_id="new", span_id=1, duration=1.0, wall=WALL + 60),
            _span("kid", trace_id="new", span_id=2, parent_id=1, duration=None,
                  wall=WALL + 60),
            _span("bad", trace_id="new", span_id=3, parent_id=1, duration=2.0,
                  status=apm.STATUS_ERROR, error="OSError: x", wall=WALL + 60),
        ]
    )
    assert [r["trace_id"] for r in rows] == ["new", "old"]
    assert rows[0]["errors"] == 1 and rows[0]["unmeasured"] == 1
    assert rows[0]["services"] == ["demo"]


def test_trace_tree_nests_children_and_surfaces_an_orphan():
    spans = [
        _span("root", span_id=1, duration=30.0),
        _span("mid", span_id=2, parent_id=1, offset=1.0, duration=20.0),
        _span("leaf", span_id=3, parent_id=2, depth=2, offset=2.0, duration=5.0),
        _span("orphan", span_id=4, parent_id=99, offset=3.0, duration=1.0),
    ]
    roots = apm.trace_tree(spans, "t1")
    assert [r["name"] for r in roots] == ["root", "orphan"]  # start order
    assert [c["name"] for c in roots[0]["children"]] == ["mid"]
    assert [g["name"] for g in roots[0]["children"][0]["children"]] == ["leaf"]
    assert roots[1]["orphan"] is True and roots[0]["orphan"] is False
    assert apm.trace_tree(spans, "nope") == []


def test_trace_tree_and_flame_survive_a_parent_cycle():
    # a hand-written file really can contain 1 -> 2 -> 1; it must not hang
    spans = [
        _span("a", span_id=1, parent_id=2, depth=1, duration=5.0),
        _span("b", span_id=2, parent_id=1, depth=1, duration=5.0),
    ]
    roots = apm.trace_tree(spans, "t1")
    assert {r["name"] for r in roots} == {"a", "b"}  # both surfaced, none dropped
    assert all(r["cycle"] for r in roots)  # named a CYCLE, not "deep"
    assert not any(r["truncated"] for r in roots)
    layout = apm.flame_layout(spans)
    assert layout["skipped_cycles"] == 2 and layout["skipped_deep"] == 0
    assert layout["blocks"] == [] and layout["layout_error"] is not None
    tree = apm.trace_tree(spans, "t1")
    assert json.dumps(tree)  # serializable -> no circular reference survived


def test_a_legally_deep_chain_is_labelled_truncated_not_a_cycle():
    # a 600-deep chain is legal, just deeper than the ancestry walk goes; calling
    # it a cycle would be a fabricated diagnosis, and forcing it to the top level
    # would lie about the call structure
    depth_limit = apm._MAX_ANCESTRY
    spans = [_span("f0", span_id=1, duration=1.0)]
    for i in range(1, depth_limit + 90):
        spans.append(
            _span(f"f{i}", span_id=i + 1, parent_id=i, depth=i, duration=1.0)
        )
    roots = apm.trace_tree(spans, "t1")
    assert [r["name"] for r in roots] == ["f0"]  # still ONE root: nothing detached
    deep = {s["span_id"]: s for s in spans}
    node, seen = roots[0], 0
    while node["children"]:
        node = node["children"][0]
        seen += 1
    assert seen == len(deep) - 1  # the whole chain nested, nothing dropped
    layout = apm.flame_layout(spans)
    assert layout["skipped_cycles"] == 0
    # the 90 spans deeper than the walk are excluded from the fold and COUNTED,
    # never folded into a shorter (wrong) stack
    assert layout["skipped_deep"] == 90
    assert layout["stacks"] == depth_limit


# ---- flame ------------------------------------------------------------------


def test_flame_layout_folds_stacks_and_computes_self_time_and_widths():
    spans = [
        _span("root", span_id=1, duration=100.0),
        _span("db", span_id=2, parent_id=1, duration=30.0),
        _span("db", span_id=3, parent_id=1, offset=40.0, duration=10.0),
        _span("render", span_id=4, parent_id=1, offset=60.0, duration=20.0),
    ]
    layout = apm.flame_layout(spans)
    assert layout["total_ms"] == 100.0 and layout["stacks"] == 3
    blocks = {tuple(b["path"]): b for b in layout["blocks"]}
    assert blocks[("root",)]["width_pct"] == 100.0
    assert blocks[("root",)]["self_ms"] == 40.0  # 100 - (30 + 10 + 20)
    db = blocks[("root", "db")]
    assert db["calls"] == 2 and db["total_ms"] == 40.0 and db["width_pct"] == 40.0
    assert db["left_pct"] == 0.0  # widest child laid out first
    render = blocks[("root", "render")]
    assert render["left_pct"] == 40.0 and render["width_pct"] == 20.0
    assert [b["depth"] for b in layout["blocks"]] == [0, 1, 1]


def test_flame_clamps_negative_self_time_and_counts_the_clamp():
    # concurrent children can exceed the parent's wall duration
    spans = [
        _span("root", span_id=1, duration=10.0),
        _span("kid", span_id=2, parent_id=1, duration=8.0),
        _span("kid", span_id=3, parent_id=1, duration=9.0),
    ]
    layout = apm.flame_layout(spans)
    root = next(b for b in layout["blocks"] if b["path"] == ["root"])
    assert root["self_ms"] == 0.0  # never negative
    assert root["clamped"] == 1  # and never silent


def test_flame_layout_with_no_measured_span_reports_the_reason():
    layout = apm.flame_layout([_span("x", span_id=1, duration=None, error="crashed")])
    assert layout["blocks"] == [] and layout["total_ms"] == 0.0
    assert "no measured span to scale" in layout["layout_error"]
    assert "crashed" in layout["layout_error"]
    unmeasured = apm.flame_layout(
        [_span("x", span_id=1, duration=5.0), _span("y", span_id=2, parent_id=1,
                                                    duration=None)]
    )
    kid = next(b for b in unmeasured["blocks"] if b["path"] == ["x", "y"])
    assert kid["unmeasured"] == 1 and kid["measured"] == 0 and kid["total_ms"] == 0.0


# ---- store ------------------------------------------------------------------


def _mem():
    return apm.open_store(":memory:")


def test_store_round_trip_and_idempotent_ingest():
    conn = _mem()
    rows = [
        _span("root", span_id=1, duration=5.0, attrs={"limit": 200}),
        _span("kid", span_id=2, parent_id=1, duration=None, error="exited"),
    ]
    first = apm.record_spans(conn, rows, ingest_ts=WALL)
    assert first == {"seen": 2, "inserted": 2, "duplicates": 0}
    again = apm.record_spans(conn, rows, ingest_ts=WALL + 1)
    assert again == {"seen": 2, "inserted": 0, "duplicates": 2}  # UNIQUE(trace, span)
    loaded = apm.load_spans(conn)
    assert loaded == rows  # exact round trip, attrs decoded
    assert loaded[0]["attrs"] == {"limit": 200}
    assert loaded[1]["duration_ms"] is None and loaded[1]["error"] == "exited"


def test_record_spans_rejects_a_bad_batch_whole():
    conn = _mem()
    good = _span("good", span_id=1, duration=1.0)
    bad = {**good, "span_id": 2, "duration_ms": None}  # ok status, no reading
    with pytest.raises(ValueError, match="requires duration_ms"):
        apm.record_spans(conn, [good, bad], ingest_ts=WALL)
    assert apm.load_spans(conn) == []  # nothing half-landed


def test_load_spans_filters_and_never_ranks_an_unmeasured_span_as_fast():
    conn = _mem()
    apm.record_spans(
        conn,
        [
            _span("fast", trace_id="t1", span_id=1, duration=1.0, wall=WALL),
            _span("slow", trace_id="t1", span_id=2, parent_id=1, duration=900.0,
                  wall=WALL),
            _span("gone", trace_id="t2", span_id=1, duration=None, error="exited",
                  wall=WALL + 100),
            _span("boom", trace_id="t2", span_id=2, parent_id=1, duration=2.0,
                  status=apm.STATUS_ERROR, error="OSError: x", wall=WALL + 100),
        ],
        ingest_ts=WALL,
    )
    assert [s["name"] for s in apm.load_spans(conn, trace_id="t2")] == ["gone", "boom"]
    assert [s["name"] for s in apm.load_spans(conn, name="slow")] == ["slow"]
    assert [s["name"] for s in apm.load_spans(conn, status="error")] == ["boom"]
    # min_ms compares against duration_ms, so NULL durations can never satisfy it
    assert [s["name"] for s in apm.load_spans(conn, min_ms=100.0)] == ["slow"]
    assert [s["name"] for s in apm.load_spans(conn, min_ms=0.0)] == [
        "fast", "slow", "boom",
    ]
    assert {s["trace_id"] for s in apm.load_spans(conn, since=WALL + 50)} == {"t2"}
    assert len(apm.load_spans(conn, limit=1)) == 1


def test_recent_trace_ids_are_newest_first():
    conn = _mem()
    apm.record_spans(
        conn,
        [
            _span("old", trace_id="old", span_id=1, duration=1.0, wall=WALL),
            _span("new", trace_id="new", span_id=1, duration=1.0, wall=WALL + 500),
            _span("undated", trace_id="undated", span_id=1, duration=1.0, wall=None),
        ],
        ingest_ts=WALL,
    )
    assert apm.recent_trace_ids(conn) == ["new", "old", "undated"]
    assert apm.recent_trace_ids(conn, limit=1) == ["new"]


def test_open_store_is_idempotent_on_a_real_file(tmp_path):
    db = tmp_path / "nested" / "apm.db"
    conn = apm.open_store(db)  # parent dir created via pathlib
    apm.record_spans(conn, [_span("a", span_id=1, duration=1.0)], ingest_ts=WALL)
    conn.close()
    conn2 = apm.open_store(db)  # re-open: no error, prior rows survive
    assert [s["name"] for s in apm.load_spans(conn2)] == ["a"]
    assert conn2.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()[0] == apm.SCHEMA_VERSION


# ---- family diagnostics -----------------------------------------------------


def test_to_diagnostics_maps_latency_bands_errors_and_gaps():
    spans = [
        _span("critical", span_id=1, duration=5000.0),
        _span("slowish", span_id=2, duration=800.0),
        _span("quick", span_id=3, duration=1.0),
        _span("flaky", span_id=4, duration=2.0, status=apm.STATUS_ERROR,
              error="ValueError: x"),
        _span("holey", span_id=5, duration=1.0),
        _span("holey", span_id=6, duration=None, error="process exited"),
    ]
    diags = apm.to_diagnostics(apm.operation_stats(spans))
    by_rule = {}
    for d in diags:
        by_rule.setdefault(d["rule"], []).append(d)
    assert by_rule["apm:critical-latency"][0]["severity"] == "error"
    assert by_rule["apm:critical-latency"][0]["path"] == "apm://demo/critical"
    assert by_rule["apm:slow"][0]["severity"] == "warning"
    # was `"apm:slow" not in {d["rule"] for d in by_rule["apm:critical-latency"]}`,
    # which cannot fail: the bucket is KEYED by d["rule"], so every member already
    # has rule == "apm:critical-latency". The property actually worth pinning is that
    # the two rules are mutually exclusive PER PATH — a span over the critical bar is
    # reported as critical and NOT also as merely slow.
    assert "apm://demo/critical" not in {d["path"] for d in by_rule.get("apm:slow", [])}
    assert by_rule["apm:errors"][0]["severity"] == "error"  # 100% of measured calls
    assert by_rule["apm:unmeasured"][0]["severity"] == "warning"
    assert "process exited" in by_rule["apm:unmeasured"][0]["message"]
    assert "quick" not in json.dumps(diags)  # a healthy op emits nothing
    summary = openswap.summarize(diags)
    assert summary["total"] == len(diags)
    assert summary["by_severity"]["error"] == 2


def test_to_diagnostics_budgets_are_configurable():
    stats = apm.operation_stats([_span("op", span_id=1, duration=100.0)])
    assert apm.to_diagnostics(stats) == []  # 100ms is fine under the defaults
    tuned = apm.to_diagnostics(stats, slow_ms=50.0, critical_ms=1000.0)
    assert [d["rule"] for d in tuned] == ["apm:slow"]
    harsh = apm.to_diagnostics(stats, slow_ms=10.0, critical_ms=50.0)
    assert [d["rule"] for d in harsh] == ["apm:critical-latency"]


def test_to_diagnostics_error_rate_severity_is_configurable():
    spans = [_span("op", span_id=i, duration=1.0) for i in range(1, 20)]
    spans.append(
        _span("op", span_id=99, duration=1.0, status=apm.STATUS_ERROR, error="OSError: x")
    )
    stats = apm.operation_stats(spans)
    assert stats[0]["error_rate"] == 0.05
    assert apm.to_diagnostics(stats)[0]["severity"] == "error"  # at the threshold
    lenient = apm.to_diagnostics(stats, error_rate_error=0.5)
    assert lenient[0]["severity"] == "warning" and lenient[0]["rule"] == "apm:errors"


# ---- the static page --------------------------------------------------------


def test_render_html_is_deterministic_escapes_and_never_shows_a_fake_zero():
    spans = [
        _span("<script>alert(1)</script>", span_id=1, duration=100.0),
        _span("kid", span_id=2, parent_id=1, offset=50.0, duration=25.0),
        _span("gone", span_id=3, parent_id=1, offset=90.0, duration=None,
              error="process exited mid-span"),
    ]
    page = apm.render_html(spans)
    assert page == apm.render_html(spans)  # byte-identical for identical input
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    # the unmeasured span gets its REASON, not a zero-width bar
    assert "process exited mid-span" in page
    assert "unmeasured" in page
    # waterfall geometry: the child starts at 50% and is 25% wide
    assert 'style="left:50.0000%;width:25.0000%"' in page
    assert "generation time not recorded" in page
    assert "perf_counter" in page
    stamped = apm.render_html(spans, generated_ts=WALL)
    assert "2023-11-14" in stamped and "generation time not recorded" not in stamped


def test_render_html_survives_an_empty_store_without_inventing_numbers():
    page = apm.render_html([])
    assert "no spans recorded" in page
    assert "0 spans (0 measured, 0 unmeasured)" in page
    assert "no measured span to scale" in page
    assert "<!DOCTYPE html>" in page and page.endswith("</html>\n")
    assert "http://" not in page and "https://" not in page  # zero external assets


def test_render_html_marks_errored_bars_and_caps_traces():
    spans = [
        _span("a", trace_id="t1", span_id=1, duration=10.0, status=apm.STATUS_ERROR,
              error="RuntimeError: boom", wall=WALL + 10),
        _span("b", trace_id="t2", span_id=1, duration=10.0, wall=WALL),
    ]
    page = apm.render_html(spans, max_traces=1)
    assert 'class="bar err"' in page
    assert "RuntimeError: boom" in page
    assert page.count("<h2>a ") == 1  # newest trace only
    assert "<h2>b " not in page


# ---- detection --------------------------------------------------------------


def test_detection_fallback_is_expected_steady_state(monkeypatch):
    from bigbang.plugins.apm import cli as apm_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = apm_cli._capability()
    assert cap["adapter"] == "apm"
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert "complete product" in cap["fallback_scope"]
    assert cap["native"]["found"] is False
    assert cap["extras"]["py-spy"]["found"] is False
    assert cap["extras"]["newrelic-admin"]["found"] is False  # SaaS agent, never run


def test_manifest_is_zero_egress():
    import yaml

    manifest = yaml.safe_load(
        (ROOT / "bigbang" / "plugins" / "apm" / "manifest.yaml").read_text(
            encoding="utf-8"
        )
    )
    net = manifest["capabilities"]["network"]
    assert net["enabled"] is False and net["domains"] == []
    assert manifest["capabilities"]["secrets"]["allow"] == []
    assert manifest["capabilities"]["filesystem"]["paths"] == [".scout"]


# ---- the real CLI in a subprocess (offline by construction) -----------------


def _cli(args, env=None):
    import os

    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(ROOT),
        env=e,
    )


def test_cli_apm_hello_envelope():
    r = _cli(["apm", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert "example" in data


def test_cli_apm_stats_without_a_store_fails_actionably(tmp_path):
    r = _cli(["apm", "stats", "--db", str(tmp_path / "missing.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no span store" in data["error"] and "example" in data


def test_cli_apm_probe_then_stats_traces_report(tmp_path):
    db = tmp_path / "apm.db"
    jsonl = tmp_path / "spans.jsonl"
    r = _cli(["apm", "probe", "--db", str(db), "--jsonl-out", str(jsonl)])
    assert r.returncode == 0, r.stderr + r.stdout
    probe = json.loads(r.stdout)["data"]
    assert probe["clock"] == "time.perf_counter"
    assert probe["recorded"]["inserted"] == len(probe["spans"]) == 4
    names = [s["name"] for s in probe["spans"]]
    assert names == ["apm.probe", "store.open", "store.read",
                     "aggregate.operation_stats"]
    for s in probe["spans"]:
        assert s["status"] == "ok"
        assert s["duration_ms"] is not None and s["duration_ms"] > 0.0  # real I/O
    assert jsonl.read_bytes().count(b"\n") == 4
    assert b"\r\n" not in jsonl.read_bytes()  # byte-exact LF via write_bytes

    stats = json.loads(_cli(["apm", "stats", "--db", str(db)]).stdout)["data"]
    assert stats["spans"] == 4 and len(stats["operations"]) == 4
    assert stats["apdex"]["score"] == 1.0  # a millisecond probe is satisfying

    board = json.loads(_cli(["apm", "traces", "--db", str(db)]).stdout)["data"]
    assert len(board["traces"]) == 1 and board["traces"][0]["spans"] == 4
    trace_id = board["traces"][0]["trace_id"]
    one = json.loads(
        _cli(["apm", "traces", "--db", str(db), "--trace", trace_id, "--tree"]).stdout
    )["data"]
    assert one["spans"][0]["name"] == "apm.probe"
    assert len(one["spans"][0]["children"]) == 3
    assert one["flame"]["total_ms"] > 0

    out = tmp_path / "report.html"
    rep = json.loads(_cli(["apm", "report", "--db", str(db), "--out", str(out)]).stdout)
    assert rep["data"]["spans"] == 4 and rep["data"]["stamped"] is False
    raw = out.read_bytes()
    assert b"\r\n" not in raw  # write_bytes, not write_text
    assert len(raw) == rep["data"]["bytes"]
    assert b"store.open" in raw and b"<!DOCTYPE html>" in raw


def test_cli_apm_ingest_reports_a_fabricated_line_and_never_stores_it(tmp_path):
    good = _span("real", span_id=1, duration=1.5)
    fake = {**good, "span_id": 2, "name": "fabricated", "duration_ms": None}
    src = tmp_path / "spans.jsonl"
    src.write_bytes(
        ("\n".join([json.dumps(good), json.dumps(fake), "", "{not json"]) + "\n").encode(
            "utf-8"
        )
    )
    db = tmp_path / "apm.db"
    r = _cli(["apm", "ingest", str(src), "--db", str(db)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["recorded"] == {"seen": 1, "inserted": 1, "duplicates": 0}
    assert [x["line"] for x in data["rejected"]] == [2, 4]
    assert "requires duration_ms" in data["rejected"][0]["error"]
    assert data["traces"] == ["t1"]
    stats = json.loads(_cli(["apm", "stats", "--db", str(db)]).stdout)["data"]
    assert [op["name"] for op in stats["operations"]] == ["real"]  # never the fake
    strict = _cli(["apm", "ingest", str(src), "--db", str(db), "--strict"])
    assert strict.returncode == 1  # the CI gate on a malformed feed


def test_cli_apm_ingest_needs_a_source(tmp_path):
    r = _cli(["apm", "ingest", "--db", str(tmp_path / "apm.db")])
    assert r.returncode == 1
    assert "--stdin" in json.loads(r.stdout)["error"]
    missing = _cli(["apm", "ingest", str(tmp_path / "nope.jsonl")])
    assert missing.returncode == 1
    assert "no such spans file" in json.loads(missing.stdout)["error"]


def test_cli_apm_stats_fail_on_gates_and_validates(tmp_path):
    db = tmp_path / "apm.db"
    assert _cli(["apm", "probe", "--db", str(db)]).returncode == 0
    clean = _cli(["apm", "stats", "--db", str(db), "--fail-on", "warning"])
    assert clean.returncode == 0  # a sub-millisecond probe breaches no budget
    tripped = _cli(
        ["apm", "stats", "--db", str(db), "--slow-ms", "0.0001", "--fail-on", "warning"]
    )
    assert tripped.returncode == 1
    assert json.loads(tripped.stdout)["data"]["summary"]["by_severity"]["warning"] > 0
    bad = _cli(["apm", "stats", "--db", str(db), "--fail-on", "nope"])
    assert bad.returncode == 1 and "--fail-on must be one of" in json.loads(bad.stdout)["error"]
