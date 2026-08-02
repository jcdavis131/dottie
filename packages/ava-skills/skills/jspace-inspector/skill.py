# Solo personal project, no connection to employer, built with public/free-tier only
"""jspace-inspector: inspect J-space slots; real mode runs the full canonical J-test
set (spider_ant, france_china, soccer_rugby, spanish_french, safety_blackmail) via the
sibling ava-open-harness `jspace_all` runner and aggregates its per-test records."""

from __future__ import annotations

import os
import pathlib
import random
import sys
from typing import Any


def describe() -> dict[str, Any]:
    """Routing metadata read from SKILL.md frontmatter — the single source of truth."""
    from pathlib import Path

    here = Path(__file__).resolve().parent
    try:
        from skills.loader import describe_from_manifest
    except ImportError:  # loaded standalone without the skills package on sys.path
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_ava_skills_loader", here.parent / "loader.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        describe_from_manifest = mod.describe_from_manifest
    return describe_from_manifest(here)


def _mock_top_concepts(seed: int, k: int = 8) -> list[dict[str, Any]]:
    random.seed(seed)
    words = [
        "spider",
        "ant",
        "france",
        "china",
        "soccer",
        "rugby",
        "spanish",
        "french",
        "blackmail",
        "threat",
        "paris",
        "beijing",
    ]
    scores = sorted([random.uniform(0.01, 0.15) for _ in words], reverse=True)
    return [{"token": w, "prob": p} for w, p in zip(words, scores, strict=False)][:k]


VALID_MODES = ("mock", "real")
SKILL_NAME = "jspace-inspector"


def run(
    model: Any = None,
    tokenizer: Any = None,
    mode: str = "mock",
    eval_name: str | None = None,
    **kw,
) -> dict[str, Any]:
    # A membership guard, NOT decoration. Without it this function tested `mode == "mock"`
    # and let EVERYTHING ELSE fall through to the real path — so a typo, a case variant or
    # "" silently ran the expensive real branch AND stamped the result `"mode": "real"`.
    # Probed 2026-08-02: `run(mode="banana")` returned a payload labelled mode="real".
    #
    # That is a provenance lie in a repo whose rule is that numbers come from real sources:
    # the one field a caller would use to tell mock from real was reporting whatever the
    # code did, not what was asked for. Same defect class as safety-scanner's fail-open
    # (e63954d), which is why the shape of this guard matches it deliberately.
    if mode not in VALID_MODES:
        raise ValueError(
            f"{SKILL_NAME}: unknown mode {mode!r}; expected one of {VALID_MODES}. "
            "Refusing to guess — an unrecognised mode previously ran the real path and "
            "labelled its own output \"real\"."
        )
    if mode == "mock":
        seed = kw.get("seed", 1234)
        random.seed(seed)
        s1_broadcast = random.uniform(0.15, 0.22)
        s2_broadcast = random.uniform(0.18, 0.28)
        critic_mass = random.uniform(0.04, 0.12)
        planner_broadcast = random.uniform(0.17, 0.24)
        mass = random.uniform(0.04, 0.12)
        # avoid exact mock literal 0.064 -> add jitter
        if abs(mass - 0.064) < 1e-4:
            mass += 0.0011
        measured = {
            "S1_fast": {
                "slots": 32,
                "hl": 8,
                "broadcast": s1_broadcast,
                "target": 0.18,
                "w": 0.6,
            },
            "S2_slow": {
                "slots": 64,
                "hl": 300,
                "broadcast": s2_broadcast,
                "target": 0.22,
                "verbalizable": mass,
                "verbalizable_target": 0.065,
                "w": 0.8,
            },
            "Critic": {
                "slots": 16,
                "hl": 30,
                "broadcast": 0.19,
                "safety_mass": critic_mass,
                "target": 1.0,
                "w": 1.0,
            },
            "Planner": {
                "slots": 32,
                "hl": 150,
                "broadcast": planner_broadcast,
                "target": 0.20,
                "w": 0.7,
            },
            "inter_mi": {"cos": random.uniform(0.35, 0.55), "target": 0.45, "w": 0.3},
            "routing_kl": {"kl": random.uniform(0.1, 0.5), "w": 0.4},
            "top_concepts": _mock_top_concepts(seed),
        }
        passed = 0.02 <= mass <= 0.20
        return {
            "skill": "jspace-inspector",
            "mode": "mock",
            "measured": measured,
            "pass": passed,
            "bar": "mass in [0.02,0.20] and broadcast 20% target",
            "eval_requested": eval_name,
        }

    # Real mode runs the FULL canonical J-test set via the sibling ava-open-harness
    # registry, aggregating one record per test. Each record's full content (incl.
    # any honest-failure 'error' explanation) is propagated rather than stripped —
    # a bare measured=None FAIL is indistinguishable from a genuinely measured
    # failure. Per-test exceptions become per-test error records, so one crashing
    # test cannot erase the others' results.
    canonical = [
        "spider_ant",
        "france_china",
        "soccer_rugby",
        "spanish_french",
        "safety_blackmail",
    ]
    bar = ">=3/5 canonical J-tests PASS"
    try:
        # Resolve ava-open-harness: DOTTIE_ROOT/packages first (dottie monorepo),
        # then the existing relative sibling probe (standalone checkout layout).
        harness_root = None
        dottie_root = os.environ.get("DOTTIE_ROOT")
        if dottie_root:
            candidate = pathlib.Path(dottie_root) / "packages" / "ava-open-harness"
            if candidate.exists():
                harness_root = candidate
        if harness_root is None:
            harness_root = (
                pathlib.Path(__file__).resolve().parents[2].parent / "ava-open-harness"
            )
        if harness_root.exists() and str(harness_root) not in sys.path:
            sys.path.insert(0, str(harness_root))
        import harness.evals.jspace_tests  # noqa: F401 — registers the canonical tests
        from harness.registry import get_eval
    except Exception as e:
        return {
            "skill": "jspace-inspector",
            "mode": "real",
            "measured": None,
            "pass": False,
            "bar": bar,
            "error": f"ava-open-harness not importable: {e}",
        }
    records: dict[str, Any] = {}
    for name in canonical:
        try:
            records[name] = get_eval(name)["fn"](
                model, tokenizer, kw.get("device", "cpu")
            )
        except Exception as e:
            records[name] = {
                "test": name,
                "measured": None,
                "pass": False,
                "error": str(e),
            }
    passed = sum(1 for r in records.values() if r.get("pass"))
    return {
        "skill": "jspace-inspector",
        "mode": "real",
        "measured": {"passed": passed, "total": len(canonical), "details": records},
        "pass": passed >= 3,
        "bar": bar,
    }
