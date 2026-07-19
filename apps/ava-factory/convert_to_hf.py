"""
convert_to_hf.py — convert deepspeed ckpt to HF
Solo personal project, no connection to employer, built with public/free-tier only
"""
import argparse
from pathlib import Path
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--ckpt", required=True)
    parser.add_argument("--out", default="hf_model")
    args=parser.parse_args()
    out=Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out/"config.json").write_text('{"model_type":"ava","hidden_size":2048,"num_layers":48}')
    (out/"README.md").write_text(f"# Converted from {args.ckpt}\nSolo personal project")
    print(f"Converted {args.ckpt} -> {args.out} (mock)")

if __name__=="__main__":
    main()
