"""
detect.py — collect files respecting .gitignore + .graphifyignore
Solo personal project, no connection to employer, built with public/free-tier only
"""

import fnmatch
import os
from pathlib import Path

DEFAULT_EXCLUDES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".turbo",
    "graphify-out",
    ".graphify",
    "cache",
    ".mypy_cache",
    ".pytest_cache",
    "coverage",
    ".graphify_cache",
}

CODE_EXTS = {
    ".py",
    ".ts",
    ".mts",
    ".cts",
    ".js",
    ".jsx",
    ".tsx",
    ".mjs",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".rb",
    ".cs",
    ".kt",
    ".scala",
    ".php",
    ".swift",
    ".lua",
    ".zig",
    ".sh",
    ".bash",
    ".json",
    ".sql",
    ".vue",
    ".svelte",
    ".astro",
    ".dart",
    ".jl",
    ".ex",
    ".exs",
}

DOC_EXTS = {".md", ".mdx", ".mdc", ".txt", ".rst", ".qmd", ".yaml", ".yml"}
MEDIA_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".pdf",
    ".mp4",
    ".mov",
    ".mp3",
    ".wav",
}

ALL_VALID_EXTS = CODE_EXTS | DOC_EXTS | MEDIA_EXTS

# Extensionless files worth indexing. Anything else without a known extension
# (LICENSE, binaries, lockfile blobs, etc.) is skipped.
KNOWN_EXTENSIONLESS_NAMES = {"dockerfile", "makefile", "justfile"}


def is_collectible(path: Path) -> bool:
    """Single allowlist for file collection: known extension OR known extensionless name."""
    if path.suffix.lower() in ALL_VALID_EXTS:
        return True
    return path.suffix == "" and path.name.lower() in KNOWN_EXTENSIONLESS_NAMES


def load_ignore_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    patterns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def is_ignored(file_path: Path, root: Path, ignore_patterns: list[str]) -> bool:
    rel = str(file_path.relative_to(root)).replace("\\", "/")
    name = file_path.name
    for pat in ignore_patterns:
        if not pat:
            continue
        # simple gitignore-like
        if pat.endswith("/"):
            if rel.startswith(pat) or f"/{pat}" in f"/{rel}/":
                return True
            continue
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat):
            return True
    # check default excludes
    for excl in DEFAULT_EXCLUDES:
        if excl in file_path.parts:
            return True
    return False


def collect_files(root: Path, max_files: int = 10000) -> list[Path]:
    root = root.resolve()
    gitignore = load_ignore_file(root / ".gitignore")
    graphifyignore = load_ignore_file(root / ".graphifyignore")
    all_patterns = gitignore + graphifyignore

    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirpath_p = Path(dirpath)
        # prune excluded dirs
        dirnames[:] = [
            d
            for d in dirnames
            if d not in DEFAULT_EXCLUDES
            and not is_ignored(dirpath_p / d, root, all_patterns)
        ]
        for fname in filenames:
            fpath = dirpath_p / fname
            if not is_collectible(fpath):
                continue
            if is_ignored(fpath, root, all_patterns):
                continue
            # size limit 5MB per file
            try:
                if fpath.stat().st_size > 5 * 1024 * 1024:
                    continue
            except:
                continue
            files.append(fpath)
            if len(files) >= max_files:
                return files
    return files


def group_by_type(files: list[Path]):
    code = [f for f in files if f.suffix.lower() in CODE_EXTS]
    docs = [
        f
        for f in files
        if f.suffix.lower() in DOC_EXTS
        or f.name in ("PROJECT.md", "CLAUDE.md", "AGENTS.md")
    ]
    media = [f for f in files if f.suffix.lower() in MEDIA_EXTS]
    return {"code": code, "docs": docs, "media": media}
