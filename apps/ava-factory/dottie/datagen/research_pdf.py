"""ResearchPdfGenerator — chunk local open-licensed research corpus into DOC_KEYS.

Solo personal project, no connection to employer, built with public/free-tier only.
HOME-only, zero network. Reads markdown/text already extracted by
``scripts/ingest_research_pdfs.py`` into ``AVA_RESEARCH_CORPUS`` (default
``data/research_corpus``).

Does **not** download PDFs. Upload-mirror sites are out of scope.

Domain → phase mapping follows docs/AGENTIC_CURRICULUM.md. If the corpus dir is
empty, the generator yields a single honest placeholder doc explaining that the
operator must populate the inbox (so weight-0 wiring stays testable offline).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from dottie.datagen.base import Generator, run_cli

_DOMAIN_PHASE = {
    "math": 1,
    "statistics": 3,
    "stats": 3,
    "causal": 3,
    "physics": 2,
    "psychology": 2,
    "psych": 2,
    "general": 2,
}

_DOMAIN_TASK = {
    "math": "deliberate",
    "statistics": "deliberate",
    "stats": "deliberate",
    "causal": "deliberate",
    "physics": "automatic",
    "psychology": "automatic",
    "psych": "automatic",
    "general": "automatic",
}


def _corpus_root() -> Path:
    env = os.environ.get("AVA_RESEARCH_CORPUS") or os.environ.get("AVA_FACTORY_ROOT")
    if os.environ.get("AVA_RESEARCH_CORPUS"):
        return Path(os.environ["AVA_RESEARCH_CORPUS"])
    if env:
        return Path(env) / "data" / "research_corpus"
    return Path("data/research_corpus")


def chunk_text(text: str, max_chars: int = 1800, overlap: int = 200) -> list[str]:
    """Whitespace-aware chunker; deterministic, no NLP deps."""
    text = " ".join(text.split())
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            # prefer break on sentence end
            window = text[start:end]
            dot = window.rfind(". ")
            if dot >= max_chars // 3:
                end = start + dot + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def iter_corpus_files(root: Path) -> list[tuple[str, Path]]:
    """Return (domain, path) for *.md / *.txt under root/<domain>/."""
    if not root.is_dir():
        return []
    out: list[tuple[str, Path]] = []
    for domain_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        domain = domain_dir.name.lower()
        for path in sorted(domain_dir.rglob("*")):
            if path.suffix.lower() in {".md", ".txt"} and path.is_file():
                out.append((domain, path))
    return out


class ResearchPdfGenerator(Generator):
    name = "research_pdf"
    # Emit across foundation/reasoning/anneal; math domain may also hit p1 via mapping
    phases = (1, 2, 3, 4, 5)

    def generate(self, target_bytes: int) -> Iterator[dict]:
        root = _corpus_root()
        files = iter_corpus_files(root)
        produced = 0
        if not files:
            text = (
                "Research corpus empty. Operator action required: place open-licensed "
                "PDFs in data/research_inbox/, run scripts/ingest_research_pdfs.py, "
                "then re-collect. Do not scrape upload-mirror sites. See "
                "configs/research_pdf_catalog.yaml and docs/AGENTIC_CURRICULUM.md."
            )
            doc = self.doc(
                text=text,
                task_type="automatic",
                concept="research_corpus_empty",
                phase=2,
                source=self.name,
            )
            yield doc
            return

        # Stable order; private rng only picks start offset for variety across seeds
        start = self.rng.randrange(len(files)) if files else 0
        ordered = files[start:] + files[:start]
        for domain, path in ordered:
            if produced >= target_bytes:
                return
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            phase = _DOMAIN_PHASE.get(domain, 2)
            # long files → also feed p4
            task_type = _DOMAIN_TASK.get(domain, "automatic")
            for i, chunk in enumerate(chunk_text(raw)):
                if produced >= target_bytes:
                    return
                use_phase = 4 if (len(chunk) > 1200 and phase in (2, 3) and i % 3 == 0) else phase
                if use_phase not in self.phases:
                    use_phase = phase
                header = f"[source_file={path.name} domain={domain}]\n"
                doc = self.doc(
                    text=header + chunk,
                    task_type=task_type if use_phase != 4 else "automatic",
                    concept=f"research_{domain}",
                    phase=use_phase,
                    source=self.name,
                )
                produced += len(doc["text"].encode("utf-8"))
                yield doc


if __name__ == "__main__":
    run_cli(ResearchPdfGenerator)
