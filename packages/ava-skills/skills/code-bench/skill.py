# Solo personal project, no connection to employer, built with public/free-tier only
"""code-bench: Exec-verified Python generation (P2 code)"""
from __future__ import annotations
from typing import Any, Dict
import subprocess, tempfile, pathlib

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

def exec_verify(code: str, timeout: int = 3) -> Dict[str,Any]:
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as tf:
        tf.write(code)
        tf.flush()
        path = tf.name
    try:
        res = subprocess.run(["python3", path], capture_output=True, text=True, timeout=timeout)
        return {"ok": res.returncode==0, "stdout": res.stdout[:500], "stderr": res.stderr[:500], "returncode": res.returncode}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            pathlib.Path(path).unlink()
        except Exception:
            pass

TASKS = [
    ("add", "def add(a,b): return a+b\nprint(add(2,3))", "5"),
    ("fact", "def fact(n): return 1 if n<=1 else n*fact(n-1)\nprint(fact(4))", "24"),
]

def run(model: Any = None, tokenizer: Any = None, mode: str = "mock", **kw):
    if mode=="mock":
        passes=0
        results=[]
        for name,code,expected in TASKS:
            r=exec_verify(code)
            ok = expected in r.get("stdout","")
            passes+=int(ok)
            results.append({"task":name,"ok":ok,"stdout":r.get("stdout","")[:100]})
        measured={"pass_rate": passes/len(TASKS), "results": results, "bias_target":"code_branch [0.25,0.45,0.05,0.25]"}
        return {"skill":"code-bench","mode":"mock","measured":measured,"pass": measured["pass_rate"]>=0.5,"bar":"pass_rate>=0.5"}
    # Real mode needs model generations fed through the same exec_verify() loop above.
    # Until a generate() path is wired, fail honestly — never report an invented pass_rate.
    return {"skill":"code-bench","mode":"real","measured":None,"pass":False,
            "bar":"pass_rate>=0.5",
            "error":"real mode not implemented: generate solutions with the model, then "
                    "exec_verify() them exactly like the mock path (previous constant 0.8 was fabricated)"}
