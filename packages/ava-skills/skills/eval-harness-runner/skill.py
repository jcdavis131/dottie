# Solo personal project, no connection to employer, built with public/free-tier only
"""eval-harness-runner: Run ava-open-harness, gate stable checkpoint"""
from __future__ import annotations
from typing import Any, Dict
import sys, pathlib

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

def run(model: Any = None, tokenizer: Any = None, mode: str = "mock", **kw):
    # try to import harness
    try:
        # add ava-open-harness to path
        here = pathlib.Path(__file__).resolve().parents[2]
        harness_path = here.parent / "ava-open-harness"
        if harness_path.exists() and str(harness_path) not in sys.path:
            sys.path.insert(0, str(harness_path))
        from harness.runner import run_harness
        res = run_harness(eval_names=kw.get("eval","jspace_all,frontier_rubric"), mode=mode, ckpt=kw.get("ckpt"), preset=kw.get("preset","nano"), verbose=False)
        passed = res["meta"]["passed"]
        total = res["meta"]["total"]
        # Gate on passed==total: the default eval set has 2 entries, so a fixed
        # ">=3" bar could never pass regardless of results.
        return {"skill":"eval-harness-runner","mode":mode,"measured":{"passed":passed,"total":total,"wall_s":res["meta"].get("wall_s",0),"results":res["evals"]},"pass": total>0 and passed==total,"bar":"all requested evals PASS"}
    except Exception as e:
        # Honest failure — NEVER fabricate a pass count. Previously this returned
        # random.randint(3,5) (always >=3 => guaranteed pass), which turned the
        # upstream anti-fabrication RuntimeError into a fake real-mode PASS: exactly
        # the antipattern the harness exists to prevent.
        return {"skill":"eval-harness-runner","mode":mode,"measured":None,"pass":False,
                "bar":"all requested evals PASS",
                "error":f"harness could not run in mode={mode}: {str(e)[:200]}"}
