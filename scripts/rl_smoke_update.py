# Solo personal project, no connection to employer, built with public/free-tier only
"""ONE real GRPO smoke update of a real pilot checkpoint from real CodeAct rollouts.

This is the unblock proof for the RL chain: every stage below runs REAL code — no stubs,
no synthetic logits, no fabricated numbers anywhere in the output:

  1. Load the nano AvaModel with the REAL branch checkpoint from the CPU pilot
     (runs/cpu_pilot/agentic/agentic_final.pt; falls back to base_final.pt and RECORDS which).
  2. Wrap it in the REAL decode policy (`ava.rl.codeact_policy.TorchModelPolicy`, subclassed
     here only to RECORD sampled token ids + their log-probs) and drive
     `ava.rl.codeact_loop.run_code_act` over real T13C.2 trajectory prompts
     (`ava.datagen.codeact.iter_trajectories`) with their `tool_sources`, through the REAL
     subprocess Sandbox. The pilot checkpoint (90+25 smoke steps) emits noise, fails the
     tasks, and earns r_task ~ 0 — that is the EXPECTED, HONEST result at this scale.
  3. Compute real `rl_return`s via `ava.rl.codeact_rewards.codeact_return` from the real
     Observations, group them per prompt through `grpo.group_advantages`, and take ONE real
     backward+optimizer step with `ava.rl.grpo_torch.TorchGRPOStep` on the real weights.
  4. Assert MECHANICAL HEALTH ONLY: finite loss, nonzero grad norm, finite params post-step.
     Append the measured numbers as a "grpo_smoke" section to runs/cpu_pilot/MANIFEST.json
     (or MANIFEST_GRPO.json when the pilot manifest is absent). NO capability claims.

Design decisions (glue-level, documented):

  * **Action segment = the FIRST generated turn.** GRPO's stepper recomputes new log-probs
    with ONE causal forward over `input_ids`, so the action tokens must share a single
    growing context. Turn 1's context is exactly `prompt_ids + generated_prefix` (guarded:
    `len(prompt_ids) + max_new_tokens <= context_window`, so the decode window never
    truncates mid-turn and the alignment is exact). Later turns condition on re-encoded
    transcripts (observation text interleaved), which cannot be expressed in the same
    forward — they still run, still execute code in the sandbox, and still count toward the
    rollout's `rl_return` and total token count; they just don't contribute action tokens.
  * **old_logp is the plain log-softmax** of the raw logits at sample time (temperature- and
    top-k-free), matching how `TorchGRPOStep` scores actions at update time — so on-policy
    ratios are ~1.0 by construction and any deviation is a real numerics signal, not a
    temperature-mismatch artifact. (The behavior distribution that *samples* is tempered /
    top-k filtered — standard off-policy-by-filtering, fine for GRPO.)
  * **Return variance at zero capability**: with r_task ~ 0 across a group, the measured
    variance comes from R_exec/R_codeuse (when a rollout happens to emit runnable code) and
    from R_len over the REAL per-rollout generated-token counts. `--family-pass-rate`
    (default 0.5) is the R_len difficulty weight — a config prior (no pass-rate history
    exists yet), NOT a measurement, and is recorded as config in the manifest. A group whose
    rollouts all tie still yields all-zero advantages (GRPO's correct no-signal behavior);
    the health gate then reports grad_norm honestly and fails if NO group had variance.
  * Recorded stop/EOS tokens stay in the action segment: they were genuinely sampled from
    the policy (the text-level cut is a serving concern, not a probability one).

Usage:
    cd /home/user/ava-agi-factory-v6-4 && python scripts/rl_smoke_update.py
    # options: --prompts 3 --group-size 4 --max-new-tokens 48 --lr 1e-5 ... (see --help)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import torch

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from ava.rl.codeact_loop import run_code_act  # noqa: E402
from ava.rl.codeact_policy import TorchModelPolicy  # noqa: E402
from ava.rl.codeact_rewards import codeact_return  # noqa: E402
from ava.rl.grpo import EntropyThermostat, group_advantages  # noqa: E402
from ava.rl.grpo_torch import GRPOStepStats, TorchGRPOStep  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Recording policy: TorchModelPolicy + capture of (prompt_ids, sampled ids, old log-probs)
# ─────────────────────────────────────────────────────────────────────────────


class RecordingTorchPolicy(TorchModelPolicy):
    """`TorchModelPolicy` that records, per generated turn, the exact decode evidence GRPO
    needs: the prompt ids fed in, every sampled token id (including tokens later cut by the
    stop-matcher — they WERE sampled), and each token's log-prob under the plain (untempered,
    unfiltered) softmax of the raw logits. One instance per episode: `records[0]` is turn 1.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.records: List[Dict[str, list]] = []
        self._cur: Optional[Dict[str, list]] = None

    def _decode_ids(self, prompt_ids: List[int], gen) -> List[int]:
        if not self.records:
            # Turn 1 is the GRPO action segment: its context must never be truncated
            # mid-decode, or the (context -> sampled token) alignment breaks.
            budget = len(prompt_ids) + self.max_new_tokens
            if budget > self.context_window:
                raise ValueError(
                    f"turn-1 prompt ({len(prompt_ids)} tokens) + max_new_tokens "
                    f"({self.max_new_tokens}) = {budget} exceeds context_window "
                    f"({self.context_window}); raise --context-window so the recorded "
                    "action segment stays exactly aligned"
                )
        self._cur = {"prompt_ids": list(prompt_ids), "gen_ids": [], "old_logps": []}
        try:
            return super()._decode_ids(prompt_ids, gen)
        finally:
            self.records.append(self._cur)
            self._cur = None

    def _pick_token(self, logits: torch.Tensor, gen) -> int:
        nxt = super()._pick_token(logits, gen)
        if self._cur is not None:
            logp = torch.log_softmax(logits.detach().to(torch.float32), dim=-1)[nxt]
            self._cur["gen_ids"].append(int(nxt))
            self._cur["old_logps"].append(float(logp))
        return nxt


# ─────────────────────────────────────────────────────────────────────────────
# Rollout collection (real decode -> real sandbox -> real rl_return)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Rollout:
    """One real episode's evidence: rl_return inputs + the turn-1 GRPO action segment."""

    prompt_index: int
    group_index: int
    decode_seed: int
    prompt_ids: List[int]
    gen_ids: List[int]                     # turn-1 sampled action tokens
    old_logps: List[float]                 # plain log-softmax at sample time, one per gen_id
    total_gen_tokens: int                  # across ALL turns (feeds R_len's token_count)
    n_executed_actions: int                # sandbox steps actually run
    terminated: str
    reached_final: bool
    r_task: float
    rl_return: float
    final_excerpt: str
    wall_s: float
    extra: Dict[str, object] = field(default_factory=dict)


def compute_r_task(answer: str, final: Optional[str], reached_final: bool) -> float:
    """Binary task signal: the sanitized FINAL contains the trajectory's labeled answer."""
    if not reached_final or final is None or not answer:
        return 0.0
    return 1.0 if answer in final else 0.0


def collect_rollouts(
    model,
    tokenizer,
    trajectories: Sequence,
    *,
    group_size: int,
    temperature: float,
    top_k: int,
    max_new_tokens: int,
    context_window: int,
    eos_id: Optional[int],
    seed: int,
    max_episode_steps: int,
    timeout_s: float,
    family_pass_rate: float,
    device: str = "cpu",
) -> Tuple[List[Rollout], List[List[float]]]:
    """G real episodes per prompt through the REAL sandbox; returns (rollouts, per-group returns).

    Rollout order is prompt-major (all of prompt 0's group, then prompt 1's, ...), which is the
    exact order `flatten_group_advantages` and `build_grpo_batch` assume.
    """
    rollouts: List[Rollout] = []
    groups: List[List[float]] = []
    for pi, traj in enumerate(trajectories):
        group_returns: List[float] = []
        for g in range(group_size):
            decode_seed = seed * 1_000_000 + pi * 1_000 + g
            policy = RecordingTorchPolicy(
                model,
                tokenizer,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_k=top_k,
                context_window=context_window,
                eos_id=eos_id,
                seed=decode_seed,
                device=device,
            )
            t0 = time.time()
            result = run_code_act(
                policy,
                traj.user,
                tool_sources=dict(traj.tool_sources),
                max_steps=max_episode_steps,
                timeout_s=timeout_s,
            )
            wall = time.time() - t0
            if not policy.records or not policy.records[0]["gen_ids"]:
                # Cannot happen with max_new_tokens >= 1 (even an instant EOS/stop token is
                # recorded), but never silently drop a rollout from a GRPO group.
                raise RuntimeError(
                    f"rollout (prompt={pi}, g={g}) recorded no turn-1 action tokens"
                )
            rec = policy.records[0]
            total_gen = sum(len(r["gen_ids"]) for r in policy.records)
            r_task = compute_r_task(traj.answer, result.final, result.reached_final)
            rl_return = codeact_return(
                r_task,
                result.observations,
                token_count=total_gen,
                family_pass_rate=family_pass_rate,
            )
            rollouts.append(
                Rollout(
                    prompt_index=pi,
                    group_index=g,
                    decode_seed=decode_seed,
                    prompt_ids=list(rec["prompt_ids"]),
                    gen_ids=list(rec["gen_ids"]),
                    old_logps=list(rec["old_logps"]),
                    total_gen_tokens=total_gen,
                    n_executed_actions=len(result.steps),
                    terminated=result.terminated,
                    reached_final=result.reached_final,
                    r_task=r_task,
                    rl_return=rl_return,
                    final_excerpt=(result.final or "")[:120],
                    wall_s=wall,
                )
            )
            group_returns.append(rl_return)
        groups.append(group_returns)
    return rollouts, groups


def flatten_group_advantages(groups: Sequence[Sequence[float]]) -> List[float]:
    """`grpo.group_advantages` per prompt group, flattened in the rollout (prompt-major) order."""
    flat: List[float] = []
    for group_returns in groups:
        flat.extend(group_advantages(list(group_returns)))
    return flat


# ─────────────────────────────────────────────────────────────────────────────
# Batch construction for TorchGRPOStep
# ─────────────────────────────────────────────────────────────────────────────


def build_grpo_batch(
    rollouts: Sequence[Rollout],
    advantages: Sequence[float],
    *,
    pad_id: int = 0,
) -> Dict[str, torch.Tensor]:
    """Right-padded causal-LM batch for `TorchGRPOStep.step`.

    Per rollout, `full = prompt_ids + gen_ids`; the model input is `full[:-1]` (position i's
    logits predict token i+1), `actions[i] = full[i+1]`, and the mask selects exactly the
    generated positions i in [P-1, P+T-2] (P prompt tokens, T generated). `old_logp` is placed
    at those positions; pads carry mask 0 (the stepper zeroes their log-ratio before exp).
    """
    if len(rollouts) != len(advantages):
        raise ValueError(f"{len(rollouts)} rollouts vs {len(advantages)} advantages")
    seqs, acts, olps, msks = [], [], [], []
    for r in rollouts:
        full = list(r.prompt_ids) + list(r.gen_ids)
        if len(r.gen_ids) != len(r.old_logps):
            raise ValueError("gen_ids and old_logps length mismatch")
        if len(full) < 2:
            raise ValueError("rollout needs at least 1 prompt and 1 generated token")
        p = len(r.prompt_ids)
        inp = full[:-1]
        act = full[1:]                      # act[i] == full[i+1]
        mask = [0.0] * len(inp)
        olp = [0.0] * len(inp)
        for t in range(len(r.gen_ids)):     # generated token t sits at input position p-1+t
            mask[p - 1 + t] = 1.0
            olp[p - 1 + t] = r.old_logps[t]
        seqs.append(inp)
        acts.append(act)
        msks.append(mask)
        olps.append(olp)
    lmax = max(len(s) for s in seqs)
    def pad(rows, fill, dtype):
        return torch.tensor([row + [fill] * (lmax - len(row)) for row in rows], dtype=dtype)
    return {
        "input_ids": pad(seqs, pad_id, torch.long),
        "actions": pad(acts, pad_id, torch.long),
        "old_logp": pad(olps, 0.0, torch.float32),
        "mask": pad(msks, 0.0, torch.float32),
        "advantages": torch.tensor(list(advantages), dtype=torch.float32),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Manifest append
# ─────────────────────────────────────────────────────────────────────────────


def append_manifest_section(section: dict, manifest_path: str) -> str:
    """Append `section` under the "grpo_smoke" key of the pilot MANIFEST.json (atomic rewrite).
    If the manifest is absent, write MANIFEST_GRPO.json next to the intended path instead.
    Returns the path actually written."""
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        manifest["grpo_smoke"] = section
        out_path = manifest_path
    else:
        manifest = {"grpo_smoke": section}
        out_path = os.path.join(os.path.dirname(manifest_path) or ".", "MANIFEST_GRPO.json")
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    os.replace(tmp, out_path)
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Main: the one real smoke update
# ─────────────────────────────────────────────────────────────────────────────


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_ckpt(run_dir: str, explicit: Optional[str]) -> Tuple[str, str]:
    """(path, which) — prefers the agentic branch checkpoint, falls back to base pretrain."""
    if explicit:
        if not os.path.exists(explicit):
            raise FileNotFoundError(f"--ckpt {explicit} does not exist")
        return explicit, "explicit"
    agentic = os.path.join(run_dir, "agentic", "agentic_final.pt")
    base = os.path.join(run_dir, "base", "base_final.pt")
    if os.path.exists(agentic):
        return agentic, "agentic_branch"
    if os.path.exists(base):
        return base, "base_pretrain_fallback"
    raise FileNotFoundError(
        f"no pilot checkpoint under {run_dir} (looked for {agentic} and {base}); "
        "run scripts/cpu_pilot_e2e.py first"
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-dir", default=os.path.join(_REPO, "runs", "cpu_pilot"))
    ap.add_argument("--ckpt", default=None, help="explicit checkpoint path (default: agentic, else base)")
    ap.add_argument("--tokenizer", default=None, help="default: <run-dir>/tokenizer/ava_nano_bpe.json")
    ap.add_argument("--preset", default="nano")
    ap.add_argument("--device", default="cpu", choices=["cpu", "cuda"],
                    help="model device; cuda inside the ava-train compose service for GPU offload "
                         "(seeded decodes stay bit-identical — sampling draws on CPU)")
    ap.add_argument("--prompts", type=int, default=3, help="distinct T13C.2 prompts")
    ap.add_argument("--group-size", type=int, default=4, help="G rollouts per prompt")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--max-new-tokens", type=int, default=48)
    ap.add_argument("--context-window", type=int, default=768)
    ap.add_argument("--max-episode-steps", type=int, default=2)
    ap.add_argument("--timeout-s", type=float, default=5.0)
    ap.add_argument("--family-pass-rate", type=float, default=0.5,
                    help="R_len difficulty prior (config knob, no pass-rate history exists yet)")
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--r-outer", type=float, default=1.0)
    ap.add_argument("--kappa", type=float, default=0.5)
    ap.add_argument("--h-target", type=float, default=0.3)
    ap.add_argument("--clip-eps", type=float, default=0.2)
    ap.add_argument("--k-max", type=float, default=4.0)
    ap.add_argument("--manifest", default=None, help="default: <run-dir>/MANIFEST.json")
    ap.add_argument("--save-updated", default=None,
                    help="optional path to save the post-update model state_dict")
    return ap.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    t_start = time.time()
    torch.manual_seed(args.seed)

    from ava.config import AvaConfig
    from ava.model import build_model, count_params
    from ava.tokenizer import EOS_ID, AvaTokenizer

    # 1. Real checkpoint into the real nano model ---------------------------------
    t0 = time.time()
    ckpt_path, ckpt_which = _resolve_ckpt(args.run_dir, args.ckpt)
    cfg = AvaConfig.load(args.preset)
    model = build_model(cfg)
    blob = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    model.load_state_dict(blob["model"])
    model.to(args.device)
    model.eval()  # dropout-free forwards: rollout scoring and update forward match exactly
    tok_path = args.tokenizer or os.path.join(args.run_dir, "tokenizer", "ava_nano_bpe.json")
    tokenizer = AvaTokenizer.load(tok_path)
    load_s = time.time() - t0
    print(f"[load] {ckpt_which}: {ckpt_path} (train step {blob.get('step')}) "
          f"params={count_params(model)} tokenizer={tok_path} vocab={tokenizer.vocab_size} "
          f"({load_s:.1f}s)")

    # 2. Real CodeAct rollouts through the real sandbox ---------------------------
    from ava.datagen.codeact import iter_trajectories

    trajs = list(iter_trajectories(seed=args.seed, n=args.prompts))
    t0 = time.time()
    rollouts, groups = collect_rollouts(
        model, tokenizer, trajs,
        group_size=args.group_size, temperature=args.temperature, top_k=args.top_k,
        max_new_tokens=args.max_new_tokens, context_window=args.context_window,
        eos_id=EOS_ID, seed=args.seed, max_episode_steps=args.max_episode_steps,
        timeout_s=args.timeout_s, family_pass_rate=args.family_pass_rate,
        device=args.device,
    )
    rollout_s = time.time() - t0
    for r in rollouts:
        print(f"[rollout] p{r.prompt_index} g{r.group_index} seed={r.decode_seed} "
              f"turn1_tokens={len(r.gen_ids)} total_tokens={r.total_gen_tokens} "
              f"exec_actions={r.n_executed_actions} terminated={r.terminated} "
              f"r_task={r.r_task} rl_return={r.rl_return:.4f} ({r.wall_s:.1f}s)")
    mean_rl_return = sum(r.rl_return for r in rollouts) / len(rollouts)
    mean_r_task = sum(r.r_task for r in rollouts) / len(rollouts)
    print(f"[rollouts] n={len(rollouts)} mean_r_task={mean_r_task:.3f} "
          f"mean_rl_return={mean_rl_return:.4f} ({rollout_s:.1f}s)")

    # 3. One real GRPO update -----------------------------------------------------
    advantages = flatten_group_advantages(groups)
    batch = build_grpo_batch(rollouts, advantages)
    thermostat = EntropyThermostat(
        kappa=args.kappa, h_target=args.h_target, eps=args.clip_eps, k_max=args.k_max
    )
    k_before = thermostat.k
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    stepper = TorchGRPOStep(
        model, optimizer, thermostat, r_outer=args.r_outer, logits_key="lm_logits"
    )
    params_before = [p.detach().clone() for p in model.parameters()]
    t0 = time.time()
    dev = args.device   # the update forward must run where the policy's weights live
    stats: GRPOStepStats = stepper.step(
        {"input_ids": batch["input_ids"].to(dev)},
        batch["actions"].to(dev),
        batch["old_logp"].to(dev),
        batch["advantages"].to(dev),
        mask=batch["mask"].to(dev),
    )
    step_s = time.time() - t0
    with torch.no_grad():
        deltas = [
            (p - q).norm() for p, q in zip(model.parameters(), params_before)
        ]
        param_delta_l2 = float(torch.linalg.vector_norm(torch.stack(deltas)))
        params_finite = all(bool(torch.isfinite(p).all()) for p in model.parameters())
    print(f"[grpo] loss={stats.loss:.6f} mean_objective={stats.mean_objective:.6f} "
          f"rl.entropy={stats.rl_entropy:.4f} rl.k={k_before}->{stats.rl_k} "
          f"clip=({stats.clip_lower:.4f},{stats.clip_upper:.4f}) "
          f"rl.outer_clip_hits={stats.outer_clip_hits} inner_clip_hits={stats.inner_clip_hits} "
          f"mean_ratio={stats.mean_ratio:.6f} grad_norm={stats.grad_norm:.6f} "
          f"batch={stats.batch_size} param_delta_l2={param_delta_l2:.6e} ({step_s:.1f}s)")

    if args.save_updated:
        torch.save({"model": model.state_dict(), "grpo_smoke": True}, args.save_updated)
        print(f"[save] post-update state_dict -> {args.save_updated}")

    # 4. Mechanical health gate (NO capability claims) ----------------------------
    health = {
        "loss_finite": math.isfinite(stats.loss),
        "grad_norm_gt_zero": stats.grad_norm > 0.0,
        "params_finite_post_step": params_finite,
        "param_delta_l2_gt_zero": param_delta_l2 > 0.0,
        "entropy_finite": math.isfinite(stats.rl_entropy),
        "thermostat_k_in_bounds": 0.0 <= stats.rl_k <= args.k_max,
    }
    ok = all(health.values())
    failures = [k for k, v in health.items() if not v]

    section = {
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scale": "smoke_cpu_pilot",
        "capability_claim": "none",
        "note": (
            "ONE real GRPO update on the real pilot checkpoint from real CodeAct rollouts "
            "through the real sandbox. The checkpoint has ~zero capability (90+25 smoke "
            "steps); r_task~0 is the expected honest result. Mechanical health only."
        ),
        "argv": list(argv) if argv is not None else sys.argv[1:],
        "checkpoint": {
            "path": os.path.relpath(ckpt_path, _REPO),
            "which": ckpt_which,
            "train_step": blob.get("step"),
            "sha256": _sha256(ckpt_path),
        },
        "tokenizer": os.path.relpath(tok_path, _REPO),
        "config": {
            "preset": args.preset, "prompts": args.prompts, "group_size": args.group_size,
            "seed": args.seed, "temperature": args.temperature, "top_k": args.top_k,
            "max_new_tokens": args.max_new_tokens, "context_window": args.context_window,
            "max_episode_steps": args.max_episode_steps, "timeout_s": args.timeout_s,
            "family_pass_rate_prior": args.family_pass_rate, "lr": args.lr,
            "r_outer": args.r_outer, "kappa": args.kappa, "h_target": args.h_target,
            "clip_eps": args.clip_eps, "k_max": args.k_max,
        },
        "rollouts": {
            "n": len(rollouts),
            "mean_r_task": mean_r_task,
            "mean_rl_return": mean_rl_return,
            "returns_by_group": [list(g) for g in groups],
            "advantages": advantages,
            "per_rollout": [
                {
                    "prompt": r.prompt_index, "g": r.group_index, "decode_seed": r.decode_seed,
                    "turn1_action_tokens": len(r.gen_ids),
                    "total_gen_tokens": r.total_gen_tokens,
                    "executed_actions": r.n_executed_actions,
                    "terminated": r.terminated, "reached_final": r.reached_final,
                    "r_task": r.r_task, "rl_return": r.rl_return,
                    "final_excerpt": r.final_excerpt, "wall_s": round(r.wall_s, 3),
                }
                for r in rollouts
            ],
        },
        "grpo_step": {
            "loss": stats.loss, "mean_objective": stats.mean_objective,
            "rl.entropy": stats.rl_entropy, "rl.k_before": k_before, "rl.k": stats.rl_k,
            "clip_lower": stats.clip_lower, "clip_upper": stats.clip_upper,
            "rl.outer_clip_hits": stats.outer_clip_hits,
            "inner_clip_hits": stats.inner_clip_hits, "mean_ratio": stats.mean_ratio,
            "grad_norm": stats.grad_norm, "batch_size": stats.batch_size,
            "param_delta_l2": param_delta_l2,
        },
        "health": {**health, "status": "success" if ok else "failed",
                   "failures": failures},
        "timings_s": {
            "load": round(load_s, 2), "rollouts": round(rollout_s, 2),
            "grpo_step": round(step_s, 2), "total": round(time.time() - t_start, 2),
        },
    }
    manifest_path = args.manifest or os.path.join(args.run_dir, "MANIFEST.json")
    written = append_manifest_section(section, manifest_path)
    print(f"[manifest] grpo_smoke section -> {written}")

    if not ok:
        print(f"[health] FAILED: {failures}", file=sys.stderr)
        return 1
    print("[health] all mechanical checks passed (no capability claims)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
