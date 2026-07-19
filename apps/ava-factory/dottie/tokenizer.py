"""Byte-level BPE tokenizer, trained locally on our own corpus.

Trained here, not downloaded: huggingface.co is unreachable from the Windows
host, and the blueprint's "dottie-tokenizer" never existed in the first place.

The artifact is FROZEN once trained. Its sha256 is recorded in the manifest and
stamped into every packed shard; `Manifest.complete(tokenizer_sha=...)` rejects
a shard packed with any other tokenizer. Retraining the tokenizer invalidates
every packed shard, and the freeze gate makes that loud rather than silent.

Special token ids are pinned at 0..5 so a checkpoint and a tokenizer can never
disagree about which id is <|pad|>.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Iterator

SPECIALS = ["<|pad|>", "<|bos|>", "<|eos|>", "<|endofdoc|>", "<|user|>", "<|assistant|>"]
PAD_ID, BOS_ID, EOS_ID, ENDOFDOC_ID, USER_ID, ASSISTANT_ID = range(6)

DEFAULT_PATH = os.environ.get("AVA_TOKENIZER", "/state/tokenizer.json")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class DottieTokenizer:
    """Thin wrapper over `tokenizers.Tokenizer` with our frozen special ids."""

    def __init__(self, tok) -> None:
        self._tok = tok
        for i, s in enumerate(SPECIALS):
            got = tok.token_to_id(s)
            if got != i:
                raise ValueError(f"special {s!r} has id {got}, expected {i}")

    # -- io -----------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None = None) -> "DottieTokenizer":
        from tokenizers import Tokenizer

        p = Path(path or DEFAULT_PATH)
        if not p.exists():
            raise FileNotFoundError(
                f"no tokenizer at {p}. Train one first:\n"
                f"  python -m dottie.tokenizer train --preset nano --corpus <dir>"
            )
        return cls(Tokenizer.from_file(str(p)))

    @property
    def vocab_size(self) -> int:
        return self._tok.get_vocab_size()

    # -- api ----------------------------------------------------------------

    def encode(self, text: str) -> list[int]:
        return self._tok.encode(text).ids

    def decode(self, ids: list[int], *, skip_special: bool = True) -> str:
        """Decode ids to text.

        `skip_special=True` (the default) is what serving wants: no stray
        `<|endofdoc|>` in generated output. Round-tripping training text needs
        `skip_special=False`, because `<|user|>` / `<|assistant|>` are genuine
        tokens in the chat corpus, not decoration.
        """
        return self._tok.decode(ids, skip_special_tokens=skip_special)

    def encode_doc(self, text: str) -> list[int]:
        """Document tokens terminated by <|endofdoc|>, as packed into shards."""
        return self.encode(text) + [ENDOFDOC_ID]

    def concept_token(self, concept: str) -> int:
        """First token id of a concept string -- the reportability target.

        Used by the J-Space report loss and by the intervention engine, which is
        why it must be a real token id and not `sha256(concept) % vocab` (what
        the blueprint's mock harness did).
        """
        ids = self.encode(concept)
        if not ids:
            raise ValueError(f"concept {concept!r} encodes to nothing")
        return ids[0]


# ---------------------------------------------------------------------------
# training


def _iter_corpus(paths: Iterable[Path], max_bytes: int) -> Iterator[str]:
    """Stream text out of .jsonl / .jsonl.zst shards until max_bytes."""
    import zstandard as zstd

    seen = 0
    for p in paths:
        if seen >= max_bytes:
            return
        if p.suffix == ".zst":
            fh = zstd.ZstdDecompressor().stream_reader(open(p, "rb"))
            stream: Iterable[str] = io.TextIOWrapper(fh, encoding="utf-8")
        else:
            stream = open(p, encoding="utf-8")
        with stream as f:  # type: ignore[union-attr]
            for line in f:
                try:
                    text = json.loads(line)["text"]
                except (json.JSONDecodeError, KeyError):
                    continue
                seen += len(text)
                yield text
                if seen >= max_bytes:
                    return


def train(corpus_dir: str | Path, out_path: str | Path, vocab_size: int,
          max_bytes: int = 2_000_000_000) -> str:
    """Train byte-level BPE. Returns the artifact's sha256."""
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

    if vocab_size > 65535:
        raise ValueError(f"vocab_size {vocab_size} > 65535 breaks uint16 token packing")

    paths = sorted(Path(corpus_dir).rglob("*.jsonl*"))
    if not paths:
        raise FileNotFoundError(f"no .jsonl/.jsonl.zst shards under {corpus_dir}")

    tok = Tokenizer(models.BPE(unk_token=None))
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=vocab_size,
        special_tokens=SPECIALS,          # ids 0..5, in order
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        show_progress=False,
    )
    tok.train_from_iterator(_iter_corpus(paths, max_bytes), trainer=trainer)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tok.save(str(tmp))
    os.replace(tmp, out)
    return sha256_file(out)


def _cmd_train(args) -> int:
    from dottie.config import DottieConfig

    vocab = args.vocab or DottieConfig.load(args.preset).model.vocab_size
    sha = train(args.corpus, args.out, vocab, max_bytes=args.max_bytes)
    print(f"trained vocab={vocab} -> {args.out}")
    print(f"sha256={sha}")

    if args.freeze:
        from dottie.pipeline.manifest import Manifest

        with Manifest(args.db) as m:
            m.freeze_tokenizer(sha, vocab)
        print("frozen in manifest; packed shards are now bound to this tokenizer")
    return 0


def _cmd_check(args) -> int:
    t = DottieTokenizer.load(args.path)
    samples = ["The capital of France is Paris.", "def f(x):\n    return x * 2\n",
               "1 + 1 = 2", "<|user|>hi<|assistant|>hello"]
    ok = all(t.decode(t.encode(s), skip_special=False) == s for s in samples)
    total_chars = sum(len(s) for s in samples)
    total_toks = sum(len(t.encode(s)) for s in samples)
    print(f"vocab={t.vocab_size} roundtrip={'ok' if ok else 'FAILED'} "
          f"chars/token={total_chars/max(1,total_toks):.2f}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ava.tokenizer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    tr = sub.add_parser("train")
    tr.add_argument("--preset", default="nano")
    tr.add_argument("--vocab", type=int, default=None)
    tr.add_argument("--corpus", default=os.environ.get("AVA_RAW_DIR", "/raw"))
    tr.add_argument("--out", default=DEFAULT_PATH)
    tr.add_argument("--max-bytes", type=int, default=2_000_000_000)
    tr.add_argument("--freeze", action="store_true", help="record sha256 in the manifest")
    tr.add_argument("--db", default=None)
    tr.set_defaults(fn=_cmd_train)

    ck = sub.add_parser("check")
    ck.add_argument("--path", default=DEFAULT_PATH)
    ck.set_defaults(fn=_cmd_check)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
