"""Data line: what data exists, how fresh it is, how it is refreshed or restored (spec §4)."""

from __future__ import annotations

import json
import shutil
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from factory.config import Factory, FactoryError, run_cmd, save_json, sha256_of, table

if TYPE_CHECKING:
    from pathlib import Path


def _age_days(path: Path, fresh_key: str) -> float | None:
    """Days since the dataset was produced; None when the declared key is unreadable."""
    if fresh_key == "mtime":
        return (time.time() - path.stat().st_mtime) / 86400
    dotted = fresh_key.removeprefix("json:")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    cur = doc
    for part in dotted.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    if not isinstance(cur, str):
        return None
    try:
        when = datetime.fromisoformat(cur.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (datetime.now(UTC) - when).total_seconds() / 86400


def check_one(f: Factory, d: dict) -> dict:
    path = f.repo_dir(d["repo"]) / d["path"]
    row = {
        "id": d["id"],
        "repo": d["repo"],
        "path": d["path"],
        "provenance": d.get("provenance", "unknown"),
        "required": bool(d.get("required", False)),
        "present": path.is_file(),
        "size": None,
        "sha16": None,
        "age_days": None,
        "cadence_days": d.get("cadence_days"),
        "problem": None,
    }
    if not row["present"]:
        row["problem"] = (
            "repo not checked out" if not f.repo_dir(d["repo"]).is_dir() else "missing"
        )
        return row
    row["size"] = path.stat().st_size
    row["sha16"] = sha256_of(path)[:16]
    expected = d.get("expected_sha256")
    if (
        expected
        and not expected.startswith(row["sha16"])
        and expected != sha256_of(path)
    ):
        row["problem"] = "sha mismatch"
    age = _age_days(path, d.get("fresh_key", "mtime"))
    row["age_days"] = None if age is None else round(age, 1)
    cad = d.get("cadence_days")
    if cad is not None:
        if age is None:
            row["problem"] = row["problem"] or "freshness unreadable"
        elif age > cad:
            row["problem"] = row["problem"] or "stale"
    return row


def check(f: Factory) -> list[dict]:
    return [check_one(f, d) for d in f.datasets()]


def render_check(rows: list[dict]) -> str:
    out = []
    for r in rows:
        size = (
            ""
            if r["size"] is None
            else (
                f"{r['size'] / 1e6:.1f}MB"
                if r["size"] >= 1e6
                else f"{r['size'] / 1e3:.0f}kB"
            )
        )
        age = "" if r["age_days"] is None else f"{r['age_days']}d"
        cad = "static" if r["cadence_days"] is None else f"every {r['cadence_days']}d"
        state = r["problem"] or "ok"
        out.append(
            [
                r["id"],
                r["repo"],
                r["provenance"],
                "req" if r["required"] else "",
                size,
                r["sha16"] or "",
                age,
                cad,
                state,
            ]
        )
    problems = sum(1 for r in rows if r["problem"])
    req_problems = sum(1 for r in rows if r["problem"] and r["required"])
    return (
        table(
            out,
            [
                "dataset",
                "repo",
                "provenance",
                "",
                "size",
                "sha256",
                "age",
                "cadence",
                "state",
            ],
        )
        + f"\n{len(rows)} datasets, {problems} with a problem ({req_problems} required)"
    )


def list_datasets(f: Factory) -> str:
    rows = [
        [
            d["id"],
            d["repo"],
            d["path"],
            d.get("provenance", "unknown"),
            d.get("refresh") or "-",
            ", ".join(d.get("consumers", [])) or "-",
        ]
        for d in f.datasets()
    ]
    return table(
        rows, ["dataset", "repo", "path", "provenance", "refresh", "consumers"]
    )


def refresh(f: Factory, ds_id: str) -> int:
    d = f.dataset(ds_id)
    cmd = d.get("refresh")
    if not cmd:
        raise FactoryError(
            f"{ds_id} has no refresh command ({d.get('source', 'source not recorded')})"
        )
    repo = f.repo_dir(d["repo"])
    if not repo.is_dir():
        raise FactoryError(f"{d['repo']} is not checked out at {repo}")
    print(f"[{ds_id}] $ {cmd}", flush=True)
    env = {**f.env, **{k: str(v) for k, v in (d.get("env") or {}).items()}}
    rc = run_cmd(cmd, repo, env=env)
    print(render_check([check_one(f, d)]))
    return rc


def restore(f: Factory, ds_id: str, *, force: bool = False) -> str:
    d = f.dataset(ds_id)
    sources = d.get("restore_from", [])
    if not sources:
        raise FactoryError(f"{ds_id} has no restore_from sources; refresh it instead")
    dest = f.repo_dir(d["repo"]) / d["path"]
    if dest.exists() and not force:
        raise FactoryError(f"{dest} exists; pass --force to overwrite")
    for rel in sources:
        src = f.workspace / rel
        if src.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            digest = sha256_of(dest)
            manifest = {
                "dataset": ds_id,
                "restored_from": rel,
                "sha256": digest,
                "size_bytes": dest.stat().st_size,
                "restored_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "provenance": d.get("provenance", "unknown"),
            }
            save_json(dest.with_name(dest.name + ".manifest.json"), manifest)
            return f"{ds_id}: restored from {rel} ({manifest['size_bytes']} bytes, sha256 {digest[:16]}…); manifest written"
    tried = "\n  ".join(str(f.workspace / s) for s in sources)
    raise FactoryError(f"{ds_id}: no restore source present. Tried:\n  {tried}")
