"""Collector tests. These run fully OFFLINE: every HF stream is replaced by a
`stream_factory` on the SourceSpec, so no network is touched in CI.

The properties under test are the ones that keep an unattended, kill-happy
pipeline correct: shards roll and publish atomically, doc ids are deterministic,
a mid-shard kill never duplicates a document on restart, backpressure halts
writes, and the source registry is internally consistent.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import zstandard as zstd

from ava.pipeline import collector
from ava.pipeline.collector import (
    CollectorConfig,
    SourceSpec,
    build_doc,
    doc_id_for,
    load_sources,
    run_source,
    serve,
    sources_for_phase,
)
from ava.pipeline.flow import FlowConfig, PauseReason
from ava.pipeline.manifest import RAW, Manifest

REPO = Path(__file__).resolve().parent.parent
SOURCES_YAML = REPO / "configs" / "sources.yaml"
PIPELINE_YAML = REPO / "configs" / "pipeline.yaml"


def _cfg(target_bytes: int = 600) -> CollectorConfig:
    return CollectorConfig(
        http_retries=8, backoff_initial=0.001, backoff_max=0.002,
        backoff_jitter=0.0, raw_target_bytes=target_bytes,
    )


def _log() -> tuple[object, io.StringIO]:
    buf = io.StringIO()
    return collector.make_logger("test:worker", stream=buf), buf


def _manifest(tmp_path: Path) -> Manifest:
    return Manifest(str(tmp_path / "manifest.db"))


def _read_shards(raw_dir: Path, source: str) -> list[dict]:
    docs = []
    d = zstd.ZstdDecompressor()
    for f in sorted((raw_dir / source).glob("*.jsonl.zst")):
        raw = d.decompress(f.read_bytes())
        for line in raw.decode("utf-8").splitlines():
            if line.strip():
                docs.append(json.loads(line))
    return docs


def _tmp_files(raw_dir: Path) -> list[Path]:
    return [p for p in raw_dir.rglob("*") if p.is_file() and p.name.endswith(".tmp")]


# ---------------------------------------------------------------------------
# doc_id determinism


def test_doc_id_is_deterministic_and_scoped():
    assert doc_id_for("src", "hello world") == doc_id_for("src", "hello world")
    assert doc_id_for("src", "a") != doc_id_for("src", "b")
    assert doc_id_for("src", "a") != doc_id_for("other", "a")
    assert doc_id_for("src", "a").startswith("src:")


def test_build_doc_id_matches_helper():
    spec = SourceSpec(name="s", kind="synthetic", generator="logic")
    d1 = build_doc(spec, 0, {"text": "same text"})
    d2 = build_doc(spec, 3, {"text": "same text"})
    assert d1["doc_id"] == d2["doc_id"] == doc_id_for("s", "same text")


# ---------------------------------------------------------------------------
# shard rolling + atomic publish


def _counting_factory(n_docs: int, kill_at: int | None = None):
    """A fake stream of `n_docs` docs that honors `skip`. If `kill_at` is set it
    raises Kill (a BaseException => a real crash, not a retryable error) once it
    has yielded that many docs in this process."""
    state = {"yielded": 0}

    class Kill(BaseException):
        pass

    def factory(skip: int):
        for i in range(skip, n_docs):
            if kill_at is not None and state["yielded"] >= kill_at:
                raise Kill()
            state["yielded"] += 1
            yield {"text": f"document number {i:04d} " + "payload " * 6}

    return factory, Kill


def test_shard_rolls_at_target_bytes_and_leaves_no_tmp(tmp_path):
    factory, _ = _counting_factory(40)
    spec = SourceSpec(name="roller", kind="synthetic", stream_factory=factory)
    raw = tmp_path / "raw"
    log, _buf = _log()
    with _manifest(tmp_path) as m:
        written = run_source(spec, 2, m, _cfg(target_bytes=500), raw, log)
        counts = m.counts_by_state()
        cursor_pos, cursor_docs = m.get_cursor(collector.cursor_key(spec, 2))

    assert written == 40
    files = sorted((raw / "roller").glob("*.jsonl.zst"))
    assert len(files) >= 2, "small target should have rolled multiple shards"
    assert counts.get(RAW) == len(files)          # every shard registered
    assert cursor_docs == 40 and cursor_pos == "docs:40"
    assert _tmp_files(raw) == []                   # no .tmp left behind
    docs = _read_shards(raw, "roller")
    assert len(docs) == 40
    assert len({d["doc_id"] for d in docs}) == 40


def test_once_produces_a_single_shard(tmp_path):
    factory, _ = _counting_factory(1000)
    spec = SourceSpec(name="oncer", kind="synthetic", stream_factory=factory)
    raw = tmp_path / "raw"
    log, _buf = _log()
    with _manifest(tmp_path) as m:
        run_source(spec, 0, m, _cfg(target_bytes=400), raw, log, once=True)
        assert m.counts_by_state().get(RAW) == 1
    assert len(list((raw / "oncer").glob("*.jsonl.zst"))) == 1


# ---------------------------------------------------------------------------
# resume across a mid-shard kill: no duplicates, full coverage


def test_resume_after_kill_has_no_duplicates_and_full_coverage(tmp_path):
    raw = tmp_path / "raw"
    log, _buf = _log()
    db = str(tmp_path / "manifest.db")

    # Run 1: crash (BaseException) after 50 docs, mid-stream.
    factory1, Kill = _counting_factory(100, kill_at=50)
    spec1 = SourceSpec(name="resumable", kind="synthetic", stream_factory=factory1)
    with Manifest(db) as m:
        with pytest.raises(Kill):
            run_source(spec1, 1, m, _cfg(target_bytes=500), raw, log)
        _, cursor_after_crash = m.get_cursor(collector.cursor_key(spec1, 1))

    assert _tmp_files(raw) == []          # crash left no partial tmp on disk
    assert cursor_after_crash < 100       # we did not finish

    # Run 2: fresh process, resumes from the manifest cursor, no kill.
    factory2, _ = _counting_factory(100)
    spec2 = SourceSpec(name="resumable", kind="synthetic", stream_factory=factory2)
    with Manifest(db) as m:
        run_source(spec2, 1, m, _cfg(target_bytes=500), raw, log)
        _, final_cursor = m.get_cursor(collector.cursor_key(spec2, 1))

    assert final_cursor == 100
    docs = _read_shards(raw, "resumable")
    ids = [d["doc_id"] for d in docs]
    texts = {d["text"] for d in docs}
    assert len(ids) == len(set(ids)), "a killed shard must not duplicate doc_ids"
    expected = {f"document number {i:04d} " + "payload " * 6 for i in range(100)}
    assert texts == expected               # every one of the 100 docs is present
    assert _tmp_files(raw) == []


# ---------------------------------------------------------------------------
# backpressure: a paused collector writes nothing


def test_backpressure_pauses_and_writes_nothing(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    log, buf = _log()
    fcfg = FlowConfig.load(PIPELINE_YAML)
    factory, _ = _counting_factory(1000)
    spec = SourceSpec(name="synth_logic", kind="synthetic", stream_factory=factory,
                      phases=(0,), weight={0: 1.0})

    monkeypatch.setattr(collector, "collector_should_pause",
                        lambda *a, **k: PauseReason(True, "disk full (test)"))
    sleeps = {"n": 0}
    with _manifest(tmp_path) as m:
        serve(m, fcfg, _cfg(), [spec], raw, log,
              max_iterations=4, sleep_fn=lambda s: sleeps.__setitem__("n", sleeps["n"] + 1))
        assert m.counts_by_state() == {}          # nothing written while paused

    assert sleeps["n"] == 4                        # it slept each paused iteration
    assert not raw.exists() or not any(raw.rglob("*.jsonl.zst"))
    # pause reason logged exactly once (no per-loop spam)
    pause_events = [json.loads(l) for l in buf.getvalue().splitlines()
                    if json.loads(l)["event"] == "collector_pause"]
    assert len(pause_events) == 1


# ---------------------------------------------------------------------------
# filters


def _fineweb_like() -> SourceSpec:
    return SourceSpec(
        name="fineweb_edu", kind="hf", text_field="text", score_field="score",
        phases=(2, 4, 5), task_type="automatic",
        filters={"min_chars": {2: 200, 4: 4000, 5: 200},
                 "min_edu_score": {2: 2.0, 5: 4.5}},
    )


def test_filters_reject_short_docs():
    spec = _fineweb_like()
    short = {"text": "too short", "score": 5.0}
    long_enough = {"text": "x" * 250, "score": 5.0}
    assert build_doc(spec, 2, short) is None
    assert build_doc(spec, 2, long_enough) is not None


def test_filters_reject_low_edu_score_per_phase():
    spec = _fineweb_like()
    text = "x" * 300
    assert build_doc(spec, 2, {"text": text, "score": 1.5}) is None   # < 2.0
    assert build_doc(spec, 2, {"text": text, "score": 2.5}) is not None
    # phase 5 is stricter
    assert build_doc(spec, 5, {"text": text, "score": 4.0}) is None   # < 4.5
    assert build_doc(spec, 5, {"text": text, "score": 4.6}) is not None
    # phase 4 has no score filter but demands long docs
    assert build_doc(spec, 4, {"text": "x" * 300}) is None            # < 4000 chars
    assert build_doc(spec, 4, {"text": "x" * 5000}) is not None


def test_missing_text_field_is_rejected():
    spec = SourceSpec(name="s", kind="hf", text_field="text")
    assert build_doc(spec, 0, {"nottext": "hi"}) is None
    assert build_doc(spec, 0, {"text": ""}) is None
    assert build_doc(spec, 0, {"text": 123}) is None


# ---------------------------------------------------------------------------
# sources.yaml registry integrity


def test_sources_yaml_parses_and_has_required_keys():
    sources = load_sources(SOURCES_YAML)
    assert sources
    names = [s.name for s in sources]
    assert len(names) == len(set(names)), "source names must be unique"
    for s in sources:
        assert s.name and s.kind in {"hf", "synthetic"}
        assert s.text_field
        assert s.phases, f"{s.name} lists no phases"
        assert s.task_type in {"automatic", "deliberate", "safety", "temporal"}
        assert set(s.weight) <= set(s.phases), f"{s.name} weights a phase it doesn't serve"
        if s.kind == "hf":
            assert s.dataset and s.split
        else:
            from ava.datagen import GENERATORS
            assert s.generator in GENERATORS, f"{s.name}: unknown generator {s.generator}"
            # the registry may not claim a phase the generator cannot emit
            gen_phases = set(GENERATORS[s.generator].phases)
            assert set(s.phases) <= gen_phases, (
                f"{s.name} lists phases {s.phases} but {s.generator} emits {sorted(gen_phases)}")


def test_every_phase_mixture_sums_to_one():
    sources = load_sources(SOURCES_YAML)
    for phase in range(6):
        total = sum(s.weight.get(phase, 0.0) for s in sources if phase in s.phases)
        assert abs(total - 1.0) < 1e-6, f"phase {phase} mixture sums to {total}, not 1.0"


def test_curriculum_covers_all_six_phases_with_synthetic_present():
    sources = load_sources(SOURCES_YAML)
    for phase in range(6):
        serving = sources_for_phase(sources, phase)
        assert serving, f"phase {phase} has no positive-weight source"
    # P0 must be synthetic-only per the curriculum
    p0 = [s for s in sources if 0 in s.phases and s.weight.get(0, 0) > 0]
    assert p0 and all(s.kind == "synthetic" for s in p0)


def test_no_gated_sources_in_registry():
    for s in load_sources(SOURCES_YAML):
        assert s.gated is False, f"{s.name} is gated; collector has no HF_TOKEN guarantee"


# ---------------------------------------------------------------------------
# weighted round-robin selection


def test_weighted_round_robin_respects_weights():
    rr = collector.WeightedRR([("a", 0.75), ("b", 0.25)])
    picks = [rr.next() for _ in range(100)]
    assert 70 <= picks.count("a") <= 80
    assert 20 <= picks.count("b") <= 30
    assert set(picks) == {"a", "b"}


def test_weighted_round_robin_skips_zero_weight():
    rr = collector.WeightedRR([("a", 1.0), ("z", 0.0)])
    assert set(rr.next() for _ in range(10)) == {"a"}
