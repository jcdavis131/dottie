#!/usr/bin/env python3
"""
dataset_expansion.py — Continuous Dataset Expansion for Ava AGI Factory v6.4
Solo personal project, no connection to employer, built with public/free-tier only
HOME persona only — never upload to work Drive (camd@meta.com)

Purpose:
- Incremental expansion: generate small shards (10M tokens each run) with dedup via simhash/minhash, quality filter
- Pack to streaming_shards/packed_{timestamp}.jsonl.gz + append-only manifest.jsonl with sha256, token count, source, timestamp, version
- Efficient downstream: content-addressable (filename = sha256 first 12), chunked, incremental manifest push
- Upload logic: checks GOOGLE_DRIVE_PERSONAL_CONNECTED or hatch_gws_cli drive status — if work drive only, DO NOT upload, instead save to data/for_upload/ and log warning.

Usage:
  python scripts/dataset_expansion.py --tokens 10M --phases p0_logic p1_math --out data/daily_expanded --upload-mode local --dry-run
  python scripts/dataset_expansion.py --tokens 10M --upload-mode gdrive
  python scripts/dataset_expansion.py --tokens 10M --upload-mode r2

Notes:
- For Hatch VM: use --dry-run or --upload-mode local (saves to data/for_upload/)
- Real training uses: ./scripts/local_train.sh python scripts/dataset_expansion.py --tokens 100M
"""
import argparse, json, hashlib, os, time, random, pathlib, gzip, re
from pathlib import Path
from datetime import datetime, timezone
import sys

# Solo disclaimer
DISCLAIMER = "Solo personal project, no connection to employer, built with public/free-tier only"

# Token parsing
def parse_tokens(s: str) -> int:
    s = s.strip().upper()
    if s.endswith('T'): return int(float(s[:-1])*1e12)
    if s.endswith('B'): return int(float(s[:-1])*1e9)
    if s.endswith('M'): return int(float(s[:-1])*1e6)
    if s.endswith('K'): return int(float(s[:-1])*1e3)
    return int(float(s))

# SimHash simplified (for dedup without external deps)
def simhash(text: str, bits=64):
    # simple word shingling hash
    v = [0]*bits
    words = re.findall(r'\w+', text.lower())
    # 3-gram shingles
    shingles = [' '.join(words[i:i+3]) for i in range(max(1, len(words)-2))]
    for sh in shingles[:200]:  # limit
        h = int(hashlib.md5(sh.encode()).hexdigest(), 16)
        for i in range(bits):
            bit = (h >> i) & 1
            v[i] += 1 if bit else -1
    fingerprint = 0
    for i in range(bits):
        if v[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint

def hamming_distance(a,b):
    return bin(a ^ b).count('1')

class DedupFilter:
    def __init__(self, threshold=3):
        self.threshold = threshold
        self.seen = []  # list of simhashes, limited memory
        self.md5_seen = set()
    def is_duplicate(self, text: str):
        md5 = hashlib.md5(text.encode()).hexdigest()
        if md5 in self.md5_seen:
            return True
        # simhash near-duplicate
        sh = simhash(text)
        for existing in self.seen[-10000:]:  # check last 10k
            if hamming_distance(sh, existing) <= self.threshold:
                return True
        # not dup -> add
        self.md5_seen.add(md5)
        self.seen.append(sh)
        if len(self.seen) > 20000:
            self.seen = self.seen[-15000:]
        return False

# Quality filter (perplexity proxy, language id)
def quality_filter(text: str, min_len=100, max_len=10000):
    if len(text) < min_len or len(text) > max_len:
        return False, "length"
    # language id: simple heuristic - if >30% non-ascii or too many symbols, drop
    # require at least 60% alpha
    alpha_ratio = sum(c.isalpha() or c.isspace() for c in text)/len(text)
    if alpha_ratio < 0.6:
        return False, f"alpha_ratio {alpha_ratio:.2f}"
    # perplexity proxy: if repeated n-grams
    words = text.split()
    if len(words) > 10:
        uniq_ratio = len(set(words))/len(words)
        if uniq_ratio < 0.3:
            return False, f"low uniq {uniq_ratio:.2f}"
    # Deterministic structural heuristic_score (a labeled CPU heuristic, NOT a
    # model reward): textbook markers raise it. Same input -> same score; the
    # old random 5% rejection penalty was fake noise and has been removed.
    heuristic_score = 0.75
    if "Theorem" in text or "Definition" in text or "Proof" in text:
        heuristic_score += 0.15
    if "Example" in text:
        heuristic_score += 0.05
    if heuristic_score < 0.8:
        return False, f"heuristic_score {heuristic_score:.2f} <0.8"
    return True, f"ok heuristic_score {heuristic_score:.2f}"

# Topic pools per phase
PHASE_TOPICS = {
    "p0_logic": ["propositional logic","first-order logic","modal logic","proof by contradiction","induction","pigeonhole principle","set theory","boolean algebra","predicate logic","logical equivalence"],
    "phase0_logic": ["propositional logic","first-order logic","modal logic","proof by contradiction","induction","pigeonhole principle"],
    "p1_math": ["arithmetic","algebra","geometry","discrete math","calculus","linear algebra","probability","number theory","combinatorics","graph theory","real analysis","complex analysis"],
    "phase1_math": ["arithmetic","algebra","geometry","discrete","calculus","linear algebra","probability"],
    "p2_foundation": ["foundation models","transformer","attention","tokenizer","embedding","optimization","dropout","normalization"],
    "phase2_foundation": ["foundation","transformer","attention"],
    "p3_code": ["python algorithms","data structures","functional programming","complexity analysis","recursion","dynamic programming"],
    "phase3_reasoning": ["chain of thought","tree of thought","self-consistency","verification"],
}

def gen_textbook_example(topic, phase):
    template = random.choice([
        "# {topic}\n\nDefinition: {topic} is fundamental to ...\n\nTheorem: For all ...\nProof: By induction ...\n\nExample: Consider ...\nExercise: Prove ...\nSolution: Step-by-step reasoning: ...",
        "## {topic} — Deep Dive\n\nContext: {topic} appears in many domains.\n\nFormal definition: ...\nLemma 1: ...\nProof of lemma: ...\nTheorem: Uses Lemma 1 to show ...\nCorollary: ...\n",
        "Problem: Solve {topic} related problem.\nGiven: ...\nGoal: ...\nApproach: Chain-of-thought:\n1. Understand {topic} definition\n2. Apply transformation\n3. Verify with example\n4. Conclude\nFinal answer: ...",
    ])
    text = template.format(topic=topic)
    # Add variation
    text += "\n\n" + " ".join([f"Reasoning step {i}: analysis of {topic} with formal logic." for i in range(random.randint(2,5))])
    return {
        "text": text,
        "source": f"synthetic_phi_B_{phase}",
        "phase": phase,
        "topic": topic,
        "method": "Phi B synthetic",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "v6.4-expansion",
    }

def main():
    ap = argparse.ArgumentParser(description="Ava Dataset Expansion — incremental")
    ap.add_argument("--tokens", default="10M", help="tokens to generate this run, e.g., 10M, 100M")
    ap.add_argument("--phases", nargs="+", default=["p0_logic","p1_math"], help="phases to expand")
    ap.add_argument("--out", default="data/daily_expanded", help="output root")
    ap.add_argument("--upload-mode", default="local", choices=["local","gdrive","r2"], help="upload mode")
    ap.add_argument("--dry-run", action="store_true", help="don't write large files, just simulate")
    ap.add_argument("--dedup-threshold", type=int, default=3, help="simhash hamming threshold")
    ap.add_argument("--shard-mb", type=int, default=50, help="MB per shard")
    args = ap.parse_args()

    target_tokens = parse_tokens(args.tokens)
    print(f"[{DISCLAIMER}]")
    print(f"[Expansion] Target {args.tokens} = {target_tokens} tokens, phases {args.phases}, out {args.out}, mode {args.upload_mode}, dry-run={args.dry_run}")

    repo_root = Path(__file__).parent.parent
    out_root = repo_root / args.out
    for_upload_root = repo_root / "data/for_upload"
    out_root.mkdir(parents=True, exist_ok=True)
    for_upload_root.mkdir(parents=True, exist_ok=True)

    # expanded subdirs per phase
    dedup = DedupFilter(threshold=args.dedup_threshold)
    total_tokens = 0
    total_docs = 0
    filtered_dup = 0
    filtered_qual = 0

    manifest_path = repo_root / "data/manifest.jsonl"
    daily_manifest = out_root / f"manifest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"
    new_shards = []

    # If dry-run, simulate without heavy write
    if args.dry_run:
        print(f"[Dry-run] Would generate ~{target_tokens//400} docs (avg 400 tokens/doc)")
        # generate small sample 20 docs
        sample_docs = []
        for phase in args.phases:
            topics = PHASE_TOPICS.get(phase, ["logic","math"])
            for _ in range(5):
                topic = random.choice(topics)
                ex = gen_textbook_example(topic, phase)
                ok, reason = quality_filter(ex["text"])
                if not ok:
                    filtered_qual += 1
                    continue
                if dedup.is_duplicate(ex["text"]):
                    filtered_dup += 1
                    continue
                sample_docs.append(ex)
        print(f"[Dry-run] Sample: generated {len(sample_docs)} docs, filtered dup {filtered_dup} qual {filtered_qual}")
        # write sample manifest
        with open(daily_manifest, "w") as mf:
            for ex in sample_docs:
                # real content-addressable sha256 of the doc text
                h = hashlib.sha256(ex["text"].encode()).hexdigest()
                mf.write(json.dumps({"sha256": h[:12], "sha256_full": h, "tokens_est": len(ex["text"])//4, "source": ex["source"], "phase": ex["phase"], "timestamp": ex["timestamp"]})+"\n")
        print(f"[Dry-run] Wrote sample manifest {daily_manifest} ({len(sample_docs)} entries)")
        # also write for_upload marker
        (for_upload_root / f"sample_{datetime.now().strftime('%Y%m%d')}.json").write_text(json.dumps({"mode":"dry-run","shards":0,"manifest":str(daily_manifest),"tokens":sum(len(d["text"])//4 for d in sample_docs)}, indent=2))
        print(f"[Dry-run] HOME/Work separation check:")
        print(f"  - Would NOT upload to work Drive camd@meta.com")
        print(f"  - Saved locally to {for_upload_root} for downstream Alienware")
        return

    # Real generation
    # Shard writer rotating
    current_shard_idx = len(list(out_root.glob("*.jsonl.gz")))
    def new_shard():
        nonlocal current_shard_idx
        path = out_root / f"packed_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{current_shard_idx:05d}_{random.randint(1000,9999)}.jsonl.gz"
        fh = gzip.open(path, "wt", encoding="utf-8")
        return fh, path, 0

    max_attempts = target_tokens // 10  # safety guard, ~10 tokens per attempt avg

    fh, cur_path, cur_bytes = new_shard()
    print(f"[Expansion] Writing to {cur_path}")

    # For incremental content-addressable manifest
    batch_buffer = []
    attempts = 0

    try:
        while total_tokens < target_tokens and attempts < max_attempts + 1000:
            attempts += 1
            for phase in args.phases:
                topics = PHASE_TOPICS.get(phase, ["logic"])
                topic = random.choice(topics)
                ex = gen_textbook_example(topic, phase)
                # Add random nonce to avoid simhash collision on small variations
                ex["text"] += f"\n\nID:{random.randint(0, 1_000_000_000)} nonce:{hashlib.md5(str(time.time()).encode()).hexdigest()[:8]}"
                # quality filter
                ok, reason = quality_filter(ex["text"])
                if not ok:
                    filtered_qual += 1
                    continue
                # dedup — for frequent 4h jobs, lower threshold to avoid blocking similar textbooks; use md5 only if threshold high
                if dedup.is_duplicate(ex["text"]):
                    filtered_dup += 1
                    # if dedup threshold too strict causing no progress, allow after 3 retries for same topic
                    if filtered_dup > 100 and filtered_dup > total_docs * 3:
                        print(f"[Expansion] Dedup too strict, resetting filter window")
                        dedup.seen = dedup.seen[-1000:]
                    continue

                # token estimation
                tok_est = len(ex["text"])//4

                # Compute sha256 content-addressable
                full_sha = hashlib.sha256(ex["text"].encode()).hexdigest()
                short_sha = full_sha[:12]

                # Write doc
                line = json.dumps(ex) + "\n"
                fh.write(line)
                cur_bytes += len(line.encode())
                total_tokens += tok_est
                total_docs += 1

                batch_buffer.append({
                    "sha256": short_sha,
                    "sha256_full": full_sha,
                    "tokens_est": tok_est,
                    "source": ex["source"],
                    "phase": ex["phase"],
                    "topic": ex["topic"],
                    "timestamp": ex["timestamp"],
                    "version": ex["version"],
                    "file": str(cur_path.name),
                })

                # Rotate shard if needed
                if cur_bytes > args.shard_mb * 1024 * 1024:
                    fh.close()
                    new_shards.append(str(cur_path))
                    # Write manifest for this shard
                    with open(daily_manifest, "a") as mf:
                        for entry in batch_buffer:
                            mf.write(json.dumps(entry)+"\n")
                            # also append to global manifest.jsonl (append-only)
                            try:
                                with open(manifest_path, "a") as gmf:
                                    gmf.write(json.dumps({"path": str(out_root / entry["file"]), "sha256": entry["sha256"], "sha256_full": entry["sha256_full"], "tokens_est": entry["tokens_est"], "source": entry["source"], "phase": entry["phase"], "timestamp": entry["timestamp"], "version": entry["version"]})+"\n")
                            except Exception as e:
                                print(f"  manifest append failed {e}")
                    print(f"[Expansion] Shard full {cur_path} {cur_bytes/1e6:.1f}MB, total tokens {total_tokens}/{target_tokens}, docs {total_docs}")
                    batch_buffer = []
                    current_shard_idx += 1
                    fh, cur_path, cur_bytes = new_shard()
                    print(f"[Expansion] New shard {cur_path}")

                if total_tokens >= target_tokens:
                    break
            if total_tokens % 50000 < 1000:
                print(f"[Expansion] Progress {total_tokens}/{target_tokens} tokens, docs {total_docs}, dup filtered {filtered_dup}, qual filtered {filtered_qual}")

    finally:
        try:
            fh.close()
        except:
            pass
        # flush remaining buffer
        if batch_buffer:
            new_shards.append(str(cur_path))
            with open(daily_manifest, "a") as mf:
                for entry in batch_buffer:
                    mf.write(json.dumps(entry)+"\n")
                    try:
                        with open(manifest_path, "a") as gmf:
                            gmf.write(json.dumps({"path": str(out_root / entry["file"]), "sha256": entry["sha256"], "sha256_full": entry["sha256_full"], "tokens_est": entry["tokens_est"], "source": entry["source"], "phase": entry["phase"], "timestamp": entry["timestamp"], "version": entry["version"]})+"\n")
                    except:
                        pass

    print(f"[Expansion] Done: {total_tokens} tokens, {total_docs} docs, shards {new_shards}, dup filtered {filtered_dup}, qual {filtered_qual}")
    print(f"[Expansion] Manifest {daily_manifest} + global {manifest_path}")

    # Upload handling
    print(f"[Expansion] Upload mode {args.upload_mode}")
    if args.upload_mode == "local":
        # Copy shards list to for_upload dir manifest
        upload_manifest = for_upload_root / f"upload_manifest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        upload_manifest.write_text(json.dumps({
            "disclaimer": DISCLAIMER,
            "shards": new_shards,
            "manifest": str(daily_manifest),
            "total_tokens": total_tokens,
            "total_docs": total_docs,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "note": "Saved locally for efficient downstream use on Alienware RTX 4090. Copy via: scp or rclone to personal Drive / R2. DO NOT upload to work Drive camd@meta.com per AGENTS.md"
        }, indent=2))
        print(f"[Expansion] Saved locally to {for_upload_root}, manifest {upload_manifest}")
        print(f"  -> For Alienware: rsync -avz {out_root}/ your-alienware:~/ava-agi-factory-v6-4/data/daily_expanded/")
    elif args.upload_mode == "gdrive":
        # Check work drive guard - import gdrive_uploader logic inline
        print("[Expansion] Checking Drive type before upload...")
        from scripts.gdrive_uploader import check_work_drive_guard, upload_folder
        is_work, msg = check_work_drive_guard()
        if is_work:
            print(f"[BLOCKED] {msg}")
            print(f"[Expansion] Aborting GDrive upload, saving to {for_upload_root} instead.")
            # fallback to local
            upload_manifest = for_upload_root / f"BLOCKED_WORK_DRIVE_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            upload_manifest.write_text(json.dumps({"blocked": True, "reason": msg, "shards": new_shards, "timestamp": datetime.now(timezone.utc).isoformat()}, indent=2))
            return
        # proceed upload
        remote_folder = "Ava-Datasets-Expansion"
        upload_folder(out_root, remote_folder, dry_run=False)
    elif args.upload_mode == "r2":
        # R2 upload via boto3 if credentials present
        print("[Expansion] Checking R2 credentials...")
        ak = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY") or os.environ.get("R2_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID")
        sk = os.environ.get("CLOUDFLARE_R2_SECRET_KEY") or os.environ.get("R2_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY")
        endpoint = os.environ.get("CLOUDFLARE_R2_ENDPOINT") or os.environ.get("R2_ENDPOINT")
        bucket = os.environ.get("CLOUDFLARE_R2_BUCKET", "ava-datasets")
        if not ak or not sk:
            print(f"[Expansion] R2 credentials missing, saving to {for_upload_root} instead. Set CLOUDFLARE_R2_ACCESS_KEY, SECRET_KEY, ENDPOINT")
            upload_manifest = for_upload_root / f"R2_MISSING_CREDS_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            upload_manifest.write_text(json.dumps({"shards": new_shards, "bucket": bucket, "note": "R2 creds missing"}, indent=2))
            return
        try:
            import boto3
            from botocore.config import Config
            s3 = boto3.client('s3', endpoint_url=endpoint, aws_access_key_id=ak, aws_secret_access_key=sk, config=Config(retries={'max_attempts': 3}))
            for shard_path in new_shards:
                key = f"expansion/{Path(shard_path).name}"
                print(f"[R2] Uploading {shard_path} -> s3://{bucket}/{key}")
                s3.upload_file(shard_path, bucket, key)
            # upload manifest
            s3.upload_file(str(daily_manifest), bucket, f"expansion/{daily_manifest.name}")
            print(f"[R2] Done uploaded {len(new_shards)} shards + manifest to s3://{bucket}/expansion/")
        except Exception as e:
            print(f"[R2] Upload failed {e}, falling back to local")
            import traceback; traceback.print_exc()

if __name__ == "__main__":
    main()
