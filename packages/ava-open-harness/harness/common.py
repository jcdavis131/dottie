"""
common.py — model/tokenizer loading, greedy decode, logprob, factory delegation utils

Solo personal project, no connection to employer, built with public/free-tier only
Mypyc-ready: typed, lazy imports for torch
"""
from __future__ import annotations
from typing import Any, Tuple, List, Dict, Optional
import os, sys, json, math, random

# ---------------------------------------------------------------------------
# Factory (ava-agi-factory-v6-4) discovery.
#
# The real eval implementations (WorkspaceSwap/BroadcastSwap interventions,
# compute_ppl, score_probes, run_needle) live in the factory repo. When it is
# importable we DELEGATE to them; when it is not, real mode fails honestly via
# real_unimplemented() — never a silent mock.

DEFAULT_FACTORY_ROOT = "/home/user/ava-agi-factory-v6-4"


def factory_root() -> str:
    """Factory repo root; override with env AVA_FACTORY_ROOT."""
    return os.environ.get("AVA_FACTORY_ROOT", DEFAULT_FACTORY_ROOT)


def factory_available() -> bool:
    root = factory_root()
    return os.path.isdir(root) and os.path.isfile(os.path.join(root, "evals", "jspace_tests.py"))


_FACTORY_CACHE: Dict[str, Any] = {}


def factory_modules() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Import the factory's real eval modules.

    Returns (modules_dict, None) on success or (None, reason) on failure.
    The reason string is surfaced in the honest-failure record so a report
    never hides WHY the real path could not run.
    """
    if _lazy_torch() is None:
        return None, "torch not installed"
    root = factory_root()
    if not factory_available():
        return None, f"factory repo not found at {root} (set AVA_FACTORY_ROOT)"
    if root in _FACTORY_CACHE:
        return _FACTORY_CACHE[root], None
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import importlib
        mods = {
            name: importlib.import_module(name)
            for name in (
                "evals.common",
                "evals.interventions",
                "evals.jspace_tests",
                "evals.perplexity",
                "evals.probes",
                "evals.needle",
            )
        }
    except Exception as e:  # surfaced, not swallowed
        return None, f"factory import failed: {e}"
    _FACTORY_CACHE[root] = mods
    return mods, None


# ---------------------------------------------------------------------------
# Honesty labels.
#
# Policy (documented per audit): every real measurement this harness produces
# today comes from the factory's cpu_pilot smoke checkpoint (~14M params,
# ~90 optimizer steps on ~17MB of synthetic data). We therefore ALWAYS attach
# the smoke-scale labels to real measured results rather than trying to derive
# a scale from the checkpoint path: no non-smoke checkpoint exists yet, and an
# over-attached honest label is safe while a missing label would overclaim.
# Revisit when a larger checkpoint ships (derive from a manifest, not a path).

SMOKE_SCALE_LABELS: Dict[str, str] = {"scale": "smoke", "capability_claim": "none"}


def attach_smoke_labels(record: Dict[str, Any]) -> Dict[str, Any]:
    """Attach smoke-scale honesty labels to a REAL measured result (in place)."""
    for k, v in SMOKE_SCALE_LABELS.items():
        record[k] = v
    return record


def real_unimplemented(test: str, bar: str, needs: str) -> Dict[str, Any]:
    """Honest real-mode failure record.

    HARNESS_SPEC: every float in a real report must come from a live forward pass.
    A real path that isn't wired yet therefore FAILS with an explanation — it never
    returns invented constants (that antipattern is exactly what this repo replaced).
    """
    return {
        "test": test,
        "measured": None,
        "pass": False,
        "bar": bar,
        "error": f"real mode not implemented: {needs}",
    }


def _lazy_torch():
    try:
        import torch
        return torch
    except ImportError:
        return None

class MockTokenizer:
    """Deterministic single-token-per-word mock for offline CI."""
    def __init__(self, vocab_size: int = 128000):
        self.vocab_size = vocab_size
        self._word_to_id: Dict[str, int] = {}
        self._next_id = 256
    def encode(self, text: str) -> List[int]:
        t = text.strip()
        if not t:
            return []
        if " " not in t:
            if t not in self._word_to_id:
                self._word_to_id[t] = (sum(b for b in t.encode()) % (self.vocab_size - 1000)) + 500
            return [self._word_to_id[t]]
        ids = []
        for w in t.split():
            if w not in self._word_to_id:
                self._next_id += 1
                self._word_to_id[w] = self._next_id % self.vocab_size
            ids.append(self._word_to_id[w])
        return ids
    def decode(self, ids: List[int]) -> str:
        inv = {v:k for k,v in self._word_to_id.items()}
        return " ".join(inv.get(i, f"<{i}>") for i in ids)

class MockModel:
    """Mock that mimics Ava model interface enough for harness shape checks."""
    def __init__(self, seed: int = 1234):
        self.seed = seed
        random.seed(seed)
    def eval(self): return self
    def reset_memory(self): pass
    def __repr__(self): return f"<MockModel seed={self.seed}>"

def load_model(
    ckpt_path: str | None,
    preset: str = "nano",
    device: str = "cpu",
    tokenizer_path: str | None = None,
) -> Tuple[Any, Any]:
    """Load the model + tokenizer.

    - ckpt None/"none"/"random-init"/"mock" → deterministic mocks (mock mode).
    - Otherwise the REAL path: any failure RAISES with the true cause. There is
      no silent fallback to mock — a caller asking for real gets real or an
      error (the runner turns the error into a structured honest-failure report).
    Returns (model, tokenizer).
    """
    ckpt_path = ckpt_path or "none"
    if ckpt_path.lower() in ("none", "random-init", "mock"):
        return MockModel(), MockTokenizer()

    torch = _lazy_torch()
    if torch is None:
        raise RuntimeError("real mode requires torch (pip install torch); refusing to mock")
    if not os.path.exists(ckpt_path):
        raise FileNotFoundError(f"checkpoint not found: {ckpt_path}")

    root = factory_root()
    if not os.path.isdir(root):
        raise FileNotFoundError(
            f"factory repo (ava package) not found at {root}; set AVA_FACTORY_ROOT"
        )
    if root not in sys.path:
        sys.path.insert(0, root)
    from ava.config import load as load_cfg
    from ava.model import build_model
    from ava.tokenizer import AvaTokenizer

    cfg = load_cfg(preset)
    model = build_model(cfg)
    # weights_only=False: torch>=2.6 defaults to weights_only=True, which cannot
    # unpickle the factory's full training blob (optimizer/sampler/rng state).
    # These checkpoints are trusted local artifacts produced by our own
    # scripts/cpu_pilot_e2e.py run — never remote downloads.
    state = torch.load(ckpt_path, map_location=device, weights_only=False)
    sd = state.get("model", state)
    model.load_state_dict(sd, strict=False)
    model.eval()

    # Tokenizer resolution: explicit --tokenizer first, then factory artifacts.
    # A REAL model with a mock tokenizer would run over hash-derived garbage
    # token IDs, so a missing tokenizer FAILS LOUDLY — never silently mocks.
    if tokenizer_path:
        if not os.path.exists(tokenizer_path):
            raise FileNotFoundError(f"--tokenizer given but not found: {tokenizer_path}")
        candidates = [tokenizer_path]
    else:
        candidates = [
            os.path.join(root, "runs", "cpu_pilot", "tokenizer", "ava_nano_bpe.json"),
            os.path.join(root, f"data/{preset}/tokenizer/ava_{preset}_bpe.json"),
        ]
    tok_path = next((p for p in candidates if os.path.exists(p)), None)
    if tok_path is None:
        raise FileNotFoundError(
            "real mode requires a real tokenizer; none found. Tried: "
            + ", ".join(candidates)
            + ". Pass --tokenizer or regenerate via factory scripts/cpu_pilot_e2e.py."
        )
    tok = AvaTokenizer.load(tok_path)
    return model, tok


def _extract_logits(out: Any, torch: Any) -> Any:
    """Pull the LM logits tensor out of a model forward result.

    The Ava model returns a dict with key 'lm_logits'; also tolerate plain
    tensors, tuples and HF-style .logits. Anything else raises."""
    if isinstance(out, dict):
        if "lm_logits" in out:
            return out["lm_logits"]
        if "logits" in out:
            return out["logits"]
        raise RuntimeError(f"model output dict has no lm_logits/logits (keys={list(out.keys())})")
    if isinstance(out, torch.Tensor):
        return out
    if isinstance(out, (list, tuple)):
        return out[0]
    if hasattr(out, "logits"):
        return out.logits
    raise RuntimeError(f"cannot extract logits from model output of type {type(out)!r}")


def greedy_decode(model: Any, prompt_ids: List[int], max_new: int = 8, vocab_size: int = 128000) -> List[int]:
    """Greedy decode — deterministic pseudo-decode for mock, live argmax for real.

    Real path RAISES on any failure (mirrors logprob_of's honest-raise). The old
    silent fall-back-to-MockModel violated the repo's own anti-fabrication rule:
    a caller asking a real model to decode must never receive mock tokens."""
    torch = _lazy_torch()
    if isinstance(model, MockModel) or torch is None:
        # deterministic pseudo-decode: hash sum (labeled mock by construction)
        out = []
        s = sum(prompt_ids)
        for i in range(max_new):
            out.append((s + i * 31) % vocab_size)
        return out
    # real path — honest raise on failure, no mock fallback
    try:
        model.eval()
        device = next(model.parameters()).device if hasattr(model, "parameters") else "cpu"
        ids = torch.tensor([prompt_ids], dtype=torch.long, device=device)
        with torch.no_grad():
            for _ in range(max_new):
                out = model(input_ids=ids)
                logits = _extract_logits(out, torch)
                nxt = int(logits[0, -1].argmax().item())
                ids = torch.cat([ids, torch.tensor([[nxt]], device=ids.device)], dim=1)
        return ids[0].tolist()[-max_new:]
    except Exception as e:
        raise RuntimeError(f"greedy_decode failed on real model: {e}") from e

def logprob_of(model: Any, prompt_ids: List[int], target_ids: List[int]) -> float:
    """Sum logprob of target continuation given prompt."""
    torch = _lazy_torch()
    if isinstance(model, MockModel) or torch is None:
        # mock: pseudo logprob from deterministic mapping
        random.seed(sum(prompt_ids)+sum(target_ids))
        return random.uniform(-5.0, -0.2)
    try:
        import torch.nn.functional as F
        device = next(model.parameters()).device if hasattr(model,'parameters') else 'cpu'
        full = prompt_ids + target_ids
        inp = torch.tensor([full[:-1]], dtype=torch.long, device=device)
        with torch.no_grad():
            out = model(input_ids=inp)
            logits = _extract_logits(out, torch)[0]
            logp = F.log_softmax(logits.float(), dim=-1)
        lp = 0.0
        for i, tid in enumerate(target_ids):
            pos = len(prompt_ids) + i -1
            if pos >=0 and pos < logp.shape[0]:
                lp += logp[pos, tid].item()
        return lp
    except Exception as e:
        # No silent fabricated fallback (HARNESS_SPEC anti-mock rule): a real-mode
        # measurement that can't be computed must fail loudly, never invent a float.
        raise RuntimeError(f"logprob_of failed on real model: {e}") from e

def cosine_sim(a: Any, b: Any) -> float:
    try:
        import numpy as np
        aa = np.array(a, dtype=float); bb = np.array(b, dtype=float)
        denom = (np.linalg.norm(aa)*np.linalg.norm(bb)+1e-9)
        return float(np.dot(aa,bb)/denom)
    except Exception:
        # pure python
        dot = sum(x*y for x,y in zip(a,b))
        na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
        return dot/(na*nb+1e-9)

def auc_trapezoid(y_true: List[int], y_score: List[float]) -> float:
    """Compute ROC AUC via trapezoid, no sklearn."""
    # sort by score descending
    pairs = sorted(zip(y_score, y_true), reverse=True)
    # compute TPR/FPR steps
    pos = sum(y_true); neg = len(y_true)-pos
    if pos==0 or neg==0:
        return 0.5
    tp = fp = 0
    prev_fpr = 0.0; prev_tpr = 0.0; auc=0.0
    for _, label in pairs:
        if label==1:
            tp+=1
        else:
            fp+=1
        tpr = tp/pos; fpr = fp/neg
        auc += (fpr-prev_fpr)*(tpr+prev_tpr)/2.0
        prev_fpr, prev_tpr = fpr, tpr
    return auc
