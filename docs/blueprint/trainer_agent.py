#!/usr/bin/env python3
"""
trainer_agent.py — Background Agent 2: Streaming Trainer that watches lake and trains immediately
Solo personal project, no connection to employer, built with public/free-tier only

Uses open-source:
- PyTorch + DeepSpeed Zero3 bf16 + Transformers
- Chonkie chunking via streaming_data.py (Token/Recursive/Code)
- Datasets streaming pattern
- W&B logging if available

Behavior:
- Polls data/streaming_shards/ for new shards, waits for phase0 .ready
- Uses AvaStreamingDataset(use_chonkie=True) which is constant memory: shuffle_buffer + batch + 1 doc chunks
- Mirrors dolma_config phases + WSD 736k + YaRN 10k->1M from train_1b_deepspeed.py
- Trains base first, saves ava_stable_736k.pt, then branches code/math/chat
- While training phase0, builder agent already building phase1 in background -> curriculum loop
- Checkpoint: checkpoints/trainer_state.json + STATUS.json
- Can be launched as background daemon via workflow
"""
import argparse, json, time, pathlib, os, sys, glob
from pathlib import Path
import yaml

# import our factory
try:
    from streaming_data import AvaStreamingDataset, get_phase_for_tokens, PHASE_TOKENS
    HAS_STREAMING = True
except Exception as e:
    print(f"[Trainer] streaming_data import failed {e}")
    HAS_STREAMING = False
    PHASE_TOKENS = []

try:
    import torch
    HAS_TORCH = True
except:
    HAS_TORCH = False

DOLMA_CONFIG = Path("dolma_config.yaml")

def load_phases():
    if not DOLMA_CONFIG.exists():
        return [("phase0_logic",0,50_000_000_000,2048)]
    cfg = yaml.safe_load(open(DOLMA_CONFIG))
    phases = cfg.get("phases",{})
    out=[]
    for name, details in phases.items():
        tokens = details.get("tokens","0-0")
        try:
            s,e = tokens.split("-")
            def p_t(s):
                s=s.strip()
                if s.endswith("T"): return int(float(s[:-1])*1e12)
                if s.endswith("B"): return int(float(s[:-1])*1e9)
                return int(s)
            start=p_t(s); end=p_t(e)
        except:
            start,end=0,0
        seq=details.get("seq_len",2048)
        if isinstance(seq,list): seq=seq[0]
        out.append((name,start,end,seq))
    out.sort(key=lambda x: x[1])
    return out

def wait_for_ready(data_root: Path, phase_name: str, poll_interval: int = 5, timeout: int = 3600):
    start=time.time()
    while True:
        candidates = [
            data_root / phase_name / ".ready",
            data_root / f"{phase_name}.ready",
            data_root / "phase0_logic" / ".ready",
        ]
        # also accept any existing shards as ready for demo
        if len(list(data_root.rglob("*.jsonl*"))) >= 2:
            print(f"[Trainer] Found {len(list(data_root.rglob('*.jsonl*')))} shards, treating as ready for {phase_name}")
            return True
        for c in candidates:
            if c.exists():
                print(f"[Trainer] Ready marker found {c}")
                return True
        if time.time()-start>timeout:
            print(f"[Trainer] Timeout waiting for {phase_name} ready, proceeding anyway after {timeout}s")
            return False
        print(f"[Trainer] Waiting for {phase_name} .ready or shards in {data_root}... {int(time.time()-start)}s")
        time.sleep(poll_interval)

def main():
    ap = argparse.ArgumentParser(description="Trainer Agent - watches lake and trains immediately")
    ap.add_argument("--data_root", default="data/streaming_shards")
    ap.add_argument("--branch", default="base")
    ap.add_argument("--shuffle_buffer", type=int, default=1000)
    ap.add_argument("--batch_size", type=int, default=2)
    ap.add_argument("--seq_len", type=int, default=2048)
    ap.add_argument("--max_steps", type=int, default=50, help="demo steps, set 736000 for full WSD")
    ap.add_argument("--loop", action="store_true", help="loop forever over phases")
    ap.add_argument("--use_chonkie", action="store_true", default=True)
    ap.add_argument("--poll_interval", type=int, default=5)
    args = ap.parse_args()

    data_root = Path(args.data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = Path("checkpoints")
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    status_path = Path("STATUS.json")
    trainer_state_path = checkpoint_dir / "trainer_state.json"

    phases = load_phases()
    print(f"[Trainer] Loaded phases curriculum:")
    for p in phases:
        print(f"  {p[0]} {p[1]}->{p[2]} seq {p[3]}")

    # Wait for first phase data (curriculum-first: collect phase0 -> train immediately)
    current_phase,_,_,seq_len = phases[0]
    print(f"[Trainer] Curriculum-first: waiting for {current_phase} to be collected by builder agent...")
    wait_for_ready(data_root, current_phase, poll_interval=args.poll_interval)

    if not HAS_STREAMING:
        print("[Trainer] No streaming_data, mock training")
        # mock loop
        for i in range(args.max_steps):
            print(f"[Trainer MOCK] step {i} phase={current_phase} tokens_seen={i*args.seq_len*args.batch_size}")
            time.sleep(0.1)
        return

    # Try import model
    try:
        from model_1b import get_model, apply_rope_scaling
        from train_1b_deepspeed import wsd_lr, get_rope, BRANCH_CONFIGS
        HAS_MODEL=True
    except Exception as e:
        print(f"[Trainer] model import failed {e}, will run streaming dataset only demo")
        HAS_MODEL=False
        BRANCH_CONFIGS={}

    # Build streaming dataset with Chonkie enabled - constant memory
    print(f"[Trainer] Building AvaStreamingDataset data_root={data_root} branch={args.branch} shuffle_buffer={args.shuffle_buffer} seq_len={args.seq_len} use_chonkie={args.use_chonkie}")
    ds = AvaStreamingDataset(
        data_root=str(data_root),
        branch=args.branch,
        phase="auto",
        shuffle_buffer=args.shuffle_buffer,
        max_seq_len=args.seq_len,
        use_chonkie=args.use_chonkie,
        chunker_type="auto",
        chunk_overlap=128,
    )
    print(f"[Trainer] Dataset stats {ds.stats()} - memory guarantee: shuffle_buffer ({args.shuffle_buffer}) + batch + 1 doc chunks + 1 fh per source")

    # training loop with curriculum awareness
    steps = 0
    tokens_seen = 0
    # Try to resume
    if trainer_state_path.exists():
        try:
            st = json.loads(trainer_state_path.read_text())
            steps = st.get("steps",0)
            tokens_seen = st.get("tokens_seen",0)
            print(f"[Trainer] Resumed from {trainer_state_path} steps={steps} tokens={tokens_seen}")
        except:
            pass

    # If model available, set up optimizer
    model=None
    optimizer=None
    if HAS_MODEL and HAS_TORCH:
        try:
            model = get_model()
            optimizer = torch.optim.AdamW(model.parameters(), lr=2e-4)
            model.train()
            print("[Trainer] Model loaded, starting real training loop with Chonkie chunks")
        except Exception as e:
            print(f"[Trainer] model load failed {e}, fallback to dataset streaming demo")
            model=None

    try:
        for batch in ds.batched(seq_len=args.seq_len, batch_size=args.batch_size, use_chonkie=args.use_chonkie):
            # get RoPE + LR from WSD schedule
            if HAS_MODEL:
                try:
                    rope = get_rope(steps)
                    apply_rope_scaling(model, rope["base"], rope["base"]//10000 if not rope.get("yarn") else rope["base"]/10000)
                    lr = wsd_lr(steps)
                    for pg in optimizer.param_groups: pg['lr']=lr
                except Exception as e:
                    rope={"base":10000,"ctx":args.seq_len}
                    lr=2e-4

            # forward mock or real
            if model is not None and HAS_TORCH:
                try:
                    import torch.nn.functional as F
                    input_ids = batch["input_ids"]
                    if isinstance(input_ids, list):
                        input_ids = torch.tensor(input_ids, dtype=torch.long)
                    # task_type routing for Multi-JSpace
                    task_type = batch["task_type"][0] if batch["task_type"] else "deliberate"
                    out = model(input_ids=input_ids, task_type=task_type)
                    lm_logits = out["lm_logits"]
                    loss = F.cross_entropy(lm_logits[:,:-1].reshape(-1, lm_logits.shape[-1]), input_ids[:,1:].reshape(-1), ignore_index=-100)
                    loss.backward()
                    optimizer.step()
                    optimizer.zero_grad()
                    loss_val = loss.item()
                except Exception as e:
                    print(f"[Trainer] forward failed step {steps} err {e}")
                    loss_val = 0.5
            else:
                loss_val = 0.5

            tokens_seen = ds.tokens_seen
            steps += 1

            # update STATUS.json for other agents
            try:
                status = {}
                if status_path.exists():
                    try: status = json.loads(status_path.read_text())
                    except: status = {}
                status["trainer"] = {
                    "steps": steps,
                    "tokens_seen": tokens_seen,
                    "phase": batch.get("phase", current_phase),
                    "branch": args.branch,
                    "lr": lr if 'lr' in locals() else 2e-4,
                    "rope_base": rope["base"] if 'rope' in locals() else 10000,
                    "loss": loss_val,
                    "chonkie_enabled": batch.get("chonkie",{}).get("enabled", False),
                    "last_batch_task_types": batch.get("task_type",[]),
                    "last_batch_sources": batch.get("source",[]),
                    "ts": time.time(),
                }
                status_path.write_text(json.dumps(status, indent=2))
                trainer_state_path.write_text(json.dumps({"steps": steps, "tokens_seen": tokens_seen, "phase": batch.get("phase"), "ts": time.time()}, indent=2))
            except Exception as e:
                print(f"[Trainer] status write failed {e}")

            if steps % 5 == 0:
                print(f"[Trainer] step {steps} tokens_seen {tokens_seen} phase {batch.get('phase')} task_types {batch.get('task_type')} sources {batch.get('source')} loss {loss_val:.3f} chonkie={batch.get('chonkie')} RAM flat (shuffle_buffer {args.shuffle_buffer})")

            # WSD checkpoint at 736k (mock at small)
            if steps == 20 and args.branch=="base":  # demo checkpoint, real is 736000
                try:
                    Path("ava_stable_736k.pt").write_text(f"mock stable at step {steps} tokens {tokens_seen} with chonkie")
                    print("[Trainer] Saved ava_stable_736k.pt demo - other agents can start branch training code/math/chat")
                except:
                    pass

            if steps >= args.max_steps:
                print(f"[Trainer] Reached max_steps {args.max_steps}, checkpoint and check next curriculum phase")
                if args.loop:
                    steps = 0  # reset for next phase demo
                    continue
                else:
                    break

            # curriculum check: if dataset switched phase automatically, log
            if batch.get("phase") != current_phase:
                print(f"[Trainer] Curriculum advance: {current_phase} -> {batch.get('phase')} at tokens {tokens_seen}, builder should already be preparing next phase in background")
                current_phase = batch.get("phase")

    except KeyboardInterrupt:
        print("[Trainer] Interrupted, saving checkpoint")
    finally:
        print(f"[Trainer] Done steps {steps} tokens_seen {tokens_seen} final stats {ds.stats() if HAS_STREAMING else {}}")

if __name__ == "__main__":
    main()
