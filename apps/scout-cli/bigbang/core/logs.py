# Solo personal project, no connection to employer, built with public/free-tier only
"""Logs — tailing collectors + parsers + indexed sqlite store (openswap #14).

Papertrail / Splunk / Loggly with the ingest endpoint deleted: the log lines
never leave the box. This module owns everything deterministic — encoding
detection, unit-aligned line splitting, per-source parsers, level
normalization, locale-independent timestamp parsing, the indexed sqlite3 store
(entries + offsets), and the query/rollup surface. The `logs` plugin CLI adds
only path resolution, argument parsing and the fs_write policy gate.

Three problems a hosted log service hides from you, solved here in the open:

[1] Incremental re-runs. Each (source, file) keeps a byte offset in the
    `offsets` table. A pass reads the file's size via Path.stat() (os.stat),
    seeks to the stored offset, consumes only whole lines, and stores
    `start + consumed`. Re-running a pass on an unchanged file ingests zero
    rows. A file whose size went BACKWARDS was rotated or truncated, so the
    offset resets to the top and the result says `rotated: true` instead of
    silently skipping the new content.

[2] Windows file semantics. Nothing here holds a handle: every read is
    open -> seek -> read -> close (see read_head/read_chunk). A tailer that
    keeps a file open on Windows blocks the writer's rotate/rename and makes
    the daemon the reason logs go missing.

[3] Encoding. This repo's own research-loop logs
    (apps/dottie/data/research/logs/*.log) are UTF-16-LE with a BOM, written by
    PowerShell redirection — decoding them as UTF-8 yields NUL-riddled
    mojibake. detect_encoding() sniffs the BOM (UTF-8/16/32, checking the
    4-byte UTF-32-LE BOM BEFORE the 2-byte UTF-16-LE prefix it starts with),
    then falls back to a NUL-position heuristic for BOM-less UTF-16, then to
    strict UTF-8, then to latin-1 (which never raises). Byte offsets are kept
    unit-aligned and newlines are found as ENCODED byte patterns
    (b"\\n\\x00" for UTF-16-LE), so a resumed read never lands mid-code-unit.

Parsers are per-source and declarative: PARSERS holds named regexes with
`ts`/`level`/`message` groups (iso, bracket, syslog), plus `jsonl` (one JSON
object per line — the shape the trainer, the research loop and the telemetry
feed actually write) and `plain` (no timestamp; level sniffed from the line).
A source may also carry its own `regex` — any pattern with a `message` group —
which is the escape hatch for a format no built-in covers.

Timestamps are parsed WITHOUT strptime: hardcoded English month names plus
calendar.timegm, exactly like certmon's notAfter parse, so a German locale or
a host TZ change cannot move an event. A naive timestamp (no Z, no offset) is
read as UTC unless the source declares `tz_offset` seconds east of UTC. BSD
syslog lines carry no year, so the collector supplies the log file's mtime
year — deterministic given the file, never "now".

Extension points:
- Sources as config: load_sources() overlays a JSON file on DEFAULT_SOURCES
  (uptime.load_targets merge semantics — dicts merge, `false` drops a source),
  so a new log file is a config edit, not a code change.
- Custom formats: put a `regex` with a named `message` group on a source.
- Rollups: rollup() buckets counts by level/source/time window — the input for
  a static dashboard or a digest, computed in sqlite, not in a SaaS query DSL.
- Family gate: to_diagnostics() maps error/critical lines onto the openswap
  diagnostic schema, so `logs query --fail-on error` gates a cron or CI run
  exactly like a prose finding or an uptime outage.
"""

from __future__ import annotations

import calendar
import codecs
import copy
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from bigbang.core import openswap

# ---- levels -----------------------------------------------------------------

LEVEL_CRITICAL = "critical"
LEVEL_ERROR = "error"
LEVEL_WARNING = "warning"
LEVEL_INFO = "info"
LEVEL_DEBUG = "debug"
LEVEL_TRACE = "trace"

# most severe first — rank 0 is the worst, mirroring openswap.SEVERITIES
LEVELS = (
    LEVEL_CRITICAL,
    LEVEL_ERROR,
    LEVEL_WARNING,
    LEVEL_INFO,
    LEVEL_DEBUG,
    LEVEL_TRACE,
)
_LEVEL_RANK = {lv: i for i, lv in enumerate(LEVELS)}
DEFAULT_LEVEL = LEVEL_INFO

# Every spelling this box actually emits: python logging, syslog priorities,
# node/pino words, and the shouty variants. Normalizing here means the store
# holds ONE vocabulary and --level comparisons are a plain integer compare.
_LEVEL_ALIASES = {
    "emerg": LEVEL_CRITICAL,
    "emergency": LEVEL_CRITICAL,
    "alert": LEVEL_CRITICAL,
    "crit": LEVEL_CRITICAL,
    "critical": LEVEL_CRITICAL,
    "fatal": LEVEL_CRITICAL,
    "panic": LEVEL_CRITICAL,
    "err": LEVEL_ERROR,
    "error": LEVEL_ERROR,
    "severe": LEVEL_ERROR,
    "exception": LEVEL_ERROR,
    "warn": LEVEL_WARNING,
    "warning": LEVEL_WARNING,
    "notice": LEVEL_INFO,
    "info": LEVEL_INFO,
    "information": LEVEL_INFO,
    "log": LEVEL_INFO,
    "debug": LEVEL_DEBUG,
    "fine": LEVEL_DEBUG,
    "verbose": LEVEL_DEBUG,
    "trace": LEVEL_TRACE,
}

# Level severity -> openswap diagnostic severity (info/debug/trace emit nothing)
_LEVEL_SEVERITY = {
    LEVEL_CRITICAL: "error",
    LEVEL_ERROR: "error",
    LEVEL_WARNING: "warning",
}

_SNIFF_RE = re.compile(
    r"\b(EMERG(?:ENCY)?|ALERT|CRIT(?:ICAL)?|FATAL|PANIC|ERR(?:OR)?|WARN(?:ING)?"
    r"|NOTICE|INFO|DEBUG|TRACE)\b",
    re.IGNORECASE,
)


def normalize_level(value: Any) -> str | None:
    """Any spelling of a log level -> the canonical one, or None if unknown."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # syslog numeric priorities 0..7 (emerg..debug); anything else is not a level
        numeric = {
            0: LEVEL_CRITICAL,
            1: LEVEL_CRITICAL,
            2: LEVEL_CRITICAL,
            3: LEVEL_ERROR,
            4: LEVEL_WARNING,
            5: LEVEL_INFO,
            6: LEVEL_INFO,
            7: LEVEL_DEBUG,
        }
        return numeric.get(int(value))
    text = str(value).strip().strip("[]()<>:").lower()
    return _LEVEL_ALIASES.get(text)


def level_rank(level: str) -> int:
    """Lower is more severe; unknown levels sort last (never silently 'critical')."""
    return _LEVEL_RANK.get(level, len(LEVELS))


def sniff_level(text: str) -> str | None:
    """Most severe level word appearing in a line, or None.

    The fallback for formats with no level field. Deliberately greedy: a line
    reading "connection error: timed out" is an error even when the writer
    never labelled it. Nothing is invented — no match returns None and the
    caller applies the source's declared default.
    """
    best: str | None = None
    for m in _SNIFF_RE.finditer(text or ""):
        lv = normalize_level(m.group(1))
        if lv is not None and (best is None or level_rank(lv) < level_rank(best)):
            best = lv
    return best


# ---- encoding detection -----------------------------------------------------

# UTF-32-LE's BOM (ff fe 00 00) STARTS WITH UTF-16-LE's (ff fe), so the wider
# BOM must be tested first or every UTF-32-LE file is misread as UTF-16-LE.
_BOM_TABLE: tuple[tuple[bytes, str, int], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32-le", 4),
    (codecs.BOM_UTF32_BE, "utf-32-be", 4),
    (codecs.BOM_UTF8, "utf-8", 1),
    (codecs.BOM_UTF16_LE, "utf-16-le", 2),
    (codecs.BOM_UTF16_BE, "utf-16-be", 2),
)

# The byte pattern a newline takes in each encoding — line splitting happens on
# BYTES so the consumed count is exact and offsets stay resumable.
_NEWLINE_BYTES = {
    "utf-8": b"\n",
    "latin-1": b"\n",
    "utf-16-le": b"\n\x00",
    "utf-16-be": b"\x00\n",
    "utf-32-le": b"\n\x00\x00\x00",
    "utf-32-be": b"\x00\x00\x00\n",
}

DETECT_BYTES = 4096
DEFAULT_MAX_BYTES = 8 * 1024 * 1024


def _decodes_as_utf8(sample: bytes) -> bool:
    """True if the sample is valid UTF-8, tolerating a truncated tail character."""
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError as exc:
        # a multi-byte char cut by the sample boundary is not an encoding verdict
        return exc.start >= len(sample) - 3


def detect_encoding(sample: bytes) -> dict[str, Any]:
    """Sniff a file head -> {encoding, bom_len, unit, via}.

    `unit` is bytes per code unit (1/2/4) and is what keeps resumed byte
    offsets aligned. `via` records HOW the verdict was reached (bom |
    nul-pattern | utf-8 | fallback) so a surprising decode is explainable
    rather than magic.
    """
    for bom, enc, unit in _BOM_TABLE:
        if sample.startswith(bom):
            return {"encoding": enc, "bom_len": len(bom), "unit": unit, "via": "bom"}
    head = sample[:DETECT_BYTES]
    pairs = len(head) // 2
    if pairs >= 8:
        # BOM-less UTF-16: ASCII text puts a NUL in every high byte, so the NULs
        # sit entirely on odd byte positions (LE) or even ones (BE).
        nul_even = sum(1 for i in range(0, pairs * 2, 2) if head[i] == 0)
        nul_odd = sum(1 for i in range(1, pairs * 2, 2) if head[i] == 0)
        if nul_odd >= pairs * 0.6 and nul_even <= pairs * 0.1:
            return {
                "encoding": "utf-16-le",
                "bom_len": 0,
                "unit": 2,
                "via": "nul-pattern",
            }
        if nul_even >= pairs * 0.6 and nul_odd <= pairs * 0.1:
            return {
                "encoding": "utf-16-be",
                "bom_len": 0,
                "unit": 2,
                "via": "nul-pattern",
            }
    if _decodes_as_utf8(head):
        return {"encoding": "utf-8", "bom_len": 0, "unit": 1, "via": "utf-8"}
    # latin-1 maps every byte to a code point, so ingest never dies on a blob
    return {"encoding": "latin-1", "bom_len": 0, "unit": 1, "via": "fallback"}


def _rfind_aligned(raw: bytes, pattern: bytes, unit: int) -> int:
    """Last index of `pattern` that sits on a code-unit boundary, or -1.

    In UTF-16-LE the two bytes of b"\\n\\x00" can also appear straddling two
    unrelated code units (U+xx0A followed by U+00xx), so an unaligned hit is
    not a newline and must be skipped.
    """
    idx = raw.rfind(pattern)
    while idx > 0 and idx % unit != 0:
        idx = raw.rfind(pattern, 0, idx)
    if idx < 0 or idx % unit != 0:
        return -1
    return idx


def split_complete_lines(
    raw: bytes,
    *,
    encoding: str,
    unit: int = 1,
    include_partial: bool = False,
) -> tuple[list[str], int]:
    """Decode whole lines out of a chunk -> (lines, bytes_consumed).

    Only bytes up to and including the LAST newline are consumed; a trailing
    partial line stays unconsumed so the next pass picks it up once the writer
    finishes it. `include_partial` consumes the tail too — the right choice for
    a static file that simply lacks a final newline, the wrong one for a live
    tail. `bytes_consumed` is always a multiple of `unit`.
    """
    if not raw:
        return [], 0
    nl = _NEWLINE_BYTES.get(encoding, b"\n")
    idx = _rfind_aligned(raw, nl, unit)
    if idx < 0:
        if not include_partial:
            return [], 0
        consumed = (len(raw) // unit) * unit
    elif include_partial:
        consumed = (len(raw) // unit) * unit
    else:
        consumed = idx + len(nl)
    if consumed <= 0:
        return [], 0
    text = raw[:consumed].decode(encoding, errors="replace")
    if text.endswith("\n"):
        text = text[:-1]
    # split on \n only (never str.splitlines, which also breaks on \v, \f and
    # U+2028 — characters that appear INSIDE real log payloads)
    return [ln.rstrip("\r") for ln in text.split("\n")], consumed


# ---- timestamps -------------------------------------------------------------

_MONTHS = {
    m: i
    for i, m in enumerate(
        "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1
    )
}

_ISO_RE = re.compile(
    r"(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})[T ](?P<h>\d{2}):(?P<mi>\d{2})"
    r"(?::(?P<s>\d{2})(?:[.,](?P<frac>\d{1,9}))?)?"
    r"(?P<tz>Z|z|[+-]\d{2}:?\d{2})?"
)
_SYSLOG_TS_RE = re.compile(
    r"(?P<mon>[A-Z][a-z]{2})\s+(?P<d>\d{1,2})\s+"
    r"(?P<h>\d{1,2}):(?P<mi>\d{2}):(?P<s>\d{2})"
)
_EPOCH_RE = re.compile(r"\d{9,14}(?:\.\d+)?")
# epochs above this are milliseconds, not seconds (1e11 s is the year 5138)
_MS_THRESHOLD = 1e11


def _tz_seconds(tz: str | None) -> float | None:
    """'Z' / '+05:30' / '-0500' -> seconds east of UTC; None when absent."""
    if not tz:
        return None
    if tz in ("Z", "z"):
        return 0.0
    sign = -1.0 if tz[0] == "-" else 1.0
    body = tz[1:].replace(":", "")
    return sign * (int(body[:2]) * 3600 + int(body[2:4]) * 60)


def parse_timestamp(
    value: Any,
    *,
    year: int | None = None,
    tz_offset: float = 0.0,
) -> float | None:
    """A log timestamp -> epoch seconds, or None when it is not one.

    Accepts epoch numbers (seconds or milliseconds), ISO-8601 (space or 'T',
    optional seconds, optional fraction, optional Z/offset) and BSD syslog
    ('Jul 19 13:45:01', which needs the caller's `year` because the line has
    none). Assembled with calendar.timegm and hardcoded English month names —
    never strptime — so the result cannot depend on the host locale or TZ.
    A timestamp with no zone is read as UTC shifted by `tz_offset` seconds east.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if abs(v) >= _MS_THRESHOLD else v
    text = str(value).strip()
    if not text:
        return None
    m = _ISO_RE.match(text)
    if m:
        g = m.groupdict()
        try:
            stamp = (
                int(g["y"]),
                int(g["mo"]),
                int(g["d"]),
                int(g["h"]),
                int(g["mi"]),
                int(g["s"] or 0),
                0,
                0,
                0,
            )
            epoch = float(calendar.timegm(stamp))
        except ValueError:
            return None
        if g["frac"]:
            epoch += float("0." + g["frac"])
        off = _tz_seconds(g["tz"])
        return epoch - (tz_offset if off is None else off)
    m = _SYSLOG_TS_RE.match(text)
    if m and year is not None:
        g = m.groupdict()
        month = _MONTHS.get(g["mon"])
        if month is None:
            return None
        try:
            stamp = (
                int(year),
                month,
                int(g["d"]),
                int(g["h"]),
                int(g["mi"]),
                int(g["s"]),
                0,
                0,
                0,
            )
        except ValueError:
            return None
        return float(calendar.timegm(stamp)) - tz_offset
    m = _EPOCH_RE.fullmatch(text)
    if m:
        v = float(text)
        return v / 1000.0 if abs(v) >= _MS_THRESHOLD else v
    return None


# ---- parsers ----------------------------------------------------------------

_TS_RE_PART = (
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d{1,9})?)?"
    r"(?:Z|z|[+-]\d{2}:?\d{2})?"
)
_LVL_RE_PART = r"[A-Za-z]{3,11}"

PARSER_JSONL = "jsonl"
PARSER_PLAIN = "plain"

PARSERS: dict[str, dict[str, Any]] = {
    "iso": {
        "kind": "regex",
        "regex": (
            rf"^(?P<ts>{_TS_RE_PART})\s+[\[(]?(?P<level>{_LVL_RE_PART})[\])]?"
            rf"\s*[:\-|]?\s*(?P<message>.*)$"
        ),
        "description": (
            "ISO-8601 timestamp, then a bare or bracketed level, then the "
            "message — python logging's default layout and most app loggers"
        ),
        "example": "2026-07-19 13:45:01,123 ERROR trainer: step 15 diverged",
    },
    "bracket": {
        "kind": "regex",
        "regex": (
            rf"^\[(?P<ts>{_TS_RE_PART})\]\s*\[(?P<level>{_LVL_RE_PART})\]"
            rf"\s*(?P<message>.*)$"
        ),
        "description": "fully bracketed prefix — [timestamp] [LEVEL] message",
        "example": "[2026-07-19T13:45:01Z] [WARN] gpu clocks pinned at 780MHz",
    },
    "syslog": {
        "kind": "regex",
        "regex": (
            r"^(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{1,2}:\d{2}:\d{2})\s+"
            r"(?P<host>\S+)\s+(?P<proc>[^:\[\s]+)(?:\[(?P<pid>\d+)\])?"
            r":\s*(?P<message>.*)$"
        ),
        "description": (
            "BSD syslog — 'Mon DD HH:MM:SS host proc[pid]: message'. The line "
            "carries no year, so the collector supplies the file's mtime year "
            "and the level is sniffed from the message"
        ),
        "example": "Jul 19 13:45:01 dottie trainer[8123]: ERROR checkpoint lost",
    },
    PARSER_JSONL: {
        "kind": "jsonl",
        "regex": None,
        "description": (
            "one JSON object per line — the shape the trainer, the research "
            "loop and the telemetry feed actually write; ts/level/message are "
            "read from the usual key spellings"
        ),
        "example": '{"ts": 1784488531.94, "level": "info", "event": "phase_enter"}',
    },
    PARSER_PLAIN: {
        "kind": "plain",
        "regex": None,
        "description": (
            "no timestamp field: the whole line is the message and the level is "
            "sniffed from it (the honest default for unstructured stdout)"
        ),
        "example": "Traceback (most recent call last): ...",
    },
}

# JSON key spellings seen in the wild, in preference order
_JSON_TS_KEYS = ("ts", "timestamp", "time", "@timestamp", "asctime", "eventTime")
_JSON_LEVEL_KEYS = ("level", "levelname", "severity", "lvl", "loglevel", "priority")
_JSON_MSG_KEYS = ("message", "msg", "event", "action", "text", "log")

LEVEL_FROM_FIELD = "field"
LEVEL_FROM_SNIFF = "sniff"
LEVEL_FROM_DEFAULT = "default"


def parser_catalog() -> list[dict[str, Any]]:
    """The built-in parsers, for `scout logs parsers` — discoverability."""
    return [
        {
            "name": name,
            "kind": spec["kind"],
            "description": spec["description"],
            "example": spec["example"],
            "regex": spec["regex"],
        }
        for name, spec in PARSERS.items()
    ]


def _first_key(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in obj:
            return obj[k]
    return None


def parse_line(
    line: str,
    *,
    parser: str = PARSER_PLAIN,
    regex: str | None = None,
    year: int | None = None,
    tz_offset: float = 0.0,
    default_level: str = DEFAULT_LEVEL,
) -> dict[str, Any]:
    """One raw line -> {ts, level, level_from, message, parsed, parser}.

    `parsed` means the declared parser's SHAPE matched this line. A non-plain
    parser that does not match falls back to plain extraction with
    parsed=False, so the collector's unparsed count tells you your parser
    choice is wrong for that source instead of hiding it. `plain` matches
    everything by construction and always reports parsed=True — which is why
    picking the right parser matters.

    A custom `regex` (from a source config) wins over `parser`; it needs a
    `message` group and may add `ts` and `level` groups.
    """
    spec = PARSERS.get(parser, PARSERS[PARSER_PLAIN])
    pattern = regex if regex else spec["regex"]
    kind = "regex" if regex else spec["kind"]

    def _plain(parsed: bool) -> dict[str, Any]:
        sniffed = sniff_level(line)
        return {
            "ts": None,
            "level": sniffed or default_level,
            "level_from": LEVEL_FROM_SNIFF if sniffed else LEVEL_FROM_DEFAULT,
            "message": line.strip(),
            "parsed": parsed,
            "parser": parser,
        }

    if kind == "jsonl":
        try:
            obj = json.loads(line)
        except ValueError:
            return _plain(False)
        if not isinstance(obj, dict):
            return _plain(False)
        raw_msg = _first_key(obj, _JSON_MSG_KEYS)
        if raw_msg is None:
            # no message-ish key: keep the object itself as the message rather
            # than inventing an empty line (the payload IS the event)
            message = json.dumps(obj, sort_keys=True, default=str)
        elif isinstance(raw_msg, str):
            message = raw_msg
        else:
            message = json.dumps(raw_msg, sort_keys=True, default=str)
        level = normalize_level(_first_key(obj, _JSON_LEVEL_KEYS))
        level_from = LEVEL_FROM_FIELD
        if level is None:
            level = sniff_level(message)
            level_from = LEVEL_FROM_SNIFF
        if level is None:
            level = default_level
            level_from = LEVEL_FROM_DEFAULT
        return {
            "ts": parse_timestamp(
                _first_key(obj, _JSON_TS_KEYS), year=year, tz_offset=tz_offset
            ),
            "level": level,
            "level_from": level_from,
            "message": message,
            "parsed": True,
            "parser": parser,
        }

    if kind == "plain" or not pattern:
        return _plain(True)

    m = re.match(pattern, line)
    if m is None:
        return _plain(False)
    groups = m.groupdict()
    message = (groups.get("message") or "").strip()
    level = normalize_level(groups.get("level"))
    level_from = LEVEL_FROM_FIELD
    if level is None:
        level = sniff_level(message) or sniff_level(line)
        level_from = LEVEL_FROM_SNIFF
    if level is None:
        level = default_level
        level_from = LEVEL_FROM_DEFAULT
    return {
        "ts": parse_timestamp(groups.get("ts"), year=year, tz_offset=tz_offset),
        "level": level,
        "level_from": level_from,
        "message": message,
        "parsed": True,
        "parser": parser,
    }


# ---- sources (policy-as-config) ---------------------------------------------

DB_REL = Path(".scout") / "logs.db"
SCHEMA_VERSION = "1"

# This box's own logs, as REPO-RELATIVE paths resolved against --root (default
# cwd) — never an absolute path or a $HOME layout, so the same config works on
# the laptop, in a container and in CI. run.log is the UTF-16-LE one.
DEFAULT_SOURCES: dict[str, dict[str, Any]] = {
    "research-loop": {
        "path": "apps/dottie/data/research/logs/run.log",
        "parser": PARSER_JSONL,
    },
    "trainer": {
        "path": "apps/ava-factory/runs/*/reports/*/train_stdout.log",
        "parser": PARSER_JSONL,
    },
    "telemetry": {
        "path": "apps/ava-factory/reports/*_telemetry.jsonl",
        "parser": PARSER_JSONL,
    },
}

_GLOB_CHARS = ("*", "?", "[")


def load_sources(path: str | None = None) -> dict[str, dict[str, Any]]:
    """DEFAULT_SOURCES overlaid with an optional JSON file.

    Merge semantics mirror uptime.load_targets: dicts merge key-by-key, and a
    bare `false` (or {"enabled": false}) drops a source. Every source needs a
    non-empty `path` (a file or a glob); `parser` must name a built-in; a
    `regex` must compile and declare a `message` group; `level` must be a known
    level; `tz_offset` must be a number. Raises ValueError / OSError / json
    errors for the CLI to turn into a fail_agent envelope.
    """
    sources = copy.deepcopy(DEFAULT_SOURCES)
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("sources file must be a JSON object of {name: config}")
        for name, cfg in raw.items():
            if cfg is False or (isinstance(cfg, dict) and cfg.get("enabled") is False):
                sources.pop(name, None)
                continue
            if not isinstance(cfg, dict):
                raise ValueError(f"source {name!r}: config must be an object or false")
            sources.setdefault(name, {}).update(cfg)
    for name, cfg in sources.items():
        p = cfg.get("path")
        if not (isinstance(p, str) and p.strip()):
            raise ValueError(f"source {name!r}: needs a non-empty path or glob")
        parser = cfg.setdefault("parser", PARSER_PLAIN)
        if parser not in PARSERS:
            raise ValueError(
                f"source {name!r}: unknown parser {parser!r} "
                f"(choose from {'|'.join(PARSERS)})"
            )
        regex = cfg.get("regex")
        if regex is not None:
            if not isinstance(regex, str):
                raise ValueError(f"source {name!r}: regex must be a string")
            try:
                compiled = re.compile(regex)
            except re.error as exc:
                raise ValueError(f"source {name!r}: bad regex — {exc}") from exc
            if "message" not in compiled.groupindex:
                raise ValueError(
                    f"source {name!r}: regex needs a named (?P<message>...) group"
                )
        level = cfg.get("level")
        if level is not None and normalize_level(level) is None:
            raise ValueError(
                f"source {name!r}: unknown level {level!r} "
                f"(choose from {'|'.join(LEVELS)})"
            )
        tz = cfg.get("tz_offset")
        if tz is not None and (isinstance(tz, bool) or not isinstance(tz, (int, float))):
            raise ValueError(f"source {name!r}: tz_offset must be a number of seconds")
    return sources


def resolve_files(cfg: dict[str, Any], *, root: str | Path = ".") -> list[Path]:
    """Expand one source's path (a file or a glob) against `root`.

    pathlib only — no os.path string surgery, no shell globbing — so a Windows
    path with a drive letter and a POSIX one behave identically. Sorted so a
    pass over a glob is deterministic; directories and dangling matches drop.
    """
    raw = str(cfg["path"])
    p = Path(raw)
    has_glob = any(ch in raw for ch in _GLOB_CHARS)
    if p.is_absolute():
        if not has_glob:
            return [p] if p.is_file() else []
        anchor = Path(p.anchor)
        rel = p.relative_to(p.anchor).as_posix()
        return sorted(x for x in anchor.glob(rel) if x.is_file())
    base = Path(root)
    if not has_glob:
        target = base / p
        return [target] if target.is_file() else []
    return sorted(x for x in base.glob(p.as_posix()) if x.is_file())


def display_path(path: Path, root: str | Path = ".") -> str:
    """Root-relative POSIX path when possible, else absolute POSIX.

    This string is the offset table's key AND what lands in the store, so it
    must be stable across shells: forward slashes everywhere, and relative to
    `root` so a moved checkout does not orphan every offset.
    """
    p = Path(path)
    base = Path(root)
    try:
        return p.resolve().relative_to(base.resolve()).as_posix()
    except (ValueError, OSError):
        return p.as_posix()


# ---- store ------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    ts REAL NOT NULL,
    dated INTEGER NOT NULL,
    ingest_ts REAL NOT NULL,
    level TEXT NOT NULL,
    level_rank INTEGER NOT NULL,
    message TEXT NOT NULL,
    raw TEXT NOT NULL,
    parser TEXT NOT NULL,
    parsed INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_ts ON entries(ts);
CREATE INDEX IF NOT EXISTS idx_entries_source_ts ON entries(source, ts);
CREATE INDEX IF NOT EXISTS idx_entries_level_ts ON entries(level_rank, ts);
CREATE TABLE IF NOT EXISTS offsets(
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    offset INTEGER NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL,
    encoding TEXT,
    lines INTEGER NOT NULL DEFAULT 0,
    ingested INTEGER NOT NULL DEFAULT 0,
    rotations INTEGER NOT NULL DEFAULT 0,
    updated_ts REAL NOT NULL,
    PRIMARY KEY(source, path)
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the log store — its OWN sqlite file.

    Never the #2 uptime ledger: log volume is bursty by nature (one trainer
    step can write hundreds of lines) and must not contend with monitoring
    probes for the same write lock.
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


def get_offset(
    conn: sqlite3.Connection, source: str, path: str
) -> dict[str, Any] | None:
    """The stored tail position for one (source, file), or None if never read."""
    row = conn.execute(
        "SELECT * FROM offsets WHERE source = ? AND path = ?", (source, path)
    ).fetchone()
    return None if row is None else dict(row)


def list_offsets(conn: sqlite3.Connection, *, source: str | None = None) -> list[dict]:
    """Every tracked file's tail position — the 'am I caught up?' read."""
    rows = conn.execute(
        "SELECT * FROM offsets WHERE (? IS NULL OR source = ?)"
        " ORDER BY source ASC, path ASC",
        (source, source),
    ).fetchall()
    return [dict(r) for r in rows]


def save_offset(
    conn: sqlite3.Connection,
    source: str,
    path: str,
    *,
    offset: int,
    size: int,
    mtime: float | None,
    encoding: str | None,
    lines: int,
    ingested: int,
    rotations: int,
    now: float,
) -> None:
    """Upsert one (source, file) tail position. The whole incrementality story."""
    conn.execute(
        "INSERT INTO offsets(source, path, offset, size, mtime, encoding, lines,"
        " ingested, rotations, updated_ts) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(source, path) DO UPDATE SET offset=excluded.offset,"
        " size=excluded.size, mtime=excluded.mtime, encoding=excluded.encoding,"
        " lines=excluded.lines, ingested=excluded.ingested,"
        " rotations=excluded.rotations, updated_ts=excluded.updated_ts",
        (
            source,
            path,
            int(offset),
            int(size),
            mtime,
            encoding,
            int(lines),
            int(ingested),
            int(rotations),
            float(now),
        ),
    )
    conn.commit()


def record_entries(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> int:
    """Insert parsed entries; returns the count written."""
    if not rows:
        return 0
    conn.executemany(
        "INSERT INTO entries(source, path, line_no, ts, dated, ingest_ts, level,"
        " level_rank, message, raw, parser, parsed)"
        " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r["source"],
                r["path"],
                int(r["line_no"]),
                float(r["ts"]),
                1 if r["dated"] else 0,
                float(r["ingest_ts"]),
                r["level"],
                level_rank(r["level"]),
                r["message"],
                r["raw"],
                r["parser"],
                1 if r["parsed"] else 0,
            )
            for r in rows
        ],
    )
    conn.commit()
    return len(rows)


# ---- collection -------------------------------------------------------------


def read_head(path: str | Path, *, size: int = DETECT_BYTES) -> bytes:
    """The first `size` bytes — opened, read, CLOSED. For encoding detection.

    A separate tiny read (rather than trusting a stored encoding) means a file
    that was rewritten in a different encoding is detected on the very next
    pass instead of decoding as garbage forever.
    """
    with Path(path).open("rb") as fh:
        return fh.read(size)


def read_chunk(
    path: str | Path, offset: int, *, max_bytes: int = DEFAULT_MAX_BYTES
) -> dict[str, Any]:
    """Read new bytes from `offset` -> {raw, size, mtime, start, rotated, capped}.

    Path.stat() (os.stat) supplies size and mtime BEFORE the read, so a size
    smaller than the stored offset is recognized as a rotation/truncation and
    the read restarts at 0. The handle is opened, seeked, read and closed in
    one `with` — nothing is held between passes, which is what lets a Windows
    writer rename or delete the file underneath us.
    """
    p = Path(path)
    st = p.stat()
    size = int(st.st_size)
    rotated = size < int(offset)
    start = 0 if rotated else max(0, int(offset))
    raw = b""
    if start < size:
        with p.open("rb") as fh:
            fh.seek(start)
            raw = fh.read(max_bytes)
    return {
        "raw": raw,
        "size": size,
        "mtime": float(st.st_mtime),
        "start": start,
        "rotated": rotated,
        # capped means more bytes are waiting: run another pass to drain them
        "capped": len(raw) >= max_bytes,
    }


def collect_file(
    conn: sqlite3.Connection,
    source: str,
    file_path: str | Path,
    cfg: dict[str, Any],
    *,
    root: str | Path = ".",
    record: bool = True,
    now: float | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    include_partial: bool = False,
) -> dict[str, Any]:
    """Tail ONE file once: detect, seek, parse whole lines, store, report.

    Returns the per-file result even on an OSError (with `error` set): a log
    pipeline that dies because one file is locked is worse than useless.
    """
    now = time.time() if now is None else float(now)
    key = display_path(Path(file_path), root)
    prev = get_offset(conn, source, key) or {}
    result: dict[str, Any] = {
        "source": source,
        "path": key,
        "start": int(prev.get("offset", 0)),
        "offset": int(prev.get("offset", 0)),
        "size": None,
        "encoding": prev.get("encoding"),
        "detected_via": None,
        "rotated": False,
        "capped": False,
        "lines": 0,
        "blank": 0,
        "ingested": 0,
        "parsed": 0,
        "unparsed": 0,
        "dated": 0,
        "by_level": {},
        "level_from": {},
        "error": None,
    }
    try:
        enc = detect_encoding(read_head(file_path))
        chunk = read_chunk(file_path, result["start"], max_bytes=max_bytes)
    except OSError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    unit = int(enc["unit"])
    bom_len = int(enc["bom_len"])
    result["encoding"] = enc["encoding"]
    result["detected_via"] = enc["via"]
    result["size"] = chunk["size"]
    result["rotated"] = chunk["rotated"]
    result["capped"] = chunk["capped"]

    start = chunk["start"]
    raw = chunk["raw"]
    if start < bom_len:
        # never hand the BOM to the parser, and never resume mid-code-unit
        raw = raw[bom_len - start :]
        start = bom_len
    elif (start - bom_len) % unit:
        drop = unit - ((start - bom_len) % unit)
        raw = raw[drop:]
        start += drop
    result["start"] = start

    prev_lines = 0 if chunk["rotated"] else int(prev.get("lines", 0))
    prev_ingested = 0 if chunk["rotated"] else int(prev.get("ingested", 0))
    rotations = int(prev.get("rotations", 0)) + (1 if chunk["rotated"] else 0)

    lines, consumed = split_complete_lines(
        raw, encoding=enc["encoding"], unit=unit, include_partial=include_partial
    )
    # syslog lines carry no year — the file's own mtime year is deterministic
    year = time.gmtime(chunk["mtime"]).tm_year
    parser = cfg.get("parser", PARSER_PLAIN)
    regex = cfg.get("regex")
    default_level = normalize_level(cfg.get("level")) or DEFAULT_LEVEL
    tz_offset = float(cfg.get("tz_offset") or 0.0)

    rows: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        line_no = prev_lines + i + 1
        if not line.strip():
            result["blank"] += 1
            continue
        got = parse_line(
            line,
            parser=parser,
            regex=regex,
            year=year,
            tz_offset=tz_offset,
            default_level=default_level,
        )
        dated = got["ts"] is not None
        rows.append(
            {
                "source": source,
                "path": key,
                "line_no": line_no,
                # `ts` is the EFFECTIVE event time: the parsed one when the line
                # carried one, else ingest time. `dated` records which, so a
                # time filter always works and never silently lies.
                "ts": got["ts"] if dated else now,
                "dated": dated,
                "ingest_ts": now,
                "level": got["level"],
                "message": got["message"],
                "raw": line,
                "parser": got["parser"],
                "parsed": got["parsed"],
            }
        )
        result["parsed" if got["parsed"] else "unparsed"] += 1
        result["dated"] += 1 if dated else 0
        result["by_level"][got["level"]] = result["by_level"].get(got["level"], 0) + 1
        lf = got["level_from"]
        result["level_from"][lf] = result["level_from"].get(lf, 0) + 1

    result["lines"] = len(lines)
    result["ingested"] = len(rows)
    # min() is a no-op in every normal pass (we never read past EOF); it guards
    # the pathological file that is SHORTER than its own BOM, which would
    # otherwise store offset > size and look rotated on every subsequent pass
    result["offset"] = min(start + consumed, chunk["size"])
    if record:
        record_entries(conn, rows)
        save_offset(
            conn,
            source,
            key,
            offset=result["offset"],
            size=chunk["size"],
            mtime=chunk["mtime"],
            encoding=enc["encoding"],
            lines=prev_lines + len(lines),
            ingested=prev_ingested + len(rows),
            rotations=rotations,
            now=now,
        )
    return result


def collect(
    conn: sqlite3.Connection,
    sources: dict[str, dict[str, Any]],
    *,
    root: str | Path = ".",
    record: bool = True,
    now: float | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    include_partial: bool = False,
) -> dict[str, Any]:
    """One tailing pass over every file of every source.

    Sources with no matching file are reported (files: 0) rather than dropped —
    "the log I asked for does not exist" is the finding, not silence.
    """
    now = time.time() if now is None else float(now)
    files: list[dict[str, Any]] = []
    per_source: dict[str, Any] = {}
    totals = {"ingested": 0, "parsed": 0, "unparsed": 0, "lines": 0, "dated": 0}
    by_level: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    for name in sorted(sources):
        cfg = sources[name]
        matched = resolve_files(cfg, root=root)
        results = [
            collect_file(
                conn,
                name,
                fp,
                cfg,
                root=root,
                record=record,
                now=now,
                max_bytes=max_bytes,
                include_partial=include_partial,
            )
            for fp in matched
        ]
        files.extend(results)
        for r in results:
            for k in totals:
                totals[k] += int(r[k])
            for lv, n in r["by_level"].items():
                by_level[lv] = by_level.get(lv, 0) + n
            if r["error"]:
                errors.append({"source": name, "path": r["path"], "error": r["error"]})
        per_source[name] = {
            "pattern": cfg["path"],
            "parser": cfg.get("parser", PARSER_PLAIN),
            "files": len(matched),
            "ingested": sum(r["ingested"] for r in results),
            "capped": any(r["capped"] for r in results),
        }
    return {
        "recorded": record,
        "root": Path(root).as_posix(),
        "files": files,
        "sources": per_source,
        "by_level": by_level,
        "errors": errors,
        **totals,
    }


# ---- query ------------------------------------------------------------------


def query(
    conn: sqlite3.Connection,
    *,
    source: str | None = None,
    level: str | None = None,
    since: float | None = None,
    until: float | None = None,
    contains: str | None = None,
    limit: int = 100,
    newest_first: bool = True,
) -> list[dict[str, Any]]:
    """Filter entries by source, minimum severity, time range and substring.

    `level` is a FLOOR, not an equality test: level="warning" returns warning,
    error and critical, which is what an operator actually means. `contains`
    matches the parsed message OR the raw line (ASCII-case-insensitive via
    sqlite instr/lower) so a jsonl source whose message is just an event name
    is still searchable by payload. Time bounds are inclusive and compare
    against the effective `ts` (see collect_file).
    """
    rank = None if level is None else level_rank(level)
    order = "DESC" if newest_first else "ASC"
    sql = (
        "SELECT id, source, path, line_no, ts, dated, ingest_ts, level,"
        " level_rank, message, raw, parser, parsed FROM entries"
        " WHERE (? IS NULL OR source = ?)"
        " AND (? IS NULL OR level_rank <= ?)"
        " AND (? IS NULL OR ts >= ?)"
        " AND (? IS NULL OR ts <= ?)"
        " AND (? IS NULL OR instr(lower(message), lower(?)) > 0"
        "      OR instr(lower(raw), lower(?)) > 0)"
        " ORDER BY ts " + order + ", id " + order + " LIMIT ?"
    )
    rows = conn.execute(
        sql,
        (
            source,
            source,
            rank,
            rank,
            since,
            since,
            until,
            until,
            contains,
            contains,
            contains,
            int(limit),
        ),
    ).fetchall()
    return [dict(r) for r in rows]


def rollup(
    conn: sqlite3.Connection,
    *,
    source: str | None = None,
    level: str | None = None,
    since: float | None = None,
    until: float | None = None,
    bucket_seconds: float = 3600.0,
) -> dict[str, Any]:
    """Counts by level, by source and by time bucket over one window.

    The Papertrail/Splunk "how much and how bad, per hour" view, computed in
    sqlite instead of a hosted query language. Raises ValueError on a
    non-positive bucket (a zero-width bucket is a division by zero, not a
    default).
    """
    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds must be > 0")
    rank = None if level is None else level_rank(level)
    where = (
        " WHERE (? IS NULL OR source = ?)"
        " AND (? IS NULL OR level_rank <= ?)"
        " AND (? IS NULL OR ts >= ?)"
        " AND (? IS NULL OR ts <= ?)"
    )
    params = (source, source, rank, rank, since, since, until, until)
    by_level = {
        r["level"]: r["n"]
        for r in conn.execute(
            "SELECT level, COUNT(*) AS n FROM entries" + where + " GROUP BY level",
            params,
        ).fetchall()
    }
    by_source = {
        r["source"]: r["n"]
        for r in conn.execute(
            "SELECT source, COUNT(*) AS n FROM entries" + where + " GROUP BY source",
            params,
        ).fetchall()
    }
    span = conn.execute(
        "SELECT COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts,"
        " SUM(dated) AS dated, SUM(parsed) AS parsed FROM entries" + where,
        params,
    ).fetchone()
    bucket_rows = conn.execute(
        "SELECT CAST(ts / ? AS INTEGER) * ? AS bucket, level, COUNT(*) AS n"
        " FROM entries" + where + " GROUP BY bucket, level ORDER BY bucket ASC",
        (bucket_seconds, bucket_seconds, *params),
    ).fetchall()
    buckets: dict[float, dict[str, Any]] = {}
    for r in bucket_rows:
        b = buckets.setdefault(
            float(r["bucket"]), {"start": float(r["bucket"]), "count": 0, "by_level": {}}
        )
        b["count"] += int(r["n"])
        b["by_level"][r["level"]] = int(r["n"])
    total = int(span["n"] or 0)
    return {
        "total": total,
        "dated": int(span["dated"] or 0),
        "parsed": int(span["parsed"] or 0),
        "first_ts": span["first_ts"],
        "last_ts": span["last_ts"],
        "by_level": {lv: by_level.get(lv, 0) for lv in LEVELS if lv in by_level},
        "by_source": dict(sorted(by_source.items())),
        "bucket_seconds": bucket_seconds,
        "buckets": [buckets[k] for k in sorted(buckets)],
        "window": {"since": since, "until": until, "level": level, "source": source},
    }


def source_status(
    conn: sqlite3.Connection,
    sources: dict[str, dict[str, Any]],
    *,
    root: str | Path = ".",
) -> list[dict[str, Any]]:
    """Per-source board: configured pattern, matched files, stored tail position.

    `behind_bytes` is size-minus-offset measured RIGHT NOW via Path.stat(), so
    "the collector is 40 MB behind" is visible without ingesting anything.
    """
    out: list[dict[str, Any]] = []
    for name in sorted(sources):
        cfg = sources[name]
        rows = []
        for fp in resolve_files(cfg, root=root):
            key = display_path(fp, root)
            off = get_offset(conn, name, key) or {}
            try:
                size = int(fp.stat().st_size)
            except OSError:
                size = None
            stored = int(off.get("offset", 0))
            rows.append(
                {
                    "path": key,
                    "size": size,
                    "offset": stored,
                    "behind_bytes": None if size is None else max(0, size - stored),
                    "lines": int(off.get("lines", 0)),
                    "ingested": int(off.get("ingested", 0)),
                    "rotations": int(off.get("rotations", 0)),
                    "encoding": off.get("encoding"),
                    "updated_ts": off.get("updated_ts"),
                }
            )
        out.append(
            {
                "source": name,
                "pattern": cfg["path"],
                "parser": cfg.get("parser", PARSER_PLAIN),
                "regex": cfg.get("regex"),
                "level": cfg.get("level"),
                "files": rows,
            }
        )
    return out


# ---- family schema ----------------------------------------------------------


def severity_for_level(level: str) -> str | None:
    """Log level -> openswap severity, or None when the level is not a finding.

    The single mapping both `to_diagnostics` and the `--fail-on` gates use, so
    "what counts as a failure" is defined once instead of drifting per command.
    """
    return _LEVEL_SEVERITY.get(level)


def to_diagnostics(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map error/critical/warning entries onto the family diagnostic schema.

    critical + error -> error, warning -> warning, everything quieter emits
    nothing. That is what lets `logs query --fail-on error` gate a cron run the
    same way `prose lint --fail-on` gates a publish.
    """
    diags = []
    for e in entries:
        severity = severity_for_level(e.get("level", ""))
        if severity is None:
            continue
        message = str(e.get("message", ""))
        diags.append(
            openswap.diagnostic(
                path=f"{e.get('source', '?')}:{e.get('path', '?')}",
                line=int(e.get("line_no", 0)),
                col=1,
                rule=f"logs:{e.get('level')}",
                severity=severity,
                message=message[:400],
                source=str(e.get("parser", "core")),
            )
        )
    return openswap.sort_diagnostics(diags)
