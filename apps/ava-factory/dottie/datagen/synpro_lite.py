"""SynPro-lite: faithful organic diversification without external hallucination.

Research (SynPro / data-bound scaling): rephrase organic text for lexical diversity
while preserving semantics. Full RL generators need GPUs; this lite path is a
deterministic, CPU-safe faithfulness gate plus light syntactic transforms so we
never invent numbers that were not in the source.

Wire-up: collectors / offline scripts call ``faithful_rephrase``; reject when
``numbers_faithful`` fails. Keep source weight at 0 in ``sources.yaml`` until an
operator enables a dedicated synth_synpro source.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

_NUM_RE = re.compile(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
_WS_RE = re.compile(r"\s+")

# Tiny closed synonym map — never introduces new entities or numbers.
_SYNONYMS: tuple[tuple[str, str], ...] = (
    (r"\bhowever\b", "but"),
    (r"\btherefore\b", "so"),
    (r"\bin order to\b", "to"),
    (r"\ba large number of\b", "many"),
    (r"\bin addition\b", "also"),
    (r"\bapproximately\b", "about"),
)


def extract_numbers(text: str) -> frozenset[str]:
    """Canonical numeric tokens present in ``text`` (commas stripped)."""
    out: set[str] = set()
    for m in _NUM_RE.finditer(text or ""):
        out.add(m.group(0).replace(",", ""))
    return frozenset(out)


def numbers_faithful(source: str, candidate: str) -> bool:
    """True iff every number in ``candidate`` already appears in ``source``."""
    return extract_numbers(candidate) <= extract_numbers(source)


def _light_paraphrase(text: str) -> str:
    s = _WS_RE.sub(" ", (text or "").strip())
    for pat, repl in _SYNONYMS:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)
    # Prefer active short clauses: drop leading filler phrases.
    s = re.sub(
        r"^(?:It is (?:important|worth noting) that\s+)", "", s, flags=re.IGNORECASE
    )
    return s.strip()


def faithful_rephrase(source: str, *, variants: int = 1) -> list[str]:
    """Return up to ``variants`` paraphrases that pass the numeric faithfulness gate.

    If the light paraphrase invents a number (should not), it is dropped and the
    original source is returned as the only faithful form.
    """
    src = (source or "").strip()
    if not src:
        return []
    out: list[str] = []
    cand = _light_paraphrase(src)
    if cand and numbers_faithful(src, cand) and cand != src:
        out.append(cand)
    # Second variant: sentence order swap when exactly two sentences.
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", src) if p.strip()]
    if variants >= 2 and len(parts) == 2:
        swapped = f"{parts[1]} {parts[0]}"
        if numbers_faithful(src, swapped):
            out.append(swapped)
    if not out:
        out.append(src)
    return out[: max(1, variants)]


def filter_faithful(source: str, candidates: Iterable[str]) -> list[str]:
    """Keep only candidates that do not invent numbers vs ``source``."""
    return [c for c in candidates if c and numbers_faithful(source, c)]
