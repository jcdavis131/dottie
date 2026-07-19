"""
openwiki_adapter.py — bridge ~/.openwiki/wiki → S2 Slow hl=300 verbalizable memory

Solo personal project, no connection to employer, built with public/free-tier only

Maps:
- Personal mode builds local personal brain wiki in ~/.openwiki/wiki from configured sources like local repositories, Gmail, Notion, Web Search, Hacker News, and X/Twitter
- → S2 Slow Workspace (hl=300 deliberate long-term memory) as verbalizable concepts with reportability loss
- Code mode builds repo documentation in openwiki/ → S1 Fast + Planner

Implements per docs/OPENWIKI_INTEGRATION.md:
- Watches ~/.openwiki/wiki/*.md markdown files
- Embeds them into S2 Slow slots (hl=300) as verbalizable concepts
- On eval, top_concepts mass should correlate with wiki pages about that concept (France→China generalization test via wiki)
- Deterministic connector pattern: raw under ~/.openwiki/connectors/<connector>/raw/ then agent synthesizes wiki — we read final wiki but also support manifest reading

Mypyc-ready: typed, lazy imports, mock fallback no torch needed.
"""

from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional
import os, pathlib, re, json, math, random
from dataclasses import dataclass

WIKI_SEARCH_PATHS = [
    "{home}/.openwiki/wiki",
    "{cwd}/openwiki",
    "{factory}/openwiki",
    "{home}/.openwiki/connectors",
]

@dataclass
class WikiPageParsed:
    path: str
    title: str
    slug: str
    content: str
    concepts: List[str]
    tags: List[str]
    source: str  # connector name inferred
    reportability_mass: float  # 0-1, for S2 hl300

def _lazy_torch():
    try:
        import torch
        return torch
    except ImportError:
        return None

def _resolve_paths(wiki_root: Optional[str] = None) -> List[pathlib.Path]:
    home = pathlib.Path.home()
    cwd = pathlib.Path.cwd()
    factory = pathlib.Path(__file__).resolve().parents[2]
    candidates: List[pathlib.Path] = []
    if wiki_root:
        candidates.append(pathlib.Path(wiki_root))
    for tmpl in WIKI_SEARCH_PATHS:
        p = pathlib.Path(
            tmpl.format(home=str(home), cwd=str(cwd), factory=str(factory))
        )
        if p.exists():
            candidates.append(p)
    # dedup
    uniq = []
    seen = set()
    for p in candidates:
        rp = str(p.resolve()) if p.exists() else str(p)
        if rp not in seen:
            seen.add(rp)
            if p.exists():
                uniq.append(p)
    # also include family-brain simulated location if present
    fb_wiki = pathlib.Path.home() / "workspace" / "family-brain-os" / "src" / "wiki"
    if fb_wiki.exists():
        uniq.append(fb_wiki)
    return uniq

def _extract_concepts(text: str) -> List[str]:
    # headings, wiki-links, bold terms
    concepts = re.findall(r"^#+\s+(.+)$", text, re.MULTILINE)
    concepts += re.findall(r"\[\[([^\]]+)\]\]", text)
    concepts += re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b", text)[:10]
    cleaned = []
    for c in concepts:
        c = c.strip()[:80]
        if len(c) >= 3 and c not in cleaned:
            cleaned.append(c)
        if len(cleaned) >= 20:
            break
    return cleaned

def _extract_tags(text: str) -> List[str]:
    # tags like #finance, frontmatter tags:
    tags = re.findall(r"#([a-z0-9_-]{2,20})", text.lower())
    # frontmatter
    m = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if m:
        tags += re.findall(r"tags:\s*\[([^\]]+)\]", m.group(1).lower())
    return list(dict.fromkeys(tags))[:12]

def _infer_source(p: pathlib.Path) -> str:
    # try to infer from path structure ~/.openwiki/connectors/<name>/raw or wiki folder name
    parts = p.parts
    if "connectors" in parts:
        idx = parts.index("connectors")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    if "openwiki" in parts:
        return "code"
    return "manual"

def parse_wiki_file(path: pathlib.Path) -> WikiPageParsed:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        text = ""
    # title = first markdown H1 or filename
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = m.group(1).strip()[:120] if m else path.stem.replace("-", " ").title()[:120]
    slug = path.stem[:80]
    concepts = _extract_concepts(text)
    tags = _extract_tags(text)
    source = _infer_source(path)
    # reportability mass heuristic: more concepts + longer content = higher mass, capped
    base = 0.02 + min(0.16, len(concepts) * 0.008 + min(len(text), 8000) / 8000 * 0.06)
    # deterministic jitter by filename hash for reproducibility
    jitter = (sum(b for b in path.name.encode()) % 100) / 1000.0
    mass = min(0.18, base + jitter)
    return WikiPageParsed(
        path=str(path),
        title=title,
        slug=slug,
        content=text[:20000],
        concepts=concepts,
        tags=tags,
        source=source,
        reportability_mass=mass,
    )

def scan_wiki(wiki_root: Optional[str] = None, limit: int = 200) -> List[WikiPageParsed]:
    roots = _resolve_paths(wiki_root)
    files: List[pathlib.Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".md":
            files.append(root)
        elif root.is_dir():
            # if it's connectors dir, look for raw manifests but also final wiki
            if root.name == "connectors":
                # walk connectors/*/raw/manifest.json for reference, but main scan is wiki elsewhere
                continue
            # for wiki roots, rglob
            files.extend(list(root.rglob("*.md"))[: limit // max(1, len(roots))])
    # also directly scan default wiki path even if not in candidates (home/.openwiki/wiki)
    default_wiki = pathlib.Path.home() / ".openwiki" / "wiki"
    if default_wiki.exists() and default_wiki not in roots:
        files.extend(list(default_wiki.rglob("*.md"))[: limit // 2])

    # dedup by path
    uniq_files = []
    seen = set()
    for f in files:
        rp = str(f.resolve()) if f.exists() else str(f)
        if rp not in seen and f.suffix == ".md":
            seen.add(rp)
            uniq_files.append(f)
        if len(uniq_files) >= limit:
            break

    parsed = [parse_wiki_file(p) for p in uniq_files]
    # sort by mass descending so S2 gets strongest first (reportability)
    parsed.sort(key=lambda x: x.reportability_mass, reverse=True)
    return parsed

def build_manifests_from_connectors() -> List[Dict[str, Any]]:
    """
    Mirrors OpenWiki deterministic pattern:
    Deterministic connector tools write raw data and manifests under ~/.openwiki/connectors/<connector>/raw/, then agent synthesizes wiki
    We read those manifests if present.
    """
    manifests = []
    base = pathlib.Path.home() / ".openwiki" / "connectors"
    if not base.exists():
        return manifests
    for connector_dir in base.iterdir():
        if not connector_dir.is_dir():
            continue
        raw_dir = connector_dir / "raw"
        if not raw_dir.exists():
            continue
        # find manifest.json
        manifest_files = list(raw_dir.glob("manifest.json")) + list(raw_dir.glob("*.json"))
        for mf in manifest_files[:3]:
            try:
                data = json.loads(mf.read_text(errors="ignore")[:5000])
                manifests.append({
                    "connector": connector_dir.name,
                    "manifestPath": str(mf),
                    "rawCount": data.get("rawCount") or data.get("count") or len(list(raw_dir.iterdir())),
                    "sampleKeys": data.get("sampleKeys", [])[:5] if isinstance(data.get("sampleKeys"), list) else [],
                    "lastSync": data.get("lastSync") or "",
                })
            except Exception:
                manifests.append({
                    "connector": connector_dir.name,
                    "manifestPath": str(mf),
                    "rawCount": len(list(raw_dir.iterdir())),
                    "sampleKeys": [],
                    "lastSync": "",
                })
    return manifests

class OpenWikiAdapter:
    """
    Bridge: wiki pages → S2 Slow hl=300 slots
    For real model: embed concepts into S2 workspace with hl=300 decay
    For mock: return reportability metrics
    """
    def __init__(self, wiki_root: Optional[str] = None):
        self.wiki_root = wiki_root
        self.pages: List[WikiPageParsed] = []

    def ingest(self, limit: int = 200) -> Dict[str, Any]:
        self.pages = scan_wiki(self.wiki_root, limit=limit)
        manifests = build_manifests_from_connectors()
        total_mass = sum(p.reportability_mass for p in self.pages)
        avg_mass = total_mass / len(self.pages) if self.pages else 0.0
        # France→China generalization test scaffolding:
        # if we have a page about France, we can test capital/language/continent/currency generalization
        has_france = any("france" in p.title.lower() or "france" in " ".join(p.concepts).lower() for p in self.pages)
        return {
            "n_files": len(self.pages),
            "total_reportability_mass": total_mass,
            "avg_mass": avg_mass,
            "sample_titles": [p.title for p in self.pages[:5]],
            "sample_concepts": [c for p in self.pages[:3] for c in p.concepts[:3]][:10],
            "manifests": manifests,
            "has_france_for_generalization_test": has_france,
            "hl_target": 300,
        }

    def to_s2_slots(self, model: Any = None) -> Dict[str, Any]:
        """
        Real mode: if torch model has S2 workspace, inject embeddings.
        Mock: return dict describing what would be injected.
        Expected model interface from multi_jspace_module.MultiJSpaceLosses / model_1b:
        - model has method get_workspace ? For now we simulate via storing in model._openwiki_memory
        """
        if not self.pages:
            self.ingest()

        torch = _lazy_torch()
        if model is None or torch is None:
            # mock injection
            slots = [
                {
                    "title": p.title,
                    "concepts": p.concepts[:5],
                    "mass": p.reportability_mass,
                    "hl": 300,
                    "source": p.source,
                    "tags": p.tags[:3],
                }
                for p in self.pages[:20]
            ]
            return {"mode": "mock", "s2_slots": slots, "hl": 300, "count": len(slots)}

        # real torch path — build simple embedding bag per page into S2
        try:
            # attempt to create embedding tensor: mean of concept hashes as dummy, replace with real tokenizer.encode if available
            embeds = []
            for p in self.pages[:32]:
                # hash concepts to vector
                vec = torch.zeros(128)
                for i, c in enumerate(p.concepts[:8]):
                    h = sum(ord(ch) for ch in c) % 128
                    vec[h] += p.reportability_mass
                vec = vec / (torch.norm(vec) + 1e-6)
                embeds.append(vec)

            if embeds:
                stack = torch.stack(embeds)  # [N, 128]
                # try to inject into model if it has attribute
                if hasattr(model, "_openwiki_memory"):
                    model._openwiki_memory = stack
                else:
                    setattr(model, "_openwiki_memory", stack)
                    setattr(model, "_openwiki_pages", [p.title for p in self.pages])

            return {"mode": "real", "injected": len(embeds), "hl": 300, "mass": float(sum(p.reportability_mass for p in self.pages[:32]))}
        except Exception as e:
            return {"mode": "real", "error": str(e), "count": len(self.pages)}

def main():
    import argparse
    ap = argparse.ArgumentParser(description="OpenWiki → S2 bridge")
    ap.add_argument("--wiki-root", default=None, help="override wiki path, default ~/.openwiki/wiki")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--real", action="store_true", help="attempt real torch injection if ckpt/model available")
    ap.add_argument("--ckpt", default=None)
    args = ap.parse_args()

    adapter = OpenWikiAdapter(wiki_root=args.wiki_root)
    stats = adapter.ingest(limit=args.limit)
    print(f"[OpenWikiAdapter] Ingested {stats['n_files']} files avg mass {stats['avg_mass']:.3f} total {stats['total_reportability_mass']:.3f}")
    print(f"Sample titles: {stats['sample_titles']}")
    print(f"Manifests: {len(stats['manifests'])} from ~/.openwiki/connectors/*/raw/")
    if stats['has_france_for_generalization_test']:
        print("[OpenWikiAdapter] France→China generalization probe available (capital/language/continent/currency)")

    if args.real:
        torch = _lazy_torch()
        model = None
        if torch and args.ckpt and os.path.exists(args.ckpt):
            try:
                factory_root = pathlib.Path(__file__).resolve().parents[1]
                import sys
                if str(factory_root) not in sys.path:
                    sys.path.insert(0, str(factory_root))
                from model_1b import get_model
                model = get_model()
                sd = torch.load(args.ckpt, map_location="cpu")
                model.load_state_dict(sd.get("model", sd), strict=False)
                print(f"Loaded ckpt {args.ckpt}")
            except Exception as e:
                print(f"Failed to load ckpt {args.ckpt}: {e}")
        result = adapter.to_s2_slots(model=model)
        print(f"Injection: {result}")

if __name__ == "__main__":
    main()
