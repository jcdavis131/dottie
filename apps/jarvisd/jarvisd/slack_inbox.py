"""Slack inbox drain: file-polled ingress from the #agent-ops watcher.

The live poller (`~/workspace/slack/poll.py`) queues human channel messages as
JSON files in an inbox dir. This module is the other half of the v1
done-criterion — "a goal typed in Slack is a goal in the daemon" — for
deployments where Slack cannot reach the daemon's HTTP doorway, or where the
operator prefers a poll loop to an open port. The HTTP doorway lives in
`jarvisd.slack`; this module never touches the network.

FAIL-CLOSED. Every item is validated before it can become a goal, and anything
that fails validation is quarantined — moved out of the inbox with its reason
stamped into the file — never silently dropped and never turned into a goal:

  - unreadable file / not a JSON object -> quarantine
  - unknown `kind`                       -> quarantine (only known inbox kinds pass)
  - missing / non-string `ts`            -> quarantine (`ts` is the dedupe key)
  - empty text after cleaning           -> quarantine (an empty goal is a lie)
  - `ts` already seen                    -> skip (a redelivery must not open a
                                            second goal for the same message)

Dedupe state is a JSON file of seen Slack `ts` ids, defaulting to
`<inbox>/../state/slack_inbox_seen.json` (the poller's own `state/` dir when the
inbox is `~/workspace/slack/inbox/`). Successfully opened items are moved to
`<inbox>/_done/`. `dry_run=True` changes nothing — no goals, no state writes, no
file moves — and reports what *would* happen.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "KNOWN_KINDS",
    "MAX_SEEN",
    "SlackInboxError",
    "clean_text",
    "drain",
    "default_state_path",
]

#: Inbox item kinds we know how to read. Anything else is quarantined, not guessed.
KNOWN_KINDS = frozenset({"channel_message", "app_mention", "im", "slash"})

#: Cap on remembered `ts` ids. Dicts keep insertion order, so eviction is FIFO:
#: this is a doorway, not an archive.
MAX_SEEN = 5000

#: Open-goal callable shape, mirroring `Jarvis.goal`: (agent, repo, text) -> {"ok": bool, ...}.
OpenGoal = Callable[[str, str, str], dict[str, Any]]

_LEADING_TOKEN = re.compile(r"^(?:<@[^>]+>|<![^>]+>)\s*")


class SlackInboxError(Exception):
    """The drain itself cannot run safely (e.g. corrupt dedupe state)."""


def default_state_path(inbox_dir: str | os.PathLike[str]) -> Path:
    """Where dedupe state lives when the caller does not say otherwise."""
    return Path(inbox_dir).parent / "state" / "slack_inbox_seen.json"


def clean_text(value: Any) -> str:
    """Strip leading `<@U123>` / `<!channel>` tokens so a mention is not the goal."""
    if not isinstance(value, str):
        return ""
    out = value
    while True:
        stripped = _LEADING_TOKEN.sub("", out)
        if stripped == out:
            break
        out = stripped
    return out.strip()


def _load_seen(state_path: Path) -> dict[str, dict[str, Any]]:
    """ts -> provenance. A corrupt file is a hard stop, not a fresh start.

    Starting over on a corrupt file would re-open every goal the file had already
    recorded. Refusing loudly is cheaper than de-duplicating the daemon later.
    """
    if not state_path.exists():
        return {}
    try:
        doc = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise SlackInboxError(f"dedupe state unreadable: {state_path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise SlackInboxError(f"dedupe state is not a JSON object: {state_path}")
    seen = doc.get("seen")
    if not isinstance(seen, dict):
        raise SlackInboxError(f"dedupe state has no 'seen' object: {state_path}")
    return seen


def _save_seen(state_path: Path, seen: dict[str, dict[str, Any]]) -> None:
    # FIFO eviction before writing: oldest `ts` ids fall off first.
    while len(seen) > MAX_SEEN:
        seen.pop(next(iter(seen)))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp.write_text(json.dumps({"seen": seen}, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, state_path)


def _quarantine(path: Path, quarantine_dir: Path, reason: str) -> dict[str, Any]:
    """Move a bad item out of the inbox with its reason stamped into the file."""
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    try:
        item = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        item = {"_unreadable": True}
    if isinstance(item, dict):
        item["_quarantine_reason"] = reason
        item["_quarantined_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    dest = quarantine_dir / path.name
    if isinstance(item, dict):
        dest.write_text(json.dumps(item, indent=2, sort_keys=True), encoding="utf-8")
        path.unlink()
    else:  # pragma: no cover — non-object JSON already handled by the caller
        os.replace(path, dest)
    return {"path": str(path), "reason": reason, "quarantined_to": str(dest)}


def _validate(item: Any) -> tuple[str, str, str, str]:
    """Return (kind, user, ts, text) or raise SlackInboxError with the reason.

    Raising here means "quarantine this item"; the drain loop catches it per file
    so one bad item never stops the rest.
    """
    if not isinstance(item, dict):
        raise SlackInboxError("not a JSON object")
    kind = item.get("kind")
    if kind not in KNOWN_KINDS:
        raise SlackInboxError(f"unknown kind: {kind!r}")
    ts = item.get("ts")
    if not isinstance(ts, str) or not ts:
        raise SlackInboxError("missing ts")
    text = clean_text(item.get("text"))
    if not text:
        raise SlackInboxError("empty text after cleaning")
    user = item.get("user")
    return kind, (user if isinstance(user, str) and user else "slack"), ts, text


def drain(
    inbox_dir: str | os.PathLike[str],
    open_goal: OpenGoal,
    *,
    agent: str = "scout",
    repo: str = "",
    dry_run: bool = False,
    state_path: str | os.PathLike[str] | None = None,
    quarantine_dir: str | os.PathLike[str] | None = None,
    done_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Drain inbox JSON files into goals. Returns a summary dict, always.

    Summary keys: `ok`, `dry_run`, `opened` (goal rows), `would_open` (dry-run
    only: item summaries), `skipped_seen` (ts ids), `quarantined` and `failed`
    (each `{path, reason[, quarantined_to]}`). `failed` items stay in the inbox
    for a later run to retry; everything else is moved or recorded.
    """
    inbox = Path(inbox_dir)
    state_file = Path(state_path) if state_path else default_state_path(inbox)
    qdir = Path(quarantine_dir) if quarantine_dir else inbox / "_quarantine"
    ddir = Path(done_dir) if done_dir else inbox / "_done"

    seen = _load_seen(state_file)
    opened: list[dict[str, Any]] = []
    would_open: list[dict[str, Any]] = []
    skipped_seen: list[str] = []
    quarantined: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    files = sorted(p for p in inbox.glob("*.json") if p.is_file())
    for path in files:
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            quarantined.append(_quarantine(path, qdir, f"unreadable: {exc.__class__.__name__}"))
            continue
        try:
            item = json.loads(raw)
        except ValueError:
            quarantined.append(_quarantine(path, qdir, "malformed JSON"))
            continue
        try:
            kind, user, ts, text = _validate(item)
        except SlackInboxError as exc:
            quarantined.append(_quarantine(path, qdir, str(exc)))
            continue
        if ts in seen:
            skipped_seen.append(ts)
            continue

        provenance = {
            "kind": kind,
            "user": user,
            "channel": item.get("channel", ""),
            "channel_name": item.get("channel_name", ""),
            "thread_ts": item.get("thread_ts", "") or "",
            "text": text,
        }
        if dry_run:
            would_open.append({"path": str(path), "ts": ts, **provenance})
            continue

        result = open_goal(agent, repo, text)
        if not isinstance(result, dict) or not result.get("ok"):
            reason = "open_goal refused"
            if isinstance(result, dict):
                reason = str(result.get("error") or result.get("reason") or reason)
            failed.append({"path": str(path), "reason": reason})
            continue

        goal = result.get("goal")
        goal_id = goal.get("id") if isinstance(goal, dict) else None
        seen[ts] = {"goal_id": goal_id, **provenance}
        opened.append(goal if isinstance(goal, dict) else {"id": goal_id, "text": text})
        try:
            ddir.mkdir(parents=True, exist_ok=True)
            os.replace(path, ddir / path.name)
        except OSError:
            # The ts is already recorded, so a later run skips it; the leftover
            # file is untidy, not a duplicate goal.
            pass

    if not dry_run:
        _save_seen(state_file, seen)

    return {
        "ok": True,
        "dry_run": dry_run,
        "opened": opened,
        "would_open": would_open,
        "skipped_seen": skipped_seen,
        "quarantined": quarantined,
        "failed": failed,
    }
