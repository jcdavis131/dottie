"""The collector: turns remote datasets + synthetic generators into RAW shards.

Responsibilities, in one sentence: keep every curriculum phase supplied with raw
`.jsonl.zst` shards, running far enough ahead of the trainer to never starve it
but never far enough to fill the disk -- and survive a `docker kill` at any
instant without ever emitting a duplicate document.

Three properties are load-bearing and everything here exists to protect them:

1. Resumability. A per-source cursor (`docs:<n>`, in the manifest) records how
   many source records have been folded into *committed* shards. On start we
   `skip(n)` the stream. A shard's cursor is advanced only after the shard is
   fully on disk AND registered, so a crash mid-shard simply re-reads those
   records into a fresh shard next time. No document is ever lost or doubled.

2. Atomic shard publication. A shard is written to a `.tmp` sibling, fsynced,
   `os.replace()`d into place, and only then registered in the manifest
   (`add_shard` is idempotent). We never register a shard that isn't wholly on
   disk, and a crash between replace and register just re-registers on restart.

3. Deterministic identity. `doc_id = "<source>:<sha1(text)[:16]>"` and the
   shard id is the sha1 of its doc_ids. Same input -> same ids -> dedupe and
   resume are idempotent by construction.

Network I/O (HF streaming) is wrapped in exponential backoff with jitter because
huggingface.co resets connections; on persistent failure we log and move to the
next source rather than crash the container.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Callable, Iterator

import yaml

from dottie.pipeline.demand import apply_demand_weights, read_demand
from dottie.pipeline.flow import (
    N_PHASES,
    FlowConfig,
    collector_should_pause,
    free_gb,
    pick_target_phase,
)
from dottie.pipeline.manifest import RAW, Manifest, worker_id

try:  # zstandard is pinned in the image; guard only so the module imports bare.
    import zstandard as zstd
except Exception:  # pragma: no cover
    zstd = None

_DEFAULT_PIPELINE_CONFIG = "/app/configs/pipeline.yaml"


# ---------------------------------------------------------------------------
# Structured logging: one JSON object per line on stdout.


def make_logger(worker: str, stream=None) -> Callable[..., None]:
    out = stream if stream is not None else sys.stdout

    def log(event: str, *, level: str = "info", source: str | None = None,
            phase: int | None = None, **fields) -> None:
        rec = {"ts": round(time.time(), 3), "level": level, "worker": worker,
               "source": source, "phase": phase, "event": event}
        rec.update(fields)
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()

    return log


# ---------------------------------------------------------------------------
# Config: the collector-specific block of pipeline.yaml.


@dataclasses.dataclass(frozen=True)
class CollectorConfig:
    http_retries: int
    backoff_initial: float
    backoff_max: float
    backoff_jitter: float
    raw_target_bytes: int

    @classmethod
    def load(cls, path: str | Path | None = None) -> "CollectorConfig":
        p = Path(path or os.environ.get("AVA_PIPELINE_CONFIG", _DEFAULT_PIPELINE_CONFIG))
        cfg = yaml.safe_load(p.read_text())
        c = cfg.get("collector", {})
        s = cfg.get("shards", {})
        return cls(
            http_retries=int(c.get("http_retries", 8)),
            backoff_initial=float(c.get("backoff_initial_seconds", 1.0)),
            backoff_max=float(c.get("backoff_max_seconds", 120.0)),
            backoff_jitter=float(c.get("backoff_jitter", 0.3)),
            raw_target_bytes=int(s.get("raw_target_bytes", 268_435_456)),
        )


def backoff_delay(attempt: int, cfg: CollectorConfig, rng: random.Random) -> float:
    """Exponential backoff with +/- jitter. attempt is 1-based."""
    base = min(cfg.backoff_max, cfg.backoff_initial * (2 ** (attempt - 1)))
    jitter = base * cfg.backoff_jitter
    return max(0.0, base + rng.uniform(-jitter, jitter))


# ---------------------------------------------------------------------------
# Source registry.


@dataclasses.dataclass
class SourceSpec:
    name: str
    kind: str                         # "hf" | "synthetic"
    text_field: str = "text"
    dataset: str | None = None
    config: str | None = None
    split: str = "train"
    score_field: str | None = None
    generator: str | None = None
    trust_remote_code: bool = False
    phases: tuple[int, ...] = ()
    weight: dict[int, float] = dataclasses.field(default_factory=dict)
    task_type: str = "automatic"
    filters: dict = dataclasses.field(default_factory=dict)
    license: str | None = None
    gated: bool = False
    seed: int = 1234                  # synthetic only; same seed => same corpus
    # Test/override hook: a callable(skip_n) -> iterator of record dicts.
    # When set it fully replaces network/synthetic streaming for this source.
    stream_factory: Callable[[int], Iterator[dict]] | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "SourceSpec":
        weight = {int(k): float(v) for k, v in (d.get("weight") or {}).items()}
        phases = tuple(int(p) for p in d.get("phases", []))
        return cls(
            name=d["name"], kind=d["kind"], text_field=d.get("text_field", "text"),
            dataset=d.get("dataset"), config=d.get("config"), split=d.get("split", "train"),
            score_field=d.get("score_field"), generator=d.get("generator"),
            trust_remote_code=bool(d.get("trust_remote_code", False)),
            phases=phases, weight=weight, task_type=d.get("task_type", "automatic"),
            filters=d.get("filters") or {}, license=d.get("license"),
            gated=bool(d.get("gated", False)), seed=int(d.get("seed", 1234)),
        )


def sources_config_path() -> Path:
    env = os.environ.get("AVA_SOURCES_CONFIG")
    if env:
        return Path(env)
    pipe = os.environ.get("AVA_PIPELINE_CONFIG")
    if pipe:
        cand = Path(pipe).parent / "sources.yaml"
        if cand.exists():
            return cand
    return Path("/app/configs/sources.yaml")


def load_sources(path: str | Path | None = None) -> list[SourceSpec]:
    p = Path(path) if path else sources_config_path()
    doc = yaml.safe_load(p.read_text())
    return [SourceSpec.from_dict(d) for d in doc["sources"]]


# ---------------------------------------------------------------------------
# Document construction + filtering.


def doc_id_for(source: str, text: str) -> str:
    return f"{source}:{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}"


def _threshold(spec_value, phase: int):
    """A filter value may be a scalar (all phases) or a {phase: value} dict."""
    if isinstance(spec_value, dict):
        return spec_value.get(phase)
    return spec_value


def passes_filters(spec: SourceSpec, phase: int, rec: dict, text: str) -> bool:
    f = spec.filters or {}
    min_chars = _threshold(f.get("min_chars"), phase)
    if min_chars is not None and len(text) < int(min_chars):
        return False
    edu = f.get("min_edu_score")
    if isinstance(edu, dict) and phase in edu:
        field = spec.score_field or "score"
        score = rec.get(field)
        if score is None or float(score) < float(edu[phase]):
            return False
    return True


def build_doc(spec: SourceSpec, phase: int, rec: dict) -> dict | None:
    """Turn a raw source record into a shard line, or None if it is rejected."""
    text = rec.get(spec.text_field)
    if not isinstance(text, str) or not text:
        return None
    if not passes_filters(spec, phase, rec, text):
        return None
    meta: dict = {}
    for k in ("language", "license", "repo_name", "path", "url"):
        if k in rec and rec[k] is not None:
            meta[k] = rec[k]
    if spec.score_field and spec.score_field in rec:
        meta[spec.score_field] = rec[spec.score_field]
    # Synthetic generators tag each doc individually; the registry's task_type is
    # only a fallback for HF records, which carry no such annotation.
    concept = rec.get("_concept")
    task_type = rec.get("_task_type") or spec.task_type
    return {
        "doc_id": doc_id_for(spec.name, text),
        "text": text,
        "task_type": task_type,
        "concept": concept,
        "phase": phase,
        "source": spec.name,
        "meta": meta,
    }


# ---------------------------------------------------------------------------
# Synthetic generators.
#
# These are NOT defined here. `dottie/datagen/` is the single source of truth: its
# generators build natural-deduction proofs that are valid by construction,
# compute every math answer in Python, and exec() code snippets to obtain their
# doctest outputs. Re-stating simplified versions here would silently ship a
# weaker corpus than the one the tests verify.

#: One synthetic "epoch" before the generator is re-seeded. Bounded so a stream
#: never materializes an unbounded corpus in memory.
_SYNTH_EPOCH_BYTES = 8 * 1024 * 1024


def _synthetic_stream(spec: SourceSpec, skip_n: int, phase: int | None = None) -> Iterator[dict]:
    """Endless deterministic doc stream from an ava.datagen generator.

    The generator -- not the registry -- decides each doc's phase, task_type and
    concept. A generator emits a *mix* (MathGenerator spans phases 1/3/4), so we
    FILTER to the requested phase rather than relabel whatever comes out. The
    earlier behaviour stamped phase-1 arithmetic as phase-4 long-context data.

    Resumability: generators are seeded, so doc N of a given phase is always the
    same doc. We skip forward by discarding, which is O(skip_n) but exact -- the
    alternative (index-addressable generation) would forbid the stateful
    curricula the generators build up.

    Each epoch re-seeds with `seed + epoch` so a long run keeps producing new
    documents instead of cycling one corpus forever.
    """
    from dottie.datagen import GENERATORS

    try:
        cls = GENERATORS[spec.generator]
    except KeyError:
        raise ValueError(
            f"source {spec.name!r}: unknown generator {spec.generator!r}; "
            f"known: {sorted(GENERATORS)}"
        ) from None

    want = None if phase is None else f"p{phase}"
    if want is not None and phase not in cls.phases:
        raise ValueError(
            f"source {spec.name!r}: generator {spec.generator!r} emits phases "
            f"{cls.phases}, not {phase}"
        )

    seen = 0
    epoch = 0
    while True:
        gen = cls(seed=spec.seed + epoch)
        for doc in gen.generate(_SYNTH_EPOCH_BYTES):
            if want is not None and doc["phase"] != want:
                continue
            if seen < skip_n:
                seen += 1
                continue
            seen += 1
            yield {"text": doc["text"], "_concept": doc["concept"],
                   "_task_type": doc["task_type"]}
        epoch += 1


def _hf_stream(spec: SourceSpec, skip_n: int) -> Iterator[dict]:
    # Lazy import: only paid when a real HF source runs (and only in-container).
    from datasets import load_dataset

    ds = load_dataset(
        spec.dataset, spec.config, split=spec.split, streaming=True,
        trust_remote_code=spec.trust_remote_code,
    )
    if skip_n:
        ds = ds.skip(skip_n)
    return iter(ds)


def make_factory(spec: SourceSpec, phase: int | None = None) -> Callable[[int], Iterator[dict]]:
    if spec.stream_factory is not None:
        return spec.stream_factory
    if spec.kind == "hf":
        return lambda skip: _hf_stream(spec, skip)
    if spec.kind == "synthetic":
        return lambda skip: _synthetic_stream(spec, skip, phase)
    raise ValueError(f"unknown source kind {spec.kind!r}")


class GiveUp(Exception):
    """Raised (internally, caught by the service) when a source keeps failing."""


def iter_records(
    spec: SourceSpec,
    start_pos: int,
    cfg: CollectorConfig,
    log: Callable[..., None],
    factory: Callable[[int], Iterator[dict]],
    rng: random.Random,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Iterator[tuple[int, dict]]:
    """Yield (source_position, record), transparently resuming across transient
    network failures. `source_position` is the 0-based index in the *source*
    stream (used for the resume cursor), independent of how many records survive
    filtering. Only `Exception` is treated as transient; `BaseException`
    (e.g. a real kill) propagates so the caller aborts without committing."""
    pos = start_pos
    it: Iterator[dict] | None = None
    fails = 0
    while True:
        try:
            if it is None:
                # Establishment is inside the try: load_dataset() itself can
                # fail transiently (e.g. HF 429 when several collectors boot
                # at once), and that must back off, not kill the process.
                it = factory(pos)
            rec = next(it)
        except StopIteration:
            return
        except Exception as e:  # transient network / stream error -> backoff + resume
            it = None  # re-establish and skip back to where we were
            fails += 1
            if fails > cfg.http_retries:
                log("source_give_up", level="error", source=spec.name,
                    error=f"{type(e).__name__}: {e}", after_retries=cfg.http_retries)
                raise GiveUp(spec.name) from e
            delay = backoff_delay(fails, cfg, rng)
            log("stream_retry", level="warn", source=spec.name, attempt=fails,
                position=pos, delay_s=round(delay, 2), error=f"{type(e).__name__}: {e}")
            sleep_fn(delay)
            continue
        fails = 0
        yield pos, rec
        pos += 1


# ---------------------------------------------------------------------------
# Shard writing: accumulate -> atomically publish -> register.


@dataclasses.dataclass
class ShardInfo:
    shard_id: str
    path: str
    bytes: int
    docs: int
    sha256: str


class ShardWriter:
    """Accumulates docs and publishes them as one `.jsonl.zst` shard atomically.

    Byte accounting is on *uncompressed* JSON, matching pipeline.yaml's
    raw_target_bytes (the disk-facing figure the backpressure math assumes).
    """

    def __init__(self, source: str, raw_dir: str | Path, target_bytes: int) -> None:
        self.source = source
        self.dir = Path(raw_dir) / source
        self.dir.mkdir(parents=True, exist_ok=True)
        self.target_bytes = target_bytes
        self.reset()

    def reset(self) -> None:
        self._lines: list[bytes] = []
        self._doc_ids: list[str] = []
        self.uncompressed = 0
        self.docs = 0

    def add(self, doc: dict) -> bool:
        """Buffer a doc. Returns True when the shard has reached target size."""
        line = (json.dumps(doc, ensure_ascii=False) + "\n").encode("utf-8")
        self._lines.append(line)
        self._doc_ids.append(doc["doc_id"])
        self.uncompressed += len(line)
        self.docs += 1
        return self.uncompressed >= self.target_bytes

    def publish(self) -> ShardInfo | None:
        """Write the buffered docs to disk atomically and return their ShardInfo.
        Returns None if empty. Does NOT touch the manifest."""
        if self.docs == 0:
            return None
        if zstd is None:  # pragma: no cover
            raise RuntimeError("zstandard is required to write shards")
        # Deterministic id: same docs -> same shard id -> idempotent re-register.
        shard_id = f"{self.source}-" + hashlib.sha1(
            "\n".join(self._doc_ids).encode("utf-8")).hexdigest()[:16]
        final = self.dir / f"{shard_id}.jsonl.zst"
        tmp = self.dir / f".{shard_id}.{os.getpid()}.tmp"
        blob = zstd.ZstdCompressor(level=10).compress(b"".join(self._lines))
        try:
            with open(tmp, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, final)          # atomic publish
            self._fsync_dir(self.dir)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return ShardInfo(
            shard_id=shard_id, path=str(final), bytes=self.uncompressed,
            docs=self.docs, sha256=hashlib.sha256(blob).hexdigest(),
        )

    @staticmethod
    def _fsync_dir(d: Path) -> None:
        try:
            fd = os.open(str(d), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:  # directory fsync unsupported on some FS (e.g. Windows)
            pass


def cursor_key(spec: SourceSpec, phase: int) -> str:
    """Cursors are per (source, phase).

    A synthetic generator can serve several phases (MathGenerator spans 1/3/4),
    and each phase consumes a different filtered subsequence. One shared cursor
    would make resuming phase 3 skip into phase 1's position."""
    return f"{spec.name}#p{phase}" if spec.kind == "synthetic" else spec.name


def _commit_shard(writer: ShardWriter, spec: SourceSpec, phase: int, m: Manifest,
                  n_read: int, log: Callable[..., None], split: str = "train") -> ShardInfo:
    """Publish to disk, register (idempotent), then advance the resume cursor.

    Order matters: the cursor advances last so a crash before it re-reads the
    same source records into an identical (idempotent) shard next time."""
    info = writer.publish()
    assert info is not None
    added = m.add_shard(info.shard_id, source=spec.name, phase=phase, path=info.path,
                        split=split, bytes_=info.bytes, docs=info.docs,
                        sha256=info.sha256, state=RAW)
    m.set_cursor(cursor_key(spec, phase), f"docs:{n_read}", n_read)
    log("shard_committed", source=spec.name, phase=phase, shard_id=info.shard_id,
        path=info.path, docs=info.docs, bytes=info.bytes, cursor=n_read,
        newly_registered=added)
    return info


# ---------------------------------------------------------------------------
# Collect one source.


def run_source(
    spec: SourceSpec,
    phase: int,
    m: Manifest,
    cfg: CollectorConfig,
    raw_dir: str | Path,
    log: Callable[..., None],
    *,
    once: bool = False,
    max_docs: int | None = None,
    split: str = "train",
    factory: Callable[[int], Iterator[dict]] | None = None,
    rng: random.Random | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    """Stream `spec` into RAW shards for `phase`. Returns docs written.

    Resumes from the manifest cursor. With `once=True` it produces at most one
    shard (rolls or exhausts, whichever first) then stops. `max_docs` caps the
    number of *written* docs for this call (smoke tests / bootstrap)."""
    rng = rng or random.Random(hash(spec.name) & 0xFFFFFFFF)
    factory = factory or make_factory(spec, phase)
    _, start = m.get_cursor(cursor_key(spec, phase))
    writer = ShardWriter(spec.name, raw_dir, cfg.raw_target_bytes)
    n_read = start
    written = 0
    log("source_start", source=spec.name, phase=phase, cursor=start, once=once)

    for pos, rec in iter_records(spec, start, cfg, log, factory, rng, sleep_fn):
        n_read = pos + 1
        doc = build_doc(spec, phase, rec)
        if doc is not None:
            rolled = writer.add(doc)
            written += 1
            if rolled:
                _commit_shard(writer, spec, phase, m, n_read, log, split)
                writer.reset()
                if once:
                    return written
            if max_docs is not None and written >= max_docs:
                break
    if writer.docs > 0:
        _commit_shard(writer, spec, phase, m, n_read, log, split)
    log("source_done", source=spec.name, phase=phase, docs_written=written, cursor=n_read)
    return written


# ---------------------------------------------------------------------------
# Source selection: smooth weighted round-robin (deterministic per phase).


class WeightedRR:
    """nginx-style smooth weighted round-robin. Deterministic given start state,
    and it never starves a positive-weight source the way modulo bucketing can."""

    def __init__(self, items: list[tuple[str, float]]) -> None:
        self.items = [(n, w) for n, w in items if w > 0]
        self.total = sum(w for _, w in self.items)
        self.current = {n: 0.0 for n, _ in self.items}

    def next(self) -> str | None:
        if not self.items:
            return None
        for n, w in self.items:
            self.current[n] += w
        best = max(self.items, key=lambda it: self.current[it[0]])[0]
        self.current[best] -= self.total
        return best


def sources_for_phase(sources: list[SourceSpec], phase: int) -> list[tuple[str, float]]:
    out = []
    for s in sources:
        w = s.weight.get(phase, 0.0)
        if phase in s.phases and w > 0:
            out.append((s.name, w))
    return sorted(out)  # sort -> deterministic RR ordering


# ---------------------------------------------------------------------------
# Service loop.


def serve(
    m: Manifest,
    fcfg: FlowConfig,
    cfg: CollectorConfig,
    sources: list[SourceSpec],
    raw_dir: str | Path,
    log: Callable[..., None],
    *,
    max_iterations: int | None = None,
    poll_seconds: float = 5.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    seed: int = 1234,
) -> None:
    """One shard per loop iteration so pause + phase re-pick stay responsive.

    ``once=True`` on ``run_source`` is load-bearing: without it a synthetic
    generator never returns, so collectors ignore raw-backlog pauses and never
    notice the trainer has moved to a later phase.
    """
    by_name = {s.name: s for s in sources}
    rng = random.Random(seed)
    last_pause_reason: str | None = None
    last_phase: int | None = None
    it = 0
    log("collector_boot", raw_dir=str(raw_dir), sources=len(sources))

    while max_iterations is None or it < max_iterations:
        it += 1
        phase = pick_target_phase(m, fcfg)
        if phase != last_phase:
            log("collector_target_phase", phase=phase, prev=last_phase)
            last_phase = phase

        pause = collector_should_pause(m, fcfg, phase=phase, disk_path=raw_dir)
        if pause:
            if pause.reason != last_pause_reason:  # log once per transition
                log("collector_pause", level="warn", phase=phase, reason=pause.reason)
                last_pause_reason = pause.reason
            sleep_fn(poll_seconds)
            continue
        if last_pause_reason is not None:
            log("collector_resume", phase=phase)
            last_pause_reason = None

        # Rebuild RR each tick from demand so expand/examples reweight live.
        demand = read_demand()
        base = sources_for_phase(sources, phase)
        task_types = {s.name: s.task_type for s in sources}
        weighted = apply_demand_weights(
            base, source_task_types=task_types, demand=demand, phase=phase,
        )
        rr = WeightedRR(weighted)
        name = rr.next()
        if name is None:
            log("no_source_for_phase", level="warn", phase=phase)
            sleep_fn(poll_seconds)
            continue
        if demand is not None and it % 20 == 1:
            acts = demand.actions_for(phase)
            if acts:
                log("demand_actuate", phase=phase, source=name, actions=list(acts),
                    effort=demand.effort_map().get(phase, 0.0),
                    reasons=list(demand.reasons)[:2])

        try:
            run_source(by_name[name], phase, m, cfg, raw_dir, log,
                       once=True, rng=rng, sleep_fn=sleep_fn)
        except GiveUp:
            continue  # move to the next source rather than crashing the container


# ---------------------------------------------------------------------------
# Bootstrap sampling for tokenizer training (Stage 5).


def bootstrap_sample(
    sources: list[SourceSpec],
    cfg: CollectorConfig,
    target_bytes: int,
    out_dir: str | Path,
    log: Callable[..., None],
    *,
    phases: range = range(N_PHASES),
    rng: random.Random | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    """One-shot stratified text sample across all phases -> plain JSONL in
    `out_dir`, roughly equal bytes per phase, mixed within a phase by weight.
    Registers nothing and uses no cursor. Returns total bytes written."""
    rng = rng or random.Random(0)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    per_phase = max(1, target_bytes // max(1, len(phases)))
    total = 0
    for phase in phases:
        srcs = sources_for_phase(sources, phase)
        wsum = sum(w for _, w in srcs)
        if not srcs:
            continue
        fpath = out / f"bootstrap_p{phase}.jsonl"
        with open(fpath, "w", encoding="utf-8") as f:
            for name, w in srcs:
                spec = next(s for s in sources if s.name == name)
                share = per_phase * (w / wsum)
                got = 0
                try:
                    for pos, rec in iter_records(spec, 0, cfg, log, make_factory(spec, phase),
                                                 rng, sleep_fn):
                        doc = build_doc(spec, phase, rec)
                        if doc is None:
                            continue
                        line = json.dumps(
                            {"text": doc["text"], "phase": phase, "source": name},
                            ensure_ascii=False) + "\n"
                        f.write(line)
                        n = len(line.encode("utf-8"))
                        got += n
                        total += n
                        if got >= share:
                            break
                except GiveUp:
                    pass
        log("bootstrap_phase_done", phase=phase, bytes_out=total)
    log("bootstrap_done", bytes_out=total, out=str(out))
    return total


# ---------------------------------------------------------------------------
# CLI.


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dottie collector")
    ap.add_argument("--once", action="store_true", help="collect one shard then exit")
    ap.add_argument("--source", default=None, help="restrict to a single source by name")
    ap.add_argument("--phase", type=int, default=None, help="override target phase")
    ap.add_argument("--max-docs", type=int, default=None, help="cap docs written this run")
    ap.add_argument("--sources", default=None, help="path to sources.yaml")
    ap.add_argument("--raw-dir", default=None, help="override AVA_RAW_DIR")
    ap.add_argument("--bootstrap-sample", action="store_true",
                    help="stratified sample across phases for tokenizer training")
    ap.add_argument("--target-bytes", type=int, default=64_000_000)
    ap.add_argument("--out", default=None, help="output dir for --bootstrap-sample")
    args = ap.parse_args(argv)

    log = make_logger(worker_id())
    cfg = CollectorConfig.load()
    sources = load_sources(args.sources)
    raw_dir = args.raw_dir or os.environ.get("AVA_RAW_DIR", "/raw")

    if args.bootstrap_sample:
        if not args.out:
            ap.error("--bootstrap-sample requires --out DIR")
        bootstrap_sample(sources, cfg, args.target_bytes, args.out, log)
        return 0

    fcfg = FlowConfig.load()
    with Manifest() as m:
        if args.once:
            if args.source:
                spec = next((s for s in sources if s.name == args.source), None)
                if spec is None:
                    ap.error(f"unknown source {args.source!r}")
                phase = args.phase if args.phase is not None else (
                    spec.phases[0] if spec.phases else 0)
            else:
                phase = args.phase if args.phase is not None else pick_target_phase(m, fcfg)
                names = sources_for_phase(sources, phase)
                if not names:
                    log("no_source_for_phase", level="error", phase=phase)
                    return 1
                spec = next(s for s in sources if s.name == names[0][0])
            try:
                run_source(spec, phase, m, cfg, raw_dir, log,
                           once=True, max_docs=args.max_docs)
            except GiveUp:
                log("once_give_up", level="error", source=spec.name)
                return 1
            return 0
        serve(m, fcfg, cfg, sources, raw_dir, log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
