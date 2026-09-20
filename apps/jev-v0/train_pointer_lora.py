#!/usr/bin/env python3
"""Train (or dry-run) a small LoRA + pointer-head System One spike.

``--dry-run`` is the default and is torch-free: it loads the frozen schema,
validates the synthetic fixtures, and prints the architecture plan.

``--go`` is optional and lazy-imports torch / transformers / peft. It is
not started by this scaffold's verification. This is NOT ``train_1b`` and
it is NOT TypeSafe parity.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_APP = Path(__file__).resolve().parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from decision_io import (
    APP_ROOT,
    DEFAULT_FIXTURES,
    DEFAULT_SCHEMA,
    SCHEMA_ID,
    load_fixtures,
    load_schema,
    option_keys,
    type_counts,
)

DEFAULT_BASE = "Qwen/Qwen2.5-0.5B"
DEFAULT_OUT = APP_ROOT / "runs" / "jev-v0-pointer"
LORA_R = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05
POINTER_DIM = 256
LORA_TARGETS = (
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
)


def architecture_plan(base_model: str) -> dict[str, Any]:
    return {
        "pivot": "small+LoRA+pointer heads",
        "not": ["train_1b", "TypeSafe parity"],
        "schema": SCHEMA_ID,
        "base_model": base_model,
        "backbone": "frozen causal LM; prefill-only; no free-text decode",
        "lora": {
            "r": LORA_R,
            "alpha": LORA_ALPHA,
            "dropout": LORA_DROPOUT,
            "targets": list(LORA_TARGETS),
        },
        "head": {
            "kind": "pointer",
            "query": "<decide> hidden state",
            "key": "</opt> hidden state per closed option",
            "dim": POINTER_DIM,
            "loss": "cross-entropy over the offered option set",
        },
        "types": {
            "choice": "pointer over criteria keys",
            "score": "pointer over ordered levels; score is E[level]",
            "noul": "pointer over {true, false}; noul = P(true)",
        },
    }


def dry_run(*, schema_path: Path, fixtures_path: Path, base_model: str) -> dict[str, Any]:
    """Validate fixtures and report the plan. Must not import torch."""
    if "torch" in sys.modules:
        raise RuntimeError("--dry-run must stay torch-free; torch was already imported")
    schema = load_schema(schema_path)
    records = load_fixtures(fixtures_path)
    report = {
        "ok": True,
        "dry_run": True,
        "training": False,
        "schema": schema["$id"],
        "schema_path": str(schema_path),
        "fixtures_path": str(fixtures_path),
        "records": len(records),
        "question_types": type_counts(records),
        "architecture": architecture_plan(base_model),
        "torch_imported": "torch" in sys.modules,
    }
    if report["torch_imported"]:
        raise RuntimeError("--dry-run imported torch; that is a regression")
    return report


def _label_index(question: dict[str, Any], label: dict[str, Any]) -> int:
    keys = option_keys(question)
    qtype = question["type"]
    if qtype == "choice":
        return keys.index(label["choice"])
    if qtype == "score":
        return min(range(len(keys)), key=lambda i: abs(i - label["score"]))
    if qtype == "noul":
        return 0 if label["noul"] >= 0.5 else 1
    impossible: str = qtype
    raise ValueError(f"unhandled question type {impossible!r}")


def _flatten_examples(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for record in records:
        state_text = json.dumps(record["state"], ensure_ascii=True, sort_keys=True)
        for qid, question in record["questions"].items():
            examples.append(
                {
                    "id": f"{record['id']}:{qid}",
                    "state": state_text,
                    "question": question,
                    "label_index": _label_index(question, record["labels"][qid]),
                }
            )
    return examples


def _render_branch(state_text: str, question: dict[str, Any]) -> tuple[str, list[str]]:
    """Pack state + one isolated question branch with option boundary tokens."""
    keys = option_keys(question)
    qtype = question["type"]
    lines = [
        "<state>",
        state_text,
        "</state>",
        f"<q type={qtype}>",
        question["instructions"],
    ]
    if qtype == "choice":
        for key in keys:
            lines.append(f"<opt id={key}> {question['criteria'][key]} </opt>")
    elif qtype == "score":
        for key, label in zip(keys, question["criteria"], strict=True):
            lines.append(f"<opt id={key}> {label} </opt>")
    elif qtype == "noul":
        lines.append("<opt id=true> The statement is true. </opt>")
        lines.append("<opt id=false> The statement is false. </opt>")
    else:
        raise ValueError(f"unhandled question type {qtype!r}")
    lines.append("<decide>")
    return "\n".join(lines), keys


def run_go(
    *,
    schema_path: Path,
    fixtures_path: Path,
    base_model: str,
    out_dir: Path,
    steps: int,
    lr: float,
) -> dict[str, Any]:
    """Optional HF+peft path. Lazy-imports heavy deps so --dry-run stays clean.

    Documented exception to the no-inline-import rule: torch / transformers /
    peft must not be imported at module load, or ``--dry-run`` stops being
    torch-free on a box that happens to have them installed.
    """
    load_schema(schema_path)
    records = load_fixtures(fixtures_path)
    examples = _flatten_examples(records)
    try:
        import torch
        from peft import LoraConfig, TaskType, get_peft_model
        from torch import nn
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise SystemExit(
            "--go needs torch, transformers, and peft. "
            "Install from requirements-jev-v0.txt on the GPU host. "
            f"Import failed: {exc}"
        ) from exc

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=False)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    special = ["<state>", "</state>", "<q>", "</opt>", "<decide>"]
    tokenizer.add_special_tokens({"additional_special_tokens": special})

    backbone = AutoModelForCausalLM.from_pretrained(base_model, trust_remote_code=False)
    backbone.resize_token_embeddings(len(tokenizer))
    for parameter in backbone.parameters():
        parameter.requires_grad = False
    lora = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=list(LORA_TARGETS),
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    backbone = get_peft_model(backbone, lora)
    hidden = int(backbone.config.hidden_size)
    query = nn.Linear(hidden, POINTER_DIM, bias=False)
    key = nn.Linear(hidden, POINTER_DIM, bias=False)
    scale = POINTER_DIM**-0.5

    trainable = [parameter for parameter in backbone.parameters() if parameter.requires_grad]
    trainable.extend(query.parameters())
    trainable.extend(key.parameters())
    optimizer = torch.optim.AdamW(trainable, lr=lr)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    backbone.to(device)
    query.to(device)
    key.to(device)
    backbone.train()
    query.train()
    key.train()

    close_id = tokenizer.convert_tokens_to_ids("</opt>")
    decide_id = tokenizer.convert_tokens_to_ids("<decide>")
    losses: list[float] = []
    for step in range(steps):
        example = examples[step % len(examples)]
        text, _keys = _render_branch(example["state"], example["question"])
        encoded = tokenizer(text, return_tensors="pt")
        input_ids = encoded["input_ids"].to(device)
        outputs = backbone(input_ids=input_ids, output_hidden_states=True)
        hidden_states = outputs.hidden_states[-1][0]
        token_ids = input_ids[0]
        opt_index = (token_ids == close_id).nonzero(as_tuple=False).squeeze(-1)
        decide_index = (token_ids == decide_id).nonzero(as_tuple=False).squeeze(-1)
        if opt_index.numel() != len(option_keys(example["question"])) or decide_index.numel() != 1:
            raise RuntimeError(f"pointer alignment failed for {example['id']}")
        opt_h = hidden_states.index_select(0, opt_index)
        decide_h = hidden_states[decide_index[0]]
        logits = (query(decide_h) @ key(opt_h).T) * scale
        target = torch.tensor(example["label_index"], device=device)
        loss = torch.nn.functional.cross_entropy(logits.unsqueeze(0), target.unsqueeze(0))
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach().cpu()))

    out_dir.mkdir(parents=True, exist_ok=True)
    backbone.save_pretrained(out_dir / "lora")
    tokenizer.save_pretrained(out_dir / "tokenizer")
    torch.save({"query": query.state_dict(), "key": key.state_dict()}, out_dir / "pointer.pt")
    report = {
        "ok": True,
        "dry_run": False,
        "training": True,
        "schema": SCHEMA_ID,
        "records": len(records),
        "examples": len(examples),
        "steps": steps,
        "final_loss": losses[-1] if losses else None,
        "device": str(device),
        "out_dir": str(out_dir),
        "architecture": architecture_plan(base_model),
    }
    (out_dir / "train_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="validate schema+fixtures and print the plan (default, torch-free)",
    )
    mode.add_argument(
        "--go",
        dest="dry_run",
        action="store_false",
        help="optional HF+peft train on the GPU host; not started by this PR",
    )
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--base-model", default=DEFAULT_BASE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--lr", type=float, default=5e-5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run:
        report = dry_run(
            schema_path=args.schema,
            fixtures_path=args.fixtures,
            base_model=args.base_model,
        )
    else:
        report = run_go(
            schema_path=args.schema,
            fixtures_path=args.fixtures,
            base_model=args.base_model,
            out_dir=args.out,
            steps=args.steps,
            lr=args.lr,
        )
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
