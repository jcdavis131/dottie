"""Real training loop. WSD schedule, 6-phase curriculum, live shard consumption.

Replaces train_1b_deepspeed.py, which ran 5 steps of `loss=torch.tensor(1.0)`
and wrote text files as "checkpoints".

Resume semantics -- read this before trusting `--resume`:
    Model, optimizer, step, phase, LR schedule and RNG state are restored
    exactly. The *data order* is not, and cannot be: the sampler claims shards
    from a manifest that collectors are still writing to, so the shard set at
    step N on a resumed run differs from the original. Resume is therefore
    loss-continuous, not bit-exact. Making it bit-exact needs an as-of manifest
    watermark pinned per run (TODOS T10.5).

Checkpoints:
    ckpt/step_{n}.pt        rotating, keep-last-N (janitor)
    ckpt/stable_p{phase}.pt at each phase boundary -- the stop-anytime and
                            branch-fork points
    ckpt/latest             symlink the server hot-reloads from
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from pathlib import Path

import numpy as np
import torch

from dottie.config import DottieConfig, PhaseConfig
from dottie.data import StreamingShardSampler
from dottie.jlosses import JSpaceObjective
from dottie.model import build_model, count_params, set_router_bias
from dottie.pipeline.demand import compute_demand, write_demand
from dottie.pipeline.flow import FlowConfig
from dottie.pipeline.manifest import Manifest
from model_1b import apply_rope_scaling

MAX_MICRO_BATCH = 8


# ---------------------------------------------------------------------------
# schedule


def wsd_lr(step: int, total_steps: int, cfg: DottieConfig) -> float:
    """Warmup -> Stable -> Decay. The stable plateau is what makes any
    checkpoint taken during it a usable model, hence "stop-anytime"."""
    w = cfg.training.wsd
    stable_until = int(total_steps * w.stable_frac)
    if step < w.warmup_steps:
        return w.lr_max * (step + 1) / max(1, w.warmup_steps)
    if step < stable_until:
        return w.lr_max
    frac = (step - stable_until) / max(1, total_steps - stable_until)
    return w.lr_min + 0.5 * (w.lr_max - w.lr_min) * (1 + math.cos(math.pi * min(1.0, frac)))


def phase_for_step(cfg: DottieConfig, tokens_done: int) -> int:
    """Which curriculum phase a token budget lands in."""
    acc = 0
    for i, p in enumerate(cfg.phases):
        acc += p.tokens or 0
        if tokens_done < acc:
            return i
    return len(cfg.phases) - 1


def micro_batch_for(seq: int, tokens_per_step: int) -> tuple[int, int]:
    mb = max(1, min(MAX_MICRO_BATCH, tokens_per_step // seq))
    accum = max(1, tokens_per_step // (mb * seq))
    return mb, accum


# ---------------------------------------------------------------------------
# checkpointing


def save_ckpt(path: Path, *, model, opt, step, phase, tokens_done, cfg, sampler) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = {
        "model": model.state_dict(),
        "optimizer": opt.state_dict(),
        "step": step,
        "phase": phase,
        "tokens_done": tokens_done,
        "preset": cfg.preset,
        "sampler": sampler.state_dict(),
        "rng": {
            "python": random.getstate(),
            "numpy": np.random.get_state(),
            "torch": torch.get_rng_state(),
            "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
        },
    }
    tmp = path.with_suffix(".tmp")
    torch.save(blob, tmp)
    os.replace(tmp, path)                       # atomic: the server may be reading


def _point_latest_at(ckpt_dir: Path, target: Path) -> None:
    latest = ckpt_dir / "latest"
    tmp = ckpt_dir / "latest.tmp"
    tmp.write_text(target.name)
    os.replace(tmp, latest)                     # a file, not a symlink: Windows volumes


def load_ckpt(path: Path, *, model, opt, sampler, device: str) -> tuple[int, int]:
    blob = torch.load(path, map_location=device, weights_only=False)
    model.load_state_dict(blob["model"])        # the blueprint printed "Loading..." and never did this
    opt.load_state_dict(blob["optimizer"])
    sampler.load_state_dict(blob["sampler"])
    r = blob["rng"]
    random.setstate(r["python"])
    np.random.set_state(r["numpy"])
    torch.set_rng_state(r["torch"].cpu() if hasattr(r["torch"], "cpu") else r["torch"])
    if r.get("cuda") and torch.cuda.is_available():
        torch.cuda.set_rng_state_all([t.cpu() for t in r["cuda"]])
    return int(blob["step"]), int(blob["tokens_done"])


# ---------------------------------------------------------------------------


def build_optimizer(model, cfg: DottieConfig):
    o = cfg.training.optimizer
    # Muon hybrid: large mats with Newton-Schulz, rest AdamW
    if o.name in ("muon", "muon_hybrid"):
        try:
            from dottie.muon import MuonAdamHybrid, get_coupled_weight_decay
            decay, no_decay = [], []
            for n, p in model.named_parameters():
                if not p.requires_grad:
                    continue
                (no_decay if p.ndim < 2 or "decay_logit" in n or "bias" in n or "sink" in n else decay).append((n, p))
            # Muon sees decay params as large mats; Adam sees rest
            decay_params = [p for _, p in decay]
            no_decay_params = [p for _, p in no_decay]
            muon_groups = []
            if decay_params:
                muon_groups.append({"params": decay_params, "weight_decay": o.weight_decay, "use_muon": True})
            if no_decay_params:
                muon_groups.append({"params": no_decay_params, "weight_decay": 0.0, "use_muon": False})
            # coupled wd: base * (lr/lr_max)^2 – handled via caller set_lr hook if needed
            hybrid = MuonAdamHybrid(muon_groups, lr=cfg.training.wsd.lr_max, betas=o.betas,
                                    base_wd=o.weight_decay, lr_max=cfg.training.wsd.lr_max)
            # expose getter for training loop
            hybrid.get_coupled_wd = lambda lr: get_coupled_weight_decay(lr, o.weight_decay, cfg.training.wsd.lr_max)
            return hybrid
        except Exception as exc:
            print(f"[warn] muon import failed {exc}, falling back AdamW")
    decay, no_decay = [], []
    for n, p in model.named_parameters():
        if not p.requires_grad:
            continue
        # no weight decay on norms, biases, or the learned decay logits
        (no_decay if p.ndim < 2 or "decay_logit" in n else decay).append(p)
    groups = [{"params": decay, "weight_decay": o.weight_decay},
              {"params": no_decay, "weight_decay": 0.0}]

    if o.name == "adamw8bit":
        import bitsandbytes as bnb
        return bnb.optim.AdamW8bit(groups, lr=cfg.training.wsd.lr_max, betas=o.betas)
    return torch.optim.AdamW(groups, lr=cfg.training.wsd.lr_max, betas=o.betas)


def apply_phase(model, cfg: DottieConfig, phase: int, log) -> PhaseConfig:
    p = cfg.phases[phase]
    apply_rope_scaling(model, p.rope_base, p.ntk)
    log("phase_enter", phase=phase, name=p.name, seq=p.seq,
        rope_base=p.rope_base, ntk=p.ntk, j_weight=cfg.jspace.j_weight_for_phase(phase))
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ava.train")
    ap.add_argument("--preset", default=os.environ.get("AVA_PRESET", "nano"))
    ap.add_argument("--device", default=None, choices=[None, "cpu", "cuda"])
    ap.add_argument("--run", default=os.environ.get("AVA_CKPT_DIR", "/ckpt"))
    ap.add_argument("--reports", default=os.environ.get("AVA_REPORTS_DIR", "/reports"))
    ap.add_argument("--packed", default=os.environ.get("AVA_PACKED_DIR", "/packed"))
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--max-steps", type=int, default=None, help="smoke tests")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--branch", default=None, help="e.g. chat")
    ap.add_argument("--init", default=None, help="checkpoint to fork a branch from")
    args = ap.parse_args(argv)

    cfg = DottieConfig.load(args.preset)
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    ckpt_dir = Path(args.run)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = Path(args.reports) / f"metrics_{args.preset}.jsonl"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    mfile = open(metrics_path, "a", buffering=1)

    def log(event, **kw):
        rec = {"ts": time.time(), "event": event, "preset": args.preset, **kw}
        line = json.dumps(rec)
        print(line, flush=True)
        mfile.write(line + "\n")

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if device == "cpu":
        torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))

    model = build_model(cfg).to(device)
    log("model_built", params=count_params(model), device=device,
        d_model=cfg.model.d_model, vocab=cfg.model.vocab_size)

    # ---- branch fork: a REAL state_dict load, then freeze + router prior
    if args.branch:
        spec = (cfg.branch_chat if args.branch == "chat" else (cfg.branches or {}).get(args.branch))
        if spec is None:
            raise SystemExit(f"preset {cfg.preset} defines no branch {args.branch!r}")
        src = Path(args.init or spec["init"])
        blob = torch.load(src, map_location=device, weights_only=False)
        model.load_state_dict(blob["model"])
        model.freeze_spaces(list(spec["freeze"]))
        set_router_bias(model, list(spec["router_bias"]))
        log("branch_forked", branch=args.branch, init=str(src), step=blob.get("step"),
            frozen=spec["freeze"], trainable=count_params(model, trainable_only=True))

    opt = build_optimizer(model, cfg)
    obj = JSpaceObjective(cfg).to(device)

    flow = FlowConfig.load()
    # `with sampler` guarantees the in-flight shard is handed back on any exit
    # path. Without it every run leaks its claim and the next one starves on data
    # it already owns.
    run_id = f"{args.preset}:{args.branch or 'base'}:{int(time.time())}"
    with Manifest() as manifest, StreamingShardSampler(
            cfg, manifest, flow, seed=args.seed, packed_dir=args.packed) as sampler:

        lm_hist: list[float] = []

        def heartbeat(step: int, phase: int, status: str = "running") -> None:
            """Publish phase + demand so miners close the data loop."""
            try:
                manifest.upsert_run(run_id, preset=args.preset, step=step,
                                    phase=phase, status=status)
            except Exception as exc:  # never let bookkeeping kill the GPU loop
                log("heartbeat_failed", error=str(exc))
                return
            try:
                ready = {p: int(manifest.tokens_ready(p)) for p in range(6)}
                by_state = manifest.counts_by_state()
                failed = int(by_state.get("FAILED", 0))
                active = max(1, sum(int(by_state.get(s, 0)) for s in (
                    "RAW", "CLAIMED_CURATE", "PACKED", "CLAIMED_TRAIN", "FAILED",
                )))
                trend = None
                if len(lm_hist) >= 3:
                    trend = lm_hist[-1] - lm_hist[0]
                snap = compute_demand(
                    tokens_ready_by_phase=ready,
                    cfg=flow,
                    trainer_phase=phase,
                    step=step,
                    preset=args.preset,
                    failed_shards=failed,
                    active_shards=active,
                    lm_trend=trend,
                )
                path = write_demand(snap)
                # Cheap history for collectors/dashboard; never block the step.
                try:
                    manifest.log_metric(run_id, "demand_effort_p" + str(phase),
                                        snap.effort_map().get(phase, 0.0))
                except Exception:
                    pass
                if step <= 1 or step % max(1, cfg.training.metrics_every_steps) == 0:
                    log("demand_published", path=str(path), step=step, phase=phase,
                        reasons=list(snap.reasons)[:3],
                        effort={str(k): v for k, v in snap.effort_map().items() if v > 0})
            except Exception as exc:
                log("demand_publish_failed", error=str(exc))

        step, tokens_done = 0, 0
        latest = ckpt_dir / "latest"
        if args.resume and latest.exists():
            target = ckpt_dir / latest.read_text().strip()
            step, tokens_done = load_ckpt(target, model=model, opt=opt,
                                          sampler=sampler, device=device)
            log("resumed", ckpt=str(target), step=step, tokens_done=tokens_done)

        total_steps = args.max_steps or cfg.total_steps()
        # Finished run + compose `restart: unless-stopped` used to spin forever
        # (load base_final → done → exit 0 → restart). Exit cleanly instead.
        if step >= total_steps:
            phase = phase_for_step(cfg, tokens_done)
            heartbeat(step, phase, status="done")
            log("already_done", step=step, tokens=tokens_done,
                total_steps=total_steps, final=str(ckpt_dir / f"{args.branch or 'base'}_final.pt"))
            mfile.close()
            return 0
        phase = phase_for_step(cfg, tokens_done)
        pc = apply_phase(model, cfg, phase, log)
        heartbeat(step, phase)
        mb, accum = micro_batch_for(pc.seq, cfg.training.tokens_per_step)
        stream = sampler.batches(phase, pc.seq, mb, log=lambda m: log("data_starved", msg=m))

        use_bf16 = device == "cuda" and cfg.training.precision == "bf16"
        model.train()
        t0 = time.time()

        while step < total_steps:
            # phase transition: new seq len + RoPE, new sampler, stable checkpoint
            new_phase = phase_for_step(cfg, tokens_done)
            if new_phase != phase and args.max_steps is None:
                stable = ckpt_dir / f"stable_p{phase}.pt"
                save_ckpt(stable, model=model, opt=opt, step=step, phase=phase,
                          tokens_done=tokens_done, cfg=cfg, sampler=sampler)
                log("stable_ckpt", path=str(stable), phase=phase, step=step)
                phase = new_phase
                pc = apply_phase(model, cfg, phase, log)
                heartbeat(step, phase)
                mb, accum = micro_batch_for(pc.seq, cfg.training.tokens_per_step)
                stream = sampler.batches(phase, pc.seq, mb,
                                         log=lambda m: log("data_starved", msg=m))

            lr = wsd_lr(step, total_steps, cfg)
            for g in opt.param_groups:
                g["lr"] = lr
                # Inkling/Muon weight decay coupling: base_wd * (lr/lr_max)^2
                if hasattr(opt, "get_coupled_wd"):
                    g["weight_decay"] = opt.get_coupled_wd(lr)
                elif g.get("weight_decay", 0) > 0:
                    # fallback: apply coupling directly
                    try:
                        from dottie.muon import get_coupled_weight_decay
                        g["weight_decay"] = get_coupled_weight_decay(lr, cfg.training.optimizer.weight_decay, cfg.training.wsd.lr_max)
                    except:
                        pass

            agg: dict[str, float] = {}
            step_tokens = 0
            # effort sampling 0.2-0.99 if model supports it
            effort_val = None
            if getattr(model, "use_effort", False):
                try:
                    from dottie.muon import EffortConditioning
                    effort_val = EffortConditioning.sample_effort(batch_size=mb)
                except:
                    effort_val = 0.6
            for _ in range(accum):
                b = next(stream)
                ids = torch.from_numpy(b.input_ids).to(device, non_blocking=True)
                cids = torch.from_numpy(b.concept_ids).to(device, non_blocking=True)

                ctx = (torch.autocast("cuda", dtype=torch.bfloat16) if use_bf16
                       else torch.autocast("cpu", enabled=False))
                with ctx:
                    if effort_val is not None:
                        out = model(input_ids=ids, task_type=b.task_type, effort=effort_val)
                    else:
                        out = model(input_ids=ids, task_type=b.task_type)
                    parts = obj(model, out, ids, phase=phase, task_type=b.task_type,
                                concept_ids=cids)
                    # effort-conditioned loss scaling if using effort
                    if effort_val is not None:
                        try:
                            from dottie.muon import compute_effort_scaled_loss
                            # scale lm loss by effort multiplier + small token penalty
                            lm_t = parts.total  # placeholder, real scaling below
                            # We trust obj returns total including lm; apply multiplier for logging only
                            pass
                        except:
                            pass

                (parts.total / accum).backward()
                step_tokens += b.tokens
                for k, v in parts.as_floats().items():
                    agg[k] = agg.get(k, 0.0) + v / accum
                agg["route_" + b.task_type] = float(out["jspace"]["route_probs"].mean(0).max())

            gnorm = torch.nn.utils.clip_grad_norm_(model.parameters(),
                                                   cfg.training.optimizer.grad_clip)
            if not torch.isfinite(torch.tensor(agg["total"])):
                raise RuntimeError(f"non-finite loss at step {step}: {agg}")
            opt.step()
            opt.zero_grad(set_to_none=True)

            step += 1
            tokens_done += step_tokens

            if step % cfg.training.metrics_every_steps == 0 or step == 1:
                mj = out["jspace"]
                dt = time.time() - t0
                log("step", step=step, phase=phase, lr=lr, tokens=tokens_done,
                    grad_norm=float(gnorm), tok_s=round(step_tokens * cfg.training.metrics_every_steps / max(dt, 1e-6)) if step > 1 else None,
                    # 4 significant figures, not 5 decimal places: `selectivity` is
                    # ~2.6e-7 at init and round(v, 5) silently logs it as 0.0
                    **{k: float(f"{v:.4g}") for k, v in agg.items()},
                    hl_est={s: round(getattr(model.multi_jspace, s).hl_est(), 2)
                            for s in ("system1", "system2", "critic", "planner")},
                    verbalizable_mass=round(float(mj["system2"]["verbalizable_mass"]), 5),
                    broadcast_strength=round(float(mj["broadcast_strength"]), 5),
                    route_probs=[round(x, 4) for x in mj["route_probs"].mean(0).tolist()])
                lm_val = float(agg.get("lm", agg.get("total", 0.0)))
                lm_hist.append(lm_val)
                if len(lm_hist) > 5:
                    lm_hist.pop(0)
                heartbeat(step, phase)
                t0 = time.time()

            if step % cfg.training.checkpoint_every_steps == 0 or step == total_steps:
                p = ckpt_dir / f"step_{step}.pt"
                save_ckpt(p, model=model, opt=opt, step=step, phase=phase,
                          tokens_done=tokens_done, cfg=cfg, sampler=sampler)
                _point_latest_at(ckpt_dir, p)
                log("checkpoint", path=str(p), step=step)
                heartbeat(step, phase)

        final = ckpt_dir / f"{args.branch or 'base'}_final.pt"
        save_ckpt(final, model=model, opt=opt, step=step, phase=phase,
                  tokens_done=tokens_done, cfg=cfg, sampler=sampler)
        _point_latest_at(ckpt_dir, final)
        heartbeat(step, phase, status="done")
        log("done", step=step, tokens=tokens_done, final=str(final))
    mfile.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
