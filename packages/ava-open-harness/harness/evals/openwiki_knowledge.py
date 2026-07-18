"""
openwiki_knowledge.py — test if model recalls facts from wiki (openwiki personal → S2)

Mock mode: seed-varying deterministic mock over discovered wiki files.
Real mode: measures the LIVE System-2 verbalizable mass (out["jspace"]["system2"]
["verbalizable_mass"]) from real forward passes over wiki page text. If no wiki
corpus exists, real mode fails honestly — it never simulates a corpus.

Solo personal project, no connection to employer, built with public/free-tier only
"""
from __future__ import annotations
from typing import Any, Dict, List
from ..registry import register_eval
from ..common import (
    MockModel, real_unimplemented, factory_modules, factory_root, attach_smoke_labels,
)
import os, random, pathlib

BAR = "mass>=0.06"

def scan_wiki(wiki_path: str | None = None) -> List[pathlib.Path]:
    candidates = []
    if wiki_path and os.path.isdir(wiki_path):
        candidates.append(pathlib.Path(wiki_path))
    # default locations
    home = pathlib.Path.home()
    candidates.extend([
        home / ".openwiki" / "wiki",
        pathlib.Path.cwd() / "openwiki",
        pathlib.Path.cwd().parent / "family-brain-os" / "src" / "wiki",  # family brain inspired version
    ])
    found = []
    for p in candidates:
        if p.exists():
            found.extend(list(p.rglob("*.md"))[:50])
    return found


def _real_s2_mass(model: Any, tokenizer: Any, device: str,
                  wiki_files: List[pathlib.Path], mods: Dict[str, Any],
                  max_files: int = 20, max_tokens: int = 256) -> Dict[str, Any]:
    """LIVE S2 verbalizable mass per wiki page — real forward passes only."""
    forward_out = mods["evals.common"].forward_out
    per_file = []
    masses = []
    for f in wiki_files[:max_files]:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ids = tokenizer.encode(text)[:max_tokens]
        if len(ids) < 4:
            continue
        out = forward_out(model, ids, task_type="deliberate", device=device)
        mass = float(out["jspace"]["system2"]["verbalizable_mass"].item())
        masses.append(mass)
        per_file.append({"file": str(f), "tokens": len(ids), "s2_mass": mass})
    avg = sum(masses) / len(masses) if masses else 0.0
    return {
        "n_wiki_files": len(wiki_files),
        "sampled": len(masses),
        "recall_mass": avg,
        "per_file": per_file[:5],
        "note": "recall_mass = mean live S2 verbalizable_mass over wiki page forwards",
    }

@register_eval(name="openwiki_knowledge", description="Wiki recall: S2 reportability mass for openwiki pages", group="knowledge")
def openwiki_knowledge(model: Any, tokenizer: Any, device: str="cpu", wiki_path: str | None = None, **kw) -> Dict[str,Any]:
    if not isinstance(model, MockModel):
        mods, err = factory_modules()
        if mods is None:
            return real_unimplemented(
                "openwiki_knowledge", BAR,
                f"factory evals not importable from {factory_root()} ({err})",
            )
        wiki_files = scan_wiki(wiki_path)
        if not wiki_files:
            # Real mode NEVER simulates a corpus (the mock path's "mock corpus"
            # shortcut is a mock-mode-only convenience).
            return real_unimplemented(
                "openwiki_knowledge", BAR,
                "no wiki corpus found (--wiki-path, ~/.openwiki/wiki or ./openwiki); "
                "real mode does not simulate a corpus",
            )
        measured = _real_s2_mass(model, tokenizer, device, wiki_files, mods)
        if measured["sampled"] == 0:
            return real_unimplemented(
                "openwiki_knowledge", BAR,
                f"wiki files found ({measured['n_wiki_files']}) but none tokenized to >=4 tokens",
            )
        return attach_smoke_labels(
            {"test": "openwiki_knowledge", "measured": measured,
             "pass": measured["recall_mass"] >= 0.06, "bar": BAR})
    wiki_files = scan_wiki(wiki_path)
    if not wiki_files:
        random.seed(model.seed)  # reproducible across runs (was unseeded)
        measured = {"n_wiki_files": 0, "recall_mass": random.uniform(0.05, 0.15),
                    "note": "no wiki found, using mock corpus from specs/02_data"}
        passed = measured["recall_mass"] >= 0.06
        return {"test":"openwiki_knowledge", "measured": measured, "pass": bool(passed), "bar":BAR}

    # mock recall: each wiki page title -> seeded concept probe
    scores = []
    for f in wiki_files[:20]:
        random.seed(hash(f.name) % 10000 + model.seed)
        scores.append(random.uniform(0.04, 0.18))
    avg = sum(scores)/len(scores) if scores else 0.0
    measured = {"n_wiki_files": len(wiki_files), "sampled": len(scores), "recall_mass": avg, "files": [str(p) for p in wiki_files[:5]]}
    return {"test":"openwiki_knowledge", "measured": measured, "pass": avg>=0.06, "bar":BAR}
