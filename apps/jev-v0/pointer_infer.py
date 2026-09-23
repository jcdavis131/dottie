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

One request asks several questions about ONE state, and every branch starts
with the same ``<state> ... </state>`` text. :class:`SharedPrefixScorer`
tokenizes each full branch exactly as training did, finds the longest shared
token prefix (never past an option or decide boundary), encodes that prefix
once with the KV cache, and runs only each question's suffix on a copy of the
cache. A causal LM's hidden states at a position depend only on the tokens up
to it, so this is the same computation as encoding each branch whole; it just
stops re-encoding the state once per question. The orchestration is torch-free
(tokenize / encode / copy / score are injected), so it is unit-tested with a
fake model on hosts without torch.
"""

from __future__ import annotations

import copy
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

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


def shared_prefix_len(seqs: Sequence[Sequence[int]], stop_ids: set[int]) -> int:
    """Longest common token prefix of ``seqs`` that contains no ``stop_ids`` and
    leaves at least one token of every sequence to run as a suffix."""
    if not seqs:
        return 0
    limit = min(len(s) for s in seqs) - 1
    n = 0
    while n < limit:
        tok = seqs[0][n]
        if tok in stop_ids or any(s[n] != tok for s in seqs[1:]):
            break
        n += 1
    return max(0, n)


def softmax(xs: Sequence[float]) -> list[float]:
    m = max(xs)
    ex = [math.exp(x - m) for x in xs]
    z = sum(ex)
    return [e / z for e in ex]


@dataclass
class SharedPrefixScorer:
    """Score every question of one request from a single encoding of the shared prefix.

    ``tokenize(text) -> list[int]`` (the training tokenizer on the full branch
    text), ``encode(ids, past) -> (hidden_rows, past)`` (rows for ``ids`` only,
    continuing from ``past``; ``past=None`` starts fresh), ``copy_past(past)``
    (an independent cache), ``score(query_row, key_rows) -> logits``.
    """

    tokenize: Callable[[str], list[int]]
    encode: Callable[[list[int], Any], tuple[Sequence[Any], Any]]
    copy_past: Callable[[Any], Any]
    score: Callable[[Any, Sequence[Any]], Sequence[float]]
    close_id: int
    decide_id: int

    def probabilities_many(self, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
        state_text = json.dumps(state, ensure_ascii=True, sort_keys=True)
        branches = {qid: _render_branch(state_text, q) for qid, q in questions.items()}
        ids = {qid: list(self.tokenize(text)) for qid, (text, _keys) in branches.items()}
        order = list(questions)
        n = shared_prefix_len([ids[q] for q in order], {self.close_id, self.decide_id})
        past = None
        if n > 0:
            _rows, past = self.encode(ids[order[0]][:n], None)
        out: dict[str, dict[str, float]] = {}
        for qid in order:
            question = questions[qid]
            full = ids[qid]
            keys = branches[qid][1]
            suffix = full[n:]
            rows, _ = self.encode(suffix, self.copy_past(past) if past is not None else None)
            opt_pos = [i for i, t in enumerate(suffix) if t == self.close_id]
            dec_pos = [i for i, t in enumerate(suffix) if t == self.decide_id]
            if len(opt_pos) != len(keys) or len(dec_pos) != 1:
                raise SchemaError("pointer alignment failed: option boundary tokens do not match the offered set")
            if keys != option_keys(question):
                raise SchemaError("rendered options drifted from the schema option order")
            probs = softmax([float(x) for x in self.score(rows[dec_pos[0]], [rows[i] for i in opt_pos])])
            out[qid] = {k: float(p) for k, p in zip(keys, probs, strict=True)}
        return out


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

    def _encode(self, ids: list[int], past: Any) -> tuple[Any, Any]:
        torch = self.torch
        with torch.no_grad():
            t = torch.tensor([ids], device=self.device)
            out = self.model(input_ids=t, past_key_values=past, use_cache=True, output_hidden_states=True)
        return out.hidden_states[-1][0], out.past_key_values

    def _score(self, query_row: Any, key_rows: Sequence[Any]) -> list[float]:
        torch = self.torch
        with torch.no_grad():
            keys = torch.stack(list(key_rows))
            logits = (self.query(query_row) @ self.key(keys).T) * self.scale
        return logits.float().cpu().tolist()

    def scorer(self) -> SharedPrefixScorer:
        return SharedPrefixScorer(
            tokenize=lambda text: list(self.tokenizer(text)["input_ids"]),
            encode=self._encode,
            copy_past=copy.deepcopy,
            score=self._score,
            close_id=int(self.close_id),
            decide_id=int(self.decide_id),
        )

    def probabilities_many(self, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
        """All questions of one request; the shared state prefix is encoded once."""
        return self.scorer().probabilities_many(state, questions)

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
