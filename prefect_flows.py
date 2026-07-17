# Solo personal project, no connection to employer, built with public/free-tier only
"""
Ava AGI Factory v6.4 — Prefect Flows
Free-tier self-hosted: pip install prefect, prefect server start --port 4200

HONESTY CONTRACT (audit rework): every task either subprocess-runs the REAL
implementation (logic_textbook_pipeline.py, python -m ava.tokenizer,
python -m ava.train, python -m evals.run_harness, eval_frontier_rubric.py,
scripts/hf_uploader.py) or raises BlockedError explaining what is missing —
the same refusal pattern as ava/rl's *BlockedError gates. No task fabricates
loss curves, checkpoints, tokenizers, scores, or deploy URLs.

Runnable:
  python prefect_flows.py --run data        # real small streaming generation run
  python prefect_flows.py --run train --preset nano   # real smoke train (needs packed shards)
  python prefect_flows.py --run eval        # real evals.run_harness + frontier rubric script
  python prefect_flows.py --run all --preset nano

Deploy:
  prefect deployment build prefect_flows.py:ava_data_gen_flow -n daily --cron "0 6 * * *" --apply
  prefect agent start -q default

Docker integration:
  Set PREFECT_API_URL=http://host.docker.internal:4200/api in docker-compose
  OLLAMA_HOST=http://host.docker.internal:11434 for free judging
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Try import prefect, fallback to no-op decorators if not installed so file still imports
try:
    from prefect import flow, task, get_run_logger
    PREFECT_AVAILABLE = True
except ImportError:
    PREFECT_AVAILABLE = False
    def flow(*args, **kwargs):
        def deco(fn): return fn
        if args and callable(args[0]): return args[0]
        return deco
    def task(*args, **kwargs):
        def deco(fn): return fn
        if args and callable(args[0]): return args[0]
        return deco
    def get_run_logger():
        import logging
        return logging.getLogger("prefect_mock")

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"
# Report HTML destination: env-configurable, defaults inside this checkout
# (was a hardcoded other-host absolute path under ~/workspace/your_files).
LOG_HTML_DIR = Path(os.getenv("AVA_LOG_HTML_DIR", str(ROOT / "reports")))
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:32b")


class BlockedError(RuntimeError):
    """Raised instead of fabricating an output (mirrors ava/rl's honesty gates)."""


# ---------- Helpers ----------
def _log(msg):
    try:
        logger = get_run_logger()
        logger.info(msg)
    except Exception:
        print(msg)


def _run(cmd, timeout=1800, cwd=None):
    """subprocess.run wrapper: logs the command, raises with real stderr on failure."""
    cmd = [str(c) for c in cmd]
    _log(f"[run] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True, timeout=timeout)
    if res.stdout:
        _log(res.stdout[-2000:])
    if res.returncode != 0:
        raise RuntimeError(
            f"command failed rc={res.returncode}: {' '.join(cmd)}\nstderr tail: {res.stderr[-2000:]}"
        )
    return res


# ---------- HF PUSH TASK (real subprocess to scripts/hf_uploader.py) ----------
@task(retries=3, retry_delay_seconds=[30, 120, 300], log_prints=True)
def push_to_hf_task(manifest_path: str = "data/daily_expanded/manifest_*.jsonl", repo: str = "jcdavis131/ava-textbook-v6", private: bool = True):
    """Push curated train/val/test to HF Hub — Solo personal project, no work Drive"""
    _log(f"[hf] push_to_hf repo={repo} manifest={manifest_path}")
    hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
    uploader = ROOT / "scripts" / "hf_uploader.py"
    if not hf_token:
        _log("[hf] HF_TOKEN not set — running hf_uploader dry-run (no upload)")
        try:
            _run([sys.executable, uploader, "--repo", repo, "--manifest", manifest_path, "--dry-run"], timeout=60)
        except Exception as e:
            _log(f"[hf] dry-run warning: {e}")
        return {"pushed": False, "reason": "no_token", "repo": repo}
    res = _run([sys.executable, uploader, "--repo", repo, "--manifest", manifest_path, "--private", "--push"], timeout=300)
    return {"pushed": res.returncode == 0, "repo": repo}


# ---------- DATA GEN FLOW ----------
@task(retries=3, retry_delay_seconds=[10, 60, 300], log_prints=True)
def generate_phase(phase: str, tokens: int = 50_000_000):
    """REAL run of logic_textbook_pipeline.py (deterministic heuristic filter),
    bounded to a small streaming shard so the task stays quick."""
    out = DATA_DIR / "mini" / "raw" / phase
    out.mkdir(parents=True, exist_ok=True)
    script = ROOT / "logic_textbook_pipeline.py"
    if not script.exists():
        raise BlockedError(f"logic_textbook_pipeline.py missing at {script}; nothing to generate")
    existing = len(list(out.rglob("*.jsonl*")))
    _run([sys.executable, script, "--out", out, "--shard_mb", "1",
          "--max_shards", str(existing + 1), "--sleep", "0"], timeout=600)
    n_shards = len(list(out.rglob("*.jsonl*")))
    _log(f"[data] generate_phase {phase}: {n_shards} shard file(s) under {out}")
    return str(out)


@task(retries=2, log_prints=True)
def build_tokenizer(vocab_size: int = 8192, corpus_dir: str = None):
    """REAL BPE training via python -m ava.tokenizer train."""
    corpus = Path(corpus_dir) if corpus_dir else (DATA_DIR / "mini" / "raw")
    if not corpus.exists() or not any(corpus.rglob("*.jsonl*")):
        raise BlockedError(
            f"no corpus under {corpus}; run the data-gen flow (or scripts/cpu_pilot_e2e.py) first"
        )
    tok_path = DATA_DIR / "mini" / "tokenizer" / "ava_bpe.json"
    tok_path.parent.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "ava.tokenizer", "train", "--corpus", corpus,
          "--out", tok_path, "--vocab", str(vocab_size)], timeout=1800)
    return str(tok_path)


@task(retries=2, log_prints=True)
def pack_shards(phase_dirs, seq_len: int = 1024):
    """Packing is implemented for real in scripts/cpu_pilot_e2e.py (stage_pack).
    Refuse rather than write a placeholder manifest that pretends packing happened."""
    raise BlockedError(
        "pack_shards is not wired as a standalone Prefect task; run the real packer via "
        "`python scripts/cpu_pilot_e2e.py` (stage_pack) which tokenizes + packs + registers "
        f"shards. Inputs that would have been packed: {list(phase_dirs)} seq_len={seq_len}"
    )


@flow(name="ava-data-gen", log_prints=True)
def ava_data_gen_flow(preset: str = "mini", tokens: int = 50_000_000):
    _log(f"Starting data_gen_flow preset={preset} tokens={tokens}")
    phases = ["p0_logic", "p1_math", "p2_foundation", "p3_code"] if preset != "nano" else ["p0_logic", "p1_math"]
    if PREFECT_AVAILABLE:
        raw_dirs = generate_phase.map(phases, tokens)
    else:
        raw_dirs = [generate_phase(p, tokens) for p in phases]
    tok = build_tokenizer()
    hf_res = push_to_hf_task(manifest_path="data/daily_expanded/manifest_*.jsonl")
    return {"tokenizer": tok, "raw": raw_dirs, "hf": hf_res}


# ---------- TRAIN FLOW ----------
@task(retries=2, retry_delay_seconds=[30, 120], log_prints=True)
def torchrun_train(preset: str, tokens_total: int, resume: bool = True, max_steps: int = 20):
    """REAL smoke training via python -m ava.train (CPU nano scale). Needs real
    packed shards; refuses if none exist instead of writing a fake checkpoint."""
    packed = Path(os.getenv("AVA_PACKED_DIR", str(ROOT / "runs" / "cpu_pilot" / "packed")))
    if not packed.exists() or not any(packed.iterdir()):
        raise BlockedError(
            f"no packed shards at {packed}; run `python scripts/cpu_pilot_e2e.py` first "
            "or point AVA_PACKED_DIR at a real packed dir"
        )
    run_dir = ROOT / "runs" / f"prefect_{preset}"
    reports_dir = ROOT / "reports"
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "ava.train", "--preset", preset, "--device", "cpu",
           "--run", run_dir, "--reports", reports_dir, "--packed", packed,
           "--max-steps", str(max_steps)]
    if resume and any(run_dir.glob("*.pt")):
        cmd.append("--resume")
    _run(cmd, timeout=3600)
    ckpts = sorted(run_dir.glob("*.pt"), key=lambda p: p.stat().st_mtime)
    if not ckpts:
        raise RuntimeError(f"ava.train exited 0 but produced no checkpoint under {run_dir}")
    return str(ckpts[-1])


@task(log_prints=True)
def monitor_metrics(ckpt_path: str):
    """Read REAL metrics.jsonl next to the checkpoint; no invented health/trend."""
    run_dir = Path(ckpt_path).parent
    metrics = run_dir / "metrics.jsonl"
    if not metrics.exists():
        return {"ckpt": ckpt_path, "metrics_file": None,
                "note": "no metrics.jsonl found — nothing to report (not fabricating)"}
    lines = [ln for ln in metrics.read_text().splitlines() if ln.strip()]
    last = json.loads(lines[-1]) if lines else {}
    return {"ckpt": ckpt_path, "metrics_file": str(metrics), "n_lines": len(lines), "last": last}


@flow(name="ava-train", log_prints=True)
def ava_train_flow(preset: str = "nano", tokens_total: int = 2_500_000_000, resume: bool = True):
    _log(f"Starting train_flow {preset} total={tokens_total}")
    ckpt = torchrun_train(preset, tokens_total, resume)
    health = monitor_metrics(ckpt)
    return {"ckpt": ckpt, "health": health}


# ---------- DISTILL FLOW ----------
@task(retries=2, log_prints=True)
def distill_mopd(base_ckpt: str):
    """The real distillation loop lives in on_policy_distill.py (reverse-KL KD
    with real tensors). It needs teacher checkpoints that do not exist yet at
    this scale, so this task refuses instead of returning a fabricated loss."""
    raise BlockedError(
        "MOPD distillation requires real domain-expert teacher checkpoints. Run the real "
        "implementation directly once teachers exist:\n"
        f"  python on_policy_distill.py --mode mopd --student-ckpt {base_ckpt} "
        "--teachers code:<ckpt>,math:<ckpt>,chat:<ckpt>\n"
        "(reverse_kl_loss there computes a real KL; nothing here to simulate)"
    )


@flow(name="ava-distill-mopd", log_prints=True)
def ava_distill_flow(base_ckpt: str = "runs/cpu_pilot/base/base_final.pt"):
    _log(f"Starting MOPD distill base={base_ckpt}")
    return distill_mopd(base_ckpt)


# ---------- EVAL FLOW ----------
@task(retries=2, log_prints=True)
def run_branch_eval(ckpt_path: str = None):
    """REAL harness: python -m evals.run_harness → reports/branch_eval_results_real.json."""
    cmd = [sys.executable, "-m", "evals.run_harness"]
    if ckpt_path:
        cmd += ["--base-ckpt", ckpt_path]
    _run(cmd, timeout=3600)
    result_path = ROOT / "reports" / "branch_eval_results_real.json"
    if not result_path.exists():
        raise RuntimeError(f"evals.run_harness exited 0 but {result_path} is missing")
    return json.loads(result_path.read_text())


@task(retries=3, retry_delay_seconds=30, log_prints=True)
def run_frontier_eval_judge_ollama(domain: str = "all"):
    """REAL run of eval_frontier_rubric.py. The avg is computed from the actual
    per-task results the script wrote; judge label reflects what actually scored
    (mock fallback when no Ollama/keys — labeled as such, no bonus)."""
    _run([sys.executable, ROOT / "eval_frontier_rubric.py", "--domain", domain,
          "--judge", "ollama"], timeout=1800)
    out = ROOT / "frontier_eval_results.json"
    if not out.exists():
        raise RuntimeError("eval_frontier_rubric.py exited 0 but frontier_eval_results.json missing")
    data = json.loads(out.read_text())
    results = data.get("results", [])
    avg = round(sum(r.get("overall", 0.0) for r in results) / len(results), 4) if results else None
    return {"domain": domain, "judge": data.get("judge"), "avg": avg, "n_tasks": len(results)}


@task(log_prints=True)
def render_html_log(branch_results, frontier_results):
    """Render an HTML log strictly from the real results passed in."""
    LOG_HTML_DIR.mkdir(parents=True, exist_ok=True)
    html_path = LOG_HTML_DIR / "latest-log.html"
    html_path.write_text(
        "<html><body><h1>Ava Experiment Log — Prefect</h1>"
        f"<pre>Branch (evals.run_harness): {json.dumps(branch_results, indent=1)[:4000]}</pre>"
        f"<pre>Frontier: {json.dumps(frontier_results, indent=1)[:4000]}</pre>"
        f"<p>Ollama: {OLLAMA_HOST} model {OLLAMA_MODEL}</p>"
        "<footer>Solo personal project, no connection to employer, built with public/free-tier only</footer>"
        "</body></html>"
    )
    return str(html_path)


@flow(name="ava-eval", log_prints=True)
def ava_eval_flow(ckpt_path: str = None):
    _log(f"Starting eval flow ckpt={ckpt_path}")
    branch = run_branch_eval(ckpt_path)
    frontier = run_frontier_eval_judge_ollama("all")
    log_path = render_html_log(branch, frontier)
    return {"branch": branch, "frontier": frontier, "html": log_path}


# ---------- FULL PIPELINE ----------
@flow(name="ava-full-pipeline", log_prints=True)
def ava_full_pipeline(preset: str = "nano", tokens_total: int = 2_500_000_000):
    _log(f"=== Ava Full Pipeline preset={preset} ===")
    data_out = ava_data_gen_flow(preset)
    train_out = ava_train_flow(preset, tokens_total)
    eval_out = ava_eval_flow(train_out["ckpt"])
    return {"data": data_out, "train": train_out, "eval": eval_out}


# ---------- DUMB MODELS FLOWS (external sports APIs — not wired) ----------
@task(retries=5, retry_delay_seconds=60, log_prints=True)
def ingest_league(source: str, league: str = "nfl"):
    raise BlockedError(
        f"ingest_league({source}, {league}): no real fetcher wired for nflverse/Sleeper/ESPN "
        "APIs in this checkout — refusing to return invented record counts"
    )


@flow(name="daily-vector", log_prints=True)
def daily_vector_flow(league: str = "nfl"):
    _log(f"=== Daily Vector Flow league={league} ===")
    raise BlockedError(
        "daily_vector_flow: ingestion/z-scores/embeddings/Vercel deploy are not implemented "
        "against real data sources in this repo; nothing honest to run"
    )


# ---------- CLI ----------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ava AGI Factory Prefect flows (real subprocess tasks)")
    parser.add_argument("--run", choices=["data", "train", "distill", "eval", "all", "vector"], default="all")
    parser.add_argument("--preset", default="nano", choices=["nano", "mini", "base1b"])
    parser.add_argument("--tokens", type=int, default=2_500_000_000)
    parser.add_argument("--league", default="nfl")
    parser.add_argument("--ckpt", default=None)
    args = parser.parse_args()

    print(f"Prefect available: {PREFECT_AVAILABLE} | OLLAMA_HOST={OLLAMA_HOST} | preset={args.preset}")

    if args.run == "data":
        ava_data_gen_flow(args.preset)
    elif args.run == "train":
        ava_train_flow(args.preset, args.tokens)
    elif args.run == "distill":
        ava_distill_flow(args.ckpt or "runs/cpu_pilot/base/base_final.pt")
    elif args.run == "eval":
        ava_eval_flow(args.ckpt)
    elif args.run == "vector":
        daily_vector_flow(args.league)
    elif args.run == "all":
        ava_full_pipeline(args.preset, args.tokens)
