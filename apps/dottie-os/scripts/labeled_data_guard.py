#!/usr/bin/env python3
"""Content-keyed labeled-data guard.

Tracked labeled data is allowed only when its sha256 matches the frozen
allowlist below. A path-only allowlist is not enough: renaming a pack
does not hide it, and editing an allowlisted file refuses.

CI wiring in ``.github/workflows`` is a separate Cam-labelled commit.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

CHUNK = 1 << 20

ALLOWED_LABELED_DATA: dict[str, str] = {
    "apps/dottie-os/tests/fixtures/leakgate_eval/source.json": (
        "665eb240279da789534f0de0aab2c7ed086dbe024e37679431e4d15dda33d11a"
    ),
    "apps/dottie-os/tests/fixtures/leakgate_eval/MANIFEST.json": (
        "888645987a1d7e605a1d11046aa08a9e79b997ec602cf929c8333b9d18e068ec"
    ),
}

LABELED_PATH_RE = re.compile(
    r"(?:^|/)(?:curated_pack_.*\.(?:jsonl|json)|.*ultradata_harvest_.*|"
    r"leakgate_eval/(?:source|MANIFEST)\.json)$"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def git_tracked_files(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(root),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"labeled_data_guard: git ls-files failed: {proc.stderr!r}")
    return [item for item in proc.stdout.decode("utf-8").split("\0") if item]


def is_labeled_path(rel: str) -> bool:
    posix = rel.replace("\\", "/")
    return bool(LABELED_PATH_RE.search(posix))


def check_tree(root: Path | None = None) -> list[str]:
    """Return refusal messages. Empty means the tree is clean."""
    root = Path(root) if root is not None else repo_root()
    hits: list[str] = []
    tracked = git_tracked_files(root)
    seen_allowed: set[str] = set()
    by_sha: dict[str, list[str]] = {}
    for rel in tracked:
        posix = rel.replace("\\", "/")
        path = root / posix
        if not path.is_file():
            continue
        if posix in ALLOWED_LABELED_DATA or is_labeled_path(posix):
            digest = sha256_file(path)
            by_sha.setdefault(digest, []).append(posix)
            expected = ALLOWED_LABELED_DATA.get(posix)
            if expected is None:
                hits.append(f"unallowlisted labeled data: {posix} sha256 {digest}")
                continue
            seen_allowed.add(posix)
            if digest != expected:
                hits.append(
                    f"allowlisted file hash mismatch: {posix} expected {expected} actual {digest}"
                )
    for rel, expected in ALLOWED_LABELED_DATA.items():
        if rel not in seen_allowed:
            hits.append(f"missing allowlisted labeled data: {rel}")
        else:
            digest = sha256_file(root / rel)
            copies = [path for path in by_sha.get(digest, []) if path != rel]
            for extra in copies:
                hits.append(
                    f"allowlisted content copied to unpinned path: {extra} sha256 {digest}"
                )
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repository root (default: three parents of this script)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve() if args.root is not None else repo_root()
    hits = check_tree(root)
    for line in hits:
        print(line, file=sys.stderr)
    if hits:
        return 1
    print("labeled-data guard: allowlist hashes match, no extra labeled files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
