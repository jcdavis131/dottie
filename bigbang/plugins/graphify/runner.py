# Solo personal project, no connection to employer, built with public/free-tier only
"""
runner.py — resolve Personal Graphify (pgraphify) and run core ops.

Prefers in-process `personal_graphify` import; falls back to `pgraphify` CLI on PATH.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

DISCLAIMER = (
    "Solo personal project, no connection to employer, built with public/free-tier only"
)

DEFAULT_ECOSYSTEM_ROOTS = (
    "scout-cli",
    "ava-agi-factory-v6-4",
    "personal-graphify",
    "personal-graphify/references",
)


def personal_graphify_home() -> Path:
    env = os.environ.get("PERSONAL_GRAPHIFY_HOME") or os.environ.get("PGRAPHIFY_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / "personal-graphify").resolve()


def resolve_graph_path(explicit: Optional[str] = None, cwd: Optional[Path] = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("SCOUT_GRAPHIFY_GRAPH") or os.environ.get("PGRAPHIFY_GRAPH")
    if env:
        return Path(env).expanduser().resolve()
    root = cwd or Path.cwd()
    local = root / "graphify-out" / "graph.json"
    if local.exists():
        return local.resolve()
    personal = personal_graphify_home() / "graphify-out" / "graph.json"
    if personal.exists():
        return personal.resolve()
    return local.resolve()


def find_pgraphify_exe() -> Optional[str]:
    for name in ("pgraphify", "personal-graphify", "graphify-personal"):
        hit = shutil.which(name)
        if hit:
            return hit
    # uv tool default on Windows
    local_bin = Path.home() / ".local" / "bin"
    for name in ("pgraphify.exe", "pgraphify", "personal-graphify.exe"):
        cand = local_bin / name
        if cand.exists():
            return str(cand)
    return None


def import_personal_graphify() -> Tuple[bool, Optional[Any]]:
    try:
        import personal_graphify  # type: ignore

        return True, personal_graphify
    except Exception:
        pass
    # Editable install path fallback
    home = personal_graphify_home()
    src = home / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
        try:
            import personal_graphify  # type: ignore

            return True, personal_graphify
        except Exception:
            return False, None
    return False, None


def status_payload(cwd: Optional[Path] = None) -> Dict[str, Any]:
    imported, mod = import_personal_graphify()
    exe = find_pgraphify_exe()
    graph = resolve_graph_path(cwd=cwd)
    home = personal_graphify_home()
    nodes = edges = None
    if graph.exists():
        try:
            data = json.loads(graph.read_text(encoding="utf-8"))
            nodes = len(data.get("nodes", []))
            edges = len(data.get("edges", []))
        except Exception:
            pass
    return {
        "ok": bool(imported or exe),
        "personal_graphify_import": imported,
        "personal_graphify_version": getattr(mod, "__version__", None) if mod else None,
        "pgraphify_exe": exe,
        "personal_graphify_home": str(home),
        "home_exists": home.exists(),
        "graph": str(graph),
        "graph_exists": graph.exists(),
        "nodes": nodes,
        "edges": edges,
        "hint": (
            "uv tool install -e ~/personal-graphify"
            if not (imported or exe)
            else "scout graphify query \"how does Scout connect to Ava?\""
        ),
        "disclaimer": DISCLAIMER,
    }


def _run_cli(args: Sequence[str], cwd: Optional[Path] = None) -> Dict[str, Any]:
    exe = find_pgraphify_exe()
    if not exe:
        return {
            "ok": False,
            "error": "pgraphify not found. Install: uv tool install -e ~/personal-graphify",
            "disclaimer": DISCLAIMER,
        }
    proc = subprocess.run(
        [exe, *args],
        cwd=str(cwd or Path.cwd()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "argv": [exe, *args],
        "disclaimer": DISCLAIMER,
    }


def run_build(
    path: str = ".",
    out: Optional[str] = None,
    roots: Optional[List[str]] = None,
    max_files: int = 4000,
    ecosystem: bool = False,
) -> Dict[str, Any]:
    root = Path(path).expanduser().resolve()
    out_dir = Path(out).expanduser().resolve() if out else root / "graphify-out"
    root_args: List[str] = []
    if ecosystem:
        home = Path.home()
        resolved = []
        for name in DEFAULT_ECOSYSTEM_ROOTS:
            p = (home / name).resolve()
            if p.exists():
                resolved.append(str(p))
        # Always include the build root first via positional path
        if resolved:
            # exclude duplicate of root
            extra = [r for r in resolved if Path(r) != root]
            if extra:
                root_args = ["--roots", ",".join(extra)]
    elif roots:
        root_args = ["--roots", ",".join(roots)]

    # Prefer CLI (has --roots). Fall back to import build without multi-root.
    if find_pgraphify_exe():
        args = ["build", str(root), "--out", str(out_dir), "--max-files", str(max_files), *root_args]
        result = _run_cli(args, cwd=root)
        result["out"] = str(out_dir)
        result["graph"] = str(out_dir / "graph.json")
        if (out_dir / "graph.json").exists():
            try:
                data = json.loads((out_dir / "graph.json").read_text(encoding="utf-8"))
                result["nodes"] = len(data.get("nodes", []))
                result["edges"] = len(data.get("edges", []))
            except Exception:
                pass
        return result

    imported, _ = import_personal_graphify()
    if not imported:
        return status_payload(cwd=root) | {"ok": False, "error": "personal-graphify not installed"}

    from personal_graphify.cli import cmd_build  # type: ignore
    import argparse

    ns = argparse.Namespace(path=str(root), out=str(out_dir), max_files=max_files, roots=[])
    cmd_build(ns)
    return {
        "ok": True,
        "out": str(out_dir),
        "graph": str(out_dir / "graph.json"),
        "mode": "import",
        "disclaimer": DISCLAIMER,
    }


def run_text_command(
    command: str,
    args: Sequence[str],
    graph: Optional[str] = None,
    cwd: Optional[Path] = None,
) -> Dict[str, Any]:
    gpath = resolve_graph_path(graph, cwd=cwd)
    if not gpath.exists() and command != "build":
        return {
            "ok": False,
            "error": f"graph.json not found at {gpath}. Run: scout graphify build .",
            "graph": str(gpath),
            "disclaimer": DISCLAIMER,
        }
    cli_args = [command, *args, "--graph", str(gpath)]
    result = _run_cli(cli_args, cwd=cwd)
    result["graph"] = str(gpath)
    result["command"] = command
    # Prefer stdout text for agents
    if result.get("ok") and result.get("stdout"):
        result["text"] = result["stdout"].strip()
    return result


def sync_to_personal(src_graph: Optional[str] = None, cwd: Optional[Path] = None) -> Dict[str, Any]:
    """Copy local scout graph.json into personal-graphify references/spaces/."""
    src = resolve_graph_path(src_graph, cwd=cwd)
    if not src.exists():
        return {"ok": False, "error": f"missing {src}", "disclaimer": DISCLAIMER}
    dest_dir = personal_graphify_home() / "references" / "spaces"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "scout-cli-graph.json"
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return {
        "ok": True,
        "src": str(src),
        "dest": str(dest),
        "bytes": dest.stat().st_size,
        "next": "Rebuild personal ecosystem: pgraphify build ~/personal-graphify --roots ~/scout-cli,...",
        "disclaimer": DISCLAIMER,
    }
