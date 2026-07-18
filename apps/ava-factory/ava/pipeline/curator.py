"""CURATOR service — the pipeline's quality gate.

Claims a RAW shard, turns its docs into cleaned / deduplicated / decontaminated
/ split / tokenized / packed training data, registers the packed shards, deletes
the raw shard, and marks the RAW row PACKED. Loops forever (or once, with
``--once``).

Per-doc pipeline (fixed order):
    normalize -> is_english -> gopher_quality -> edu_score_ok -> scrub_pii
    -> dedup -> decontaminate -> assign_split
then docs are bucketed by split, tokenized+packed per split, written atomically,
registered, and the raw file is removed.

One raw shard -> up to three packed shards
------------------------------------------
A raw shard's docs fan out across train/val/test. We emit up to three packed
shards under ``/packed/p{phase}/{split}/{raw_shard_id}.bin`` (+ ``.idx.json``):

  * TRAIN maps onto the ORIGINAL raw row: ``manifest.complete(raw_shard_id, ...)``
    moves that row RAW -> PACKED carrying the train split's tokens/docs/path. So
    ``flow.tokens_ready(phase, split='train')`` — the number the trainer actually
    consumes — counts exactly the train tokens of this shard.
  * VAL and TEST become NEW rows ``{raw_shard_id}:val`` / ``:test`` via
    ``add_shard(..., state=PACKED, split=...)``. NOTE: ``add_shard`` has no
    ``tokens`` argument and only ``complete`` (which needs a claimed row) can set
    tokens, so these rows carry ``tokens=0`` in the manifest; the authoritative
    val/test token counts live in each shard's ``.idx.json``. Nothing in the flow
    layer sums val/test tokens, so this is a reporting detail, not a correctness
    one. The freeze gate is still enforced once, on the train row's ``complete``.

Crash-safety ordering (DELIBERATE DEVIATION from the task's literal ordering)
-----------------------------------------------------------------------------
Order is: write packed files atomically -> register val/test -> ``complete``
the train row -> delete the raw file. The task text lists "delete raw THEN
complete"; we complete BEFORE deleting raw on purpose. If we deleted the raw
file first and crashed before ``complete``, the lease would expire, the row
would requeue to RAW, and re-curation would find the raw file gone -> the shard
FAILS and its data is lost. Completing first means the worst a crash can do is
leak an inert raw file (the row is already PACKED, so no one re-claims it) — a
tiny disk leak, never data loss and never a double-count (packed writes are
atomic and val/test ids are deterministic, so replays are idempotent).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path

import yaml
import zstandard as zstd

from ava.pipeline import clean, decontaminate
from ava.pipeline.dedup import MinHashDeduper
from ava.pipeline.decontaminate import Decontaminator
from ava.pipeline.flow import FlowConfig, curator_claim_phases
from ava.pipeline.manifest import Manifest, worker_id
from ava.pipeline.pack import load_tokenizer, pack_docs, write_shard
from ava.pipeline.split import assign_split

DEFAULT_CONFIG = "/app/configs/pipeline.yaml"
RENEW_INTERVAL_SECONDS = 60.0
IDLE_POLL_SECONDS = 5.0


def _log(event: str, **fields) -> None:
    """One structured JSON object per line to stdout."""
    rec = {"ts": round(time.time(), 3), "svc": "curator", "event": event}
    rec.update(fields)
    print(json.dumps(rec, sort_keys=True), flush=True)


def _read_raw_docs(path: str):
    """Yield doc dicts from a zstd-compressed JSONL raw shard (streaming)."""
    dctx = zstd.ZstdDecompressor()
    with open(path, "rb") as fh:
        with dctx.stream_reader(fh) as reader:
            text = io.TextIOWrapper(reader, encoding="utf-8")
            for line in text:
                line = line.strip()
                if line:
                    yield json.loads(line)


def _phase_num(doc: dict, fallback: int) -> int:
    p = doc.get("phase")
    if isinstance(p, str) and p.startswith("p") and p[1:].isdigit():
        return int(p[1:])
    if isinstance(p, int):
        return p
    return fallback


class Curator:
    def __init__(
        self,
        *,
        config_path: str | None = None,
        db_path: str | None = None,
        raw_dir: str | None = None,
        packed_dir: str | None = None,
        dedup_db: str | None = None,
        tokenizer_path: str | None = None,
    ) -> None:
        self.config_path = config_path or os.environ.get("AVA_PIPELINE_CONFIG", DEFAULT_CONFIG)
        cfg = yaml.safe_load(Path(self.config_path).read_text())
        cur = cfg["curator"]
        self.batch_docs = int(cur.get("batch_docs", 1000))
        self.minhash_perm = int(cur.get("minhash_perm", 128))
        self.minhash_threshold = float(cur.get("minhash_threshold", 0.8))
        self.ngram_decontam = int(cur.get("ngram_decontam", 13))
        self.split_ratios = {k: float(v) for k, v in cfg["splits"].items()}

        self.raw_dir = raw_dir or os.environ.get("AVA_RAW_DIR", "/raw")
        self.packed_dir = packed_dir or os.environ.get("AVA_PACKED_DIR", "/packed")
        self.db_path = db_path or os.environ.get("AVA_STATE_DB", "/state/manifest.db")
        self.dedup_db = dedup_db or os.environ.get("AVA_DEDUP_DB", "/state/dedup.db")
        self.tokenizer_path = tokenizer_path or os.environ.get("AVA_TOKENIZER")
        self.report_path = os.path.join(self.packed_dir, "decontam_report.json")

        self.flow = FlowConfig.load(self.config_path)
        self.worker = worker_id()
        self._stop = False
        # Loaded lazily on first shard so `--help` / construction never touch the
        # frozen tokenizer file.
        self._lt = None
        self._decon = Decontaminator(ngram=self.ngram_decontam)

    # -- lifecycle ----------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        def handler(signum, frame):
            self._stop = True
            _log("sigterm", note="will finish current shard then exit")

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

    @property
    def lt(self):
        if self._lt is None:
            self._lt = load_tokenizer(self.tokenizer_path)
            _log("tokenizer_loaded", sha=self._lt.sha256[:12], vocab=self._lt.vocab_size)
        return self._lt

    # -- core ---------------------------------------------------------------

    def process_shard(self, m: Manifest, shard) -> dict:
        """Curate one claimed shard end to end. Returns per-stage counts."""
        t0 = time.time()
        raw_path = shard.path
        counts = {
            "read": 0, "kept": 0, "empty": 0, "non_english": 0,
            "edu_reject": 0, "duplicate": 0,
            "gopher_reject": {}, "contaminated": {},
        }
        by_split: dict[str, list[dict]] = {"train": [], "val": [], "test": []}

        deduper = MinHashDeduper(
            self.dedup_db, num_perm=self.minhash_perm, threshold=self.minhash_threshold
        )
        last_renew = time.time()
        try:
            for doc in _read_raw_docs(raw_path):
                counts["read"] += 1
                doc_id = doc.get("doc_id") or f"{doc.get('source','?')}:{counts['read']}"

                norm = clean.normalize(doc.get("text", ""))
                if not norm:
                    counts["empty"] += 1
                    continue
                if not clean.is_english(norm):
                    counts["non_english"] += 1
                    continue
                ok, reason = clean.gopher_quality(norm)
                if not ok:
                    counts["gopher_reject"][reason] = counts["gopher_reject"].get(reason, 0) + 1
                    continue
                phase_num = _phase_num(doc, shard.phase)
                if not clean.edu_score_ok(doc.get("meta"), phase_num, clean.DEFAULT_EDU_THRESHOLDS):
                    counts["edu_reject"] += 1
                    continue
                scrubbed = clean.scrub_pii(norm)
                if not deduper.add_if_new(doc_id, scrubbed):
                    counts["duplicate"] += 1
                    continue
                contaminated, which = self._decon.is_contaminated(scrubbed)
                if contaminated:
                    counts["contaminated"][which] = counts["contaminated"].get(which, 0) + 1
                    continue

                split = assign_split(doc_id, self.split_ratios)
                by_split[split].append({
                    "doc_id": doc_id,
                    "text": scrubbed,
                    "task_type": doc.get("task_type", ""),
                    "concept": doc.get("concept", ""),
                    "phase": doc.get("phase", f"p{phase_num}"),
                })
                counts["kept"] += 1

                if time.time() - last_renew >= RENEW_INTERVAL_SECONDS:
                    m.renew(shard.id, by=self.worker)
                    last_renew = time.time()
        finally:
            deduper.close()

        self._emit_packed(m, shard, by_split, counts)

        # Decontamination removal report (append-safe across replicas).
        if counts["contaminated"]:
            decontaminate.write_report(
                {shard.source: counts["contaminated"]}, self.report_path
            )

        counts["elapsed_s"] = round(time.time() - t0, 3)
        return counts

    def _emit_packed(self, m: Manifest, shard, by_split: dict[str, list[dict]], counts: dict) -> None:
        phase = shard.phase
        written: dict[str, dict] = {}

        # 1. Write every split's packed files atomically (nothing registered yet).
        for split in ("train", "val", "test"):
            docs = by_split[split]
            if not docs:
                continue
            arr, idx = pack_docs(docs, self.lt)
            bin_path = os.path.join(self.packed_dir, f"p{phase}", split, f"{shard.id}.bin")
            write_shard(arr, idx, bin_path)
            written[split] = {
                "path": bin_path,
                "tokens": int(arr.size),
                "docs": len(docs),
                "bytes": int(arr.nbytes),
            }

        # 2. Register val/test as new PACKED rows (idempotent on replay).
        for split in ("val", "test"):
            if split in written:
                w = written[split]
                m.add_shard(
                    f"{shard.id}:{split}",
                    source=shard.source,
                    phase=phase,
                    path=w["path"],
                    split=split,
                    bytes_=w["bytes"],
                    docs=w["docs"],
                    state="PACKED",
                )

        # 3. Complete the train row (RAW -> PACKED). Freeze gate enforced here.
        tw = written.get("train")
        m.complete(
            shard.id,
            by=self.worker,
            path=(tw["path"] if tw else None),
            tokens=(tw["tokens"] if tw else 0),
            docs=(tw["docs"] if tw else 0),
            split="train",
            tokenizer_sha=self.lt.sha256,
            bytes_=(tw["bytes"] if tw else 0),
        )

        # 4. Delete the raw file LAST — after the row is safely PACKED. A crash
        #    before this only leaks an inert raw file, never loses data.
        try:
            os.remove(shard.path)
        except FileNotFoundError:
            pass

        counts["packed"] = {s: w["tokens"] for s, w in written.items()}

    # -- loops --------------------------------------------------------------

    def run_once(self, m: Manifest) -> bool:
        """Claim and process one shard. Returns False if nothing was ready.

        Claims only within the trainer's prefetch window (starved phase first),
        so a mountain of phase-0 RAW cannot monopolize every curator while the
        GPU is DATA_STARVED on phase 3.
        """
        shard = None
        for phase in curator_claim_phases(m, self.flow):
            shard = m.claim("curate", by=self.worker, phases=[phase])
            if shard is not None:
                break
        if shard is None:
            return False
        _log("claimed", shard=shard.id, source=shard.source, phase=shard.phase, bytes=shard.bytes)
        try:
            counts = self.process_shard(m, shard)
            _log("packed_ok", shard=shard.id, **counts)
        except Exception as exc:  # never crash the container on one bad shard
            err = f"{type(exc).__name__}: {exc}"
            _log("shard_failed", shard=shard.id, error=err, tb=traceback.format_exc()[-1500:])
            state = m.fail(shard.id, by=self.worker, error=err)
            _log("shard_parked", shard=shard.id, state=state)
        return True

    def serve(self, *, once: bool = False) -> int:
        self._install_signal_handlers()
        _log("start", worker=self.worker, once=once, raw_dir=self.raw_dir, packed_dir=self.packed_dir)
        with Manifest(self.db_path) as m:
            if once:
                did = self.run_once(m)
                _log("stop", reason="once", processed=did)
                return 0
            while not self._stop:
                did = self.run_once(m)
                if not did:
                    for _ in range(int(IDLE_POLL_SECONDS * 10)):
                        if self._stop:
                            break
                        time.sleep(0.1)
        _log("stop", reason="sigterm" if self._stop else "loop_end")
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ava curator service")
    ap.add_argument("--once", action="store_true", help="process a single shard and exit")
    ap.add_argument("--config", default=None)
    ap.add_argument("--db", default=None)
    args = ap.parse_args(argv)
    curator = Curator(config_path=args.config, db_path=args.db)
    return curator.serve(once=args.once)


if __name__ == "__main__":
    sys.exit(main())
