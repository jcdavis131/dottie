"""Shared contract for all Ava synthetic data generators.

Hard rules enforced here (see specs/02_data_generation.md for the long
version):
  * zero network access, ever;
  * every generator owns a PRIVATE ``random.Random(seed)`` instance -- the
    global ``random`` module must never be touched;
  * output is byte-identical across runs given the same seed;
  * every yielded doc has exactly the six keys in ``DOC_KEYS``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
from abc import ABC, abstractmethod
from typing import Iterable, Iterator

import zstandard as zstd

DOC_KEYS = frozenset({"doc_id", "text", "task_type", "concept", "phase", "source"})
VALID_TASK_TYPES = frozenset({"automatic", "deliberate", "safety", "temporal"})
VALID_PHASES = frozenset({"p0", "p1", "p2", "p3", "p4", "p5"})


def sha1_short(text: str) -> str:
    """First 16 hex chars of the sha1 of ``text`` (UTF-8 encoded)."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def make_doc_id(source: str, text: str) -> str:
    return f"{source}:{sha1_short(text)}"


def make_doc(text: str, task_type: str, concept: str, phase: str, source: str) -> dict:
    """Build a schema-conformant doc dict. Fails loudly on bad input so a
    generator bug surfaces immediately rather than poisoning a shard."""
    if not text:
        raise ValueError("doc text must be non-empty")
    if task_type not in VALID_TASK_TYPES:
        raise ValueError(f"bad task_type: {task_type!r}")
    if not concept:
        raise ValueError("concept must be non-empty")
    if phase not in VALID_PHASES:
        raise ValueError(f"bad phase: {phase!r}")
    if not source:
        raise ValueError("source must be non-empty")
    return {
        "doc_id": make_doc_id(source, text),
        "text": text,
        "task_type": task_type,
        "concept": concept,
        "phase": phase,
        "source": source,
    }


def validate_doc(doc: dict, allowed_phases: Iterable[int] | None = None) -> None:
    """Raise AssertionError on any schema violation. Used by generators
    internally (via write_shards) and by tests."""
    keys = set(doc.keys())
    assert keys == DOC_KEYS, f"doc has wrong keys: {sorted(keys)}"
    for k in DOC_KEYS:
        v = doc[k]
        assert isinstance(v, str) and v, f"key {k!r} must be a non-empty str, got {v!r}"
    assert doc["task_type"] in VALID_TASK_TYPES, f"bad task_type: {doc['task_type']!r}"
    assert doc["phase"] in VALID_PHASES, f"bad phase: {doc['phase']!r}"
    expected_id = make_doc_id(doc["source"], doc["text"])
    assert doc["doc_id"] == expected_id, f"doc_id mismatch: {doc['doc_id']!r} != {expected_id!r}"
    if allowed_phases is not None:
        phase_num = int(doc["phase"][1:])
        assert phase_num in allowed_phases, (
            f"phase {doc['phase']!r} not in generator's declared phases {sorted(allowed_phases)}"
        )


class Generator(ABC):
    """Base class for every synthetic data generator.

    Subclasses set the class attributes ``name`` (short slug, e.g. "logic")
    and ``phases`` (tuple of the curriculum phase numbers the generator can
    emit, e.g. ``(0,)`` or ``(2, 4)``), and implement ``generate``.
    """

    name: str = ""
    phases: tuple[int, ...] = ()

    def __init__(self, seed: int):
        self.seed = seed
        self.rng = random.Random(seed)  # private instance only; never touch the global random module

    @abstractmethod
    def generate(self, target_bytes: int) -> Iterator[dict]:
        """Yield doc dicts (schema per DOC_KEYS) until roughly
        ``target_bytes`` of serialized text has been produced. Generators
        must stream -- never materialize the whole corpus in memory."""
        raise NotImplementedError

    def doc(self, text: str, task_type: str, concept: str, phase: int, source: str) -> dict:
        """Convenience wrapper: build a doc with an int phase number,
        converted to the "pN" string form, and validate it against this
        generator's declared phases."""
        phase_str = f"p{phase}"
        d = make_doc(text=text, task_type=task_type, concept=concept, phase=phase_str, source=source)
        validate_doc(d, allowed_phases=self.phases)
        return d


def write_shards(gen: Generator, out_dir: str, target_mb: float, shard_mb: float = 8) -> dict:
    """Drive ``gen.generate()`` and write zstd-compressed JSONL shards.

    Files are named ``{out_dir}/{gen.name}_{shard:04d}.jsonl.zst``. Each
    shard's uncompressed payload is UTF-8 JSONL, one doc per line, produced
    via ``json.dumps(doc, sort_keys=True, ensure_ascii=False)`` for
    byte-determinism. Stops once cumulative *uncompressed* text bytes >=
    target_mb * 2**20.

    Returns ``{"files": [...], "bytes": int, "docs": int, "sha256": hex}``
    where "bytes" is the uncompressed text volume produced and "sha256" is
    the sha256 of all shard files' actual on-disk bytes, concatenated in
    filename order.
    """
    os.makedirs(out_dir, exist_ok=True)
    target_bytes = int(target_mb * (1024 ** 2))
    shard_bytes_limit = int(shard_mb * (1024 ** 2))

    files: list[str] = []
    total_bytes = 0
    total_docs = 0
    shard_idx = 0
    buf_parts: list[str] = []
    buf_bytes = 0

    def flush() -> None:
        nonlocal shard_idx, buf_parts, buf_bytes
        if not buf_parts:
            return
        fname = f"{gen.name}_{shard_idx:04d}.jsonl.zst"
        fpath = os.path.join(out_dir, fname)
        raw = "".join(buf_parts).encode("utf-8")
        cctx = zstd.ZstdCompressor(level=19)
        compressed = cctx.compress(raw)
        with open(fpath, "wb") as f:
            f.write(compressed)
        files.append(fname)
        shard_idx += 1
        buf_parts = []
        buf_bytes = 0

    for d in gen.generate(target_bytes):
        validate_doc(d, allowed_phases=gen.phases)
        line = json.dumps(d, sort_keys=True, ensure_ascii=False) + "\n"
        line_bytes = len(line.encode("utf-8"))
        buf_parts.append(line)
        buf_bytes += line_bytes
        total_bytes += line_bytes
        total_docs += 1
        if buf_bytes >= shard_bytes_limit:
            flush()
        if total_bytes >= target_bytes:
            break
    flush()

    h = hashlib.sha256()
    for fname in files:  # already in creation order == filename sort order
        with open(os.path.join(out_dir, fname), "rb") as f:
            h.update(f.read())

    return {"files": files, "bytes": total_bytes, "docs": total_docs, "sha256": h.hexdigest()}


def read_shards(out_dir: str, files: Iterable[str] | None = None) -> Iterator[dict]:
    """Read back docs from zstd JSONL shards written by write_shards. Handy
    for tests and downstream tooling."""
    if files is None:
        files = sorted(f for f in os.listdir(out_dir) if f.endswith(".jsonl.zst"))
    dctx = zstd.ZstdDecompressor()
    for fname in files:
        with open(os.path.join(out_dir, fname), "rb") as f:
            raw = dctx.decompress(f.read())
        for line in raw.decode("utf-8").splitlines():
            if line:
                yield json.loads(line)


def run_cli(generator_cls: type[Generator]) -> None:
    """Shared CLI entrypoint for `python -m ava.datagen.<mod> --seed S --out DIR --mb N`."""
    parser = argparse.ArgumentParser(description=f"Run the {generator_cls.__name__} data generator.")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", type=str, required=True)
    parser.add_argument("--mb", type=float, required=True)
    parser.add_argument("--shard-mb", type=float, default=8.0)
    args = parser.parse_args()

    gen = generator_cls(seed=args.seed)
    result = write_shards(gen, args.out, args.mb, shard_mb=args.shard_mb)
    print(json.dumps(result, sort_keys=True))
