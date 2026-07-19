"""
Skillbooks — modular capability packages versioned like code

Solo personal project, no connection to employer, built with public/free-tier only

Skills in Unified Auto are modular capability packages: docs, Python code, bootstrap notebooks.
Skillbook: anyone can create/share custom skills without diff. Built on Bento Notebooks:
edit skill and use it immediately (no code push), iterate latest vs published, visibility private/team/everyone.
Fastest way to create one: get workflow working in conversation with Advanced Auto and tell it to save as skillbook.

Real example: needed skill to debug session failures. Told agent "create skillbook for diagnosing cf session failures based on this notebook" and iterated until it worked. ~1 hour. Whole team uses it.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time
import json
import os
from pathlib import Path

@dataclass
class SkillBook:
    name: str
    description: str
    code: str  # Python code with host calls
    docs: str  # documentation
    bootstrap_notebook: str  # bootstrap notebook
    version: str = "latest"  # latest vs published
    visibility: str = "private"  # private, team, everyone
    created_at: float = field(default_factory=time.time)
    saves: int = 0
    
    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "visibility": self.visibility,
            "created_at": self.created_at,
            "saves": self.saves,
            "code_len": len(self.code),
            "docs_len": len(self.docs),
        }

class SkillBookManager:
    """Manages Skillbooks — modular capability packages, versioned, shareable without diff"""
    
    def __init__(self, root: Path = Path("dottie/skills")):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.books: Dict[str, SkillBook] = {}
        self._load_existing()
    
    def _load_existing(self):
        if not self.root.exists():
            return
        for p in self.root.glob("*.json"):
            try:
                data = json.loads(p.read_text())
                # lightweight load — detailed code defer-loaded
                self.books[data["name"]] = SkillBook(
                    name=data["name"],
                    description=data.get("description", ""),
                    code="",  # defer-loaded
                    docs="",
                    bootstrap_notebook="",
                    version=data.get("version", "latest"),
                )
            except:
                pass
    
    def create_from_conversation(self, name: str, description: str, working_code: str, docs: str = "") -> SkillBook:
        """
        Fastest way to create one: get workflow working in conversation with Advanced Auto
        and tell it to save as skillbook.
        """
        notebook = f'''
# Bootstrap notebook for {name}
# Edit and use immediately (no code push)

# {description}

{working_code}

# Test:
# await run_{name}_workflow()
'''
        
        book = SkillBook(
            name=name,
            description=description,
            code=working_code,
            docs=docs or f"# {name}\n\n{description}",
            bootstrap_notebook=notebook,
            version="latest",
            visibility="private",
        )
        
        # save immediately — no diff needed, team can use it
        path = self.root / f"{name}.python.py"
        path.write_text(working_code)
        (self.root / f"{name}.md").write_text(book.docs)
        (self.root / f"{name}.ipynb.json").write_text(json.dumps({"cells": [notebook]}, indent=2))
        (self.root / f"{name}.json").write_text(json.dumps(book.to_dict(), indent=2))
        
        self.books[name] = book
        return book
    
    def publish(self, name: str, visibility: str = "everyone"):
        """Control visibility private/team-scoped/shared with everyone"""
        book = self.books.get(name)
        if not book:
            return None
        book.version = "published"
        book.visibility = visibility
        book.saves += 1
        # overwrite with published version
        (self.root / f"{name}.json").write_text(json.dumps(book.to_dict(), indent=2))
        return book
    
    def list(self) -> List[Dict]:
        return [b.to_dict() for b in self.books.values()]

def create_ava_skillbooks(manager: SkillBookManager):
    """Convert Dottie's 8 starter skills + 3 new ones to Skillbooks"""
    
    skills = [
        ("jspace-inspector", "Inspect J-Space S1 Fast hl=8 S2 hl=300 Critic hl=30 Planner hl=150, hl_est, route_probs", "latest"),
        ("openwiki-sync", "Sync ~/.openwiki/wiki -> S2 Slow hl=300 verbalizable memory", "latest"),
        ("logic-prover", "Phi Method B logic textbook prover for phase0", "latest"),
        ("code-bench", "Code repo 50% + long 32k eval, S2 hl=350 bias", "latest"),
        ("safety-scanner", "Critic hl=30-35 early warning leverage/blackmail 4-5 tok", "latest"),
        ("memory-router", "Router + arbitration veto routing KL", "latest"),
        ("eval-harness-runner", "Branch harness mock/real, frontier rubric 11-cat", "latest"),
        ("family-brain-wiki", "Family Brain local personal brain wiki client-only", "latest"),
        # 3 new unlocked by LLMVM
        ("diagnose-wsd-spike", "Diagnose WSD phase transition loss spikes >3x median, RoPE 10k->1M", "latest"),
        ("audit-jspace-leak", "Audit codebase for causal mask missing, future->past broadcast, constant verbalizable_mass", "latest"),
        ("discover-dataset-fast", "Fast dataset discovery: 58 HF candidates filtered in one cell with md5 13.5s", "latest"),
    ]
    
    for name, desc, ver in skills:
        if name not in manager.books:
            manager.create_from_conversation(
                name=name,
                description=desc,
                working_code=f"# {name} — skillbook placeholder\nasync def run_{name.replace('-','_')}_workflow():\n    print('Running {name}: {desc}')\n    return True\n",
                docs=f"# {name}\n\n{desc}\n\nVersion: {ver}\n"
            )
    
    return manager.list()
