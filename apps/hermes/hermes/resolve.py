# Solo personal project, no connection to employer, built with public/free-tier only
"""Dottie-aware sibling resolution — how Hermes finds the factory, harness, skills, and ETL.

Mirrors the resolution style of ``packages/ava-open-harness/harness/common.py::factory_root``:
explicit env vars win, then path-relative monorepo siblings (this file lives at
``<dottie>/apps/hermes/hermes/``), then the documented default factory checkout. Every getter
either returns a verified real path or raises :class:`HermesResolutionError` with an honest
message saying exactly what was probed — a missing dependency is reported, never papered over.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# The documented standalone factory checkout (same default the harness uses).
DEFAULT_FACTORY_ROOT = Path("/home/user/ava-agi-factory-v6-4")

_HERE = Path(__file__).resolve().parent  # <dottie>/apps/hermes/hermes


class HermesResolutionError(RuntimeError):
    """A required monorepo sibling could not be found. The message lists every probed path."""


def dottie_root() -> Path:
    """Monorepo root: env ``DOTTIE_ROOT`` wins, else path-relative from this file."""
    env = os.environ.get("DOTTIE_ROOT")
    if env:
        return Path(env)
    return _HERE.parent.parent.parent  # apps/hermes/hermes -> apps/hermes -> apps -> <dottie>


def _factory_candidates() -> List[Path]:
    """Ordered factory-code candidates. Env AVA_FACTORY_ROOT is honored verbatim first
    (matching the harness contract: pointing it at a bogus path forces honest failures)."""
    cands: List[Path] = []
    env = os.environ.get("AVA_FACTORY_ROOT")
    if env:
        cands.append(Path(env))
    cands.append(dottie_root() / "apps" / "ava-factory")
    cands.append(DEFAULT_FACTORY_ROOT)
    out: List[Path] = []
    for c in cands:
        if c not in out:
            out.append(c)
    return out


def _has_factory_code(root: Path) -> bool:
    """Marker: the CodeAct substrate Hermes imports is present."""
    return (root / "ava" / "rl" / "codeact_loop.py").is_file()


def factory_code_root() -> Path:
    """First candidate that actually contains the ``ava`` CodeAct code, or raise honestly."""
    cands = _factory_candidates()
    for cand in cands:
        if _has_factory_code(cand):
            return cand
    raise HermesResolutionError(
        "ava-factory code (ava/rl/codeact_loop.py) not found. Probed: "
        + ", ".join(str(c) for c in cands)
        + ". Set AVA_FACTORY_ROOT or DOTTIE_ROOT to a checkout that has it."
    )


def ensure_factory_on_path() -> Path:
    """Put the factory code root on ``sys.path`` so ``import ava.rl...`` works; returns it."""
    root = factory_code_root()
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)
    return root


def ava_ckpt_candidates() -> List[Path]:
    """Ordered ava checkpoint candidates (agentic branch preferred over base pretrain),
    across every factory candidate root. Existence is checked by the caller."""
    out: List[Path] = []
    for root in _factory_candidates():
        for rel in ("agentic/agentic_final.pt", "base/base_final.pt"):
            p = root / "runs" / "cpu_pilot" / rel
            if p not in out:
                out.append(p)
    return out


def default_ava_ckpt() -> Optional[Path]:
    """First existing checkpoint candidate, or None (the caller must refuse honestly)."""
    for p in ava_ckpt_candidates():
        if p.is_file():
            return p
    return None


def harness_root() -> Path:
    """packages/ava-open-harness — the eval gate (``python -m harness run``)."""
    root = dottie_root() / "packages" / "ava-open-harness"
    if not (root / "harness" / "runner.py").is_file():
        raise HermesResolutionError(
            f"ava-open-harness not found at {root} (looked for harness/runner.py); "
            "set DOTTIE_ROOT to the dottie monorepo root."
        )
    return root


def skills_root() -> Path:
    """packages/ava-skills — memory-mint / memory-router live here."""
    root = dottie_root() / "packages" / "ava-skills"
    if not (root / "skills" / "memory-mint" / "skill.py").is_file():
        raise HermesResolutionError(
            f"ava-skills memory-mint not found under {root} "
            "(looked for skills/memory-mint/skill.py); set DOTTIE_ROOT."
        )
    return root


def rft_etl_path() -> Path:
    """apps/scout-cli's RFT ETL module file (audit.jsonl -> RFT dataset)."""
    p = dottie_root() / "apps" / "scout-cli" / "bigbang" / "plugins" / "rft" / "etl.py"
    if not p.is_file():
        raise HermesResolutionError(
            f"scout-cli RFT ETL not found at {p}; set DOTTIE_ROOT to the dottie monorepo root."
        )
    return p


def rl_smoke_update_script() -> Path:
    """The factory's proven rollout->reward->GRPO-update script."""
    for cand in _factory_candidates():
        p = cand / "scripts" / "rl_smoke_update.py"
        if p.is_file():
            return p
    raise HermesResolutionError(
        "scripts/rl_smoke_update.py not found in any factory candidate: "
        + ", ".join(str(c) for c in _factory_candidates())
    )


def probe() -> Dict[str, Dict[str, object]]:
    """REAL filesystem probes of every sibling Hermes integrates with — no invented state.
    Each entry reports the resolved path (or the probe list) and whether it is actually there.
    """
    out: Dict[str, Dict[str, object]] = {}

    def _entry(fn) -> Dict[str, object]:
        try:
            return {"available": True, "path": str(fn())}
        except HermesResolutionError as e:
            return {"available": False, "error": str(e)}

    out["factory_code"] = _entry(factory_code_root)
    out["harness"] = _entry(harness_root)
    out["skills_memory_mint"] = _entry(skills_root)
    out["rft_etl"] = _entry(rft_etl_path)
    out["rl_smoke_update"] = _entry(rl_smoke_update_script)
    ckpt = default_ava_ckpt()
    out["ava_checkpoint"] = (
        {"available": True, "path": str(ckpt)}
        if ckpt
        else {
            "available": False,
            "error": "no ava checkpoint found",
            "probed": [str(p) for p in ava_ckpt_candidates()],
        }
    )
    return out
