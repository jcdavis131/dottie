"""
todos plugin — summarize TODO/FIXME/HACK markers across scout-cli and dottie monorepo.

Factory wrapper rule: if Dottie factory interaction is ever needed, invoke via
`scout ava ...` subprocess / CLI, never direct import of apps/ava-factory.
No secrets in code. Telemetry files stay gitignored.

Contract: uses make_plugin_app + ok()/err() envelope + emit(), supports
--json via root callback, --yes/-y + SCOUT_YES env, --path filter.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import typer

from bigbang.core.cli_ux import examples_epilog
from bigbang.core.contract import err, make_plugin_app, ok
from bigbang.core.output import emit

app = make_plugin_app(
    "todos",
    "📝 TODOs — summarize TODO/FIXME/HACK markers across the repo",
    examples=[
        "scout todos",
        "scout todos --path bigbang/plugins/write",
        "scout --json todos",
        "scout --json todos --path bigbang/plugins",
        "scout todos --help --json",
        "SCOUT_YES=1 scout todos --path ~/workspace/dottie",
    ],
    no_args_is_help=False,
)

# ------------------------------------------------------------------ #
# Core scanning
# ------------------------------------------------------------------ #

# The leading \b is load-bearing. Without it the pattern anchored only on the RIGHT, so
# every DEBUG in the tree was reported as a BUG marker — and re.IGNORECASE made lowercase
# `debug` match too. Measured over bigbang/ on 2026-08-02, before and after:
#
#     shipped regex : 85 markers
#     with \b       : 58 markers
#     false         : 27  (31.8%)
#
# LEVEL_DEBUG = "debug", logger.setLevel(DEBUG), .lv-debug in a CSS string — all counted as
# outstanding BUGs. A third of this plugin's entire output was noise, in the one plugin
# whose only job is counting markers accurately.
#
# `#TODO` with no space still matches: `#` is a non-word character, so the boundary holds.
MARKER_RE = re.compile(
    r"\b(?P<marker>TODO|FIXME|HACK|XXX|BUG)\b[:\s-]*?(?P<rest>.*)?",
    re.IGNORECASE,
)

# directories to always skip
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    ".cache",
    ".wandb",
    "checkpoints",
    ".scout",
    "graphify-out",
    "graphify-out-research",
    "graphify-out-research-combined",
    ".env",
    ".next",
    ".turbo",
}

SKIP_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".o",
    ".a",
    ".log",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".mp4",
    ".mp3",
    ".zip",
    ".gz",
    ".tar",
}

# binary-ish names to skip
SKIP_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
}


def _is_ignored_dir(p: Path) -> bool:
    name = p.name
    if name in SKIP_DIRS:
        return True
    if name.startswith(".") and name not in {".", ".."}:
        # keep .github etc? but skip hidden caches; allow .github not needed for TODOs
        # we skip dot-dirs except we explicitly allow a few
        if name in {".git", ".hg"}:
            return True
        # skip other dot dirs like .venv handled, but also .ruff_cache etc
        if name.startswith(".") and len(name) > 1:
            # allow .github? check if it looks like cache - keep conservative skip
            if name in {".github"}:
                return False
            return True
    if name.endswith(".egg-info"):
        return True
    return False


def _should_skip_file(p: Path) -> bool:
    if p.name in SKIP_FILES:
        return True
    if p.suffix.lower() in SKIP_SUFFIXES:
        return True
    if p.name.startswith(".") and p.suffix == "":
        return True
    if ".egg-info" in p.parts:
        return True
    # skip telemetry-ish
    if "dottie_live_status" in p.name or "dottie_telemetry" in p.name:
        return True
    if "STATUS.json" in p.name:
        return True
    return False


def _derive_plugin(file_path: Path, root: Path) -> str:
    """Derive plugin name if file lives under bigbang/plugins/<name>/"""
    try:
        parts = file_path.relative_to(root).parts if file_path.is_relative_to(root) else file_path.parts
    except Exception:
        parts = file_path.parts
    # look for .../plugins/<name>/...
    if "plugins" in parts:
        idx = parts.index("plugins")
        if idx + 1 < len(parts):
            candidate = parts[idx + 1]
            # guard against __pycache__ etc
            if not candidate.startswith("__") and not candidate.startswith("."):
                return candidate
    # also monorepo grouping: apps/<app>/
    if "apps" in parts:
        idx = parts.index("apps")
        if idx + 1 < len(parts):
            return f"apps/{parts[idx+1]}"
    # packages
    if "packages" in parts:
        idx = parts.index("packages")
        if idx + 1 < len(parts):
            return f"packages/{parts[idx+1]}"
    return "core"


def _resolve_root() -> Path:
    """Default root: scout-cli package root"""
    # this file: bigbang/plugins/todos/cli.py -> parents[3] = apps/scout-cli
    try:
        here = Path(__file__).resolve()
        # bigbang/plugins/todos/cli.py -> parents: todos, plugins, bigbang, scout-cli
        candidate = here.parents[3]
        if (candidate / "bigbang" / "cli.py").exists():
            return candidate
    except Exception:
        pass
    # fallback via DOTTIE_ROOT env or home workspace
    dottie = os.environ.get("DOTTIE_ROOT")
    if dottie:
        p = Path(dottie).expanduser() / "apps" / "scout-cli"
        if p.exists():
            return p
    home = Path.home() / "workspace" / "dottie" / "apps" / "scout-cli"
    if home.exists():
        return home
    return Path.cwd()


def _is_truthy_env(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _should_confirm(root: Path, target: Path) -> bool:
    """Whether scanning target requires confirmation (outside default root and large)."""
    try:
        # if target is inside default root, no confirm
        if target.resolve().is_relative_to(root.resolve()):
            return False
    except Exception:
        pass
    # scanning entire dottie monorepo or home is larger
    return True


def _scan_markers(
    root: Path,
    path_filter: str | None = None,
    type_filter: str | None = None,
    max_items: int = 1000,
) -> dict[str, Any]:
    """Scan files for markers."""
    # Determine effective scan root
    scan_root = root
    substring_filter: str | None = None

    if path_filter:
        pf = path_filter.strip()
        # allow env expansion and tilde
        expanded = Path(os.path.expanduser(os.path.expandvars(pf)))
        if expanded.exists():
            if expanded.is_file():
                scan_root = expanded.parent
                # if single file, narrow filter to that file name
                substring_filter = expanded.name
            else:
                scan_root = expanded
        else:
            # treat as substring filter relative to root OR absolute path string
            # if it looks like a path containing slash or backslash
            maybe_path = root / pf
            if maybe_path.exists():
                scan_root = maybe_path
            else:
                # substring filter mode: scan root, filter files containing string
                substring_filter = pf

    if not scan_root.exists():
        return {
            "error": f"path does not exist: {scan_root}",
            "root": str(root),
            "scan_root": str(scan_root),
        }

    todos: list[dict[str, Any]] = []
    scanned_files = 0
    skipped_files = 0

    # Normalize type_filter
    allowed_types = None
    if type_filter:
        allowed_types = {t.strip().upper() for t in type_filter.split(",") if t.strip()}

    # walk
    for dirpath, dirnames, filenames in os.walk(scan_root, topdown=True, followlinks=False):
        # modify dirnames in-place to skip ignored dirs
        dirpath_p = Path(dirpath)
        # prune
        pruned = []
        for d in list(dirnames):
            full = dirpath_p / d
            if _is_ignored_dir(full):
                pruned.append(d)
        for d in pruned:
            dirnames.remove(d)

        for fname in filenames:
            fpath = dirpath_p / fname
            if _should_skip_file(fpath):
                skipped_files += 1
                continue
            # substring filter early: if filter string and not in file path, skip
            if substring_filter:
                # match against full path string or relative
                try:
                    rel = str(fpath.relative_to(root))
                except Exception:
                    rel = str(fpath)
                if substring_filter not in str(fpath) and substring_filter not in rel:
                    continue

            # avoid huge files > 2MB
            try:
                if fpath.stat().st_size > 2_000_000:
                    continue
            except Exception:
                continue

            # only scan text-ish extensions if we want to be efficient
            # but we also want to catch TODO in many file types, so try to read
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                skipped_files += 1
                continue

            # quick pre-check
            if "TODO" not in text and "FIXME" not in text and "HACK" not in text and "XXX" not in text and "BUG" not in text:
                # also check lowercase
                low = text.lower()
                if "todo" not in low and "fixme" not in low and "hack" not in low:
                    scanned_files += 1
                    continue

            scanned_files += 1
            for i, line in enumerate(text.splitlines(), start=1):
                m = MARKER_RE.search(line)
                if not m:
                    continue
                marker = m.group("marker").upper()
                if allowed_types and marker not in allowed_types:
                    continue
                # context: trimmed line (up to 300 chars)
                ctx = line.strip()[:400]
                # relative path for grouping
                try:
                    rel_path = str(fpath.relative_to(root))
                except Exception:
                    # if scanning outside root, relative to scan_root or absolute
                    try:
                        rel_path = str(fpath.relative_to(scan_root))
                    except Exception:
                        rel_path = str(fpath)
                plugin = _derive_plugin(fpath, root)

                todos.append(
                    {
                        "file": rel_path,
                        "abs_path": str(fpath),
                        "line": i,
                        "type": marker,
                        "marker": m.group("marker"),
                        "context": ctx,
                        "plugin": plugin,
                    }
                )
                if len(todos) >= max_items:
                    break
            if len(todos) >= max_items:
                break
        if len(todos) >= max_items:
            break

    # groupings
    by_type: dict[str, int] = {}
    by_plugin: dict[str, int] = {}
    by_file: dict[str, int] = {}

    for item in todos:
        by_type[item["type"]] = by_type.get(item["type"], 0) + 1
        by_plugin[item["plugin"]] = by_plugin.get(item["plugin"], 0) + 1
        by_file[item["file"]] = by_file.get(item["file"], 0) + 1

    # sort groupings for stability
    by_type_sorted = dict(sorted(by_type.items(), key=lambda x: (-x[1], x[0])))
    by_plugin_sorted = dict(sorted(by_plugin.items(), key=lambda x: (-x[1], x[0])))
    by_file_sorted = dict(sorted(by_file.items(), key=lambda x: (-x[1], x[0])))

    return {
        "root": str(root),
        "scan_root": str(scan_root),
        "path_filter": path_filter,
        "type_filter": type_filter,
        "substring_filter": substring_filter,
        "scanned_files": scanned_files,
        "skipped_files": skipped_files,
        "total_markers": len(todos),
        "todos": todos[: max_items if len(todos) <= max_items else max_items],
        "by_type": by_type_sorted,
        "by_plugin": by_plugin_sorted,
        "by_file": by_file_sorted,
        "truncated": len(todos) >= max_items,
        "max_items": max_items,
    }


# ------------------------------------------------------------------ #
# CLI commands
# ------------------------------------------------------------------ #

def _confirm_if_needed(
    root: Path,
    target: Path,
    yes: bool,
) -> None:
    """Handle --yes / SCOUT_YES env for large scans."""
    # honor env var
    env_yes = _is_truthy_env(os.environ.get("SCOUT_YES"))
    effective_yes = yes or env_yes
    if not _should_confirm(root, target):
        return
    # If scanning outside default root and not yes, ask confirmation if interactive
    if effective_yes:
        return
    # Non-interactive without yes: fail fast with example using contract err()
    # But for todos, we can still allow with warning; we will confirm via typer if tty
    try:
        is_tty = os.isatty(0)
    except Exception:
        is_tty = False
    if not is_tty:
        # non-interactive and no --yes: we still proceed but emit hint? spec says support yes handling
        # To respect safety, we require --yes for scanning outside root when non-tty.
        # Use err envelope and raise Exit.
        emit(
            err(
                f"Scanning outside scout-cli root ({target}) requires --yes/-y or SCOUT_YES=1 in non-interactive mode",
                command="todos list",
                example=f"scout todos --path {target} --yes",
                discover="scout todos --help",
            ),
            command="todos list",
        )
        raise typer.Exit(1)
    # interactive: prompt
    confirmed = typer.confirm(f"Scan outside scout-cli root: {target} ? This may be large. Continue?")
    if not confirmed:
        emit(
            ok(
                {"cancelled": True, "target": str(target)},
                command="todos",
                example=f"scout todos --path {target} --yes",
            ),
            command="todos",
        )
        raise typer.Exit(0)


@app.callback(invoke_without_command=True)
def _todos_root(
    ctx: typer.Context,
    path: str | None = typer.Option(
        None,
        "--path",
        "-p",
        help="Root path to scan OR substring filter (e.g. bigbang/plugins/write, ~/workspace/dottie)",
    ),
    type_filter: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter marker type (comma-separated): TODO,FIXME,HACK",
    ),
    max_items: int = typer.Option(
        500,
        "--max",
        help="Max markers to return (truncate for large repos)",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation for large/outside scans (also env SCOUT_YES=1)",
        envvar="SCOUT_YES",
    ),
):
    """Summarize TODO/FIXME/HACK markers.

    Default scans apps/scout-cli. Use --path to scan a subdir, file, or substring.
    Factory wrapper guarantee: never imports apps/ava-factory directly; would use
    `scout ava ...` subprocess if factory interaction were needed.
    """
    if ctx.invoked_subcommand is not None:
        return

    root = _resolve_root()

    # resolve target for confirm check
    target_path = root
    if path:
        expanded = Path(os.path.expanduser(os.path.expandvars(path)))
        if expanded.exists():
            target_path = expanded
        else:
            maybe = root / path
            if maybe.exists():
                target_path = maybe
            else:
                # substring mode: target is still root, but we treat filter later
                target_path = root

    # confirmation gate for outside scans
    _confirm_if_needed(root, target_path, yes)

    result = _scan_markers(root, path_filter=path, type_filter=type_filter, max_items=max_items)
    if "error" in result:
        emit(
            err(
                result["error"],
                command="todos",
                example="scout todos --path bigbang/plugins",
                discover="scout todos --help",
            ),
            command="todos",
        )
        raise typer.Exit(1)

    # Factory wrapper note: no direct factory import; if we needed factory,
    # we would call via subprocess like: subprocess.run(["scout","ava","status"],...)
    # kept clean to satisfy doctrine.

    emit(
        ok(
            result,
            command="todos",
            example="scout --json todos --path bigbang/plugins/write",
            discover="scout todos --path bigbang/plugins --type TODO",
        ),
        command="todos",
    )


@app.command(
    "list",
    epilog=examples_epilog(
        [
            "scout todos list",
            "scout todos list --path bigbang/plugins/write",
            "scout --json todos list",
            "scout --json todos list --type FIXME",
            "SCOUT_YES=1 scout todos list --path ~/workspace/dottie",
        ]
    ),
)
def list_cmd(
    path: str | None = typer.Option(
        None,
        "--path",
        "-p",
        help="Root path to scan OR substring filter",
    ),
    type_filter: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter marker type: TODO,FIXME,HACK (comma-separated)",
    ),
    max_items: int = typer.Option(
        500,
        "--max",
        help="Max markers to return",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt (also env SCOUT_YES=1)",
        envvar="SCOUT_YES",
    ),
):
    """List TODO/FIXME/HACK markers with grouping."""
    root = _resolve_root()
    target_path = root
    if path:
        expanded = Path(os.path.expanduser(os.path.expandvars(path)))
        if expanded.exists():
            target_path = expanded
        else:
            maybe = root / path
            if maybe.exists():
                target_path = maybe

    _confirm_if_needed(root, target_path, yes)

    result = _scan_markers(root, path_filter=path, type_filter=type_filter, max_items=max_items)
    if "error" in result:
        emit(
            err(result["error"], command="todos list", example="scout todos list --path bigbang/plugins"),
            command="todos list",
        )
        raise typer.Exit(1)

    emit(
        ok(
            result,
            command="todos list",
            example="scout --json todos list --path bigbang/plugins/write",
            discover="scout todos --help",
        ),
        command="todos list",
    )


@app.command(
    "summary",
    epilog=examples_epilog(
        [
            "scout todos summary",
            "scout --json todos summary",
        ]
    ),
)
def summary_cmd(
    path: str | None = typer.Option(None, "--path", "-p", help="Root path or substring filter"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation", envvar="SCOUT_YES"),
):
    """Compact summary (counts only) grouped by type and plugin."""
    root = _resolve_root()
    target_path = root
    if path:
        expanded = Path(os.path.expanduser(os.path.expandvars(path)))
        if expanded.exists():
            target_path = expanded
    _confirm_if_needed(root, target_path, yes)

    result = _scan_markers(root, path_filter=path, max_items=1000)
    if "error" in result:
        emit(err(result["error"], command="todos summary"), command="todos summary")
        raise typer.Exit(1)

    # compact view
    compact = {
        "root": result["root"],
        "scan_root": result["scan_root"],
        "scanned_files": result["scanned_files"],
        "total_markers": result["total_markers"],
        "by_type": result["by_type"],
        "by_plugin": result["by_plugin"],
        "top_files": dict(list(result["by_file"].items())[:20]),
    }
    emit(
        ok(compact, command="todos summary", example="scout --json todos summary"),
        command="todos summary",
    )


# `_call_via_ava_subprocess` used to sit here. Its own docstring said it: "intentionally
# not used in normal todos flow; provided to satisfy doctrine". Dead code kept to
# demonstrate a rule is still dead code — the rule lives in the module docstring above,
# where it costs nothing and cannot rot out of sync with a real call site.


def register(root):
    root.add_typer(app, name="todos")
