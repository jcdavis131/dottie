"""Document cleaning: pure, independently-testable quality heuristics.

Every function here is a *pure* function of its inputs — no I/O, no globals, no
hidden state — so each can be unit-tested against known-good / known-bad
fixtures in isolation. The curator wires them together in a fixed order
(normalize -> is_english -> gopher_quality -> edu_score_ok -> scrub_pii); the
ordering lives in ``curator.py``, not here.

Design stance
-------------
These are *cheap, no-network* heuristics. We deliberately accept false
negatives (dropping a good doc) over false positives (keeping garbage), because
the corpus is large and the training budget is the scarce resource: it is
always better to train on slightly less, cleaner data.

PII scrubbing in particular is intentionally *conservative*: it would rather
leave a borderline token alone than mangle a code snippet or a math expression,
because corrupting code/math silently poisons capability evals. See
``scrub_pii`` for the explicit list of what we do and do not touch.
"""

from __future__ import annotations

import unicodedata

import regex as re

# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------

# Any Unicode "Other" char (Cc control, Cf format, Co private-use, Cs surrogate,
# Cn unassigned). \n and \t are Cc but we keep them (handled in the lambda).
_CTRL_RE = re.compile(r"\p{C}")
# Horizontal whitespace runs (spaces, tabs, NBSP, ...) but NOT newlines.
_HWS_RE = re.compile(r"[^\S\n]+")
_TRAIL_WS_RE = re.compile(r"[^\S\n]+\n")
_BLANKLINES_RE = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    """Canonicalize text for hashing / dedup / training.

    Steps: Unicode NFC -> strip control/format chars (keep ``\\n`` ``\\t``) ->
    collapse horizontal whitespace runs to a single space -> strip trailing
    horizontal whitespace on each line -> collapse 3+ consecutive newlines to a
    blank-line separator (``\\n\\n``) -> strip leading/trailing whitespace.

    Idempotent: ``normalize(normalize(x)) == normalize(x)``.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = _CTRL_RE.sub(lambda m: m.group(0) if m.group(0) in "\n\t" else "", text)
    text = text.replace("\t", " ")
    text = _HWS_RE.sub(" ", text)
    text = _TRAIL_WS_RE.sub("\n", text)
    text = _BLANKLINES_RE.sub("\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# is_english
# ---------------------------------------------------------------------------

#: A small, high-frequency English function-word set. Presence of several of
#: these is a strong cheap signal of running English prose.
ENGLISH_STOPWORDS = frozenset(
    "the be to of and a in that have i it for not on with he as you do at this "
    "but his by from they we say her she or an will my one all would there their "
    "what so up out if about who get which go me when make can like time no just "
    "him know take people into year your good some could them see other than then "
    "now look only come its over think also back after use two how our work first "
    "well way even new want because any these give day most us is are was were of".split()
)

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)  # letters only, no digits/underscore


def is_english(text: str, *, min_latin_ratio: float = 0.85, min_stopwords: int = 2) -> bool:
    """Cheap English-language heuristic — no network, no model.

    Two signals combined:
      1. *Latin/ASCII ratio*: fraction of alphabetic characters that are Latin
         (a-z / A-Z, incl. accented Latin). Filters CJK / Cyrillic / Arabic etc.
      2. *Stopword hit test*: at least ``min_stopwords`` distinct high-frequency
         English function words appear.

    False-negative risk (documented, accepted): very short English snippets, or
    English that is almost entirely code / math / tables (few function words),
    can be rejected. Because the corpus is large we prefer that over admitting
    e.g. Latin-script non-English text (Spanish, German) that happens to share a
    couple of function words — the ratio test alone would let those through, so
    we require BOTH signals. Spanish/French can still slip through when they
    share stopwords like "a"/"no"/"me"; this heuristic is a coarse filter, not a
    language ID model.
    """
    if not text:
        return False
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return False
    latin = 0
    for c in alpha:
        # 'LATIN' name prefix covers ASCII + accented Latin letters.
        try:
            if unicodedata.name(c).startswith("LATIN"):
                latin += 1
        except ValueError:
            pass
    latin_ratio = latin / len(alpha)
    if latin_ratio < min_latin_ratio:
        return False

    words = {w.lower() for w in _WORD_RE.findall(text)}
    hits = len(words & ENGLISH_STOPWORDS)
    return hits >= min_stopwords


# ---------------------------------------------------------------------------
# gopher_quality
# ---------------------------------------------------------------------------

_GOPHER_STOPWORDS = ("the", "be", "to", "of", "and", "that", "have", "with")
_BULLET_CHARS = ("*", "-", "•", "·", "‣", "◦", "–", "—", "#")


def gopher_quality(text: str) -> tuple[bool, str]:
    """Gopher-style document quality filter.

    Returns ``(ok, reason)`` where ``reason`` is "" when ok, else a short slug
    naming the first failed rule (used for the per-stage reject histogram).

    Rules (Rae et al. 2021, adapted):
      * word count in [50, 100_000];
      * mean word length in [3, 10];
      * symbol-to-word ratio (# and …) < 0.1;
      * fraction of lines starting with a bullet < 0.9;
      * fraction of lines ending with an ellipsis < 0.3;
      * >= 80% of lines contain at least one alphabetic char;
      * at least 2 of the stopwords {the, be, to, of, and, that, have, with}.
    """
    words = text.split()
    n = len(words)
    if n < 50:
        return False, "too_short"
    if n > 100_000:
        return False, "too_long"

    mean_wl = sum(len(w) for w in words) / n
    if not (3.0 <= mean_wl <= 10.0):
        return False, "mean_word_len"

    n_symbols = text.count("#") + text.count("…") + text.count("...")
    if n_symbols / n >= 0.1:
        return False, "symbol_ratio"

    lines = [ln for ln in text.split("\n") if ln.strip()]
    if lines:
        bullet_lines = sum(1 for ln in lines if ln.lstrip().startswith(_BULLET_CHARS))
        if bullet_lines / len(lines) >= 0.9:
            return False, "bullet_lines"

        ellipsis_lines = sum(
            1 for ln in lines if ln.rstrip().endswith("…") or ln.rstrip().endswith("...")
        )
        if ellipsis_lines / len(lines) >= 0.3:
            return False, "ellipsis_lines"

        alpha_lines = sum(1 for ln in lines if any(c.isalpha() for c in ln))
        if alpha_lines / len(lines) < 0.8:
            return False, "non_alpha_lines"

    lower = text.lower()
    lw = set(re.findall(r"[a-z]+", lower))
    if sum(1 for s in _GOPHER_STOPWORDS if s in lw) < 2:
        return False, "no_stopwords"

    return True, ""


# ---------------------------------------------------------------------------
# edu_score_ok
# ---------------------------------------------------------------------------

#: Per-phase minimum fineweb-edu score. Only the phases with an explicit
#: threshold gate on score; all others admit any score.
DEFAULT_EDU_THRESHOLDS: dict[int, float] = {2: 2.0, 5: 4.5}


def edu_score_ok(meta: dict | None, phase: int, thresholds: dict[int, float] | None = None) -> bool:
    """Apply per-phase fineweb-edu score thresholds.

    ``meta`` may carry a numeric ``"score"`` (fineweb-edu classifier output). A
    **missing** score passes unconditionally — synthetic generators emit no
    score and must not be gated by an edu classifier they never ran through.

    ``phase`` is the integer curriculum phase. ``thresholds`` maps phase ->
    minimum score (defaults to P2>=2.0, P5>=4.5).
    """
    if thresholds is None:
        thresholds = DEFAULT_EDU_THRESHOLDS
    threshold = thresholds.get(phase)
    if threshold is None:
        return True
    if not meta:
        return True
    score = meta.get("score")
    if score is None:
        return True
    try:
        return float(score) >= threshold
    except (TypeError, ValueError):
        return True


# ---------------------------------------------------------------------------
# scrub_pii
# ---------------------------------------------------------------------------

# NOTE on ordering: specific, high-confidence secret shapes (sk-..., AKIA...)
# run BEFORE the generic long-blob rules so they get their own placeholder and
# aren't double-processed. Emails/IPs/phones are structurally distinct and
# order-independent.

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# OpenAI-style key: sk- followed by >=20 base62 chars.
_SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
# AWS access key id: AKIA + 16 uppercase alphanumerics.
_AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

# Generic hex secret: >=32 hex chars, NOT a 0x-prefixed C/asm literal.
_HEX_SECRET_RE = re.compile(r"(?<![0-9A-Za-z])(?<!0x)(?<!0X)[0-9a-fA-F]{32,}(?![0-9A-Za-z])")
# Generic base64-ish secret: >=32 chars that mix letters AND digits (so plain
# long words, which have no digits, are left alone). Conservative on purpose.
_B64_SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9+/])"
    r"(?=[A-Za-z0-9+/]*[0-9])(?=[A-Za-z0-9+/]*[A-Za-z])"
    r"[A-Za-z0-9+/]{32,}={0,2}"
    r"(?![A-Za-z0-9+/=])"
)

# IPv4 dotted quad.
_IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
# IPv6: require >=4 colon-separated hextets, or a "::" compression, to avoid
# eating time-like "12:34:56:78" (decimal, no hex letters is still ambiguous —
# we accept that as a rare false positive; a mangled timestamp is harmless
# relative to a leaked address).
_IPV6_RE = re.compile(
    r"(?<![:.\w])(?:"
    r"(?:[0-9A-Fa-f]{1,4}:){4,7}[0-9A-Fa-f]{1,4}"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,7}:"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}"
    r"|::(?:[0-9A-Fa-f]{1,4}:){0,5}[0-9A-Fa-f]{1,4}"
    r")(?![:.\w])"
)
# Phone: require separators so we do NOT match bare 10-digit ids or math. The
# boundaries are digit/word based (not ".") so a trailing sentence period does
# not defeat the match, while a longer digit run still does.
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[-.\s])?(?:\(\d{3}\)\s?|\d{3}[-.\s])\d{3}[-.\s]\d{4}(?!\d)"
)


def scrub_pii(text: str) -> str:
    """Replace high-confidence PII / secret shapes with stable placeholders.

    Replaced (each with a fixed placeholder token so the model learns the
    *shape* is redacted rather than seeing garbage):
      * emails                -> ``<|email|>``
      * OpenAI ``sk-`` keys, AWS ``AKIA`` keys, and long (>=32) hex/base64
        secret blobs -> ``<|key|>``
      * IPv4 and IPv6 addresses -> ``<|ip|>``
      * separator-delimited phone numbers -> ``<|phone|>``

    Deliberately NOT scrubbed (conservative, to avoid mangling code/math):
      * personal names, street addresses, dates, ZIP codes;
      * short hex literals such as ``0xDEADBEEF`` (the ``0x`` lookbehind and the
        >=32 length floor both protect these);
      * bare digit runs (credit-card / SSN shapes, numeric ids, math) — matching
        these reliably needs Luhn/context we won't risk here, and a false
        positive that rewrites a number inside a math proof is worse than a
        missed card number in a corpus we control.

    A false negative (a slipped-through secret) is strictly preferred over a
    false positive that corrupts a code or math token.
    """
    text = _EMAIL_RE.sub("<|email|>", text)
    text = _SK_KEY_RE.sub("<|key|>", text)
    text = _AWS_KEY_RE.sub("<|key|>", text)
    text = _HEX_SECRET_RE.sub("<|key|>", text)
    text = _B64_SECRET_RE.sub("<|key|>", text)
    text = _IPV6_RE.sub("<|ip|>", text)
    text = _IPV4_RE.sub("<|ip|>", text)
    text = _PHONE_RE.sub("<|phone|>", text)
    return text
