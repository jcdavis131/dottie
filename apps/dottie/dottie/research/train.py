# Solo personal project, no connection to employer, built with public/free-tier only
"""Training worker (worker 3) — the real measurement that produces a hill-climbable metric.

The honest problem: fully wiring an arbitrary generated module into the 1B factory model and
running a capability-scale train needs a GPU *and* a factory integration hook that does not exist
yet. So the default trainer is a **synthetic micro-benchmark**: it drops the validated module
into a tiny sequence model and trains it for real, on CPU, on a deterministic copy/shift task
where a module that genuinely mixes sequence information *can* lower the loss. This mirrors the
ecosystem's existing proxy-first discipline (scout-rtx's TinyStories proxy promoted via an EG
gate) — a cheap, REAL, comparable signal, honestly labelled as a proxy, not downstream capability.

Every number returned is measured. A run that goes NaN/Inf is killed immediately (aggressive
early-stopping) and reported as unstable — never silently kept. The trainer is a pluggable
callable so the box can swap in a factory-integrated GPU trainer when the hook lands.
"""

from __future__ import annotations

import importlib.util
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dottie.research.ledger import (
    Ledger, Experiment, EVALUATION_PENDING, FAILED_TRAINING, READY_FOR_TRAINING,
)

# The metric the loop hill-climbs on by default. Lower is better; labelled as a proxy.
PROXY_METRIC = "proxy_loss"


@dataclass
class TrainResult:
    ok: bool
    stable: bool
    metrics: Dict[str, Any] = field(default_factory=dict)
    detail: str = ""


# A Trainer measures an experiment and returns real metrics. Default = micro_benchmark_trainer.
Trainer = Callable[[Experiment, Dict[str, Any]], TrainResult]


def _load_module(workspace: str | Path, module_name: Optional[str]):
    """Import the validated candidate module written into the experiment workspace."""
    ws = Path(workspace)
    pys = sorted(ws.glob("*.py"))
    if not pys:
        raise FileNotFoundError(f"no .py module in workspace {ws}")
    # `validate()` writes a scratch `candidate_<uuid>.py` into this SAME workspace on every
    # attempt, including failed ones, while implementation.py writes the final module under
    # its own name. Picking `sorted(...)[0]` therefore selected by ALPHABET across a mixed
    # pool: "candidate_" sorts before most generated filenames, so the trainer loaded a
    # validator scratch file rather than the validated module.
    #
    # Measured 2026-07-20 (TODOS §5.3.R49) over 25 trainable workspaces: **25 of 25** loaded
    # a candidate_ file. In 23 the newest scratch file happened to be byte-identical to the
    # final module, so the right code trained by luck. In **2 it was an earlier FAILED
    # attempt with different content** — the loop trained and judged code it had already
    # rejected, silently. One of those is 694633b2d354, whose failed_training verdict may
    # therefore be about the wrong module.
    #
    # Prefer the real module; fall back to scratch only if nothing else exists, and then take
    # the NEWEST (the passing attempt) rather than the alphabetically first.
    finals = [p for p in pys if not p.name.startswith("candidate_")]
    pool = finals or pys
    path = max(pool, key=lambda p: p.stat().st_mtime) if len(pool) > 1 else pool[0]
    name = f"dottie_research_train_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _select_module_class(module, module_name, torch):
    if module_name and getattr(module, module_name, None) is not None:
        return getattr(module, module_name)
    cands = [v for v in vars(module).values()
             if isinstance(v, type) and issubclass(v, torch.nn.Module) and v is not torch.nn.Module]
    if not cands:
        raise LookupError("no nn.Module subclass in generated module")
    return cands[0]


def micro_benchmark_trainer(experiment: Experiment, config: Dict[str, Any]) -> TrainResult:
    """Train the experimental module on a synthetic shift task for real, on CPU.

    Proxy task: random token sequences embedded to ``dim``; the module transforms
    [batch, seq, dim] -> [batch, seq, dim]; a tied head predicts the next token. A module that
    mixes across the sequence can beat an identity/pointwise one. Returns mean/std final loss over
    seeds, a stability flag, param count, and throughput — all measured."""
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
    except Exception as e:  # pragma: no cover - torch present in CI/box
        return TrainResult(False, False, detail=f"torch unavailable: {e}")

    impl = experiment.implementation or {}
    dry = (impl.get("dry_run") or {}) if isinstance(impl.get("dry_run"), dict) else {}
    init_kwargs = dict(dry.get("init_kwargs") or {})
    shape = dry.get("input_shape") or [8, 16, 64]
    dim = int(shape[-1])
    seq = int(shape[1]) if len(shape) >= 2 else 16
    batch = int(config.get("batch", max(8, shape[0])))
    steps = int(config.get("steps", 60))
    seeds = list(config.get("seeds", [0, 1, 2]))
    vocab = int(config.get("vocab", 64))
    lr = float(config.get("lr", 1e-3))

    try:
        module = _load_module(experiment.workspace, impl.get("module_name"))
        Cls = _select_module_class(module, impl.get("module_name"), torch)
    except Exception:
        # ok=True/stable=False -> FAILED_TRAINING (the candidate's fault), NOT ok=False
        # (retryable infrastructure). The module being imported here IS the candidate's
        # own artifact, so a load or class-selection failure reproduces identically on
        # every retry: as ok=False the experiment stays ready_for_training forever and
        # blocks the queue behind it. factory_trainer.py already draws the line this way;
        # this path was left inconsistent with it.
        return TrainResult(True, False, metrics={"integration": "proxy_micro_benchmark",
                                                 "detail": "candidate module not loadable"},
                           detail=traceback.format_exc()[-1500:])

    finals: List[float] = []
    n_params = None
    t0 = time.monotonic()
    for seed in seeds:
        g = torch.Generator().manual_seed(int(seed))
        torch.manual_seed(int(seed))

        class Proxy(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.embed = nn.Embedding(vocab, dim)
                self.core = Cls(**init_kwargs)
                self.head = nn.Linear(dim, vocab)

            def forward(self, toks):
                h = self.embed(toks)                 # [B,S,dim]
                y = self.core(h)
                y = y[0] if isinstance(y, (tuple, list)) else y
                assert y.shape == h.shape, f"core changed shape {h.shape}->{y.shape}"
                return self.head(y)                  # [B,S,vocab]

        try:
            net = Proxy()
        except Exception:
            # Same reasoning: Cls(**init_kwargs) raising is the candidate's __init__
            # failing, which no retry can fix.
            return TrainResult(True, False, metrics={"integration": "proxy_micro_benchmark",
                                                     "detail": "candidate not constructible"},
                               detail=traceback.format_exc()[-1500:])
        if n_params is None:
            n_params = sum(p.numel() for p in net.parameters())
        opt = torch.optim.Adam(net.parameters(), lr=lr)
        # Deterministic task: predict the token 1 step ahead (shift/copy).
        toks = torch.randint(0, vocab, (batch, seq + 1), generator=g)
        x, target = toks[:, :-1], toks[:, 1:]
        last = float("nan")
        try:
            for _ in range(steps):
                opt.zero_grad()
                logits = net(x)
                loss = F.cross_entropy(logits.reshape(-1, vocab), target.reshape(-1))
                if not torch.isfinite(loss):
                    return TrainResult(True, False,
                                       metrics={"seed": seed, "params": n_params},
                                       detail="loss became NaN/Inf — unstable architecture, "
                                              "killed")
                loss.backward()
                opt.step()
                last = float(loss.detach())
        except Exception:
            # A candidate that RAISES mid-training (as opposed to going NaN) used to escape
            # this function entirely: the exception propagated out of run_training into the
            # daemon's generic handler, which left the experiment in ready_for_training AND
            # counted a consecutive error toward the five-error exit. factory_trainer already
            # wraps its training loop this way; this one did not (TODOS 5.3.R46 — the same
            # asymmetry as 5.3.R45, found by reading rather than by it happening).
            return TrainResult(True, False,
                               metrics={"seed": seed, "params": n_params,
                                        "integration": "proxy_micro_benchmark",
                                        "detail": "candidate raised during training"},
                               detail=traceback.format_exc()[-1500:])
        finals.append(last)

    wall = round(time.monotonic() - t0, 3)
    mean = sum(finals) / len(finals)
    var = sum((f - mean) ** 2 for f in finals) / len(finals)
    metrics = {
        PROXY_METRIC: round(mean, 5),
        "proxy_loss_std": round(var ** 0.5, 5),
        "per_seed": [round(f, 5) for f in finals],
        "seeds": seeds,
        "steps": steps,
        "params": int(n_params or 0),
        "wall_s": wall,
        "task": "synthetic next-token shift (proxy micro-benchmark, NOT downstream capability)",
        "integration": "proxy_micro_benchmark",
    }
    return TrainResult(True, True, metrics=metrics)


def run_training(ledger: Ledger, *, trainer: Optional[Trainer] = None,
                 config: Optional[Dict[str, Any]] = None,
                 ts: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Pick the oldest ready_for_training experiment, measure it, and record the outcome.

    Returns a summary dict, or None if nothing is ready. A stable run -> evaluation_pending
    with real train_metrics; a NaN, a crash, or a module that will not load -> failed_training
    (all the candidate's own fault, all non-retryable). ONLY genuine infrastructure gaps —
    torch or the factory checkout missing — leave the experiment in ready_for_training.
    (Was: "loading/trainer infra errors leave it retryable", which stopped being true when
    load failures were reclassified as candidate faults; TODOS 5.3.R46.)"""
    trainer = trainer or micro_benchmark_trainer
    cfg = dict(config or {})
    exp = ledger.next_in_state(READY_FOR_TRAINING)
    if exp is None:
        return None
    result = trainer(exp, cfg)
    if result.ok and result.stable:
        ledger.transition(exp.id, EVALUATION_PENDING, train_metrics=result.metrics, ts=ts)
        return {"experiment": exp.id, "state": EVALUATION_PENDING, "metrics": result.metrics}
    if result.ok and not result.stable:  # trained but diverged — a real (bad) outcome
        ledger.transition(exp.id, FAILED_TRAINING,
                          train_metrics=result.metrics or {"stable": False},
                          failure=result.detail or "unstable (NaN/Inf)", ts=ts)
        return {"experiment": exp.id, "state": FAILED_TRAINING, "reason": "unstable"}
    # Genuine infrastructure only (torch/factory missing): leave retryable, report honestly.
    # Candidate-caused failures never reach here — they return ok=True above.
    return {"experiment": exp.id, "state": READY_FOR_TRAINING, "error": result.detail}
