"""
Ava AGI Factory — HF Hub Curated Dataset Uploader (Loop 1 -> Loop 2)
Solo personal project, no connection to employer, built with public/free-tier only
"""
import argparse, glob, json, hashlib, os, sys
from pathlib import Path
from datetime import datetime, timezone

DISCLAIMER = "Solo personal project, no connection to employer, built with public/free-tier only"

def gather_manifests(pattern):
    files = sorted(glob.glob(pattern))
    if not files:
        return [], []
    entries = []
    for mf in files:
        try:
            with open(mf) as fd:
                for line in fd:
                    try:
                        entries.append(json.loads(line))
                    except: pass
        except: pass
    return entries, files

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="jcdavis131/ava-textbook-v6")
    ap.add_argument("--manifest", default="data/daily_expanded/manifest_*.jsonl")
    ap.add_argument("--private", action="store_true", default=True)
    ap.add_argument("--parquet", action="store_true")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--split", default="92/6/2")
    args = ap.parse_args()

    entries, mfiles = gather_manifests(args.manifest)
    if not entries:
        # fallback: for_upload
        fm = sorted(Path("data/for_upload").glob("upload_manifest_*.json"))
        if fm:
            print(f"Using for_upload manifests: {fm[-1]}")
            try:
                data = json.loads(Path(fm[-1]).read_text())
                # normalize mixed formats: if data is dict with shards list, treat as mfiles
                if isinstance(data, dict):
                    print(json.dumps(data, indent=2)[:2000])
                    # entries remain empty, but we have manifest for downstream
                    mfiles = fm
                else:
                    mfiles = fm
            except Exception as e:
                print(f"read for_upload failed: {e}")
                mfiles = fm

    total_tokens = 0
    if entries:
        try:
            total_tokens = sum(e.get("tokens",0) if isinstance(e, dict) else 0 for e in entries)
        except:
            total_tokens = 0
    print(f"[HF Uploader] {DISCLAIMER} Repo: {args.repo} entries={len(entries)} tokens={total_tokens}")

    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if not hf_token:
        print("WARNING: HF_TOKEN not set — saving locally for Alienware push (expected in Hatch VM)")
        Path("data/for_upload").mkdir(parents=True, exist_ok=True)
        out = Path(f"data/for_upload/hf_ready_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")
        out.write_text(json.dumps({
            "disclaimer": DISCLAIMER,
            "repo": args.repo,
            "manifests": [str(p) for p in mfiles],
            "total_tokens": total_tokens,
            "split": args.split,
            "note": "On Alienware: HF_TOKEN=... python scripts/hf_uploader.py --repo jcdavis131/ava-textbook-v6 --push",
            "streaming_example": f'from datasets import load_dataset; ds = load_dataset("{args.repo}", streaming=True, split="train"); next(iter(ds))'
        }, indent=2))
        print(f"Saved {out}")
        return 0

    if args.dry_run:
        print("Dry-run — not pushing")
        return 0

    if hf_token and args.push:
        try:
            from datasets import Dataset
            from huggingface_hub import HfApi
            import pandas as pd
            api = HfApi(token=hf_token)
            try:
                api.create_repo(repo_id=args.repo, repo_type="dataset", private=args.private, exist_ok=True)
                print(f"Repo ensured: {args.repo}")
            except Exception as e:
                print(f"create_repo: {e}")
            if entries:
                rows = [{"text": e.get("text","")[:2000], "source": e.get("source",""), "tokens": e.get("tokens",0), "phase": e.get("phase","")} for e in entries[:1000]]
                df = pd.DataFrame(rows)
                ds = Dataset.from_pandas(df)
                split_ratio = [int(x) for x in args.split.split("/")]
                total = sum(split_ratio)
                train_end = int(len(ds)*split_ratio[0]/total)
                val_end = train_end + int(len(ds)*split_ratio[1]/total)
                ds_train = ds.select(range(0, train_end))
                ds_val = ds.select(range(train_end, val_end))
                ds_test = ds.select(range(val_end, len(ds)))
                print(f"Pushing {len(ds_train)}/{len(ds_val)}/{len(ds_test)}")
                ds_train.push_to_hub(args.repo, private=args.private, split="train")
                if len(ds_val)>0: ds_val.push_to_hub(args.repo, private=args.private, split="validation")
                if len(ds_test)>0: ds_test.push_to_hub(args.repo, private=args.private, split="test")
                print("Push complete")
            else:
                print("No entries — run dataset_expansion.py first")
        except Exception as e:
            print(f"Push failed: {e}")
            import traceback; traceback.print_exc()
    else:
        print("Set --push and HF_TOKEN")

if __name__ == "__main__":
    sys.exit(main())
