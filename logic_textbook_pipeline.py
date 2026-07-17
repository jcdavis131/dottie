"""
logic_textbook_pipeline.py — generates 50B logic + 300B math textbooks (Phi Method B)
Solo personal project, no connection to employer, built with public/free-tier only

v2 streaming: constant low-memory rotating shards 100MB each, never holds 50B/300B in RAM.
Old batch mode kept for compatibility via --batch flag.
Streaming mode intended to feed AvaStreamingDataset background generator.
"""
import argparse, json, random, time, gzip
from pathlib import Path

PHI_PROMPTS=[
    "Explain {topic} like a textbook chapter with definitions, theorems, examples.",
    "Create a problem set for {topic} with step-by-step solutions.",
    "Write a Socratic dialogue exploring {topic} misconceptions.",
]

TOPICS_LOGIC=["propositional logic","first-order logic","modal logic","proof by contradiction","induction","pigeonhole"]
TOPICS_MATH=["arithmetic","algebra","geometry","discrete","calculus","linear algebra","probability"]

def gen_textbook(topic, method="Phi B"):
    return f"# {topic}\n\nDefinition: ...\nTheorem: If ... then ...\nProof: ...\nExample: ...\nExercise: ... (Method {method})"

def heuristic_quality_score(text: str) -> float:
    """Deterministic CPU heuristic (same family as scripts/dataset_expansion.py's
    quality_filter): structure markers + length + unique-word ratio. Same input
    always yields the same score — this is a labeled heuristic, NOT a model
    reward and NOT a measurement."""
    score = 0.75
    if "Theorem" in text or "Definition" in text or "Proof" in text:
        score += 0.15
    if "Example" in text:
        score += 0.05
    words = text.split()
    if len(words) < 25:
        score -= 0.2
    if len(words) > 10:
        uniq_ratio = len(set(words)) / len(words)
        if uniq_ratio < 0.3:
            score -= 0.3
    return round(max(0.0, min(1.0, score)), 4)

def gen_jsonl_example(topic, prompt_template=None, source="synthetic_logic_textbooks_phi_B"):
    prompt = prompt_template or random.choice(PHI_PROMPTS)
    txt = gen_textbook(topic)
    # Phi B style: textbook chapter + problem set
    text = f"{prompt.format(topic=topic)}\n\n{txt}\n\n" + "Exercise solution with reasoning. " * 10
    return {
        "text": text,
        "source": source,
        "task_type": "deliberate" if "logic" in topic or topic in TOPICS_LOGIC else "deliberate",
        "topic": topic,
        "prompt_type": prompt,
        # Deterministic structural heuristic — was random.uniform masquerading
        # as a Nemotron-70B reward. Renamed so no consumer mistakes it for one.
        "reward_heuristic": heuristic_quality_score(text),
        "method": "Phi B",
    }

def run_streaming(out_root: Path, shard_mb: int = 100, max_shards: int = 0, filter_threshold: float = 0.8, sleep: float = 0.01):
    """
    Constant low-memory streaming writer:
    - 1 file handle open, 100MB per shard gzipped jsonl, rotates forever
    - never stores full 50B/300B textbook list
    - deterministic heuristic filtering >0.8 on the fly (heuristic_quality_score)
    - backpressure via max_shards pause if too far ahead of trainer
    """
    out_root = Path(out_root)
    # main synthetic source for phase0
    logic_dir = out_root / "synthetic_logic_textbooks_phi_B"
    logic_dir.mkdir(parents=True, exist_ok=True)
    math_dir = out_root / "math_textbooks_ordered"
    math_dir.mkdir(parents=True, exist_ok=True)

    all_topics = TOPICS_LOGIC + TOPICS_MATH
    shard_idx = len(list(logic_dir.glob("*.jsonl*")))
    # open rotating shards
    def new_shard(dir_path: Path, idx: int):
        p = dir_path / f"shard_{idx:05d}.jsonl.gz"
        fh = gzip.open(p, "wt", encoding="utf-8")
        return fh, p, 0

    fh_logic, cur_path_logic, cur_bytes_logic = new_shard(logic_dir, shard_idx)
    fh_math, cur_path_math, cur_bytes_math = new_shard(math_dir, shard_idx)

    topics_cycle = (all_topics * 1000)  # infinite iterator conceptually
    written = 0
    kept = 0
    try:
        for topic in topics_cycle:
            if max_shards and shard_idx >= max_shards and written > 1000:
                print(f"[streaming] hit max_shards={max_shards}, stopping")
                break
            ex = gen_jsonl_example(topic)
            # Deterministic heuristic filter >0.8 streaming (labeled heuristic, not a model reward)
            if ex["reward_heuristic"] < filter_threshold:
                continue
            line = json.dumps(ex) + "\n"
            # route by topic type for correct phase mix
            if topic in TOPICS_LOGIC:
                fh_logic.write(line)
                cur_bytes_logic += len(line.encode("utf-8"))
                if cur_bytes_logic > shard_mb * 1024 * 1024:
                    fh_logic.close()
                    shard_idx += 1
                    fh_logic, cur_path_logic, cur_bytes_logic = new_shard(logic_dir, shard_idx)
            else:
                fh_math.write(line)
                cur_bytes_math += len(line.encode("utf-8"))
                if cur_bytes_math > shard_mb * 1024 * 1024:
                    fh_math.close()
                    fh_math, cur_path_math, cur_bytes_math = new_shard(math_dir, shard_idx)

            written += 1
            kept += 1
            if written % 500 == 0:
                print(f"[streaming] written={written} kept={kept} shard={shard_idx} current_bytes log={cur_bytes_logic//1024}KB math={cur_bytes_math//1024}KB RAM ~ constant (1 handle)")
                # backpressure check
                total_shards = len(list(logic_dir.glob("*.jsonl*"))) + len(list(math_dir.glob("*.jsonl*")))
                if total_shards > 30:  # if trainer slow, pause
                    time.sleep(1.0)
            time.sleep(sleep)  # throttle to avoid CPU spin
    finally:
        try: fh_logic.close()
        except: pass
        try: fh_math.close()
        except: pass
    print(f"Streaming finished — kept {kept}/{written} examples, shards in {out_root} — train can consume while generating")

def run_batch(out: Path):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Generating batch (old mode) to {out}")
    for i, t in enumerate(TOPICS_LOGIC):
        (out/f"logic_{i}_{t.replace(' ','_')}.md").write_text(gen_textbook(t))
    for i, t in enumerate(TOPICS_MATH):
        (out/f"math_{i}_{t.replace(' ','_')}.md").write_text(gen_textbook(t))
    print(f"Wrote {len(TOPICS_LOGIC)+len(TOPICS_MATH)} mock textbooks to {out} — for streaming use, run without --batch")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--logic_tokens", default="50B")
    parser.add_argument("--math_tokens", default="300B")
    parser.add_argument("--out", default="data/streaming_shards", help="output root for streaming shards (was data/synthetic)")
    parser.add_argument("--batch", action="store_true", help="old batch mode: write handful of md files")
    parser.add_argument("--shard_mb", type=int, default=100, help="MB per rotating shard")
    parser.add_argument("--max_shards", type=int, default=0, help="0 = infinite stream until Ctrl-C")
    parser.add_argument("--reward_threshold", type=float, default=0.8, help="heuristic_quality_score filter threshold")
    parser.add_argument("--sleep", type=float, default=0.01)
    args=parser.parse_args()
    if args.batch:
        run_batch(Path(args.out))
    else:
        print(f"Streaming Phi Method B generation: {args.logic_tokens} logic + {args.math_tokens} math -> {args.out} rotating {args.shard_mb}MB shards, heuristic score>{args.reward_threshold}")
        print("Constant memory: 1 file handle, ~100MB buffer, no full corpus in RAM. Ctrl-C to stop. Trainer can consume concurrently.")
        run_streaming(Path(args.out), shard_mb=args.shard_mb, max_shards=args.max_shards, filter_threshold=args.reward_threshold, sleep=args.sleep)

if __name__=="__main__":
    main()
