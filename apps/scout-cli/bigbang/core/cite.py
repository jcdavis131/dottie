# Solo personal project, no connection to employer, built with public/free-tier only
"""Cite — BibTeX/CSL-lite store + deterministic formatter (openswap #33: Zotero).

The paid thing being replaced is not the Zotero *reader* (that is free and
local) — it is the STORAGE/SYNC tier and the hosted "citation API" services
around it: your library, your unpublished reading list and your draft
bibliography living in someone else's database, metered by gigabyte. This
adapter keeps the library in a local sqlite file and renders the bibliography
with arithmetic, so the manifest disables the network axis entirely and "the
reading list never left the box" is architectural rather than a ToS promise.

Everything deterministic lives here: the brace-aware BibTeX tokenizer, the
LaTeX-accent decoder, BibTeX name splitting (all three comma forms plus von
particles), the sqlite store, the CSL-JSON mapping and five deterministic
output styles. The plugin CLI owns the ONE real I/O (reading a local .bib/.json
file) plus the fs_write gate on the store, and nothing else.

ROUND-TRIP FIDELITY IS THE CONTRACT, and it is enforced in three places rather
than asserted in a docstring:

[1] Parse keeps EVERY field, including fields no style knows how to render, and
    keeps `field_order` so re-emission is not a re-sort. Unknown entry types are
    kept verbatim with a warning; they are not coerced to @misc, because
    coercion is exactly the silent edit this module exists to prevent.
[2] A malformed entry is REPORTED AND REJECTED, never half-imported. Rejected
    entries come back in their own list with the reason, the line number and the
    raw text, so the operator fixes the .bib instead of discovering three fields
    went missing a month later. `REJECTING_RULES` names them, and a rules
    overlay is FORBIDDEN from disabling one — a data-integrity rule is not a
    style preference (see load_rules).
[3] `roundtrip_report` does the actual experiment: emit the stored entry, parse
    the emission back, and diff type/key/fields/order. `lost_fields` is measured,
    not promised. The store keeps the original entry text next to the normalized
    field rows so the diff can be run against what was really on disk.

Honesty rules that shape the code:
- A rendering has EITHER `text` OR `error`, never both, never neither. A missing
  REQUIRED field for the entry type is an error naming the fields, not a string
  with a hole in it. Missing OPTIONAL fields are listed in `omitted`, so a short
  reference is visibly short rather than quietly short.
- A missing date renders as the CSL-standard `n.d.` — a LABELLED absence, and it
  is also reported in `omitted`. Nothing is ever guessed from the URL, the key
  or the file mtime.
- Value normalization on re-emission is limited to the delimiter (`"x"` and
  `{x}` denote the same value) and is documented as such; @string macros are
  expanded at parse time and each use is recorded in `macros`, so the expansion
  is visible instead of being a silent rewrite.

Stated limits (SCOPE_LIMITS ships in the payload of every command):
- No PDF ingestion and no metadata lookup by DOI/ISBN — both need the network
  this adapter deletes. A DOI is validated for SHAPE and never resolved.
- Five built-in styles, not the 10k-entry CSL style repository: there is no
  .csl XML interpreter here, and `rules` says so.
- @crossref inheritance is NOT resolved (reported as cite:crossref-unresolved).
- Author lists are never truncated to "et al." — a truncation rule differs per
  style edition and a wrong one is a fabricated citation.
- Sorting is a plain lowercase compare, not locale collation.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any

from bigbang.core import openswap

SCOPE_LIMITS = (
    "local .bib/.csl-json files only: no PDF ingestion, no DOI/ISBN metadata "
    "lookup (that needs the network this adapter deletes — a DOI is shape-checked, "
    "never resolved), no .csl XML style interpreter (five built-in styles), no "
    "@crossref inheritance, no 'et al.' truncation, and sorting is a lowercase "
    "compare rather than locale collation"
)

# ---- rules ------------------------------------------------------------------

# Every problem this module can report, with the severity it maps onto in the
# family diagnostic schema. `rejects` marks the ones that refuse the entry: a
# partially imported reference is worse than a loudly refused one.
RULES: dict[str, dict[str, Any]] = {
    "cite:unterminated-entry": {
        "severity": "error",
        "rejects": True,
        "what": "an @entry body was never closed — the remainder of the file cannot be trusted and is not imported",
    },
    "cite:missing-key": {
        "severity": "error",
        "rejects": True,
        "what": "the entry has no citation key (or the first element is a field assignment)",
    },
    "cite:duplicate-key": {
        "severity": "error",
        "rejects": True,
        "what": "a second entry reuses a citation key already seen in this file; the first wins and the second is refused",
    },
    "cite:duplicate-field": {
        "severity": "error",
        "rejects": True,
        "what": "the same field name appears twice in one entry; choosing a winner would be silent data loss",
    },
    "cite:malformed-field": {
        "severity": "error",
        "rejects": True,
        "what": "a field element has no `name = value` shape, or the name is not a BibTeX identifier",
    },
    "cite:malformed-value": {
        "severity": "error",
        "rejects": True,
        "what": "a field value is not a braced/quoted string, a number or a macro reference",
    },
    "cite:missing-body": {
        "severity": "error",
        "rejects": True,
        "what": "an @type was not followed by a { or ( body",
    },
    "cite:bad-entry-type": {
        "severity": "error",
        "rejects": True,
        "what": "an @ was not followed by an entry-type identifier (stray text)",
    },
    "cite:csl-missing-id": {
        "severity": "error",
        "rejects": True,
        "what": "a CSL-JSON item has no `id`, so it has no citation key to store under",
    },
    "cite:roundtrip-lost": {
        "severity": "error",
        "rejects": False,
        "what": "re-emitting the entry and parsing it back did not reproduce it — measured, not assumed",
    },
    "cite:unknown-type": {
        "severity": "warning",
        "rejects": False,
        "what": "entry type is not one of the known BibTeX types; kept verbatim rather than coerced to @misc",
    },
    "cite:unknown-macro": {
        "severity": "warning",
        "rejects": False,
        "what": "a bare word value matched no @string definition; the literal token is kept so nothing is invented",
    },
    "cite:empty-value": {
        "severity": "warning",
        "rejects": False,
        "what": "a field is present but empty; kept, because deleting it would change the entry",
    },
    "cite:missing-required": {
        "severity": "warning",
        "rejects": False,
        "what": "a field this entry type needs for formatting is absent; rendering will error rather than print a hole",
    },
    "cite:duplicate-doi": {
        "severity": "warning",
        "rejects": False,
        "what": "two different keys carry the same DOI — the classic Zotero double-import",
    },
    "cite:bad-doi": {
        "severity": "warning",
        "rejects": False,
        "what": "a doi field does not have DOI shape (10.<registrant>/<suffix>); kept verbatim, not repaired",
    },
    "cite:crossref-unresolved": {
        "severity": "warning",
        "rejects": False,
        "what": "the entry has a crossref field; inheritance is OUT OF SCOPE here and the inherited fields are absent",
    },
    "cite:key-conflict": {
        "severity": "info",
        "rejects": False,
        "what": "the store already holds this key; --on-conflict decided what happened",
    },
    "cite:csl-unmapped": {
        "severity": "info",
        "rejects": False,
        "what": "fields with no CSL-JSON equivalent were left out of the CSL item and are named here",
    },
}

REJECTING_RULES = frozenset(r for r, spec in RULES.items() if spec["rejects"])


def default_rules() -> dict[str, dict[str, Any]]:
    """A fresh copy of the rule table with every rule enabled."""
    return {
        rule: {
            "severity": spec["severity"],
            "rejects": spec["rejects"],
            "enabled": True,
            "what": spec["what"],
        }
        for rule, spec in RULES.items()
    }


def load_rules(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """RULES overlaid with an optional JSON file (policy-as-config).

    An overlay may retune `severity` (so a shop can gate on cite:missing-required)
    and may disable a NON-rejecting rule. Disabling a rejecting rule raises:
    "import this malformed entry anyway" is a data-integrity decision, not an
    org style preference, and silently honouring it would reintroduce the
    partial-import bug this module exists to prevent.
    """
    merged = default_rules()
    if not path:
        return merged
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("rules file must be a JSON object of {rule_id: overlay}")
    for rule, over in raw.items():
        if rule not in merged:
            raise ValueError(
                f"unknown rule {rule!r} (choose from {', '.join(sorted(merged))})"
            )
        if not isinstance(over, dict):
            raise ValueError(f"rule {rule!r}: overlay must be an object")
        if "severity" in over:
            sev = over["severity"]
            if sev not in openswap.SEVERITIES:
                raise ValueError(
                    f"rule {rule!r}: severity must be one of {'|'.join(openswap.SEVERITIES)}"
                )
            merged[rule]["severity"] = sev
        if "enabled" in over:
            if not over["enabled"] and rule in REJECTING_RULES:
                raise ValueError(
                    f"rule {rule!r} cannot be disabled: it refuses a malformed entry, and a "
                    "half-imported reference is the bug this store exists to prevent"
                )
            merged[rule]["enabled"] = bool(over["enabled"])
    return merged


def diagnostics_from(
    problems: list[dict[str, Any]],
    *,
    path: str,
    rules: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Map parse/import problems onto the family diagnostic schema."""
    table = rules or default_rules()
    out = []
    for p in problems:
        rule = p["rule"]
        spec = table.get(rule) or {"severity": "warning", "enabled": True}
        if not spec.get("enabled", True):
            continue
        out.append(
            openswap.diagnostic(
                path=p.get("path") or path,
                line=int(p.get("line") or 1),
                rule=rule,
                severity=spec["severity"],
                message=p["message"],
                suggestion=p.get("suggestion"),
                source="cite",
            )
        )
    return openswap.sort_diagnostics(out)


# ---- entry types ------------------------------------------------------------

# Fields the FORMATTER genuinely needs per type. Deliberately the classic BibTeX
# required sets, relaxed in one place: the author slot accepts `editor` for
# collections, and which one was used is reported as `author_role` rather than
# blurred.
REQUIRED: dict[str, tuple[str, ...]] = {
    "article": ("author", "title", "journal", "year"),
    "book": ("author", "title", "publisher", "year"),
    "booklet": ("title",),
    "inbook": ("author", "title", "publisher", "year"),
    "incollection": ("author", "title", "booktitle", "publisher", "year"),
    "inproceedings": ("author", "title", "booktitle", "year"),
    "conference": ("author", "title", "booktitle", "year"),
    "manual": ("title",),
    "mastersthesis": ("author", "title", "school", "year"),
    "phdthesis": ("author", "title", "school", "year"),
    "proceedings": ("title", "year"),
    "techreport": ("author", "title", "institution", "year"),
    "unpublished": ("author", "title", "note"),
    "misc": ("title",),
    "online": ("title",),
    "electronic": ("title",),
    "dataset": ("title",),
    "software": ("title",),
    "thesis": ("author", "title", "school", "year"),
}
DEFAULT_REQUIRED = ("title",)
KNOWN_TYPES = tuple(sorted(REQUIRED))

# Where the "who" and the "where" live, in preference order. A type that carries
# `institution` instead of `publisher` must still render.
_AUTHOR_FIELDS = ("author", "editor")
_CONTAINER_FIELDS = ("journal", "journaltitle", "booktitle", "series")
_PUBLISHER_FIELDS = ("publisher", "institution", "school", "organization")

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def required_fields(entry_type: str) -> tuple[str, ...]:
    """The fields this type needs before a reference can be rendered."""
    return REQUIRED.get(str(entry_type).lower(), DEFAULT_REQUIRED)


# ---- LaTeX -> unicode (display only; the store keeps the original) ----------

# Accent command -> the COMBINING codepoint, then NFC. That is 15 lines instead
# of a 400-entry precomposed table, and it composes for any base letter.
_ACCENTS = {
    "'": "́",  # acute
    "`": "̀",  # grave
    "^": "̂",  # circumflex
    '"': "̈",  # diaeresis
    "~": "̃",  # tilde
    "=": "̄",  # macron
    ".": "̇",  # dot above
    "c": "̧",  # cedilla
    "v": "̌",  # caron
    "u": "̆",  # breve
    "H": "̋",  # double acute
    "r": "̊",  # ring above
    "d": "̣",  # dot below
    "b": "̱",  # macron below
    "k": "̨",  # ogonek
}
_LIGATURES = {
    r"\ss": "ß",
    r"\aa": "å",
    r"\AA": "Å",
    r"\ae": "æ",
    r"\AE": "Æ",
    r"\oe": "œ",
    r"\OE": "Œ",
    r"\o": "ø",
    r"\O": "Ø",
    r"\l": "ł",
    r"\L": "Ł",
    r"\i": "i",
    r"\j": "j",
}
_ACCENT_RE = re.compile(
    r"\\([`'^\"~=.]|[cvuHrdbk])\s*(?:\{\s*(\\i|\\j|[A-Za-z])\s*\}|(\\i|\\j|[A-Za-z]))"
)
# Private-use sentinels: a LITERAL brace (written \{ in LaTeX) is parked here so
# the final case-protection strip cannot eat it. U+E000/E001 cannot occur in a
# .bib file that a TeX engine would accept, and if one somehow did it would come
# back out as a brace, which is a visible wrong character rather than a silent
# deletion.
_LBRACE_SENTINEL = "\ue000"
_RBRACE_SENTINEL = "\ue001"
_ESCAPED = {
    r"\&": "&",
    r"\%": "%",
    r"\$": "$",
    r"\#": "#",
    r"\_": "_",
    r"\{": _LBRACE_SENTINEL,
    r"\}": _RBRACE_SENTINEL,
}


def delatex(value: str) -> str:
    """Decode the LaTeX a .bib file actually contains, for DISPLAY only.

    The store keeps the original text of every field, so this is a VIEW and never
    an edit: `roundtrip_report` and `_store_faithful` both compare stored values,
    not decoded ones. Order matters — escaped braces are parked on the sentinels
    first, accents compose next, and the case-protection braces are stripped last.
    """
    if not value:
        return ""
    out = value
    for src, dst in _ESCAPED.items():
        out = out.replace(src, dst)

    def _accent(m: re.Match[str]) -> str:
        base = m.group(2) or m.group(3) or ""
        base = _LIGATURES.get(base, base)
        return unicodedata.normalize("NFC", base + _ACCENTS[m.group(1)])

    out = _ACCENT_RE.sub(_accent, out)
    # longest command first: \AA must not be eaten by the \A- prefix of nothing,
    # and \o must not fire inside \oe
    for src, dst in sorted(_LIGATURES.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(re.escape(src) + r"(?![A-Za-z])", dst, out)
    out = out.replace("---", "—").replace("--", "–")
    out = out.replace("``", "“").replace("''", "”")
    out = out.replace("~", " ")  # LaTeX non-breaking space
    out = out.replace("{", "").replace("}", "")
    out = out.replace(_LBRACE_SENTINEL, "{").replace(_RBRACE_SENTINEL, "}")
    return re.sub(r"\s+", " ", out).strip()


# ---- brace-aware scanning ---------------------------------------------------


def balanced(text: str) -> bool:
    """True when every { has its }, and no } arrives early."""
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _scan_body(src: str, start: int, close_ch: str) -> tuple[str | None, int]:
    """Body between the delimiters at `start`, or (None, -1) if never closed."""
    depth = 0
    for i in range(start, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and close_ch == "}":
                return src[start + 1 : i], i + 1
            if depth < 0:
                return None, -1
        elif ch == close_ch and close_ch == ")" and depth == 0:
            return src[start + 1 : i], i + 1
    return None, -1


def split_top(text: str, sep: str) -> list[str]:
    """Split on `sep` only at brace depth 0 and outside "..." quoting.

    A BACKSLASH-ESCAPED quote does not toggle the quoting state, and that is not
    a nicety: `author = {Sch\\"onherr, Erdos}` is ordinary .bib, and without this
    the `\\"` opened a phantom quoted region that swallowed the comma, so the
    "von Last, First" split never happened and the surname came out as the last
    word of the given name. Brace depth is counted LITERALLY (an escaped `\\{`
    still counts), because that is what BibTeX's own scanner does and a divergence
    here would make `balanced()` and this function disagree about the same string.
    """
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    quoted = False
    prev = ""
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == '"' and depth == 0 and prev != "\\":
            quoted = not quoted
        elif ch == sep and depth == 0 and not quoted:
            out.append("".join(buf))
            buf = []
            prev = ch
            continue
        buf.append(ch)
        prev = ch
    out.append("".join(buf))
    return out


def _split_ws_top(text: str) -> list[str]:
    """Whitespace tokens at brace depth 0 — `{de la}` stays one token."""
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch.isspace() and depth == 0:
            if buf:
                out.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


# ---- BibTeX parsing ---------------------------------------------------------

_TYPE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_FIELD_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_:.+-]*\Z")
_AND_RE = re.compile(r"\s+and\s+", re.IGNORECASE)
_DOI_RE = re.compile(r"\A10\.\d{4,9}/\S+\Z")
_YEAR_RE = re.compile(r"(1[0-9]{3}|2[0-9]{3})")


def _line_of(src: str, idx: int) -> int:
    return src.count("\n", 0, idx) + 1


def _parse_value(
    raw: str, strings: dict[str, str]
) -> tuple[str | None, str | None, list[str]]:
    """One field value: braced, quoted, numeric, macro, or a # concatenation.

    Returns (value, error, macros_referenced) where the third element names EVERY
    bare identifier the value referenced, resolved or not. Recording the resolved
    ones matters as much as the unresolved: the store keeps them so
    `_store_faithful` can re-parse the entry's original text with the same macro
    table, instead of reporting a phantom "the journal changed" for every entry
    that used a @string. A value has EITHER a value OR an error — a half-decoded
    value is exactly the silent corruption this module exists to prevent.
    """
    macros: list[str] = []
    parts: list[str] = []
    for piece in split_top(raw, "#"):
        p = piece.strip()
        if not p:
            return None, "empty piece in a # concatenation", macros
        if p.startswith("{"):
            inner = p[1:-1]
            if not (p.endswith("}") and balanced(p) and balanced(inner)):
                return None, f"unbalanced braces in value {p[:40]!r}", macros
            parts.append(inner)
        elif p.startswith('"'):
            if len(p) < 2 or not p.endswith('"'):
                return None, f"unterminated quoted value {p[:40]!r}", macros
            inner = p[1:-1]
            if not balanced(inner):
                return None, f"unbalanced braces in quoted value {p[:40]!r}", macros
            parts.append(inner)
        elif p.isdigit():
            parts.append(p)
        elif _FIELD_NAME_RE.match(p):
            low = p.lower()
            macros.append(p)
            # an UNDEFINED macro keeps its literal token: BibTeX would silently
            # substitute the empty string, which deletes data
            parts.append(strings.get(low, p))
        else:
            return None, f"malformed value {p[:40]!r}", macros
    return "".join(parts), None, macros


def _parse_entry_body(
    etype: str, key_and_fields: list[str], strings: dict[str, str]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Body elements -> an entry, or None plus the rules that refused it."""
    problems: list[dict[str, Any]] = []
    key = key_and_fields[0].strip()
    if not key or "=" in key or any(c.isspace() for c in key):
        return None, [
            {
                "rule": "cite:missing-key",
                "message": f"@{etype} has no citation key (first body element was {key[:40]!r})",
                "suggestion": "write @type{somekey, field = {value}, ...}",
            }
        ]
    fields: dict[str, str] = {}
    order: list[str] = []
    macros: dict[str, list[str]] = {}
    unresolved_macros: dict[str, list[str]] = {}
    strings_used: dict[str, str] = {}
    for element in key_and_fields[1:]:
        if not element.strip():
            continue  # a trailing comma is legal BibTeX, not a finding
        halves = split_top(element, "=")
        if len(halves) < 2:
            problems.append(
                {
                    "rule": "cite:malformed-field",
                    "message": f"@{etype}{{{key}}}: element {element.strip()[:40]!r} is not `name = value`",
                    "suggestion": "every element after the key must be name = {value}",
                }
            )
            continue
        name = halves[0].strip().lower()
        if not _FIELD_NAME_RE.match(name):
            problems.append(
                {
                    "rule": "cite:malformed-field",
                    "message": f"@{etype}{{{key}}}: {name[:40]!r} is not a BibTeX field name",
                    "suggestion": "field names start with a letter",
                }
            )
            continue
        if name in fields:
            problems.append(
                {
                    "rule": "cite:duplicate-field",
                    "message": f"@{etype}{{{key}}}: field {name!r} appears twice — refusing to pick a winner",
                    "suggestion": f"delete one of the two {name} lines",
                }
            )
            continue
        value, error, used = _parse_value("=".join(halves[1:]), strings)
        if error is not None:
            problems.append(
                {
                    "rule": "cite:malformed-value",
                    "message": f"@{etype}{{{key}}}: field {name!r}: {error}",
                    "suggestion": "wrap the value in braces: name = {value}",
                }
            )
            continue
        fields[name] = value or ""
        order.append(name)
        if used:
            macros[name] = used
            unresolved = [m for m in used if m.lower() not in strings]
            if unresolved:
                unresolved_macros[name] = unresolved
            strings_used.update(
                {m: strings[m.lower()] for m in used if m.lower() in strings}
            )
    if any(p["rule"] in REJECTING_RULES for p in problems):
        return None, problems
    entry = {
        "key": key,
        "type": etype,
        "fields": fields,
        "field_order": order,
        "macros": macros,
        "unresolved_macros": unresolved_macros,
        "strings_used": dict(sorted(strings_used.items())),
    }
    return entry, problems


def _entry_warnings(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Non-rejecting findings about an accepted entry."""
    out: list[dict[str, Any]] = []
    etype, key, fields = entry["type"], entry["key"], entry["fields"]
    if etype not in REQUIRED:
        out.append(
            {
                "rule": "cite:unknown-type",
                "message": f"@{etype}{{{key}}}: unknown entry type, kept verbatim (not coerced to @misc)",
                "suggestion": f"known types: {', '.join(KNOWN_TYPES)}",
            }
        )
    for name, used in sorted(entry.get("unresolved_macros", {}).items()):
        out.append(
            {
                "rule": "cite:unknown-macro",
                "message": f"@{etype}{{{key}}}: field {name!r} references undefined macro(s) {', '.join(used)}; the literal token was kept",
                "suggestion": "add @string{name = {value}} above the entry, or brace the value",
            }
        )
    for name in sorted(n for n, v in fields.items() if not v.strip()):
        out.append(
            {
                "rule": "cite:empty-value",
                "message": f"@{etype}{{{key}}}: field {name!r} is empty",
                "suggestion": "fill it or delete the line",
            }
        )
    missing = missing_required(entry)
    if missing:
        out.append(
            {
                "rule": "cite:missing-required",
                "message": f"@{etype}{{{key}}}: missing {', '.join(missing)} — rendering will report an error rather than print a hole",
                "suggestion": f"@{etype} needs {', '.join(required_fields(etype))}",
            }
        )
    doi = fields.get("doi", "").strip()
    if doi and normalize_doi(doi) is None:
        out.append(
            {
                "rule": "cite:bad-doi",
                "message": f"@{etype}{{{key}}}: doi {doi[:60]!r} is not DOI-shaped (10.<registrant>/<suffix>); kept verbatim",
                "suggestion": "a DOI is never resolved here — fix it at the source",
            }
        )
    if fields.get("crossref", "").strip():
        out.append(
            {
                "rule": "cite:crossref-unresolved",
                "message": f"@{etype}{{{key}}}: crossref={fields['crossref']!r} is NOT resolved here; inherited fields are absent",
                "suggestion": "copy the inherited fields into the entry, or format the parent separately",
            }
        )
    return out


def parse_bibtex(
    text: str, *, path: str = "<bibtex>", strings: dict[str, str] | None = None
) -> dict[str, Any]:
    """Parse a .bib document. Malformed entries are refused, never half-kept.

    Returns {entries, rejected, strings, preambles, problems, counts}. `entries`
    holds only entries that survived intact; every refusal is in `rejected` with
    its rule, line and raw text so the operator can fix the source.

    `strings` pre-seeds the @string macro table. That is what makes the fidelity
    audit honest: one entry's text, lifted out of its file, no longer resolves the
    macros defined at the top of that file, and re-checking it without them would
    report a change that never happened.
    """
    src = text.replace("\r\n", "\n").replace("\r", "\n")
    entries: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    strings = {k.lower(): v for k, v in (strings or {}).items()}
    preambles: list[str] = []
    problems: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    counts = {"comments": 0, "strings": 0, "preambles": 0, "truncated": False}
    i = 0
    while True:
        at = src.find("@", i)
        if at < 0:
            break
        line = _line_of(src, at)
        m = _TYPE_RE.match(src, at + 1)
        if m is None:
            problems.append(
                {
                    "rule": "cite:bad-entry-type",
                    "line": line,
                    "message": f"line {line}: '@' is not followed by an entry type",
                    "suggestion": "escape a literal @ inside braces, or write @type{...}",
                }
            )
            i = at + 1
            continue
        etype = m.group(0).lower()
        k = m.end()
        while k < len(src) and src[k].isspace():
            k += 1
        if k >= len(src) or src[k] not in "{(":
            problems.append(
                {
                    "rule": "cite:missing-body",
                    "line": line,
                    "message": f"line {line}: @{etype} is not followed by a {{ or ( body",
                    "suggestion": "write @type{key, field = {value}}",
                }
            )
            i = m.end()
            continue
        body, end = _scan_body(src, k, "}" if src[k] == "{" else ")")
        if body is None:
            problems.append(
                {
                    "rule": "cite:unterminated-entry",
                    "line": line,
                    "message": f"line {line}: @{etype} body is never closed — refusing to import the rest of the file",
                    "suggestion": "balance the braces; nothing after this point was parsed",
                }
            )
            rejected.append(
                {
                    "key": None,
                    "type": etype,
                    "line": line,
                    "rule": "cite:unterminated-entry",
                    "raw": src[at : at + 200],
                }
            )
            counts["truncated"] = True
            break
        raw = src[at:end]
        i = end
        if etype == "comment":
            counts["comments"] += 1
            continue
        if etype == "preamble":
            preambles.append(body.strip())
            counts["preambles"] += 1
            continue
        if etype == "string":
            _absorb_string(body, strings, problems, line, counts)
            continue
        elements = split_top(body, ",")
        entry, entry_problems = _parse_entry_body(etype, elements, strings)
        for p in entry_problems:
            p.setdefault("line", line)
        problems.extend(entry_problems)
        if entry is None:
            rejected.append(
                {
                    "key": (elements[0].strip() or None) if elements else None,
                    "type": etype,
                    "line": line,
                    "rule": next(
                        p["rule"]
                        for p in entry_problems
                        if p["rule"] in REJECTING_RULES
                    ),
                    "raw": raw,
                }
            )
            continue
        if entry["key"] in seen:
            problems.append(
                {
                    "rule": "cite:duplicate-key",
                    "line": line,
                    "message": f"line {line}: key {entry['key']!r} already defined at line {seen[entry['key']]}; the first one wins",
                    "suggestion": "rename one of the two keys",
                }
            )
            rejected.append(
                {
                    "key": entry["key"],
                    "type": etype,
                    "line": line,
                    "rule": "cite:duplicate-key",
                    "raw": raw,
                }
            )
            continue
        seen[entry["key"]] = line
        entry["line"] = line
        entry["raw"] = raw
        entry["path"] = path
        warnings = _entry_warnings(entry)
        for w in warnings:
            w["line"] = line
        problems.extend(warnings)
        entries.append(entry)
    for p in problems:
        p.setdefault("path", path)
    counts["entries"] = len(entries)
    counts["rejected"] = len(rejected)
    return {
        "entries": entries,
        "rejected": rejected,
        "strings": strings,
        "preambles": preambles,
        "problems": problems,
        "counts": counts,
    }


def _absorb_string(
    body: str,
    strings: dict[str, str],
    problems: list[dict[str, Any]],
    line: int,
    counts: dict[str, Any],
) -> None:
    """@string{name = {value}} -> the macro table, or a malformed-field finding."""
    halves = split_top(body, "=")
    if len(halves) < 2 or not _FIELD_NAME_RE.match(halves[0].strip()):
        problems.append(
            {
                "rule": "cite:malformed-field",
                "line": line,
                "message": f"line {line}: @string body {body.strip()[:40]!r} is not `name = value`",
                "suggestion": "write @string{jcp = {J. Chem. Phys.}}",
            }
        )
        return
    value, error, _ = _parse_value("=".join(halves[1:]), strings)
    if error is not None:
        problems.append(
            {
                "rule": "cite:malformed-value",
                "line": line,
                "message": f"line {line}: @string {halves[0].strip()!r}: {error}",
                "suggestion": "write @string{name = {value}}",
            }
        )
        return
    strings[halves[0].strip().lower()] = value or ""
    counts["strings"] += 1


# ---- emission ---------------------------------------------------------------


def ordered_fields(entry: dict[str, Any]) -> list[str]:
    """Parse order first, then any field added later, alphabetically."""
    fields = entry.get("fields") or {}
    order = [n for n in (entry.get("field_order") or []) if n in fields]
    return order + sorted(set(fields) - set(order))


def to_bibtex(entry: dict[str, Any], *, indent: str = "  ") -> str:
    """Re-emit one entry. Delimiters normalize to braces; nothing else changes.

    Raises ValueError on a value whose braces do not balance rather than writing
    a file that will not parse back — that is the whole point of the round-trip
    contract.
    """
    fields = entry.get("fields") or {}
    names = ordered_fields(entry)
    for name in names:
        if not balanced(fields[name]):
            raise ValueError(
                f"field {name!r} of {entry.get('key')!r} has unbalanced braces; refusing to emit"
            )
    width = max((len(n) for n in names), default=0)
    lines = [f"@{entry['type']}{{{entry['key']},"]
    lines.extend(f"{indent}{n.ljust(width)} = {{{fields[n]}}}," for n in names)
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_bibtex(entries: list[dict[str, Any]]) -> str:
    """A whole .bib document. @string macros were expanded at parse time."""
    return "\n".join(to_bibtex(e) for e in entries)


def roundtrip_report(entry: dict[str, Any]) -> dict[str, Any]:
    """Emit -> reparse -> diff. `identical` is measured, never assumed."""
    report: dict[str, Any] = {
        "key": entry.get("key"),
        "type": entry.get("type"),
        "emitted": None,
        "reparsed": False,
        "lost_fields": [],
        "added_fields": [],
        "changed_fields": [],
        "type_preserved": None,
        "order_preserved": None,
        "identical": False,
        "error": None,
    }
    try:
        emitted = to_bibtex(entry)
    except ValueError as exc:
        report["error"] = f"emit failed: {exc}"
        return report
    report["emitted"] = emitted
    parsed = parse_bibtex(emitted, path="<roundtrip>")
    if len(parsed["entries"]) != 1:
        rules = sorted({r["rule"] for r in parsed["rejected"]}) or ["cite:no-entry"]
        report["error"] = (
            f"re-parse produced {len(parsed['entries'])} entries ({', '.join(rules)})"
        )
        return report
    back = parsed["entries"][0]
    report["reparsed"] = True
    before, after = entry.get("fields") or {}, back["fields"]
    report["lost_fields"] = sorted(set(before) - set(after))
    report["added_fields"] = sorted(set(after) - set(before))
    # UNREACHABLE WITH TODAY'S EMITTER, kept deliberately: to_bibtex writes the
    # value verbatim inside braces and the parser strips exactly those braces, so
    # no accepted input can change a shared field's value (a mutation that deletes
    # this conjunct from `identical` therefore survives the suite — see
    # test_the_emitter_is_verbatim_so_no_value_can_change_across_a_round_trip,
    # which pins the property this guard is insurance against). It exists so that
    # the day someone teaches the emitter to normalize a value — re-wrap a URL,
    # collapse whitespace, re-case a name — the fidelity audit reports it instead
    # of calling the entry identical.
    report["changed_fields"] = [
        {"field": n, "before": before[n], "after": after[n]}
        for n in sorted(set(before) & set(after))
        if before[n] != after[n]
    ]
    report["type_preserved"] = (
        back["type"] == entry["type"] and back["key"] == entry["key"]
    )
    report["order_preserved"] = back["field_order"] == ordered_fields(entry)
    report["identical"] = (
        not report["lost_fields"]
        and not report["added_fields"]
        and not report["changed_fields"]
        and bool(report["type_preserved"])
        and bool(report["order_preserved"])
    )
    return report


# ---- names ------------------------------------------------------------------


def split_names(field: str) -> list[str]:
    """Split an author/editor field on ' and ' at brace depth 0.

    Depth is what protects `{Bread and Butter Institute}` from becoming two
    authors, which is the standard BibTeX contract for corporate names.
    """
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    while i < len(field):
        ch = field[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth == 0:
            m = _AND_RE.match(field, i)
            if m is not None:
                out.append("".join(buf))
                buf = []
                i = m.end()
                continue
        buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [t.strip() for t in out if t.strip()]


# a special character opens with a control WORD (\ss) or a control SYMBOL (\'),
# and it is the first letter AFTER it that carries the case
_SPECIAL_LETTER_RE = re.compile(r"\{\\(?:[A-Za-z]+|[^A-Za-z])\s*\{?([A-Za-z])")
_CONTROL_WORD_RE = re.compile(r"\\[A-Za-z]+")


def _first_alpha_lower(token: str) -> bool:
    """BibTeX's von test: the case of the first letter AT BRACE LEVEL 0.

    A braced group is a "special character" in BibTeX terms, and a special
    character with no accent command inside is CASELESS — which BibTeX treats as
    uppercase. That is not pedantry: `Jean {de la} Fontaine` gives "Jean {de la}"
    as the given name precisely because bracing is how an author says "do not
    treat this as a von particle", and stripping the braces first (the naive
    implementation) silently reclassified it. An accent command inside does
    contribute a letter, so `{\\'e}tienne` still reads as lowercase.
    """
    depth = 0
    i = 0
    while i < len(token):
        ch = token[i]
        if ch == "{":
            if depth == 0:
                m = _SPECIAL_LETTER_RE.match(token, i)
                return m.group(1).islower() if m else False
            depth += 1
            i += 1
            continue
        if ch == "}":
            depth -= 1
            i += 1
            continue
        if depth == 0:
            if ch == "\\":
                m = _CONTROL_WORD_RE.match(token, i)
                if m is not None:  # a control word contributes no case of its own
                    i = m.end()
                    continue
            elif ch.isalpha():
                return ch.islower()
        i += 1
    return False


def _split_von(chunk: str) -> tuple[list[str], list[str]]:
    """ "von Last" -> (von tokens, family tokens). The last token is never von."""
    tokens = _split_ws_top(chunk)
    i = 0
    while i < len(tokens) - 1 and _first_alpha_lower(tokens[i]):
        i += 1
    return tokens[:i], tokens[i:]


def _first_von_last(chunk: str) -> tuple[list[str], list[str], list[str]]:
    """ "First von Last" -> (given, von, family) by the BibTeX lowercase rule."""
    tokens = _split_ws_top(chunk)
    if len(tokens) <= 1:
        return [], [], tokens
    lower = [i for i in range(len(tokens) - 1) if _first_alpha_lower(tokens[i])]
    if lower:
        first, last = lower[0], lower[-1]
        return tokens[:first], tokens[first : last + 1], tokens[last + 1 :]
    return tokens[:-1], [], tokens[-1:]


def parse_name(raw: str) -> dict[str, Any]:
    """One BibTeX name -> {given, von, family, jr, literal, corporate}.

    All three comma forms are handled: "First von Last", "von Last, First" and
    "von Last, Jr, First". A wholly braced name is a corporate/literal name and
    is never split into initials.
    """
    s = raw.strip()
    if s.startswith("{") and s.endswith("}") and balanced(s) and balanced(s[1:-1]):
        inner = s[1:-1].strip()
        return {
            "given": "",
            "von": "",
            "family": inner,
            "jr": "",
            "literal": inner,
            "corporate": True,
        }
    parts = [p.strip() for p in split_top(s, ",")]
    if len(parts) >= 3:
        von, family = _split_von(parts[0])
        jr = parts[1]
        given = " ".join(p for p in parts[2:] if p)
    elif len(parts) == 2:
        von, family = _split_von(parts[0])
        jr = ""
        given = parts[1]
    else:
        given_t, von, family = _first_von_last(parts[0])
        jr = ""
        given = " ".join(given_t)
    return {
        "given": given.strip(),
        "von": " ".join(von),
        "family": " ".join(family),
        "jr": jr.strip(),
        "literal": None,
        "corporate": False,
    }


def entry_names(entry: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Parsed contributor list plus WHICH field it came from (author vs editor)."""
    for field in _AUTHOR_FIELDS:
        raw = (entry.get("fields") or {}).get(field, "").strip()
        if raw:
            return [parse_name(n) for n in split_names(raw)], field
    return [], None


def initials(given: str) -> str:
    """ "John Ronald" -> "J. R."; "Jean-Robert" -> "J.-R.". Empty stays empty."""
    chunks = []
    for token in _split_ws_top(delatex(given)):
        pieces = [p for p in token.split("-") if p]
        letters = [p[0].upper() + "." for p in pieces if p[0].isalpha()]
        if letters:
            chunks.append("-".join(letters))
    return " ".join(chunks)


def display_name(name: dict[str, Any], form: str) -> str:
    """One contributor as a style needs it. Every form goes through delatex."""
    if name.get("corporate"):
        return delatex(str(name.get("literal") or name.get("family") or ""))
    family = delatex(" ".join(p for p in (name.get("von"), name.get("family")) if p))
    given = delatex(name.get("given") or "")
    jr = delatex(name.get("jr") or "")
    inits = initials(name.get("given") or "")
    if form == "family-initials":
        head = f"{family}, {inits}" if inits else family
    elif form == "initials-family":
        head = f"{inits} {family}".strip()
    elif form == "family-given":
        head = f"{family}, {given}" if given else family
    else:  # given-family
        head = f"{given} {family}".strip()
    return f"{head}, {jr}" if jr else head


def _join(items: list[str], *, last: str, sep: str = ", ") -> str:
    """Deterministic list join: 1 -> a; 2 -> a<last>b; 3+ -> a, b<last>c."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return sep.join(items[:-1]) + last + items[-1]


# ---- field access -----------------------------------------------------------


def _field(entry: dict[str, Any], *names: str) -> str:
    for n in names:
        v = (entry.get("fields") or {}).get(n, "").strip()
        if v:
            return v
    return ""


def entry_year(entry: dict[str, Any]) -> int | None:
    """A 4-digit year from `year`, else from `date`. None when absent."""
    for field in ("year", "date"):
        m = _YEAR_RE.search(_field(entry, field))
        if m is not None:
            return int(m.group(0))
    return None


def entry_month(entry: dict[str, Any]) -> int | None:
    """A month number from `month` (English names or a number), else None.

    Hardcoded English month names, exactly like logs #14 and certmon: strptime
    under a German locale would silently fail to parse "Mar".
    """
    raw = _field(entry, "month").lower().strip(" .")
    if not raw:
        return None
    if raw.isdigit():
        n = int(raw)
        return n if 1 <= n <= 12 else None
    return MONTHS.get(raw[:9]) or MONTHS.get(raw[:3])


def normalize_doi(value: str) -> str | None:
    """A bare, lowercased DOI, or None when the string is not DOI-shaped.

    Never resolved — resolving needs the network this adapter deletes. This is
    a SHAPE check and the docstring for cite:bad-doi says so.
    """
    v = (value or "").strip().lower()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if v.startswith(prefix):
            v = v[len(prefix) :].strip()
    return v if _DOI_RE.match(v) else None


def missing_required(entry: dict[str, Any]) -> list[str]:
    """Required fields this entry does not satisfy (editor counts as author)."""
    fields = entry.get("fields") or {}
    out = []
    for name in required_fields(entry.get("type", "")):
        if name == "author":
            if not any(fields.get(f, "").strip() for f in _AUTHOR_FIELDS):
                out.append("author")
        elif name == "publisher":
            if not any(fields.get(f, "").strip() for f in _PUBLISHER_FIELDS):
                out.append("publisher")
        elif name == "journal":
            if not any(fields.get(f, "").strip() for f in ("journal", "journaltitle")):
                out.append("journal")
        elif name == "year":
            if entry_year(entry) is None:
                out.append("year")
        elif not fields.get(name, "").strip():
            out.append(name)
    return out


OPTIONAL_REPORTED = ("volume", "number", "pages", "doi", "url", "publisher")


# ---- styles -----------------------------------------------------------------

STYLES = ("apa", "mla", "chicago", "ieee", "bibtex", "csl")
NO_DATE = "n.d."


def _apa(entry: dict[str, Any], names: list[dict[str, Any]], year: int | None) -> str:
    authors = _join([display_name(n, "family-initials") for n in names], last=", & ")
    title = delatex(_field(entry, "title"))
    bits = [
        f"{authors} ({year if year else NO_DATE}). {title}."
        if authors
        else f"{title}. ({year if year else NO_DATE})."
    ]
    container = delatex(_field(entry, *_CONTAINER_FIELDS))
    vol, num, pages = (
        _field(entry, "volume"),
        _field(entry, "number", "issue"),
        delatex(_field(entry, "pages")),
    )
    if container:
        seg = container
        if vol:
            seg += f", {vol}"
            if num:
                seg += f"({num})"
        if pages:
            seg += f", {pages}"
        bits.append(seg + ".")
    publisher = delatex(_field(entry, *_PUBLISHER_FIELDS))
    if publisher:
        bits.append(publisher + ".")
    doi = normalize_doi(_field(entry, "doi"))
    if doi:
        bits.append(f"https://doi.org/{doi}")
    elif _field(entry, "url"):
        bits.append(_field(entry, "url"))
    return " ".join(bits)


def _mla(entry: dict[str, Any], names: list[dict[str, Any]], year: int | None) -> str:
    shown = (
        [display_name(names[0], "family-given")]
        + [display_name(n, "given-family") for n in names[1:]]
        if names
        else []
    )
    # MLA 9 uses ", and " before the final name at every list length; the "et al."
    # short form is NOT applied here (a truncation rule differs per edition and a
    # wrong one is a fabricated citation — see SCOPE_LIMITS).
    authors = _join(shown, last=", and ")
    bits = []
    if authors:
        bits.append(authors + ".")
    bits.append(f'"{delatex(_field(entry, "title"))}."')
    container = delatex(_field(entry, *_CONTAINER_FIELDS))
    seg = []
    if container:
        seg.append(container)
    if _field(entry, "volume"):
        seg.append(f"vol. {_field(entry, 'volume')}")
    if _field(entry, "number", "issue"):
        seg.append(f"no. {_field(entry, 'number', 'issue')}")
    # The publisher is a REQUIRED field for @book/@techreport/@thesis, so it has
    # to appear in the rendered reference; a required-field check that gates on a
    # field the renderer then drops would be decorative.
    if _field(entry, *_PUBLISHER_FIELDS):
        seg.append(delatex(_field(entry, *_PUBLISHER_FIELDS)))
    seg.append(str(year) if year else NO_DATE)
    if _field(entry, "pages"):
        seg.append(f"pp. {delatex(_field(entry, 'pages'))}")
    bits.append(", ".join(seg) + ".")
    return " ".join(bits)


def _chicago(
    entry: dict[str, Any], names: list[dict[str, Any]], year: int | None
) -> str:
    shown = (
        [display_name(names[0], "family-given")]
        + [display_name(n, "given-family") for n in names[1:]]
        if names
        else []
    )
    bits = []
    if shown:
        bits.append(_join(shown, last=", and ") + ".")
    bits.append(f"{year if year else NO_DATE}.")
    bits.append(f'"{delatex(_field(entry, "title"))}."')
    container = delatex(_field(entry, *_CONTAINER_FIELDS))
    if container:
        seg = container
        if _field(entry, "volume"):
            seg += f" {_field(entry, 'volume')}"
        if _field(entry, "number", "issue"):
            seg += f" ({_field(entry, 'number', 'issue')})"
        if _field(entry, "pages"):
            seg += f": {delatex(_field(entry, 'pages'))}"
        bits.append(seg + ".")
    publisher = delatex(_field(entry, *_PUBLISHER_FIELDS))
    if publisher:
        bits.append(publisher + ".")
    return " ".join(bits)


def _ieee(entry: dict[str, Any], names: list[dict[str, Any]], year: int | None) -> str:
    authors = _join(
        [display_name(n, "initials-family") for n in names],
        last=", and " if len(names) > 2 else " and ",
    )
    bits = []
    if authors:
        bits.append(authors + ",")
    bits.append(f'"{delatex(_field(entry, "title"))},"')
    tail = []
    container = delatex(_field(entry, *_CONTAINER_FIELDS))
    if container:
        tail.append(container)
    if _field(entry, "volume"):
        tail.append(f"vol. {_field(entry, 'volume')}")
    if _field(entry, "number", "issue"):
        tail.append(f"no. {_field(entry, 'number', 'issue')}")
    if _field(
        entry, *_PUBLISHER_FIELDS
    ):  # required for @book/@techreport — must render
        tail.append(delatex(_field(entry, *_PUBLISHER_FIELDS)))
    if _field(entry, "pages"):
        tail.append(f"pp. {delatex(_field(entry, 'pages'))}")
    tail.append(str(year) if year else NO_DATE)
    bits.append(", ".join(tail) + ".")
    return " ".join(bits)


_RENDERERS = {"apa": _apa, "mla": _mla, "chicago": _chicago, "ieee": _ieee}


def in_text(entry: dict[str, Any], style: str, *, index: int | None = None) -> str:
    """The in-text marker: (Doe & Roe, 2020) / (Doe and Roe 2020) / [3]."""
    names, _ = entry_names(entry)
    year = entry_year(entry)
    if style == "ieee":
        return f"[{index}]" if index else f"[{entry['key']}]"
    # The von particle belongs in the in-text marker: APA cites "de la Fontaine",
    # not "Fontaine", and dropping it would print a name nobody can look up.
    families = [
        delatex(
            n["literal"]
            if n.get("corporate")
            else " ".join(p for p in (n["von"], n["family"]) if p)
        )
        for n in names
    ] or [entry["key"]]
    if style == "apa":
        who = _join(families, last=" & ")
        return f"({who}, {year if year else NO_DATE})"
    if style == "mla":
        return f"({_join(families, last=' and ')})"
    return f"({_join(families, last=' and ')} {year if year else NO_DATE})"


def render(
    entry: dict[str, Any], style: str, *, index: int | None = None
) -> dict[str, Any]:
    """One reference in one style. EITHER `text` OR `error`, never both/neither.

    A missing required field is an error naming the fields, because a reference
    with a hole where the journal should be is a fabricated citation. Absent
    OPTIONAL fields are listed in `omitted` so a thin entry looks thin.
    """
    style = str(style).lower()
    reading: dict[str, Any] = {
        "key": entry.get("key"),
        "type": entry.get("type"),
        "style": style,
        "text": None,
        "error": None,
        "missing_required": [],
        "omitted": [],
        "author_role": None,
        "in_text": None,
    }
    if style not in STYLES:
        reading["error"] = f"unknown style {style!r} (choose from {'|'.join(STYLES)})"
        return reading
    missing = missing_required(entry)
    reading["missing_required"] = missing
    names, role = entry_names(entry)
    reading["author_role"] = role
    fields = entry.get("fields") or {}
    reading["omitted"] = [f for f in OPTIONAL_REPORTED if not fields.get(f, "").strip()]
    if entry_year(entry) is None:
        reading["omitted"] = sorted({*reading["omitted"], "year"})
    if style == "bibtex":
        try:
            reading["text"] = to_bibtex(entry)
        except ValueError as exc:
            reading["error"] = str(exc)
        return reading
    if style == "csl":
        reading["text"] = json.dumps(to_csl(entry)["item"], indent=2, sort_keys=True)
        return reading
    if missing:
        reading["error"] = (
            f"cannot format @{entry.get('type')}{{{entry.get('key')}}} in {style}: "
            f"missing {', '.join(missing)}"
        )
        return reading
    reading["text"] = _RENDERERS[style](entry, names, entry_year(entry))
    reading["in_text"] = in_text(entry, style, index=index)
    return reading


SORT_KEYS = ("key", "author", "year", "type")


def sort_entries(
    entries: list[dict[str, Any]], by: str = "key"
) -> list[dict[str, Any]]:
    """Deterministic ordering. Ties always fall through to the key.

    Lowercase compare, not locale collation (SCOPE_LIMITS says so): a collation
    that moves with $LC_ALL would make a bibliography irreproducible.
    """
    if by not in SORT_KEYS:
        raise ValueError(f"sort must be one of {'|'.join(SORT_KEYS)}, got {by!r}")

    def _first_family(e: dict[str, Any]) -> str:
        names, _ = entry_names(e)
        return delatex(names[0].get("family") or "").lower() if names else ""

    def _key(e: dict[str, Any]) -> tuple:
        base = str(e.get("key") or "").lower()
        if by == "author":
            return (_first_family(e), entry_year(e) or 0, base)
        if by == "year":
            return (entry_year(e) or 0, _first_family(e), base)
        if by == "type":
            return (str(e.get("type") or ""), base, "")
        return (base, "", "")

    return sorted(entries, key=_key)


def bibliography(
    entries: list[dict[str, Any]], style: str, *, sort: str = "key"
) -> dict[str, Any]:
    """A whole bibliography: ordered readings plus a formatted/failed tally."""
    ordered = sort_entries(entries, sort)
    readings = [render(e, style, index=i + 1) for i, e in enumerate(ordered)]
    formatted = [r for r in readings if r["text"] is not None]
    return {
        "style": str(style).lower(),
        "sort": sort,
        "count": len(readings),
        "formatted": len(formatted),
        "failed": len(readings) - len(formatted),
        "entries": readings,
    }


# ---- CSL-JSON (lite) --------------------------------------------------------

CSL_TYPES = {
    "article": "article-journal",
    "book": "book",
    "booklet": "pamphlet",
    "inbook": "chapter",
    "incollection": "chapter",
    "inproceedings": "paper-conference",
    "conference": "paper-conference",
    "manual": "report",
    "mastersthesis": "thesis",
    "phdthesis": "thesis",
    "thesis": "thesis",
    "proceedings": "book",
    "techreport": "report",
    "unpublished": "manuscript",
    "misc": "document",
    "online": "webpage",
    "electronic": "webpage",
    "dataset": "dataset",
    "software": "software",
}
_CSL_TO_BIB = {
    "article-journal": "article",
    "article-magazine": "article",
    "article-newspaper": "article",
    "book": "book",
    "chapter": "incollection",
    "dataset": "dataset",
    "document": "misc",
    "manuscript": "unpublished",
    "pamphlet": "booklet",
    "paper-conference": "inproceedings",
    "report": "techreport",
    "software": "software",
    "thesis": "phdthesis",
    "webpage": "online",
}
# BibTeX field -> CSL key. Anything not here is UNMAPPED and reported, never
# dropped in silence; the store still holds it and `bibtex` style still emits it.
_CSL_FIELDS = {
    "title": "title",
    "volume": "volume",
    "number": "issue",
    "issue": "issue",
    "pages": "page",
    "url": "URL",
    "abstract": "abstract",
    "note": "note",
    "edition": "edition",
    "isbn": "ISBN",
    "issn": "ISSN",
    "language": "language",
}
_CSL_HANDLED = frozenset(
    {
        *_CSL_FIELDS,
        *_AUTHOR_FIELDS,
        *_CONTAINER_FIELDS,
        *_PUBLISHER_FIELDS,
        "doi",
        "year",
        "date",
        "month",
    }
)


def to_csl(entry: dict[str, Any]) -> dict[str, Any]:
    """One entry -> {item: CSL-JSON, unmapped: [fields left out, named]}."""
    fields = entry.get("fields") or {}
    item: dict[str, Any] = {
        "id": entry.get("key"),
        "type": CSL_TYPES.get(str(entry.get("type", "")).lower(), "document"),
    }
    names, role = entry_names(entry)
    if names:
        item["editor" if role == "editor" else "author"] = [
            {"literal": delatex(str(n["literal"]))}
            if n.get("corporate")
            else {
                "family": delatex(" ".join(p for p in (n["von"], n["family"]) if p)),
                "given": delatex(n["given"]),
            }
            for n in names
        ]
    for bib, csl in _CSL_FIELDS.items():
        v = fields.get(bib, "").strip()
        if v and csl not in item:
            item[csl] = delatex(v)
    container = _field(entry, *_CONTAINER_FIELDS)
    if container:
        item["container-title"] = delatex(container)
    publisher = _field(entry, *_PUBLISHER_FIELDS)
    if publisher:
        item["publisher"] = delatex(publisher)
    doi = normalize_doi(_field(entry, "doi"))
    if doi:
        item["DOI"] = doi
    year, month = entry_year(entry), entry_month(entry)
    if year is not None:
        item["issued"] = {"date-parts": [[year, month] if month else [year]]}
    unmapped = sorted(n for n in fields if n not in _CSL_HANDLED and fields[n].strip())
    return {"item": item, "unmapped": unmapped}


def _csl_name_to_bibtex(person: dict[str, Any]) -> str:
    if person.get("literal"):
        return "{" + str(person["literal"]).strip() + "}"
    family = str(person.get("family") or "").strip()
    given = str(person.get("given") or "").strip()
    return f"{family}, {given}" if given else family


def parse_csl_json(text: str, *, path: str = "<csl-json>") -> dict[str, Any]:
    """Parse CSL-JSON into the same shape as parse_bibtex.

    An item with no `id` is REFUSED (cite:csl-missing-id), for the same reason a
    keyless @article is: without a key there is nothing to cite it by, and
    inventing one would put a fabricated identifier in someone's manuscript.
    """
    raw = json.loads(text)
    items = raw if isinstance(raw, list) else [raw]
    entries: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pos, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not str(item.get("id") or "").strip():
            problems.append(
                {
                    "rule": "cite:csl-missing-id",
                    "line": pos,
                    "path": path,
                    "message": f"CSL item #{pos} has no non-empty `id` — refused, a citation key cannot be invented",
                    "suggestion": 'give every item an "id"',
                }
            )
            rejected.append(
                {
                    "key": None,
                    "type": None,
                    "line": pos,
                    "rule": "cite:csl-missing-id",
                    "raw": json.dumps(item)[:200],
                }
            )
            continue
        key = str(item["id"]).strip()
        entry = _entry_from_csl(key, item)
        if key in seen:
            problems.append(
                {
                    "rule": "cite:duplicate-key",
                    "line": pos,
                    "path": path,
                    "message": f"CSL item #{pos}: id {key!r} already seen; the first one wins",
                    "suggestion": "make every id unique",
                }
            )
            rejected.append(
                {
                    "key": key,
                    "type": entry["type"],
                    "line": pos,
                    "rule": "cite:duplicate-key",
                    "raw": json.dumps(item)[:200],
                }
            )
            continue
        seen.add(key)
        entry["line"] = pos
        entry["path"] = path
        warnings = _entry_warnings(entry)
        for w in warnings:
            w["line"] = pos
            w["path"] = path
        problems.extend(warnings)
        entries.append(entry)
    return {
        "entries": entries,
        "rejected": rejected,
        "strings": {},
        "preambles": [],
        "problems": problems,
        "counts": {
            "entries": len(entries),
            "rejected": len(rejected),
            "comments": 0,
            "strings": 0,
            "preambles": 0,
            "truncated": False,
        },
    }


def _entry_from_csl(key: str, item: dict[str, Any]) -> dict[str, Any]:
    """One CSL item -> a BibTeX-shaped entry (fields in a stable order)."""
    btype = _CSL_TO_BIB.get(str(item.get("type") or ""), "misc")
    fields: dict[str, str] = {}
    order: list[str] = []

    def _put(name: str, value: Any) -> None:
        text = str(value).strip()
        if text and name not in fields:
            fields[name] = text
            order.append(name)

    for role in ("author", "editor"):
        people = item.get(role)
        if isinstance(people, list) and people:
            _put(
                role,
                " and ".join(
                    _csl_name_to_bibtex(p) for p in people if isinstance(p, dict)
                ),
            )
    _put("title", item.get("title") or "")
    _put(
        "journal" if btype == "article" else "booktitle",
        item.get("container-title") or "",
    )
    _put("publisher", item.get("publisher") or "")
    parts = ((item.get("issued") or {}).get("date-parts") or [[]])[0]
    if parts:
        _put("year", parts[0])
        if len(parts) > 1:
            _put("month", parts[1])
    for csl_key, bib in (
        ("volume", "volume"),
        ("issue", "number"),
        ("page", "pages"),
        ("DOI", "doi"),
        ("URL", "url"),
        ("edition", "edition"),
        ("ISBN", "isbn"),
        ("ISSN", "issn"),
        ("abstract", "abstract"),
        ("note", "note"),
        ("language", "language"),
    ):
        _put(bib, item.get(csl_key) or "")
    raw = {
        "key": key,
        "type": btype,
        "fields": fields,
        "field_order": order,
        "macros": {},
    }
    raw["raw"] = to_bibtex(raw)
    return raw


# ---- store ------------------------------------------------------------------

DB_REL = Path(".scout") / "cite.db"
SCHEMA_VERSION = "1"
CONFLICT_POLICIES = ("skip", "replace", "fail")

# `raw` keeps the entry text AS IT WAS ON DISK next to the normalized field rows,
# so roundtrip can diff against the source instead of against itself. `fields` is
# a table rather than a JSON blob so a DOI/author query is an index hit, and
# `pos` preserves parse order — dropping it would silently re-sort every export.
# `strings` keeps the @string macros THIS entry resolved, because `raw` alone is
# not self-contained: `journal = jcp` lifted out of its file no longer knows what
# jcp meant, and the fidelity audit would report a change that never happened.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries(
    key TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    raw TEXT NOT NULL,
    source TEXT,
    line INTEGER,
    added_ts REAL NOT NULL,
    strings TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS fields(
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    pos INTEGER NOT NULL,
    PRIMARY KEY(key, name)
);
CREATE INDEX IF NOT EXISTS idx_fields_name_value ON fields(name, value);
CREATE INDEX IF NOT EXISTS idx_entries_type ON entries(type);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the citation library — its OWN sqlite file.

    Not the logs #14 or uptime #2 database: a reference library is long-lived
    user data that should be backed up and moved as one file, and it must not
    share a write lock with a tailing collector.
    """
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()
    return conn


def _write_entry(
    conn: sqlite3.Connection, entry: dict[str, Any], *, source: str | None, now: float
) -> None:
    conn.execute("DELETE FROM fields WHERE key = ?", (entry["key"],))
    conn.execute(
        "INSERT OR REPLACE INTO entries(key, type, raw, source, line, added_ts, strings)"
        " VALUES(?, ?, ?, ?, ?, ?, ?)",
        (
            entry["key"],
            entry["type"],
            entry.get("raw") or to_bibtex(entry),
            source,
            entry.get("line"),
            now,
            json.dumps(entry.get("strings_used") or {}, sort_keys=True),
        ),
    )
    conn.executemany(
        "INSERT INTO fields(key, name, value, pos) VALUES(?, ?, ?, ?)",
        [
            (entry["key"], n, (entry["fields"] or {})[n], i)
            for i, n in enumerate(ordered_fields(entry))
        ],
    )


def import_entries(
    conn: sqlite3.Connection,
    entries: list[dict[str, Any]],
    *,
    source: str | None = None,
    on_conflict: str = "skip",
    now: float | None = None,
    record: bool = True,
) -> dict[str, Any]:
    """Store parsed entries. Conflicts are reported, never silently merged.

    `on_conflict="fail"` writes NOTHING when any key already exists: a partial
    import is the failure mode this module is built against, so the validation
    pass runs before the first INSERT. `record=False` is a real dry run — it
    reports exactly what would happen and leaves the file untouched.
    """
    if on_conflict not in CONFLICT_POLICIES:
        raise ValueError(
            f"on_conflict must be one of {'|'.join(CONFLICT_POLICIES)}, got {on_conflict!r}"
        )
    stamp = time.time() if now is None else float(now)
    existing = {r["key"] for r in conn.execute("SELECT key FROM entries").fetchall()}
    conflicts = [e["key"] for e in entries if e["key"] in existing]
    problems: list[dict[str, Any]] = []
    if conflicts and on_conflict == "fail":
        raise ValueError(
            f"{len(conflicts)} key(s) already in the library ({', '.join(sorted(conflicts)[:5])}) "
            "— nothing was written; re-run with --on-conflict skip or replace"
        )
    imported: list[str] = []
    skipped: list[str] = []
    replaced: list[str] = []
    for entry in entries:
        conflict = entry["key"] in existing
        if conflict:
            problems.append(
                {
                    "rule": "cite:key-conflict",
                    "line": entry.get("line") or 1,
                    "path": entry.get("path") or source or "<import>",
                    "message": f"key {entry['key']!r} already in the library — {on_conflict}",
                    "suggestion": "use --on-conflict replace to overwrite, or rename the incoming key",
                }
            )
            if on_conflict == "skip":
                skipped.append(entry["key"])
                continue
            replaced.append(entry["key"])
        else:
            imported.append(entry["key"])
        if record:
            _write_entry(conn, entry, source=source, now=stamp)
        existing.add(entry["key"])
    if record:
        conn.commit()
    problems.extend(_doi_conflicts(conn, entries, source) if record else [])
    return {
        "recorded": record,
        "imported": sorted(imported),
        "replaced": sorted(replaced),
        "skipped": sorted(skipped),
        "on_conflict": on_conflict,
        "problems": problems,
    }


def _doi_conflicts(
    conn: sqlite3.Connection, entries: list[dict[str, Any]], source: str | None
) -> list[dict[str, Any]]:
    """The classic Zotero double-import: one DOI under two keys.

    ONE finding per DOI, not one per entry. "a and b share a DOI" is a symmetric
    relation, and emitting it from both sides double-counted a single problem —
    which would have inflated `by_rule` in every gate summary.
    """
    incoming: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        doi = normalize_doi((entry.get("fields") or {}).get("doi", ""))
        if doi:
            incoming.setdefault(doi, []).append(entry)
    if not incoming:
        return []
    stored: dict[str, set[str]] = {}
    for row in conn.execute(
        "SELECT key, value FROM fields WHERE name = 'doi' ORDER BY key ASC"
    ).fetchall():
        norm = normalize_doi(row["value"])
        if norm:
            stored.setdefault(norm, set()).add(row["key"])
    out = []
    for doi in sorted(incoming):
        keys = {e["key"] for e in incoming[doi]} | stored.get(doi, set())
        if len(keys) < 2:
            continue
        first = incoming[doi][0]
        out.append(
            {
                "rule": "cite:duplicate-doi",
                "line": first.get("line") or 1,
                "path": first.get("path") or source or "<import>",
                "message": f"DOI {doi} is under {len(keys)} keys: {', '.join(sorted(keys))}",
                "suggestion": "delete the duplicate key, or fix the wrong DOI",
            }
        )
    return out


def load_entry(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    """Rebuild one entry from the store, field order and macro table and all."""
    row = conn.execute("SELECT * FROM entries WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    rows = conn.execute(
        "SELECT name, value FROM fields WHERE key = ? ORDER BY pos ASC", (key,)
    ).fetchall()
    try:
        macro_table = json.loads(row["strings"] or "{}")
    except (json.JSONDecodeError, TypeError):
        macro_table = {}  # a corrupt blob must not hide the entry itself
    return {
        "key": row["key"],
        "type": row["type"],
        "fields": {r["name"]: r["value"] for r in rows},
        "field_order": [r["name"] for r in rows],
        "raw": row["raw"],
        "source": row["source"],
        "line": row["line"],
        "added_ts": row["added_ts"],
        "strings_used": macro_table,
        "macros": {},
    }


def query(
    conn: sqlite3.Connection,
    *,
    key_contains: str | None = None,
    entry_type: str | None = None,
    author_contains: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    doi: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Field filters over the library, newest-key-order-independent.

    Substring matching on author/key is a deliberate floor, not a search engine:
    full-text ranking over a corpus is searchindex #20's job (sqlite FTS5) and
    duplicating it here would be a second index to keep in sync.

    A `doi` filter that is not DOI-shaped RAISES instead of being ignored. The
    first version normalized it to None and then skipped the comparison, so
    `--doi 10.1/typo` quietly returned the WHOLE library — a filter that cannot
    match anything must be an error, never a full-table scan dressed up as a hit.
    """
    wanted_doi = None
    if doi is not None and str(doi).strip():
        wanted_doi = normalize_doi(doi)
        if wanted_doi is None:
            raise ValueError(
                f"doi filter {doi!r} is not DOI-shaped (10.<registrant>/<suffix>) — "
                "it could never match, so this is refused rather than silently ignored"
            )
    rows = conn.execute(
        "SELECT key FROM entries WHERE (:type IS NULL OR type = :type)"
        " AND (:key IS NULL OR instr(lower(key), lower(:key)) > 0)"
        " ORDER BY key ASC",
        {"type": (entry_type or "").lower() or None, "key": key_contains or None},
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        entry = load_entry(conn, r["key"])
        if entry is None:
            continue
        if author_contains:
            names, _ = entry_names(entry)
            hay = " ".join(
                delatex(
                    f"{n.get('given', '')} {n.get('von', '')} {n.get('family', '')}"
                )
                for n in names
            ).lower()
            if author_contains.lower() not in hay:
                continue
        year = entry_year(entry)
        if year_min is not None and (year is None or year < year_min):
            continue
        if year_max is not None and (year is None or year > year_max):
            continue
        if (
            wanted_doi is not None
            and normalize_doi(entry["fields"].get("doi", "")) != wanted_doi
        ):
            continue
        out.append(entry)
    return out[offset : offset + limit] if limit >= 0 else out[offset:]


def library_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """What is actually in the library — counted in sqlite, not estimated."""
    total = conn.execute("SELECT COUNT(*) AS n FROM entries").fetchone()["n"]
    by_type = {
        r["type"]: r["n"]
        for r in conn.execute(
            "SELECT type, COUNT(*) AS n FROM entries GROUP BY type ORDER BY type ASC"
        ).fetchall()
    }
    field_rows = conn.execute(
        "SELECT name, COUNT(*) AS n FROM fields GROUP BY name ORDER BY n DESC, name ASC"
    ).fetchall()
    years = [
        y
        for y in (
            entry_year({"fields": {"year": r["value"]}})
            for r in conn.execute(
                "SELECT value FROM fields WHERE name IN ('year','date')"
            ).fetchall()
        )
        if y is not None
    ]
    return {
        "entries": total,
        "by_type": by_type,
        "distinct_fields": len(field_rows),
        "field_counts": {r["name"]: r["n"] for r in field_rows},
        "year_range": [min(years), max(years)] if years else None,
        "schema_version": SCHEMA_VERSION,
    }


def store_roundtrip(
    conn: sqlite3.Connection, keys: list[str] | None = None
) -> dict[str, Any]:
    """Round-trip every stored entry AND diff it against the original .bib text.

    Two experiments per entry, because they can fail independently:
    `store_faithful` compares the normalized field rows to a re-parse of the raw
    text that was imported (did the STORE drop anything?), and the emit/reparse
    report catches an emitter that cannot write what it read.
    """
    target = (
        keys
        if keys is not None
        else [
            r["key"]
            for r in conn.execute("SELECT key FROM entries ORDER BY key ASC").fetchall()
        ]
    )
    reports = []
    for key in target:
        entry = load_entry(conn, key)
        if entry is None:
            reports.append(
                {
                    "key": key,
                    "identical": False,
                    "error": "not in the library",
                    "store_faithful": None,
                }
            )
            continue
        report = roundtrip_report(entry)
        report["store_faithful"], report["store_diff"] = _store_faithful(entry)
        reports.append(report)
    lost = sorted({f for r in reports for f in (r.get("lost_fields") or [])})
    return {
        "checked": len(reports),
        "identical": sum(1 for r in reports if r["identical"]),
        "store_faithful": sum(1 for r in reports if r.get("store_faithful") is True),
        "lost_fields": lost,
        "reports": reports,
    }


def _store_faithful(entry: dict[str, Any]) -> tuple[bool | None, dict[str, Any] | None]:
    """Did the store keep every field the ORIGINAL text had? None = unmeasurable.

    The @string macros this entry resolved are fed back in, because the raw text
    alone is not self-contained: `journal = jcp` re-parsed without the definition
    at the top of the file yields the literal token `jcp`, and reporting that as
    "the journal changed in the store" would be a fabricated finding.
    """
    raw = entry.get("raw") or ""
    parsed = parse_bibtex(
        raw, path="<stored-raw>", strings=entry.get("strings_used") or {}
    )
    if len(parsed["entries"]) != 1:
        return None, {
            "reason": "stored raw text does not re-parse to exactly one entry"
        }
    original = parsed["entries"][0]["fields"]
    stored = entry.get("fields") or {}
    diff = {
        "missing_from_store": sorted(set(original) - set(stored)),
        "extra_in_store": sorted(set(stored) - set(original)),
        "changed": sorted(
            n for n in set(original) & set(stored) if original[n] != stored[n]
        ),
    }
    return (not any(diff.values())), diff


def delete_entries(conn: sqlite3.Connection, keys: list[str]) -> dict[str, Any]:
    """Remove keys; report which were actually present rather than claiming N."""
    present = {
        r["key"]
        for r in conn.execute("SELECT key FROM entries ORDER BY key ASC").fetchall()
    }
    hit = sorted(k for k in keys if k in present)
    miss = sorted(k for k in keys if k not in present)
    for key in hit:
        conn.execute("DELETE FROM fields WHERE key = ?", (key,))
        conn.execute("DELETE FROM entries WHERE key = ?", (key,))
    conn.commit()
    return {"deleted": hit, "not_found": miss}
