"""Stage 5: print the GPU-host System One training command for this pack. Runs nothing.

The trainer is apps/jev-v0/train_pointer_lora.py (the same argv
dottie_loop.router_training.train_command builds for router packs): `--go`
trains LoRA + pointer heads on `--fixtures`, one question per step, walking the
file in order (curate shuffles train.jsonl for that reason). The default step
count is one pass over every question of every train record.
"""

from __future__ import annotations

import argparse
import json
import shlex

from . import PACK_VERSION
from .common import APP_ROOT, DATA

REPO = APP_ROOT.parent.parent


def command(pack: str = PACK_VERSION, steps: int | None = None, base_model: str | None = None) -> dict[str, object]:
    pack_dir = DATA / "packs" / pack
    manifest = json.loads((pack_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    questions = len(manifest["questions"])
    n_steps = steps or manifest["rows"]["train"] * questions
    rel = pack_dir.relative_to(REPO).as_posix()
    out = f"apps/jev-v0/runs/{pack}"
    go = ["python", "apps/jev-v0/train_pointer_lora.py", "--go", "--fixtures", f"{rel}/train.jsonl",
          "--out", out, "--steps", str(n_steps)]
    if base_model:
        go += ["--base-model", base_model]
    return {
        "pack": pack,
        "train_rows": manifest["rows"]["train"],
        "questions_per_row": questions,
        "steps": n_steps,
        "setup": "pip install -r apps/jev-v0/requirements-jev-v0.txt   # plus the host CUDA torch wheel",
        "rebuild": f"python3 apps/atlas-outcomes/run.py curate   # rebuilds {rel}/ offline from sources/",
        "dry_run": shlex.join(["python", "apps/jev-v0/train_pointer_lora.py", "--dry-run", "--fixtures", f"{rel}/train.jsonl"]),
        "train": shlex.join(go),
        "serve": shlex.join(["python", "apps/jev-v0/serve_decide.py", "--checkpoint", out, "--port", "8771"]),
        "eval": f"score {rel}/holdout.jsonl with the served checkpoint and compare against apps/atlas-outcomes/BASELINE.json "
                "(python3 apps/atlas-outcomes/run.py baseline --score <predictions.jsonl>); nothing promotes without a human stamp",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack", default=PACK_VERSION)
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--base-model", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    c = command(args.pack, args.steps, args.base_model)
    if args.json:
        print(json.dumps(c, indent=2))
        return 0
    print("# GPU host, from the repo root. Not run here.")
    print(f"# pack {c['pack']}: {c['train_rows']} train rows x {c['questions_per_row']} questions = {c['steps']} steps (one pass)")
    for k in ("setup", "rebuild", "dry_run", "train", "serve"):
        print(c[k])
    print(f"# eval: {c['eval']}")
    return 0
