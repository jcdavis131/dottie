# Solo personal project, no connection to employer, built with public/free-tier only
"""
Dottie AGI Factory v6.4 + Dumb Models — Prefect Flows PoC
Free-tier self-hosted: pip install prefect, prefect server start --port 4200

Runnable:
  python prefect_flows.py --run data        # data gen only (mock if no GPU)
  python prefect_flows.py --run train --preset mini
  python prefect_flows.py --run eval
  python prefect_flows.py --run distill
  python prefect_flows.py --run all --preset nano
  python prefect_flows.py --run vector --league nfl

Deploy:
  prefect deployment build prefect_flows.py:dottie_data_gen_flow -n daily --cron "0 6 * * *" --apply
  prefect agent start -q default

Docker integration:
  Set PREFECT_API_URL=http://host.docker.internal:4200/api in docker-compose
  OLLAMA_HOST=http://host.docker.internal:11434 for free judging
"""
import argparse
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

# Try import prefect, fallback to no-op decorators if not installed so file still imports
try:
    from prefect import flow, task, get_run_logger
    from prefect.tasks import task_input_hash
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
YOUR_FILES = Path.home() / "workspace" / "your_files" / "dottie-agi" / "runs"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:32b")

# ---------- Helpers ----------
def _log(msg):
    try:
        logger = get_run_logger()
        logger.info(msg)
    except:
        print(msg)

# ---------- HF PUSH TASK (NEW — 2-loop) ----------
@task(retries=3, retry_delay_seconds=[30, 120, 300], log_prints=True)
def push_to_hf_task(manifest_path: str = "data/daily_expanded/manifest_*.jsonl", repo: str = "jcdavis131/dottie-textbook-v6", private: bool = True):
    """Push curated train/val/test to HF Hub for streaming Loop2 — Solo personal project, no work Drive"""
    _log(f"[hf] push_to_hf repo={repo} manifest={manifest_path}")
    hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
    if not hf_token:
        _log("[hf] HF_TOKEN not set — saving manifest to data/for_upload/hf_ready_*.json for Alienware push (expected in Hatch VM)")
        # call hf_uploader dry-run via subprocess or just log
        import subprocess
        cmd = f"python3 {ROOT}/scripts/hf_uploader.py --repo {repo} --manifest '{manifest_path}' --dry-run"
        try:
            subprocess.run(cmd, shell=True, timeout=30)
        except Exception as e:
            _log(f"[hf] dry-run warning: {e}")
        return {"pushed": False, "reason": "no_token", "repo": repo}
    # real push
    import subprocess
    cmd = f"HF_TOKEN={hf_token} python3 {ROOT}/scripts/hf_uploader.py --repo {repo} --manifest '{manifest_path}' --private --push"
    _log(f"[hf] cmd: {cmd}")
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        _log(res.stdout[-2000:])
        if res.returncode == 0:
            return {"pushed": True, "repo": repo}
        else:
            _log(f"[hf] push failed rc={res.returncode} {res.stderr[-2000:]}")
            return {"pushed": False, "rc": res.returncode}
    except Exception as e:
        _log(f"[hf] exception {e}")
        return {"pushed": False, "error": str(e)}

# ---------- DATA GEN FLOW ----------
@task(retries=3, retry_delay_seconds=[10, 60, 300], log_prints=True)
def generate_phase(phase: str, tokens: int = 50_000_000):
    """Wraps logic_textbook_pipeline.py --phase p0_logic etc"""
    _log(f"[data] generate_phase {phase} tokens={tokens}")
    out = DATA_DIR / "mini" / "raw" / phase
    out.mkdir(parents=True, exist_ok=True)
    # Real run if script exists, else mock
    script = ROOT / "logic_textbook_pipeline.py"
    if script.exists():
        # mock small run to keep PoC fast; real uses subprocess
        # We avoid heavy work in PoC — write placeholder JSONL
        (out / f"{phase}.jsonl").write_text(json.dumps({"phase": phase, "tokens": tokens, "ts": datetime.utcnow().isoformat()}) + "\n")
        time.sleep(0.5)
    else:
        (out / f"{phase}.jsonl").write_text('{"mock":true}\n')
    return str(out)

@task(retries=2, log_prints=True)
def build_tokenizer(vocab_size: int = 8192):
    _log(f"[data] build_tokenizer vocab={vocab_size}")
    tok_path = DATA_DIR / "mini" / "tokenizer" / "dottie_bpe_32k.json"
    tok_path.parent.mkdir(parents=True, exist_ok=True)
    # Real: from streaming_data import build_tokenizer
    # PoC: touch
    if not tok_path.exists():
        tok_path.write_text(json.dumps({"vocab_size": vocab_size, "mock": True}))
    return str(tok_path)

@task(retries=2, log_prints=True)
def pack_shards(phase_dirs, seq_len: int = 1024):
    _log(f"[data] pack_shards seq={seq_len} from {len(phase_dirs)} dirs")
    packed = DATA_DIR / "mini" / "packed"
    packed.mkdir(parents=True, exist_ok=True)
    # PoC: write manifest
    (packed / "manifest.json").write_text(json.dumps({"phases": phase_dirs, "seq_len": seq_len}))
    return str(packed)

@flow(name="dottie-data-gen", log_prints=True)
def dottie_data_gen_flow(preset: str = "mini", tokens: int = 50_000_000):
    _log(f"Starting data_gen_flow preset={preset} tokens={tokens}")
    phases = ["p0_logic", "p1_math", "p2_foundation", "p3_code"] if preset != "nano" else ["p0_logic", "p1_math"]
    # Parallel via .map() if prefect available
    if PREFECT_AVAILABLE:
        raw_dirs = generate_phase.map(phases, tokens)
    else:
        raw_dirs = [generate_phase(p, tokens) for p in phases]
    tok = build_tokenizer()
    packed = pack_shards(raw_dirs, seq_len=1024 if preset=="mini" else 256)
    # NEW: push to HF for 2-loop arch (Loop1 -> Loop2 streaming)
    hf_res = push_to_hf_task(manifest_path="data/daily_expanded/manifest_*.jsonl")
    return {"tokenizer": tok, "packed": packed, "raw": raw_dirs, "hf": hf_res}

# ---------- TRAIN FLOW ----------
@task(retries=2, retry_delay_seconds=[30,120], log_prints=True)
def torchrun_train(preset: str, tokens_total: int, resume: bool = True):
    _log(f"[train] torchrun preset={preset} tokens={tokens_total} resume={resume}")
    ckpt_dir = ROOT / "checkpoints" / preset
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    # Real command would be:
    # torchrun --nproc_per_node=1 train_1b_deepspeed.py --preset base1b --deepspeed deepspeed_zero3_bf16.json --tokens_total 2B
    # PoC: simulate metrics.jsonl write
    metrics_path = ckpt_dir / "metrics.jsonl"
    for i in range(3):
        line = {"step": i*100, "lm_loss": 3.0/(i+1), "tokens": tokens_total//3 * (i+1), "ts": datetime.utcnow().isoformat()}
        with open(metrics_path, "a") as f:
            f.write(json.dumps(line)+"\n")
        time.sleep(0.2)
    # fake stable ckpt
    stable = ckpt_dir / f"dottie_stable_{preset}.pt"
    stable.write_text(f"mock ckpt {preset} {tokens_total}")
    return str(stable)

@task(log_prints=True)
def monitor_metrics(ckpt_path: str):
    _log(f"[train] monitor {ckpt_path}")
    return {"ckpt": ckpt_path, "health": "OK", "loss_trend": "down"}

@flow(name="dottie-train", log_prints=True)
def dottie_train_flow(preset: str = "mini", tokens_total: int = 2_500_000_000, resume: bool = True):
    _log(f"Starting train_flow {preset} total={tokens_total}")
    ckpt = torchrun_train(preset, tokens_total, resume)
    health = monitor_metrics(ckpt)
    return {"ckpt": ckpt, "health": health}

# ---------- DISTILL FLOW — MOPD from distillation-2026 article ----------
@task(retries=2, log_prints=True)
def generate_teacher_rollouts(expert_name: str):
    _log(f"[distill] teacher rollout {expert_name} (S1/S2/Critic/Planner)")
    # In real: load expert ckpt, generate rollouts, capture logits
    return {"expert": expert_name, "logits_path": f"/tmp/{expert_name}_logits.pt", "specialization": expert_name}

@task(log_prints=True)
def student_rollout(ckpt_path: str):
    _log(f"[distill] student rollout ckpt={ckpt_path}")
    return {"student_ckpt": ckpt_path, "rollout": "student_gen.jsonl"}

@task(log_prints=True)
def reverse_kl_loss(student_rollout, teacher_rollouts):
    _log(f"[distill] reverse KL student vs {len(teacher_rollouts)} teachers — MOPD")
    # Real: from trl import ... loss = reverse_kl(student_logits, teacher_logits)
    # Qwen3 reports 1/10 GPU hours vs RL
    return {"loss": 0.42, "method": "MOPD reverse KL", "teachers": len(teacher_rollouts)}

@flow(name="dottie-distill-mopd", log_prints=True)
def dottie_distill_flow(base_ckpt: str = "checkpoints/mini/dottie_stable_mini.pt"):
    """
    Implements Multi-Teacher On-Policy Distillation per https://huggingface.co/blog/sergiopaniego/distillation-2026
    - Separate RL experts per domain (code/math/chat)
    - Student generates own rollouts, teachers grade every token
    - Self-distill privileged hint pattern for Planner
    """
    _log(f"Starting MOPD distill base={base_ckpt}")
    expert_names = ["S1_Fast_code", "S2_Slow_math", "Critic_safety", "Planner_temporal"]
    if PREFECT_AVAILABLE:
        teacher_rollouts = generate_teacher_rollouts.map(expert_names)
    else:
        teacher_rollouts = [generate_teacher_rollouts(n) for n in expert_names]
    s_rollout = student_rollout(base_ckpt)
    loss = reverse_kl_loss(s_rollout, teacher_rollouts)
    _log(f"[distill] merged loss {loss} — ready for continual learning via earlier-teacher trick")
    return loss

# ---------- EVAL FLOW ----------
@task(retries=2, log_prints=True)
def run_branch_eval(ckpt_path: str = None):
    _log(f"[eval] branch_harness ckpt={ckpt_path}")
    # Real: python eval_branch_harness.py --branch all --mode mock
    result_path = ROOT / "branch_eval_results.json"
    if result_path.exists():
        data = json.loads(result_path.read_text())
    else:
        data = {"mock": True, "passes": 5, "cap_pres": 1.0}
    return data

@task(retries=3, retry_delay_seconds=30, log_prints=True)
def run_frontier_eval_judge_ollama(domain: str = "all"):
    _log(f"[eval] frontier rubric domain={domain} judge={OLLAMA_MODEL} host={OLLAMA_HOST}")
    # Real: OLLAMA_HOST=... python eval_frontier_rubric.py --domain all --judge ollama
    # Check Ollama reachable
    try:
        import urllib.request
        urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2)
        reachable = True
    except:
        reachable = False
    result = {"domain": domain, "judge": OLLAMA_MODEL, "reachable": reachable, "avg": 0.589}
    return result

@task(log_prints=True)
def render_html_log(branch_results, frontier_results):
    _log("[eval] render latest-log.html")
    out = YOUR_FILES
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / "latest-log.html"
    # Real builder would parse metrics.jsonl + evals + git HEAD f508569
    html_path.write_text(f"""<html><body><h1>Dottie Experiment Log — Prefect</h1>
<p>Branch: {branch_results}</p><p>Frontier: {frontier_results}</p>
<p>Ollama: {OLLAMA_HOST} model {OLLAMA_MODEL}</p>
<footer>Solo personal project, no connection to employer, built with public/free-tier only</footer></body></html>""")
    return str(html_path)

@flow(name="dottie-eval", log_prints=True)
def dottie_eval_flow(ckpt_path: str = None):
    _log(f"Starting eval flow ckpt={ckpt_path}")
    branch = run_branch_eval(ckpt_path)
    if PREFECT_AVAILABLE:
        # Parallel domains
        frontier_list = run_frontier_eval_judge_ollama.map(["finance","bio","code","law","macro"])
    else:
        frontier_list = [run_frontier_eval_judge_ollama(d) for d in ["finance","bio","code","law","macro"]]
    log_path = render_html_log(branch, frontier_list)
    return {"branch": branch, "frontier": frontier_list, "html": log_path}

# ---------- FULL PIPELINE ----------
@flow(name="dottie-full-pipeline", log_prints=True)
def dottie_full_pipeline(preset: str = "mini", tokens_total: int = 2_500_000_000):
    _log(f"=== Dottie Full Pipeline preset={preset} ===")
    data_out = dottie_data_gen_flow(preset)
    train_out = dottie_train_flow(preset, tokens_total)
    distill_out = dottie_distill_flow(train_out["ckpt"])
    eval_out = dottie_eval_flow(train_out["ckpt"])
    return {"data": data_out, "train": train_out, "distill": distill_out, "eval": eval_out}

# ---------- DUMB MODELS FLOWS ----------
@task(retries=5, retry_delay_seconds=60, log_prints=True)
def ingest_league(source: str, league: str = "nfl"):
    _log(f"[vector] ingest {source} league={league}")
    # Real: fetch nflverse, Sleeper, ESPN APIs
    return {"source": source, "league": league, "records": 150}

@task(retries=2, log_prints=True)
def compute_zscores(raw_data):
    _log(f"[vector] compute zscores per-100 from {len(raw_data)} sources")
    return {"zscores": True, "input": raw_data}

@task(log_prints=True)
def build_embeddings(zscores):
    _log("[vector] build embeddings PCA/UMAP")
    # Real: sklearn PCA, embeddings -> public/data/*.json
    out = Path("public/data/embeddings.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mock": True, "zscores": str(zscores)}))
    return str(out)

@task(retries=3, log_prints=True)
def vercel_deploy(embeddings_path: str):
    _log(f"[vector] vercel deploy hook {embeddings_path}")
    # Real: POST to VERCEL_DEPLOY_HOOK_URL
    return {"deployed": True, "url": "https://gridiron.dumbmodel.com"}

@flow(name="daily-vector", log_prints=True)
def daily_vector_flow(league: str = "nfl"):
    _log(f"=== Daily Vector Flow league={league} ===")
    sources = ["nflverse", "pff", "sleeper", "espn"]
    if PREFECT_AVAILABLE:
        raw = ingest_league.map(sources, league)
    else:
        raw = [ingest_league(s, league) for s in sources]
    zs = compute_zscores(raw)
    emb = build_embeddings(zs)
    dep = vercel_deploy(emb)
    return {"league": league, "deploy": dep}

# ---------- CLI ----------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dottie AGI Factory Prefect PoC")
    parser.add_argument("--run", choices=["data","train","distill","eval","all","vector"], default="all")
    parser.add_argument("--preset", default="mini", choices=["nano","mini","base1b"])
    parser.add_argument("--tokens", type=int, default=2_500_000_000)
    parser.add_argument("--league", default="nfl")
    parser.add_argument("--ckpt", default=None)
    args = parser.parse_args()

    print(f"Prefect available: {PREFECT_AVAILABLE} | OLLAMA_HOST={OLLAMA_HOST} | preset={args.preset}")

    if args.run == "data":
        dottie_data_gen_flow(args.preset)
    elif args.run == "train":
        dottie_train_flow(args.preset, args.tokens)
    elif args.run == "distill":
        dottie_distill_flow(args.ckpt or f"checkpoints/{args.preset}/dottie_stable_{args.preset}.pt")
    elif args.run == "eval":
        dottie_eval_flow(args.ckpt)
    elif args.run == "vector":
        daily_vector_flow(args.league)
    elif args.run == "all":
        dottie_full_pipeline(args.preset, args.tokens)
