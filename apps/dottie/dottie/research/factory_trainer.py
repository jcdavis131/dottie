# Solo personal project, no connection to employer, built with public/free-tier only
"""Factory-integrated trainer — the real-Ava swap-in for the research loop's ``Trainer`` hook.

Where ``micro_benchmark_trainer`` trains the candidate module on a synthetic copy/shift task,
this trainer drops the candidate into the REAL factory nano model (``AvaModel1B`` via
``ava.model.build_model``) — replacing one fusion-layer block, the same slot the factory's own
``deltanet_layers`` mechanism swaps — and trains the whole model from scratch on the REAL packed
pilot corpus, measuring cross-entropy on a held-out token tail the training loop never touches.

The hill-climb metric is ``factory_lm_loss``: held-out LM loss of the real architecture on the
real corpus at nano scale. That is a real, comparable, capability-relevant measurement — and it
is still nano-smoke scale, so it carries ``capability_claim: none`` like every pilot artifact.

Honesty contract:
  * torch/factory/packed-data missing -> ``ok=False`` with the true reason (infrastructure;
    the experiment stays retryable). Nothing is simulated.
  * A candidate that cannot be LOADED, cannot be instantiated at the model's ``d_model``,
    breaks the block contract, or raises during training -> ``ok=True, stable=False`` (a real
    negative outcome: failed_training). All four are the candidate's own artifact failing, so
    none of them is retryable; ``ok=False`` is reserved for infrastructure the candidate did
    not cause. ("cannot be LOADED" was added 2026-07-20 with the fix in TODOS 5.3.R45 — that
    path used to return ok=False and would have blocked the queue forever.)
  * NaN/Inf mid-run -> killed immediately, ``stable=False``.
  * The baseline the loop compares against must be measured by ``run_baseline_calibration``
    (identical config, unmodified model) — never hand-typed.
"""

from __future__ import annotations

import inspect
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dottie import resolve
from dottie.research.ledger import Experiment
from dottie.research.train import TrainResult, _load_module, _select_module_class

FACTORY_METRIC = "factory_lm_loss"

# Constructor kwarg names a candidate may use for its model width; whichever exist are forced
# to the real model's d_model so the block drops into the residual stream.
#: "hidden"/"channels"/"width" were missing until 2026-07-20: a candidate naming its
#: constructor arg `hidden` was built at its OWN default width and then handed d_model-wide
#: input, so the swap failed and the candidate was blamed for a mismatch we created.
_DIM_KWARGS = ("d_model", "dim", "hidden", "hidden_dim", "hidden_size", "embed_dim",
               "input_dim", "n_embd", "channels", "width")


def _default_packed_dirs(root: Path) -> List[Path]:
    return [root / "runs" / "cpu_pilot_4080" / "packed", root / "runs" / "cpu_pilot" / "packed"]


def _load_packed_tokens(packed_dir: Path, np):
    """Concatenate every uint16 ``.bin`` shard in the packed dir (the factory pack format)."""
    bins = sorted(packed_dir.glob("*.bin"))
    if not bins:
        raise FileNotFoundError(f"no .bin shards in {packed_dir}")
    arrays = [np.fromfile(str(b), dtype=np.uint16) for b in bins]
    return np.concatenate(arrays)


def _make_candidate(Cls, declared_kwargs: Dict[str, Any], d_model: int):
    """Instantiate the candidate at the real model width (dim-like kwargs overridden)."""
    kwargs = dict(declared_kwargs or {})
    try:
        params = inspect.signature(Cls.__init__).parameters
    except (TypeError, ValueError):
        params = {}
    for name in _DIM_KWARGS:
        if name in params:
            kwargs[name] = d_model
    # Drop declared kwargs the constructor does not accept (unless it takes **kwargs).
    if params and not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        kwargs = {k: v for k, v in kwargs.items() if k in params}
    return Cls(**kwargs)


def _train_and_measure(model, tokens, *, torch, np, device: str, steps: int, seq_len: int,
                       batch: int, lr: float, holdout_frac: float, eval_batches: int,
                       seed: int) -> Tuple[Optional[float], Dict[str, Any]]:
    """Train ``model`` on random windows of the train split; return (heldout CE, extras).

    Returns (None, extras) when the run went NaN/Inf — the caller records failed_training."""
    import torch.nn.functional as F

    n_holdout = max(int(len(tokens) * holdout_frac), (seq_len + 1) * eval_batches)
    if len(tokens) < 2 * n_holdout:
        raise ValueError(f"packed corpus too small: {len(tokens)} tokens")
    train_toks = torch.from_numpy(tokens[:-n_holdout].astype(np.int64))
    held_toks = torch.from_numpy(tokens[-n_holdout:].astype(np.int64))

    g = torch.Generator().manual_seed(seed)
    model = model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, betas=(0.9, 0.95), weight_decay=0.1)

    def batch_from(toks, rng_or_step) -> Tuple[Any, Any]:
        if isinstance(rng_or_step, int):  # deterministic eval windows, evenly spaced
            span = len(toks) - seq_len - 1
            starts = [(i * span) // max(1, eval_batches - 1) for i in range(batch)]
            starts = [min(s + rng_or_step * seq_len, span) % max(1, span) for s in starts]
        else:
            starts = torch.randint(0, len(toks) - seq_len - 1, (batch,), generator=rng_or_step).tolist()
        x = torch.stack([toks[s:s + seq_len] for s in starts])
        y = torch.stack([toks[s + 1:s + seq_len + 1] for s in starts])
        return x.to(device), y.to(device)

    losses: List[float] = []
    model.train()
    t0 = time.monotonic()
    for step in range(steps):
        x, y = batch_from(train_toks, g)
        opt.zero_grad(set_to_none=True)
        out = model(input_ids=x)
        logits = out["lm_logits"] if isinstance(out, dict) else out
        loss = F.cross_entropy(logits.reshape(-1, logits.shape[-1]), y.reshape(-1))
        if not torch.isfinite(loss):
            return None, {"failed_at_step": step, "train_wall_s": round(time.monotonic() - t0, 3)}
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        losses.append(float(loss.detach()))
    train_wall = round(time.monotonic() - t0, 3)

    model.eval()
    with torch.no_grad():
        ce = []
        for i in range(eval_batches):
            x, y = batch_from(held_toks, i)
            out = model(input_ids=x)
            logits = out["lm_logits"] if isinstance(out, dict) else out
            ce.append(float(F.cross_entropy(logits.reshape(-1, logits.shape[-1]), y.reshape(-1))))
    heldout = sum(ce) / len(ce)
    if not all(map(lambda v: v == v and abs(v) != float("inf"), ce)):
        return None, {"failed_at": "eval", "train_wall_s": train_wall}

    return heldout, {
        "train_loss_first": round(losses[0], 5), "train_loss_final": round(losses[-1], 5),
        "train_wall_s": train_wall, "eval_ce_per_batch": [round(v, 5) for v in ce],
    }


def _setup(config: Dict[str, Any]):
    """Shared infra resolution. Returns (torch, np, cfg, packed_tokens, device, knobs) or raises."""
    import numpy as np
    import torch

    root = resolve.ensure_factory_on_path()          # DottieResolutionError propagates
    from ava.config import load as load_cfg          # noqa: E402  (factory import, path just set)

    preset = str(config.get("preset", "nano"))
    cfg = load_cfg(preset)

    packed_dir = config.get("packed_dir")
    dirs = [Path(packed_dir)] if packed_dir else _default_packed_dirs(root)
    tokens = None
    probed = []
    for d in dirs:
        probed.append(str(d))
        if d.is_dir() and any(d.glob("*.bin")):
            tokens = _load_packed_tokens(d, np)
            packed_dir = d
            break
    if tokens is None:
        raise FileNotFoundError(
            "no packed corpus found (run the factory pilot chain first, e.g. "
            "scripts/cpu_pilot_e2e.py). Probed: " + ", ".join(probed))

    device = str(config.get("device") or ("cuda" if torch.cuda.is_available() else "cpu"))
    knobs = {
        "steps": int(config.get("factory_steps", config.get("steps", 150))),
        "seq_len": int(config.get("seq_len", 256)),
        "batch": int(config.get("batch", 16)),
        "lr": float(config.get("lr", 3e-4)),
        "holdout_frac": float(config.get("holdout_frac", 0.05)),
        "eval_batches": int(config.get("eval_batches", 20)),
        "seed": int(config.get("seed", 1234)),
    }
    return torch, np, cfg, tokens, str(packed_dir), device, knobs


def _base_metrics(cfg, packed_dir: str, device: str, knobs: Dict[str, Any], n_tokens: int,
                  params: int) -> Dict[str, Any]:
    return {
        **{k: knobs[k] for k in ("steps", "seq_len", "batch", "lr", "seed")},
        "params": params, "device": device, "packed_dir": packed_dir,
        "packed_tokens": int(n_tokens), "preset": cfg.preset,
        "task": "held-out LM cross-entropy on the real packed pilot corpus",
        "integration": "factory_nano_block_swap",
        "scale": "nano-smoke", "capability_claim": "none",
    }


def _resolve_seeds(config: Dict[str, Any], default_seed: int) -> List[int]:
    """The seeds to train the candidate at.

    A ``seeds`` list in the config enables the CROSS-SEED measurement the evaluator's
    significance test pairs at source (recorded as ``per_seed``); absent it, the single
    configured seed is used and behaviour is unchanged. The unmodified model's own held-out
    loss swings ~0.34 across seeds (TODOS §5.3.R93), so a one-seed candidate number cannot be
    compared honestly against the multi-seed baseline — this is what closes that gap."""
    raw = config.get("seeds")
    if isinstance(raw, (list, tuple)) and raw:
        seen: set = set()
        out: List[int] = []
        for s in raw:
            try:
                v = int(s)
            except (TypeError, ValueError):
                continue
            if v not in seen:
                seen.add(v)
                out.append(v)
        if out:
            return out
    return [int(default_seed)]


class _CandidateFailure(Exception):
    """Carries the exact ``TrainResult`` for a per-seed hard failure so the seed loop can
    surface it unchanged (integration failure / candidate raised during training)."""

    def __init__(self, result: TrainResult) -> None:
        super().__init__(result.detail or "candidate failure")
        self.result = result


def _build_swap_train(Cls, dry, cfg, tokens, *, torch, np, build_model, count_params,
                      device: str, knobs: Dict[str, Any], seed: int, config: Dict[str, Any]):
    """One seed: build the real model, swap the candidate into the fusion slot, prove the
    integrated forward runs, then train and measure held-out CE.

    Returns ``(heldout, extras, replaced_params, candidate_block_params, params, swap_idx)``;
    ``heldout`` is None when the run went NaN/Inf. Raises ``_CandidateFailure`` (carrying the
    caller's TrainResult) on an integration or training-time exception — the candidate's own
    artifact failing, reproducible across seeds, so it is not retryable infrastructure."""
    torch.manual_seed(seed)
    model = build_model(cfg)
    d_model = model.d_model
    try:
        candidate = _make_candidate(Cls, dry.get("init_kwargs") or {}, d_model)

        class CandidateBlockAdapter(torch.nn.Module):
            """Adapts the candidate's [B,S,D]->[B,S,D] contract onto the factory block
            signature (cos/sin/attn_factor ignored, exactly like DeltaNetBlock)."""

            def __init__(self) -> None:
                super().__init__()
                self.candidate = candidate

            def forward(self, x, cos, sin, attn_factor=1.0):
                y = self.candidate(x)
                y = y[0] if isinstance(y, (tuple, list)) else y
                assert y.shape == x.shape, f"candidate changed shape {x.shape}->{y.shape}"
                return y

        swap_idx = int(config.get("swap_layer", len(model.fusion_layers) // 2))
        # Capacity accounting (TODOS §5.3.R): the swap REPLACES a real parameterized block,
        # so a parameter-light candidate also shrinks the model and can "win" at fixed steps
        # for that reason alone (MLBR did). Measure both sides before the swap so the verdict
        # can state the capacity change instead of hiding it. Recording only — not a gate.
        replaced_params = sum(int(p.numel()) for p in model.fusion_layers[swap_idx].parameters()
                              if p.requires_grad)
        candidate_block_params = sum(int(p.numel()) for p in candidate.parameters()
                                     if p.requires_grad)
        model.fusion_layers[swap_idx] = CandidateBlockAdapter()
        # Prove the integrated forward runs before burning training compute.
        with torch.no_grad():
            probe = model(input_ids=torch.randint(0, model.vocab_size, (2, 16)))
            assert torch.isfinite(probe["lm_logits"]).all(), "non-finite logits at init"
    except Exception:
        raise _CandidateFailure(TrainResult(
            True, False,
            metrics={"integration": "factory_nano_block_swap",
                     "detail": "candidate not integrable into the factory model"},
            detail=f"candidate not integrable at d_model={d_model}: "
                   f"{traceback.format_exc()[-1500:]}"))

    params = count_params(model)
    try:
        heldout, extras = _train_and_measure(model, tokens, torch=torch, np=np, device=device,
                                             **{**knobs, "seed": seed})
    except Exception:
        raise _CandidateFailure(TrainResult(
            True, False,
            metrics={"integration": "factory_nano_block_swap",
                     "detail": "candidate raised during training"},
            detail=traceback.format_exc()[-1500:]))
    return heldout, extras, replaced_params, candidate_block_params, params, swap_idx


def factory_nano_trainer(experiment: Experiment, config: Dict[str, Any]) -> TrainResult:
    """The real-factory ``Trainer``: candidate block into the real nano model, real corpus.

    With a ``seeds`` list in the config the candidate is trained once per seed and each seed's
    held-out CE is recorded in ``per_seed`` (the metric is their mean), so the evaluator's
    significance test pairs against the multi-seed baseline at source instead of falling back
    to within-run per-batch spread (TODOS §5.3.R93/R94, SPEC #3)."""
    try:
        torch, np, cfg, tokens, packed_dir, device, knobs = _setup(config)
    except Exception as e:
        return TrainResult(False, False, detail=f"factory trainer infrastructure missing: {e}")

    from ava.model import build_model, count_params

    # Load the validated candidate and instantiate it at the model's width.
    impl = experiment.implementation or {}
    dry = (impl.get("dry_run") or {}) if isinstance(impl.get("dry_run"), dict) else {}
    try:
        module = _load_module(experiment.workspace, impl.get("module_name"))
        Cls = _select_module_class(module, impl.get("module_name"), torch)
    except Exception:
        # ok=True/stable=False -> FAILED_TRAINING (the candidate's fault), NOT ok=False
        # (retryable infrastructure). The module being imported here is the CANDIDATE's own
        # artifact, so a load or class-selection failure reproduces identically on every
        # retry: as ok=False the experiment stays ready_for_training forever and blocks the
        # queue behind it.
        #
        # TODOS 5.3.R45: this is the same bug fixed in train.py, in the file I cited as
        # already getting it right. The integration probe and the training loop below both
        # return ok=True correctly; only this path did not. Two of three correct is how a
        # file passes a spot check. Observed frequency: zero, same as train.py -- fixed on
        # consistency grounds, because a silent queue stall is a bad enough failure not to
        # wait for.
        return TrainResult(True, False,
                           metrics={"integration": "factory_nano_block_swap",
                                    "detail": "candidate module not loadable"},
                           detail=traceback.format_exc()[-1500:])

    # One training run per seed. `first` captures the seed-independent facts (capacity
    # accounting, swap index, param count, seed-0 extras) recorded regardless of outcome; a
    # per-seed integration/training exception surfaces unchanged via _CandidateFailure, and a
    # NaN/Inf at ANY seed is a real instability (stable=False) — a candidate that only trains
    # on some seeds has not earned a promotion.
    seed_list = _resolve_seeds(config, knobs["seed"])
    per_seed: List[float] = []
    first: Optional[Tuple[Dict[str, Any], int, int, int, int]] = None
    for seed in seed_list:
        try:
            heldout, extras, replaced_params, candidate_block_params, params, swap_idx = (
                _build_swap_train(Cls, dry, cfg, tokens, torch=torch, np=np,
                                  build_model=build_model, count_params=count_params,
                                  device=device, knobs=knobs, seed=seed, config=config))
        except _CandidateFailure as f:
            return f.result
        if first is None:
            first = (extras, replaced_params, candidate_block_params, params, swap_idx)
        if heldout is None:
            extras0, replaced_params, candidate_block_params, params, swap_idx = first
            metrics = {**_base_metrics(cfg, packed_dir, device, knobs, len(tokens), params),
                       **extras0, "seed": seed_list[0], "seeds": seed_list,
                       "per_seed": [round(v, 5) for v in per_seed], "failed_seed": seed,
                       "swap_layer": swap_idx, "replaced_block_params": replaced_params,
                       "candidate_block_params": candidate_block_params,
                       "block_param_delta": candidate_block_params - replaced_params}
            return TrainResult(True, False, metrics=metrics,
                               detail=f"loss became NaN/Inf at seed {seed} — unstable in the "
                                      "factory model, killed")
        per_seed.append(heldout)

    extras0, replaced_params, candidate_block_params, params, swap_idx = first
    mean_heldout = sum(per_seed) / len(per_seed)
    metrics = {**_base_metrics(cfg, packed_dir, device, knobs, len(tokens), params), **extras0,
               # `seed` echoes the first seed for back-compat; `seeds`/`per_seed` are the
               # authoritative cross-seed record the evaluator's significance test consumes.
               "seed": seed_list[0], "seeds": seed_list,
               "per_seed": [round(v, 5) for v in per_seed],
               "swap_layer": swap_idx,
               # Capacity delta of the swap itself: negative means the candidate REMOVED
               # capacity, which confounds a fixed-step comparison (see TODOS §5.3.R).
               "replaced_block_params": replaced_params,
               "candidate_block_params": candidate_block_params,
               "block_param_delta": candidate_block_params - replaced_params}
    metrics[FACTORY_METRIC] = round(mean_heldout, 5)
    return TrainResult(True, True, metrics=metrics)


def run_baseline_calibration(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Measure the UNMODIFIED factory model under the identical training config.

    This is the only honest source for the ``factory_lm_loss`` baseline value: same corpus,
    same steps/seq/batch/lr/seed, no candidate. Raises on missing infrastructure."""
    config = dict(config or {})
    torch, np, cfg, tokens, packed_dir, device, knobs = _setup(config)
    from ava.model import build_model, count_params

    torch.manual_seed(knobs["seed"])
    model = build_model(cfg)
    params = count_params(model)
    heldout, extras = _train_and_measure(model, tokens, torch=torch, np=np, device=device,
                                         **knobs)
    if heldout is None:
        raise RuntimeError(f"baseline calibration went NaN/Inf: {extras}")
    return {**_base_metrics(cfg, packed_dir, device, knobs, len(tokens), params), **extras,
            FACTORY_METRIC: round(heldout, 5)}
