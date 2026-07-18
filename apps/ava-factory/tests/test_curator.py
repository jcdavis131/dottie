"""Curator test suite — proves the quality gate actually gates.

Grouped by stage: clean, dedup, decontaminate, split, pack, then an end-to-end
`--once` run. The dedup and concurrency tests use a real on-disk SQLite DB (not
mocks) because cross-process safety is precisely the property under test.
"""

from __future__ import annotations

import json
import random
import threading
from pathlib import Path

import numpy as np
import pytest
import zstandard as zstd

from ava.pipeline import clean
from ava.pipeline.dedup import MinHashDeduper, exact_hash
from ava.pipeline.decontaminate import Decontaminator, write_report
from ava.pipeline.split import assign_split
from ava.pipeline import pack
from ava.pipeline.manifest import Manifest, PACKED, TokenizerMismatch, worker_id
from evals.eval_sets import all_eval_texts, EVAL_SETS

# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------

# A pool of distinct English sentences, used to synthesize mutually-distinct
# English documents that survive the cleaning heuristics.
_SENTENCES = [
    "The quick brown fox jumps over the lazy dog every single morning.",
    "Scientists have discovered a new species of frog in the rainforest.",
    "The committee agreed that the proposal should be revised before the vote.",
    "A gentle rain fell over the valley as the sun began to set slowly.",
    "Engineers built a bridge that could withstand the strongest of storms.",
    "The children played in the park until the streetlights finally came on.",
    "Economists warned that inflation could rise sharply over the next year.",
    "She carefully painted the old fence a bright and cheerful shade of blue.",
    "The library was quiet except for the soft turning of ancient pages.",
    "Farmers harvested the wheat before the first heavy frost of the season.",
    "The orchestra tuned their instruments as the audience took their seats.",
    "A curious cat watched the birds gather near the edge of the pond.",
    "The professor explained how the theory changed our view of the universe.",
    "Travelers crossed the mountains in search of a warmer place to live.",
    "The bakery filled the whole street with the smell of fresh warm bread.",
    "A team of doctors worked through the night to save the injured patient.",
    "The river carved a deep canyon through the rock over many centuries.",
    "Students gathered in the hall to hear the results of the competition.",
    "The old clock in the tower still kept perfect time after many years.",
    "A soft breeze carried the scent of flowers across the open meadow.",
    "The captain steered the ship carefully through the narrow rocky channel.",
    "Workers repaired the road that had been damaged by the recent flood.",
    "The artist sketched the city skyline from the roof of a tall building.",
    "A flock of geese flew south as the days grew shorter and colder.",
    "The chef prepared a wonderful meal using only fresh local ingredients.",
    "Historians debated the true cause of the ancient empire's sudden fall.",
    "The garden bloomed with roses and tulips in the warm spring sunshine.",
    "A young inventor built a small machine that could sort coins by size.",
    "The train rolled slowly into the station as the passengers stood to leave.",
    "Volunteers cleaned the beach and collected several bags of plastic waste.",
    "The mountain climbers reached the summit just as the clouds rolled in.",
    "A wise old owl watched the forest from its perch high in the oak tree.",
    "The market was crowded with people buying fruit and fresh vegetables.",
    "Researchers measured the temperature of the ocean at many different depths.",
    "The dancers moved gracefully across the stage under the bright lights.",
    "A small boat drifted quietly along the calm surface of the wide lake.",
    "The teacher wrote the difficult problem on the board and asked for answers.",
    "Birds built their nests in the tall trees along the edge of the river.",
    "The company announced that it would open three new offices next year.",
    "A gentle giant of a dog guarded the sleeping baby through the long night.",
]


def make_english_doc(rng: random.Random, n_sentences: int = 8) -> str:
    return " ".join(rng.sample(_SENTENCES, n_sentences))


@pytest.fixture(scope="module")
def tiny_tokenizer(tmp_path_factory) -> Path:
    """Train a throwaway ByteLevel BPE (vocab 512) with <|endofdoc|> and save it.

    ByteLevel guarantees exact decode round-trips, which the pack test relies on.
    Independent of Stage 5.
    """
    from tokenizers import Tokenizer, models, trainers, pre_tokenizers, decoders

    tok = Tokenizer(models.BPE())
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=512,
        special_tokens=[pack.EOD_TOKEN],
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        show_progress=False,
    )
    corpus = _SENTENCES * 20
    tok.train_from_iterator(corpus, trainer=trainer)

    out = tmp_path_factory.mktemp("tok") / "tokenizer.json"
    tok.save(str(out))
    return out


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------

def test_normalize_idempotent_and_collapses():
    raw = "Hello\x00 \t world\r\n\n\n\nnext   line   \n"
    out = clean.normalize(raw)
    assert "\x00" not in out and "\r" not in out
    assert "\n\n\n" not in out  # 3+ blank lines collapsed
    assert clean.normalize(out) == out  # idempotent


def test_is_english_accepts_english_rejects_cjk():
    assert clean.is_english("The cat sat on the mat and looked at the bright moon.")
    assert not clean.is_english("これは日本語の文章であり英語ではありません")
    assert not clean.is_english("这是一段中文文本而不是英文文本内容")


def test_gopher_accepts_good_rejects_bad():
    good = " ".join(_SENTENCES[:8])
    ok, reason = clean.gopher_quality(good)
    assert ok, reason

    ok, reason = clean.gopher_quality("Too short a document indeed.")
    assert not ok and reason == "too_short"

    # A doc dominated by bullets (real words, so mean word length stays in
    # range and the bullet rule is what trips).
    bullets = "\n".join(
        "- these sentences that describe wonderful things and passing ordinary matters"
        for _ in range(60)
    )
    ok, reason = clean.gopher_quality(bullets)
    assert not ok and reason == "bullet_lines"


def test_edu_score_thresholds():
    assert clean.edu_score_ok({"score": 4.6}, 5, {2: 2.0, 5: 4.5})
    assert not clean.edu_score_ok({"score": 3.0}, 5, {2: 2.0, 5: 4.5})
    assert clean.edu_score_ok({}, 5, {2: 2.0, 5: 4.5})       # missing score -> pass
    assert clean.edu_score_ok({"score": 0.0}, 0, {2: 2.0})   # phase with no threshold -> pass


def test_scrub_pii_redacts_but_preserves_code():
    text = (
        "Email me at john.doe@example.com or call 415-555-0199. "
        "The box at 192.168.1.100 uses key AKIAIOSFODNN7EXAMPLE. "
        "In code, x = 0xDEADBEEF is just a constant."
    )
    out = clean.scrub_pii(text)
    assert "<|email|>" in out
    assert "<|phone|>" in out
    assert "<|ip|>" in out
    assert "<|key|>" in out
    assert "john.doe@example.com" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    # Code/math literal must survive untouched.
    assert "0xDEADBEEF" in out


def test_scrub_pii_leaves_long_words_alone():
    # A long plain word has no digits -> not a base64 secret.
    text = "antidisestablishmentarianism is a very long ordinary english word here"
    assert clean.scrub_pii(text) == text


# ---------------------------------------------------------------------------
# dedup
# ---------------------------------------------------------------------------

_DWORDS = [f"word{i:03d}" for i in range(400)]


def _rand_doc(rng: random.Random, n: int = 120) -> str:
    return " ".join(rng.choice(_DWORDS) for _ in range(n))


def test_exact_hash_normalizes():
    assert exact_hash("hello   world") == exact_hash("hello world")
    assert exact_hash("a") != exact_hash("b")


def test_dedup_recall_precision(tmp_path):
    rng = random.Random(20240509)
    db = str(tmp_path / "dedup.db")

    originals = [_rand_doc(rng) for _ in range(200)]
    # 20% planted near-duplicates.
    n_dup = 40
    dup_sources = rng.sample(range(len(originals)), n_dup)

    tp = fp = fn = tn = 0
    with MinHashDeduper(db, num_perm=128, threshold=0.8) as d:
        # Seed the index with all originals (all new).
        for i, txt in enumerate(originals):
            assert d.add_if_new(f"orig:{i}", txt) is True

        # Interleave near-dups (label=dup) and fresh distinct docs (label=new).
        eval_items = []
        for k, si in enumerate(dup_sources):
            base = originals[si]
            if k % 2 == 0:
                # whitespace-perturbed -> caught by exact hash
                near = base.replace(" ", "  ", 3)
            else:
                # paraphrase: append two tokens -> high-Jaccard near-dup
                near = base + " " + rng.choice(_DWORDS) + " " + rng.choice(_DWORDS)
            eval_items.append((f"dup:{k}", near, True))
        for j in range(40):
            eval_items.append((f"new:{j}", _rand_doc(rng), False))

        rng.shuffle(eval_items)
        for doc_id, txt, is_dup in eval_items:
            flagged = not d.add_if_new(doc_id, txt)
            if is_dup and flagged:
                tp += 1
            elif is_dup and not flagged:
                fn += 1
            elif not is_dup and flagged:
                fp += 1
            else:
                tn += 1

    recall = tp / (tp + fn)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    assert recall >= 0.95, f"recall {recall:.3f} (tp={tp} fn={fn})"
    assert precision >= 0.98, f"precision {precision:.3f} (tp={tp} fp={fp})"


def test_dedup_concurrent_no_double_accept(tmp_path):
    """Two replicas racing to add near-duplicate docs: exactly one accepts."""
    db = str(tmp_path / "dedup.db")
    rng = random.Random(7)

    for trial in range(6):
        base = _rand_doc(rng)
        a_text = base
        b_text = base + " " + rng.choice(_DWORDS)  # near-dup, Jaccard ~0.99
        results: list[bool] = []
        lock = threading.Lock()

        def worker(doc_id, text):
            with MinHashDeduper(db, num_perm=128, threshold=0.8, timeout=60.0) as d:
                r = d.add_if_new(doc_id, text)
            with lock:
                results.append(r)

        t1 = threading.Thread(target=worker, args=(f"a{trial}", a_text))
        t2 = threading.Thread(target=worker, args=(f"b{trial}", b_text))
        t1.start(); t2.start(); t1.join(30); t2.join(30)

        assert sum(results) == 1, f"trial {trial}: exactly one should accept, got {results}"


# ---------------------------------------------------------------------------
# decontaminate
# ---------------------------------------------------------------------------

def test_decontaminate_removes_every_eval_prompt():
    d = Decontaminator(ngram=13)
    filler = "Here is some ordinary surrounding text that wraps the probe. "
    for t in all_eval_texts():
        # bare
        cont, which = d.is_contaminated(t)
        assert cont, f"eval prompt not detected verbatim: {t!r}"
        # embedded in a larger doc
        doc = filler + t + " " + filler
        cont, which = d.is_contaminated(doc)
        assert cont, f"eval prompt not detected when embedded: {t!r}"
        assert which in EVAL_SETS


def test_decontaminate_keeps_facts_in_different_words():
    d = Decontaminator(ngram=13)
    facts = [
        "Spiders possess eight legs.",
        "A spider has eight legs and can spin silk webs to catch its prey.",
        "Paris is the capital city of France and sits on the river Seine.",
        "An ant is an insect with six legs and a segmented body.",
        "Water is a compound made of hydrogen and oxygen atoms bonded together.",
        "People in France commonly speak the French language in daily life.",
    ]
    for f in facts:
        cont, which = d.is_contaminated(f)
        assert not cont, f"fact wrongly flagged as contaminated ({which}): {f!r}"


def test_decontaminate_report_merges(tmp_path):
    report = tmp_path / "decontam_report.json"
    write_report({"srcA": {"j_space": 2}}, report)
    write_report({"srcA": {"j_space": 3, "capability": 1}}, report)
    write_report({"srcB": {"needle": 4}}, report)
    data = json.loads(report.read_text())
    assert data["srcA"]["j_space"] == 5
    assert data["srcA"]["capability"] == 1
    assert data["srcB"]["needle"] == 4


# ---------------------------------------------------------------------------
# split
# ---------------------------------------------------------------------------

RATIOS = {"train": 0.98, "val": 0.01, "test": 0.01}


def test_split_deterministic_and_reorder_invariant():
    ids = [f"doc:{i}" for i in range(5000)]
    a = {i: assign_split(i, RATIOS) for i in ids}
    b = {i: assign_split(i, RATIOS) for i in reversed(ids)}
    assert a == b  # order-independent, deterministic


def test_split_ratios_within_tolerance():
    n = 100_000
    counts = {"train": 0, "val": 0, "test": 0}
    for i in range(n):
        counts[assign_split(f"doc:{i}", RATIOS)] += 1
    for split, target in RATIOS.items():
        frac = counts[split] / n
        assert abs(frac - target) <= 0.005, f"{split}: {frac:.4f} vs {target}"
    assert sum(counts.values()) == n  # every doc assigned exactly one split


# ---------------------------------------------------------------------------
# pack
# ---------------------------------------------------------------------------

def _docs(rng: random.Random, n: int = 12) -> list[dict]:
    out = []
    for i in range(n):
        text = make_english_doc(rng, n_sentences=6)
        out.append({
            "doc_id": f"pk:{i}",
            "text": text,
            "task_type": "deliberate",
            "concept": "spider",
            "phase": "p1",
        })
    return out


def test_pack_roundtrip_and_offsets(tiny_tokenizer, tmp_path):
    lt = pack.load_tokenizer(tiny_tokenizer)
    rng = random.Random(3)
    docs = _docs(rng)
    arr, idx = pack.pack_docs(docs, lt)

    bin_path = tmp_path / "p1" / "train" / "shard.bin"
    pack.write_shard(arr, idx, bin_path)
    arr2, idx2 = pack.read_shard(bin_path)

    assert np.array_equal(arr, arr2)
    assert idx2["tokens"] == arr2.size == len(arr)
    assert idx2["tokenizer_sha"] == lt.sha256

    tok = lt.tokenizer
    for d, meta in zip(docs, idx2["docs"]):
        s, e = meta["start"], meta["end"]
        # exact round-trip of the doc's token range
        assert tok.decode(arr2[s:e].tolist()) == d["text"]
        # the separator sits right after the doc range
        assert int(arr2[e]) == lt.eod_id
        # concept token id is the first token of the concept string
        assert meta["concept_token_id"] == tok.encode(d["concept"]).ids[0]
        # a random sub-window decodes to a substring of the source
        if e - s > 4:
            w0 = s + 1
            w1 = e - 1
            frag = tok.decode(arr2[w0:w1].tolist())
            assert frag.strip() in d["text"]

    # doc ranges are contiguous and non-overlapping
    prev_end = -1
    for meta in idx2["docs"]:
        assert meta["start"] == prev_end + 1
        prev_end = meta["end"]  # eod occupies [end], next start = end+1


def test_pack_raises_when_no_tokenizer(tmp_path):
    with pytest.raises(pack.TokenizerNotFrozen):
        pack.load_tokenizer(tmp_path / "does_not_exist.json")


def test_complete_wrong_tokenizer_sha_raises(tmp_path, tiny_tokenizer):
    lt = pack.load_tokenizer(tiny_tokenizer)
    db = str(tmp_path / "manifest.db")
    with Manifest(db) as m:
        me = worker_id()
        m.add_shard("s1", source="test", phase=1, path="/raw/s1.jsonl.zst", bytes_=1, docs=1)
        m.freeze_tokenizer(lt.sha256, lt.vocab_size)
        shard = m.claim("curate", by=me)
        assert shard is not None
        with pytest.raises(TokenizerMismatch):
            m.complete("s1", by=me, tokenizer_sha="deadbeef" * 8, tokens=1, split="train")


def test_complete_no_frozen_tokenizer_raises(tmp_path):
    db = str(tmp_path / "manifest.db")
    with Manifest(db) as m:
        me = worker_id()
        m.add_shard("s1", source="test", phase=1, path="/raw/s1.jsonl.zst")
        shard = m.claim("curate", by=me)
        assert shard is not None
        with pytest.raises(TokenizerMismatch):
            m.complete("s1", by=me, tokenizer_sha="a" * 64, tokens=1, split="train")


# ---------------------------------------------------------------------------
# end-to-end --once
# ---------------------------------------------------------------------------

def _write_raw_shard(path: Path, docs: list[dict]) -> None:
    payload = "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs).encode("utf-8")
    compressed = zstd.ZstdCompressor(level=10).compress(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(compressed)


def test_end_to_end_once(tmp_path, tiny_tokenizer, monkeypatch):
    from ava.pipeline.curator import Curator

    # Isolate from any live metrics_{preset}.jsonl that would redirect claims
    # to the trainer's current phase.
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setenv("AVA_REPORTS_DIR", str(reports))

    raw_dir = tmp_path / "raw"
    packed_dir = tmp_path / "packed"
    state_dir = tmp_path / "state"
    for d in (raw_dir, packed_dir, state_dir):
        d.mkdir(parents=True, exist_ok=True)
    db = str(state_dir / "manifest.db")
    dedup_db = str(state_dir / "dedup.db")

    # Build 60 mutually-distinct English docs with explicit doc_ids so we can
    # predict their split assignment.
    rng = random.Random(99)
    ratios = {"train": 0.98, "val": 0.01, "test": 0.01}
    docs = []
    for i in range(60):
        docs.append({
            "doc_id": f"e2e:{i:04d}",
            "text": make_english_doc(rng, n_sentences=9),
            "task_type": "deliberate",
            "concept": "spider",
            "phase": "p1",
            "source": "e2e",
        })
    expected_splits = {d["doc_id"]: assign_split(d["doc_id"], ratios) for d in docs}
    present_splits = set(expected_splits.values())

    raw_path = raw_dir / "e2e_0000.jsonl.zst"
    _write_raw_shard(raw_path, docs)

    lt = pack.load_tokenizer(tiny_tokenizer)
    with Manifest(db) as m:
        m.add_shard("e2e_0000", source="e2e", phase=1, path=str(raw_path),
                    bytes_=raw_path.stat().st_size, docs=len(docs))
        m.freeze_tokenizer(lt.sha256, lt.vocab_size)
        m.upsert_run("e2e", preset="nano", step=0, phase=1, status="running")

    curator = Curator(
        config_path="configs/pipeline.yaml",
        db_path=db,
        raw_dir=str(raw_dir),
        packed_dir=str(packed_dir),
        dedup_db=dedup_db,
        tokenizer_path=str(tiny_tokenizer),
    )
    rc = curator.serve(once=True)
    assert rc == 0

    # RAW row is now PACKED, raw file deleted.
    assert not raw_path.exists(), "raw file should be deleted after completion"
    with Manifest(db) as m:
        counts = m.counts_by_state()
        assert counts.get(PACKED, 0) >= 1
        train_row = m.db.execute("SELECT * FROM shards WHERE id='e2e_0000'").fetchone()
        assert train_row["state"] == PACKED
        assert train_row["split"] == "train"

        # Packed files exist for every split that got docs, and the manifest
        # train token count matches the train shard's idx.json. The packed file
        # is named by the raw shard id under the split directory; the manifest
        # row id for val/test additionally carries a :split suffix.
        for split in present_splits:
            row_id = "e2e_0000" if split == "train" else f"e2e_0000:{split}"
            row = m.db.execute("SELECT * FROM shards WHERE id=?", (row_id,)).fetchone()
            assert row is not None and row["state"] == PACKED and row["split"] == split
            bin_path = Path(row["path"])
            assert bin_path.exists(), f"missing packed file for split {split}: {bin_path}"
            assert bin_path == packed_dir / "p1" / split / "e2e_0000.bin"
            arr, idx = pack.read_shard(bin_path)
            assert idx["tokens"] == arr.size > 0
            if split == "train":
                assert train_row["tokens"] == idx["tokens"], "manifest train tokens mismatch"
                assert m.tokens_ready(1, split="train") == idx["tokens"]
