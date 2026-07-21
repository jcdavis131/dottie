"""OCR-decompression objective + comprehension probe (specs/12 items 2 & 4).

The optical arm of the model reads a *rendered page image* in place of the
text tokens it depicts (pxpipe: 512x512 monospace pages -> 1024-dim patch
vectors; see ava/pipeline/pxpipe.py and DeepSeek-OCR's "Contexts Optical
Compression", arXiv 2510.18234). Two supervision signals live here:

  * ``ocr_decompress_loss`` -- the *decompression* pretext: forward the model
    with the page as an IMAGE prefix and the same span as text tokens, then
    next-token cross-entropy on the text. Low loss means the model can read
    its own rendered pixels back out as tokens, i.e. the vision tokens really
    carry the characters. This is a plain LM loss over ``lm_logits`` and adds
    NOTHING to the default (text-only) forward path -- callers that never
    render pages never touch it.

  * ``comprehension_probe`` -- the specs/12 *amended eval gate*. Char-level
    OCR accuracy rewards a model that photocopies pixels without understanding
    them; the gate we actually care about is whether a computed fact rendered
    into a page can be *answered* from that page. So we render a wiki atlas to
    patches, ask "What is the <field> of <name>?" with the atlas supplied only
    as image, greedy-decode a short answer, and score containment of the
    ground-truth number. Comprehension over the rendered page, not transcription.

Nothing in this module imports or mutates model state; it only *calls* a model
that already honors the vision-prefix contract:
``forward(images=[B,N,1024], input_ids=[B,L], task_type=...) -> {"lm_logits": [B, L, V], ...}``.
"""

from __future__ import annotations

import re

import numpy as np
import torch
import torch.nn.functional as F

from dottie.pipeline import pxpipe

__all__ = ["comprehension_probe", "ocr_decompress_loss", "render_window"]


# ---------------------------------------------------------------------------
# 1. OCR-decompression loss
# ---------------------------------------------------------------------------


def _as_tensor_patches(patches, batch: int) -> torch.Tensor:
    """Coerce ``patches`` to a float32 tensor of shape [batch, N, 1024].

    Accepts an unbatched page stack ``[N, 1024]`` (expanded to every row of
    the text batch, since one rendered window prefixes one text span) or an
    already-batched ``[B, N, 1024]`` (used as-is; B must equal ``batch``).
    """
    if not torch.is_tensor(patches):
        patches = torch.as_tensor(np.asarray(patches))
    patches = patches.to(torch.float32)
    if patches.dim() == 2:  # [N, 1024] -> [B, N, 1024]
        patches = patches.unsqueeze(0).expand(batch, -1, -1)
    elif patches.dim() == 3:  # [B, N, 1024]
        if patches.shape[0] != batch:
            raise ValueError(
                f"batched patches B={patches.shape[0]} != input_ids B={batch}"
            )
    else:
        raise ValueError(
            f"patches must be [N,1024] or [B,N,1024], got {tuple(patches.shape)}"
        )
    return patches


def ocr_decompress_loss(model, input_ids, patches) -> torch.Tensor:
    """Next-token CE on the text tokens with the page supplied as image prefix.

    ``input_ids``: LongTensor/list, ``[L]`` or ``[B, L]``.
    ``patches``:   the rendered window, ``[N, 1024]`` or ``[B, N, 1024]``
                   (float patch vectors from pxpipe.render_to_patches).

    Returns a scalar tensor. Standard causal shift: predict token t+1 from the
    prefix up to t. Per the vision-prefix contract the model's ``lm_logits``
    are aligned to the *text* positions ([B, L_text, V]), so the shift is the
    ordinary one -- the image contributes through the forward, not by adding
    rows to the logit sequence.
    """
    if not torch.is_tensor(input_ids):
        input_ids = torch.as_tensor(input_ids, dtype=torch.long)
    input_ids = input_ids.long()
    if input_ids.dim() == 1:
        input_ids = input_ids.unsqueeze(0)  # [L] -> [1, L]
    B, L = input_ids.shape
    if L < 2:
        raise ValueError("need at least 2 text tokens to form a next-token target")

    images = _as_tensor_patches(patches, B)
    out = model(images=images, input_ids=input_ids)
    logits = out["lm_logits"]  # [B, L, V]
    V = logits.shape[-1]

    shift_logits = logits[:, :-1, :].reshape(-1, V)
    shift_labels = input_ids[:, 1:].reshape(-1)
    return F.cross_entropy(shift_logits, shift_labels)


# ---------------------------------------------------------------------------
# 2. render_window -- thin wrapper over the pxpipe render step
# ---------------------------------------------------------------------------


def render_window(text: str, max_pages: int = 4) -> np.ndarray:
    """Render ``text`` to the model-ready optical form: [n_vision_tokens, 1024]
    float32 in [0,1].

    A thin re-export of ``pxpipe.render_to_patches`` so the OCR objective and
    the eval gate share one entry point (and one place to change geometry).
    Keeps pxpipe's ``crop=True`` default: trailing blank patch-rows are dropped
    so a sparse page does not cost the full 256 vision tokens.
    """
    return pxpipe.render_to_patches(text, max_pages=max_pages)


# ---------------------------------------------------------------------------
# 3. comprehension_probe -- the specs/12 amended eval gate
# ---------------------------------------------------------------------------

# Computed facts on a WikiGenerator planet page render as, e.g.:
#   "Type: rocky planet. Orbit: 0.35 AU. Period: 0.21 yr. Radius: 1.2 R_earth.
#    Equilibrium temperature: 290 K. Moons: 2."
# Each pattern captures the numeric answer; the human-readable field name is the
# question phrasing. Concept/index/log pages use a different "(0.35 AU, 2 moons)"
# shape that intentionally does NOT match, so facts bind only to planet pages.
_FACT_PATTERNS = (
    ("orbit", re.compile(r"Orbit:\s*([0-9]+(?:\.[0-9]+)?)\s*AU")),
    ("period", re.compile(r"Period:\s*([0-9]+(?:\.[0-9]+)?)\s*yr")),
    (
        "equilibrium temperature",
        re.compile(r"Equilibrium temperature:\s*([0-9]+(?:\.[0-9]+)?)\s*K"),
    ),
    ("moons", re.compile(r"Moons:\s*([0-9]+)")),
)
_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _parse_facts(atlas_text: str) -> list[dict]:
    """Extract (name, field, value) facts, each tied to the nearest preceding
    ``# <name>`` heading. Document order is preserved so sampling is
    deterministic."""
    headings = [(m.start(), m.group(1).strip()) for m in _HEADING.finditer(atlas_text)]
    head_pos = [h[0] for h in headings]

    def name_for(pos: int) -> str | None:
        # rightmost heading whose start is <= pos
        lo, hi = 0, len(head_pos)
        while lo < hi:
            mid = (lo + hi) // 2
            if head_pos[mid] <= pos:
                lo = mid + 1
            else:
                hi = mid
        return headings[lo - 1][1] if lo > 0 else None

    facts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for field, pat in _FACT_PATTERNS:
        for m in pat.finditer(atlas_text):
            name = name_for(m.start())
            if name is None:
                continue
            key = (name, field)
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                {"name": name, "field": field, "value": m.group(1), "pos": m.start()}
            )
    facts.sort(key=lambda f: f["pos"])  # restore document order
    return facts


@torch.no_grad()
def _greedy_decode(
    model, tok, patches: torch.Tensor, prompt_ids: list[int], max_new: int = 8
) -> str:
    """Greedy-decode <=``max_new`` tokens conditioned on the image prefix and
    the prompt; return the decoded *continuation* only."""
    ids = list(prompt_ids)
    new_ids: list[int] = []
    for _ in range(max_new):
        input_ids = torch.tensor([ids], dtype=torch.long)
        out = model(images=patches, input_ids=input_ids)
        nxt = int(out["lm_logits"][0, -1].argmax().item())
        ids.append(nxt)
        new_ids.append(nxt)
    return tok.decode(new_ids)


def comprehension_probe(model, tok, atlas_text: str, max_questions: int = 4) -> dict:
    """Score reading comprehension over a rendered wiki atlas (specs/12 gate).

    Renders ``atlas_text`` to patches ONCE, then for up to ``max_questions``
    computed facts asks "What is the <field> of <name>?" with the atlas given
    only as an image prefix, greedy-decodes a short answer, and scores exact
    containment of the ground-truth number in the decoded string.

    ``tok`` needs only ``.encode(str) -> list[int]`` and ``.decode(list[int])
    -> str``. Returns ``{"score": float in [0,1], "n": int}``; ``score`` is 0.0
    when no facts are found (``n == 0``).
    """
    facts = _parse_facts(atlas_text)[:max_questions]
    n = len(facts)
    if n == 0:
        return {"score": 0.0, "n": 0}

    patches_np = render_window(atlas_text)
    patches = torch.as_tensor(patches_np, dtype=torch.float32).unsqueeze(
        0
    )  # [1, N, 1024]

    hits = 0
    for fact in facts:
        prompt = f"Q: What is the {fact['field']} of {fact['name']}?\nA:"
        prompt_ids = list(tok.encode(prompt))
        decoded = _greedy_decode(model, tok, patches, prompt_ids)
        if fact["value"] in decoded:
            hits += 1
    return {"score": hits / n, "n": n}
