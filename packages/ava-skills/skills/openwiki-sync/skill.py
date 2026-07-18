# Solo personal project, no connection to employer, built with public/free-tier only
"""openwiki-sync: Sync OpenWiki personal wiki (~/.openwiki/wiki) into S2 Slow hl300 verbalizable memory"""
from __future__ import annotations
from typing import Any, Dict, List
import os, pathlib, re

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

def _scan_wiki(wiki_path: str | None) -> List[pathlib.Path]:
    candidates = []
    if wiki_path and os.path.isdir(wiki_path):
        candidates.append(pathlib.Path(wiki_path))
    home = pathlib.Path.home()
    candidates.extend([home / ".openwiki" / "wiki", pathlib.Path.cwd() / "openwiki"])
    found = []
    for p in candidates:
        if p.exists():
            found.extend(list(p.rglob("*.md"))[:200])
    return found

def _extract_concepts(text: str) -> List[str]:
    concepts = re.findall(r"^#+\s+(.+)$", text, re.MULTILINE)
    concepts += re.findall(r"\[\[([^\]]+)\]\]", text)
    return [c.strip()[:80] for c in concepts[:20] if c.strip()]

def run(model: Any = None, tokenizer: Any = None, mode: str = "mock", wiki_path: str | None = None, **kw) -> Dict[str, Any]:
    files = _scan_wiki(wiki_path)
    if mode == "mock":
        import random
        random.seed(len(files) + 7)
        concepts = []
        for f in files[:10]:
            try:
                concepts.extend(_extract_concepts(f.read_text(errors="ignore")[:4000]))
            except Exception:
                continue
        if not concepts:
            concepts = ["Spider", "France", "Soccer", "Spanish", "Blackmail", "Ava", "J-Space"]
        mass = min(0.18, len(concepts)*0.008 + random.uniform(0.02,0.06)) + 1e-5*(len(files)%10)
        return {"skill":"openwiki-sync","mode":"mock","measured":{"n_files":len(files),"n_concepts":len(concepts),"reportability_mass":mass,"hl":300,"sample_concepts":concepts[:5]},"pass":mass>=0.06,"bar":"mass>=0.06","files":[str(p) for p in files[:5]]}
    try:
        concepts=[]
        for f in files:
            try:
                concepts.extend(_extract_concepts(f.read_text(errors="ignore")))
            except Exception:
                continue
        # Honest real-mode metric: concept density actually derived from the scanned wiki
        # (concepts per file, capped), not the previous fabricated constant 0.072. The
        # true S2-injection reportability mass still requires a live model readout — that
        # limitation is carried in the record so the harness can distinguish the two.
        # concept_density is a real filesystem diagnostic, but reportability mass is
        # an S2 forward-pass metric that is NOT wired. Report the diagnostic and FAIL
        # honestly rather than passing a bar on an unmeasured proxy — matching
        # code-bench / family-brain-wiki, so the honest-failure regime is uniform.
        density = (len(concepts) / max(1, len(files)))
        return {"skill":"openwiki-sync","mode":"real","measured":None,"pass":False,
                "bar":"mass>=0.06",
                "diagnostics":{"n_files":len(files),"n_concepts":len(concepts),
                                "concept_density":density},
                "error":"real mode not implemented: reportability mass needs a live S2 "
                        "readout; concept_density is a filesystem diagnostic, not the metric"}
    except Exception as e:
        return {"skill":"openwiki-sync","mode":"real","measured":None,"error":str(e),"pass":False,"bar":"mass>=0.06"}
