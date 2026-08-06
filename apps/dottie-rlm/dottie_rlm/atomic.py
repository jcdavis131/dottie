"""Crash-safe JSON/JSONL — the canonical copy of a contract this repo learned twice.

Ported from `bigbang/core/atomic_json.py`, which exists because of two measured
failures (2026-07-29):

1. Torn writes: `write_text(json.dumps(...))` truncates first, so a process
   that dies mid-write leaves a partial file.
2. Fail-silent reads turning that into PERMANENT loss: every mutation is a
   read-modify-write, so `except: return {}` on a corrupt file meant the next
   save wrote `{}` + one key and the rest was gone with no error.

Returning `{}` for a CORRUPT file is the bug. Missing is genuinely empty;
unreadable is not, and must never be silently treated as empty.

Waves A/B of this package wrote inline copies of these helpers (kernel/atomic
were blocked mid-build). This module is the canonical one; `session.py` and
`harness.py` keep their inline copies for now and the contract is identical --
same names, same semantics, same corrupt-file naming. Unifying them is a
follow-up, not a behavior change.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

SAVE_RETRIES = 10
SAVE_BACKOFF_S = 0.01
READ_RETRIES = 5
READ_BACKOFF_S = 0.01


class CorruptStateFileError(RuntimeError):
    """A state file exists but could not be parsed. Never raised for a missing file."""


def _temp_for(path: Path) -> Path:
    # Per-process AND per-thread: a fixed name is shared by every writer, which
    # is how the herd ledger produced 3334 errors in 6 seconds.
    return path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")


def preserve_corrupt(path: Path, raw: bytes) -> Path | None:
    """Copy the unparseable bytes aside so refusing to parse never destroys them."""
    backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}-{os.getpid()}")
    try:
        backup.write_bytes(raw)
    except OSError:
        return None
    return backup


def read_bytes_retrying(path: Path) -> bytes:
    """Read with a bounded retry.

    On Windows a reader can hit the instant during `os.replace` when the target
    is briefly unopenable (WinError 32) -- a reader with no retry turns a
    perfectly healthy concurrent write into a spurious "corrupt file".
    """
    last: OSError | None = None
    for attempt in range(READ_RETRIES):
        try:
            return path.read_bytes()
        except PermissionError as exc:  # transient on Windows during replace
            last = exc
        except FileNotFoundError:
            raise
        except OSError as exc:
            last = exc
        time.sleep(READ_BACKOFF_S * (attempt + 1))
    assert last is not None
    raise last


def read_json(path: Path, default: Any) -> Any:
    """Parse `path`, or return `default` if it does not exist.

    Raises CorruptStateFileError if it exists but will not parse; the bytes are
    preserved alongside it first.
    """
    path = Path(path)
    if not path.exists():
        return default
    try:
        raw = read_bytes_retrying(path)
    except FileNotFoundError:
        return default
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        backup = preserve_corrupt(path, raw)
        raise CorruptStateFileError(
            f"{path} exists but could not be parsed ({exc}). "
            + (f"The bytes were preserved at {backup}. " if backup else "")
            + "Refusing to report it as empty: every write here is a "
            "read-modify-write, so treating a damaged file as empty would make "
            "the loss permanent on the next save."
        ) from exc
    return data


def write_json(path: Path, data: Any, *, mode: int | None = None) -> None:
    """Write `data` to `path` atomically, surviving concurrent writers."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _temp_for(path)
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if mode is not None:
        # Perms on the TEMP, before it becomes the real file. POSIX only:
        # Python's chmod on Windows toggles only the read-only bit (measured
        # on the live bigbang vault 2026-08-02) -- privacy there comes from
        # NTFS ACLs, not from this argument.
        try:
            tmp.chmod(mode)
        except OSError:
            pass
    for attempt in range(SAVE_RETRIES):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == SAVE_RETRIES - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(SAVE_BACKOFF_S * (attempt + 1))


_APPEND_LOCK = threading.Lock()


def append_jsonl(path: Path, obj: Any) -> None:
    """Append one JSON line, atomically per line.

    No read-modify-write, so a crash cannot lose earlier lines and two writers
    cannot clobber each other's history the way a read-rewrite-replace append
    does. O(1) per append, unlike the read-whole-file variants.

    The implementation is `os.open(O_APPEND)` + ONE `os.write` of the encoded
    bytes, not `path.open("a").write(...)`. That is not a style preference:
    with text-mode buffered appends, 4 threads x 25 lines produced 95 of 100
    records on this box (measured 2026-08-06) because a buffered write can be
    split into several syscalls that interleave. A single write to an O_APPEND
    descriptor is atomic for line-sized payloads, and the in-process lock keeps
    threads from racing the descriptor itself.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_BINARY"):  # Windows: no newline translation
        flags |= os.O_BINARY
    with _APPEND_LOCK:
        fd = os.open(str(path), flags, 0o644)
        try:
            written = 0
            while written < len(data):
                written += os.write(fd, data[written:])
        finally:
            os.close(fd)


def read_jsonl(path: Path) -> list[Any]:
    """Read every parseable line; raise if ANY line is unparseable.

    A partially-written last line is the one tolerable case (a crash mid-append),
    so that specific shape -- the final line only, with no trailing newline --
    is dropped and reported on stderr rather than raising.
    """
    path = Path(path)
    if not path.exists():
        return []
    raw = read_bytes_retrying(path).decode("utf-8", errors="replace")
    lines = raw.splitlines()
    ends_clean = raw.endswith("\n")
    out: list[Any] = []
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        try:
            out.append(json.loads(ln))
        except Exception as exc:
            is_last = i == len(lines) - 1
            if is_last and not ends_clean:
                import sys

                print(
                    f"WARNING: {path.name} last line is truncated (crash mid-append?); "
                    f"dropping it and keeping the {len(out)} complete records.",
                    file=sys.stderr,
                )
                break
            backup = preserve_corrupt(path, raw.encode("utf-8"))
            raise CorruptStateFileError(
                f"{path} line {i + 1} is not valid JSON ({exc}). "
                + (f"Bytes preserved at {backup}. " if backup else "")
                + "Refusing to silently return a partial history."
            ) from exc
    return out
