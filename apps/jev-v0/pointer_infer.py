"""Load a ``train_pointer_lora.py --go`` checkpoint and answer typed questions.

GPU-host code: torch / transformers / peft are imported inside
:func:`load_checkpoint`, never at module load, so ``serve_decide.py`` without
``--checkpoint`` (and every test) stays torch-free.

A checkpoint directory is what ``--go`` writes::

    lora/             peft adapter (save_pretrained)
    tokenizer/        tokenizer with the added boundary tokens
    pointer.pt        {"query": state_dict, "key": state_dict}
    train_report.json names the base model (architecture.base_model)

Inference mirrors training exactly: the same ``_render_branch`` text, the
query at ``<decide>``, one key per ``</opt>``, softmax over the offered set.
The result is a closed distribution; nothing here is calibrated or called
confidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_APP = Path(__file__).resolve().parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from decision_io import SchemaError, option_keys
from train_pointer_lora import POINTER_DIM, _render_branch

REQUIRED = ("lora", "tokenizer", "pointer.pt", "train_report.json")


def check_layout(checkpoint: Path) -> dict[str, Any]:
    """Refuse a directory that is not a ``--go`` checkpoint. Torch-free."""
    missing = [name for name in REQUIRED if not (checkpoint / name).exists()]
    if missing:
        raise SchemaError(f"{checkpoint} is not a pointer-LoRA checkpoint (missing {missing})")
    report = json.loads((checkpoint / "train_report.json").read_text(encoding="utf-8"))
    base = ((report.get("architecture") or {}).get("base_model")) if isinstance(report, dict) else None
    if not base:
        raise SchemaError(f"{checkpoint}/train_report.json does not name architecture.base_model")
    return report


class PointerPredictor:
    """Frozen backbone + LoRA + pointer heads, eval mode, no gradients."""

    def __init__(self, checkpoint: Path, report: dict[str, Any]) -> None:
        try:
            import torch
            from peft import PeftModel
            from torch import nn
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise SystemExit(
                "--checkpoint needs torch, transformers and peft (requirements-jev-v0.txt, GPU host). "
                f"Import failed: {exc}"
            ) from exc
        self.torch = torch
        base_model = report["architecture"]["base_model"]
        self.tokenizer = AutoTokenizer.from_pretrained(str(checkpoint / "tokenizer"), trust_remote_code=False)
        backbone = AutoModelForCausalLM.from_pretrained(base_model, trust_remote_code=False)
        backbone.resize_token_embeddings(len(self.tokenizer))
        self.model = PeftModel.from_pretrained(backbone, str(checkpoint / "lora"))
        hidden = int(self.model.config.hidden_size)
        self.query = nn.Linear(hidden, POINTER_DIM, bias=False)
        self.key = nn.Linear(hidden, POINTER_DIM, bias=False)
        heads = torch.load(checkpoint / "pointer.pt", map_location="cpu", weights_only=True)
        self.query.load_state_dict(heads["query"])
        self.key.load_state_dict(heads["key"])
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        for module in (self.model, self.query, self.key):
            module.to(self.device)
            module.eval()
        self.scale = POINTER_DIM**-0.5
        self.close_id = self.tokenizer.convert_tokens_to_ids("</opt>")
        self.decide_id = self.tokenizer.convert_tokens_to_ids("<decide>")

    def probabilities(self, state: dict[str, Any], question: dict[str, Any]) -> dict[str, float]:
        torch = self.torch
        state_text = json.dumps(state, ensure_ascii=True, sort_keys=True)
        text, keys = _render_branch(state_text, question)
        with torch.no_grad():
            input_ids = self.tokenizer(text, return_tensors="pt")["input_ids"].to(self.device)
            hidden = self.model(input_ids=input_ids, output_hidden_states=True).hidden_states[-1][0]
            ids = input_ids[0]
            opt_index = (ids == self.close_id).nonzero(as_tuple=False).squeeze(-1)
            decide_index = (ids == self.decide_id).nonzero(as_tuple=False).squeeze(-1)
            if opt_index.numel() != len(keys) or decide_index.numel() != 1:
                raise SchemaError("pointer alignment failed: option boundary tokens do not match the offered set")
            logits = (self.query(hidden[decide_index[0]]) @ self.key(hidden.index_select(0, opt_index)).T) * self.scale
            probs = torch.softmax(logits.float(), dim=-1).cpu().tolist()
        if keys != option_keys(question):
            raise SchemaError("rendered options drifted from the schema option order")
        return {k: float(p) for k, p in zip(keys, probs, strict=True)}


def load_checkpoint(checkpoint: Path) -> PointerPredictor:
    report = check_layout(Path(checkpoint))
    return PointerPredictor(Path(checkpoint), report)
