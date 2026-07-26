# Solo personal project, no connection to employer, built with public/free-tier only
"""Prose — pure-stdlib prose-linting core (openswap #1: Grammarly Premium).

Heuristic, data-driven linting for markdown/HTML/plain-text prose: doubled
words, a/an agreement, passive-voice markers, sentence-length outliers,
wordiness/cliche phrases, quote+space hygiene, and spellcheck (exact known-typo
map plus difflib near-miss suggestions against a wordlist). Everything here is
PURE logic — no network, no filesystem, no subprocess — mirroring the reach
split: the `prose` plugin CLI supplies real I/O and the optional harper-cli
native tier (bigbang/core/reach.py + plugins/reach/cli.py is the pattern).

Rules are data (policy-as-config): DEFAULT_RULES is the built-in policy and
`load_rules(path)` overlays a JSON file on top — dicts merge, lists extend,
scalars replace, and a bare boolean toggles `enabled` — so new org style rules
require no code edit.

Extension points:
- Per-surface rule profiles: keep one rules JSON per surface (README vs steer
  digest vs site copy) and select it with `scout prose lint --rules`; nothing
  here hardcodes a surface.
- Readability scorer (openswap table #21): DONE, and the template for the next
  one — bigbang/core/readability.py owns the Flesch/fog arithmetic, reuses the
  extraction and `passive_pattern` below instead of copying them, and plugs in
  as one `(lines, rules, path) -> [diagnostics]` entry in CHECKS. Its knobs live
  in `readability.DEFAULT_CONFIG` and are injected into `load_rules` output, so
  `scout prose rules --rules x.json` tunes it like any other rule.
- Pre-publish gate: `openswap.summarize(diags)["by_severity"]` plus
  `scout prose lint --fail-on <severity>` is the stable gate contract for all
  8 sites' copy.
- Native tier: `parse_harper_output` normalizes harper-cli findings into the
  same schema (source="harper") so merged output never branches by tier.
"""

from __future__ import annotations

import copy
import difflib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from bigbang.core import openswap

# One source of truth for lintable extensions — extension-list drift between
# core and CLI is a known bug class in this repo, so the CLI imports this.
PROSE_EXTS = (".md", ".markdown", ".html", ".htm", ".txt")

DEFAULT_RULES: dict[str, Any] = {
    "doubled_word": {
        "enabled": True,
        "severity": "warning",
        "allowed": ["that", "had", "very"],
    },
    "a_an": {
        "enabled": True,
        "severity": "warning",
        # vowel-letter words that still take "a" (consonant sound)
        "use_a": [
            "one",
            "once",
            "unicorn",
            "uniform",
            "union",
            "unique",
            "unit",
            "united",
            "university",
            "url",
            "usb",
            "usable",
            "user",
            "utility",
            "uuid",
            "european",
            "ui",
        ],
        # consonant-letter words that take "an" (vowel sound / silent h)
        "use_an": [
            "heir",
            "herb",
            "honest",
            "honor",
            "hour",
            "html",
            "http",
            "faq",
            "mba",
            "rss",
            "sql",
            "xml",
        ],
    },
    "passive_voice": {
        "enabled": True,
        "severity": "suggestion",
        "irregular_participles": [
            "begun",
            "broken",
            "brought",
            "bought",
            "built",
            "caught",
            "chosen",
            "done",
            "drawn",
            "driven",
            "eaten",
            "fallen",
            "felt",
            "forgotten",
            "found",
            "frozen",
            "given",
            "gotten",
            "grown",
            "held",
            "hidden",
            "kept",
            "known",
            "led",
            "left",
            "lost",
            "made",
            "meant",
            "paid",
            "put",
            "read",
            "run",
            "said",
            "seen",
            "sent",
            "set",
            "shown",
            "spoken",
            "stolen",
            "taken",
            "taught",
            "thought",
            "told",
            "understood",
            "worn",
            "written",
        ],
        # -ed words that are not participles (adjectives/nouns) — never flag
        "not_participles": [
            "red",
            "bed",
            "fed",
            "led",
            "wed",
            "shed",
            "need",
            "speed",
            "indeed",
            "exceed",
            "proceed",
            "succeed",
            "hundred",
            "sacred",
            "wicked",
            "naked",
        ],
    },
    "sentence_length": {"enabled": True, "severity": "info", "max_words": 35},
    "wordiness": {
        "enabled": True,
        "severity": "suggestion",
        # phrase -> replacement ("" means: usually deletable)
        "phrases": {
            "a large number of": "many",
            "at the end of the day": "ultimately",
            "at this point in time": "now",
            "due to the fact that": "because",
            "each and every": "every",
            "first and foremost": "first",
            "for the purpose of": "to",
            "in close proximity": "near",
            "in order to": "to",
            "in spite of the fact that": "although",
            "in the event that": "if",
            "it goes without saying": "",
            "needless to say": "",
            "on a daily basis": "daily",
            "take into consideration": "consider",
            "the vast majority of": "most",
            "utilize": "use",
            "very unique": "unique",
            "with regard to": "about",
        },
    },
    "hygiene": {"enabled": True, "severity": "info"},
    "misspelling": {
        "enabled": True,
        "severity": "warning",
        # exact known typo -> correction (high precision, day-one useful)
        "map": {
            "accomodate": "accommodate",
            "acheive": "achieve",
            "adress": "address",
            "arguement": "argument",
            "becuase": "because",
            "begining": "beginning",
            "beleive": "believe",
            "calender": "calendar",
            "commited": "committed",
            "concious": "conscious",
            "definately": "definitely",
            "dependant": "dependent",
            "enviroment": "environment",
            "existance": "existence",
            "familar": "familiar",
            "finaly": "finally",
            "foriegn": "foreign",
            "gaurd": "guard",
            "goverment": "government",
            "happend": "happened",
            "immediatly": "immediately",
            "independant": "independent",
            "intrest": "interest",
            "knowlege": "knowledge",
            "liason": "liaison",
            "libary": "library",
            "maintainance": "maintenance",
            "neccessary": "necessary",
            "noticable": "noticeable",
            "occassion": "occasion",
            "occured": "occurred",
            "publically": "publicly",
            "realy": "really",
            "recieve": "receive",
            "recomend": "recommend",
            "refered": "referred",
            "relevent": "relevant",
            "seperate": "separate",
            "seperately": "separately",
            "succesful": "successful",
            "suprise": "surprise",
            "teh": "the",
            "tommorow": "tomorrow",
            "truely": "truly",
            "untill": "until",
            "wich": "which",
            "wierd": "weird",
            "writting": "writing",
        },
    },
    "spellcheck": {
        "enabled": True,
        "severity": "suggestion",
        "min_len": 6,
        "cutoff": 0.86,
        # correct forms for difflib near-miss ("did you mean") — curated small
        # on purpose: candidates come only FROM this list, so a small list
        # keeps precision high (unknown jargon simply matches nothing).
        "wordlist": [
            "address",
            "argument",
            "because",
            "beginning",
            "believe",
            "business",
            "calendar",
            "committed",
            "company",
            "complete",
            "conscious",
            "consider",
            "continue",
            "default",
            "definitely",
            "dependent",
            "develop",
            "different",
            "document",
            "environment",
            "example",
            "existence",
            "experience",
            "familiar",
            "feature",
            "finally",
            "foreign",
            "function",
            "general",
            "government",
            "however",
            "important",
            "include",
            "independent",
            "information",
            "install",
            "interest",
            "knowledge",
            "language",
            "library",
            "maintenance",
            "manage",
            "message",
            "module",
            "necessary",
            "network",
            "noticeable",
            "number",
            "occasion",
            "occurred",
            "option",
            "output",
            "package",
            "people",
            "performance",
            "platform",
            "possible",
            "present",
            "problem",
            "process",
            "produce",
            "product",
            "program",
            "project",
            "provide",
            "public",
            "publicly",
            "purpose",
            "question",
            "really",
            "receive",
            "recommend",
            "referred",
            "release",
            "relevant",
            "remember",
            "replace",
            "request",
            "require",
            "research",
            "response",
            "result",
            "return",
            "review",
            "schedule",
            "science",
            "section",
            "security",
            "separate",
            "service",
            "session",
            "setting",
            "should",
            "similar",
            "simple",
            "source",
            "special",
            "specific",
            "standard",
            "statement",
            "structure",
            "success",
            "successful",
            "suggest",
            "support",
            "surface",
            "surprise",
            "system",
            "technical",
            "template",
            "thought",
            "through",
            "together",
            "tomorrow",
            "understand",
            "update",
            "upgrade",
            "validate",
            "value",
            "version",
            "warning",
            "website",
            "without",
            "workflow",
            "writing",
        ],
    },
}


def load_rules(path: str | None = None) -> dict[str, Any]:
    """DEFAULT_RULES overlaid with an optional JSON file.

    Merge semantics: dicts merge key-by-key, lists extend (deduped, order
    kept), scalars replace, and a bare boolean is shorthand for
    {"enabled": bool}. Raises ValueError / OSError / json errors for the CLI
    to convert into a fail_agent envelope.
    """
    rules = copy.deepcopy(DEFAULT_RULES)
    # Readability (#21) owns its own thresholds; injected here so it appears in
    # `prose rules`, accepts the same JSON overlay as every other rule, and is
    # never duplicated in two policy tables. Local import: readability imports
    # this module for extraction, so a module-level import would be a cycle.
    from bigbang.core import readability

    rules["readability"] = copy.deepcopy(readability.DEFAULT_CONFIG)
    if not path:
        return rules
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("rules file must be a JSON object of {rule_id: config}")
    for rid, cfg in raw.items():
        base = rules.setdefault(rid, {})
        if isinstance(cfg, bool):
            base["enabled"] = cfg
            continue
        if not isinstance(cfg, dict):
            raise ValueError(f"rule {rid!r}: config must be an object or boolean")
        for k, v in cfg.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k].update(v)
            elif isinstance(v, list) and isinstance(base.get(k), list):
                base[k] = base[k] + [x for x in v if x not in base[k]]
            else:
                base[k] = v
    return rules


# ---- extraction -------------------------------------------------------------
# Non-prose spans are replaced with a \x00 sentinel of equal length: it is
# neither a word char nor whitespace, so it can't fabricate doubled words,
# double spaces, or spellcheck tokens, while columns stay real.

_SENTINEL = "\x00"
_NBSP = " "
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_LINK_URL_RE = re.compile(r"\]\([^)\s]+")
_BARE_URL_RE = re.compile(r"https?://\S+")
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def _blank(m: re.Match) -> str:
    return _SENTINEL * len(m.group(0))


def extract_markdown(text: str) -> list[str]:
    """Markdown -> prose lines (code/urls blanked, line+col positions kept)."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence:
            out.append("")
            continue
        s = _INLINE_CODE_RE.sub(_blank, line)
        s = _LINK_URL_RE.sub(lambda m: "](" + _SENTINEL * (len(m.group(0)) - 2), s)
        s = _BARE_URL_RE.sub(_blank, s)
        s = _HTML_TAG_RE.sub(_blank, s)
        out.append(s)
    return out


class _HTMLProse(HTMLParser):
    _SKIP = {"script", "style", "code", "pre", "kbd", "samp"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.lines: dict[int, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        line, _col = self.getpos()
        for i, chunk in enumerate(data.splitlines()):
            if chunk.strip():
                self.lines.setdefault(line + i, []).append(chunk.strip())


def extract_html(text: str) -> list[str]:
    """HTML -> prose lines via html.parser (script/style/code skipped).

    Line numbers are real (parser getpos); columns are approximate (1).
    """
    p = _HTMLProse()
    try:
        p.feed(text)
        p.close()
    except Exception:
        pass  # malformed HTML: lint whatever was parsed before the error
    n = len(text.splitlines())
    return [" ".join(p.lines.get(i, [])) for i in range(1, n + 1)]


def detect_format(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in (".md", ".markdown"):
        return "markdown"
    if suffix in (".html", ".htm"):
        return "html"
    return "text"


# ---- checks -----------------------------------------------------------------

# public: the readability scorer (#21) tokenizes with the SAME word definition
WORD_RE = re.compile(r"\b\w[\w'-]*\b")
_DOUBLE_RE = re.compile(r"\b([A-Za-z]+)[ \t]+\1\b", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"\b(a|an)\s+([A-Za-z][A-Za-z'-]*)", re.IGNORECASE)
_DOUBLE_SPACE_RE = re.compile(r"(?<=\S) {2,}(?=\S)")
_TOKEN_RE = re.compile(r"\b[A-Za-z][a-z'-]+\b")
_LOWER_TOKEN_RE = re.compile(r"\b[a-z]+\b")
# words after a/an that are grammar, not the noun being introduced
_ARTICLE_STOP = {"is", "are", "was", "were", "and", "or", "if", "of"}


def _check_doubled_word(lines: list[str], rules: dict, path: str) -> list[dict]:
    cfg = rules.get("doubled_word", {})
    if not cfg.get("enabled"):
        return []
    allowed = {w.lower() for w in cfg.get("allowed", [])}
    out = []
    for i, line in enumerate(lines, 1):
        for m in _DOUBLE_RE.finditer(line):
            word = m.group(1)
            if word.lower() in allowed:
                continue
            out.append(
                openswap.diagnostic(
                    path=path,
                    line=i,
                    col=m.start() + 1,
                    rule="doubled_word",
                    severity=cfg.get("severity", "warning"),
                    message=f"doubled word '{word}'",
                    suggestion=word,
                )
            )
    return out


def _check_a_an(lines: list[str], rules: dict, path: str) -> list[dict]:
    cfg = rules.get("a_an", {})
    if not cfg.get("enabled"):
        return []
    use_a = {w.lower() for w in cfg.get("use_a", [])}
    use_an = {w.lower() for w in cfg.get("use_an", [])}
    out = []
    for i, line in enumerate(lines, 1):
        for m in _ARTICLE_RE.finditer(line):
            art, word = m.group(1), m.group(2)
            wl = word.lower()
            if wl in _ARTICLE_STOP:
                continue
            if word.isupper() and len(word) <= 5:
                continue  # acronym: spoken form is unknowable from spelling
            if wl in use_a:
                expected = "a"
            elif wl in use_an:
                expected = "an"
            else:
                expected = "an" if wl[0] in "aeiou" else "a"
            if art.lower() != expected:
                fix = expected.capitalize() if art[0].isupper() else expected
                out.append(
                    openswap.diagnostic(
                        path=path,
                        line=i,
                        col=m.start(1) + 1,
                        rule="a_an",
                        severity=cfg.get("severity", "warning"),
                        message=f"'{art} {word}' — use '{fix}'",
                        suggestion=fix,
                    )
                )
    return out


def passive_pattern(cfg: dict[str, Any]) -> re.Pattern[str]:
    """Compiled "be + past participle" matcher for a passive_voice rule config.

    Public because the readability scorer (#21) reports a passive RATIO over the
    same constructions this rule flags: two regexes would eventually disagree,
    and then one of the two numbers would be wrong with no way to tell which.
    """
    parts = [r"[A-Za-z]{2,}ed"]
    parts.extend(re.escape(w) for w in cfg.get("irregular_participles", []))
    return re.compile(
        r"\b(?:am|is|are|was|were|be|been|being)\s+(" + "|".join(parts) + r")\b",
        re.IGNORECASE,
    )


def _check_passive_voice(lines: list[str], rules: dict, path: str) -> list[dict]:
    cfg = rules.get("passive_voice", {})
    if not cfg.get("enabled"):
        return []
    not_participles = {w.lower() for w in cfg.get("not_participles", [])}
    pat = passive_pattern(cfg)
    out = []
    for i, line in enumerate(lines, 1):
        for m in pat.finditer(line):
            if m.group(1).lower() in not_participles:
                continue
            out.append(
                openswap.diagnostic(
                    path=path,
                    line=i,
                    col=m.start() + 1,
                    rule="passive_voice",
                    severity=cfg.get("severity", "suggestion"),
                    message=f"passive voice: '{m.group(0)}' — prefer an active subject",
                )
            )
    return out


def paragraphs(lines: list[str]):
    """Blank-line-separated paragraphs as (first_line_number, joined_text).

    Public: the readability scorer (#21) needs the identical paragraph boundaries
    so a per-paragraph grade and a sentence_length finding can never point at
    different text.
    """
    start, buf = None, []
    for i, line in enumerate(lines, 1):
        if line.strip():
            if start is None:
                start = i
            buf.append(line.strip())
        else:
            if buf:
                yield start, " ".join(buf)
            start, buf = None, []
    if buf:
        yield start, " ".join(buf)


def _check_sentence_length(lines: list[str], rules: dict, path: str) -> list[dict]:
    cfg = rules.get("sentence_length", {})
    if not cfg.get("enabled"):
        return []
    limit = int(cfg.get("max_words", 35))
    out = []
    for start, text in paragraphs(lines):
        for sent in re.split(r"(?<=[.!?])\s+", text):
            n = len(WORD_RE.findall(sent))
            if n > limit:
                out.append(
                    openswap.diagnostic(
                        path=path,
                        line=start,
                        col=1,
                        rule="sentence_length",
                        severity=cfg.get("severity", "info"),
                        message=f"{n}-word sentence (limit {limit}) — consider splitting",
                    )
                )
    return out


def _check_wordiness(lines: list[str], rules: dict, path: str) -> list[dict]:
    cfg = rules.get("wordiness", {})
    if not cfg.get("enabled"):
        return []
    compiled = [
        (phrase, repl, re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE))
        for phrase, repl in cfg.get("phrases", {}).items()
    ]
    out = []
    for i, line in enumerate(lines, 1):
        for phrase, repl, pat in compiled:
            for m in pat.finditer(line):
                tail = f" -> '{repl}'" if repl else " — usually deletable"
                out.append(
                    openswap.diagnostic(
                        path=path,
                        line=i,
                        col=m.start() + 1,
                        rule="wordiness",
                        severity=cfg.get("severity", "suggestion"),
                        message=f"wordy: '{phrase}'{tail}",
                        suggestion=repl or None,
                    )
                )
    return out


def _check_hygiene(lines: list[str], rules: dict, path: str) -> list[dict]:
    cfg = rules.get("hygiene", {})
    if not cfg.get("enabled"):
        return []
    sev = cfg.get("severity", "info")
    out = []
    for i, line in enumerate(lines, 1):
        # markdown table rows legitimately align with runs of spaces
        if not line.lstrip().startswith("|"):
            for m in _DOUBLE_SPACE_RE.finditer(line):
                out.append(
                    openswap.diagnostic(
                        path=path,
                        line=i,
                        col=m.start() + 1,
                        rule="hygiene",
                        severity=sev,
                        message="multiple consecutive spaces",
                    )
                )
        if _NBSP in line:
            out.append(
                openswap.diagnostic(
                    path=path,
                    line=i,
                    col=line.index(_NBSP) + 1,
                    rule="hygiene",
                    severity=sev,
                    message="non-breaking space (U+00A0) in prose",
                )
            )
        if '"' in line and ("“" in line or "”" in line):
            out.append(
                openswap.diagnostic(
                    path=path,
                    line=i,
                    col=1,
                    rule="hygiene",
                    severity=sev,
                    message="mixed straight and curly double quotes on one line",
                )
            )
    return out


def _check_misspelling(lines: list[str], rules: dict, path: str) -> list[dict]:
    cfg = rules.get("misspelling", {})
    if not cfg.get("enabled"):
        return []
    mapping = {k.lower(): v for k, v in cfg.get("map", {}).items()}
    out = []
    for i, line in enumerate(lines, 1):
        for m in _TOKEN_RE.finditer(line):
            tok = m.group(0)
            tl = tok.lower()
            hit = mapping.get(tl)
            if hit is None:
                for suf in ("s", "es", "d", "ed", "ing", "ly"):
                    if tl.endswith(suf) and tl[: -len(suf)] in mapping:
                        hit = mapping[tl[: -len(suf)]]
                        break
            if hit:
                out.append(
                    openswap.diagnostic(
                        path=path,
                        line=i,
                        col=m.start() + 1,
                        rule="misspelling",
                        severity=cfg.get("severity", "warning"),
                        message=f"'{tok}' -> '{hit}'",
                        suggestion=hit,
                    )
                )
    return out


def _known(tok: str, wordset: set[str]) -> bool:
    if tok in wordset:
        return True
    for suf in ("s", "es", "ed", "d", "ing", "ly", "er", "est"):
        if tok.endswith(suf) and tok[: -len(suf)] in wordset:
            return True
    if tok.endswith("ing") and tok[:-3] + "e" in wordset:
        return True
    return tok.endswith("ies") and tok[:-3] + "y" in wordset


def _check_spellcheck(lines: list[str], rules: dict, path: str) -> list[dict]:
    cfg = rules.get("spellcheck", {})
    if not cfg.get("enabled"):
        return []
    words = [w.lower() for w in cfg.get("wordlist", [])]
    wordset = set(words)
    mapping = rules.get("misspelling", {}).get("map", {})
    handled = {k.lower() for k in mapping} | {str(v).lower() for v in mapping.values()}
    min_len = int(cfg.get("min_len", 6))
    cutoff = float(cfg.get("cutoff", 0.86))
    seen: set[str] = set()  # each token judged once per file; caches negatives too
    out = []
    for i, line in enumerate(lines, 1):
        for m in _LOWER_TOKEN_RE.finditer(line):
            tok = m.group(0)
            if len(tok) < min_len or tok in seen or tok in handled:
                continue
            seen.add(tok)
            if _known(tok, wordset):
                continue
            cand = difflib.get_close_matches(tok, words, n=1, cutoff=cutoff)
            # same-first-letter guard: classic precision constraint for typos
            if cand and cand[0] != tok and cand[0][0] == tok[0]:
                out.append(
                    openswap.diagnostic(
                        path=path,
                        line=i,
                        col=m.start() + 1,
                        rule="spellcheck",
                        severity=cfg.get("severity", "suggestion"),
                        message=f"'{tok}' — did you mean '{cand[0]}'?",
                        suggestion=cand[0],
                    )
                )
    return out


def _check_readability(lines: list[str], rules: dict, path: str) -> list[dict]:
    """Readability (#21) as a lint rule — grade over target, hard sentences, budgets.

    A thin adapter on purpose: the arithmetic lives in core/readability.py, and
    the import is LOCAL because that module imports this one for extraction. It
    is registered in CHECKS below rather than appended by whoever happens to
    import readability first — an import-order-dependent rule would silently
    vanish from `prose lint`, which is the one failure mode a linter must not have.
    """
    from bigbang.core import readability

    return readability.readability_check(lines, rules, path)


# Ordered check registry. Adding a rule = one `(lines, rules, path) ->
# [diagnostics]` function plus its entry here (see _check_readability).
CHECKS = [
    _check_doubled_word,
    _check_a_an,
    _check_passive_voice,
    _check_sentence_length,
    _check_wordiness,
    _check_hygiene,
    _check_misspelling,
    _check_spellcheck,
    _check_readability,
]


def lint_text(
    text: str,
    *,
    path: str = "<text>",
    fmt: str = "markdown",
    rules: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run every enabled check; return sorted normalized diagnostics."""
    rules = rules or load_rules(None)
    if fmt == "markdown":
        lines = extract_markdown(text)
    elif fmt == "html":
        lines = extract_html(text)
    else:
        lines = text.splitlines()
    diags: list[dict[str, Any]] = []
    for check in CHECKS:
        diags.extend(check(lines, rules, path))
    return openswap.sort_diagnostics(diags)


def parse_harper_output(raw: str, *, path: str) -> list[dict[str, Any]]:
    """Normalize harper-cli machine output into the openswap schema.

    harper's exact machine format is not pinned here (the binary is verified
    absent on this box), so parsing is tolerant: a JSON array, or an object
    with a "lints" list, of objects carrying line/rule/message under a few
    plausible key names. Anything unparseable is dropped — the heuristic core
    already produced its own findings, so a bad parse degrades, never crashes.
    """
    try:
        body = json.loads(raw)
    except Exception:
        return []
    items = body.get("lints", []) if isinstance(body, dict) else body
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        msg = it.get("message") or it.get("problem") or it.get("description")
        if not msg:
            continue
        try:
            span = it.get("span") if isinstance(it.get("span"), dict) else {}
            line = int(
                it.get("line") or it.get("start_line") or span.get("start_line") or 1
            )
            col = int(it.get("col") or it.get("column") or 1)
            rule = str(
                it.get("lint_kind") or it.get("kind") or it.get("rule") or "lint"
            ).lower()
            sugg = it.get("suggestions")
            suggestion = str(sugg[0]) if isinstance(sugg, list) and sugg else None
            out.append(
                openswap.diagnostic(
                    path=path,
                    line=line,
                    col=col,
                    rule=f"harper:{rule}",
                    severity="warning",
                    message=str(msg),
                    suggestion=suggestion,
                    source="harper",
                )
            )
        except Exception:
            continue
    return out
