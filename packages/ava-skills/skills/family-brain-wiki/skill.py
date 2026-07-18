# Solo personal project, no connection to employer, built with public/free-tier only
"""family-brain-wiki: Bridge Family Brain OS WikiTab pages into S2.

Primary input: a JSON export of the browser localStorage key
`family-brain-wiki-pages:v1` (pass export_path=...). Falls back to a filesystem
scan, then to generated sample pages.
"""
from __future__ import annotations
from typing import Any, Dict, List
import json, pathlib

STORAGE_KEY = "family-brain-wiki-pages:v1"

def describe() -> Dict[str, Any]:
    """Routing metadata read from SKILL.md frontmatter — the single source of truth."""
    from pathlib import Path
    here = Path(__file__).resolve().parent
    try:
        from skills.loader import describe_from_manifest
    except ImportError:  # loaded standalone without the skills package on sys.path
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ava_skills_loader", here.parent / "loader.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        describe_from_manifest = mod.describe_from_manifest
    return describe_from_manifest(here)

def _scan_family_wiki() -> List[Dict[str,Any]]:
    # scan for family-brain-os storage key in local files or wiki folder
    candidates=[]
    # check src/components/WikiTab.tsx exists?
    fb_root = pathlib.Path.home() / "workspace" / "family-brain-os"
    if (fb_root / "src" / "components" / "WikiTab.tsx").exists():
        candidates.append({"source":"WikiTab.tsx","exists":True})
    # check localStorage export json?
    for name in ["your_files","family-brain-os"]:
        p = pathlib.Path.home() / "workspace" / name
        if p.exists():
            candidates.extend([{"source": str(f), "type":"md"} for f in p.rglob("*wiki*.md")][:5])
    return candidates

def _load_export(export_path: str | pathlib.Path) -> List[Dict[str, str]]:
    """Parse {title, body} pages from a JSON export of the localStorage STORAGE_KEY.

    Accepts any of the shapes a browser export produces:
    - the raw value: a JSON list of page objects
    - a dump keyed by storage key: {"family-brain-wiki-pages:v1": <value>}
    - either of the above where the value is a JSON-encoded string
      (localStorage values are always strings)
    """
    raw = json.loads(pathlib.Path(export_path).expanduser().read_text(encoding="utf-8"))
    if isinstance(raw, dict) and STORAGE_KEY in raw:
        raw = raw[STORAGE_KEY]
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        raise ValueError(f"export must contain a list of pages under {STORAGE_KEY!r}, got {type(raw).__name__}")
    return [{"title": str(pg.get("title", "")), "body": str(pg.get("body", ""))}
            for pg in raw if isinstance(pg, dict)]

def _gen_pages_from_state(state: Dict[str,Any] | None) -> List[Dict[str,str]]:
    # mock generation from family brain state
    pages=[]
    if not state:
        pages=[
            {"title":"Family Policies","body":"# Policies\n- Roth $7000\n- Emergency 6mo\n- Vacation fund"},
            {"title":"Bills","body":"# Bills\n- Due dates calendar\n- Auto-pay status"},
        ]
    else:
        # state has accounts etc
        pages.append({"title":"Finances","body":f"# Finances\nAccounts: {len(state.get('accounts',[]))}\nEF: {state.get('burn',0)*6}"})
    return pages

def run(model: Any = None, tokenizer: Any = None, mode: str = "mock", **kw):
    import random
    if mode != "mock":
        # Simulated mass must never be labeled real (previous code passed mode through,
        # so mode="real" returned a random number presented as a live measurement).
        return {"skill":"family-brain-wiki","mode":"real","measured":None,"pass":False,
                "bar":"mass>=0.06",
                "error":"real mode not implemented: S2 injection mass needs a live model readout"}
    random.seed(kw.get("seed",7))
    wiki_info = _scan_family_wiki()
    pages_source = "generated"
    export_error = None
    pages: List[Dict[str, str]] = []
    export_path = kw.get("export_path")
    if export_path:
        try:
            pages = _load_export(export_path)
            pages_source = "export"
            wiki_info.insert(0, {"source": str(export_path), "type": "localStorage-export"})
        except (OSError, ValueError, json.JSONDecodeError) as e:
            export_error = f"{type(e).__name__}: {e}"
    if not pages:
        pages = _gen_pages_from_state(kw.get("state"))
    # simulate S2 injection mass (mock only)
    mass = 0.06 + random.uniform(0,0.08) + 1e-5*len(pages)
    measured={"n_wiki_sources": len(wiki_info), "n_pages_generated": len(pages), "reportability_mass": mass, "pages": [p["title"] for p in pages], "sources": wiki_info[:3], "pages_source": pages_source, "storage_key": STORAGE_KEY}
    if export_error:
        measured["export_error"] = export_error
    return {"skill":"family-brain-wiki","mode":"mock","measured":measured,"pass": mass>=0.06,"bar":"mass>=0.06","wiki_pages": pages}
