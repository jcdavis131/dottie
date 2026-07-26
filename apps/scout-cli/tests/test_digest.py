"""Digest — openswap #32 (Mailchimp -> stdlib digest mailer over local ledgers).

Pure-logic core tests: address validation, roster states and dedupe, config
merge + every named refusal, the double-gated section reader (identifier regex,
sqlite_master, pragma_table_info) against REAL ledger schemas built by the
uptime/logs/glitch/feeds cores themselves, window bounds, the value-XOR-error
honesty invariant, tie-stable ordering, merge-tag templating (an unknown tag
survives VERBATIM and is named), HTML escaping of hostile ledger content, the
no-tracking audit, email.mime part order and header-injection refusal, the
dry-run-is-a-rehearsal invariant, the never-repeat guard, and the real CLI in a
subprocess. Offline and deterministic by construction: the only smtplib in here
is a recorder injected in place of the real one, and no test opens a socket.
"""

from __future__ import annotations

import ast
import email
import json
import os
import sqlite3
import subprocess
import sys
import time
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path

import pytest

from bigbang.core import digest, feeds, glitch, logs, openswap, uptime

ROOT = Path(__file__).resolve().parents[1]
T0 = 1_750_000_000.0  # a fixed instant: every timestamp below is derived from it
DAY = 86400.0


# ---- helpers ----------------------------------------------------------------


def _conn(
    schema: str, rows: list[tuple] = (), *, insert: str = ""
) -> sqlite3.Connection:
    """An in-memory ledger with the schema under test. No fixture files."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(schema)
    for r in rows:
        c.execute(insert, r)
    c.commit()
    return c


def _spec(**over) -> dict:
    base = {
        "name": "s",
        "db": "mem",
        "table": "t",
        "cols": {"ts": "ts", "title": "title"},
        "title": "Section",
        "order": 10,
        "enabled": True,
    }
    base.update(over)
    return digest.validate_section(base.get("name", "s"), base) | {"name": base["name"]}


def _cfg(tmp_path: Path, **over) -> dict:
    """A config written to disk and loaded back, so load_config is on the path."""
    body = {
        "mail": {"from": "digest@box", "host": "127.0.0.1", "port": 25},
        "digest": {"title": "Weekly"},
        "recipients": [{"email": "jc@box", "name": "JC"}],
        "sections": {},
    }
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(body.get(key), dict):
            body[key] = {**body[key], **value}
        else:
            body[key] = value
    p = tmp_path / "digest.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return digest.load_config(str(p))


def _dg(items: list[dict], *, since=T0 - DAY, until=T0, error=None, undated=0) -> dict:
    """A digest dict shaped exactly like assemble() returns one."""
    section = {
        "name": "s",
        "title": "Section",
        "db": "mem",
        "count": None if error else len(items),
        "items": [] if error else items,
        "undated_rows": None if error else undated,
        "error": error,
        "error_rule": digest.ERR_SCHEMA_DRIFT if error else None,
    }
    dg = {
        "generated_ts": T0,
        "since": since,
        "until": until,
        "sections": [section],
        "totals": {
            "items": 0 if error else len(items),
            "sections_read": 0 if error else 1,
            "sections_failed": 1 if error else 0,
        },
        "empty": bool(error) or not items,
    }
    dg["campaign_id"] = digest.campaign_id(dg)
    return dg


def _item(**over) -> dict:
    base = {
        "ts": T0 - 60,
        "title": "a thing happened",
        "body": None,
        "link": None,
        "tag": None,
    }
    base.update(over)
    return base


# ---- addresses and the roster ------------------------------------------------


def test_valid_address_accepts_real_shapes():
    for good in (
        "jc@box",
        "digest@jcamd.com",
        "a.b+tag@sub.example.co.uk",
        "x@127.0.0.1",
    ):
        assert digest.valid_address(good) is True, good


def test_valid_address_rejects_everything_ambiguous():
    bad = [
        "",
        "jc",
        "jc@",
        "@box",
        "jc box@x",  # parseaddr keeps this verbatim — the regex is the real gate
        "a@b,c@d",  # parseaddr silently truncates to a@b: would mail a stranger
        "JC <jc@box>",  # a display name belongs in from_name, not in the address
        "jc@box\nBcc: evil@x",
        "jc@box\r\n",
        "jc@-box",
        "jc@box..com",
        "a" * 250 + "@box",
        None,
        12,
        True,
    ]
    for value in bad:
        assert digest.valid_address(value) is False, value


def test_normalize_recipient_accepts_a_bare_string_and_defaults_to_subscribed():
    assert digest.normalize_recipient("jc@box") == {
        "email": "jc@box",
        "name": "",
        "state": digest.STATE_SUBSCRIBED,
    }
    assert digest.normalize_recipient({"email": "jc@box", "name": "  "})["name"] == ""


def test_normalize_recipient_refuses_an_unknown_state_by_name():
    with pytest.raises(digest.DigestError) as e:
        digest.normalize_recipient({"email": "jc@box", "state": "maybe"})
    assert e.value.rule == digest.ERR_BAD_CONFIG
    assert "maybe" in e.value.message


def test_deliverable_labels_every_exclusion_and_keeps_order():
    mailable, skipped = digest.deliverable(
        [
            {"email": "b@box"},
            {"email": "a@box"},
            {"email": "old@box", "state": digest.STATE_UNSUBSCRIBED},
            {"email": "gone@box", "state": digest.STATE_BOUNCED},
            {"email": "not an address"},
        ]
    )
    assert [r["email"] for r in mailable] == [
        "b@box",
        "a@box",
    ]  # roster order, not sorted
    assert [(s["email"], s["reason"]) for s in skipped] == [
        ("old@box", digest.ERR_UNSUBSCRIBED),
        ("gone@box", digest.ERR_UNSUBSCRIBED),
        ("not an address", digest.ERR_BAD_ADDRESS),
    ]
    assert all(s["detail"] for s in skipped), "every skip must carry a WHY"


def test_deliverable_collapses_a_duplicated_address():
    mailable, skipped = digest.deliverable([{"email": "jc@box"}, {"email": "JC@BOX"}])
    assert [r["email"] for r in mailable] == ["jc@box"]
    assert len(skipped) == 1 and skipped[0]["detail"] == "duplicate address in roster"


# ---- config ------------------------------------------------------------------


def test_shipped_config_has_no_sender_no_relay_and_no_roster():
    """The headline invariant: nothing is invented, so nothing is configured."""
    cfg = digest.load_config()
    assert cfg["mail"]["from"] is None and cfg["mail"]["host"] is None
    assert cfg["recipients"] == []
    assert digest.valid_address(cfg["mail"]["from"]) is False


def test_default_sections_point_at_the_other_adapters_own_db_constants():
    dbs = {name: s["db"] for name, s in digest.DEFAULT_SECTIONS.items()}
    assert dbs["incidents"] == uptime.DB_REL.as_posix()
    assert dbs["errors"] == logs.DB_REL.as_posix()
    assert dbs["issues"] == glitch.DB_REL.as_posix()
    assert dbs["reading"] == feeds.DB_REL.as_posix()


def test_error_threshold_is_read_from_the_logs_level_ladder():
    """A renamed/reordered level must not silently change what the digest reports."""
    want = logs.LEVELS.index(logs.LEVEL_ERROR)
    assert digest.DEFAULT_SECTIONS["errors"]["filter"]["value"] == want
    assert logs.LEVELS.index(logs.LEVEL_CRITICAL) <= want, (
        "critical must pass an <= error filter"
    )


def test_config_overlay_merges_dicts_and_drops_a_section_with_false(tmp_path):
    cfg = _cfg(
        tmp_path,
        sections={**digest.DEFAULT_SECTIONS, "reading": False},
        digest={"title": "Mine"},
    )
    assert "reading" not in cfg["sections"] and "incidents" in cfg["sections"]
    assert cfg["digest"]["title"] == "Mine"
    assert (
        cfg["digest"]["window_days"] == digest.DEFAULT_DIGEST["window_days"]
    )  # untouched key


def test_config_replaces_the_recipient_list_wholesale(tmp_path):
    cfg = _cfg(tmp_path, recipients=[{"email": "only@box"}])
    assert [r["email"] for r in cfg["recipients"]] == ["only@box"]


def test_config_refuses_a_forged_from_a_bad_port_and_a_zero_window(tmp_path):
    for over, rule in [
        ({"mail": {"from": "not an address"}}, digest.ERR_BAD_ADDRESS),
        ({"mail": {"port": 0}}, digest.ERR_BAD_CONFIG),
        ({"mail": {"port": True}}, digest.ERR_BAD_CONFIG),
        ({"mail": {"timeout_s": 0}}, digest.ERR_BAD_CONFIG),
        ({"digest": {"window_days": 0}}, digest.ERR_BAD_CONFIG),
        ({"digest": {"body_chars": -1}}, digest.ERR_BAD_CONFIG),
    ]:
        with pytest.raises(digest.DigestError) as e:
            _cfg(tmp_path, **over)
        assert e.value.rule == rule, over


def test_config_rejects_a_non_object_file(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(digest.DigestError) as e:
        digest.load_config(str(p))
    assert e.value.rule == digest.ERR_BAD_CONFIG


def test_section_validation_refuses_sql_in_an_identifier():
    for value in ("entries; DROP TABLE entries", "a b", '"t"', "1t", "", None):
        with pytest.raises(digest.DigestError) as e:
            digest.validate_section(
                "s", {"db": "d", "table": value, "cols": {"ts": "ts", "title": "x"}}
            )
        assert e.value.rule == digest.ERR_BAD_IDENTIFIER, value


def test_section_validation_refuses_a_bad_column_role_or_a_missing_required_one():
    with pytest.raises(digest.DigestError) as e:
        digest.validate_section(
            "s",
            {
                "db": "d",
                "table": "t",
                "cols": {"ts": "ts", "title": "x", "author": "a"},
            },
        )
    assert e.value.rule == digest.ERR_BAD_CONFIG and "author" in e.value.message
    for cols in ({"title": "x"}, {"ts": "ts"}, {}):
        with pytest.raises(digest.DigestError) as e:
            digest.validate_section("s", {"db": "d", "table": "t", "cols": cols})
        assert e.value.rule == digest.ERR_BAD_CONFIG and "required" in e.value.message


def test_section_validation_refuses_a_filter_op_outside_the_fixed_set():
    with pytest.raises(digest.DigestError) as e:
        digest.validate_section(
            "s",
            {
                "db": "d",
                "table": "t",
                "cols": {"ts": "ts", "title": "x"},
                "filter": {"col": "lvl", "op": "OR 1=1 --", "value": 1},
            },
        )
    assert e.value.rule == digest.ERR_BAD_CONFIG
    assert set(digest.FILTER_OPS) >= {"=", "<=", "isnull", "notnull"}


def test_every_shipped_section_survives_its_own_validator():
    # Pin the PREMISES first: without these the assertions below cannot fail.
    # `set(x) >= set()` is True for every x, so an empty REQUIRED_ROLES would make
    # the cols check vacuous; and an empty DEFAULT_SECTIONS would skip the loop
    # entirely and still pass. Both are currently non-empty (('ts','title') and 4
    # sections) — these two lines are what keeps that true.
    assert digest.REQUIRED_ROLES, (
        "empty REQUIRED_ROLES makes the cols assertion vacuous"
    )
    assert len(digest.DEFAULT_SECTIONS) >= 4, (
        "an empty mapping would skip the loop and pass"
    )
    for name, spec in digest.DEFAULT_SECTIONS.items():
        out = digest.validate_section(name, spec)
        assert out["enabled"] is True and out["title"]
        assert set(out["cols"]) >= set(digest.REQUIRED_ROLES)


# ---- reading the ledgers -----------------------------------------------------

_T_SCHEMA = (
    "CREATE TABLE t(ts REAL, title TEXT, body TEXT, link TEXT, tag TEXT, lvl INTEGER)"
)
_T_INSERT = "INSERT INTO t(ts, title, body, link, tag, lvl) VALUES(?,?,?,?,?,?)"


def _rows(*specs) -> sqlite3.Connection:
    return _conn(_T_SCHEMA, list(specs), insert=_T_INSERT)


def test_read_section_returns_newest_first_and_breaks_ties_by_rowid():
    """Two rows in the same second must not swap between runs — the campaign id
    is a hash of this order, so a nondeterministic tie kills the repeat guard."""
    c = _rows(
        (T0 - 300, "older", None, None, None, 0),
        (T0, "tie-first-inserted", None, None, None, 0),
        (T0, "tie-second-inserted", None, None, None, 0),
    )
    out = digest.read_section(c, _spec())
    assert [i["title"] for i in out["items"]] == [
        "tie-second-inserted",
        "tie-first-inserted",
        "older",
    ]
    twin = _rows(
        (T0 - 300, "older", None, None, None, 0),
        (T0, "tie-first-inserted", None, None, None, 0),
        (T0, "tie-second-inserted", None, None, None, 0),
    )
    assert digest.read_section(twin, _spec())["items"] == out["items"]


def test_read_section_window_bounds_are_inclusive_and_exclude_the_outside():
    c = _rows(
        (T0 - 2 * DAY, "before", None, None, None, 0),
        (T0 - DAY, "on the since bound", None, None, None, 0),
        (T0 - 600, "inside", None, None, None, 0),
        (T0, "on the until bound", None, None, None, 0),
        (T0 + 1, "after", None, None, None, 0),
    )
    out = digest.read_section(c, _spec(), since=T0 - DAY, until=T0)
    assert [i["title"] for i in out["items"]] == [
        "on the until bound",
        "inside",
        "on the since bound",
    ]
    assert out["count"] == 3


def test_read_section_limit_caps_the_rows_read():
    c = _rows(*[(T0 - i, f"row {i}", None, None, None, 0) for i in range(10)])
    out = digest.read_section(c, _spec(), limit=3)
    assert out["count"] == 3 and [i["title"] for i in out["items"]] == [
        "row 0",
        "row 1",
        "row 2",
    ]


def test_read_section_applies_a_declarative_filter():
    c = _rows(
        (T0, "critical", None, None, None, 0),
        (T0 - 1, "error", None, None, None, 1),
        (T0 - 2, "info", None, None, None, 3),
    )
    spec = _spec(
        cols={"ts": "ts", "title": "title"},
        filter={"col": "lvl", "op": "<=", "value": 1},
    )
    assert [i["title"] for i in digest.read_section(c, spec)["items"]] == [
        "critical",
        "error",
    ]
    null_spec = _spec(filter={"col": "tag", "op": "isnull"})
    assert digest.read_section(c, null_spec)["count"] == 3


def test_read_section_counts_undated_rows_instead_of_dropping_them_silently():
    c = _rows(
        (T0, "dated", None, None, None, 0),
        (None, "no timestamp", None, None, None, 0),
        (None, "also none", None, None, None, 0),
    )
    out = digest.read_section(c, _spec(), since=T0 - DAY, until=T0)
    assert out["count"] == 1 and out["undated_rows"] == 2
    assert "no timestamp" not in [i["title"] for i in out["items"]]


def test_read_section_reports_a_missing_table_as_schema_drift_not_as_zero():
    out = digest.read_section(_rows(), _spec(table="gone"))
    assert out["count"] is None and out["error_rule"] == digest.ERR_SCHEMA_DRIFT
    assert "gone" in out["error"] and out["items"] == []


def test_read_section_reports_a_vanished_column_and_names_it():
    out = digest.read_section(_rows(), _spec(cols={"ts": "ts", "title": "headline"}))
    assert out["count"] is None and out["error_rule"] == digest.ERR_SCHEMA_DRIFT
    assert "headline" in out["error"]
    flt = digest.read_section(
        _rows(), _spec(filter={"col": "nope", "op": "=", "value": 1})
    )
    assert flt["count"] is None and "nope" in flt["error"]


def test_a_reading_has_either_a_value_or_a_reason_never_both_never_neither():
    good = digest.read_section(_rows((T0, "x", None, None, None, 0)), _spec())
    bad = digest.read_section(_rows(), _spec(table="gone"))
    for out in (good, bad):
        assert (out["error"] is None) != (out["count"] is None), out
        if out["error"] is None:
            assert isinstance(out["count"], int) and isinstance(
                out["undated_rows"], int
            )
        else:
            assert out["error_rule"] in (
                digest.ERR_SCHEMA_DRIFT,
                digest.ERR_SOURCE_UNREADABLE,
            )
            assert out["undated_rows"] is None


def test_read_section_quotes_identifiers_so_a_keyword_column_still_works():
    c = _conn(
        'CREATE TABLE t(ts REAL, "order" TEXT)',
        [(T0, "quoted fine")],
        insert='INSERT INTO t(ts, "order") VALUES(?,?)',
    )
    out = digest.read_section(c, _spec(cols={"ts": "ts", "title": "order"}))
    assert [i["title"] for i in out["items"]] == ["quoted fine"]


def test_read_section_collapses_whitespace_and_truncates_the_body():
    c = _rows((T0, "  a\n  spread   title ", "x" * 300, None, None, 0))
    out = digest.read_section(
        c, _spec(cols={"ts": "ts", "title": "title", "body": "body"}), body_chars=50
    )
    item = out["items"][0]
    assert item["title"] == "a spread title"
    assert len(item["body"]) == 50 and item["body"].endswith("…")


def test_truncate_never_exceeds_the_limit_and_leaves_short_text_alone():
    assert digest.truncate("abcde", 5) == "abcde"
    assert (
        digest.truncate("abcdef", 5) == "abcd…"
        and len(digest.truncate("abcdef", 5)) == 5
    )
    assert digest.truncate("hello world again", 12) == "hello world…"
    assert digest.truncate("x", 0) == "x"  # limit <= 0 disables the clip


def test_read_section_absent_roles_come_back_as_none_not_missing_keys():
    out = digest.read_section(_rows((T0, "t", "b", "l", "g", 0)), _spec())
    item = out["items"][0]
    assert set(item) == {"ts", "title", "body", "link", "tag"}
    assert (item["body"], item["link"], item["tag"]) == (None, None, None)


# ---- the real ledger schemas -------------------------------------------------


def _real_ledgers(root: Path, *, base: float = T0) -> Path:
    """Build the four ledgers with their OWN cores, so the schemas are real.

    Idempotent (a scenario may be built twice inside one test) and every
    connection is CLOSED: Windows refuses to unlink a file sqlite still holds.
    """
    scout = root / ".scout"
    if (scout / "uptime.db").exists():
        return scout
    scout.mkdir(parents=True, exist_ok=True)
    up = uptime.open_ledger(scout / "uptime.db")
    up.execute(
        "INSERT INTO incidents(target, state, opened_ts, closed_ts) VALUES(?,?,?,?)",
        ("dumbmodel.com", uptime.STATE_DOWN, base - 3600, None),
    )
    up.commit()
    lg = logs.open_store(scout / "logs.db")
    for i, (level, msg) in enumerate([("error", "CUDA OOM"), ("info", "step 4121")]):
        lg.execute(
            "INSERT INTO entries(source, path, line_no, ts, dated, ingest_ts, level, level_rank,"
            " message, raw, parser, parsed) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "trainer",
                "train.log",
                i,
                base - 600,
                1,
                base,
                level,
                logs.LEVELS.index(level),
                msg,
                msg,
                "jsonl",
                1,
            ),
        )
    lg.commit()
    gl = glitch.open_store(scout / "glitch.db")
    for status, msg in (
        (glitch.STATUS_OPEN, "KeyError: tokenizer"),
        (glitch.STATUS_RESOLVED, "old"),
    ):
        gl.execute(
            "INSERT INTO issues(project, fingerprint, kind, message, culprit, file, line, level,"
            " status, first_seen, last_seen, count) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "dottie",
                msg,
                "KeyError",
                msg,
                "eval.py:88",
                "eval.py",
                88,
                "error",
                status,
                base - 9000,
                base - 900,
                4,
            ),
        )
    gl.commit()
    fd = feeds.open_store(scout / "feeds.db")
    fd.execute(
        "INSERT INTO entries(feed, key, link, title, summary, published_ts, first_seen_ts, score)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (
            "arxiv",
            "k1",
            "https://arxiv.org/abs/1",
            "Muon at scale",
            "holds up",
            base - 1200,
            base - 1200,
            3.0,
        ),
    )
    fd.commit()
    for conn in (up, lg, gl, fd):
        conn.close()
    return scout


def test_every_shipped_section_reads_the_real_schema_its_adapter_writes(tmp_path):
    _real_ledgers(tmp_path)
    opened: list[str] = []

    def open_conn(db: str):
        opened.append(db)
        p = tmp_path / db
        if not p.exists():
            return None, f"ledger not found: {p}"
        c = sqlite3.connect(str(p))
        c.row_factory = sqlite3.Row
        return c, None

    dg = digest.assemble(
        open_conn, digest.load_config()["sections"], since=T0 - DAY, until=T0
    )
    by_name = {s["name"]: s for s in dg["sections"]}
    assert sorted(opened) == sorted(s["db"] for s in digest.DEFAULT_SECTIONS.values())
    assert [s["error"] for s in dg["sections"]] == [None, None, None, None], by_name
    assert by_name["incidents"]["count"] == 1
    assert by_name["errors"]["count"] == 1, "the level filter must drop the info line"
    assert by_name["issues"]["count"] == 1, (
        "the status filter must drop the resolved issue"
    )
    assert by_name["reading"]["count"] == 1
    assert dg["totals"]["items"] == 4 and dg["empty"] is False
    assert by_name["reading"]["items"][0]["link"] == "https://arxiv.org/abs/1"


def test_a_missing_ledger_is_a_labelled_reason_and_the_rest_still_read(tmp_path):
    scout = _real_ledgers(tmp_path)
    (scout / "feeds.db").unlink()

    def open_conn(db: str):
        p = tmp_path / db
        if not p.exists():
            return None, f"ledger not found: {p} (nothing has written it yet)"
        c = sqlite3.connect(str(p))
        c.row_factory = sqlite3.Row
        return c, None

    dg = digest.assemble(
        open_conn, digest.load_config()["sections"], since=T0 - DAY, until=T0
    )
    reading = next(s for s in dg["sections"] if s["name"] == "reading")
    assert (
        reading["count"] is None
        and reading["error_rule"] == digest.ERR_SOURCE_UNREADABLE
    )
    assert "nothing has written it yet" in reading["error"]
    assert dg["totals"]["sections_failed"] == 1 and dg["totals"]["sections_read"] == 3
    assert dg["totals"]["items"] == 3, "a failed section must not poison the item count"


# ---- assemble ----------------------------------------------------------------


def _mem_opener(mapping: dict[str, sqlite3.Connection]):
    def open_conn(db: str):
        if db not in mapping:
            return None, f"no such ledger: {db}"
        return mapping[db], None

    return open_conn


def test_assemble_orders_sections_by_order_then_name_and_skips_disabled():
    c = _rows((T0, "x", None, None, None, 0))
    sections = {
        "zulu": {**_spec(name="zulu", order=1), "db": "a"},
        "alpha": {**_spec(name="alpha", order=1), "db": "a"},
        "last": {**_spec(name="last", order=99), "db": "a"},
        "off": {**_spec(name="off", order=0), "db": "a", "enabled": False},
    }
    dg = digest.assemble(_mem_opener({"a": c}), sections, now=T0)
    assert [s["name"] for s in dg["sections"]] == ["alpha", "zulu", "last"]
    assert dg["generated_ts"] == T0


def test_assemble_marks_an_empty_digest():
    c = _rows()
    dg = digest.assemble(_mem_opener({"a": c}), {"s": {**_spec(), "db": "a"}}, now=T0)
    assert dg["totals"]["items"] == 0 and dg["empty"] is True
    c2 = _rows((T0, "one", None, None, None, 0))
    dg2 = digest.assemble(_mem_opener({"a": c2}), {"s": {**_spec(), "db": "a"}}, now=T0)
    assert dg2["totals"]["items"] == 1 and dg2["empty"] is False


# ---- the campaign id ---------------------------------------------------------


def test_campaign_id_ignores_the_clock_so_the_repeat_guard_can_ever_fire():
    """A cron firing 3s late moves the window; the issue is still the same issue."""
    items = [_item(title="same")]
    early = _dg(items, since=T0 - DAY, until=T0)
    late = _dg(items, since=T0 - DAY + 3, until=T0 + 3)
    late["generated_ts"] = T0 + 3
    assert early["campaign_id"] == late["campaign_id"]


def test_campaign_id_changes_when_the_content_changes():
    base = _dg([_item(title="a")])["campaign_id"]
    assert _dg([_item(title="b")])["campaign_id"] != base
    assert _dg([_item(title="a"), _item(title="a")])["campaign_id"] != base
    assert _dg([_item(title="a", body="new detail")])["campaign_id"] != base
    assert _dg([], error="table gone")["campaign_id"] != base
    assert len(base) == 16 and set(base) <= set("0123456789abcdef")


def test_campaign_id_is_stable_across_processes():
    """hashlib, not builtin hash(): PYTHONHASHSEED must not move the id."""
    dg = _dg([_item(title="stable")])
    src = "import json,sys;sys.path.insert(0,sys.argv[1]);from bigbang.core import digest;print(digest.campaign_id(json.loads(sys.argv[2])))"
    out = subprocess.run(
        [sys.executable, "-c", src, str(ROOT), json.dumps(dg)],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONHASHSEED": "7"},
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == dg["campaign_id"]


# ---- templating --------------------------------------------------------------


def test_merge_leaves_an_unknown_tag_verbatim_and_names_it():
    out, missing = digest.merge(
        "Hi {{name}}, see {{nmae}} and {{count}}", {"name": "JC", "count": 3}
    )
    assert out == "Hi JC, see {{nmae}} and 3"
    assert missing == ["nmae"], "a typo'd tag must be reported, never blanked"


def test_merge_reports_each_unknown_tag_once_and_tolerates_spacing():
    out, missing = digest.merge("{{ name }} {{x}} {{x}} {{y}}", {"name": "JC"})
    assert out == "JC {{x}} {{x}} {{y}}" and missing == ["x", "y"]


def test_merge_does_not_treat_stray_braces_as_tags():
    out, missing = digest.merge("{{Name}} {{ }} {} {{1x}} literal", {})
    assert missing == [] and out == "{{Name}} {{ }} {} {{1x}} literal"


def test_period_label_says_which_bound_is_open():
    assert digest.period_label(None, None) == "all time"
    assert digest.period_label(T0, None).startswith("since ")
    assert digest.period_label(None, T0).startswith("up to ")
    both = digest.period_label(T0 - DAY, T0)
    assert " .. " in both and feeds.fmt_ts(T0) in both


def test_every_shipped_template_tag_resolves_for_a_real_recipient(tmp_path):
    cfg = _cfg(tmp_path)
    dg = _dg([_item(title="x")])
    template = " ".join("{{" + t + "}}" for t in digest.TAGS)
    rendered = digest.personalize(
        dg, cfg, cfg["recipients"][0], template_text=template, template_html=template
    )
    assert rendered["unresolved"] == []
    assert "{{" not in rendered["text"] and "{{" not in rendered["html"]
    assert set(digest.RECIPIENT_TAGS) <= set(digest.TAGS)


def test_the_shipped_templates_only_use_declared_tags():
    used = set(digest.TAG_RE.findall(digest.TEMPLATE_TEXT))
    used |= set(digest.TAG_RE.findall(digest.TEMPLATE_HTML))
    used |= set(digest.TAG_RE.findall(str(digest.DEFAULT_DIGEST["subject"])))
    assert used and used <= set(digest.TAGS), sorted(used - set(digest.TAGS))


def test_render_text_shows_sections_counts_errors_and_the_undated_note():
    body = digest.render_text(
        _dg(
            [_item(title="a thing", tag="down", body="detail", link="https://x/1")],
            undated=2,
        )
    )
    assert "Section (1)" in body and "1. [down] a thing" in body
    assert "detail" in body and "https://x/1" in body
    assert "2 row(s) carry no timestamp" in body
    empty = digest.render_text(_dg([]))
    assert "(nothing in this window)" in empty
    broken = digest.render_text(_dg([], error="table gone"))
    assert "unavailable — table gone" in broken and "(1)" not in broken


def test_render_text_marks_an_undated_item_rather_than_printing_an_epoch():
    body = digest.render_text(_dg([_item(ts=None, title="no date")]))
    assert "(undated)" in body and "1970" not in body


def test_render_text_does_not_embed_the_generation_time():
    """Two runs of the same issue must render the same body, or campaign identity
    and the rendered mail disagree about what "the same digest" means."""
    early = _dg([_item(title="stable", body="x")])
    late = _dg([_item(title="stable", body="x")], since=T0 - DAY + 9, until=T0 + 9)
    late["generated_ts"] = T0 + 9
    assert digest.render_text(early) == digest.render_text(late)
    assert feeds.fmt_ts(T0) not in digest.render_text(early)


def test_render_html_escapes_hostile_ledger_content():
    hostile = '<script>alert(1)</script> & "quoted"'
    html = digest.render_html(_dg([_item(title=hostile, body=hostile, tag=hostile)]))
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert html.count("&amp;") >= 1


def test_render_html_refuses_to_make_a_hostile_link_clickable_but_still_shows_it():
    for hostile in (
        "javascript:alert(1)",
        "data:text/html,<script>x</script>",
        "file:///etc/passwd",
    ):
        html = digest.render_html(_dg([_item(title="t", link=hostile)]))
        assert 'href="' not in html, hostile
        assert digest.safe_link(hostile) is None
    safe = digest.render_html(_dg([_item(title="t", link="https://arxiv.org/abs/1")]))
    assert '<a href="https://arxiv.org/abs/1">' in safe


def test_safe_link_accepts_only_http_https_mailto_and_rejects_smuggled_whitespace():
    assert digest.safe_link("https://x/1") == "https://x/1"
    assert digest.safe_link(" http://x/1 ") == "http://x/1"
    assert digest.safe_link("mailto:jc@box") == "mailto:jc@box"
    for bad in (
        "//x/1",
        "https://x/1\nSet-Cookie: a",
        'https://x/"onload=x',
        "",
        None,
        5,
    ):
        assert digest.safe_link(bad) is None, bad


def test_digest_values_escapes_the_title_on_the_html_path_only(tmp_path):
    cfg = _cfg(tmp_path, digest={"title": "R&D <weekly>"})
    dg = _dg([_item()])
    assert digest.digest_values(dg, cfg, html=False)["title"] == "R&D <weekly>"
    assert digest.digest_values(dg, cfg, html=True)["title"] == "R&amp;D &lt;weekly&gt;"


def test_digest_values_body_is_markup_on_the_html_path_and_plain_otherwise(tmp_path):
    cfg = _cfg(tmp_path)
    dg = _dg([_item(title="a thing")])
    html_body = digest.digest_values(dg, cfg, html=True)["body"]
    text_body = digest.digest_values(dg, cfg, html=False)["body"]
    assert "<h2" in html_body and "&lt;h2" not in html_body, (
        "the body must not be double-escaped"
    )
    assert "<h2" not in text_body and "a thing" in text_body


def test_recipient_values_escape_a_hostile_display_name_on_the_html_path():
    person = {
        "email": "jc@box",
        "name": "<img src=x>",
        "state": digest.STATE_SUBSCRIBED,
    }
    mail = {"from": "digest@box"}
    assert digest.recipient_values(person, mail, html=False)["name"] == "<img src=x>"
    assert (
        digest.recipient_values(person, mail, html=True)["name"] == "&lt;img src=x&gt;"
    )


def test_recipient_values_fall_back_to_the_local_part_and_name_the_unsubscribe_route():
    values = digest.recipient_values(
        {"email": "jc@box", "name": "", "state": digest.STATE_SUBSCRIBED},
        {"from": "digest@box"},
        html=False,
    )
    assert values["name"] == "jc"
    assert "digest@box" in values["unsubscribe"] and "jc@box" in values["unsubscribe"]
    assert "http" not in values["unsubscribe"], (
        "unsubscribing must not need a web request"
    )


# ---- the no-tracking audit ---------------------------------------------------


def test_this_adapters_own_html_loads_nothing_remote():
    hostile = _dg(
        [
            _item(
                title='<img src="https://track.example/o.gif">',
                body="x",
                link="https://ok/1",
            ),
            _item(title="second", body='<script src="https://evil/x.js"></script>'),
        ]
    )
    assert digest.tracking_findings(digest.render_html(hostile)) == []


def test_a_pasted_tracking_pixel_is_found_and_located():
    found = digest.tracking_findings(
        '<p>hi</p><img src="https://track.example/o.gif?u=1" width="1">'
    )
    assert len(found) == 1
    assert found[0] == {
        "tag": "img",
        "attr": "src",
        "url": "https://track.example/o.gif?u=1",
    }


def test_the_audit_covers_every_auto_loading_shape_this_family_cares_about():
    html = """
    <link rel="stylesheet" href="https://cdn/x.css">
    <iframe src="//protocol.relative/frame"></iframe>
    <body background="http://old/bg.gif">
    <td style="background-image:url('https://css/pixel.png')"></td>
    <style>div { background: url(https://in-style/px.gif); }</style>
    <video poster="https://v/p.jpg" src="https://v/v.mp4"></video>
    <img srcset="https://s/1x.png 1x, https://s/2x.png 2x">
    """
    urls = {f["url"] for f in digest.tracking_findings(html)}
    assert urls == {
        "https://cdn/x.css",
        "//protocol.relative/frame",
        "http://old/bg.gif",
        "https://css/pixel.png",
        "https://in-style/px.gif",
        "https://v/p.jpg",
        "https://v/v.mp4",
        "https://s/1x.png",
        "https://s/2x.png",
    }
    assert {f["tag"] for f in digest.tracking_findings(html)} >= {
        "link",
        "iframe",
        "body",
        "td",
        "style",
        "video",
        "img",
    }


def test_the_audit_does_not_cry_wolf_on_a_link_or_a_local_or_data_resource():
    clean = (
        '<a href="https://arxiv.org/abs/1">a link the reader chooses</a>'
        '<img src="cid:embedded"><img src="data:image/gif;base64,R0lGOD">'
        '<img src="/local/logo.png"><a href="mailto:jc@box">unsub</a>'
    )
    assert digest.tracking_findings(clean) == []


def test_tracking_findings_are_sorted_so_the_report_diffs_clean():
    html = '<img src="https://b/2.gif"><img src="https://a/1.gif"><script src="https://a/0.js"></script>'
    found = digest.tracking_findings(html)
    assert [f["url"] for f in found] == [
        "https://a/1.gif",
        "https://b/2.gif",
        "https://a/0.js",
    ]


# ---- the message -------------------------------------------------------------


def _msg(**over):
    kwargs = {
        "sender": "digest@jcamd.com",
        "sender_name": "Dottie",
        "recipient": "jc@box",
        "subject": "Weekly",
        "text": "plain body",
        "html": "<p>html body</p>",
        "date_ts": T0,
        "msg_id": "<a@b>",
    }
    kwargs.update(over)
    return digest.build_message(**kwargs)


def test_build_message_puts_plain_before_html_so_clients_prefer_the_html():
    parts = _msg().get_payload()
    assert [p.get_content_type() for p in parts] == ["text/plain", "text/html"]
    assert parts[0].get_payload(decode=True).decode("utf-8") == "plain body"
    assert parts[1].get_payload(decode=True).decode("utf-8") == "<p>html body</p>"


def test_build_message_addresses_exactly_one_person_and_carries_no_bcc():
    msg = _msg()
    assert msg["To"] == "jc@box" and msg["Cc"] is None and msg["Bcc"] is None
    assert msg["From"] == "Dottie <digest@jcamd.com>"
    assert msg["Message-ID"] == "<a@b>"
    assert msg["Auto-Submitted"] == "auto-generated"
    assert msg["List-Unsubscribe"] == "<mailto:digest@jcamd.com?subject=unsubscribe>"
    assert msg.get_content_type() == "multipart/alternative"


def test_build_message_dates_in_gmt_so_the_local_zone_never_leaks():
    msg = _msg(date_ts=T0)
    assert parsedate_to_datetime(msg["Date"]).timestamp() == T0
    assert msg["Date"].endswith("GMT"), (
        "usegmt=True is what keeps the host TZ out of the header"
    )


def test_build_message_survives_a_non_ascii_subject_through_the_wire():
    subject = "Résumé — 5.54404 → 5.60506"
    parsed = email.message_from_bytes(_msg(subject=subject).as_bytes())
    assert str(make_header(decode_header(parsed["Subject"]))) == subject
    assert "Résumé" not in parsed["Subject"], (
        "the header must be RFC 2047 encoded on the wire"
    )


def test_build_message_refuses_a_header_with_a_newline_in_it():
    # NUL is pinned separately from CR/LF because it is a SEPARATE branch of the
    # same guard: safe_header screens "\r\n\0", and this test previously covered
    # only \n and \r\n, so narrowing the guard to "\r\n" survived the whole suite.
    # safe_header's own docstring promises "Reject CR/LF/NUL", and NUL is the one
    # a template can carry from ledger text without looking like a newline.
    # Each of the three characters needs a BARE case. "D\r\nX: y" does NOT test \r:
    # it contains an LF, so the guard still catches it with \r removed — which is how
    # a mutation dropping only CR survived this test even after the \x00 cases were
    # added. One guard, three characters, three isolated cases.
    for field, value in (
        ("subject", "Weekly\nBcc: evil@x"),
        ("sender_name", "D\r\nX: y"),
        ("subject", "Weekly\rBcc: evil@x"),
        ("sender_name", "D\rX: y"),
        ("subject", "Weekly\x00Bcc: evil@x"),
        ("sender_name", "D\x00X: y"),
    ):
        with pytest.raises(digest.DigestError) as e:
            _msg(**{field: value})
        assert e.value.rule == digest.ERR_HEADER_INJECTION
    assert digest.safe_header("fine") == "fine"


def test_build_message_refuses_to_forge_a_from_or_mail_a_bad_address():
    with pytest.raises(digest.DigestError) as e:
        _msg(sender="not an address")
    assert e.value.rule == digest.ERR_NO_SENDER
    with pytest.raises(digest.DigestError) as e:
        _msg(recipient="jc box@x")
    assert e.value.rule == digest.ERR_BAD_ADDRESS


def test_message_id_is_deterministic_per_campaign_and_recipient():
    a = digest.message_id("cafe1234", "jc@box", "digest@jcamd.com")
    assert a == digest.message_id("cafe1234", "jc@box", "digest@jcamd.com")
    assert a != digest.message_id("cafe1234", "other@box", "digest@jcamd.com")
    assert a != digest.message_id("beef5678", "jc@box", "digest@jcamd.com")
    assert a.startswith("<digest.cafe1234.") and a.endswith("@jcamd.com>")


# ---- delivery ----------------------------------------------------------------


class _Relay:
    """The injected egress boundary. Records; never opens a socket."""

    def __init__(self, ok: bool = True, detail: str = "delivered"):
        self.ok, self.detail, self.sent = ok, detail, []

    def __call__(self, msg, recipient):
        self.sent.append((recipient, msg))
        return self.ok, self.detail


def test_deliver_refuses_to_invent_a_sender_or_a_recipient(tmp_path):
    dg = _dg([_item()])
    with pytest.raises(digest.DigestError) as e:
        digest.deliver(dg, _cfg(tmp_path, mail={"from": None}))
    assert e.value.rule == digest.ERR_NO_SENDER
    with pytest.raises(digest.DigestError) as e:
        digest.deliver(dg, _cfg(tmp_path, recipients=[]))
    assert e.value.rule == digest.ERR_NO_RECIPIENTS
    with pytest.raises(digest.DigestError) as e:
        digest.deliver(
            dg, _cfg(tmp_path, recipients=[{"email": "x@box", "state": "unsubscribed"}])
        )
    assert e.value.rule == digest.ERR_NO_RECIPIENTS


def test_deliver_refuses_a_send_with_no_relay_configured(tmp_path):
    with pytest.raises(digest.DigestError) as e:
        digest.deliver(
            _dg([_item()]),
            _cfg(tmp_path, mail={"host": None}),
            send=True,
            send_fn=_Relay(),
        )
    assert e.value.rule == digest.ERR_NO_RELAY


def test_deliver_refuses_an_empty_issue_unless_told_otherwise(tmp_path):
    empty = _dg([])
    with pytest.raises(digest.DigestError) as e:
        digest.deliver(empty, _cfg(tmp_path))
    assert e.value.rule == digest.ERR_EMPTY
    out = digest.deliver(
        empty, _cfg(tmp_path, digest={"send_when_empty": True}), now=T0
    )
    assert out["totals"]["recipients"] == 1


def test_every_refusal_fires_identically_on_the_dry_run_path(tmp_path):
    """A rehearsal that skipped a check would not be a rehearsal."""
    for over, rule in [
        ({"mail": {"from": None}}, digest.ERR_NO_SENDER),
        ({"recipients": []}, digest.ERR_NO_RECIPIENTS),
    ]:
        cfg = _cfg(tmp_path, **over)
        for send in (False, True):
            with pytest.raises(digest.DigestError) as e:
                digest.deliver(_dg([_item()]), cfg, send=send, send_fn=_Relay())
            assert e.value.rule == rule, (over, send)


def test_a_dry_run_opens_nothing_and_records_nothing(tmp_path):
    relay, recorded = _Relay(), []
    out = digest.deliver(
        _dg([_item()]),
        _cfg(tmp_path),
        send=False,
        send_fn=relay,
        record_fn=recorded.append,
        now=T0,
    )
    assert relay.sent == [] and recorded == []
    assert out["dry_run"] is True
    row = out["results"][0]
    assert row["status"] == digest.STATUS_DRY_RUN and "not sent" in row["detail"]
    assert row["bytes"] > 0, "the rehearsal still builds the real message"


def test_the_dry_run_builds_the_same_bytes_the_real_send_would(tmp_path):
    cfg = _cfg(tmp_path)
    dg = _dg([_item(title="x")])
    dry = digest.deliver(dg, cfg, send=False, now=T0)
    relay = _Relay()
    wet = digest.deliver(dg, cfg, send=True, send_fn=relay, now=T0)
    assert dry["results"][0]["bytes"] == wet["results"][0]["bytes"]
    assert dry["results"][0]["message_id"] == wet["results"][0]["message_id"]
    assert len(relay.sent[0][1].as_bytes()) == dry["results"][0]["bytes"]


def test_deliver_sends_one_message_per_person_each_addressed_only_to_them(tmp_path):
    cfg = _cfg(
        tmp_path, recipients=[{"email": "a@box", "name": "A"}, {"email": "b@box"}]
    )
    relay = _Relay()
    out = digest.deliver(_dg([_item()]), cfg, send=True, send_fn=relay, now=T0)
    assert [r for r, _ in relay.sent] == ["a@box", "b@box"]
    tos = [m["To"] for _, m in relay.sent]
    assert tos == ["a@box", "b@box"], "a shared To: would publish the roster to itself"
    ids = {r["message_id"] for r in out["results"]}
    assert len(ids) == 2
    bodies = [
        m.get_payload()[0].get_payload(decode=True).decode("utf-8")
        for _, m in relay.sent
    ]
    assert "Hello A." in bodies[0] and "Hello b." in bodies[1]
    assert out["totals"][digest.STATUS_SENT] == 2


def test_a_relay_failure_is_a_failed_row_not_a_crash(tmp_path):
    relay = _Relay(ok=False, detail="ConnectionRefusedError: nope")
    recorded = []
    out = digest.deliver(
        _dg([_item()]),
        _cfg(tmp_path),
        send=True,
        send_fn=relay,
        record_fn=recorded.append,
        now=T0,
    )
    row = out["results"][0]
    assert (
        row["status"] == digest.STATUS_FAILED
        and row["detail"] == "ConnectionRefusedError: nope"
    )
    assert out["totals"][digest.STATUS_FAILED] == 1
    assert len(recorded) == 1, "a failure must be recorded so it can be seen"


def test_deliver_will_not_pretend_to_send_without_an_egress_callable(tmp_path):
    with pytest.raises(ValueError, match="send_fn"):
        digest.deliver(_dg([_item()]), _cfg(tmp_path), send=True, send_fn=None)


def test_an_already_sent_campaign_is_skipped_and_force_overrides_it(tmp_path):
    cfg = _cfg(tmp_path)
    dg = _dg([_item()])
    relay = _Relay()
    asked: list[tuple] = []

    def lookup(campaign, email):
        asked.append((campaign, email))
        return True

    out = digest.deliver(dg, cfg, send=True, send_fn=relay, sent_lookup=lookup, now=T0)
    assert out["results"][0]["status"] == digest.STATUS_DUPLICATE
    assert relay.sent == [] and asked == [(dg["campaign_id"], "jc@box")]
    forced = digest.deliver(
        dg, cfg, send=True, send_fn=relay, sent_lookup=lookup, force=True, now=T0
    )
    assert forced["results"][0]["status"] == digest.STATUS_SENT and len(relay.sent) == 1


def test_deliver_reports_the_skipped_roster_entries_alongside_the_sends(tmp_path):
    cfg = _cfg(
        tmp_path,
        recipients=[
            {"email": "a@box"},
            {"email": "old@box", "state": "bounced"},
            {"email": "junk"},
        ],
    )
    out = digest.deliver(_dg([_item()]), cfg, now=T0)
    assert out["totals"]["recipients"] == 1 and out["totals"]["skipped"] == 2
    assert {s["reason"] for s in out["skipped"]} == {
        digest.ERR_UNSUBSCRIBED,
        digest.ERR_BAD_ADDRESS,
    }


def test_deliver_surfaces_a_beacon_and_an_unresolved_tag_per_recipient(tmp_path):
    cfg = _cfg(tmp_path)
    out = digest.deliver(
        _dg([_item()]),
        cfg,
        now=T0,
        template_text="{{body}} {{typo}}",
        template_html='<img src="https://track/o.gif">{{body}}',
    )
    row = out["results"][0]
    assert row["unresolved"] == ["typo"]
    assert [h["url"] for h in row["tracking"]] == ["https://track/o.gif"]


# ---- the send ledger ---------------------------------------------------------


def _ledger():
    return digest.open_ledger(":memory:")


def test_only_a_successful_send_suppresses_the_next_one():
    c = _ledger()
    row = {
        "email": "jc@box",
        "status": digest.STATUS_FAILED,
        "detail": "relay down",
        "subject": "s",
        "message_id": "<m>",
    }
    digest.record_send(c, "cafe", row, ts=T0)
    assert digest.already_sent(c, "cafe", "jc@box") is False, (
        "a failure must retry next pass"
    )
    digest.record_send(c, "cafe", {**row, "status": digest.STATUS_SENT}, ts=T0 + 1)
    assert digest.already_sent(c, "cafe", "jc@box") is True
    assert digest.SENT_STATUSES == (digest.STATUS_SENT,)


def test_the_repeat_guard_is_scoped_to_this_campaign_and_this_address():
    c = _ledger()
    digest.record_send(
        c,
        "cafe",
        {
            "email": "jc@box",
            "status": digest.STATUS_SENT,
            "detail": "d",
            "subject": "s",
            "message_id": "<m>",
        },
        ts=T0,
    )
    assert digest.already_sent(c, "cafe", "jc@box") is True
    assert digest.already_sent(c, "cafe", "other@box") is False
    assert digest.already_sent(c, "beef", "jc@box") is False


def test_a_retry_replaces_the_earlier_outcome_rather_than_duplicating_it():
    c = _ledger()
    for status in (digest.STATUS_FAILED, digest.STATUS_SENT):
        digest.record_send(
            c,
            "cafe",
            {
                "email": "jc@box",
                "status": status,
                "detail": status,
                "subject": "s",
                "message_id": "<m>",
            },
            ts=T0,
        )
    rows = digest.history(c)
    assert len(rows) == 1 and rows[0]["status"] == digest.STATUS_SENT


def test_history_is_newest_first_with_a_readable_stamp():
    c = _ledger()
    for i, who in enumerate(["a@box", "b@box", "c@box"]):
        digest.record_send(
            c,
            "cafe",
            {
                "email": who,
                "status": digest.STATUS_SENT,
                "detail": "d",
                "subject": "s",
                "message_id": f"<{i}>",
            },
            ts=T0 + i,
        )
    rows = digest.history(c, limit=2)
    assert [r["recipient"] for r in rows] == ["c@box", "b@box"]
    assert rows[0]["when"] == feeds.fmt_ts(T0 + 2)


def test_the_ledger_lives_in_its_own_file_not_on_a_monitored_one():
    assert digest.DB_REL != uptime.DB_REL and digest.DB_REL.parent.name == ".scout"
    c = _ledger()
    tables = {
        r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert tables == {"sends", "meta"}
    assert (
        c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        == digest.SCHEMA_VERSION
    )


# ---- diagnostics -------------------------------------------------------------


def test_diagnostics_grade_a_schema_drift_above_a_missing_ledger(tmp_path):
    drift = _dg([], error="entries has no column(s) ['message']")
    by_rule = {d["rule"]: d for d in digest.to_diagnostics(drift)}
    assert by_rule[digest.ERR_SCHEMA_DRIFT]["severity"] == "error"
    missing = _dg([], error="ledger not found")
    missing["sections"][0]["error_rule"] = digest.ERR_SOURCE_UNREADABLE
    by_rule = {d["rule"]: d for d in digest.to_diagnostics(missing)}
    assert by_rule[digest.ERR_SOURCE_UNREADABLE]["severity"] == "warning"


def test_diagnostics_report_undated_rows_and_an_empty_issue():
    diags = digest.to_diagnostics(_dg([_item()], undated=3))
    undated = next(d for d in diags if d["rule"] == digest.ERR_UNDATED)
    assert undated["severity"] == "info" and "3 row(s)" in undated["message"]
    empty = digest.to_diagnostics(_dg([]))
    assert (
        next(d for d in empty if d["rule"] == digest.ERR_EMPTY)["severity"]
        == "suggestion"
    )
    assert digest.ERR_EMPTY not in [d["rule"] for d in diags]


def test_delivery_diagnostics_gate_a_failure_a_beacon_and_a_typo_as_errors(tmp_path):
    result = {
        "results": [
            {
                "email": "jc@box",
                "status": digest.STATUS_FAILED,
                "detail": "relay down",
                "unresolved": ["nmae"],
                "tracking": [{"tag": "img", "attr": "src", "url": "https://t/o.gif"}],
            }
        ],
        "skipped": [
            {"email": "junk", "reason": digest.ERR_BAD_ADDRESS, "detail": "bad"},
            {"email": "old@box", "reason": digest.ERR_UNSUBSCRIBED, "detail": "state"},
        ],
    }
    diags = digest.to_diagnostics(_dg([_item()]), result)
    sev = {d["rule"]: d["severity"] for d in diags}
    assert sev[digest.ERR_UNDELIVERABLE] == "error"
    assert sev[digest.ERR_TRACKING] == "error"
    assert sev[digest.ERR_UNRESOLVED_TAG] == "error"
    assert sev[digest.ERR_BAD_ADDRESS] == "warning"
    assert sev[digest.ERR_UNSUBSCRIBED] == "info"
    assert openswap.summarize(diags)["by_severity"]["error"] == 3


def test_a_clean_pass_emits_no_diagnostics(tmp_path):
    relay = _Relay()
    dg = _dg([_item()])
    result = digest.deliver(dg, _cfg(tmp_path), send=True, send_fn=relay, now=T0)
    assert digest.to_diagnostics(dg, result) == []


def test_diagnostics_are_sorted_for_a_clean_diff():
    result = {
        "results": [
            {
                "email": "z@box",
                "status": digest.STATUS_FAILED,
                "detail": "x",
                "unresolved": [],
                "tracking": [],
            },
            {
                "email": "a@box",
                "status": digest.STATUS_FAILED,
                "detail": "x",
                "unresolved": [],
                "tracking": [],
            },
        ],
        "skipped": [],
    }
    diags = digest.to_diagnostics(_dg([_item()]), result)
    assert [d["path"] for d in diags] == sorted(d["path"] for d in diags)


# ---- the plugin: policy, manifest, egress -----------------------------------


def _plugin_dir() -> Path:
    return ROOT / "bigbang" / "plugins" / "digest"


def _cli_mod():
    from bigbang.plugins.digest import cli

    return cli


def test_the_manifest_denies_the_saas_it_replaces():
    from bigbang.core.policy import check_permission, load_manifest

    manifest = load_manifest(_plugin_dir())
    assert manifest["name"] == "digest"
    for esp in ("smtp.mailchimp.com", "smtp.sendgrid.net", "smtp.mailgun.org"):
        allowed, reason = check_permission(manifest, "network", esp)
        assert allowed is False and esp in reason, esp
    allowed, _ = check_permission(manifest, "network", "127.0.0.1")
    assert allowed is True, "a loopback relay is the intended default"


def test_the_manifest_allows_exactly_one_secret_and_only_the_scout_dir():
    from bigbang.core.policy import check_permission, load_manifest

    manifest = load_manifest(_plugin_dir())
    assert manifest["capabilities"]["secrets"]["allow"] == [
        "SCOUT_DIGEST_SMTP_PASSWORD"
    ]
    assert check_permission(manifest, "secret", "AWS_SECRET_ACCESS_KEY")[0] is False
    assert check_permission(manifest, "secret", "SCOUT_DIGEST_SMTP_PASSWORD")[0] is True
    assert check_permission(manifest, "fs_write", ".scout/digest.db")[0] is True


def test_the_core_imports_nothing_outside_the_stdlib():
    tree = ast.parse(
        (ROOT / "bigbang" / "core" / "digest.py").read_text(encoding="utf-8")
    )
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level:
            roots.add((node.module or "").split(".")[0])
    assert roots, "the AST walk must actually find imports"
    assert roots <= set(sys.stdlib_module_names) | {"bigbang"}, sorted(
        roots - set(sys.stdlib_module_names)
    )


def _fake_smtp(box, *, explode=None):
    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host, self.port, self.timeout = host, port, timeout
            self.starttls_called, self.login_args, self.sent = False, None, []
            box.append(self)
            if explode:
                raise explode

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def starttls(self):
            self.starttls_called = True

        def login(self, user, password):
            self.login_args = (user, password)

        def send_message(self, msg):
            self.sent.append(msg)

    return FakeSMTP


def _mail(**over) -> dict:
    base = {
        "host": "127.0.0.1",
        "port": 25,
        "timeout_s": 10.0,
        "starttls": False,
        "user": None,
        "password_env": None,
    }
    base.update(over)
    return base


def test_the_only_egress_hands_the_message_to_the_relay(monkeypatch):
    cli = _cli_mod()
    box = []
    monkeypatch.setattr(cli.smtplib, "SMTP", _fake_smtp(box))
    ok, detail = cli._send_message(_mail(), _msg(), "jc@box")
    assert ok is True and detail == "smtp 127.0.0.1:25 -> jc@box"
    assert (box[0].host, box[0].port, box[0].timeout) == ("127.0.0.1", 25, 10.0)
    assert box[0].sent[0]["To"] == "jc@box"
    assert box[0].starttls_called is False and box[0].login_args is None


def test_a_relay_outside_the_manifest_never_opens_a_socket(monkeypatch):
    cli = _cli_mod()
    box = []
    monkeypatch.setattr(cli.smtplib, "SMTP", _fake_smtp(box))
    ok, detail = cli._send_message(_mail(host="smtp.mailchimp.com"), _msg(), "jc@box")
    assert ok is False and detail.startswith("policy denied:")
    assert box == [], "a denied relay must be refused before the connection"


def test_a_secret_outside_the_manifest_is_never_read(monkeypatch):
    cli = _cli_mod()
    box = []
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-never-be-read")
    monkeypatch.setattr(cli.smtplib, "SMTP", _fake_smtp(box))
    ok, detail = cli._send_message(
        # S106: an env var NAME, not a secret — the point is that it is never read
        _mail(user="scout", password_env="AWS_SECRET_ACCESS_KEY"),  # noqa: S106
        _msg(),
        "jc@box",
    )
    assert ok is False and "AWS_SECRET_ACCESS_KEY" in detail
    assert box == []


def test_an_allowlisted_secret_is_used_for_starttls_login_and_never_echoed(monkeypatch):
    cli = _cli_mod()
    box = []
    monkeypatch.setenv("SCOUT_DIGEST_SMTP_PASSWORD", "hunter2")
    monkeypatch.setattr(cli.smtplib, "SMTP", _fake_smtp(box))
    ok, detail = cli._send_message(
        # S106: an env var NAME; the value comes from the environment below
        _mail(starttls=True, user="scout", password_env="SCOUT_DIGEST_SMTP_PASSWORD"),  # noqa: S106
        _msg(),
        "jc@box",
    )
    assert ok is True and box[0].starttls_called is True
    assert box[0].login_args == ("scout", "hunter2")
    assert "hunter2" not in detail
    assert "hunter2" not in box[0].sent[0].as_string()


def test_a_dead_relay_is_a_failed_delivery_not_a_traceback(monkeypatch):
    cli = _cli_mod()
    monkeypatch.setattr(
        cli.smtplib, "SMTP", _fake_smtp([], explode=TimeoutError("relay down"))
    )
    ok, detail = cli._send_message(_mail(), _msg(), "jc@box")
    assert ok is False and "TimeoutError: relay down" in detail


def test_the_ledgers_it_reads_are_opened_read_only_by_sqlite_itself(tmp_path):
    cli = _cli_mod()
    scout = _real_ledgers(tmp_path)
    conn, error = cli._open_reader(str(scout / "logs.db"))
    assert error is None and conn is not None
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 2
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("DELETE FROM entries")
    assert "mode=ro" in cli._ro_uri(scout / "logs.db")


def test_a_missing_ledger_comes_back_as_a_reason(tmp_path):
    cli = _cli_mod()
    conn, error = cli._open_reader(str(tmp_path / "nope.db"))
    assert conn is None and "nothing has written it yet" in error


def test_a_corrupt_ledger_costs_one_section_not_the_whole_digest(tmp_path):
    """sqlite validates the file header on first READ, not at connect, so
    _open_reader hands back a live connection for a junk file and the failure
    lands inside read_section. It must be caught there."""
    cli = _cli_mod()
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not sqlite" * 100)
    conn, error = cli._open_reader(str(junk))
    assert conn is not None and error is None, "the header check really is deferred"
    spec = _spec(db=str(junk), table="entries", cols={"ts": "ts", "title": "message"})
    dg = digest.assemble(cli._open_reader, {"s": spec})
    section = dg["sections"][0]
    assert (
        section["count"] is None
        and section["error_rule"] == digest.ERR_SOURCE_UNREADABLE
    )
    assert "DatabaseError" in section["error"]
    assert dg["totals"]["sections_failed"] == 1


# ---- the real CLI in a subprocess -------------------------------------------


def _run(args, cwd=None):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(cwd or ROOT),
        env=env,
    )


def _scenario(tmp_path: Path, **over) -> Path:
    # stamped against the real clock: the CLI windows against time.time()
    _real_ledgers(tmp_path, base=time.time())
    body = {
        "mail": {
            "from": "digest@jcamd.com",
            "from_name": "Dottie",
            "host": "127.0.0.1",
            "port": 25,
        },
        "digest": {"title": "Dottie weekly"},
        "recipients": [
            {"email": "jc@jcamd.com", "name": "JC"},
            {"email": "old@jcamd.com", "state": "unsubscribed"},
        ],
    }
    for k, v in over.items():
        body[k] = {**body.get(k, {}), **v} if isinstance(v, dict) else v
    p = tmp_path / "digest.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def test_cli_hello_envelope():
    r = _run(["digest", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["plugin"] == "digest"
    assert data["data"]["sections"] == sorted(digest.DEFAULT_SECTIONS)


def test_cli_detect_reports_fallback_and_proves_the_esp_is_denied():
    r = _run(["digest", "detect"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["tier"] == "fallback" and data["delegates"] is False
    assert data["policy"]["esp_allowed"] is False
    assert "not in allowlist" in data["policy"]["esp_reason"]
    assert set(data["extras"]) == {"msmtp", "sendmail", "mutt"}


def test_cli_config_names_every_blocker_on_a_fresh_box():
    r = _run(["digest", "config"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["ready"] is False
    assert data["blockers"] == [
        digest.ERR_NO_SENDER,
        digest.ERR_NO_RELAY,
        digest.ERR_NO_RECIPIENTS,
    ]
    assert data["recipients"]["mailable"] == []


def test_cli_config_is_ready_once_configured(tmp_path):
    cfg = _scenario(tmp_path)
    r = _run(["digest", "config", "--config", str(cfg)], cwd=tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["ready"] is True and data["blockers"] == []
    assert data["recipients"]["mailable"] == ["jc@jcamd.com"]
    assert data["recipients"]["skipped"][0]["reason"] == digest.ERR_UNSUBSCRIBED


def test_cli_preview_renders_the_real_ledgers_without_a_sender(tmp_path):
    _real_ledgers(tmp_path, base=time.time())
    r = _run(["digest", "preview", "--days", "1", "--html"], cwd=tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["totals"]["items"] == 4 and data["empty"] is False
    assert "CUDA OOM" in data["text"] and "dumbmodel.com" in data["text"]
    used = set(digest.TAG_RE.findall(digest.TEMPLATE_TEXT))
    used |= set(digest.TAG_RE.findall(digest.TEMPLATE_HTML))
    expected = sorted(used & set(digest.RECIPIENT_TAGS))
    assert expected and data["pending_tags"] == expected
    assert "resolve per recipient" in data["pending_note"]
    assert data["tracking"] == {"clean": True, "remote_resources": []}
    assert "<h2" in data["html"]
    assert all("items" not in s for s in data["sections"])


def test_cli_preview_gates_on_a_missing_ledger(tmp_path):
    r = _run(["digest", "preview", "--fail-on", "warning"], cwd=tmp_path)
    assert r.returncode == 1, "four absent ledgers must trip a warning gate"
    data = json.loads(r.stdout)["data"]
    rules = {d["rule"] for d in data["diagnostics"]}
    assert rules == {digest.ERR_SOURCE_UNREADABLE, digest.ERR_EMPTY}
    assert data["summary"]["by_severity"]["warning"] == 4


def test_cli_preview_rejects_a_bad_fail_on(tmp_path):
    r = _run(["digest", "preview", "--fail-on", "catastrophe"], cwd=tmp_path)
    assert r.returncode == 1
    assert "--fail-on must be one of" in json.loads(r.stdout)["error"]


def test_cli_send_defaults_to_a_dry_run_that_writes_no_ledger(tmp_path):
    cfg = _scenario(tmp_path)
    r = _run(["digest", "send", "--config", str(cfg)], cwd=tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["dry_run"] is True
    assert data["results"][0]["status"] == digest.STATUS_DRY_RUN
    assert data["results"][0]["bytes"] > 1000
    assert not (tmp_path / ".scout" / "digest.db").exists(), (
        "a rehearsal writes nothing"
    )
    assert data["ledger"]["state"].startswith("absent")


def test_cli_send_is_reproducible_across_runs(tmp_path):
    cfg = _scenario(tmp_path)
    ids = []
    for _ in range(2):
        r = _run(["digest", "send", "--config", str(cfg)], cwd=tmp_path)
        assert r.returncode == 0, r.stderr + r.stdout
        ids.append(json.loads(r.stdout)["data"]["campaign_id"])
    assert ids[0] == ids[1], "a moving window must not mint a new campaign"


def test_cli_send_refuses_an_unconfigured_sender_and_roster_by_name(tmp_path):
    for over, rule in [
        ({"mail": {"from": None}}, digest.ERR_NO_SENDER),
        ({"recipients": []}, digest.ERR_NO_RECIPIENTS),
    ]:
        cfg = _scenario(tmp_path, **over)
        r = _run(["digest", "send", "--config", str(cfg)], cwd=tmp_path)
        assert r.returncode == 1, r.stdout
        assert json.loads(r.stdout)["error"].startswith(rule)


def test_cli_send_refuses_a_section_with_sql_in_its_table_name(tmp_path):
    cfg = _scenario(
        tmp_path,
        sections={
            "evil": {
                "db": ".scout/logs.db",
                "table": "entries; DROP TABLE entries",
                "cols": {"ts": "ts", "title": "message"},
            }
        },
    )
    r = _run(["digest", "send", "--config", str(cfg)], cwd=tmp_path)
    assert r.returncode == 1
    error = json.loads(r.stdout)["error"]
    assert error.startswith(digest.ERR_BAD_IDENTIFIER)
    assert "DROP TABLE" in error, "the refusal must quote the value it rejected"
    assert "evil" in error, "and name the section it came from"


def test_cli_send_refuses_an_empty_issue(tmp_path):
    cfg = _scenario(tmp_path)
    r = _run(["digest", "send", "--config", str(cfg), "--days", "0.0001"], cwd=tmp_path)
    assert r.returncode == 1
    assert json.loads(r.stdout)["error"].startswith(digest.ERR_EMPTY)


def test_cli_status_on_a_box_that_has_never_sent(tmp_path):
    r = _run(["digest", "status"], cwd=tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["sends"] == [] and data["count"] == 0
    assert data["state"].startswith("absent")
    assert data["counts_toward_repeat_guard"] == [digest.STATUS_SENT]
    assert not (tmp_path / ".scout" / "digest.db").exists()
