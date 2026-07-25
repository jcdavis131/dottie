# Solo personal project, no connection to employer, built with public/free-tier only
"""Readability — pure-stdlib readability scoring (openswap #21: Hemingway Editor Plus).

This is the arithmetic half of the prose gate: Flesch reading ease, Flesch-Kincaid
grade, Gunning fog, Coleman-Liau, a sentence-length histogram, adverb/passive
budgets, and per-paragraph + per-sentence difficulty bands (Hemingway's yellow
"hard" / red "very hard" highlighting, as data). It is a MODULE OF #1, not a
second plugin: `bigbang/core/prose.py` already owns markdown/HTML extraction,
paragraph splitting and the passive-voice matcher, so this file imports them
rather than growing a parallel copy, and the findings surface as
`scout prose score` / `scout prose report` plus a `readability` rule inside
`scout prose lint`. prose.py's own module docstring named this extension point.

Everything here is PURE logic — no network, no filesystem, no subprocess (the
plugin CLI supplies the I/O, same split as reach/statuspage).

Honesty about the numbers, because a readability score is easy to fake:

- Syllables are a HEURISTIC (vowel-group counting + silent-e/-ed/-es fixes).
  It undercounts adjacent vowels pronounced separately ("cre-ate", "i-de-a")
  and mis-handles a few silent clusters, so SYLLABLE_EXCEPTIONS pins the common
  English words where it is known wrong. Nothing here claims dictionary-grade
  syllabification, which is why COLEMAN-LIAU (letters per word — no syllables
  at all) is reported next to the syllable-based scores: when the two disagree
  the syllable heuristic is doing the work, and the report says so.
- Pure numerals ("2026", "9.5") are counted as neither words nor syllables:
  their spoken length is unknowable from spelling, exactly the reasoning behind
  prose's acronym guard in the a/an rule. `counts.numeric_excluded` reports how
  many were dropped so the denominator is never silently wrong.
- Gunning fog's classic definition excludes proper nouns and familiar
  compounds; detecting those from spelling alone is unreliable, so this
  implementation applies only the suffix half of the rule (-es/-ed/-ing that
  pushes a word to three syllables) and declares the omission in `notes`.
- Every formula is unstable on tiny samples, so document-level findings are
  suppressed below `min_words` and per-sentence bands below
  `min_sentence_words`; the scores are still reported, with a note.

Extension points: thresholds are policy-as-config in DEFAULT_CONFIG (overlaid
by `scout prose lint --rules`, like every other prose rule); add a metric by
appending to `_score_row` and it flows into JSON, the HTML report and the
consensus median for free.
"""

from __future__ import annotations

import html
import re
import statistics
from pathlib import Path
from typing import Any

from bigbang.core import openswap, prose

# Default output path for the HTML report — the repo-local scratch dir every
# other adapter writes into (manifest allowlists `.scout`, never $HOME).
PAGE_REL = Path(".scout") / "readability.html"

# Single source of truth for the readability policy. prose.load_rules() injects
# this under the "readability" key so `scout prose rules` lists it and a JSON
# overlay tunes it without a code edit.
DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "severity": "suggestion",
    # document target: consensus grade above this is a finding
    "max_grade": 12.0,
    # per-sentence bands (Hemingway's yellow/red)
    "hard_grade": 12.0,
    "very_hard_grade": 16.0,
    # stability floors — below these the formulas are noise, so no findings
    "min_words": 30,
    "min_sentence_words": 5,
    # budgets, expressed per-100-words / percent-of-sentences
    "adverbs_per_100_words": 2.0,
    "passive_pct": 10.0,
    # how many offending examples to carry in the report
    "examples": 5,
}

# Words where vowel-group counting is KNOWN wrong. Data, not code: each entry is
# a hand-checked English syllable count, not a guess.
SYLLABLE_EXCEPTIONS: dict[str, int] = {
    "area": 3, "areas": 3, "business": 2, "businesses": 3,
    "create": 2, "created": 3, "creates": 2, "creating": 3,
    "diet": 2, "fluid": 2, "genuine": 3, "idea": 3, "ideas": 3,
    "poem": 2, "poems": 2, "quiet": 2, "ruin": 2, "science": 2,
    "sciences": 2, "being": 2, "someone": 2, "everyone": 3,
}

# -ly words that are not adverbs. Every entry here is >= 5 chars because the
# pattern below already requires that much: the short offenders ("only", "fly",
# "ugly", "holy", "rely", "ally", "july") are excluded by the length floor, so
# listing them again would be dead data. 5 is the floor rather than 6 so real
# short adverbs ("badly", "sadly") still get flagged.
NON_ADVERB_LY = frozenset({
    "anomaly", "apply", "assembly", "belly", "bully", "comply", "family",
    "folly", "imply", "italy", "jelly", "melancholy", "monopoly", "multiply",
    "panoply", "rally", "reply", "silly", "supply", "tally",
})

# Flesch reading-ease bands (the published table).
_EASE_BANDS = (
    (90.0, "very easy"),
    (80.0, "easy"),
    (70.0, "fairly easy"),
    (60.0, "plain english"),
    (50.0, "fairly difficult"),
    (30.0, "difficult"),
    (float("-inf"), "very confusing"),
)

# Sentence-length histogram buckets: (label, low, high) inclusive.
HISTOGRAM_BUCKETS = (
    ("1-5", 1, 5),
    ("6-10", 6, 10),
    ("11-15", 11, 15),
    ("16-20", 16, 20),
    ("21-25", 21, 25),
    ("26-30", 26, 30),
    ("31-40", 31, 40),
    ("41+", 41, 10**9),
)

BAND_PLAIN = "plain"
BAND_HARD = "hard"
BAND_VERY_HARD = "very_hard"

_VOWELS = "aeiouy"
_NON_ALPHA_RE = re.compile(r"[^a-z]")
# markdown table rows: tabular data, not prose (the same test prose's hygiene
# rule uses to stop counting column padding as double spaces)
_TABLE_ROW_RE = re.compile(r"^\s*\|")
# prose.extract_* replaces code spans and URLs with a NUL sentinel of equal
# length to keep columns honest; readability reports no columns, so it collapses
# them instead of carrying NULs into JSON and HTML
_SENTINEL_RE = re.compile(r"\x00+")
_RUN_RE = re.compile(r"\s{2,}")
_HAS_LETTER_RE = re.compile(r"[A-Za-z]")
_LY_RE = re.compile(r"^[a-z]{3,}ly$")
# sibilants keep the extra -es syllable ("houses", "prices"); stops do not ("makes")
_ES_KEEP = frozenset("cszxhgj")
_ED_KEEP = frozenset("td")
# sentence terminator + optional closing quote/bracket, then whitespace or EOS
_SENT_SPLIT_RE = re.compile(r"([.!?]+[\"'”’)\]]*)(\s+|$)")
_TRAILING_WORD_RE = re.compile(r"([A-Za-z]+)\W*$")
# abbreviations whose period is not a sentence end
ABBREVIATIONS = frozenset({
    "al", "approx", "apr", "aug", "ca", "cf", "co", "dec", "dept", "dr", "eg",
    "est", "etc", "feb", "fig", "ie", "inc", "jan", "jr", "jul", "jun", "ltd",
    "mr", "mrs", "ms", "mt", "no", "nov", "oct", "prof", "sep", "sept", "sr",
    "st", "vol", "vs",
})


# ---- tokenizing -------------------------------------------------------------


def count_syllables(word: str) -> int:
    """Syllables in one word by vowel-group counting (see the module doc).

    Returns 0 for tokens with no letters ("2026") so numerals never inflate the
    syllable total, and at least 1 for anything alphabetic.
    """
    w = _NON_ALPHA_RE.sub("", word.lower())
    if not w:
        return 0
    if w in SYLLABLE_EXCEPTIONS:
        return SYLLABLE_EXCEPTIONS[w]
    if len(w) <= 3:
        return 1
    groups = 0
    prev_vowel = False
    for ch in w:
        is_vowel = ch in _VOWELS
        if is_vowel and not prev_vowel:
            groups += 1
        prev_vowel = is_vowel
    # silent final -e ("make" 1) but not the -le/-ee/-ye syllables ("apple" 2)
    if groups > 1 and w.endswith("e") and not w.endswith(("le", "ee", "ye")):
        groups -= 1
    # silent -ed ("walked" 1) unless the stem ends t/d ("wanted" 2)
    elif groups > 1 and w.endswith("ed") and w[-3] not in _ED_KEEP:
        groups -= 1
    # silent -es ("makes" 1) unless the stem ends in a sibilant ("houses" 2)
    elif groups > 1 and w.endswith("es") and w[-3] not in _ES_KEEP:
        groups -= 1
    return max(1, groups)


def words_of(text: str) -> list[str]:
    """Word tokens that carry at least one letter (numerals excluded)."""
    return [t for t in prose.WORD_RE.findall(text) if _HAS_LETTER_RE.search(t)]


def numeric_tokens(text: str) -> list[str]:
    """The purely numeric tokens dropped from the arithmetic (reported, not hidden)."""
    return [t for t in prose.WORD_RE.findall(text) if not _HAS_LETTER_RE.search(t)]


def split_sentences(text: str) -> list[str]:
    """Split into sentences, guarding the two boundaries that skew the ratio.

    Sentence count is the denominator of every formula here, so a naive
    `split on [.!?]` inflates grades on any text containing "e.g." or an
    initial. A terminator is NOT a boundary when the token before it is a known
    abbreviation or a single letter (initials), or when the next character is
    lowercase (a continuation). Decimals need no special case: "9.5" has no
    whitespace after the period.
    """
    out: list[str] = []
    start = 0
    for m in _SENT_SPLIT_RE.finditer(text):
        head = text[start:m.end(1)]
        prev = _TRAILING_WORD_RE.search(text[start:m.start(1)])
        token = prev.group(1).lower() if prev else ""
        if m.group(1) == "." and (token in ABBREVIATIONS or len(token) == 1):
            continue
        tail = text[m.end():].lstrip()
        if tail[:1].islower():
            continue
        if head.strip():
            out.append(head.strip())
        start = m.end()
    rest = text[start:].strip()
    if rest:
        out.append(rest)
    return out


def strip_tables(lines: list[str]) -> list[str]:
    """Blank markdown table rows, keeping every line number intact.

    Measured need, not a guess: scoring this repo's own README with tables
    included produced a "112-word sentence" at grade 48 out of a status table,
    because a row of cells has no terminator and reads as one enormous
    sentence. Cells are data; grading them says nothing about the prose. The
    count of dropped rows is reported so the omission is visible.
    """
    return ["" if _TABLE_ROW_RE.match(line) else line for line in lines]


def clean_text(text: str) -> str:
    """Display/scoring text: sentinels collapsed to a space, runs squeezed.

    Neither substitution changes a count — the NUL sentinel is not a word
    character and whitespace is not a letter — so this is presentation only.
    """
    return _RUN_RE.sub(" ", _SENTINEL_RE.sub(" ", text)).strip()


def is_complex(word: str) -> bool:
    """Gunning-fog "complex": 3+ syllables, not counting -es/-ed/-ing inflection."""
    syl = count_syllables(word)
    if syl < 3:
        return False
    stem = _NON_ALPHA_RE.sub("", word.lower())
    for suffix in ("es", "ed", "ing"):
        if stem.endswith(suffix) and len(stem) - len(suffix) >= 3:
            if count_syllables(stem[: -len(suffix)]) < 3:
                return False
    return True


def adverbs_of(text: str) -> list[str]:
    """-ly adverbs, minus the known non-adverb -ly words."""
    return [
        w for w in words_of(text)
        if _LY_RE.match(w.lower()) and w.lower() not in NON_ADVERB_LY
    ]


def passive_hits(text: str, rules: dict[str, Any] | None = None) -> list[str]:
    """Passive constructions, using PROSE's matcher so the two never disagree."""
    rules = rules or {}
    cfg = rules.get("passive_voice") or prose.DEFAULT_RULES["passive_voice"]
    not_participles = {w.lower() for w in cfg.get("not_participles", [])}
    return [
        m.group(0)
        for m in prose.passive_pattern(cfg).finditer(text)
        if m.group(1).lower() not in not_participles
    ]


# ---- formulas ---------------------------------------------------------------


def flesch_reading_ease(words: int, sentences: int, syllables: int) -> float | None:
    """206.835 - 1.015*(W/S) - 84.6*(Sy/W). None when the text has no content."""
    if words <= 0 or sentences <= 0:
        return None
    return 206.835 - 1.015 * (words / sentences) - 84.6 * (syllables / words)


def flesch_kincaid_grade(words: int, sentences: int, syllables: int) -> float | None:
    """0.39*(W/S) + 11.8*(Sy/W) - 15.59 — US grade level."""
    if words <= 0 or sentences <= 0:
        return None
    return 0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59


def gunning_fog(words: int, sentences: int, complex_words: int) -> float | None:
    """0.4*[(W/S) + 100*(complex/W)] — proper-noun exclusion omitted (module doc)."""
    if words <= 0 or sentences <= 0:
        return None
    return 0.4 * ((words / sentences) + 100.0 * (complex_words / words))


def coleman_liau(words: int, sentences: int, letters: int) -> float | None:
    """0.0588*L - 0.296*S - 15.8 over per-100-word letter/sentence counts.

    The syllable-free cross-check: if this disagrees sharply with Flesch-Kincaid,
    the syllable heuristic is what is being measured.
    """
    if words <= 0 or sentences <= 0:
        return None
    L = 100.0 * letters / words
    S = 100.0 * sentences / words
    return 0.0588 * L - 0.296 * S - 15.8


def ease_label(ease: float | None) -> str:
    """Published Flesch band name for a reading-ease score."""
    if ease is None:
        return "no data"
    for floor, label in _EASE_BANDS:
        if ease >= floor:
            return label
    return "very confusing"


def _round(v: float | None, places: int = 2) -> float | None:
    return None if v is None else round(v, places)


def _band(grade: float | None, cfg: dict[str, Any]) -> str:
    if grade is None:
        return BAND_PLAIN
    if grade >= float(cfg["very_hard_grade"]):
        return BAND_VERY_HARD
    if grade >= float(cfg["hard_grade"]):
        return BAND_HARD
    return BAND_PLAIN


def _config(rules: dict[str, Any] | None) -> dict[str, Any]:
    """DEFAULT_CONFIG overlaid with rules["readability"] (missing keys keep defaults)."""
    cfg = dict(DEFAULT_CONFIG)
    override = (rules or {}).get("readability")
    if isinstance(override, dict):
        cfg.update(override)
    return cfg


# ---- scoring ----------------------------------------------------------------


def _metrics(text: str, *, sentences: int) -> dict[str, Any]:
    """Raw counts + the four formulas for one span of prose.

    `sentences` is a COUNT supplied by the caller, never re-derived here: the
    document total must be the sum of the per-paragraph splits, or the ratio
    that every formula divides by would disagree with the histogram.
    """
    words = words_of(text)
    syllables = sum(count_syllables(w) for w in words)
    letters = sum(len(_NON_ALPHA_RE.sub("", w.lower())) for w in words)
    complex_words = [w for w in words if is_complex(w)]
    n_w, n_s = len(words), sentences
    fk = flesch_kincaid_grade(n_w, n_s, syllables)
    fog = gunning_fog(n_w, n_s, len(complex_words))
    cl = coleman_liau(n_w, n_s, letters)
    grades = [g for g in (fk, fog, cl) if g is not None]
    return {
        "words": n_w,
        "sentences": n_s,
        "syllables": syllables,
        "letters": letters,
        "complex_words": len(complex_words),
        "numeric_excluded": len(numeric_tokens(text)),
        "scores": {
            "flesch_reading_ease": _round(flesch_reading_ease(n_w, n_s, syllables)),
            "flesch_kincaid_grade": _round(fk),
            "gunning_fog": _round(fog),
            "coleman_liau": _round(cl),
            "consensus_grade": _round(statistics.median(grades)) if grades else None,
        },
    }


def histogram(sentence_words: list[int]) -> list[dict[str, Any]]:
    """Sentence-length distribution over the fixed buckets (always all buckets)."""
    total = len(sentence_words)
    rows = []
    for label, lo, hi in HISTOGRAM_BUCKETS:
        n = sum(1 for w in sentence_words if lo <= w <= hi)
        rows.append({
            "bucket": label,
            "count": n,
            "pct": round(100.0 * n / total, 1) if total else 0.0,
        })
    return rows


def _sentence_rows(
    paragraph_index: int, line: int, sentences: list[str], cfg: dict[str, Any]
) -> list[dict[str, Any]]:
    """Per-sentence grade + band. Below min_sentence_words the band is withheld."""
    floor = int(cfg["min_sentence_words"])
    rows = []
    for text in sentences:
        m = _metrics(text, sentences=1)
        graded = m["words"] >= floor
        rows.append({
            "paragraph": paragraph_index,
            "line": line,
            "words": m["words"],
            "grade": m["scores"]["flesch_kincaid_grade"],
            "band": _band(m["scores"]["flesch_kincaid_grade"], cfg) if graded else BAND_PLAIN,
            "graded": graded,
            "text": text if len(text) <= 160 else text[:157] + "...",
        })
    return rows


def score_lines(
    lines: list[str], *, path: str = "<text>", rules: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Score already-extracted prose lines (the shape prose.CHECKS passes).

    Taking `lines` rather than raw text is what lets this reuse prose's
    markdown/HTML extraction verbatim: code fences, inline code and URLs are
    already blanked upstream, so no README's shell snippet lands in a grade.
    """
    cfg = _config(rules)
    tables = sum(1 for line in lines if _TABLE_ROW_RE.match(line))
    paragraphs: list[dict[str, Any]] = []
    sentence_rows: list[dict[str, Any]] = []
    body_parts: list[str] = []
    for idx, (line, raw) in enumerate(prose.paragraphs(strip_tables(lines)), 1):
        text = clean_text(raw)
        sentences = split_sentences(text)
        m = _metrics(text, sentences=len(sentences))
        rows = _sentence_rows(idx, line, sentences, cfg)
        sentence_rows.extend(rows)
        body_parts.append(text)
        paragraphs.append({
            "index": idx,
            "line": line,
            "words": m["words"],
            "sentences": m["sentences"],
            "grade": m["scores"]["flesch_kincaid_grade"],
            "reading_ease": m["scores"]["flesch_reading_ease"],
            "band": _band(m["scores"]["flesch_kincaid_grade"], cfg)
            if m["words"] >= int(cfg["min_sentence_words"]) else BAND_PLAIN,
            "hard": sum(1 for r in rows if r["band"] == BAND_HARD),
            "very_hard": sum(1 for r in rows if r["band"] == BAND_VERY_HARD),
            "text": text if len(text) <= 240 else text[:237] + "...",
        })
    body = " ".join(body_parts)
    doc = _metrics(body, sentences=len(sentence_rows))
    report: dict[str, Any] = {
        "path": path,
        "counts": {
            "words": doc["words"],
            "sentences": doc["sentences"],
            "paragraphs": len(paragraphs),
            "syllables": doc["syllables"],
            "letters": doc["letters"],
            "complex_words": doc["complex_words"],
            "numeric_excluded": doc["numeric_excluded"],
            "table_rows_skipped": tables,
        },
        "averages": {
            "words_per_sentence": _round(doc["words"] / doc["sentences"])
            if doc["sentences"] else None,
            "syllables_per_word": _round(doc["syllables"] / doc["words"])
            if doc["words"] else None,
            "letters_per_word": _round(doc["letters"] / doc["words"])
            if doc["words"] else None,
        },
        "scores": doc["scores"],
        "ease_label": ease_label(doc["scores"]["flesch_reading_ease"]),
        "target_grade": float(cfg["max_grade"]),
        "over_target": bool(
            doc["scores"]["consensus_grade"] is not None
            and doc["scores"]["consensus_grade"] > float(cfg["max_grade"])
        ),
        "histogram": histogram([r["words"] for r in sentence_rows]),
        "sentences": {
            "total": len(sentence_rows),
            "hard": sum(1 for r in sentence_rows if r["band"] == BAND_HARD),
            "very_hard": sum(1 for r in sentence_rows if r["band"] == BAND_VERY_HARD),
            "ungraded_short": sum(1 for r in sentence_rows if not r["graded"]),
            "longest": max(sentence_rows, key=lambda r: r["words"], default=None),
            "worst": sorted(
                (r for r in sentence_rows if r["band"] != BAND_PLAIN),
                key=lambda r: (-(r["grade"] or 0.0), r["line"]),
            )[: int(cfg["examples"])],
        },
        "flags": _flags(body, doc["words"], len(sentence_rows), cfg, rules),
        "paragraphs": paragraphs,
        "notes": _notes(doc["words"], cfg),
        "reliable": doc["words"] >= int(cfg["min_words"]),
    }
    return report


def _flags(
    body: str,
    words: int,
    sentences: int,
    cfg: dict[str, Any],
    rules: dict[str, Any] | None,
) -> dict[str, Any]:
    """Adverb and passive budgets — Hemingway's two red flags, as ratios."""
    advs = adverbs_of(body)
    per_100 = (100.0 * len(advs) / words) if words else 0.0
    passives = passive_hits(body, rules)
    pct = (100.0 * len(passives) / sentences) if sentences else 0.0
    limit_adv = float(cfg["adverbs_per_100_words"])
    limit_pas = float(cfg["passive_pct"])
    keep = int(cfg["examples"])
    return {
        "adverbs": {
            "count": len(advs),
            "per_100_words": round(per_100, 2),
            "budget_per_100_words": limit_adv,
            "over_budget": bool(words and per_100 > limit_adv),
            "examples": sorted({a.lower() for a in advs})[:keep],
        },
        "passive": {
            "count": len(passives),
            "pct_of_sentences": round(pct, 1),
            "budget_pct": limit_pas,
            "over_budget": bool(sentences and pct > limit_pas),
            "examples": [p.lower() for p in passives[:keep]],
        },
    }


def _notes(words: int, cfg: dict[str, Any]) -> list[str]:
    """Say out loud where the numbers are weak. Never silently unreliable."""
    notes = [
        "syllables are heuristic (vowel groups + silent -e/-ed/-es); "
        "coleman_liau uses letters only and is the syllable-free cross-check",
        "gunning_fog omits the proper-noun/compound exclusion — spelling alone "
        "cannot identify those reliably",
        "pure numerals and markdown table rows are excluded from every count "
        "(counts.numeric_excluded, counts.table_rows_skipped)",
        "the passive count uses prose's matcher, which needs the participle to "
        "follow the auxiliary directly: 'was subsequently approved' is missed, so "
        "read the passive ratio as a floor, not a total",
    ]
    if words < int(cfg["min_words"]):
        notes.append(
            f"{words} words is below min_words={cfg['min_words']}: scores are "
            "reported but too small to gate on, so no document-level finding is raised"
        )
    return notes


def score_text(
    text: str,
    *,
    path: str = "<text>",
    fmt: str = "markdown",
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score raw source text, extracting prose the way `prose lint` does."""
    if fmt == "markdown":
        lines = prose.extract_markdown(text)
    elif fmt == "html":
        lines = prose.extract_html(text)
    else:
        lines = text.splitlines()
    report = score_lines(lines, path=path, rules=rules)
    report["format"] = fmt
    return report


# ---- diagnostics (the family schema) ---------------------------------------


def to_diagnostics(
    report: dict[str, Any], *, rules: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Normalized openswap diagnostics, so readability rides the same gate.

    Document-level findings anchor to line 1 and per-sentence findings to their
    PARAGRAPH's first line — the same convention prose's sentence_length rule
    already uses, because paragraphs are joined before sentence splitting.
    """
    cfg = _config(rules)
    sev = cfg.get("severity", "suggestion")
    path = report.get("path", "<text>")
    out: list[dict[str, Any]] = []
    if report.get("reliable") and report.get("over_target"):
        grade = report["scores"]["consensus_grade"]
        out.append(openswap.diagnostic(
            path=path, line=1, rule="readability:grade", severity=sev,
            message=(
                f"consensus grade {grade} above target {report['target_grade']} "
                f"(flesch ease {report['scores']['flesch_reading_ease']} = "
                f"{report['ease_label']})"
            ),
        ))
    for row in report["sentences"]["worst"]:
        very = row["band"] == BAND_VERY_HARD
        out.append(openswap.diagnostic(
            path=path, line=row["line"], rule=f"readability:{row['band']}-sentence",
            severity=sev if very else "info",
            message=(
                f"{'very hard' if very else 'hard'} sentence "
                f"(grade {row['grade']}, {row['words']} words): {row['text'][:80]}"
            ),
        ))
    shown = len(report["sentences"]["worst"])
    banded = report["sentences"]["hard"] + report["sentences"]["very_hard"]
    if banded > shown:
        # the `examples` cap must not read as "that was all of them"
        out.append(openswap.diagnostic(
            path=path, line=1, rule="readability:sentences", severity="info",
            message=(
                f"{banded} sentences over the difficulty threshold "
                f"({report['sentences']['very_hard']} very hard, "
                f"{report['sentences']['hard']} hard); the {shown} worst are "
                "listed above — `scout prose score` reports every one"
            ),
        ))
    adv = report["flags"]["adverbs"]
    if report.get("reliable") and adv["over_budget"]:
        out.append(openswap.diagnostic(
            path=path, line=1, rule="readability:adverbs", severity="info",
            message=(
                f"{adv['count']} -ly adverbs = {adv['per_100_words']} per 100 words "
                f"(budget {adv['budget_per_100_words']}): "
                f"{', '.join(adv['examples']) or 'none'}"
            ),
        ))
    pas = report["flags"]["passive"]
    if report.get("reliable") and pas["over_budget"]:
        out.append(openswap.diagnostic(
            path=path, line=1, rule="readability:passive", severity="info",
            message=(
                f"{pas['count']} passive constructions in "
                f"{report['counts']['sentences']} sentences = "
                f"{pas['pct_of_sentences']}% (budget {pas['budget_pct']}%)"
            ),
        ))
    return out


def readability_check(
    lines: list[str], rules: dict[str, Any], path: str
) -> list[dict[str, Any]]:
    """prose.CHECKS entry point — same (lines, rules, path) -> diagnostics shape."""
    cfg = _config(rules)
    if not cfg.get("enabled"):
        return []
    if not any(line.strip() for line in lines):
        return []
    return to_diagnostics(score_lines(lines, path=path, rules=rules), rules=rules)


# ---- the Hemingway artifact: per-paragraph difficulty as one HTML file ------

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font: 16px/1.55 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       margin: 0 auto; max-width: 60rem; padding: 2rem 1.25rem 3rem;
       background: #fff; color: #1b2027; }
h1 { font-size: 1.6rem; margin: 0 0 .25rem; }
h2 { font-size: 1.1rem; margin: 2rem 0 .5rem; }
.note, footer { color: #55606e; font-size: .85em; }
.mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .85em; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0 1rem; }
th, td { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid #e3e8ef;
         vertical-align: top; }
th { font-weight: 600; color: #55606e; font-size: .8em; text-transform: uppercase; }
.pill { border-radius: 999px; padding: .1rem .5rem; font-size: .78em; font-weight: 600; }
.b-plain { background: #e7f6ec; color: #14532d; }
.b-hard { background: #fdf3d0; color: #6b4d05; }
.b-very_hard { background: #fbe0e0; color: #7c1d1d; }
.para { border-left: 4px solid #cbd5e1; padding: .4rem .75rem; margin: .5rem 0;
        background: #f8fafc; }
.para.b-hard { border-left-color: #d9a406; background: #fffbeb; }
.para.b-very_hard { border-left-color: #c0392b; background: #fff5f5; }
.bar { background: #e3e8ef; border-radius: 3px; height: .8rem; }
.bar > span { display: block; height: 100%; border-radius: 3px; background: #3b6fd4; }
.nodata { border: 1px dashed #c0392b; padding: .75rem; margin: 1rem 0; color: #7c1d1d; }
@media (prefers-color-scheme: dark) {
  body { background: #12161c; color: #e7ecf2; }
  th, td { border-bottom-color: #2b3440; }
  th, .mono, .note, footer { color: #9aa7b6; }
  .para { background: #171d25; border-left-color: #2b3440; }
  .para.b-hard { background: #1f1b0e; }
  .para.b-very_hard { background: #241416; }
  .bar { background: #2b3440; }
}
"""


def _metrics_table(report: dict[str, Any], e: Any) -> str:
    s = report["scores"]
    c = report["counts"]
    a = report["averages"]
    rows = [
        ("flesch reading ease", s["flesch_reading_ease"], report["ease_label"]),
        ("flesch-kincaid grade", s["flesch_kincaid_grade"], "syllable-based"),
        ("gunning fog", s["gunning_fog"], f"{c['complex_words']} complex words"),
        ("coleman-liau", s["coleman_liau"], "letters only, no syllables"),
        ("consensus grade", s["consensus_grade"], f"target {report['target_grade']}"),
        ("words / sentence", a["words_per_sentence"], f"{c['sentences']} sentences"),
        ("syllables / word", a["syllables_per_word"], f"{c['words']} words"),
    ]
    body = "\n".join(
        f"<tr><td>{e(label)}</td><td><b>{'—' if val is None else e(str(val))}</b></td>"
        f'<td class="mono">{e(str(note))}</td></tr>'
        for label, val, note in rows
    )
    return f"<table><tr><th>metric</th><th>value</th><th>note</th></tr>\n{body}\n</table>"


def _histogram_table(report: dict[str, Any], e: Any) -> str:
    rows = []
    peak = max((row["count"] for row in report["histogram"]), default=0) or 1
    for row in report["histogram"]:
        width = int(round(100.0 * row["count"] / peak))
        rows.append(
            f'<tr><td class="mono">{e(row["bucket"])}</td>'
            f'<td>{row["count"]}</td><td>{e(str(row["pct"]))}%</td>'
            f'<td><div class="bar"><span style="width:{width}%"></span></div></td></tr>'
        )
    return (
        "<table><tr><th>words / sentence</th><th>n</th><th>share</th>"
        "<th></th></tr>\n" + "\n".join(rows) + "\n</table>"
    )


def _paragraph_blocks(report: dict[str, Any], e: Any) -> str:
    blocks = []
    for p in report["paragraphs"]:
        grade = "—" if p["grade"] is None else f"{p['grade']}"
        blocks.append(
            f'<div class="para b-{e(p["band"])}">'
            f'<span class="pill b-{e(p["band"])}">{e(p["band"].replace("_", " "))}</span>'
            f' <span class="mono">line {p["line"]} · grade {e(grade)} · '
            f'{p["words"]} words · {p["sentences"]} sentences · '
            f'{p["hard"]} hard / {p["very_hard"]} very hard</span>'
            f'<p>{e(p["text"])}</p></div>'
        )
    return "\n".join(blocks)


def render_html(reports: list[dict[str, Any]], *, title: str = "Readability") -> str:
    """One self-contained HTML file: inline CSS, no JavaScript, no external assets.

    This is the Hemingway artifact — every paragraph carried with its difficulty
    band — rendered so it works from file://, a static host, or an email. Every
    dynamic string goes through html.escape because the input is arbitrary prose
    (including, deliberately, prose containing HTML).
    """
    e = html.escape
    parts = [
        f"<h1>{e(title)}</h1>",
        f'<p class="note">{len(reports)} file(s) scored locally by '
        '<span class="mono">scout prose report</span> (openswap #21 — Hemingway '
        "Editor Plus replaced by arithmetic). Nothing was uploaded: the scorer is "
        "pure stdlib and the prose plugin's manifest disables the network axis.</p>",
    ]
    if not reports:
        parts.append(
            '<div class="nodata"><b>No files scored.</b> Nothing was passed to '
            "the renderer, so this page states that rather than showing an "
            "invented score.</div>"
        )
    for report in reports:
        parts.append(f'<h2 class="mono">{e(str(report["path"]))}</h2>')
        if not report.get("reliable"):
            parts.append(
                f'<div class="nodata"><b>Sample too small to gate.</b> '
                f'{report["counts"]["words"]} words — the scores below are '
                "reported but no finding is raised from them.</div>"
            )
        parts.append(_metrics_table(report, e))
        parts.append("<h2>Sentence length</h2>")
        parts.append(_histogram_table(report, e))
        flags = report["flags"]
        parts.append(
            f'<p class="note">Adverbs {flags["adverbs"]["count"]} '
            f'({flags["adverbs"]["per_100_words"]} per 100 words, budget '
            f'{flags["adverbs"]["budget_per_100_words"]}) · passive '
            f'{flags["passive"]["count"]} '
            f'({flags["passive"]["pct_of_sentences"]}% of sentences, budget '
            f'{flags["passive"]["budget_pct"]}%)</p>'
        )
        parts.append("<h2>Per-paragraph difficulty</h2>")
        parts.append(_paragraph_blocks(report, e) or '<p class="note">No prose paragraphs.</p>')
        parts.append(
            '<p class="note">'
            + "<br>".join(e(n) for n in report.get("notes", []))
            + "</p>"
        )
    parts.append(
        '<footer>Static page, generated by <span class="mono">scout prose report'
        "</span>. Syllable counting is heuristic and every formula is stated in "
        "the notes above — read the grade as a comparison across drafts, not as "
        "a measurement.</footer>"
    )
    body = "\n".join(parts)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<style>{_CSS}</style></head>
<body>
{body}
</body></html>
"""
