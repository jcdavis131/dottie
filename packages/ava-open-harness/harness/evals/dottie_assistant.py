# Solo personal project, no connection to employer, built with public/free-tier only
"""
dottie_assistant.py — assistant verified-task success rate through the REAL dottie engine

The dottie assistant app (apps/dottie) runs verified tasks (dottie.tasks
VerifiedTaskProvider: 5 deterministic families with deterministic verifiers)
through the factory's real CodeAct loop + sandbox via DottieEngine.run_task.
This eval measures the task success rate (mean r_task) of a small batch.

Mock mode (labeled plumbing, plumbing_only=True — never a capability claim):
  * EchoPolicy batch — the real engine, real sandbox, real verifiers; echo
    scores 0.0 BY CONSTRUCTION (the provider's no-leakage guard means an echoed
    prompt can never contain the scoring token), proving the verifier bites.
  * A minimal in-eval SCRIPTED SOLVER batch (labeled synthetic, mirroring
    dottie's scripted-solver test pattern) — emits real code derived from the
    task prompt, the sandbox really executes it, the FINAL is parsed from the
    REAL rendered Observation — proving the pipeline can measure a NONZERO rate.
  * Seed-varying (anti-mock guard convention): the batch's family mix and task
    seeds derive from the mock model's seed, so the measured dict genuinely
    varies across seeds.

Real mode: the batch runs with a real assistant backend — ``ava`` (default; the
factory's smoke-scale checkpoint via dottie's AvaPolicy) or ``ollama`` (a live
local server, expected unavailable in CI). Backend from ``dottie_backend`` kw or
env ``DOTTIE_EVAL_BACKEND``. The measured success rate is honest — near-zero
for the smoke-scale ava checkpoint — and carries scale=smoke /
capability_claim=none. A missing dottie app / checkpoint / torch / server
returns the structured honest-failure record (real_unimplemented), never an
invented number. Note: the model/tokenizer the harness loads are NOT used here;
the engine's own policy backend does the real decoding (documented, not hidden).

Dottie app resolution mirrors ``harness.common.factory_root``'s tiered pattern:
env DOTTIE_ASSISTANT_ROOT verbatim (even if missing — tests point it at a bogus
path to force honest failures) → DOTTIE_ROOT/apps/dottie → path-relative
monorepo sibling ../../../../apps/dottie. Unavailable → labeled structured
'dottie app not found' record in both modes (never a crash). Known limit: once
the dottie package is imported from one root, a later different root cannot be
re-imported in-process (availability is checked before import, so honest
failures still work).
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from ..registry import register_eval
from ..common import MockModel, attach_smoke_labels, real_unimplemented

TEST = "dottie_assistant"
BAR = "success_rate>=0.6"
_CAPABILITY_BAR = 0.6

# Small batches: this is a smoke-scale harness; n is honest in the record.
DEFAULT_ECHO_N = 4
DEFAULT_SCRIPTED_N = 2
DEFAULT_REAL_N = 5

REAL_BACKENDS = ("ava", "ollama")


# ---------------------------------------------------------------------------
# Dottie app resolution (mirrors common.factory_root's tiered pattern)
# ---------------------------------------------------------------------------

def _has_dottie_code(root: str) -> bool:
    """Marker: the dottie assistant package is present (dottie/engine.py)."""
    return os.path.isdir(root) and os.path.isfile(os.path.join(root, "dottie", "engine.py"))


def _dottie_candidates() -> List[str]:
    """Ordered dottie-app root candidates. Env DOTTIE_ASSISTANT_ROOT is honored
    verbatim first (pointing it at a bogus path forces honest failures)."""
    cands: List[str] = []
    env = os.environ.get("DOTTIE_ASSISTANT_ROOT")
    if env:
        return [env]  # verbatim, even if missing — mirrors AVA_FACTORY_ROOT semantics
    dottie = os.environ.get("DOTTIE_ROOT")
    if dottie:
        cands.append(os.path.join(dottie, "apps", "dottie"))
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        cands.append(os.path.abspath(
            os.path.join(here, "..", "..", "..", "..", "apps", "dottie")))
    except Exception:
        pass  # never let probing break import
    out: List[str] = []
    for c in cands:
        if c not in out:
            out.append(c)
    return out


def dottie_assistant_root() -> str:
    """First candidate with dottie code, else the first candidate (honest miss)."""
    cands = _dottie_candidates()
    for cand in cands:
        if _has_dottie_code(cand):
            return cand
    return cands[0] if cands else "<no dottie candidates>"


def dottie_assistant_available() -> bool:
    return _has_dottie_code(dottie_assistant_root())


def _import_dottie() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Import the dottie app's real modules.

    Returns (modules_dict, None) or (None, reason). The reason is surfaced in
    the structured record so a report never hides WHY dottie could not run."""
    cands = _dottie_candidates()
    root = dottie_assistant_root()
    if not _has_dottie_code(root):
        return None, (
            "dottie app not found (looked for dottie/engine.py). Probed: "
            + ", ".join(cands) + ". Set DOTTIE_ASSISTANT_ROOT or DOTTIE_ROOT."
        )
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import importlib
        mods = {
            name: importlib.import_module(name)
            for name in ("dottie.engine", "dottie.policy", "dottie.tasks", "dottie.resolve")
        }
    except Exception as e:  # surfaced, not swallowed
        return None, f"dottie app import failed from {root}: {type(e).__name__}: {e}"
    return mods, None


# ---------------------------------------------------------------------------
# In-eval scripted solver — SYNTHETIC (labeled), real execution.
# ---------------------------------------------------------------------------

class _ScriptedComputeSolver:
    """Labeled synthetic scripted-solver policy for the 'compute' family
    (dottie's scripted-solver test pattern, kept in-eval because dottie's
    version lives inside its test suite and is not cleanly importable).

    It emits ONE real python action derived from the task prompt, the REAL
    sandbox executes it, and the FINAL is parsed from the REAL rendered
    Observation — so an r_task of 1.0 is a genuine verified success of the
    machinery. plumbing_only=True: never a model-capability measurement."""

    name = "scripted-compute-solver"
    plumbing_only = True

    def __init__(self) -> None:
        self._step = 0

    def __call__(self, transcript: str) -> str:
        self._step += 1
        if self._step == 1:
            nums = re.search(r"Data list: (\[[^\]]*\])", transcript).group(1)
            code = (
                f"nums = {nums}\n"
                "sum(x * x for x in nums if x % 2 == 0) - sum(x for x in nums if x % 2 == 1)"
            )
            return f"Thought: scripted plumbing solve with real code.\n```python\n{code}\n```"
        if self._step == 2:
            got = re.findall(r"=> (\S+)", transcript)[-1]
            return f"FINAL: computed in the real sandbox; the result is {got}."
        return ""  # exhausted -> honest policy_empty termination

    def probe(self) -> Dict[str, Any]:
        return {"backend": self.name, "available": True, "plumbing_only": True}


# ---------------------------------------------------------------------------
# Batch runner over the REAL DottieEngine
# ---------------------------------------------------------------------------

def _detail(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "task_id": rec["task_id"],
        "family": rec["verified_task"]["family"],
        "seed": rec["verified_task"]["seed"],
        "backend": rec["backend"],
        "plumbing_only": rec["plumbing_only"],
        "r_task": rec["reward_components"]["r_task"],
        "terminated": rec["terminated"],
        "n_steps": rec["n_steps"],
        "steps_ok": all(s["ok"] for s in rec["steps"]),
    }


def _run_batch(
    engine_mod: Any,
    engine: Any,
    specs: List[Tuple[str, int]],
    backend: str,
    *,
    max_steps: int,
    timeout_s: float,
    policy_factory: Any = None,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Run (family, seed) specs through engine.run_task; returns (mean r_task, details).

    ``policy_factory`` (mock scripted solver only) temporarily swaps the engine
    module's get_policy — restored in a finally — mirroring dottie's own
    scripted-solver tests; every sandbox step and verifier call stays real."""
    details: List[Dict[str, Any]] = []
    orig_get_policy = engine_mod.get_policy
    try:
        if policy_factory is not None:
            engine_mod.get_policy = lambda _backend, **_kw: policy_factory()
        for family, seed in specs:
            rec = engine.run_task(family=family, seed=seed, backend=backend,
                                  max_steps=max_steps, timeout_s=timeout_s)
            details.append(_detail(rec))
    finally:
        engine_mod.get_policy = orig_get_policy
    rate = sum(d["r_task"] for d in details) / len(details) if details else 0.0
    return rate, details


# ---------------------------------------------------------------------------
# Eval
# ---------------------------------------------------------------------------

@register_eval(
    name=TEST,
    description="Assistant verified-task success rate through the real dottie engine "
                "(CodeAct sandbox + deterministic verifiers)",
    group="assistant",
)
def dottie_assistant(model: Any, tokenizer: Any, device: str = "cpu", **kw: Any) -> Dict[str, Any]:
    if isinstance(model, MockModel):
        return _mock_run(model, kw)
    return _real_run(kw)


def _mock_run(model: MockModel, kw: Dict[str, Any]) -> Dict[str, Any]:
    mods, err = _import_dottie()
    if mods is None:
        # Labeled structured 'dottie app not found' record — never a crash.
        return {"test": TEST, "measured": None, "pass": False, "bar": BAR,
                "mode_label": "mock_plumbing", "plumbing_only": True, "error": err}
    engine_mod = mods["dottie.engine"]
    fams: Tuple[str, ...] = mods["dottie.tasks"].FAMILIES
    n_echo = int(kw.get("dottie_n_echo", DEFAULT_ECHO_N))
    n_scripted = int(kw.get("dottie_n_scripted", DEFAULT_SCRIPTED_N))
    seed = int(getattr(model, "seed", 0))
    # SEED-VARYING batch composition (anti-mock guard convention): both the
    # family mix and the task seeds derive from the mock model's seed, so the
    # measured dict genuinely varies across seeds. Rates themselves are honest
    # constants by construction (echo 0.0 via the no-leak guard; scripted 1.0
    # via real solved-in-sandbox tasks) — the variation lives in the task mix
    # and per-task details, which are real records of real runs.
    echo_specs = [(fams[(seed + i) % len(fams)], seed * 101 + i) for i in range(n_echo)]
    scripted_specs = [("compute", seed * 97 + i) for i in range(n_scripted)]
    data_dir = tempfile.mkdtemp(prefix="dottie-assistant-eval-")
    try:
        engine = engine_mod.DottieEngine(data_dir)
        echo_rate, echo_details = _run_batch(
            engine_mod, engine, echo_specs, "echo", max_steps=6, timeout_s=5.0)
        scripted_rate, scripted_details = _run_batch(
            engine_mod, engine, scripted_specs, "scripted", max_steps=4, timeout_s=5.0,
            policy_factory=_ScriptedComputeSolver)
    except Exception as e:
        # e.g. factory (CodeAct substrate) missing → honest structured record.
        return {"test": TEST, "measured": None, "pass": False, "bar": BAR,
                "mode_label": "mock_plumbing", "plumbing_only": True,
                "error": f"mock plumbing batch could not run: {type(e).__name__}: {e}"}
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
    measured = {
        "mode_label": "mock_plumbing",
        "seed": seed,
        # In mock, the bar applies to the scripted-solver plumbing rate: "the
        # pipeline can measure a rate that clears the bar". Labeled synthetic.
        "success_rate": scripted_rate,
        "echo_success_rate": echo_rate,
        "scripted_success_rate": scripted_rate,
        "echo_n": n_echo,
        "scripted_n": n_scripted,
        "task_mix": [f"{f}:{s}" for f, s in echo_specs + scripted_specs],
        "details": echo_details + scripted_details,
        "note": ("plumbing measurement through the REAL DottieEngine/sandbox/verifiers; "
                 "echo scores 0.0 by construction (provider no-leak guarantee), the "
                 "labeled synthetic scripted solver proves a nonzero rate is measurable. "
                 "NOT a capability claim."),
    }
    ok = scripted_rate >= _CAPABILITY_BAR and echo_rate == 0.0
    return {"test": TEST, "measured": measured, "pass": ok, "bar": BAR,
            "plumbing_only": True}


def _real_run(kw: Dict[str, Any]) -> Dict[str, Any]:
    backend = str(kw.get("dottie_backend") or os.environ.get("DOTTIE_EVAL_BACKEND") or "ava")
    mods, err = _import_dottie()
    if mods is None:
        return real_unimplemented(TEST, BAR, err)
    if backend not in REAL_BACKENDS:
        return real_unimplemented(
            TEST, BAR,
            f"unsupported real backend {backend!r} (choices: {', '.join(REAL_BACKENDS)}; "
            "echo is mock-only plumbing)")
    engine_mod = mods["dottie.engine"]
    policy_mod = mods["dottie.policy"]
    fams: Tuple[str, ...] = mods["dottie.tasks"].FAMILIES
    n = int(kw.get("dottie_n_real", DEFAULT_REAL_N))
    max_steps = int(kw.get("dottie_max_steps", 3))
    timeout_s = float(kw.get("dottie_timeout_s", 5.0))
    specs = [(fams[i % len(fams)], i) for i in range(n)]  # deterministic real batch
    data_dir = tempfile.mkdtemp(prefix="dottie-assistant-eval-")
    try:
        engine = engine_mod.DottieEngine(data_dir)
        details: List[Dict[str, Any]] = []
        for family, seed in specs:
            rec = engine.run_task(family=family, seed=seed, backend=backend,
                                  max_steps=max_steps, timeout_s=timeout_s)
            details.append(_detail(rec))
    except policy_mod.DottiePolicyUnavailable as e:
        # Missing checkpoint / torch / unreachable Ollama → honest structured failure.
        return real_unimplemented(TEST, BAR, f"backend {backend!r} unavailable: {e}")
    except Exception as e:
        return real_unimplemented(TEST, BAR, f"real run failed: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
    rate = sum(d["r_task"] for d in details) / len(details)
    measured = {
        "success_rate": rate,
        "backend": backend,
        "n": n,
        "max_steps": max_steps,
        "task_mix": [f"{f}:{s}" for f, s in specs],
        "details": details,
        "note": ("real end-to-end run: dottie engine + real CodeAct sandbox + deterministic "
                 "verifiers over the real policy backend. The harness-loaded model/tokenizer "
                 "are unused here; the engine's backend does the decoding. For the smoke-scale "
                 "ava checkpoint an honest near-zero rate is the EXPECTED result — the bar is "
                 "the eventual capability bar and today's result fails it honestly."),
    }
    return attach_smoke_labels(
        {"test": TEST, "measured": measured, "pass": rate >= _CAPABILITY_BAR, "bar": BAR})
