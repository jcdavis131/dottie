# Solo personal project, no connection to employer, built with public/free-tier only
"""Contentgap — TF-IDF draft-vs-corpus coverage core (openswap #24: Clearscope).

Clearscope (and Surfer/MarketMuse) sell one loop: paste a draft, they crawl the
pages already ranking for your topic, weight the vocabulary those pages share,
and hand back "terms you are missing". Everything expensive about that is the
crawl — which is also the part that ships your unpublished draft to someone
else's box. This adapter deletes the crawl: the comparison corpus is FILES
ALREADY ON DISK (whatever you saved, exported or extracted earlier), the term
weighting is `collections.Counter` plus `math.log`, and the manifest disables
the network axis outright. Zero egress is the product, not a setting.

Everything here is pure: text in, verdict out. No sockets, no sqlite, no disk.
The plugin CLI owns the one real I/O (reading the draft and the corpus files)
so the whole pipeline is unit-testable with string literals.

The arithmetic, stated so a number can be checked by hand:

- tokenizer: `[^\\W_]+` runs (letters and digits, underscore excluded) joined by
  internal hyphens/apostrophes, casefolded, trailing possessive dropped. Markup
  is stripped FIRST by reusing bigbang.core.prose's markdown/HTML extractors —
  code fences, URLs, script/style never reach the counter, and this module ships
  no second copy of that logic.
- a "term" is a token that is >= `min_length` chars, is not all digits and is
  not a closed-class stopword; a "phrase" is two adjacent terms inside the same
  segment (never spanning a line/paragraph break, so `## GPU\\nClocks drift`
  does not invent "gpu clocks").
- tf is sublinear: `1 + log(count)`. One page repeating a word 90 times must not
  outvote nine pages using it twice.
- idf is smoothed: `log((N+1)/(df+1)) + 1`, so a term used by EVERY comparison
  page keeps weight 1.0 instead of collapsing to zero. That matters here and is
  the opposite of what a retrieval ranker wants: the terms every competitor
  covers are exactly the ones a draft must not miss.
- a term's corpus `weight` (its importance) is the mean of `tf * idf` over ALL
  usable corpus docs, so spread and intensity are one number: a term in 1 of 10
  pages is divided by 10 just the same as one in all 10.
- `expected` mentions for the draft is density-normalized:
  `corpus_count / corpus_tokens * draft_tokens`. A 300-word draft is never
  scolded for lacking the 14 mentions a 3,000-word page had.
- classify(): 0 mentions is `missing`; below `max(1, ceil(expected *
  thin_ratio))` is `thin` with partial credit; above `expected * over_ratio`
  (and at least `over_floor` mentions) is `overused` — Clearscope's
  over-optimization warning, which a naive "more keywords" tool never gives you.
- coverage_score = 100 * sum(weight * credit) / sum(weight) over the target
  terms. `overused` scores full credit (stuffing is reported separately, it does
  not inflate or deflate coverage).

Honesty rules this module enforces rather than documents:
- reading() carries EITHER a value OR a labelled error, never both, never
  neither. An empty corpus produces `coverage_score: {value: None, error:
  "..."}` and an `error`-severity `contentgap:unmeasured` diagnostic — an audit
  that could not measure must never read as a pass.
- a corpus file that cannot be counted (unreadable, too large, no words after
  markup extraction) lands in `skipped` WITH its reason and is excluded from
  N/df/idf. Silently dropping it would quietly move every weight.

Extension points:
- Budgets as config: analyze(thin_ratio=, over_ratio=, over_floor=,
  target_score=) tunes the gate without touching code.
- Corpus shape: build_corpus() takes [{name, text, format}] from anywhere — a
  directory of saved pages today, `scout extract`'s cached document store or a
  sitemap crawl's text later, with no change here.
- Family gate: to_diagnostics() maps gaps onto the openswap diagnostic schema,
  so `contentgap audit --fail-on warning` gates a publish exactly like a prose
  finding or an uptime outage.
- Native tier: there is none to prefer. Clearscope, Surfer and MarketMuse are
  browser apps with hosted APIs; no local binary does draft-vs-corpus coverage,
  so the plugin's detect() reports tier=fallback as the steady state.
"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from bigbang.core import openswap, prose

# ---- knobs (all overridable per call — budgets are config, not code) --------

MIN_TERM_LENGTH = 2
DEFAULT_TOP = 40
DEFAULT_THIN_RATIO = 0.5
DEFAULT_OVER_RATIO = 3.0
DEFAULT_OVER_FLOOR = 3
DEFAULT_TARGET_SCORE = 70.0
DEFAULT_MAX_KB = 2048
DEFAULT_DRAFT_ONLY = 10

# Repo-relative defaults (never absolute, never $HOME): the corpus is a folder
# of files you already saved, and the brief is a build artifact under .scout.
CORPUS_REL = Path(".scout") / "contentgap" / "corpus"
BRIEF_REL = Path(".scout") / "contentgap" / "brief.md"

# Derived, never re-listed: an extension list copied by hand drifts from its
# source the first time one side gains a format (a real bug class in this repo).
CORPUS_EXTS: tuple[str, ...] = prose.PROSE_EXTS

STATUS_MISSING = "missing"
STATUS_THIN = "thin"
STATUS_COVERED = "covered"
STATUS_OVERUSED = "overused"
STATUSES = (STATUS_MISSING, STATUS_THIN, STATUS_OVERUSED, STATUS_COVERED)

# Gap status -> openswap severity. Defined once so `to_diagnostics` and any
# --fail-on gate agree about what blocks a publish.
_STATUS_SEVERITY = {
    STATUS_MISSING: "warning",
    STATUS_THIN: "suggestion",
    STATUS_OVERUSED: "warning",
}

FORMAT_TEXT = "text"
FORMAT_MARKDOWN = "markdown"
FORMAT_HTML = "html"

# Closed-class function words ONLY — articles, pronouns, prepositions,
# conjunctions, auxiliaries, degree adverbs and clitic fragments. No nouns, no
# verbs, no adjectives: a topical word in this list would silently censor a
# whole subject area from every report, which is unfixable from the outside.
STOPWORDS = frozenset(
    """
    a about above after again against all also always am an and another any
    anything are aren as at
    be because been before being below between both but by
    can cannot could couldn
    did didn do does doesn doing don down during
    each either else enough even ever every everything few for from further
    had hadn has hasn have haven having he her here hers herself him himself
    his how however
    i if in into is isn it its itself
    just
    many may me might more most much must my myself
    neither never no nor not nothing now
    of off often on once only or other others ought our ours ourselves out
    over own
    rather same several shall shan she should shouldn since so some someone
    something sometimes still such
    than that the their theirs them themselves then there therefore these they
    this those though through thus to together too toward towards
    under unless until up upon us
    very
    was wasn we were weren what when whenever where wherever whether which
    while who whoever whom whose why will with within without won would wouldn
    yet you your yours yourself yourselves
    d ll m o re s t ve
    """.split()
)

# Word characters minus underscore, so snake_case splits into parts and a
# markdown separator line never becomes a term. Internal hyphens/apostrophes
# survive ("bf16", "gpu-bound", "don't"), edges cannot (the pattern requires a
# word character on both sides of every join).
_TOKEN_RE = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*")
_POSSESSIVE_RE = re.compile(r"['’]s$")


# ---- honest readings --------------------------------------------------------


def reading(value: Any = None, *, error: str | None = None) -> dict[str, Any]:
    """A measurement: EITHER a value OR a labelled reason it is unmeasurable.

    The one place this family's "never invent a number to fill a field" rule is
    mechanical instead of aspirational. Passing both (or neither) is a
    programming error and raises, so a caller cannot ship a metric that is
    simultaneously 0.0 and broken.
    """
    if (value is None) == (error is None):
        raise ValueError("a reading needs exactly one of value / error")
    return {"value": value, "error": error}


# ---- tokenizing -------------------------------------------------------------


def plain_segments(text: str, *, fmt: str = FORMAT_TEXT) -> list[str]:
    """Text -> prose segments with markup removed, one per source line.

    Delegates to bigbang.core.prose for markdown and HTML (code fences, inline
    code, URLs, script/style are blanked there) instead of shipping a second
    extractor that would drift from it. Segments are the phrase boundary: a
    bigram never spans two of them.
    """
    if fmt == FORMAT_MARKDOWN:
        return prose.extract_markdown(text)
    if fmt == FORMAT_HTML:
        return prose.extract_html(text)
    return text.splitlines()


def normalize_token(raw: str) -> str:
    """One raw match -> the canonical token (casefolded, possessive dropped)."""
    tok = _POSSESSIVE_RE.sub("", raw.casefold())
    return tok.strip("-'’")


def token_segments(text: str, *, fmt: str = FORMAT_TEXT) -> list[list[str]]:
    """Text -> per-segment lists of normalized tokens (stopwords still in).

    Stopwords are kept at this stage on purpose: they are part of the document
    LENGTH used to density-normalize expectations, and they are the gaps that
    stop a phrase from forming ("state of the art" yields no bigram).
    """
    out: list[list[str]] = []
    for segment in plain_segments(text, fmt=fmt):
        toks = [
            t for t in (normalize_token(m) for m in _TOKEN_RE.findall(segment)) if t
        ]
        if toks:
            out.append(toks)
    return out


def token_count(segments: list[list[str]]) -> int:
    """Total tokens — the document length that normalizes every expectation."""
    return sum(len(seg) for seg in segments)


def is_term(token: str, *, min_length: int = MIN_TERM_LENGTH) -> bool:
    """Is this token eligible to be a topic term (length, not numeric, not a stopword)?"""
    if len(token) < min_length:
        return False
    if token.isdigit():
        return False
    return token not in STOPWORDS


def phrase_terms(segment: list[str], *, min_length: int = MIN_TERM_LENGTH) -> list[str]:
    """Bigrams of ADJACENT eligible terms inside one segment.

    No stopword bridging ("part of speech" gives nothing) and no cross-segment
    joins, so every phrase is one a reader actually saw.
    """
    out: list[str] = []
    for first, second in itertools.pairwise(segment):
        if is_term(first, min_length=min_length) and is_term(
            second, min_length=min_length
        ):
            out.append(f"{first} {second}")
    return out


def term_counts(
    segments: list[list[str]],
    *,
    phrases: bool = True,
    min_length: int = MIN_TERM_LENGTH,
) -> Counter[str]:
    """One document's raw term frequencies (unigrams, plus bigrams if enabled)."""
    counts: Counter[str] = Counter()
    for segment in segments:
        counts.update(t for t in segment if is_term(t, min_length=min_length))
        if phrases:
            counts.update(phrase_terms(segment, min_length=min_length))
    return counts


# ---- weighting --------------------------------------------------------------


def tf_weight(count: int) -> float:
    """Sublinear term frequency: 1 + log(count); 0 for an absent term.

    Linear tf lets one keyword-stuffed comparison page dictate the whole target
    list. log() keeps the 90-mention page ahead of the 2-mention page without
    letting it outvote nine other pages.
    """
    if count <= 0:
        return 0.0
    return 1.0 + math.log(count)


def idf(doc_freq: int, n_docs: int) -> float:
    """Smoothed inverse document frequency: log((N+1)/(df+1)) + 1.

    NOT the same function as `searchindex._idf`, and the two must NOT be merged.
    That one is BM25 -- log(1 + (N - df + 0.5)/(df + 0.5)) -- tuned for RANKING
    retrieval hits, where the consensus vocabulary should sink. This one is the
    smoothed sklearn-style form tuned for COVERAGE, where a term on every
    comparison page is the most important thing a draft can be missing, so it must
    still weigh 1.0 instead of 0.0 (see below). Unifying them would silently change
    one plugin's output, and note the argument orders are also mirrored
    (`doc_freq, n_docs` here vs `doc_count, df` there), so a shared two-int helper
    would invite callers to swap them.

    The +1s are why a term present in EVERY comparison page still weighs 1.0
    rather than 0.0. Plain idf would zero out the consensus vocabulary — the
    single most important signal for "what must this draft cover".
    """
    if n_docs <= 0:
        raise ValueError("idf needs at least one document")
    return math.log((n_docs + 1) / (doc_freq + 1)) + 1.0


def build_corpus(
    docs: list[dict[str, Any]],
    *,
    phrases: bool = True,
    min_length: int = MIN_TERM_LENGTH,
) -> dict[str, Any]:
    """[{name, text, format}] -> the weighted corpus model.

    A document that cannot be counted is never dropped in silence: a pre-set
    `error` (unreadable / too large, set by the CLI's I/O), a missing text, or
    zero words after markup extraction all land in `skipped` WITH the reason and
    are excluded from N, df and idf. Dropping one quietly would move every
    weight in the report.
    """
    documents: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    per_doc: list[Counter[str]] = []
    tokens_total = 0
    for doc in docs:
        name = str(doc.get("name") or "?")
        text = doc.get("text")
        error = doc.get("error")
        if error is None and not isinstance(text, str):
            error = "no text supplied for this document"
        segments = (
            [] if error else token_segments(text, fmt=doc.get("format") or FORMAT_TEXT)
        )
        length = token_count(segments)
        if error is None and length == 0:
            error = "no words found after markup extraction"
        if error:
            skipped.append({"name": name, "error": str(error)})
            continue
        counts = term_counts(segments, phrases=phrases, min_length=min_length)
        per_doc.append(counts)
        tokens_total += length
        documents.append(
            {
                "name": name,
                "tokens": length,
                "term_instances": sum(counts.values()),
                "unique_terms": len(counts),
                "error": None,
            }
        )
    return {
        "n_docs": len(documents),
        "tokens": tokens_total,
        "phrases": phrases,
        "min_length": min_length,
        "documents": documents,
        "skipped": skipped,
        "terms": _weigh(per_doc, len(documents), tokens_total),
    }


def _weigh(
    per_doc: list[Counter[str]], n_docs: int, tokens_total: int
) -> dict[str, dict[str, Any]]:
    """Per-term {doc_freq, coverage, count, rate, idf, weight} over the corpus."""
    doc_freq: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    tf_sum: dict[str, float] = {}
    for counts in per_doc:
        for term, count in counts.items():
            doc_freq[term] += 1
            totals[term] += count
            tf_sum[term] = tf_sum.get(term, 0.0) + tf_weight(count)
    terms: dict[str, dict[str, Any]] = {}
    for term, freq in doc_freq.items():
        weight = idf(freq, n_docs)
        terms[term] = {
            "doc_freq": freq,
            "coverage": round(freq / n_docs, 4),
            "count": totals[term],
            # occurrences per token: the density that makes `expected` fair
            # across a 300-word draft and a 3,000-word comparison page
            "rate": (totals[term] / tokens_total) if tokens_total else 0.0,
            "idf": round(weight, 4),
            "weight": round(tf_sum[term] * weight / n_docs, 4),
        }
    return terms


def corpus_terms(
    model: dict[str, Any], *, limit: int | None = None
) -> list[dict[str, Any]]:
    """Corpus terms ranked by weight, ties broken alphabetically (deterministic)."""
    rows = [{"term": term, **info} for term, info in model["terms"].items()]
    rows.sort(key=lambda r: (-r["weight"], r["term"]))
    if limit is None:
        return rows
    return rows[: max(0, limit)]


# ---- classification ---------------------------------------------------------


def expected_count(rate: float, draft_tokens: int) -> float:
    """Mentions a draft of this length would need to match the corpus density."""
    return round(rate * max(0, draft_tokens), 2)


def minimum_count(expected: float, thin_ratio: float) -> int:
    """The floor that counts as covered: max(1, ceil(expected * thin_ratio)).

    ceil (not round) means a term the corpus density justifies 1.2 times still
    asks for 1 mention rather than 0. The max(1, ...) matters when the product is
    exactly zero — a zero-length draft, or thin_ratio=0 — and keeps `minimum` an
    actionable instruction: a report never tells a writer to add "0+ mentions" of
    a term it lists in the same breath as missing.
    """
    if thin_ratio < 0:
        raise ValueError("thin_ratio must be >= 0")
    return max(1, math.ceil(expected * thin_ratio))


def classify(
    draft_count: int,
    expected: float,
    *,
    thin_ratio: float = DEFAULT_THIN_RATIO,
    over_ratio: float = DEFAULT_OVER_RATIO,
    over_floor: int = DEFAULT_OVER_FLOOR,
) -> tuple[str, float]:
    """One term -> (status, credit in 0..1). See the module docstring's contract."""
    floor = minimum_count(expected, thin_ratio)
    if draft_count <= 0:
        return STATUS_MISSING, 0.0
    if draft_count < floor:
        return STATUS_THIN, round(draft_count / floor, 4)
    if (
        over_ratio > 0
        and draft_count >= over_floor
        and draft_count > expected * over_ratio
    ):
        return STATUS_OVERUSED, 1.0
    return STATUS_COVERED, 1.0


def _target_row(
    target: dict[str, Any],
    draft_counts: Counter[str],
    draft_tokens: int,
    *,
    thin_ratio: float,
    over_ratio: float,
    over_floor: int,
) -> dict[str, Any]:
    term = target["term"]
    expected = expected_count(target["rate"], draft_tokens)
    found = int(draft_counts.get(term, 0))
    status, credit = classify(
        found,
        expected,
        thin_ratio=thin_ratio,
        over_ratio=over_ratio,
        over_floor=over_floor,
    )
    return {
        "term": term,
        "status": status,
        "weight": target["weight"],
        "coverage": target["coverage"],
        "corpus_docs": target["doc_freq"],
        "corpus_count": target["count"],
        "expected": expected,
        "minimum": minimum_count(expected, thin_ratio),
        "draft_count": found,
        "credit": credit,
    }


def draft_only_terms(
    draft_counts: Counter[str],
    model: dict[str, Any],
    *,
    limit: int = DEFAULT_DRAFT_ONLY,
) -> list[dict[str, Any]]:
    """Draft terms NO comparison page uses — the inverse gap.

    Not a defect (it can be the draft's original contribution); it is the honest
    other half of a coverage report, and a long list of these next to a low
    score usually means the corpus is about a different topic than the draft.
    """
    known = model["terms"]
    rows = [
        {"term": term, "draft_count": count}
        for term, count in draft_counts.items()
        if term not in known
    ]
    rows.sort(key=lambda r: (-r["draft_count"], r["term"]))
    return rows[: max(0, limit)]


def analyze(
    draft_text: str,
    model: dict[str, Any],
    *,
    path: str = "draft",
    fmt: str = FORMAT_TEXT,
    top: int = DEFAULT_TOP,
    thin_ratio: float = DEFAULT_THIN_RATIO,
    over_ratio: float = DEFAULT_OVER_RATIO,
    over_floor: int = DEFAULT_OVER_FLOOR,
    target_score: float = DEFAULT_TARGET_SCORE,
) -> dict[str, Any]:
    """Draft + corpus model -> the contentgap report (see module docstring).

    Deterministic and offline by construction: both inputs are already text.
    `coverage_score` and `weighted_gap` are readings — with an empty corpus they
    carry a labelled reason instead of a zero that looks like a measurement.
    """
    segments = token_segments(draft_text, fmt=fmt)
    draft_tokens = token_count(segments)
    draft_counts = term_counts(
        segments, phrases=model.get("phrases", True), min_length=model["min_length"]
    )
    targets = [
        _target_row(
            t,
            draft_counts,
            draft_tokens,
            thin_ratio=thin_ratio,
            over_ratio=over_ratio,
            over_floor=over_floor,
        )
        for t in corpus_terms(model, limit=top)
    ]
    counts = dict.fromkeys(STATUSES, 0)
    for row in targets:
        counts[row["status"]] += 1
    total_weight = round(sum(r["weight"] for r in targets), 4)
    earned = round(sum(r["weight"] * r["credit"] for r in targets), 4)
    if total_weight > 0:
        score = reading(round(100.0 * earned / total_weight, 2))
        gap = reading(round(total_weight - earned, 4))
    else:
        why = _no_corpus_reason(model)
        score = reading(error=why)
        gap = reading(error=why)
    return {
        "path": path,
        "format": fmt,
        "draft_tokens": draft_tokens,
        "draft_terms": len(draft_counts),
        "corpus": {
            "n_docs": model["n_docs"],
            "tokens": model["tokens"],
            "unique_terms": len(model["terms"]),
            "phrases": model.get("phrases", True),
            "min_length": model["min_length"],
            "documents": [d["name"] for d in model["documents"]],
            "skipped": model["skipped"],
        },
        "targets": targets,
        "counts": counts,
        "target_weight": total_weight,
        "earned_weight": earned,
        "coverage_score": score,
        "weighted_gap": gap,
        "target_score": target_score,
        "draft_only": draft_only_terms(draft_counts, model),
    }


def _no_corpus_reason(model: dict[str, Any]) -> str:
    """Why a score could not be computed — never a silent 0.0."""
    if model["n_docs"] == 0:
        skipped = "; ".join(f"{s['name']}: {s['error']}" for s in model["skipped"])
        return "no usable corpus document" + (
            f" ({len(model['skipped'])} skipped — {skipped})" if skipped else ""
        )
    return (
        f"{model['n_docs']} corpus document(s) yielded no scorable term "
        f"(min_length={model['min_length']})"
    )


# ---- family schema ----------------------------------------------------------


def _gap_message(row: dict[str, Any]) -> str:
    term, found = row["term"], row["draft_count"]
    if row["status"] == STATUS_MISSING:
        return (
            f"'{term}' is absent from the draft — used by {row['corpus_docs']} "
            f"comparison page(s), expected ~{row['expected']} mention(s)"
        )
    if row["status"] == STATUS_THIN:
        return (
            f"'{term}' appears {found}x, under the corpus-weighted minimum of "
            f"{row['minimum']} (expected ~{row['expected']})"
        )
    return (
        f"'{term}' appears {found}x against a corpus expectation of "
        f"~{row['expected']} — over-optimization risk"
    )


def to_diagnostics(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Map gaps onto the family diagnostic schema.

    One diagnostic per non-covered target term plus at most one document-level
    row: `contentgap:coverage` (warning) when the score is under target, or
    `contentgap:unmeasured` (ERROR) when there was nothing to measure against —
    an audit that could not run must not be mistaken for one that passed.
    line/col carry no meaning for a whole-document term statistic and stay 0.
    """
    path = report.get("path", "draft")
    diags = []
    for row in report.get("targets", []):
        severity = _STATUS_SEVERITY.get(row["status"])
        if severity is None:
            continue
        diags.append(
            openswap.diagnostic(
                path=path,
                line=0,
                col=0,
                rule=f"contentgap:{row['status']}",
                severity=severity,
                message=_gap_message(row),
                suggestion=(
                    f"cover '{row['term']}' ({row['minimum']}+ mentions)"
                    if row["status"] != STATUS_OVERUSED
                    else f"cut '{row['term']}' back toward ~{row['expected']}"
                ),
                source="tfidf",
            )
        )
    score = report.get("coverage_score") or {}
    target = report.get("target_score", DEFAULT_TARGET_SCORE)
    if score.get("error"):
        diags.append(
            openswap.diagnostic(
                path=path,
                line=0,
                col=0,
                rule="contentgap:unmeasured",
                severity="error",
                message=f"coverage score not measured — {score['error']}",
                source="tfidf",
            )
        )
    elif score.get("value") is not None and score["value"] < target:
        counts = report.get("counts", {})
        diags.append(
            openswap.diagnostic(
                path=path,
                line=0,
                col=0,
                rule="contentgap:coverage",
                severity="warning",
                message=(
                    f"coverage score {score['value']} below target {target} — "
                    f"{counts.get(STATUS_MISSING, 0)} missing, "
                    f"{counts.get(STATUS_THIN, 0)} thin of "
                    f"{len(report.get('targets', []))} target terms"
                ),
                source="tfidf",
            )
        )
    return openswap.sort_diagnostics(diags)


# ---- the brief (Clearscope's actual deliverable) ----------------------------


def _score_line(report: dict[str, Any]) -> str:
    score = report["coverage_score"]
    if score["error"]:
        return f"- coverage score: NOT MEASURED — {score['error']}"
    return (
        f"- coverage score: **{score['value']}** / 100 "
        f"(target {report['target_score']}, "
        f"weighted gap {report['weighted_gap']['value']})"
    )


def render_brief(report: dict[str, Any], *, title: str = "Content brief") -> str:
    """The report as a deterministic markdown brief (LF only, no timestamp).

    No clock and no host paths beyond the ones the caller passed, so the same
    inputs always render byte-identical — the file can be committed and diffed.
    The CLI writes it with write_bytes for exactly that reason: write_text would
    translate these newlines to CRLF on Windows and the artifact would diff
    against itself.
    """
    corpus = report["corpus"]
    out = [
        f"# {title}",
        "",
        f"- draft: `{report['path']}` ({report['draft_tokens']} words, "
        f"{report['draft_terms']} distinct terms)",
        f"- corpus: {corpus['n_docs']} page(s), {corpus['tokens']} words, "
        f"{corpus['unique_terms']} distinct terms"
        f"{' (phrases on)' if corpus['phrases'] else ''}",
        _score_line(report),
        f"- gaps: {report['counts'][STATUS_MISSING]} missing, "
        f"{report['counts'][STATUS_THIN]} thin, "
        f"{report['counts'][STATUS_OVERUSED]} overused, "
        f"{report['counts'][STATUS_COVERED]} covered",
        "",
        "## Target terms",
        "",
        "| term | status | weight | pages | expected | min | in draft |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["targets"]:
        out.append(
            f"| {row['term']} | {row['status']} | {row['weight']} | "
            f"{row['corpus_docs']}/{corpus['n_docs']} | {row['expected']} | "
            f"{row['minimum']} | {row['draft_count']} |"
        )
    out.extend(_brief_lists(report))
    return "\n".join(out) + "\n"


def _brief_lists(report: dict[str, Any]) -> list[str]:
    """The prose half of the brief: what to add, what to cut, what is unmatched."""
    out: list[str] = []
    for status, heading in (
        (STATUS_MISSING, "## Add (missing)"),
        (STATUS_THIN, "## Deepen (thin)"),
        (STATUS_OVERUSED, "## Cut back (overused)"),
    ):
        rows = [r for r in report["targets"] if r["status"] == status]
        if not rows:
            continue
        out.extend(["", heading, ""])
        out.extend(f"- {_gap_message(r)}" for r in rows)
    if report["corpus"]["skipped"]:
        out.extend(["", "## Corpus files skipped (not counted)", ""])
        out.extend(
            f"- `{s['name']}` — {s['error']}" for s in report["corpus"]["skipped"]
        )
    if report["draft_only"]:
        out.extend(["", "## In the draft, in no comparison page", ""])
        out.extend(f"- {r['term']} ({r['draft_count']}x)" for r in report["draft_only"])
    return out
