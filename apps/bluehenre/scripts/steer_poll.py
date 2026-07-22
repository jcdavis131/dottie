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
import subprocess
import sys

GIST_ID = "c899ef776dcb81e99319239efa0f92ba"
OWNER = "jcdavis131"
ROBOT = "\U0001f916"  # 🤖


def _gh(args: list[str], inp: str | None = None) -> str:
    p = subprocess.run(["gh", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60, input=inp)
    if p.returncode != 0:
        raise SystemExit(f"gh failed: {(p.stderr or p.stdout)[:300]}")
    return p.stdout


def comments() -> list[dict]:
    return json.loads(_gh(["api", f"gists/{GIST_ID}/comments", "--paginate"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ack", metavar="COMMENT_ID", help="ack this directive id")
    ap.add_argument("--note", default="done", help="status line for the ack")
    args = ap.parse_args(argv)

    if args.ack:
        body = f"{ROBOT} ack {args.ack}: {args.note}"
        _gh(["api", f"gists/{GIST_ID}/comments", "-f", f"body={body}"])
        print(json.dumps({"acked": args.ack}))
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
