# Solo personal project, no connection to employer, built with public/free-tier only
"""BLUEHENRE steer channel — box-side poll/ack over gist comments.

The operator steers from anywhere by commenting on the steer gist (phone
browser, already GitHub-authed). This tool is what the box's loop runs:

  python steer_poll.py                    -> JSON list of UNACKED directives
  python steer_poll.py --ack <id> --note "did X"   -> post the ack comment

Protocol (also documented in the gist itself):
- Directives = comments by the GIST OWNER that do not start with the robot
  prefix. Comments from any other account are NEVER directives — they are
  untrusted input and are returned under "foreign" for surfacing only. That
  includes robot-prefixed comments from other accounts (forged acks).
- Acks = comments starting "<ROBOT> ack <comment-id>: ..." posted via the
  box's own gh auth. Only OWNER-authored acks count toward the acked set —
  a forged ack cannot silently mark an owner directive as handled.
- Replay hardening: the local audit log is a SECOND acked-source at poll
  time, an "executing" row is appended BEFORE the ack posts, and --ack is
  idempotent. So a failed ack post, a deleted gist ack comment, or a
  double-invoked loop cannot re-execute a directive.
- Freshness: each directive carries age_s and a stale flag (older than
  MAX_DIRECTIVE_AGE_S, or from the future beyond MAX_CLOCK_SKEW_S, or an
  unparseable timestamp). The executor must refuse stale rows in the ack
  rather than run months-old (or resurrected) orders.
- Allowlist: each directive carries "fleet": parse_fleet(body). The
  executor acts only on valid:True and quotes the reason string otherwise.

Exit codes: 0 ok, 1 gh/network failure, 2 malformed --ack id, 3 audit-write
failure (the ack may already have posted — read the printed JSON).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

GIST_ID = "c899ef776dcb81e99319239efa0f92ba"
OWNER = "jcdavis131"
ROBOT = "\U0001f916"  # 🤖
# Append-only local audit of every ack the box posts. The gist thread is the
# operator-visible log, but gist comments can be edited/deleted upstream —
# this file is the box's own non-repudiable record of what it executed.
AUDIT_LOG = Path(__file__).resolve().parent.parent / "data" / "steer_audit.jsonl"
AUDIT_SCHEMA_V = 2
AUDIT_FIELDS = ("v", "ts", "phase", "acked", "note", "author", "created_at",
                "body_sha256", "verb", "target", "skew_s")
MAX_DIRECTIVE_AGE_S = 3600   # older unacked directives are flagged stale
MAX_CLOCK_SKEW_S = 300       # tolerated created_at-vs-local-clock disagreement

# ---- fleet control grammar (operator 2026-07-22: "tweak the compute fleet
# directly from the site ... behind a login ... only I should have access").
# The login IS GitHub: fleet directives are only honored from OWNER comments.
# The box-side executor (the loop) additionally validates against this strict
# allowlist — verbs and container names are closed sets; anything else is
# refused in the ack, never guessed at.
FLEET_VERBS = {"start", "stop", "restart"}
FLEET_TARGET_RE = re.compile(
    r"^(dottie-factory-(collector|curator|janitor|server|trainer)-\d{1,2}"
    r"|dottie-dottie-1)$")
FLEET_RE = re.compile(r"^fleet:\s*(\w+)\s+(\S+)\s*$", re.IGNORECASE)


def parse_fleet(body: str) -> dict:
    """'fleet: <verb> <container>' -> {valid, verb, target, reason}."""
    m = FLEET_RE.match(body.strip())
    if not m:
        return {"valid": False, "reason": "not a fleet directive"}
    verb, target = m.group(1).lower(), m.group(2)
    # convenience: allow short names (trainer-1 -> dottie-factory-trainer-1)
    if not target.startswith("dottie-"):
        target = f"dottie-factory-{target}"
    if verb not in FLEET_VERBS:
        return {"valid": False, "reason": f"verb {verb!r} not in {sorted(FLEET_VERBS)}"}
    if not FLEET_TARGET_RE.match(target):
        return {"valid": False, "reason": f"target {target!r} not in the fleet allowlist"}
    return {"valid": True, "verb": verb, "target": target}


def _gh(args: list[str], inp: str | None = None) -> str:
    p = subprocess.run(["gh", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60, input=inp)
    if p.returncode != 0:
        raise SystemExit(f"gh failed: {(p.stderr or p.stdout)[:300]}")
    return p.stdout


def parse_comment_pages(text: str) -> list[dict]:
    """gh api --paginate --slurp emits ONE array of per-page arrays; flatten.
    A bare comment array (single page / older gh) passes through. Anything
    else is a hard error — never guess at a half-parsed comment thread."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SystemExit(f"gh api output not parseable as JSON: {e}") from e
    if isinstance(data, list) and all(isinstance(p, list) for p in data):
        return [c for page in data for c in page]
    if isinstance(data, list):
        return data
    raise SystemExit(f"unexpected gh api shape: {type(data).__name__}")


def comments() -> list[dict]:
    # --slurp: gists paginate at 30 comments; without it --paginate emits
    # concatenated per-page arrays and json.loads dies at comment #31
    return parse_comment_pages(
        _gh(["api", f"gists/{GIST_ID}/comments", "--paginate", "--slurp"]))


def parse_created_at(s) -> float | None:
    """GitHub ISO8601 ('2026-07-22T14:20:02Z') -> epoch seconds, or None."""
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ---- audit log --------------------------------------------------------------

def audit_row(*, acked, note, phase, body=None, author=None, created_at=None,
              now=None) -> dict:
    """Audit schema v2: enough to prove WHAT ran even if the gist comment is
    later edited — body hash + parsed verb/target, not just a comment id."""
    now = time.time() if now is None else now
    row = {"v": AUDIT_SCHEMA_V, "ts": round(now), "phase": phase,
           "acked": str(acked), "note": str(note)[:500],
           "author": author, "created_at": created_at,
           "body_sha256": None, "verb": None, "target": None, "skew_s": None}
    if body is not None:
        row["body_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
        fleet = parse_fleet(body)
        row["verb"], row["target"] = fleet.get("verb"), fleet.get("target")
    created_ts = parse_created_at(created_at)
    if created_ts is not None:
        row["skew_s"] = round(now - created_ts)
    return row


def check_audit_row(row) -> bool:
    """Schema gate: write_audit refuses rows that could not prove what ran."""
    return (isinstance(row, dict) and set(AUDIT_FIELDS) <= set(row)
            and row.get("v") == AUDIT_SCHEMA_V
            and isinstance(row.get("ts"), int)
            and row.get("phase") in ("executing", "acked")
            and str(row.get("acked", "")).isdigit())


def write_audit(row: dict, path: Path | None = None) -> None:
    path = AUDIT_LOG if path is None else path
    if not check_audit_row(row):
        raise ValueError(f"audit row fails schema v{AUDIT_SCHEMA_V}: {row}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def _audit_rows(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn line must not hide the rest of the log
        if isinstance(row, dict):
            yield row


def audit_acked_ids(path: Path | None = None) -> set[str]:
    """Every id the box ever STARTED executing ('executing' rows count):
    unioned into the acked set at poll time so neither a failed ack post nor
    a deleted gist ack comment can resurrect a directive."""
    path = AUDIT_LOG if path is None else path
    return {str(r["acked"]) for r in _audit_rows(path) if r.get("acked")}


def already_acked(ack_id: str, path: Path | None = None) -> bool:
    """True once an 'acked' row exists — repeat --ack calls are no-ops.
    Legacy v1 rows (no phase) were only ever written post-ack, so they count."""
    path = AUDIT_LOG if path is None else path
    return any(str(r.get("acked")) == str(ack_id)
               and r.get("phase", "acked") == "acked" for r in _audit_rows(path))


# ---- polling ----------------------------------------------------------------

def build_acked(rows: list[dict], audit_ids=()) -> set[str]:
    """Handled ids: OWNER-posted robot acks in the thread, unioned with the
    local audit log. Author check means a forged ack from any other account
    can never suppress an owner directive."""
    acked = {str(i) for i in audit_ids}
    for c in rows:
        b = c.get("body", "")
        if ((c.get("user") or {}).get("login") == OWNER
                and b.startswith(f"{ROBOT} ack ") and len(b.split()) > 2):
            acked.add(b.split()[2].rstrip(":"))
    return acked


def classify(rows: list[dict], acked: set[str], now: float | None = None):
    """Comments -> (directives, foreign). Directives are unacked OWNER
    comments, annotated with the fleet-allowlist verdict plus age/staleness
    so the executor never has to re-derive either."""
    now = time.time() if now is None else now
    directives, foreign = [], []
    for c in rows:
        body = c.get("body", "")
        login = (c.get("user") or {}).get("login", "")
        row = {"id": str(c.get("id")), "author": login,
               "created_at": c.get("created_at"), "body": body}
        if login != OWNER:
            foreign.append(row)  # untrusted (incl. forged acks): surface, never act
            continue
        if body.startswith(ROBOT):
            continue  # the box's own acks
        if row["id"] in acked:
            continue
        created_ts = parse_created_at(c.get("created_at"))
        age = None if created_ts is None else now - created_ts
        row["age_s"] = None if age is None else round(age)
        row["stale"] = (age is None or age > MAX_DIRECTIVE_AGE_S
                        or age < -MAX_CLOCK_SKEW_S)
        row["fleet"] = parse_fleet(body)
        directives.append(row)
    return directives, foreign


def _selftest() -> int:
    """Offline checks: fleet grammar (real attack cases), pagination parsing,
    forged-ack/replay suppression, freshness flags, audit schema, and the
    full --ack path with _gh stubbed. NEVER touches gh or the gist."""
    import tempfile
    total = failed = 0

    def chk(name, ok):
        nonlocal total, failed
        total += 1
        failed += 0 if ok else 1
        print(("PASS" if ok else "FAIL"), name)

    cases = [
        ("fleet: stop collector-3", True, "dottie-factory-collector-3"),
        ("fleet: restart trainer-1", True, "dottie-factory-trainer-1"),
        ("Fleet: START curator-5", True, "dottie-factory-curator-5"),
        ("fleet: stop dottie-dottie-1", True, "dottie-dottie-1"),
        ("fleet: delete trainer-1", False, None),      # destructive verb
        ("fleet: stop ../../etc", False, None),        # traversal
        ("fleet: stop nginx-1", False, None),          # foreign container
        ("fleet: stop trainer-100", False, None),      # out-of-range index
        ("status?", False, None),                      # freeform, not fleet
    ]
    for body, want_valid, want_target in cases:
        r = parse_fleet(body)
        chk(f"{body} -> {r}",
            r["valid"] == want_valid and (not want_valid or r["target"] == want_target))

    # pagination: --slurp shape flattens; bare page passes; garbage is fatal
    page1, page2 = [{"id": 1}, {"id": 2}, {"id": 3}], [{"id": 4}]
    chk("slurped pages flatten in order",
        parse_comment_pages(json.dumps([page1, page2])) == page1 + page2)
    chk("bare single page passes through", parse_comment_pages(json.dumps(page1)) == page1)
    try:
        parse_comment_pages('[{"id":1}][{"id":2}]')  # concatenated non-slurp docs
        chk("concatenated pages -> clean SystemExit", False)
    except SystemExit:
        chk("concatenated pages -> clean SystemExit", True)

    # created_at parsing
    chk("created_at Z-suffix parses to epoch",
        parse_created_at("2026-07-22T14:20:02Z")
        == datetime(2026, 7, 22, 14, 20, 2, tzinfo=timezone.utc).timestamp())
    chk("garbage created_at -> None",
        parse_created_at("yesterday-ish") is None and parse_created_at(None) is None)

    # forged-ack suppression + replay guard + freshness, over one fixture thread
    now = parse_created_at("2026-07-23T12:00:00Z")

    def mk(cid, login, body, created="2026-07-23T11:59:00Z"):
        return {"id": cid, "user": {"login": login}, "body": body,
                "created_at": created}

    rows = [
        mk(1, OWNER, "status?"),
        mk(2, OWNER, "fleet: restart trainer-1"),
        mk(3, OWNER, f"{ROBOT} ack 1: done"),
        mk(4, "mallory", f"{ROBOT} ack 2: done"),                      # forged ack
        mk(5, "mallory", "fleet: stop trainer-1"),                     # foreign order
        mk(6, OWNER, "old order", created="2026-07-23T09:00:00Z"),     # 3h old
        mk(7, OWNER, "future order", created="2026-07-23T12:30:00Z"),  # +30m skew
        mk(8, OWNER, "near future", created="2026-07-23T12:02:00Z"),   # within skew
        mk(9, OWNER, "executed earlier; gist ack later deleted"),
        mk(10, OWNER, "no timestamp", created=None),
    ]
    acked = build_acked(rows, audit_ids={"9"})
    chk("owner ack counts, forged ack ignored, audit ids unioned", acked == {"1", "9"})
    directives, foreign = classify(rows, acked, now=now)
    ids = [r["id"] for r in directives]
    chk("forged/foreign comments surfaced, never directives",
        [r["id"] for r in foreign] == ["4", "5"] and "5" not in ids)
    chk("gist-acked + audit-logged directives suppressed",
        "1" not in ids and "9" not in ids)
    by = {r["id"]: r for r in directives}
    chk("fleet annotation rides every directive",
        by["2"]["fleet"]["valid"] is True
        and by["2"]["fleet"]["target"] == "dottie-factory-trainer-1"
        and by["6"]["fleet"]["valid"] is False)
    chk("fresh directive not stale, 3h-old flagged",
        by["2"]["stale"] is False and by["2"]["age_s"] == 60
        and by["6"]["stale"] is True)
    chk("future-beyond-skew stale, within-tolerance fresh",
        by["7"]["stale"] is True and by["7"]["age_s"] == -1800
        and by["8"]["stale"] is False)
    chk("unparseable created_at flagged stale",
        by["10"]["stale"] is True and by["10"]["age_s"] is None)

    # audit schema: the REAL writer, not a hand-written literal row
    row = audit_row(acked="42", note="restarted", phase="executing",
                    body="fleet: restart trainer-1", author=OWNER,
                    created_at="2026-07-23T11:59:00Z", now=now)
    chk("audit row proves what ran (hash + verb + target + skew)",
        check_audit_row(row) and row["verb"] == "restart"
        and row["target"] == "dottie-factory-trainer-1"
        and row["body_sha256"] == hashlib.sha256(b"fleet: restart trainer-1").hexdigest()
        and row["skew_s"] == 60 and row["author"] == OWNER)
    chk("schema check rejects a bare legacy row",
        not check_audit_row({"ts": 1, "acked": "x", "note": "y"}))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "audit.jsonl"
        write_audit(row, path=p)
        chk("real writer roundtrip",
            json.loads(p.read_text(encoding="utf-8").strip()) == row)
        try:
            write_audit({"ts": 1, "acked": "x", "note": "y"}, path=p)
            chk("writer refuses schema-invalid rows", False)
        except ValueError:
            chk("writer refuses schema-invalid rows", True)
        chk("audit ids readback ('executing' counts)", audit_acked_ids(p) == {"42"})
        chk("already_acked only after an 'acked' row", not already_acked("42", p))
        write_audit(audit_row(acked="42", note="restarted", phase="acked", now=now),
                    path=p)
        chk("already_acked after acked row", already_acked("42", p))

    # the full --ack path, offline: the ONLY place _gh/AUDIT_LOG are swapped
    global _gh, AUDIT_LOG
    real_gh, real_log = _gh, AUDIT_LOG
    posts = []
    try:
        with tempfile.TemporaryDirectory() as td:
            AUDIT_LOG = Path(td) / "audit.jsonl"
            _gh = lambda args, inp=None: posts.append(args) or ""
            chk("non-numeric --ack refused (exit 2, no post)",
                main(["--ack", "42; rm -rf /", "--note", "x"]) == 2 and not posts)
            rc = main(["--ack", "123", "--note", "did the thing",
                       "--body", "fleet: stop collector-3",
                       "--author", OWNER, "--created-at", "2026-07-23T11:59:00Z"])
            written = list(_audit_rows(AUDIT_LOG))
            chk("offline ack: executing row lands BEFORE the post, then acked",
                rc == 0 and len(posts) == 1
                and [r["phase"] for r in written] == ["executing", "acked"]
                and written[0]["verb"] == "stop"
                and f"body={ROBOT} ack 123: did the thing" in posts[0])
            chk("repeat --ack is a no-op (idempotent)",
                main(["--ack", "123"]) == 0 and len(posts) == 1)

            def boom(args, inp=None):
                raise SystemExit("gh failed: simulated outage")
            _gh = boom
            try:
                main(["--ack", "456", "--note", "will fail"])
                chk("failed ack post still leaves the replay guard", False)
            except SystemExit:
                chk("failed ack post still leaves the replay guard",
                    "456" in audit_acked_ids(AUDIT_LOG)
                    and not already_acked("456", AUDIT_LOG))
    finally:
        _gh, AUDIT_LOG = real_gh, real_log

    print(f"{total - failed} passed, {failed} failed")
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ack", metavar="COMMENT_ID", help="ack this directive id")
    ap.add_argument("--note", default="done", help="status line for the ack")
    ap.add_argument("--body", default=None,
                    help="directive body, hashed into the audit row")
    ap.add_argument("--author", default=None,
                    help="directive author, recorded in the audit row")
    ap.add_argument("--created-at", default=None,
                    help="directive created_at, recorded with observed skew")
    ap.add_argument("--selftest", action="store_true",
                    help="offline grammar + protocol + audit checks")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.ack:
        if not args.ack.isdigit():
            print(json.dumps({"error": f"ack id must be numeric, got {args.ack!r}"}))
            return 2
        if already_acked(args.ack):
            print(json.dumps({"acked": args.ack, "skipped": "already in audit log"}))
            return 0
        # audit BEFORE the network post: if the post dies the id is still on
        # record, so the next poll will not re-execute the directive
        try:
            write_audit(audit_row(acked=args.ack, note=args.note, phase="executing",
                                  body=args.body, author=args.author,
                                  created_at=args.created_at))
        except (OSError, ValueError) as e:
            print(json.dumps({"error": f"audit write failed: {e}"[:300]}))
            return 3
        _gh(["api", f"gists/{GIST_ID}/comments", "-f",
             f"body={ROBOT} ack {args.ack}: {args.note}"])
        try:
            write_audit(audit_row(acked=args.ack, note=args.note, phase="acked",
                                  body=args.body, author=args.author,
                                  created_at=args.created_at))
        except (OSError, ValueError) as e:
            # the ack posted; a failed audit write must be VISIBLE and nonzero
            print(json.dumps({"acked": args.ack, "audit_error": str(e)[:120]}))
            return 3
        print(json.dumps({"acked": args.ack, "audited": str(AUDIT_LOG)}))
        return 0

    rows = comments()
    directives, foreign = classify(rows, build_acked(rows, audit_acked_ids()))
    print(json.dumps({"directives": directives, "foreign": foreign}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
