"""Real intervention engine — forward hooks on live workspace states."""

from __future__ import annotations

from typing import Any

import torch
import torch.nn.functional as F

from multi_jspace_module import SPACE_NAMES

_SPACE_ALIASES = {
    "s1": "system1",
    "s2": "system2",
    "system1": "system1",
    "system2": "system2",
    "critic": "critic",
    "planner": "planner",
}


def resolve_space(name: str) -> str:
    key = name.lower().replace("-", "").replace("_", "")
    for alias, canonical in _SPACE_ALIASES.items():
        if key == alias.replace("_", ""):
            return canonical
    if name in SPACE_NAMES:
        return name
    raise ValueError(f"unknown workspace {name!r}; expected one of {SPACE_NAMES}")


def concept_vector(model, tokenizer, word: str) -> tuple[torch.Tensor, int]:
    """Unit-norm tied verbalizer row for a concept.

    Prefer a single-token encode; when BPE splits the word (nano vocab),
    fall back to ``concept_token()`` (first piece) — same addressing the
    reportability loss uses. Spec 06 assumed merged concepts; this deviation
    is required for sub-32k vocabs.
    """
    ids = tokenizer.encode(word)
    if len(ids) == 1:
        tok_id = ids[0]
    else:
        tok_id = tokenizer.concept_token(word)
    vec = model.lm_head.weight[tok_id]
    return F.normalize(vec, dim=0), tok_id


def _swap_workspace(ws: torch.Tensor, from_vec: torch.Tensor, to_vec: torch.Tensor, alpha: float) -> torch.Tensor:
    """Project each slot onto from_vec, replace that component with alpha * to_vec."""
    coef = torch.einsum("bsd,d->bs", ws, from_vec)
    return ws - coef.unsqueeze(-1) * from_vec + coef.unsqueeze(-1) * alpha * to_vec


def _swap_broadcast(b: torch.Tensor, from_vec: torch.Tensor, to_vec: torch.Tensor, alpha: float) -> torch.Tensor:
    """Swap concept direction in a broadcast tensor [B, L, D]."""
    coef = torch.einsum("bld,d->bl", b, from_vec)
    return b - coef.unsqueeze(-1) * from_vec + coef.unsqueeze(-1) * alpha * to_vec


class WorkspaceSwap:
    """Swap a concept direction in one workspace's state before each chunk broadcast."""

    def __init__(self, model, tokenizer, space: str, from_word: str, to_word: str, alpha: float = 1.0):
        self.model = model
        self.tokenizer = tokenizer
        self.space = resolve_space(space)
        self.from_vec, _ = concept_vector(model, tokenizer, from_word)
        self.to_vec, _ = concept_vector(model, tokenizer, to_word)
        self.alpha = alpha
        self._orig_emit = None

    def __enter__(self):
        mj = self.model.multi_jspace
        if mj is None:
            raise RuntimeError("model has no multi_jspace")
        orig = mj._emit
        space = self.space
        fv, tv, alpha = self.from_vec, self.to_vec, self.alpha

        def patched_emit(states, chunk_len, task_type):
            states = dict(states)
            states[space] = _swap_workspace(states[space], fv, tv, alpha)
            return orig(states, chunk_len, task_type)

        mj._emit = patched_emit  # type: ignore[method-assign]
        self._orig_emit = orig
        return self

    def __exit__(self, *args):
        if self._orig_emit is not None:
            self.model.multi_jspace._emit = self._orig_emit  # type: ignore[method-assign]


class BroadcastSwap:
    """Swap concept direction in one space's broadcast contribution only."""

    def __init__(self, model, tokenizer, space: str, from_word: str, to_word: str, alpha: float = 1.0):
        self.model = model
        self.tokenizer = tokenizer
        self.space = resolve_space(space)
        self.from_vec, _ = concept_vector(model, tokenizer, from_word)
        self.to_vec, _ = concept_vector(model, tokenizer, to_word)
        self.alpha = alpha
        self._orig_emit = None

    def __enter__(self):
        mj = self.model.multi_jspace
        if mj is None:
            raise RuntimeError("model has no multi_jspace")
        orig = mj._emit
        space = self.space
        fv, tv, alpha = self.from_vec, self.to_vec, self.alpha
        spaces = mj.spaces()

        def patched_emit(states, chunk_len, task_type):
            B = states["system1"].shape[0]
            b = {}
            for n in SPACE_NAMES:
                raw = spaces[n].broadcast_from(states[n], chunk_len)
                if n == space:
                    raw = _swap_broadcast(raw, fv, tv, alpha)
                b[n] = raw

            pooled = torch.stack([states[n].mean(dim=1) for n in SPACE_NAMES], 0).mean(0)
            route_probs, route_logits = mj.router(pooled, task_type=task_type)
            veto = mj.arbitration(states["system1"].mean(dim=1), states["system2"].mean(dim=1))
            w = [route_probs[:, i].view(B, 1, 1) for i in range(4)]
            w[1] = w[1] * (1 + veto.view(B, 1, 1) * 0.5)
            combined = sum(wi * b[n] for wi, n in zip(w, SPACE_NAMES))
            return combined, route_probs, route_logits, veto

        mj._emit = patched_emit  # type: ignore[method-assign]
        self._orig_emit = orig
        return self

    def __exit__(self, *args):
        if self._orig_emit is not None:
            self.model.multi_jspace._emit = self._orig_emit  # type: ignore[method-assign]


def top_concept_trace(model, tokenizer, out: dict[str, Any], k: int = 8) -> dict[str, list[tuple[str, float]]]:
    """Map jspace top_concepts/top_probs to (token_str, prob) pairs per space."""
    trace: dict[str, list[tuple[str, float]]] = {}
    jspace = out.get("jspace", {})
    for space in SPACE_NAMES:
        if space not in jspace:
            continue
        top_idx = jspace[space]["top_concepts"][0]
        top_vals = jspace[space]["top_probs"][0]
        pairs = []
        for idx, prob in zip(top_idx.tolist(), top_vals.tolist()):
            pairs.append((tokenizer.decode([int(idx)]), float(prob)))
        trace[space] = pairs
    return trace
