# Solo personal project, no connection to employer, built with public/free-tier only
"""Read the research daemon's run.log correctly.

    apps/dottie> .venv/Scripts/python.exe scripts/run_log.py            # last 15 records
    apps/dottie> .venv/Scripts/python.exe scripts/run_log.py --since-boot
    apps/dottie> .venv/Scripts/python.exe scripts/run_log.py --durations implement

Three things about this file break ad-hoc one-liners, and all three bit me on 2026-07-20:

1. **It is UTF-16.** `open()` with the default encoding yields spaced-out garbage.
2. **Not every line is JSON.** torch UserWarnings and PowerShell `NativeCommandError`
   wrappers land here too. They carry no timestamp.
3. **Because they carry no timestamp, filtering by `ts >= boot` silently keeps ALL of
   them, from the whole file.** That made 2 post-boot lines look like 2,047 and briefly
   convinced me my own residual-stream probe was flooding the log. Scope by POSITION
   relative to the last `boot` record, never by timestamp.

The daemon prints a `boot` record with `git_sha` and `prompts_sha256` at start (TODOS
§5.3.R9), so "which code produced this?" is answerable from the log rather than from
process-creation times that vanish when the process dies.
"""

from __future__ import annotations

import argparse
import datetime
import json
import statistics
from pathlib import Path
from typing import Any

DEFAULT = Path(__file__).resolve().parents[1] / "data" / "research" / "logs" / "run.log"


def read_lines(path: Path) -> list[str]:
    raw = path.read_bytes()
    for enc in ("utf-16", "utf-8"):
        try:
            return [ln for ln in raw.decode(enc).splitlines() if ln.strip()]
        except UnicodeDecodeError:
            continue
    return [ln for ln in raw.decode("utf-8", "replace").splitlines() if ln.strip()]


def parse(lines: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """(json records, non-json noise) — preserving order within each."""
    records: list[dict[str, Any]] = []
    noise: list[str] = []
    for ln in lines:
        if ln.lstrip().startswith("{"):
            try:
                records.append(json.loads(ln))
                continue
            except json.JSONDecodeError:
                pass
        noise.append(ln)
    return records, noise


def since_boot(lines: list[str]) -> list[str]:
    """Lines from the LAST boot record onward, by position — not by timestamp."""
    idx = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("{"):
            try:
                if json.loads(ln).get("action") == "boot":
                    idx = i
            except json.JSONDecodeError:
                pass
    return lines if idx is None else lines[idx:]


def fmt(rec: dict[str, Any]) -> str:
    ts = datetime.datetime.fromtimestamp(rec["ts"]).strftime("%H:%M:%S")
    result = json.dumps(rec.get("result", "")) if rec.get("result") else ""
    dur = f" dur={rec['dur_s']}s" if rec.get("dur_s") else ""
    phase = f" {rec['phase']}" if rec.get("phase") else ""
    return f"{ts} {rec.get('action', '?')}{phase} {result[:90]}{dur}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", type=Path, default=DEFAULT)
    ap.add_argument("--since-boot", action="store_true")
    ap.add_argument("--durations", metavar="ACTION")
    ap.add_argument("-n", type=int, default=15)
    args = ap.parse_args()

    lines = read_lines(args.path)
    scoped = since_boot(lines) if args.since_boot else lines
    records, noise = parse(scoped)

    if args.durations:
        durs = [
            r["dur_s"]
            for r in records
            if r.get("action") == args.durations and r.get("dur_s")
        ]
        if not durs:
            print(f"no completed {args.durations!r} records in scope")
            return 0
        print(
            f"{args.durations}: n={len(durs)}  min={min(durs):.0f}s  "
            f"median={statistics.median(durs):.0f}s  max={max(durs):.0f}s"
        )
        return 0

    boot = next((r for r in records if r.get("action") == "boot"), None)
    if boot:
        print(
            f"boot: pid={boot.get('pid')} git_sha={boot.get('git_sha')} "
            f"prompts={boot.get('prompts_sha256')} "
            f"at {datetime.datetime.fromtimestamp(boot['ts']):%H:%M:%S}"
        )
    print(
        f"scope: {len(records)} records, {len(noise)} non-JSON lines "
        f"({'since last boot' if args.since_boot else 'whole file'})"
    )
    for r in records[-args.n :]:
        print("  " + fmt(r))
    if records:
        last = records[-1]
        idle = (datetime.datetime.now().timestamp() - last["ts"]) / 60
        if not last.get("dur_s"):
            print(f"  -> in progress {idle:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
