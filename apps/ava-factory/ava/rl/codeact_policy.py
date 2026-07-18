# Solo personal project, no connection to employer, built with public/free-tier only
"""TorchModelPolicy — the REAL model-driven code-act policy (spec 13 T13C.5, real decode half).

This is the module `ava/rl/codeact_loop.py::ModelPolicy` honestly refused to be until a real
decode path existed. It implements the loop's `Policy` contract (transcript: str -> next
assistant turn: str) over any torch language model + any encode/decode tokenizer:

    tokenize transcript -> left-truncate to `context_window` -> autoregressive decode
    (greedy or temperature/top-k sampling, seedable) -> decode the NEW tokens ->
    cut at stop sequences (the `<|user|>` marker / EOS) -> return the turn text.

Honesty gate, preserved but relocated: the old `ModelPolicy` refused to *run* because no decode
machinery existed — refusing was the only non-fabricating option. Now the machinery is real, so
the gate moves to construction: `TorchModelPolicy(model=None, ...)` or `(..., tokenizer=None)`
raises immediately with a clear error. With a real (even untrained) model it WORKS — an untrained
nano model emits noise turns, and that is the honest output of an untrained model, not a
fabrication. Capability is a property of the *checkpoint*, not of this code.

Model adapter (documented contract): the wrapped model is called `model(input_ids=<LongTensor
[B, L]>, **forward_kwargs)` and may return EITHER
  • a dict containing ``'lm_logits'`` of shape [B, L, V]  (the AvaModel contract), OR
  • a raw logits tensor of shape [B, L, V] (or [B, V] for a last-step-only model).
Anything else raises `TypeError`. No KV cache — each step re-runs the full (truncated) prefix;
dependency-light (torch only) and plenty for nano-scale CPU decoding.

Tokenizer contract (duck-typed): `encode(str) -> list[int]` and `decode(list[int]) -> str`.
`AvaTokenizer` satisfies it; its `decode(ids, skip_special=...)` keyword is used when available
(specials kept, so the `<|user|>` stop marker survives decoding) and skipped otherwise.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import torch

# Match ava/rl/codeact_loop.py / ava/datagen/codeact.py: the next-turn marker is the stop.
DEFAULT_STOP_SEQUENCES: Tuple[str, ...] = ("<|user|>", "<|assistant|>", "<|endofdoc|>")


def _extract_logits(out: Any) -> torch.Tensor:
    """Adapter: dict-with-'lm_logits' (AvaModel) or raw tensor -> last-position logits [B, V]."""
    if isinstance(out, dict):
        if "lm_logits" not in out:
            raise TypeError(
                f"model returned a dict without 'lm_logits' (keys={sorted(out.keys())}); "
                "the AvaModel contract requires out['lm_logits'] of shape [B, L, V]"
            )
        out = out["lm_logits"]
    if not torch.is_tensor(out):
        raise TypeError(
            f"model output must be a dict with 'lm_logits' or a logits tensor, got {type(out)!r}"
        )
    if out.dim() == 3:          # [B, L, V] — full-sequence logits
        return out[:, -1, :]
    if out.dim() == 2:          # [B, V] — a last-step-only model
        return out
    raise TypeError(f"logits must be [B, L, V] or [B, V], got shape {tuple(out.shape)}")


class TorchModelPolicy:
    """Real autoregressive code-act policy: wraps (model, tokenizer) as a loop `Policy`.

    Spec 13 T13C.5: this is the decode driver `run_code_act` plugs a model into — the piece
    `ServeEngine.generate`'s code-act mode and the T13C.3 real eval were gated on.

    Args:
        model: torch LM; called ``model(input_ids=LongTensor[1, L], **forward_kwargs)``; must
            return a dict with ``'lm_logits'`` [B, L, V] (AvaModel) or a raw logits tensor.
            Required — ``None`` raises (the honest gate: no model, no policy).
        tokenizer: duck-typed ``encode(str)->list[int]`` / ``decode(list[int])->str``.
            Required — ``None`` raises.
        max_new_tokens: decode budget per turn (default 256).
        temperature: 0.0 (default) = greedy argmax; > 0 = sample from softmax(logits/T).
        top_k: with sampling, keep only the k highest logits (0 = no filter).
        stop_sequences: strings that end the turn; everything from the first stop match onward
            is cut. Default: the ``<|user|>`` / ``<|assistant|>`` / ``<|endofdoc|>`` markers.
        context_window: max prompt tokens fed to the model; longer transcripts are
            LEFT-truncated (keep the most recent tokens) — the running code-act transcript
            grows monotonically and the newest observations matter most.
        eos_id: token id that hard-stops decoding (cut, not included). Default: sniffed from
            ``tokenizer.eos_id`` / ``tokenizer.eos_token_id`` if present, else disabled.
            (`AvaTokenizer` exposes neither attribute — pass ``ava.tokenizer.EOS_ID`` explicitly.)
        seed: default RNG seed for sampling. Every ``generate`` call builds a fresh
            ``torch.Generator`` seeded with it, so identical calls are bit-deterministic.
            ``None`` = unseeded (nondeterministic sampling). Ignored by greedy decoding,
            which is deterministic by construction.
        forward_kwargs: extra kwargs forwarded to the model (e.g. ``{'task_type': 'deliberate'}``;
            AvaModel already defaults to that).
        device: where input ids are placed (default 'cpu').
    """

    def __init__(
        self,
        model: Any,
        tokenizer: Any,
        *,
        max_new_tokens: int = 256,
        temperature: float = 0.0,
        top_k: int = 0,
        stop_sequences: Sequence[str] = DEFAULT_STOP_SEQUENCES,
        context_window: int = 1024,
        eos_id: Optional[int] = None,
        seed: Optional[int] = None,
        forward_kwargs: Optional[Dict[str, Any]] = None,
        device: str = "cpu",
    ) -> None:
        if model is None:
            raise ValueError(
                "TorchModelPolicy needs a real model (got None). The T13C.5 honest gate: this "
                "policy decodes from an actual checkpoint — build one with "
                "ava.model.build_model(AvaConfig.load(...)) and load real weights; do not stub "
                "turns. (An untrained model runs but emits noise — that is expected, not hidden.)"
            )
        if tokenizer is None:
            raise ValueError(
                "TorchModelPolicy needs a real tokenizer (got None) — any object with "
                "encode(str)->list[int] and decode(list[int])->str (AvaTokenizer qualifies)."
            )
        if max_new_tokens < 1:
            raise ValueError(f"max_new_tokens must be >= 1, got {max_new_tokens}")
        if temperature < 0.0:
            raise ValueError(f"temperature must be >= 0, got {temperature}")
        if context_window < 1:
            raise ValueError(f"context_window must be >= 1, got {context_window}")

        self.model = model
        self.tokenizer = tokenizer
        self.max_new_tokens = int(max_new_tokens)
        self.temperature = float(temperature)
        self.top_k = int(top_k)
        self.stop_sequences: Tuple[str, ...] = tuple(stop_sequences)
        self.context_window = int(context_window)
        self.seed = seed
        self.forward_kwargs = dict(forward_kwargs or {})
        self.device = device
        if eos_id is None:
            eos_id = getattr(tokenizer, "eos_id", None)
            if eos_id is None:
                eos_id = getattr(tokenizer, "eos_token_id", None)
        self.eos_id = int(eos_id) if eos_id is not None else None

        # Pre-encode each stop sequence once so decoding can match at the *id* level, which is
        # robust even when the tokenizer's decode() strips special tokens from the text.
        self._stop_id_seqs: List[List[int]] = []
        for s in self.stop_sequences:
            ids = list(self.tokenizer.encode(s))
            if ids:
                self._stop_id_seqs.append(ids)

    # -- Policy contract ----------------------------------------------------------
    def __call__(self, transcript: str) -> str:
        """`ava.rl.codeact_loop.Policy`: running transcript -> next assistant turn."""
        return self.generate(transcript)

    # -- decoding -----------------------------------------------------------------
    def generate(self, prompt: str, *, seed: Optional[int] = None) -> str:
        """Decode one assistant turn from `prompt`. `seed` overrides the constructor seed for
        this call only (sampling mode; greedy ignores it)."""
        prompt_ids = list(self.tokenizer.encode(prompt))
        gen = self._make_generator(self.seed if seed is None else seed)

        was_training = getattr(self.model, "training", False)
        if hasattr(self.model, "eval"):
            self.model.eval()
        try:
            new_ids = self._decode_ids(prompt_ids, gen)
        finally:
            if was_training and hasattr(self.model, "train"):
                self.model.train()

        text = self._decode_text(new_ids)
        return self._cut_at_stops(text)

    def _decode_ids(self, prompt_ids: List[int], gen: Optional[torch.Generator]) -> List[int]:
        ids = list(prompt_ids)
        new_ids: List[int] = []
        with torch.no_grad():
            for _ in range(self.max_new_tokens):
                window = ids[-self.context_window:]  # LEFT-truncate: keep most recent tokens
                x = torch.tensor([window], dtype=torch.long, device=self.device)
                logits = _extract_logits(self.model(input_ids=x, **self.forward_kwargs))[0]
                nxt = self._pick_token(logits, gen)
                if self.eos_id is not None and nxt == self.eos_id:
                    break                            # EOS is a stop, never part of the turn
                ids.append(nxt)
                new_ids.append(nxt)
                cut = self._match_stop_ids(new_ids)
                if cut is not None:
                    return new_ids[:cut]             # drop the matched stop marker itself
        return new_ids

    def _pick_token(self, logits: torch.Tensor, gen: Optional[torch.Generator]) -> int:
        if self.temperature == 0.0:
            return int(torch.argmax(logits).item())  # greedy: deterministic by construction
        logits = logits / self.temperature
        if self.top_k > 0 and self.top_k < logits.shape[-1]:
            kth = torch.topk(logits, self.top_k).values[-1]
            logits = logits.masked_fill(logits < kth, float("-inf"))
        # Sampling happens on CPU regardless of the model's device: the seeded generator is a CPU
        # generator (torch.multinomial requires generator/input device match), and drawing from a
        # CPU copy of the [V] prob vector keeps seeded decodes BIT-IDENTICAL across cpu/cuda runs
        # (per-token copy of 8192 floats — negligible next to the forward pass).
        probs = torch.softmax(logits.to(torch.float32), dim=-1).cpu()
        return int(torch.multinomial(probs, 1, generator=gen).item())

    def _match_stop_ids(self, new_ids: List[int]) -> Optional[int]:
        """If `new_ids` ends with a stop-id sequence, return the cut index (len minus match)."""
        for seq in self._stop_id_seqs:
            n = len(seq)
            if len(new_ids) >= n and new_ids[-n:] == seq:
                return len(new_ids) - n
        return None

    # -- text helpers -------------------------------------------------------------
    def _decode_text(self, ids: List[int]) -> str:
        try:
            # AvaTokenizer: keep specials so a stop marker mid-stream is still text-cuttable.
            return self.tokenizer.decode(ids, skip_special=False)
        except TypeError:
            return self.tokenizer.decode(ids)

    def _cut_at_stops(self, text: str) -> str:
        # Second line of defense at the TEXT level: a stop string produced by a token split
        # different from tokenizer.encode(stop) evades the id-level match; cut it here.
        cut = len(text)
        for s in self.stop_sequences:
            i = text.find(s)
            if i != -1:
                cut = min(cut, i)
        return text[:cut].strip()

    @staticmethod
    def _make_generator(seed: Optional[int]) -> Optional[torch.Generator]:
        if seed is None:
            return None
        g = torch.Generator(device="cpu")
        g.manual_seed(int(seed))
        return g
