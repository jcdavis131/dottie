"""Audit trail — every invocation logged, security first"""

import json
from datetime import UTC, datetime
from pathlib import Path

AUDIT_DIR = Path.home() / ".local" / "share" / "bigbang"
AUDIT_FILE = AUDIT_DIR / "audit.jsonl"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def log_event(command: str, args: dict, status: str = "ok", duration_ms: int = 0):
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "command": command,
        "args": args,
        "status": status,
        "duration_ms": duration_ms,
    }
    # Tolerate only I/O failures (read-only FS, missing home). Anything else —
    # e.g. unserializable args — is a programming error and must be loud.
    try:
        with AUDIT_FILE.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        pass


_TAIL_CHUNK = 64 * 1024


def _read_last_lines(path: Path, n: int) -> list[str]:
    """The last n lines, reading only the tail rather than the whole file.

    `read_text().split("\\n")[-n:]` pulled the ENTIRE log into memory to return a handful
    of records. Measured 2026-08-01 on the real file: 41.4 MB, 28,778 entries,
    `tail_events(20)` cost 154 ms and allocated the whole file as one str plus a list of
    28,778 more. That cost is linear in a file that only ever grows, and `bb ... status`
    pays it to show five events.

    Reads 64 KB chunks backwards until it has n+1 newlines, so cost is bounded by what is
    actually returned. The first line in the buffer may be a partial record — that is fine
    and deliberate, because the `[-n:]` slice discards it once enough newlines are present.
    """
    with path.open("rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        buf = b""
        while pos > 0 and buf.count(b"\n") <= n:
            step = min(_TAIL_CHUNK, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + buf
    text = buf.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    # rstrip("\r") per line, because this reads BYTES while the previous implementation
    # used read_text(), whose text mode silently strips \r on Windows. Without this the
    # two disagree on every CRLF record — caught by diffing the new tail against the old
    # whole-file slice, which came back False on a change that was only meant to be faster.
    # The real log has MIXED endings (some records \r\n, some \n), so this is not
    # hypothetical.
    #
    # split("\n") + rstrip rather than splitlines(): splitlines() also breaks on \v, \f,
    # \x1c-\x1e and  / , any of which appearing raw inside a record would split
    # one entry into two and silently manufacture a corrupt line.
    return [ln.rstrip("\r") for ln in text.split("\n")][-n:]


def tail_events(n: int = 20, *, return_stats: bool = False):
    """Recent audit records, newest last.

    `return_stats=False` keeps the original contract exactly — a list of dicts — because
    cockpit.py and system/cli.py index into it.

    UNPARSABLE LINES ARE COUNTED, not silently dropped. The old body was
    `except Exception: pass`, so a corrupt record vanished with no trace. The real log has
    three of them (lines 6200, 8344, 13516 as of 2026-08-01): each is an orphaned TAIL of a
    record whose head is gone, while the preceding line parses fine and ends normally. That
    is what concurrent appends look like — `log_event` opens with "a" and writes with no
    lock, so two processes can overwrite each other's partial content.

    Three bad records in 28,778 is a 0.01% rate, which is exactly why it went unnoticed: an
    audit trail that silently discards what it cannot parse reports a clean history whether
    or not it has one. Counting them does not fix the write path — that needs locking, and
    it touches every CLI invocation, so it is deliberately left as a separate decision —
    but it stops the loss from being invisible.
    """
    if not AUDIT_FILE.exists():
        return ([], {"read": 0, "skipped": 0}) if return_stats else []
    lines = _read_last_lines(AUDIT_FILE, n)
    out, skipped = [], 0
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            skipped += 1
    if return_stats:
        return out, {"read": len(lines), "skipped": skipped}
    return out
