"""packs import stub — zero-deps stdlib only, honest 503
usage: import.py <git-url>
Distilled from qm — packs imported from git, scope-owned, shareable by grant
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # scopes/
PACKS_DIR = ROOT / "packs"
REGISTRY = ROOT / "registry.json"


def _git_clone(url: str, dest: Path) -> dict:
    # honest 503 if git missing
    if not url or not url.startswith(("https://", "git@", "ssh://", "http://")):
        return {"ok": False, "error": f"invalid git url: {url}", "errorClass": "VALIDATION_ERROR"}
    git = shutil.which("git") if (shutil := __import__("shutil")) else None
    if git is None:
        import shutil as _sh
        git_path = _sh.which("git")
        if not git_path:
            return {"ok": False, "error": "git not found in PATH", "errorClass": "IO_MISSING", "hint": "install git or copy pack manually"}
        git = git_path

    try:
        # shallow clone for speed, stdlib only
        proc = subprocess.run(
            [git, "clone", "--depth", "1", url, str(dest)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:2000] or f"git clone exit {proc.returncode}", "errorClass": "GIT_ERROR"}
        return {"ok": True, "path": str(dest)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git clone timeout 60s", "errorClass": "TIMEOUT"}
    except FileNotFoundError as e:
        return {"ok": False, "error": f"git missing at exec: {e}", "errorClass": "IO_MISSING"}


def import_pack(url: str, name: str | None = None) -> dict:
    if not url:
        return {"ok": False, "error": "no url", "errorClass": "VALIDATION_ERROR"}
    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    # derive name from url if not given
    if not name:
        name = url.rstrip("/").split("/")[-1].replace(".git", "") or "pack"
    dest = PACKS_DIR / name
    if dest.exists():
        return {"ok": False, "error": f"pack already exists: {dest}", "errorClass": "ALREADY_EXISTS", "hint": f"rm -rf {dest} first"}

    res = _git_clone(url, dest)
    if not res.get("ok"):
        return res

    # update registry.json — scope-owned packs
    try:
        reg = {}
        if REGISTRY.exists():
            reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        packs = reg.get("packs", {})
        packs[name] = {"url": url, "path": str(dest), "imported_at": __import__("datetime").datetime.utcnow().isoformat() + "Z"}
        reg["packs"] = packs
        tmp = REGISTRY.with_suffix(".tmp")
        tmp.write_text(json.dumps(reg, indent=2), encoding="utf-8")
        tmp.replace(REGISTRY)
    except Exception:
        # non-fatal — clone succeeded even if registry update fails
        pass

    return {"ok": True, "name": name, "path": str(dest), "url": url}


def list_packs() -> dict:
    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    packs = [p.name for p in PACKS_DIR.iterdir() if p.is_dir()]
    return {"ok": True, "packs": sorted(packs), "dir": str(PACKS_DIR)}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="scopes/packs import — git import for skill packs")
    ap.add_argument("url", nargs="?", help="git url of pack")
    ap.add_argument("--name", help="pack name override")
    ap.add_argument("--list", action="store_true", help="list imported packs")
    args = ap.parse_args()

    if args.list:
        print(json.dumps(list_packs(), indent=2))
        return

    if not args.url:
        ap.print_help()
        sys.exit(2)

    res = import_pack(args.url, args.name)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
