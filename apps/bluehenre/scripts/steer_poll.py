# Solo personal project, no connection to employer, built with public/free-tier only
"""BLUEHENRE steer channel — box-side poll/ack over gist comments.

The operator steers from anywhere by commenting on the steer gist (phone
browser, already GitHub-authed). This tool is what the box's loop runs:

  python steer_poll.py                    -> JSON list of UNACKED directives
  python steer_poll.py --ack <id> --note "did X"   -> post the ack comment

Protocol (also documented in the gist itself):
- Directives = comments by the GIST OWNER that do not start with the robot
  prefix. Comments from any other account are NEVER directives — they are
  untrusted input and are returned under "foreign" for surfacing only.
- Acks = comments starting "<ROBOT> ack <comment-id>: ..." posted via the
  box's own gh auth. A directive is "acked" once such a comment exists, so
  the protocol is stateless — no local bookkeeping to lose.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

GIST_ID = "c899ef776dcb81e99319239efa0f92ba"
OWNER = "jcdavis131"
ROBOT = "\U0001f916"  # 🤖
# Append-only local audit of every ack the box posts. The gist thread is the
# operator-visible log, but gist comments can be edited/deleted upstream —
# this file is the box's own non-repudiable record of what it executed.
AUDIT_LOG = Path(__file__).resolve().parent.parent / "data" / "steer_audit.jsonl"

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


def comments() -> list[dict]:
    return json.loads(_gh(["api", f"gists/{GIST_ID}/comments", "--paginate"]))


def _selftest() -> int:
    """Offline checks: fleet grammar (real attack cases) + audit append."""
    import tempfile
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
    failed = 0
    for body, want_valid, want_target in cases:
        r = parse_fleet(body)
        ok = r["valid"] == want_valid and (not want_valid or r["target"] == want_target)
        failed += 0 if ok else 1
        print(("PASS" if ok else "FAIL"), body, "->", r)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "audit.jsonl"
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": 1, "acked": "x", "note": "y"}) + "\n")
        row = json.loads(p.read_text(encoding="utf-8").strip())
        ok = row == {"ts": 1, "acked": "x", "note": "y"}
        failed += 0 if ok else 1
        print(("PASS" if ok else "FAIL"), "audit append/readback")
    print(f"{len(cases) + 1 - failed} passed, {failed} failed")
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ack", metavar="COMMENT_ID", help="ack this directive id")
    ap.add_argument("--note", default="done", help="status line for the ack")
    ap.add_argument("--selftest", action="store_true", help="offline grammar + audit checks")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.ack:
        body = f"{ROBOT} ack {args.ack}: {args.note}"
        _gh(["api", f"gists/{GIST_ID}/comments", "-f", f"body={body}"])
        try:
            AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with AUDIT_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": round(time.time()), "acked": args.ack,
                                    "note": args.note[:500]}) + "\n")
        except OSError as e:
            # the ack posted; a failed audit write must be VISIBLE, not silent
            print(json.dumps({"acked": args.ack, "audit_error": str(e)[:120]}))
            return 0
        print(json.dumps({"acked": args.ack, "audited": str(AUDIT_LOG)}))
        return 0

    rows = comments()
    acked = {b.split()[2].rstrip(":") for c in rows
             if (b := c.get("body", "")).startswith(f"{ROBOT} ack ") and len(b.split()) > 2}
    directives = []
    foreign = []
    for c in rows:
        body = c.get("body", "")
        login = (c.get("user") or {}).get("login", "")
        if body.startswith(ROBOT):
            continue
        row = {"id": str(c["id"]), "author": login,
               "created_at": c.get("created_at"), "body": body}
        if login != OWNER:
            foreign.append(row)  # untrusted: surface, never act
        elif str(c["id"]) not in acked:
            directives.append(row)
    print(json.dumps({"directives": directives, "foreign": foreign}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
