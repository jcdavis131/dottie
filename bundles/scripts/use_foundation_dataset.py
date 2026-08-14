#!/usr/bin/env python3
"""
use_foundation_dataset.py — Dottie hook to consume foundation self-improvement dataset as SFT/RL extra data
Zero-deps stdlib only, Dottie-native
- Reads datasets/foundation-self-improvement/latest/instruction_tuning.jsonl
- Exposes as LLMVM env key foundation_lessons, for rlm.py env injection
- Can be called as: python3 use_foundation_dataset.py --info | --train-file
"""
import pathlib, json, sys, argparse

HOME=pathlib.Path.home()
BASE=HOME/"workspace"/"datasets"/"foundation-self-improvement"
LATEST=BASE/"latest"
VDIR=BASE/"v0.1.0"

def resolve_latest():
    if LATEST.is_symlink():
        try:
            return LATEST.resolve()
        except:
            return VDIR
    if LATEST.exists():
        return LATEST
    return VDIR

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--info", action="store_true")
    parser.add_argument("--train-file", action="store_true")
    parser.add_argument("--val-file", action="store_true")
    args=parser.parse_args()

    v = resolve_latest()
    instr = v/"instruction_tuning.jsonl"
    if not instr.exists():
        instr = VDIR/"instruction_tuning.jsonl"

    if args.info:
        manifest=v/"manifest.json"
        if manifest.exists():
            print(manifest.read_text())
        else:
            print(json.dumps({"error":"manifest missing","fallback":str(v)}))
        return

    if args.train_file:
        p=v/"train.jsonl"
        if p.exists():
            print(str(p))
        else:
            print(str(v/"instruction_tuning.jsonl"))
        return

    if args.val_file:
        p=v/"val.jsonl"
        print(str(p) if p.exists() else str(v/"instruction_tuning.jsonl"))
        return

    # default: print env injection snippet for rlm.py
    count=0
    lessons=[]
    if instr.exists():
        with instr.open() as f:
            for line in f:
                try:
                    j=json.loads(line)
                    lessons.append(j)
                    count+=1
                except:
                    continue
    # for llmvm env: provide summary
    print(json.dumps({
        "foundation_lessons_count": count,
        "foundation_dataset_path": str(instr),
        "foundation_train": str(v/"train.jsonl"),
        "foundation_val": str(v/"val.jsonl"),
        "foundation_version": str(v),
        "usage": "Add to dottie/rlm.py env as foundation_lessons=lessons[:5] for few-shot, or --data foundation-self-improvement/latest for SFT"
    }, indent=2))

if __name__=="__main__":
    main()
