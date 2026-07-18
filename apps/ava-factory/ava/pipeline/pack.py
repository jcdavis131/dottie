"""Tokenize + pack cleaned docs into contiguous uint16 token shards.

Output per split shard:
  * ``{shard}.bin``      — raw little-endian ``uint16`` token stream, docs
    concatenated with a ``<|endofdoc|>`` separator after each doc.
  * ``{shard}.idx.json`` — sidecar with exact per-doc offsets, the token count,
    and the tokenizer sha256 the shard was packed with.

uint16 is only valid because the frozen vocab is small (8k / 32k). We *assert*
``vocab_size <= 65535`` rather than assume it — a 64k+ vocab would silently wrap
token ids and corrupt every shard.

The tokenizer is the frozen one loaded from ``$AVA_TOKENIZER`` (default
``/state/tokenizer.json``). Its sha256 is computed here and threaded through to
``manifest.complete(tokenizer_sha=...)``, which raises ``TokenizerMismatch`` if
it disagrees with the frozen sha — that is the freeze gate, enforced by the
manifest, not re-implemented here.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

EOD_TOKEN = "<|endofdoc|>"
DEFAULT_TOKENIZER_PATH = "/state/tokenizer.json"
_UINT16_MAX = 0xFFFF

#: Sentinel concept_token_id for docs with no concept tag (all HF sources).
#: The J-Space reportability loss masks these out; see ava/jlosses.py.
UNTAGGED_CONCEPT = -1


class TokenizerNotFrozen(RuntimeError):
    """No frozen tokenizer file exists where packing expected one."""


@dataclass
class LoadedTokenizer:
    tokenizer: object  # tokenizers.Tokenizer
    sha256: str
    eod_id: int
    vocab_size: int


def _sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_tokenizer(path: str | Path | None = None) -> LoadedTokenizer:
    """Load and validate the frozen tokenizer.

    Raises :class:`TokenizerNotFrozen` with an operator-actionable message if the
    file is missing (Stage 5 tokenizer bootstrap has not run), a ``ValueError``
    if it lacks the ``<|endofdoc|>`` special token, and asserts the vocab fits in
    uint16.
    """
    p = Path(path or os.environ.get("AVA_TOKENIZER", DEFAULT_TOKENIZER_PATH))
    if not p.exists():
        raise TokenizerNotFrozen(
            f"no frozen tokenizer at {p}. Run the Stage 5 tokenizer bootstrap "
            f"(`python -m ava.tokenizer train`) and freeze it before packing."
        )
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(p))
    eod_id = tok.token_to_id(EOD_TOKEN)
    if eod_id is None:
        raise ValueError(f"tokenizer at {p} is missing the required {EOD_TOKEN!r} special token")
    vocab_size = tok.get_vocab_size()
    assert vocab_size <= _UINT16_MAX + 1, (
        f"vocab_size {vocab_size} exceeds uint16 range; packed shards would wrap. "
        f"uint16 packing requires vocab <= {_UINT16_MAX + 1}."
    )
    return LoadedTokenizer(tokenizer=tok, sha256=_sha256_file(p), eod_id=eod_id, vocab_size=vocab_size)


def pack_docs(docs: list[dict], lt: LoadedTokenizer) -> tuple[np.ndarray, dict]:
    """Tokenize ``docs`` into one uint16 array + an index sidecar dict.

    Each doc's own tokens occupy ``[start, end)`` in the array; a single
    ``<|endofdoc|>`` separator follows at index ``end`` (so the next doc begins
    at ``end + 1``). ``tokenizer.decode(arr[start:end])`` reconstructs the doc.

    idx sidecar: ``{"tokens": N, "tokenizer_sha": ..., "docs": [{doc_id, start,
    end, task_type, concept_token_id, phase}, ...]}``.
    """
    tok = lt.tokenizer
    stream: list[int] = []
    index: list[dict] = []

    for d in docs:
        ids = tok.encode(d["text"]).ids
        start = len(stream)
        stream.extend(ids)
        end = len(stream)
        stream.append(lt.eod_id)  # separator, not counted in [start, end)

        # Only synthetic docs carry a concept; HF records have `concept: null`.
        # `.get("concept", "")` returns None for an explicit null and blows up in
        # the tokenizer ("TextInputSequence must be str").
        #
        # UNTAGGED (-1) rather than eod_id: HF is most of the corpus, so mapping
        # every untagged doc onto a real token would teach the reportability loss
        # that the answer is almost always <|endofdoc|>. ava/jlosses.py masks -1.
        concept = d.get("concept") or ""
        concept_ids = tok.encode(concept).ids if concept else []
        concept_token_id = concept_ids[0] if concept_ids else UNTAGGED_CONCEPT

        index.append(
            {
                "doc_id": d["doc_id"],
                "start": start,
                "end": end,
                "task_type": d.get("task_type", ""),
                "concept_token_id": int(concept_token_id),
                "phase": d.get("phase", ""),
            }
        )

    arr = np.array(stream, dtype=np.uint16)
    if arr.size:
        assert int(arr.max()) <= _UINT16_MAX, "token id exceeds uint16 range"
    idx = {"tokens": int(arr.size), "tokenizer_sha": lt.sha256, "docs": index}
    return arr, idx


def idx_path_for(bin_path: str | Path) -> Path:
    p = Path(bin_path)
    if p.suffix == ".bin":
        return p.with_suffix(".idx.json")
    return Path(str(p) + ".idx.json")


def write_shard(arr: np.ndarray, idx: dict, bin_path: str | Path) -> tuple[Path, Path]:
    """Atomically write ``{shard}.bin`` and ``{shard}.idx.json``.

    Both files are written to ``.tmp`` siblings and ``os.replace``-d into place
    (bin first, then idx), so a crash mid-write never leaves a torn shard: a
    reader either sees the complete pair or neither. Callers must register the
    shard in the manifest only AFTER this returns.
    """
    bin_path = Path(bin_path)
    idx_path = idx_path_for(bin_path)
    bin_path.parent.mkdir(parents=True, exist_ok=True)

    bin_tmp = bin_path.with_suffix(bin_path.suffix + ".tmp")
    idx_tmp = Path(str(idx_path) + ".tmp")

    with open(bin_tmp, "wb") as f:
        f.write(arr.tobytes())
        f.flush()
        os.fsync(f.fileno())
    with open(idx_tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f)
        f.flush()
        os.fsync(f.fileno())

    os.replace(bin_tmp, bin_path)
    os.replace(idx_tmp, idx_path)
    return bin_path, idx_path


def read_shard(bin_path: str | Path) -> tuple[np.ndarray, dict]:
    """Load a packed shard back as ``(uint16 array, idx dict)`` — for tests/tools."""
    bin_path = Path(bin_path)
    arr = np.fromfile(str(bin_path), dtype=np.uint16)
    with open(idx_path_for(bin_path), encoding="utf-8") as f:
        idx = json.load(f)
    return arr, idx
