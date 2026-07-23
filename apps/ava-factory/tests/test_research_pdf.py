"""Offline tests for research PDF chunking + generator."""

from __future__ import annotations

from pathlib import Path

from dottie.datagen.base import validate_doc
from dottie.datagen.research_pdf import (
    ResearchPdfGenerator,
    chunk_text,
    iter_corpus_files,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "research_corpus"


def test_chunk_text_respects_max_and_overlap():
    text = ("Sentence number %d. " % i for i in range(200))
    blob = "".join(text)
    chunks = chunk_text(blob, max_chars=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 220 for c in chunks)  # soft bound; sentence snap may vary
    assert chunks[0]


def test_empty_corpus_yields_honest_placeholder(monkeypatch, tmp_path):
    monkeypatch.setenv("AVA_RESEARCH_CORPUS", str(tmp_path / "empty"))
    gen = ResearchPdfGenerator(seed=1)
    docs = list(gen.generate(2000))
    assert len(docs) == 1
    validate_doc(docs[0], allowed_phases=gen.phases)
    assert "Research corpus empty" in docs[0]["text"]
    assert docs[0]["concept"] == "research_corpus_empty"


def test_fixture_corpus_emits_causal_chunks(monkeypatch):
    monkeypatch.setenv("AVA_RESEARCH_CORPUS", str(FIXTURE))
    files = iter_corpus_files(FIXTURE)
    assert files and files[0][0] == "causal"
    gen = ResearchPdfGenerator(seed=2)
    docs = list(gen.generate(5000))
    assert docs
    for d in docs:
        validate_doc(d, allowed_phases=gen.phases)
        assert d["source"] == "research_pdf"
        assert "research_causal" in d["concept"] or "source_file=" in d["text"]
    assert any("Causal Factor Analysis" in d["text"] for d in docs)


def test_ingest_script_handles_markdown(tmp_path):
    import json
    import subprocess
    import sys

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "note.md").write_text(
        "A" * 60 + " Causal factor conditions enable events. " + "B" * 60,
        encoding="utf-8",
    )
    (inbox / "note.meta.json").write_text(
        json.dumps(
            {
                "license": "cc-by-4.0",
                "source_url": "https://example.org/note",
                "title": "Note",
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "corpus"
    script = Path(__file__).resolve().parents[1] / "scripts" / "ingest_research_pdfs.py"
    r = subprocess.run(
        [
            sys.executable,
            str(script),
            "--inbox",
            str(inbox),
            "--out",
            str(out),
            "--domain",
            "causal",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    written = list((out / "causal").glob("*.md"))
    assert written
    assert "cc-by-4.0" in written[0].read_text(encoding="utf-8")
