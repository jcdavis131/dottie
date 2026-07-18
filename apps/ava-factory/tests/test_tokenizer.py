"""Tokenizer contract tests.

The load-bearing properties: special ids are pinned (a checkpoint and a
tokenizer must never disagree about which id is <|pad|>), round-trip is exact,
and the frozen artifact is bound to the manifest so packed shards cannot be
mixed across tokenizers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ava.pipeline.manifest import Manifest, TokenizerMismatch
from ava.tokenizer import (
    ASSISTANT_ID,
    ENDOFDOC_ID,
    PAD_ID,
    SPECIALS,
    AvaTokenizer,
    sha256_file,
    train,
)

_CORPUS = [
    "The capital of France is Paris, and its currency is the Euro.",
    "A spider has eight legs. An ant has six legs.",
    "def add(a, b):\n    return a + b\n",
    "1 + 1 = 2. 12 * 12 = 144.",
    "<|user|>What is 2+2?<|assistant|>It is 4.",
    "Modus ponens: if A then B; A; therefore B.",
] * 60


@pytest.fixture(scope="module")
def corpus_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("corpus")
    with open(d / "shard.jsonl", "w", encoding="utf-8") as f:
        for t in _CORPUS:
            f.write(json.dumps({"text": t}) + "\n")
    return d


@pytest.fixture(scope="module")
def trained(tmp_path_factory, corpus_dir) -> tuple[Path, str]:
    out = tmp_path_factory.mktemp("tok") / "tokenizer.json"
    sha = train(corpus_dir, out, vocab_size=512)
    return out, sha


def test_special_token_ids_are_pinned(trained):
    path, _ = trained
    t = AvaTokenizer.load(path)
    assert PAD_ID == 0 and ENDOFDOC_ID == 3 and ASSISTANT_ID == 5
    assert len(SPECIALS) == 6


def test_roundtrip_is_exact(trained):
    """Chat markers are real tokens, so fidelity requires skip_special=False."""
    path, _ = trained
    t = AvaTokenizer.load(path)
    for s in set(_CORPUS):
        assert t.decode(t.encode(s), skip_special=False) == s


def test_decode_skips_specials_by_default(trained):
    """Serving must not emit <|endofdoc|> into generated text."""
    path, _ = trained
    t = AvaTokenizer.load(path)
    ids = t.encode_doc("hello world")
    assert "<|endofdoc|>" not in t.decode(ids)
    assert "<|endofdoc|>" in t.decode(ids, skip_special=False)


def test_encode_doc_terminates_with_endofdoc(trained):
    path, _ = trained
    t = AvaTokenizer.load(path)
    ids = t.encode_doc("hello world")
    assert ids[-1] == ENDOFDOC_ID
    assert ids[:-1] == t.encode("hello world")


def test_concept_token_is_a_real_id(trained):
    """The blueprint used sha256(concept) % vocab -- a random direction with no
    relationship to the concept. This must be a real token."""
    path, _ = trained
    t = AvaTokenizer.load(path)
    tid = t.concept_token("spider")
    assert 0 <= tid < t.vocab_size
    assert t.concept_token("spider") == tid          # deterministic
    assert t.concept_token("spider") != t.concept_token("france")


def test_ids_fit_uint16(trained):
    path, _ = trained
    t = AvaTokenizer.load(path)
    assert t.vocab_size <= 65535
    assert max(t.encode(" ".join(set(_CORPUS)))) < 65536


def test_vocab_over_uint16_rejected(tmp_path, corpus_dir):
    with pytest.raises(ValueError, match="uint16"):
        train(corpus_dir, tmp_path / "x.json", vocab_size=70000)


def test_training_is_atomic_no_tmp_left(trained):
    path, _ = trained
    assert path.exists()
    assert not path.with_suffix(".tmp").exists()


def test_missing_tokenizer_error_names_the_fix(tmp_path):
    with pytest.raises(FileNotFoundError, match="python -m ava.tokenizer train"):
        AvaTokenizer.load(tmp_path / "nope.json")


def test_sha_is_stable_and_binds_the_manifest(tmp_path, trained):
    path, sha = trained
    assert sha == sha256_file(path)

    with Manifest(str(tmp_path / "m.db")) as m:
        m.freeze_tokenizer(sha, 512)
        assert m.tokenizer_sha() == sha
        m.add_shard("s1", source="x", phase=0, path="/raw/s1")
        s = m.claim("curate", by="w")

        with pytest.raises(TokenizerMismatch, match="not hash-compatible"):
            m.complete(s.id, by="w", tokens=10, tokenizer_sha="deadbeef")

        m.complete(s.id, by="w", tokens=10, tokenizer_sha=sha)  # correct one is accepted


def test_compression_ratio_is_sane(trained):
    """Not a quality bar (a 512-vocab toy tokenizer on 6 sentences is not the
    production artifact) -- just proof BPE merged anything at all."""
    path, _ = trained
    t = AvaTokenizer.load(path)
    text = " ".join(set(_CORPUS))
    ratio = len(text) / len(t.encode(text))
    assert ratio > 1.5, f"chars/token {ratio:.2f} -- BPE learned no merges"
