# Solo personal project, no connection to employer, built with public/free-tier only
"""Digest — templated digest mailer over the ledgers this box already has (openswap #32).

Mailchimp sells five things. Four of them are already on this box and the fifth
is the one you should not want:

  1 an audience list        -> a JSON roster in config, on your disk
  2 campaign templating     -> merge-tag substitution over a text+HTML template
  3 sending infrastructure  -> smtplib against ONE relay you already run
  4 scheduling              -> cron, plus a send ledger so a run never repeats
  5 open/click analytics    -> DELETED, and deleting it is the product

(5) is worth being explicit about. Mailchimp's open tracking is a 1x1 remote
image and its click tracking is every link rewritten through their domain, so
"marketing analytics" is implemented as your readers' mail clients phoning a
third party each time they read you. This module renders mail that loads
NOTHING remote and rewrites no link, and `tracking_findings()` proves it by
parsing the rendered HTML back and reporting any auto-loading remote resource as
`digest:tracking-beacon` — an error. The check runs on a custom template too, so
pasting a vendor's pixel into one fails the gate instead of shipping.

Everything here is deterministic and offline. The ONE real egress in the whole
adapter is `smtplib.SMTP` in the plugin CLI, injected into `deliver()` as
`send_fn` exactly like alerts (#19) injects `dispatch`, so the assembly,
templating, refusal and dedupe logic is provable with no socket in sight.

THE REFUSALS ARE THE FEATURE. A mailer's worst failure is not a crash, it is
mailing the wrong people or mailing nobody and looking healthy:
- Ships with `mail.from = null` and an EMPTY roster. `deliver()` raises
  DigestError("digest:no-sender") / ("digest:no-recipients") rather than
  inventing an address. There is no "scout@localhost" default anywhere in this
  file; a From header this box did not configure is a forged From header.
- `--dry-run` is the DEFAULT and it is a real rehearsal, not a different code
  path: the same refusals fire, the same MIME message is built byte-for-byte,
  and only the smtplib call and the ledger write are skipped. A dry run
  therefore cannot consume a campaign and silence the real send behind it.
- Only status "sent" starts the never-repeat clock (SENT_STATUSES). A failed
  relay must retry on the next pass, so a failure is recorded and does NOT
  suppress; this is the alerts DEDUP_STATUSES rule restated for mail.
- An empty digest is refused ("digest:empty") unless `send_when_empty` is set:
  a weekly mail that says nothing trains the reader to ignore the next one.
- Each recipient gets their OWN message with To: set to exactly them. No shared
  To:, no BCC games — nobody on the roster learns anyone else is on it.

Sections are declarative reads over the ledgers other adapters already write —
uptime #2 `incidents`, logs #14 `entries`, glitch #8 `issues`, feeds #12
`entries`. The db paths are taken from those modules' own DB_REL constants and
the logs level threshold from `logs.LEVELS`, so a store that moves or a level
that is renamed cannot leave this module quietly reading nothing (the dupes #28
"DOC_EXTS IS prose.PROSE_EXTS" rule). Nothing here writes those ledgers; the
only write is this adapter's own `sends` table in its own sqlite file.

Table and column names cannot be parameterized in SQL, so identifiers are
gated twice: `_IDENT_RE` before anything is built, then existence in
`sqlite_master` / `pragma_table_info(?)` (both parameterized) before the SELECT
is assembled. Every caller VALUE travels as a `?`. A section pointed at
`entries; DROP TABLE` is refused at load time by name.

Reading honesty, per the family rule that a reading has EITHER a value OR a
labelled reason: a section whose ledger is missing, whose table is gone or whose
declared column disappeared reports `count: null` + `error: <why>`, never an
innocent zero. Rows whose timestamp column is NULL can appear in no window at
all, so they are counted and surfaced as `digest:undated-rows` instead of being
dropped in silence.

Ties are ordered `ts DESC, rowid DESC`: two rows written in the same second must
not swap places between runs, or the campaign fingerprint moves and the
never-repeat guard stops working. `campaign_id()` hashes the period bounds and
the item content and NOT `generated_ts`, which is what makes "the same digest"
identifiable across runs.

Two adjacent surfaces this does NOT duplicate, named because the names collide:
`scout feeds digest` (#12) ranks and text-renders ONE feed's entries and mails
nothing — this module consumes its `entries` table as a section instead of
reimplementing it. And `later` (#34) strips tracking QUERY PARAMS from a URL it
is saving (inbound, reader side); `tracking_findings()` here audits rendered mail
for auto-loading REMOTE RESOURCES (outbound, sender side). Different direction,
different mechanism, no shared code. Canonicalising a feed item's link is the
INGEST layer's job, not the mailer's: rewriting the reader's links is precisely
the behaviour this adapter exists to delete.

Deliberately out of scope, stated rather than implied: subscribe/unsubscribe
web forms (they need a public HTTP endpoint, which is the egress this deletes —
the roster is edited in config), A/B subject testing (needs open rates, which
needs the beacon), deliverability warmup and DKIM signing (a property of the
relay and its DNS, not of this file), and embedded charts (charts #16 renders
SVG, which mail clients treat as an attachment or drop entirely; a link to the
generated file is honest, a broken image is not).
"""

from __future__ import annotations

import copy
import hashlib
import html as html_mod
import json
import re
import sqlite3
import time
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, parseaddr
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from bigbang.core import feeds, glitch, logs, openswap, uptime

# This adapter's OWN sqlite file: the send ledger. Never one of the ledgers it
# reads — a digest run must not hold a write lock on the monitoring ledger.
DB_REL = Path(".scout") / "digest.db"
SCHEMA_VERSION = "1"

# ---- named refusals ---------------------------------------------------------
# Every refusal has a stable id so a caller can branch on it and a human can
# grep for it. "Refuse with a named error" beats "return an empty result".

ERR_NO_SENDER = "digest:no-sender"
ERR_NO_RECIPIENTS = "digest:no-recipients"
ERR_NO_RELAY = "digest:no-relay"
ERR_BAD_ADDRESS = "digest:bad-address"
ERR_BAD_CONFIG = "digest:bad-config"
ERR_BAD_IDENTIFIER = "digest:bad-identifier"
ERR_HEADER_INJECTION = "digest:header-injection"
ERR_EMPTY = "digest:empty"
ERR_UNRESOLVED_TAG = "digest:unresolved-tag"
ERR_TRACKING = "digest:tracking-beacon"
ERR_SOURCE_UNREADABLE = "digest:source-unreadable"
ERR_SCHEMA_DRIFT = "digest:schema-drift"
ERR_UNDATED = "digest:undated-rows"
ERR_UNDELIVERABLE = "digest:undeliverable"
ERR_UNSUBSCRIBED = "digest:unsubscribed"


class DigestError(ValueError):
    """A refusal with a stable name. `rule` is the id above, `args[1]` the why."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(rule, message)
        self.rule = rule
        self.message = message

    def __str__(self) -> str:  # pragma: no cover - trivial formatting
        return f"{self.rule}: {self.message}"


# ---- recipients -------------------------------------------------------------

STATE_SUBSCRIBED = "subscribed"
STATE_UNSUBSCRIBED = "unsubscribed"
STATE_BOUNCED = "bounced"
RECIPIENT_STATES = (STATE_SUBSCRIBED, STATE_UNSUBSCRIBED, STATE_BOUNCED)

# Conservative addr-spec: no whitespace, no comma, no angle brackets, no quoting
# and no group syntax. parseaddr() is NOT a validator (it happily returns
# 'a b@c' unchanged and silently truncates 'a@b,c@d' to 'a@b' — which would mail
# a stranger), so it is used only to reject anything it rewrites, and this regex
# is the actual gate.
_ADDR_RE = re.compile(r"^[^\s@,<>\"();:\\]+@[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?$")
_MAX_ADDR = 254  # RFC 5321 forward-path limit
_MAX_LOCAL = 64  # RFC 5321 local-part limit


def valid_address(value: object) -> bool:
    """True only for a bare, unambiguous addr-spec (no display name, no list)."""
    if not isinstance(value, str) or not value or len(value) > _MAX_ADDR:
        return False
    if any(c in value for c in "\r\n\t\0"):
        return False
    if parseaddr(value)[1] != value:
        return False
    if not _ADDR_RE.match(value):
        return False
    local, _, domain = value.rpartition("@")
    return len(local) <= _MAX_LOCAL and ".." not in domain


def normalize_recipient(raw: Any) -> dict[str, Any]:
    """One roster entry -> {email, name, state}. Raises DigestError on nonsense.

    A malformed roster line is a config bug that must surface at load time: the
    alternative is discovering it mid-campaign, after some of the list was
    already mailed.
    """
    if isinstance(raw, str):
        raw = {"email": raw}
    if not isinstance(raw, dict):
        raise DigestError(ERR_BAD_CONFIG, f"recipient must be a string or object, got {raw!r}")
    email = raw.get("email")
    state = str(raw.get("state") or STATE_SUBSCRIBED)
    if state not in RECIPIENT_STATES:
        raise DigestError(
            ERR_BAD_CONFIG,
            f"recipient {email!r}: state must be one of {'|'.join(RECIPIENT_STATES)}, got {state!r}",
        )
    name = raw.get("name")
    return {
        "email": email if isinstance(email, str) else "",
        "name": str(name) if isinstance(name, str) and name.strip() else "",
        "state": state,
    }


def deliverable(recipients: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """(mailable, skipped) — every exclusion carries a LABELLED reason.

    Order is preserved so the send plan is reproducible, and duplicates of the
    same address collapse to the first entry (a roster pasted twice must not
    mail the same person twice).
    """
    mailable: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    for r in recipients:
        entry = normalize_recipient(r)
        email = entry["email"]
        if not valid_address(email):
            skipped.append({**entry, "reason": ERR_BAD_ADDRESS, "detail": f"not a mailable address: {email!r}"})
            continue
        key = email.lower()
        if key in seen:
            skipped.append({**entry, "reason": ERR_BAD_ADDRESS, "detail": "duplicate address in roster"})
            continue
        seen.add(key)
        if entry["state"] != STATE_SUBSCRIBED:
            skipped.append({**entry, "reason": ERR_UNSUBSCRIBED, "detail": f"state is {entry['state']}"})
            continue
        mailable.append(entry)
    return mailable, skipped


# ---- config -----------------------------------------------------------------

# NO sender, NO relay, NO recipients. This emptiness is load-bearing: see the
# module docstring on forged From headers.
DEFAULT_MAIL: dict[str, Any] = {
    "from": None,
    "from_name": "",
    "host": None,
    "port": 25,
    "starttls": False,
    "user": None,
    "password_env": None,
    "timeout_s": 20.0,
}

DEFAULT_DIGEST: dict[str, Any] = {
    "title": "Digest",
    "subject": "{{title}} — {{period}}",
    "window_days": 7.0,
    "body_chars": 240,
    "section_limit": 20,
    "send_when_empty": False,
}

# Threshold read from logs' own ladder, not written as 1: renaming a level or
# reordering LEVELS must not silently change which lines the digest reports.
_ERROR_RANK = logs.LEVELS.index(logs.LEVEL_ERROR)

DEFAULT_SECTIONS: dict[str, dict[str, Any]] = {
    "incidents": {
        "order": 10,
        "title": "Incidents",
        "db": uptime.DB_REL.as_posix(),
        "table": "incidents",
        "cols": {"ts": "opened_ts", "title": "target", "tag": "state"},
        "enabled": True,
    },
    "errors": {
        "order": 20,
        "title": "Errors in the logs",
        "db": logs.DB_REL.as_posix(),
        "table": "entries",
        "cols": {"ts": "ts", "title": "message", "tag": "level", "body": "path"},
        "filter": {"col": "level_rank", "op": "<=", "value": _ERROR_RANK},
        "enabled": True,
    },
    "issues": {
        "order": 30,
        "title": "Open issues",
        "db": glitch.DB_REL.as_posix(),
        "table": "issues",
        "cols": {"ts": "last_seen", "title": "message", "tag": "level", "body": "culprit"},
        "filter": {"col": "status", "op": "=", "value": glitch.STATUS_OPEN},
        "enabled": True,
    },
    "reading": {
        "order": 40,
        "title": "Reading",
        "db": feeds.DB_REL.as_posix(),
        "table": "entries",
        "cols": {
            "ts": "first_seen_ts",
            "title": "title",
            "body": "summary",
            "link": "link",
            "tag": "feed",
        },
        "enabled": True,
    },
}

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ROLES = ("ts", "title", "body", "link", "tag")
REQUIRED_ROLES = ("ts", "title")
# op -> (sql fragment, takes a value). Fixed set: no caller string ever becomes
# SQL, so there is no injection surface in the filter either.
FILTER_OPS: dict[str, tuple[str, bool]] = {
    "=": ("= ?", True),
    "!=": ("!= ?", True),
    "<": ("< ?", True),
    "<=": ("<= ?", True),
    ">": ("> ?", True),
    ">=": (">= ?", True),
    "isnull": ("IS NULL", False),
    "notnull": ("IS NOT NULL", False),
}


def _ident(value: Any, *, what: str) -> str:
    """A bare SQL identifier or a refusal. The first of two injection gates."""
    if not isinstance(value, str) or not _IDENT_RE.match(value):
        raise DigestError(ERR_BAD_IDENTIFIER, f"{what} must be a plain identifier, got {value!r}")
    return value


def validate_section(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Check one section spec hard enough that `read_section` can trust it."""
    if not isinstance(spec, dict):
        raise DigestError(ERR_BAD_CONFIG, f"section {name!r}: config must be an object or false")
    out = dict(spec)
    db = out.get("db")
    if not isinstance(db, str) or not db.strip():
        raise DigestError(ERR_BAD_CONFIG, f"section {name!r}: needs a `db` path")
    out["table"] = _ident(out.get("table"), what=f"section {name!r} table")
    cols = out.get("cols")
    if not isinstance(cols, dict):
        raise DigestError(ERR_BAD_CONFIG, f"section {name!r}: `cols` must be an object of role->column")
    unknown = sorted(set(cols) - set(ROLES))
    if unknown:
        raise DigestError(
            ERR_BAD_CONFIG, f"section {name!r}: unknown col role(s) {unknown} (roles: {list(ROLES)})"
        )
    for role in REQUIRED_ROLES:
        if not cols.get(role):
            raise DigestError(ERR_BAD_CONFIG, f"section {name!r}: cols.{role} is required")
    out["cols"] = {r: _ident(c, what=f"section {name!r} cols.{r}") for r, c in cols.items() if c}
    flt = out.get("filter")
    if flt is not None:
        if not isinstance(flt, dict):
            raise DigestError(ERR_BAD_CONFIG, f"section {name!r}: `filter` must be an object")
        op = flt.get("op")
        if op not in FILTER_OPS:
            raise DigestError(
                ERR_BAD_CONFIG,
                f"section {name!r}: filter op must be one of {sorted(FILTER_OPS)}, got {op!r}",
            )
        out["filter"] = {
            "col": _ident(flt.get("col"), what=f"section {name!r} filter.col"),
            "op": op,
            "value": flt.get("value"),
        }
    out["order"] = int(out.get("order", 100))
    out["title"] = str(out.get("title") or name)
    out["enabled"] = bool(out.get("enabled", True))
    return out


def load_config(path: str | None = None) -> dict[str, Any]:
    """Defaults overlaid with an optional JSON file. Raises for the CLI to wrap.

    Merge semantics mirror uptime.load_targets/prose.load_rules: dicts merge
    key-by-key and a bare `false` drops a section. `recipients` is the one
    exception — it is a LIST and replaces wholesale, because merging two lists
    of people by position is how someone gets mailed by accident.
    """
    cfg: dict[str, Any] = {
        "mail": copy.deepcopy(DEFAULT_MAIL),
        "digest": copy.deepcopy(DEFAULT_DIGEST),
        "sections": copy.deepcopy(DEFAULT_SECTIONS),
        "recipients": [],
    }
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise DigestError(ERR_BAD_CONFIG, "config file must be a JSON object")
        for key in ("mail", "digest"):
            block = raw.get(key)
            if block is not None:
                if not isinstance(block, dict):
                    raise DigestError(ERR_BAD_CONFIG, f"`{key}` must be an object")
                cfg[key].update(block)
        if "recipients" in raw:
            if not isinstance(raw["recipients"], list):
                raise DigestError(ERR_BAD_CONFIG, "`recipients` must be a list")
            cfg["recipients"] = list(raw["recipients"])
        for name, spec in (raw.get("sections") or {}).items():
            if spec is False or (isinstance(spec, dict) and spec.get("enabled") is False):
                cfg["sections"].pop(name, None)
                continue
            merged = {**cfg["sections"].get(name, {}), **(spec if isinstance(spec, dict) else {})}
            cfg["sections"][name] = merged if isinstance(spec, dict) else spec
    cfg["sections"] = {n: validate_section(n, s) for n, s in cfg["sections"].items()}
    cfg["recipients"] = [normalize_recipient(r) for r in cfg["recipients"]]
    _validate_mail(cfg["mail"])
    dg = cfg["digest"]
    for key in ("window_days", "body_chars", "section_limit"):
        if float(dg.get(key) or 0) <= 0:
            raise DigestError(ERR_BAD_CONFIG, f"digest.{key} must be > 0, got {dg.get(key)!r}")
    return cfg


def _validate_mail(mail: dict[str, Any]) -> None:
    """A configured-but-wrong relay is worse than an unconfigured one: refuse."""
    sender = mail.get("from")
    if sender is not None and not valid_address(sender):
        raise DigestError(ERR_BAD_ADDRESS, f"mail.from is not a mailable address: {sender!r}")
    port = mail.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise DigestError(ERR_BAD_CONFIG, f"mail.port must be 1..65535, got {port!r}")
    if float(mail.get("timeout_s") or 0) <= 0:
        raise DigestError(ERR_BAD_CONFIG, f"mail.timeout_s must be > 0, got {mail.get('timeout_s')!r}")


# ---- reading the ledgers ----------------------------------------------------

# Per-role length bounds. A log line can be a 40 KB traceback and a digest is a
# summary, so the clip happens at READ time: an unbounded body would make both
# the mail and the campaign fingerprint depend on how verbose one crash was.
_TITLE_CHARS = 160
_LINK_CHARS = 400
_TAG_CHARS = 40


def truncate(text: str, limit: int) -> str:
    """Clip at a word boundary, marked. Never longer than `limit`."""
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[: max(0, limit - 1)]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def _one_line(value: Any, limit: int) -> str | None:
    """Ledger text -> one collapsed, length-bounded line (None stays None)."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    return truncate(text, limit) if text else ""


def read_section(
    conn: sqlite3.Connection,
    spec: dict[str, Any],
    *,
    since: float | None = None,
    until: float | None = None,
    limit: int = 20,
    body_chars: int = 240,
) -> dict[str, Any]:
    """Rows from one validated section spec. Value XOR labelled error, always.

    The second injection gate lives here: the table must exist in
    sqlite_master and every declared column in pragma_table_info — both asked
    with `?` parameters — before any identifier is placed into a SELECT.
    """
    table, cols = spec["table"], spec["cols"]
    # sqlite validates the file HEADER lazily, on first read — not at connect —
    # so a truncated or non-sqlite ledger surfaces right here. Caught, because a
    # corrupt uptime.db must cost one labelled section, not the whole digest.
    try:
        present = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
            (table,),
        ).fetchone()
        known = {r[1] for r in conn.execute("SELECT * FROM pragma_table_info(?)", (table,))}
    except sqlite3.DatabaseError as e:
        return _section_error(spec, ERR_SOURCE_UNREADABLE, f"{spec['db']}: {type(e).__name__}: {e}")
    if not present:
        return _section_error(spec, ERR_SCHEMA_DRIFT, f"table {table!r} is not in {spec['db']}")
    wanted = set(cols.values()) | ({spec["filter"]["col"]} if spec.get("filter") else set())
    missing = sorted(wanted - known)
    if missing:
        return _section_error(
            spec, ERR_SCHEMA_DRIFT, f"{table!r} has no column(s) {missing} — ledger schema moved"
        )
    ts_col = cols["ts"]
    where, params = ["1 = 1"], []
    if since is not None:
        where.append(f'"{ts_col}" >= ?')
        params.append(float(since))
    if until is not None:
        where.append(f'"{ts_col}" <= ?')
        params.append(float(until))
    flt = spec.get("filter")
    if flt:
        frag, takes_value = FILTER_OPS[flt["op"]]
        where.append(f'"{flt["col"]}" {frag}')
        if takes_value:
            params.append(flt["value"])
    select = ", ".join(f'"{cols[r]}" AS "{r}"' for r in ROLES if r in cols)
    # Ties broken by rowid so two rows written in the same second cannot swap
    # between runs — campaign_id hashes this order.
    tail = f' ORDER BY "{ts_col}" DESC, rowid DESC LIMIT ?'
    # S608: `select`/`where`/`tail` are built ONLY from identifiers validated by
    # _ident() and confirmed present in this table; every caller value is a `?`.
    sql = f'SELECT {select} FROM "{table}" WHERE ' + " AND ".join(where) + tail  # noqa: S608
    try:
        rows = conn.execute(sql, (*params, int(limit))).fetchall()
        undated = conn.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{ts_col}" IS NULL'  # noqa: S608
        ).fetchone()[0]
    except sqlite3.DatabaseError as e:
        return _section_error(spec, ERR_SOURCE_UNREADABLE, f"{type(e).__name__}: {e}")
    items = [
        {
            "ts": None if r["ts"] is None else float(r["ts"]),
            "title": _one_line(r["title"], _TITLE_CHARS),
            "body": _one_line(r["body"], body_chars) if "body" in cols else None,
            "link": _one_line(r["link"], _LINK_CHARS) if "link" in cols else None,
            "tag": _one_line(r["tag"], _TAG_CHARS) if "tag" in cols else None,
        }
        for r in rows
    ]
    return {
        "name": _section_name(spec),
        "title": spec["title"],
        "db": spec["db"],
        "count": len(items),
        "items": items,
        "undated_rows": int(undated),
        "error": None,
        "error_rule": None,
    }


def _section_name(spec: dict[str, Any]) -> str:
    """The configured section key; the table name when read directly in a test."""
    return str(spec.get("name") or spec["table"])


def _section_error(spec: dict[str, Any], rule: str, why: str) -> dict[str, Any]:
    """count=None is the honest reading when the source could not be read."""
    return {
        "name": _section_name(spec),
        "title": spec["title"],
        "db": spec["db"],
        "count": None,
        "items": [],
        "undated_rows": None,
        "error": why,
        "error_rule": rule,
    }


def assemble(
    open_conn: Any,
    sections: dict[str, dict[str, Any]],
    *,
    since: float | None = None,
    until: float | None = None,
    limit: int = 20,
    body_chars: int = 240,
    now: float | None = None,
) -> dict[str, Any]:
    """The digest: every enabled section read through an injected opener.

    `open_conn(db_path) -> (conn | None, error | None)` is the I/O boundary —
    the CLI passes a policy-gated sqlite open, tests pass in-memory ledgers.
    """
    generated = time.time() if now is None else float(now)
    out: list[dict[str, Any]] = []
    for name, spec in sorted(sections.items(), key=lambda kv: (kv[1].get("order", 100), kv[0])):
        if not spec.get("enabled", True):
            continue
        spec = {**spec, "name": name}
        conn, error = open_conn(spec["db"])
        if conn is None:
            out.append(_section_error(spec, ERR_SOURCE_UNREADABLE, error or "source unavailable"))
            continue
        out.append(
            read_section(
                conn, spec, since=since, until=until, limit=limit, body_chars=body_chars
            )
        )
    items = sum(s["count"] for s in out if s["count"] is not None)
    dg = {
        "generated_ts": generated,
        "since": since,
        "until": until,
        "sections": out,
        "totals": {
            "items": items,
            "sections_read": sum(1 for s in out if s["error"] is None),
            "sections_failed": sum(1 for s in out if s["error"] is not None),
        },
        "empty": items == 0,
    }
    dg["campaign_id"] = campaign_id(dg)
    return dg


def campaign_id(dg: dict[str, Any]) -> str:
    """Stable id for "this digest CONTENT" — deliberately not time-dependent.

    Neither generated_ts nor the window bounds are hashed, and that is the whole
    point: a cron that fires at 06:00:03 instead of 06:00:00 moves `since` and
    `until` by three seconds, so a bounds-sensitive id would be unique on every
    single run and `already_sent()` would never match — a never-repeat guard that
    is dead code. The bounds are how the items were SELECTED; the items are what
    the issue IS. Two runs holding the same items are the same issue, and the
    second one is suppressed.

    hashlib, never builtin hash(): PYTHONHASHSEED randomizes that per process, so
    it cannot identify anything across the runs this guard has to compare.
    """
    canon = {
        "sections": [
            {
                "name": s["name"],
                "error": s["error_rule"],
                "items": [[i["ts"], i["title"], i["body"], i["link"], i["tag"]] for i in s["items"]],
            }
            for s in dg.get("sections", [])
        ],
    }
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ---- templating -------------------------------------------------------------

TAG_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")

# Every tag the shipped templates and subjects may use.
TAGS = ("title", "period", "generated", "count", "body", "name", "email", "unsubscribe", "campaign")
# Tags that only exist once a specific recipient is known — `preview` reports
# these as pending rather than pretending they resolved to "".
RECIPIENT_TAGS = ("name", "email", "unsubscribe")

TEMPLATE_TEXT = """{{title}} — {{period}}

Hello {{name}}.

{{body}}

--
{{count}} item(s), generated {{generated}}. Campaign {{campaign}}.
{{unsubscribe}}
"""

TEMPLATE_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{{title}}</title></head>
<body style="font:14px/1.5 system-ui,sans-serif;color:#111;background:#fff;margin:0;padding:16px">
<h1 style="font-size:18px;margin:0 0 4px">{{title}}</h1>
<p style="margin:0 0 16px;color:#555">{{period}} &middot; {{count}} item(s)</p>
<p style="margin:0 0 16px">Hello {{name}}.</p>
{{body}}
<hr style="border:0;border-top:1px solid #ddd;margin:24px 0 8px">
<p style="font-size:12px;color:#555;margin:0">Generated {{generated}}. Campaign {{campaign}}.<br>{{unsubscribe}}</p>
</body></html>
"""


def merge(template: str, values: dict[str, Any]) -> tuple[str, list[str]]:
    """Substitute {{tags}}; return (rendered, unresolved tag names).

    An unknown tag is left VERBATIM in the output and named in `unresolved`. The
    alternative — silently substituting "" — is exactly how a newsletter goes
    out saying "Hello ," to nine thousand people, so a typo'd tag is visible in
    the preview and gateable by the caller.
    """
    unresolved: list[str] = []

    def sub(m: re.Match[str]) -> str:
        tag = m.group(1)
        if tag not in values:
            unresolved.append(tag)
            return m.group(0)
        return str(values[tag])

    return TAG_RE.sub(sub, template), sorted(set(unresolved))


def period_label(since: float | None, until: float | None) -> str:
    """Human window for the subject line, honest when a bound is open."""
    if since is None and until is None:
        return "all time"
    if since is None:
        return f"up to {feeds.fmt_ts(until)}"
    if until is None:
        return f"since {feeds.fmt_ts(since)}"
    return f"{feeds.fmt_ts(since)} .. {feeds.fmt_ts(until)}"


def render_text(dg: dict[str, Any]) -> str:
    """The plain-text SECTIONS. Pure function of the digest -> identical anywhere.

    No title/period header here, symmetrically with render_html: the template
    owns the header via {{title}}/{{period}}, and emitting it twice is what a
    "body" renderer that thinks it is the whole mail does.
    """
    lines: list[str] = []
    for s in dg["sections"]:
        head = f"{s['title']}" + ("" if s["count"] is None else f" ({s['count']})")
        lines += [head, "-" * len(head)]
        if s["error"]:
            lines += [f"  !! unavailable — {s['error']}", ""]
            continue
        if not s["items"]:
            lines += ["  (nothing in this window)", ""]
        for n, it in enumerate(s["items"], 1):
            tag = f"[{it['tag']}] " if it.get("tag") else ""
            lines.append(f"  {n:>2}. {tag}{it.get('title') or '(untitled)'}")
            stamp = feeds.fmt_ts(it.get("ts")) or "(undated)"
            lines.append(f"      {stamp}")
            if it.get("body"):
                lines.append(f"      {it['body']}")
            if it.get("link"):
                lines.append(f"      {it['link']}")
        if s.get("undated_rows"):
            lines.append(
                f"  ({s['undated_rows']} row(s) carry no timestamp and appear in no window)"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_SAFE_SCHEMES = ("http://", "https://", "mailto:")


def safe_link(url: Any) -> str | None:
    """A link this renderer is willing to make clickable, else None.

    Ledger content is untrusted input: a feed item whose link is
    `javascript:...` or `data:text/html,...` must never become an anchor in mail
    the operator's own tooling generated. Rejected links are still SHOWN, as
    escaped text, so nothing is hidden from the reader.
    """
    if not isinstance(url, str):
        return None
    clean = url.strip()
    if not clean or any(c in clean for c in "\r\n\t <>\""):
        return None
    return clean if clean.lower().startswith(_SAFE_SCHEMES) else None


def render_html(dg: dict[str, Any]) -> str:
    """The HTML body fragment. Every ledger value escaped, nothing remote loaded."""
    esc = html_mod.escape
    out: list[str] = []
    for s in dg["sections"]:
        head = esc(s["title"]) + ("" if s["count"] is None else f" ({s['count']})")
        out.append(f'<h2 style="font-size:15px;margin:20px 0 6px">{head}</h2>')
        if s["error"]:
            out.append(
                f'<p style="margin:0;color:#a00">unavailable — {esc(s["error"])}</p>'
            )
            continue
        if not s["items"]:
            out.append('<p style="margin:0;color:#555">(nothing in this window)</p>')
        out.append('<ul style="margin:0;padding-left:20px">')
        for it in s["items"]:
            tag = f'<strong>[{esc(str(it["tag"]))}]</strong> ' if it.get("tag") else ""
            out.append(f'<li style="margin:0 0 8px">{tag}{esc(it.get("title") or "(untitled)")}')
            stamp = esc(feeds.fmt_ts(it.get("ts")) or "(undated)")
            out.append(f'<br><span style="color:#555;font-size:12px">{stamp}</span>')
            if it.get("body"):
                out.append(f'<br>{esc(str(it["body"]))}')
            link = safe_link(it.get("link"))
            if link:
                out.append(f'<br><a href="{esc(link)}">{esc(link)}</a>')
            elif it.get("link"):
                out.append(f'<br><span style="color:#a00">{esc(str(it["link"]))}</span>')
            out.append("</li>")
        out.append("</ul>")
        if s.get("undated_rows"):
            out.append(
                f'<p style="color:#555;font-size:12px;margin:4px 0 0">{s["undated_rows"]}'
                " row(s) carry no timestamp and appear in no window</p>"
            )
    return "\n".join(out)


def digest_values(dg: dict[str, Any], cfg: dict[str, Any], *, html: bool) -> dict[str, Any]:
    """The non-recipient merge values, in the right form for text or HTML.

    `body` is the ONE pre-formatted value: on the HTML path it is markup and
    must not be escaped again, while every value that came out of a ledger is
    escaped inside render_html/render_text before it gets here.
    """
    title = str(cfg["digest"]["title"])
    values = {
        "title": html_mod.escape(title) if html else title,
        "period": period_label(dg.get("since"), dg.get("until")),
        "generated": feeds.fmt_ts(dg.get("generated_ts")),
        "count": str(dg["totals"]["items"]),
        "campaign": str(dg.get("campaign_id") or ""),
        "body": render_html(dg) if html else render_text(dg),
    }
    return values


def recipient_values(recipient: dict[str, Any], mail: dict[str, Any], *, html: bool) -> dict[str, Any]:
    """name/email/unsubscribe for one person. Escaped on the HTML path.

    The unsubscribe instruction is a mailto:, never a URL: a click-to-unsubscribe
    link would need a public HTTP endpoint, which is precisely the egress this
    adapter deletes, and it would also be a read receipt.
    """
    name = recipient.get("name") or recipient["email"].partition("@")[0]
    sender = mail.get("from") or ""
    note = f"To stop these, reply to {sender} or remove {recipient['email']} from the roster."
    if html:
        return {
            "name": html_mod.escape(name),
            "email": html_mod.escape(recipient["email"]),
            "unsubscribe": html_mod.escape(note),
        }
    return {"name": name, "email": recipient["email"], "unsubscribe": note}


# ---- the no-tracking audit --------------------------------------------------

# Tags whose attributes make the CLIENT fetch something without being clicked —
# the shape of every open-tracking beacon. <a href> is absent on purpose: a link
# the reader chooses to follow is content, not surveillance.
_RESOURCE_ATTRS: dict[str, tuple[str, ...]] = {
    "img": ("src", "srcset", "lowsrc"),
    "script": ("src",),
    "iframe": ("src",),
    "frame": ("src",),
    "link": ("href",),
    "source": ("src", "srcset"),
    "video": ("src", "poster"),
    "audio": ("src",),
    "embed": ("src",),
    "object": ("data",),
    "track": ("src",),
    "input": ("src",),
    "body": ("background",),
    "table": ("background",),
    "td": ("background",),
}
_REMOTE_RE = re.compile(r"^(?:https?:|//)", re.IGNORECASE)
_CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)", re.IGNORECASE)


class _ResourceFinder(HTMLParser):
    """Collect every auto-loading remote reference in a rendered mail body."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[dict[str, str]] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "style":
            self._in_style = True
        wanted = _RESOURCE_ATTRS.get(tag, ())
        for name, value in attrs:
            if value is None:
                continue
            if name in wanted:
                for candidate in value.split(","):
                    url = candidate.strip().split(" ")[0]
                    if _REMOTE_RE.match(url):
                        self.found.append({"tag": tag, "attr": name, "url": url})
            if name == "style":
                self._scan_css(value, tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self._in_style = False

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self._scan_css(data, "style")

    def _scan_css(self, css: str, tag: str) -> None:
        for url in _CSS_URL_RE.findall(css):
            if _REMOTE_RE.match(url.strip()):
                self.found.append({"tag": tag, "attr": "css-url", "url": url.strip()})


def tracking_findings(html: str) -> list[dict[str, str]]:
    """Every remote resource the mail would make the reader's client fetch.

    Zero is the contract for this adapter's own output; a non-empty list on a
    custom template is the vendor pixel someone pasted in, named and located.
    """
    finder = _ResourceFinder()
    finder.feed(html)
    finder.close()
    return sorted(finder.found, key=lambda f: (f["tag"], f["attr"], f["url"]))


# ---- the message (email.mime) ----------------------------------------------


def safe_header(value: str, *, what: str = "header") -> str:
    """Reject CR/LF/NUL before it reaches a header. Header injection, closed.

    A section title or feed entry can reach the subject line through a template,
    and "Weekly\\nBcc: someone@else" in a header is a mail this box did not
    intend to send.
    """
    if any(c in value for c in "\r\n\0"):
        raise DigestError(ERR_HEADER_INJECTION, f"{what} contains a newline or NUL: {value!r}")
    return value


def message_id(campaign: str, recipient: str, sender: str) -> str:
    """Deterministic RFC 5322 Message-ID: same campaign + person -> same id.

    email.utils.make_msgid() mixes in a clock and randomness, which would make
    two renderings of one campaign differ and make a dry run unable to prove
    what the real send will contain.
    """
    domain = sender.rpartition("@")[2] or "localhost"
    tag = hashlib.sha256(f"{campaign}\0{recipient}".encode()).hexdigest()[:16]
    return f"<digest.{campaign}.{tag}@{domain}>"


def build_message(
    *,
    sender: str,
    recipient: str,
    subject: str,
    text: str,
    html: str,
    date_ts: float,
    msg_id: str,
    sender_name: str = "",
) -> MIMEMultipart:
    """One multipart/alternative message for exactly one recipient.

    Part order is plain THEN html: RFC 2046 says the LAST alternative is the
    preferred one, so reversing these serves plain text to every graphical
    client. To: is this one address — a shared To/Cc would publish the roster to
    everyone on it, and BCC-to-a-list gets the mail filed as spam.
    """
    if not valid_address(sender):
        raise DigestError(ERR_NO_SENDER, f"refusing to forge a From header: {sender!r}")
    if not valid_address(recipient):
        raise DigestError(ERR_BAD_ADDRESS, f"not a mailable recipient: {recipient!r}")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(safe_header(subject, what="subject"), "utf-8")
    msg["From"] = formataddr((safe_header(sender_name, what="from_name"), sender), charset="utf-8")
    msg["To"] = recipient
    msg["Date"] = formatdate(float(date_ts), usegmt=True)
    msg["Message-ID"] = msg_id
    # RFC 3834: a scheduled digest must not trigger vacation autoreplies, and
    # RFC 2369 gives clients an unsubscribe affordance that is a mailto, so the
    # act of unsubscribing opens no HTTP connection either.
    msg["Auto-Submitted"] = "auto-generated"
    msg["List-Unsubscribe"] = f"<mailto:{sender}?subject=unsubscribe>"
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def personalize(
    dg: dict[str, Any],
    cfg: dict[str, Any],
    recipient: dict[str, Any],
    *,
    template_text: str = TEMPLATE_TEXT,
    template_html: str = TEMPLATE_HTML,
) -> dict[str, Any]:
    """Render one person's copy: subject, text, html, and what did not resolve."""
    mail = cfg["mail"]
    text_values = {**digest_values(dg, cfg, html=False), **recipient_values(recipient, mail, html=False)}
    html_values = {**digest_values(dg, cfg, html=True), **recipient_values(recipient, mail, html=True)}
    text, missing_text = merge(template_text, text_values)
    html, missing_html = merge(template_html, html_values)
    subject, missing_subject = merge(str(cfg["digest"]["subject"]), text_values)
    return {
        "subject": " ".join(subject.split()),
        "text": text,
        "html": html,
        "unresolved": sorted(set(missing_text) | set(missing_html) | set(missing_subject)),
        "tracking": tracking_findings(html),
    }


# ---- delivery ---------------------------------------------------------------

STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_DRY_RUN = "dry-run"
STATUS_DUPLICATE = "skipped-duplicate"
STATUSES = (STATUS_SENT, STATUS_FAILED, STATUS_DRY_RUN, STATUS_DUPLICATE)
# Only a confirmed send suppresses a future one. A failure must retry next pass
# (the alerts #19 DEDUP_STATUSES rule, restated for mail).
SENT_STATUSES = (STATUS_SENT,)


def deliver(
    dg: dict[str, Any],
    cfg: dict[str, Any],
    *,
    send: bool = False,
    send_fn: Any = None,
    sent_lookup: Any = None,
    record_fn: Any = None,
    force: bool = False,
    now: float | None = None,
    template_text: str = TEMPLATE_TEXT,
    template_html: str = TEMPLATE_HTML,
) -> dict[str, Any]:
    """Render per recipient and (only if `send`) hand each message to `send_fn`.

    Dry run is the DEFAULT and is a true rehearsal: identical refusals, identical
    messages, no socket and no ledger row. `send_fn(msg, recipient) -> (ok,
    detail)` is the single egress boundary; tests pass a recorder.
    """
    stamp = time.time() if now is None else float(now)
    mail = cfg["mail"]
    sender = mail.get("from")
    if not valid_address(sender):
        raise DigestError(
            ERR_NO_SENDER,
            "mail.from is not configured — refusing to invent a From address "
            "(set mail.from in the digest config)",
        )
    if send and not mail.get("host"):
        raise DigestError(
            ERR_NO_RELAY, "mail.host is not configured — no relay to hand the digest to"
        )
    if send and send_fn is None:
        raise ValueError("send=True requires send_fn — the caller owns the only egress")
    targets, skipped = deliverable(cfg["recipients"])
    if not targets:
        raise DigestError(
            ERR_NO_RECIPIENTS,
            f"no subscribed, mailable recipient in the roster ({len(skipped)} entr(y/ies) skipped) "
            "— refusing to invent one",
        )
    if dg.get("empty") and not cfg["digest"].get("send_when_empty"):
        raise DigestError(
            ERR_EMPTY,
            "the digest has no items — refusing to mail an empty issue "
            "(set digest.send_when_empty to override)",
        )
    campaign = str(dg.get("campaign_id") or campaign_id(dg))
    results: list[dict[str, Any]] = []
    for person in targets:
        rendered = personalize(
            dg, cfg, person, template_text=template_text, template_html=template_html
        )
        mid = message_id(campaign, person["email"], sender)
        row: dict[str, Any] = {
            "email": person["email"],
            "name": person["name"],
            "subject": rendered["subject"],
            "message_id": mid,
            "unresolved": rendered["unresolved"],
            "tracking": rendered["tracking"],
            "status": STATUS_DRY_RUN,
            "detail": "rendered, not sent (dry run)",
            "bytes": None,
        }
        msg = build_message(
            sender=sender,
            sender_name=str(mail.get("from_name") or ""),
            recipient=person["email"],
            subject=rendered["subject"],
            text=rendered["text"],
            html=rendered["html"],
            date_ts=stamp,
            msg_id=mid,
        )
        row["bytes"] = len(msg.as_bytes())
        already = bool(sent_lookup(campaign, person["email"])) if sent_lookup else False
        if already and not force:
            row["status"] = STATUS_DUPLICATE
            row["detail"] = f"campaign {campaign} already sent to this address (--force to repeat)"
        elif send:
            ok, detail = send_fn(msg, person["email"])
            row["status"] = STATUS_SENT if ok else STATUS_FAILED
            row["detail"] = detail
            if record_fn is not None:
                record_fn(row)
        results.append(row)
    return {
        "campaign_id": campaign,
        "dry_run": not send,
        "sender": sender,
        "relay": mail.get("host"),
        "results": results,
        "skipped": skipped,
        "totals": {
            **{s: sum(1 for r in results if r["status"] == s) for s in STATUSES},
            "skipped": len(skipped),
            "recipients": len(results),
        },
        "generated_ts": stamp,
    }


# ---- the send ledger --------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sends(
    campaign_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    ts REAL NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    subject TEXT,
    message_id TEXT,
    PRIMARY KEY(campaign_id, recipient)
);
CREATE INDEX IF NOT EXISTS idx_sends_ts ON sends(ts);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_ledger(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) this adapter's OWN send ledger.

    Its own file: a digest run must never hold the monitoring ledger's write
    lock, and the ledgers it reads are opened read-only.
    """
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)", (SCHEMA_VERSION,)
    )
    conn.commit()
    return conn


def record_send(conn: sqlite3.Connection, campaign: str, row: dict[str, Any], *, ts: float) -> None:
    """Persist one delivery outcome. REPLACE so a retry overwrites its failure."""
    conn.execute(
        "INSERT OR REPLACE INTO sends(campaign_id, recipient, ts, status, detail, subject, message_id)"
        " VALUES(?,?,?,?,?,?,?)",
        (
            campaign,
            row["email"],
            float(ts),
            row["status"],
            row.get("detail"),
            row.get("subject"),
            row.get("message_id"),
        ),
    )
    conn.commit()


def already_sent(conn: sqlite3.Connection, campaign: str, recipient: str) -> bool:
    """True only if this exact campaign reached this address SUCCESSFULLY."""
    placeholders = ",".join("?" for _ in SENT_STATUSES)
    # S608: `placeholders` is a run of `?` sized from a module constant; the
    # status values themselves are bound parameters like every other value here.
    sql = f"SELECT 1 FROM sends WHERE campaign_id = ? AND recipient = ? AND status IN ({placeholders}) LIMIT 1"  # noqa: S608
    row = conn.execute(sql, (campaign, recipient, *SENT_STATUSES)).fetchone()
    return row is not None


def history(conn: sqlite3.Connection, *, limit: int = 25) -> list[dict[str, Any]]:
    """Newest deliveries first — what this box actually mailed, and to whom."""
    rows = conn.execute(
        "SELECT campaign_id, recipient, ts, status, detail, subject, message_id"
        " FROM sends ORDER BY ts DESC, recipient ASC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [{**dict(r), "when": feeds.fmt_ts(r["ts"])} for r in rows]


# ---- the family gate --------------------------------------------------------

_SECTION_SEVERITY = {ERR_SOURCE_UNREADABLE: "warning", ERR_SCHEMA_DRIFT: "error"}


def to_diagnostics(dg: dict[str, Any], result: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Map a digest pass onto the openswap schema so --fail-on gates it.

    Severity reasoning: a schema drift is an ERROR (the section will report
    nothing forever and nobody would notice), a missing ledger is a WARNING (a
    store that was never created is a normal state on a fresh box), an
    unresolved tag and a tracking beacon are ERRORS (both mean the mail is wrong
    in a way the reader sees), and a failed delivery is an ERROR (silence).
    """
    diags: list[dict[str, Any]] = []
    for s in dg.get("sections", []):
        if s["error"]:
            diags.append(
                openswap.diagnostic(
                    path=s["db"],
                    line=0,
                    col=0,
                    rule=s["error_rule"] or ERR_SOURCE_UNREADABLE,
                    severity=_SECTION_SEVERITY.get(s["error_rule"] or "", "warning"),
                    message=f"section {s['name']}: {s['error']}",
                )
            )
        elif s.get("undated_rows"):
            diags.append(
                openswap.diagnostic(
                    path=s["db"],
                    line=0,
                    col=0,
                    rule=ERR_UNDATED,
                    severity="info",
                    message=(
                        f"section {s['name']}: {s['undated_rows']} row(s) have a NULL "
                        "timestamp and can appear in no digest window"
                    ),
                )
            )
    if dg.get("empty"):
        diags.append(
            openswap.diagnostic(
                path="digest",
                line=0,
                col=0,
                rule=ERR_EMPTY,
                severity="suggestion",
                message="no items in the window — widen --days or ingest first",
            )
        )
    diags.extend(_delivery_diagnostics(result or {}))
    return openswap.sort_diagnostics(diags)


def _delivery_diagnostics(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-recipient findings: failures, beacons and unresolved tags."""
    diags: list[dict[str, Any]] = []
    for r in result.get("results", []):
        if r["status"] == STATUS_FAILED:
            diags.append(
                openswap.diagnostic(
                    path=r["email"],
                    line=0,
                    col=0,
                    rule=ERR_UNDELIVERABLE,
                    severity="error",
                    message=f"delivery failed: {r.get('detail')}",
                )
            )
        for tag in r.get("unresolved", []):
            diags.append(
                openswap.diagnostic(
                    path=r["email"],
                    line=0,
                    col=0,
                    rule=ERR_UNRESOLVED_TAG,
                    severity="error",
                    message=f"template tag {{{{{tag}}}}} did not resolve — it shipped verbatim",
                )
            )
        for hit in r.get("tracking", []):
            diags.append(
                openswap.diagnostic(
                    path=r["email"],
                    line=0,
                    col=0,
                    rule=ERR_TRACKING,
                    severity="error",
                    message=(
                        f"<{hit['tag']} {hit['attr']}> loads {hit['url']} — a remote resource in "
                        "mail is a read receipt; this adapter exists to delete it"
                    ),
                )
            )
    for s in result.get("skipped", []):
        diags.append(
            openswap.diagnostic(
                path=s.get("email") or "(no address)",
                line=0,
                col=0,
                rule=s["reason"],
                severity="warning" if s["reason"] == ERR_BAD_ADDRESS else "info",
                message=f"recipient skipped: {s['detail']}",
            )
        )
    return diags
