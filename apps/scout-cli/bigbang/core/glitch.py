# Solo personal project, no connection to employer, built with public/free-tier only
"""Glitch — GlitchTip-lite error-tracking core (openswap #8: Sentry).

Sentry's capture -> group -> store -> browse loop rebuilt on the stdlib with
the wire protocol deleted: everything this org runs (scout-cli, factory
daemons, the bluehenre API, the /app console) lives on one box, so events go
straight into sqlite and the hosted dashboard becomes a generated static HTML
page. Zero stack-trace egress — Sentry's DSN-and-envelope endpoint is the
paid enemy's architecture, so no wire tier exists even as a fallback.

Capture is three drop-ins, all import-only:
- Handler — a logging.Handler: `log.addHandler(glitch.Handler(db, project="x"))`
  captures ERROR+ records; grouping uses the UNFORMATTED record.msg template,
  so "step 12 failed" and "step 99 failed" are one issue, not N.
- install_excepthook(db, project=...) — wraps sys.excepthook and chains to the
  previous hook; KeyboardInterrupt passes through unrecorded (Ctrl+C is an
  operator action, not a defect) and a capture failure never masks the crash.
- parse_traceback_text(text) — parses the LAST complete traceback block out of
  arbitrary log text, so `scout glitch ingest crash.log` retro-instruments
  processes that were never touched.

Grouping (the Sentry fingerprint, stdlib edition): sha256 over the exception
type plus each frame's (normalized path tail, function). Line numbers and
messages are deliberately excluded — edits above the crash site and varying
interpolated values must not split an issue. Stack-less log events hash
(kind, logger, template) instead.

Everything here is deterministic and offline: `now`/`ts` are injectable and
the only I/O is sqlite3. The store keeps issues (fingerprint, first/last-seen,
count, status open/resolved/ignored — resolved reopens as a regression on the
next event, ignored stays ignored) plus per-event occurrences (message,
traceback text, JSON context).

Extension points:
- smtplib daily digest: openswap.summarize(to_diagnostics(list_issues(conn)))
  is the digest-body contract; an operator cron mails it via a localhost MTA —
  the core stays import-only and egress-free.
- Alert-router feed (severity rules): capture() returns {new, regressed} — a
  router that maps a new/regressed fatal|error issue to
  uptime.record_event(kind="alert") on the #2 ledger plugs Sentry-grade
  signals into the existing heartbeat/uptime alert path.
- Per-daemon retention: load_retention() overlays DEFAULT_RETENTION with JSON
  ({project: {max_age_s, keep_last}}; "*" is the default row; false exempts a
  project); prune() ages out occurrences while issue counters survive.
- Context enrichment: capture(..., context={...}) stores arbitrary JSON per
  occurrence (step number, checkpoint path, request id) surfaced by `show`.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import logging
import re
import sqlite3
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from bigbang.core import openswap

LEVEL_FATAL = "fatal"
LEVEL_ERROR = "error"
LEVEL_WARNING = "warning"
LEVEL_INFO = "info"
LEVEL_DEBUG = "debug"
LEVELS = (LEVEL_FATAL, LEVEL_ERROR, LEVEL_WARNING, LEVEL_INFO, LEVEL_DEBUG)
_LEVEL_RANK = {lv: i for i, lv in enumerate(LEVELS)}  # lower = more severe

STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"
STATUS_IGNORED = "ignored"
STATUSES = (STATUS_OPEN, STATUS_RESOLVED, STATUS_IGNORED)

DB_REL = Path(".scout") / "glitch.db"

# 30 days / 200 occurrences per issue — GlitchTip's free-tier retention shape,
# generous for a solo box. Counters survive pruning; only raw events age out.
DEFAULT_RETENTION: dict[str, Any] = {
    "*": {"max_age_s": 30 * 86400.0, "keep_last": 200},
}

_SEVERITY_OF = {
    LEVEL_FATAL: "error",
    LEVEL_ERROR: "error",
    LEVEL_WARNING: "warning",
    LEVEL_INFO: "info",
    LEVEL_DEBUG: "info",
}


def level_of(levelno: int) -> str:
    """Map a stdlib logging levelno onto the Sentry-style level scale."""
    if levelno >= logging.CRITICAL:
        return LEVEL_FATAL
    if levelno >= logging.ERROR:
        return LEVEL_ERROR
    if levelno >= logging.WARNING:
        return LEVEL_WARNING
    if levelno >= logging.INFO:
        return LEVEL_INFO
    return LEVEL_DEBUG


# ---- normalization + fingerprinting -----------------------------------------


def _norm_frame(filename: str, function: str) -> str:
    """Grouping key for one frame: last two path segments, /-joined, lowercased.

    Lowercased because Windows paths are case-preserving, not case-sensitive;
    two segments because basenames alone over-group (every package has an
    __init__.py). Line numbers stay out on purpose — see module doc.
    """
    parts = re.split(r"[\\/]+", filename)
    tail = "/".join(p for p in parts[-2:] if p)
    return f"{tail.lower()}:{function}"


def fingerprint_of(event: dict[str, Any]) -> str:
    """sha256 issue-grouping key (full hex — stable for scripts/allowlists)."""
    h = hashlib.sha256()
    h.update(str(event.get("kind", "?")).encode("utf-8"))
    frames = event.get("frames") or []
    if frames:
        for f in frames:
            key = _norm_frame(str(f.get("file", "?")), str(f.get("function", "?")))
            h.update(b"\0" + key.encode("utf-8"))
    elif event.get("template") is not None:
        h.update(b"\0" + str(event.get("logger") or "").encode("utf-8"))
        h.update(b"\0" + str(event["template"]).encode("utf-8"))
    else:
        # no stack and no template: the message is all there is to group on
        h.update(b"\0" + str(event.get("message", "")).encode("utf-8"))
    return h.hexdigest()


def _finish(event: dict[str, Any]) -> dict[str, Any]:
    frames = event.get("frames") or []
    if frames:
        crash = frames[-1]  # innermost frame is the crash site
        event["culprit"] = f"{crash['file']}:{crash['function']}"
        event["file"] = crash["file"]
        event["line"] = int(crash["line"] or 0)
    event["fingerprint"] = fingerprint_of(event)
    return event


def normalize_exception(
    exc: BaseException, *, level: str = LEVEL_ERROR
) -> dict[str, Any]:
    """One live exception -> the normalized capture schema (see module doc)."""
    te = traceback.TracebackException.from_exception(exc)
    frames = [
        {
            "file": fs.filename,
            "line": fs.lineno or 0,
            "function": fs.name,
            "code": fs.line,
        }
        for fs in te.stack
    ]
    kind = type(exc).__name__
    module = type(exc).__module__
    if module not in ("builtins", "__main__"):
        kind = f"{module}.{kind}"
    return _finish(
        {
            "kind": kind,
            "message": str(exc),
            "level": level if level in _LEVEL_RANK else LEVEL_ERROR,
            "logger": None,
            "frames": frames,
            "traceback": "".join(te.format()),
            "culprit": None,
            "file": None,
            "line": 0,
            "template": None,
        }
    )


def log_event(
    message: str,
    *,
    level: str = LEVEL_ERROR,
    logger: str | None = None,
    template: str | None = None,
) -> dict[str, Any]:
    """Build a message-only capture event (`scout glitch log`, shell cron)."""
    if level not in _LEVEL_RANK:
        level = LEVEL_ERROR
    return _finish(
        {
            "kind": f"log.{level}",
            "message": message,
            "level": level,
            "logger": logger,
            "frames": [],
            "traceback": None,
            "culprit": logger,
            "file": None,
            "line": 0,
            "template": template or message,
        }
    )


def normalize_log_record(record: logging.LogRecord) -> dict[str, Any]:
    """One logging.LogRecord -> the capture schema.

    exc_info wins when present (frame grouping); otherwise the UNFORMATTED
    record.msg template is the grouping key, so interpolated values never
    shard an issue into per-message fragments.
    """
    exc = record.exc_info[1] if record.exc_info else None
    if exc is not None:
        event = normalize_exception(exc, level=level_of(record.levelno))
        event["logger"] = record.name  # frames drive the fingerprint, unchanged
        return event
    lv = level_of(record.levelno)
    return _finish(
        {
            "kind": f"log.{lv}",
            "message": record.getMessage(),
            "level": lv,
            "logger": record.name,
            "frames": [],
            "traceback": None,
            "culprit": f"{record.name}:{record.funcName}",
            "file": record.pathname,
            "line": record.lineno,
            "template": str(record.msg),
        }
    )


# ---- crash-log ingestion ----------------------------------------------------

_TB_HEADER = "Traceback (most recent call last):"
_FILE_RE = re.compile(
    r'^\s+File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+)$'
)
_EXC_RE = re.compile(
    r"^(?P<kind>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
    r"(?::\s?(?P<msg>.*))?$"
)


def parse_traceback_text(text: str) -> dict[str, Any] | None:
    """Parse the LAST complete traceback block out of arbitrary log text.

    The last block is the fatal one in a crash tail; with chained exceptions
    ("During handling...") it is the outermost — what Sentry displays. A block
    needs at least one frame and a terminating exception line, so stray
    "Traceback" prose and truncated tails return None instead of junk issues.
    Multi-line exception messages keep only their first line.
    """
    lines = text.splitlines()
    headers = [i for i, ln in enumerate(lines) if ln.strip() == _TB_HEADER]
    for start in reversed(headers):
        frames: list[dict[str, Any]] = []
        raw = [lines[start].strip()]
        exc_match = None
        i = start + 1
        while i < len(lines):
            ln = lines[i]
            m = _FILE_RE.match(ln)
            if m:
                frames.append(
                    {
                        "file": m["file"],
                        "line": int(m["line"]),
                        "function": m["func"].strip(),
                        "code": None,
                    }
                )
                raw.append(ln)
            elif ln[:1].isspace() and ln.strip():
                # source echo, ^^^ / ~~~ markers, "[Previous line repeated...]"
                if frames and frames[-1]["code"] is None and not ln.strip().startswith(
                    ("^", "~", "[")
                ):
                    frames[-1]["code"] = ln.strip()
                raw.append(ln)
            elif not ln.strip():
                break  # traceback blocks are contiguous; blank = truncated tail
            else:
                exc_match = _EXC_RE.match(ln.strip())
                if exc_match:
                    raw.append(ln.strip())
                break
            i += 1
        if exc_match is None or not frames:
            continue  # incomplete block — try the previous one
        return _finish(
            {
                "kind": exc_match["kind"],
                "message": (exc_match["msg"] or "").strip(),
                "level": LEVEL_ERROR,
                "logger": None,
                "frames": frames,
                "traceback": "\n".join(raw),
                "culprit": None,
                "file": None,
                "line": 0,
                "template": None,
            }
        )
    return None


# ---- the issue store --------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS issues(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    culprit TEXT,
    file TEXT,
    line INTEGER NOT NULL DEFAULT 0,
    level TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    count INTEGER NOT NULL,
    UNIQUE(project, fingerprint)
);
CREATE TABLE IF NOT EXISTS occurrences(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    message TEXT NOT NULL,
    traceback TEXT,
    context TEXT
);
CREATE INDEX IF NOT EXISTS idx_occ_issue_ts ON occurrences(issue_id, ts);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the issue store.

    Its own file, NOT the #2 uptime ledger: error volume is bursty (a crash
    loop writes hundreds of rows a minute) and must never contend with uptime
    probes for the same sqlite write lock.
    """
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', '1')"
    )
    conn.commit()
    return conn


def capture(
    conn: sqlite3.Connection,
    event: dict[str, Any],
    *,
    project: str = "default",
    ts: float | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Upsert the issue for this event's fingerprint and append an occurrence.

    Returns {issue_id, fingerprint, count, status, new, regressed}. A resolved
    issue seeing a fresh event reopens (regressed=True) — the Sentry regression
    contract; an ignored issue stays ignored (that is the escape hatch's whole
    point) but still counts occurrences so un-ignoring shows true volume.
    first/last_seen use MIN/MAX so ingesting old logs never rewrites history.
    """
    ts = time.time() if ts is None else float(ts)
    fp = event.get("fingerprint") or fingerprint_of(event)
    level = event.get("level", LEVEL_ERROR)
    if level not in _LEVEL_RANK:
        level = LEVEL_ERROR
    row = conn.execute(
        "SELECT * FROM issues WHERE project = ? AND fingerprint = ?", (project, fp)
    ).fetchone()
    new = row is None
    regressed = False
    if new:
        cur = conn.execute(
            "INSERT INTO issues(project, fingerprint, kind, message, culprit,"
            " file, line, level, status, first_seen, last_seen, count)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (
                project,
                fp,
                event.get("kind", "?"),
                event.get("message", ""),
                event.get("culprit"),
                event.get("file"),
                int(event.get("line") or 0),
                level,
                STATUS_OPEN,
                ts,
                ts,
            ),
        )
        issue_id, count, status = int(cur.lastrowid), 1, STATUS_OPEN
    else:
        issue_id, count = int(row["id"]), int(row["count"]) + 1
        status = row["status"]
        if status == STATUS_RESOLVED:
            status, regressed = STATUS_OPEN, True
        prev = row["level"] if row["level"] in _LEVEL_RANK else LEVEL_ERROR
        worst = level if _LEVEL_RANK[level] < _LEVEL_RANK[prev] else prev
        conn.execute(
            "UPDATE issues SET message = ?, culprit = ?, file = ?, line = ?,"
            " level = ?, status = ?, first_seen = MIN(first_seen, ?),"
            " last_seen = MAX(last_seen, ?), count = ? WHERE id = ?",
            (
                event.get("message", ""),
                event.get("culprit") or row["culprit"],
                event.get("file") or row["file"],
                int(event.get("line") or 0) or int(row["line"]),
                worst,
                status,
                ts,
                ts,
                count,
                issue_id,
            ),
        )
    conn.execute(
        "INSERT INTO occurrences(issue_id, ts, message, traceback, context)"
        " VALUES(?, ?, ?, ?, ?)",
        (
            issue_id,
            ts,
            event.get("message", ""),
            event.get("traceback"),
            json.dumps(context) if context else None,
        ),
    )
    conn.commit()
    return {
        "issue_id": issue_id,
        "fingerprint": fp,
        "count": count,
        "status": status,
        "new": new,
        "regressed": regressed,
    }


def get_issue(conn: sqlite3.Connection, issue_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    return dict(row) if row else None


def list_issues(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
    status: str | None = None,
    level: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Newest-activity-first issue rows; None filters mean \"all\"."""
    rows = conn.execute(
        "SELECT * FROM issues WHERE (? IS NULL OR project = ?)"
        " AND (? IS NULL OR status = ?) AND (? IS NULL OR level = ?)"
        " ORDER BY last_seen DESC, id DESC LIMIT ?",
        (project, project, status, status, level, level, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def occurrences_of(
    conn: sqlite3.Connection, issue_id: int, *, limit: int = 10
) -> list[dict[str, Any]]:
    """Newest-first occurrences with context JSON decoded."""
    rows = conn.execute(
        "SELECT * FROM occurrences WHERE issue_id = ? ORDER BY ts DESC, id DESC"
        " LIMIT ?",
        (issue_id, limit),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("context"):
            try:
                d["context"] = json.loads(d["context"])
            except ValueError:
                pass  # pre-schema junk stays visible as the raw string
        out.append(d)
    return out


def set_status(
    conn: sqlite3.Connection, issue_id: int, status: str
) -> dict[str, Any] | None:
    """Triage verdict; raises ValueError on a bad status, None on no such issue."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    cur = conn.execute(
        "UPDATE issues SET status = ? WHERE id = ?", (status, issue_id)
    )
    conn.commit()
    return get_issue(conn, issue_id) if cur.rowcount else None


# ---- retention (policy-as-config) -------------------------------------------


def load_retention(path: str | None = None) -> dict[str, Any]:
    """DEFAULT_RETENTION overlaid with an optional JSON file.

    Shape: {project: {max_age_s, keep_last}}; "*" is the default row applied
    to projects without their own; false (or {"enabled": false}) exempts a
    project from pruning entirely. Raises ValueError / OSError / json errors
    for the CLI to convert into a fail_agent envelope.
    """
    retention = copy.deepcopy(DEFAULT_RETENTION)
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("retention file must be a JSON object of {project: cfg}")
        for name, cfg in raw.items():
            if cfg is False or (isinstance(cfg, dict) and cfg.get("enabled") is False):
                retention[name] = False
                continue
            if not isinstance(cfg, dict):
                raise ValueError(f"project {name!r}: config must be an object or false")
            base = retention.get(name)
            merged = dict(base) if isinstance(base, dict) else {}
            merged.update(cfg)
            retention[name] = merged
    for name, cfg in retention.items():
        if cfg is False:
            continue
        v = cfg.get("max_age_s")
        if v is not None and (
            isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0
        ):
            raise ValueError(f"project {name!r}: max_age_s must be positive seconds")
        k = cfg.get("keep_last")
        if k is not None and (isinstance(k, bool) or not isinstance(k, int) or k < 0):
            raise ValueError(f"project {name!r}: keep_last must be a non-negative int")
    return retention


def prune(
    conn: sqlite3.Connection, retention: dict[str, Any], *, now: float | None = None
) -> dict[str, Any]:
    """Apply per-project retention. Issue counters ALWAYS survive.

    Occurrences past max_age_s or beyond keep_last (newest kept) are deleted;
    whole issues are dropped only when resolved/ignored AND aged past
    max_age_s — an open issue is still a bug no matter how old.
    """
    now = time.time() if now is None else float(now)
    occ_deleted = 0
    issues_deleted = 0
    projects = [
        r["project"] for r in conn.execute("SELECT DISTINCT project FROM issues")
    ]
    for project in projects:
        cfg = retention.get(project, retention.get("*"))
        if not isinstance(cfg, dict):
            continue  # false / missing everywhere = exempt
        max_age = cfg.get("max_age_s")
        keep_last = cfg.get("keep_last")
        issue_ids = [
            r["id"]
            for r in conn.execute("SELECT id FROM issues WHERE project = ?", (project,))
        ]
        for iid in issue_ids:
            if max_age is not None:
                cur = conn.execute(
                    "DELETE FROM occurrences WHERE issue_id = ? AND ts < ?",
                    (iid, now - float(max_age)),
                )
                occ_deleted += cur.rowcount
            if keep_last is not None:
                cur = conn.execute(
                    "DELETE FROM occurrences WHERE issue_id = ? AND id NOT IN ("
                    "SELECT id FROM occurrences WHERE issue_id = ?"
                    " ORDER BY ts DESC, id DESC LIMIT ?)",
                    (iid, iid, int(keep_last)),
                )
                occ_deleted += cur.rowcount
        if max_age is not None:
            cur = conn.execute(
                "DELETE FROM issues WHERE project = ? AND status != ?"
                " AND last_seen < ?",
                (project, STATUS_OPEN, now - float(max_age)),
            )
            issues_deleted += cur.rowcount
    cur = conn.execute(
        "DELETE FROM occurrences WHERE issue_id NOT IN (SELECT id FROM issues)"
    )
    occ_deleted += cur.rowcount
    conn.commit()
    return {"occurrences_deleted": occ_deleted, "issues_deleted": issues_deleted}


# ---- capture plumbing (the drop-ins) ----------------------------------------


class Handler(logging.Handler):
    """Drop-in capture: `logger.addHandler(glitch.Handler(db, project="x"))`.

    Opens a short-lived sqlite connection per emit — error volume is low and
    this keeps the handler thread-safe without pinning a write lock for the
    host process's lifetime. emit() never raises (handleError semantics):
    telemetry must never take the daemon down with it.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        project: str = "default",
        level: int = logging.ERROR,
    ):
        super().__init__(level=level)
        self.db_path = str(db_path)
        self.project = project

    def emit(self, record: logging.LogRecord) -> None:
        try:
            event = normalize_log_record(record)
            conn = open_store(self.db_path)
            try:
                capture(
                    conn,
                    event,
                    project=self.project,
                    context={"logger": record.name},
                )
            finally:
                conn.close()
        except Exception:
            self.handleError(record)


def install_excepthook(db_path: str | Path, *, project: str = "default"):
    """Record uncaught exceptions, then chain to the PREVIOUS hook.

    The crash still prints — capture is a tap, not a swallow. KeyboardInterrupt
    passes through unrecorded (operator action, not a defect), and any capture
    failure is dropped so telemetry never masks the real crash. The previous
    hook is kept on the returned function: `sys.excepthook = hook.previous`
    uninstalls.
    """
    previous = sys.excepthook

    def hook(exc_type, exc, tb):
        if not issubclass(exc_type, KeyboardInterrupt):
            try:
                if exc.__traceback__ is None and tb is not None:
                    exc = exc.with_traceback(tb)
                conn = open_store(db_path)
                try:
                    capture(conn, normalize_exception(exc), project=project)
                finally:
                    conn.close()
            except Exception:
                pass
        previous(exc_type, exc, tb)

    hook.previous = previous
    sys.excepthook = hook
    return hook


def install(
    db_path: str | Path,
    *,
    project: str = "default",
    logger: str | None = None,
    level: int = logging.ERROR,
) -> dict[str, Any]:
    """One-line instrumentation: logging Handler + excepthook together."""
    handler = Handler(db_path, project=project, level=level)
    logging.getLogger(logger).addHandler(handler)
    hook = install_excepthook(db_path, project=project)
    return {
        "handler": handler,
        "excepthook": hook,
        "db": str(db_path),
        "project": project,
    }


# ---- family schema + the static browser -------------------------------------


def to_diagnostics(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map OPEN issues onto the family diagnostic schema.

    fatal/error=error, warning=warning, info/debug=info; resolved/ignored emit
    nothing, so `issues --fail-on` gates only on live problems — exactly like
    ok daemons in heartbeat and clean files in prose.
    """
    diags = []
    for i in issues:
        if i.get("status") != STATUS_OPEN:
            continue
        diags.append(
            openswap.diagnostic(
                path=i.get("file") or f"glitch:{i.get('project', '?')}",
                line=int(i.get("line") or 0),
                rule=f"glitch:{i.get('kind', '?')}",
                severity=_SEVERITY_OF.get(i.get("level"), "warning"),
                message=(
                    f"[{i.get('project')}] {i.get('kind')}: {i.get('message')}"
                    f" (seen {i.get('count')}x)"
                ),
            )
        )
    return openswap.sort_diagnostics(diags)


def _iso(ts: float | None) -> str:
    if ts is None:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(float(ts)))


def render_html(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
    limit: int = 200,
    title: str = "Glitch — local issue browser",
) -> str:
    """The hosted dashboard, deleted: one static self-contained HTML page.

    Every dynamic string goes through html.escape (tracebacks and messages are
    attacker-adjacent text); drill-down is native <details> — zero JavaScript,
    zero external assets, so the page works offline from file://.
    """
    e = html.escape
    issues = list_issues(conn, project=project, status=None, limit=limit)
    issues.sort(
        key=lambda i: (
            0 if i["status"] == STATUS_OPEN else 1,
            _LEVEL_RANK.get(i["level"], 99),
            -(i["last_seen"] or 0),
        )
    )
    open_n = sum(1 for i in issues if i["status"] == STATUS_OPEN)
    rows = []
    for i in issues:
        occ = occurrences_of(conn, i["id"], limit=1)
        tb = occ[0]["traceback"] if occ and occ[0].get("traceback") else None
        ctx = occ[0].get("context") if occ else None
        detail = ""
        if tb:
            detail += f"<pre>{e(tb)}</pre>"
        if ctx:
            detail += f"<pre>context: {e(json.dumps(ctx, default=str))}</pre>"
        rows.append(
            f'<tr class="st-{e(i["status"])}">'
            f'<td>#{i["id"]}</td>'
            f'<td><span class="lv lv-{e(i["level"])}">{e(i["level"])}</span></td>'
            f'<td><details><summary><b>{e(i["kind"])}</b> — {e(i["message"])}'
            f"</summary>"
            f'<p class="mono">{e(i["culprit"] or "?")} · fp {e(i["fingerprint"][:12])}'
            f"</p>{detail}</details></td>"
            f'<td>{i["count"]}</td>'
            f'<td class="mono">{e(_iso(i["first_seen"]))}</td>'
            f'<td class="mono">{e(_iso(i["last_seen"]))}</td>'
            f'<td>{e(i["project"])}</td>'
            f'<td>{e(i["status"])}</td></tr>'
        )
    body = "\n".join(rows) or '<tr><td colspan="8">no issues recorded</td></tr>'
    scope = f" · project {e(project)}" if project else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 1.5rem; color: #1c2430; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #d8dee6;
  vertical-align: top; }}
.mono {{ font-family: ui-monospace, monospace; font-size: .85em; color: #55606e; }}
pre {{ background: #f4f6f8; padding: .6rem; overflow-x: auto; font-size: .8em; }}
.lv {{ padding: .1rem .45rem; border-radius: .6rem; font-size: .8em; color: #fff; }}
.lv-fatal, .lv-error {{ background: #b3261e; }}
.lv-warning {{ background: #a86500; }}
.lv-info, .lv-debug {{ background: #4a5b70; }}
.st-resolved td, .st-ignored td {{ opacity: .55; }}
summary {{ cursor: pointer; }}
</style></head>
<body>
<h1>{e(title)}</h1>
<p>{open_n} open / {len(issues)} shown{scope} · generated {e(_iso(time.time()))}
 · fully local — nothing on this page ever left the box</p>
<table>
<tr><th>id</th><th>level</th><th>issue</th><th>count</th><th>first seen</th>
<th>last seen</th><th>project</th><th>status</th></tr>
{body}
</table>
</body></html>
"""
