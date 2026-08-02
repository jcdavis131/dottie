"""Crash-safe JSON for the small shared state files bigbang keeps under $HOME.

Two failures this exists to prevent, both measured on 2026-07-29:

1. **Torn writes.** `security.py` and `registry.py` wrote with
   `FILE.write_text(json.dumps(...))`, which truncates first. A process that dies
   between truncate and write leaves a partial file.

2. **Fail-silent reads turning that into PERMANENT loss.** Both `_load()`s caught
   every exception and returned empty. Since every mutation is a read-modify-write,
   the next `set_secret` read `{}`, added one key, and wrote it back -- so ONE torn
   write plus ONE ordinary write destroyed the whole vault with no error:

       vault before      : ['AWS', 'HF_TOKEN', 'OPENAI_KEY']
       after torn write  : []            <- swallowed
       after next set    : ['NEW_KEY']   <- loss made permanent

   Returning `{}` for a CORRUPT file is the bug. Missing is genuinely empty;
   unreadable is not, and must never be silently treated as empty.

The write path mirrors the fix made to the herd ledger in 0ae2dc6: a per-process
temp name, because a fixed one is shared by every concurrent writer, plus a
bounded retry on the replace (atomic everywhere, but fails on Windows with
WinError 32 when the TARGET is open, and readers open these files constantly).
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

_SAVE_RETRIES = 10
_SAVE_BACKOFF_S = 0.01


class CorruptStateFileError(RuntimeError):
    """A state file exists but could not be parsed. Never raised for a missing file."""


def read_json(path: Path, default: Any) -> Any:
    """Parse `path`, or return `default` if it does not exist.

    Raises CorruptStateFileError if it exists but will not parse. The corrupt bytes are
    preserved alongside it first -- refusing to parse must not also mean refusing
    to keep the only copy of whatever survived.
    """
    if not path.exists():
        return default
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        try:
            backup.write_bytes(raw)
        except OSError:  # pragma: no cover - best effort; the raise is the point
            backup = None
        raise CorruptStateFileError(
            f"{path} exists but could not be parsed ({exc}). "
            + (f"The bytes were preserved at {backup}. " if backup else "")
            + "Refusing to report it as empty: every write here is a "
            "read-modify-write, so treating a damaged file as {} would make the "
            "loss permanent on the next save."
        ) from exc
    if not isinstance(data, dict):
        raise CorruptStateFileError(f"{path} does not contain a JSON object: {type(data)}")
    return data


def write_json(path: Path, data: Any, *, mode: int | None = None) -> None:
    """Write `data` to `path` atomically, surviving concurrent writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if mode is not None:
        # Set perms on the TEMP, before it becomes the real file. Doing it after
        # the replace leaves a window where the secrets vault is world-readable.
        #
        # POSIX ONLY. On Windows this call succeeds and changes nothing that matters —
        # Python's chmod there toggles only the read-only bit, so group/other bits are
        # untouched. Measured on the live vault 2026-08-02:
        #
        #     mode after write   0o666
        #     chmod(0o600)       before 0o666 -> after 0o666
        #     icacls             SYSTEM, Administrators, owner only (inherited)
        #
        # The file is still private on Windows, by NTFS ACLs inherited from the user
        # profile — but not because of this line. Callers that treat `mode=` as the
        # security mechanism (security.py's vault, auth/cli.py's registry) are relying on
        # something that is a no-op on half the platforms this runs on, and both now say so
        # at their call sites. Hardening further on Windows means ACLs, not a mode argument.
        #
        # The except is not a swallow: chmod legitimately fails on filesystems without
        # permission bits, and failing the whole write for that would be worse than the
        # already-documented limitation.
        try:
            tmp.chmod(mode)
        except OSError:
            pass
    for attempt in range(_SAVE_RETRIES):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == _SAVE_RETRIES - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(_SAVE_BACKOFF_S * (attempt + 1))
