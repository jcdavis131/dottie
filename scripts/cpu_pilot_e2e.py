# Solo personal project, no connection to employer, built with public/free-tier only
"""CPU-pilot end-to-end chain (T9.3/T9.5 mechanism at nano smoke scale).

Runs the REAL pipeline, no stage faked:

    1. corpus    — six ava.datagen generators (logic, math, codeact, ency,
                   chat, code) write zstd JSONL raw shards via
                   ``ava.datagen.base.write_shards``.
    2. tokenizer — ``ava.tokenizer.train`` trains the byte-level BPE at the
                   nano vocab (8192) on that corpus. Empirically the templated
                   synthetic corpus saturates BPE merges: 6 MB reaches only
                   ~6.6k merges; ~17 MB across all six generators is the
                   smallest corpus that reaches the full 8192 — hence the
                   default ``--corpus-mb 17``.
    3. pack      — ``ava.pipeline.pack`` tokenizes docs into uint16 ``.bin`` +
                   ``.idx.json`` shards; shards are registered through the real
                   manifest state machine (RAW -> claim(curate) -> PACKED) with
                   the tokenizer frozen in the manifest DB.
    4. pretrain  — ``python -m ava.train --preset nano --device cpu`` consumes
                   the packed shards through StreamingShardSampler.
    5. branch    — ``--branch agentic --init <base ckpt>`` forks a fine-tune
                   from the pretrain checkpoint (freeze system1/system2, router
                   prior toward planner) — the actual branch-fork mechanism.

Everything lands under ``--out`` (default runs/cpu_pilot). A MANIFEST.json is
written with real timings, byte counts, sha256s and the full logged loss
series of both runs. Scale is smoke: a ~14M-param CPU model trained for tens
of steps has NO capability, and the manifest says so explicitly.

Notes on honesty:
  * The trainer only claims manifest-phase-0 shards at tokens_done ~ 0, so all
    packed shards are registered under manifest phase 0 for this smoke run
    (each doc keeps its own curriculum phase tag in the idx sidecar).
  * The corpus is small, so each packed shard file is registered multiple
    times (distinct shard ids, same file) to give the sampler enough runway —
    i.e. the smoke run may repeat data. The number of registered copies is
    recorded in the manifest as ``shard_copies_registered``.
  * The ``agentic`` branch spec does not exist in configs/nano.yaml; this
    script writes a *copy* of the config dir under ``--out`` with a
    ``branches.agentic`` section added and ``metrics_every_steps: 1`` (so the
    manifest carries a per-step loss series instead of every-10th), and points
    both training runs at it via ``AVA_CONFIG_DIR``. No repo config file is
    modified; all other config values are byte-for-byte the nano preset's.

Usage:
    python scripts/cpu_pilot_e2e.py --steps 60 --branch-steps 20 \\
        --corpus-mb 4 --out runs/cpu_pilot
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

TOKENS_PER_STEP = 8192          # nano tokens_per_step (configs/nano.yaml)
SUPPLY_SAFETY = 2.0             # runway over-provisioning vs. exact step budget
DOCS_PER_SHARD = 600            # packing granularity for the smoke corpus


class StageError(RuntimeError):
    """A pipeline stage failed; message carries the real underlying error."""


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# stage 1: corpus


def stage_corpus(raw_dir: Path, corpus_mb: float, seed: int) -> dict:
    """Generate the raw corpus with six real repo generators (max diversity —
    needed for the byte-level BPE to reach the full 8192-merge vocab)."""
    from ava.datagen.base import write_shards
    from ava.datagen.chat_safety import ChatSafetyGenerator
    from ava.datagen.code_gen import CodeGenGenerator
    from ava.datagen.codeact import CodeActGenerator
    from ava.datagen.encyclopedia import EncyclopediaGenerator
    from ava.datagen.logic import LogicGenerator
    from ava.datagen.math_gen import MathGenerator

    gens = (LogicGenerator, MathGenerator, CodeActGenerator,
            EncyclopediaGenerator, ChatSafetyGenerator, CodeGenGenerator)
    raw_dir.mkdir(parents=True, exist_ok=True)
    per_gen_mb = corpus_mb / len(gens)
    out: dict = {"generators": {}, "bytes": 0, "docs": 0}
    for i, cls in enumerate(gens):
        gen = cls(seed=seed + i)
        r = write_shards(gen, str(raw_dir), per_gen_mb, shard_mb=2.0)
        out["generators"][gen.name] = {
            "files": r["files"], "bytes": r["bytes"], "docs": r["docs"],
            "sha256": r["sha256"], "seed": seed + i,
        }
        out["bytes"] += r["bytes"]
        out["docs"] += r["docs"]
    if out["docs"] == 0:
        raise StageError("corpus stage produced zero docs")
    return out


# ---------------------------------------------------------------------------
# stage 2: tokenizer


def stage_tokenizer(raw_dir: Path, tok_path: Path, vocab: int) -> dict:
    from ava.tokenizer import AvaTokenizer, train

    sha = train(str(raw_dir), str(tok_path), vocab)
    t = AvaTokenizer.load(tok_path)  # validates frozen special ids 0..5
    if t.vocab_size > vocab:
        raise StageError(f"tokenizer vocab {t.vocab_size} exceeds requested {vocab}")
    return {"path": str(tok_path), "sha256": sha, "vocab_size": t.vocab_size,
            "requested_vocab": vocab}


# ---------------------------------------------------------------------------
# stage 3: pack + manifest registration


def stage_pack(raw_dir: Path, packed_dir: Path, tok_path: Path) -> dict:
    from ava.datagen.base import read_shards
    from ava.pipeline.pack import load_tokenizer, pack_docs, write_shard

    packed_dir.mkdir(parents=True, exist_ok=True)
    lt = load_tokenizer(tok_path)
    docs = list(read_shards(str(raw_dir)))
    if not docs:
        raise StageError(f"no docs readable from {raw_dir}")

    shards: list[dict] = []
    for si in range(0, len(docs), DOCS_PER_SHARD):
        chunk = docs[si:si + DOCS_PER_SHARD]
        arr, idx = pack_docs(chunk, lt)
        bin_path = packed_dir / f"cpu_pilot_{si // DOCS_PER_SHARD:04d}.bin"
        bpath, ipath = write_shard(arr, idx, bin_path)
        shards.append({
            "bin": str(bpath), "idx": str(ipath),
            "tokens": int(idx["tokens"]), "docs": len(chunk),
            "bytes": bpath.stat().st_size,
        })
    return {"tokenizer_sha": lt.sha256, "eod_id": lt.eod_id,
            "total_tokens": sum(s["tokens"] for s in shards), "shards": shards}


def stage_register(pack_info: dict, vocab: int, needed_tokens: int) -> dict:
    """Register packed shards via the REAL manifest state machine.

    Freezes the tokenizer sha, then drives each shard entry through
    RAW -> CLAIMED_CURATE -> PACKED exactly as a curator would. The corpus is
    tiny, so each physical shard file is registered ``copies`` times (distinct
    ids) so two short training runs cannot starve the sampler.
    """
    from ava.pipeline.manifest import Manifest, worker_id

    total = pack_info["total_tokens"]
    copies = max(1, math.ceil(needed_tokens * SUPPLY_SAFETY / max(1, total)))
    tokens_by_path = {s["bin"]: s for s in pack_info["shards"]}

    with Manifest() as m:
        m.freeze_tokenizer(pack_info["tokenizer_sha"], vocab)
        wid = worker_id()
        registered = 0
        for c in range(copies):
            for s in pack_info["shards"]:
                sid = f"cpu_pilot:{Path(s['bin']).stem}:copy{c}"
                m.add_shard(sid, source="cpu_pilot_e2e", phase=0, path=s["bin"],
                            bytes_=s["bytes"], docs=s["docs"])
                registered += 1
        # curate-complete every RAW entry so it lands PACKED with token counts
        completed = 0
        while True:
            claimed = m.claim("curate", by=wid)
            if claimed is None:
                break
            info = tokens_by_path[claimed.path]
            m.complete(claimed.id, by=wid, path=claimed.path,
                       tokens=info["tokens"], docs=info["docs"],
                       tokenizer_sha=pack_info["tokenizer_sha"],
                       bytes_=info["bytes"])
            completed += 1
        ready = m.tokens_ready(0)

    return {"db": os.environ.get("AVA_STATE_DB", "/state/manifest.db"),
            "shard_copies_registered": copies, "entries_registered": registered,
            "entries_packed": completed, "tokens_ready_phase0": ready,
            "needed_tokens": needed_tokens}


# ---------------------------------------------------------------------------
# stages 4/5: training subprocesses


def run_train(*, out: Path, run_dir: Path, reports_dir: Path, packed_dir: Path,
              steps: int, seed: int, env: dict, branch: str | None = None,
              init: Path | None = None, timeout_s: int = 1800,
              preset: str = "nano", device: str = "cpu") -> dict:
    """Run ``python -m ava.train`` as a subprocess and parse its metrics.

    `preset`/`device` default to the nano CPU pilot but are parameterized so the SAME chain
    scales onto a GPU box: ``--preset mini --device cuda`` inside the `ava-train` compose
    service is the capability-scale run (T9.3/T9.5 proper), not a different pipeline."""
    cmd = [sys.executable, "-m", "ava.train", "--preset", preset, "--device", device,
           "--run", str(run_dir), "--reports", str(reports_dir),
           "--packed", str(packed_dir), "--max-steps", str(steps),
           "--seed", str(seed)]
    if branch:
        cmd += ["--branch", branch]
    if init:
        cmd += ["--init", str(init)]

    log_path = reports_dir / "train_stdout.log"
    reports_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with open(log_path, "w") as lf:
        try:
            proc = subprocess.run(cmd, cwd=str(REPO), env=env, stdout=lf,
                                  stderr=subprocess.STDOUT, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            raise StageError(
                f"training run {branch or 'base'} exceeded {timeout_s}s watchdog "
                f"(likely DATA_STARVED — see {log_path})")
    wall = time.time() - t0
    if proc.returncode != 0:
        tail = "\n".join(log_path.read_text().splitlines()[-30:])
        raise StageError(
            f"ava.train exited {proc.returncode} for run {branch or 'base'}.\n"
            f"cmd: {' '.join(cmd)}\nlog tail:\n{tail}")

    metrics = parse_metrics(reports_dir / f"metrics_{preset}.jsonl")
    final_ckpt = run_dir / f"{branch or 'base'}_final.pt"
    if not final_ckpt.exists():
        raise StageError(f"training finished but final checkpoint missing: {final_ckpt}")
    return {"cmd": cmd, "wall_seconds": round(wall, 2), "steps": steps,
            "log": str(log_path), "final_ckpt": str(final_ckpt),
            "final_ckpt_sha256": sha256_file(final_ckpt),
            "final_ckpt_bytes": final_ckpt.stat().st_size, **metrics}


def parse_metrics(path: Path) -> dict:
    """Extract the real logged loss series from the trainer's metrics jsonl."""
    if not path.exists():
        raise StageError(f"metrics file missing: {path}")
    steps, lm, total, model_built, branch_forked = [], [], [], None, None
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        ev = rec.get("event")
        if ev == "step":
            steps.append(int(rec["step"]))
            lm.append(float(rec.get("lm", float("nan"))))
            total.append(float(rec.get("total", float("nan"))))
        elif ev == "model_built":
            model_built = {"params": rec.get("params"), "vocab": rec.get("vocab")}
        elif ev == "branch_forked":
            branch_forked = {k: rec.get(k) for k in
                             ("branch", "init", "step", "frozen", "trainable")}
    if not steps:
        raise StageError(f"no 'step' events found in {path}")
    out = {"metrics_file": str(path), "logged_steps": steps,
           "lm_loss_series": lm, "total_loss_series": total,
           "model_built": model_built}
    if branch_forked:
        out["branch_forked"] = branch_forked
    return out


# ---------------------------------------------------------------------------
# pilot config (agentic branch spec + per-step metrics, in a COPIED config
# dir — repo configs are never modified)


def write_pilot_config(out: Path, preset: str = "nano") -> Path:
    import yaml

    cfg_dir = out / "configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    for f in (REPO / "configs").glob("*.yaml"):
        shutil.copy2(f, cfg_dir / f.name)
    nano = cfg_dir / f"{preset}.yaml"
    raw = yaml.safe_load(nano.read_text())
    # log every step so the manifest carries a full per-step loss series
    raw["training"]["metrics_every_steps"] = 1
    raw["branches"] = {
        "agentic": {
            "init": str(out / "base" / "base_final.pt"),
            "lr": 2.5e-4,
            "freeze": ["system1", "system2"],
            "finetune": ["critic", "planner", "router", "arbitration"],
            # planner-forward prior for agentic/tool-use behavior
            "router_bias": [0.15, 0.30, 0.15, 0.40],
            "target_hl": {"system1": 8, "system2": 60, "critic": 35, "planner": 55},
            "mix": {"codeact": 0.6, "logic": 0.2, "math": 0.2},
        }
    }
    nano.write_text(yaml.safe_dump(raw, sort_keys=False))
    return cfg_dir


# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--steps", type=int, default=90, help="pretrain steps")
    ap.add_argument("--branch-steps", type=int, default=25, help="branch fine-tune steps")
    ap.add_argument("--corpus-mb", type=float, default=17.0,
                    help="raw corpus size, MB (~17 MB reaches the full 8192 BPE vocab)")
    ap.add_argument("--out", default=str(REPO / "runs" / "cpu_pilot"))
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--preset", default="nano",
                    help="config preset; 'mini' + --device cuda = the capability-scale run on a GPU box")
    ap.add_argument("--device", default="cpu", choices=["cpu", "cuda"],
                    help="training device; cuda inside the ava-train compose service for GPU offload")
    ap.add_argument("--vocab", type=int, default=8192)
    ap.add_argument("--train-timeout-s", type=int, default=1800,
                    help="watchdog per training subprocess")
    args = ap.parse_args(argv)

    out = Path(args.out).resolve()
    raw_dir, packed_dir = out / "raw", out / "packed"
    tok_path = out / "tokenizer" / "ava_nano_bpe.json"
    state_dir = out / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    # Environment for every stage: manifest DB, pipeline flow config, demand
    # snapshot path, tokenizer path — all scoped under --out.
    env = dict(os.environ)
    env.update({
        "AVA_STATE_DB": str(state_dir / "manifest.db"),
        "AVA_PIPELINE_CONFIG": str(REPO / "configs" / "pipeline.yaml"),
        "AVA_DEMAND_PATH": str(state_dir / "demand.json"),
        "AVA_TOKENIZER": str(tok_path),
        "AVA_REPORTS_DIR": str(out / "reports"),
        "OMP_NUM_THREADS": env.get("OMP_NUM_THREADS", "4"),
        "PYTHONPATH": str(REPO),
    })
    # in-process stages read the same env
    os.environ.update({k: env[k] for k in
                       ("AVA_STATE_DB", "AVA_PIPELINE_CONFIG", "AVA_DEMAND_PATH",
                        "AVA_TOKENIZER")})

    manifest: dict = {
        "scale": "smoke_cpu_pilot",
        "capability_claim": "none",
        "note": ("nano (~14M param) CPU smoke run proving every pipeline stage "
                 "is real end-to-end; loss numbers are real measurements at "
                 "smoke scale and imply no model capability."),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": args.seed,
        "args": vars(args),
        "stages": {},
        "runs": {},
    }
    manifest_path = out / "MANIFEST.json"

    def record(stage: str, t0: float, payload: dict) -> None:
        manifest["stages"][stage] = {"seconds": round(time.time() - t0, 2), **payload}
        manifest_path.write_text(json.dumps(manifest, indent=2))

    try:
        t = time.time()
        corpus = stage_corpus(raw_dir, args.corpus_mb, args.seed)
        record("corpus", t, corpus)
        print(f"[corpus] {corpus['bytes']} bytes, {corpus['docs']} docs")

        t = time.time()
        tok = stage_tokenizer(raw_dir, tok_path, args.vocab)
        record("tokenizer", t, tok)
        print(f"[tokenizer] vocab={tok['vocab_size']} sha={tok['sha256'][:12]}")

        t = time.time()
        pack = stage_pack(raw_dir, packed_dir, tok_path)
        record("pack", t, pack)
        print(f"[pack] {pack['total_tokens']} tokens in {len(pack['shards'])} shards")

        t = time.time()
        needed = (args.steps + args.branch_steps) * TOKENS_PER_STEP
        reg = stage_register(pack, tok["vocab_size"], needed)
        record("register", t, reg)
        print(f"[register] {reg['entries_packed']} PACKED entries, "
              f"{reg['tokens_ready_phase0']} tokens ready")

        cfg_dir = write_pilot_config(out, preset=args.preset)
        env["AVA_CONFIG_DIR"] = str(cfg_dir)
        manifest["config_dir"] = str(cfg_dir)

        t = time.time()
        base = run_train(out=out, run_dir=out / "base",
                         reports_dir=out / "reports" / "base",
                         packed_dir=packed_dir, steps=args.steps,
                         seed=args.seed, env=env, timeout_s=args.train_timeout_s,
                         preset=args.preset, device=args.device)
        manifest["runs"]["pretrain"] = base
        record("pretrain", t, {"wall_seconds": base["wall_seconds"]})
        print(f"[pretrain] {args.steps} steps in {base['wall_seconds']}s; "
              f"lm {base['lm_loss_series'][0]:.3f} -> {base['lm_loss_series'][-1]:.3f}")

        t = time.time()
        branch = run_train(out=out, run_dir=out / "agentic",
                           reports_dir=out / "reports" / "agentic",
                           packed_dir=packed_dir, steps=args.branch_steps,
                           seed=args.seed + 1, env=env, branch="agentic",
                           init=Path(base["final_ckpt"]),
                           timeout_s=args.train_timeout_s,
                           preset=args.preset, device=args.device)
        branch["config_dir"] = str(cfg_dir)
        manifest["runs"]["branch_agentic"] = branch
        record("branch", t, {"wall_seconds": branch["wall_seconds"]})
        print(f"[branch] {args.branch_steps} steps in {branch['wall_seconds']}s; "
              f"lm {branch['lm_loss_series'][0]:.3f} -> {branch['lm_loss_series'][-1]:.3f}")

        manifest["status"] = "success"
    except Exception as e:  # record the REAL error verbatim, then re-raise
        manifest["status"] = "failed"
        manifest["error"] = f"{type(e).__name__}: {e}"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        raise

    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"[done] manifest -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
