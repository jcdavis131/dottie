"""pxpipe: deterministic text -> page-image rendering for optical training.

The technique (after teamchong/pxpipe and DeepSeek-OCR's "Contexts Optical
Compression", arXiv 2510.18234): dense text is rendered onto fixed-geometry
monospace page images, and the model reads the *image* -- N vision tokens
standing in for k*N text tokens. DeepSeek-OCR reports ~97% decoding precision
at <10x compression. pxpipe itself is TypeScript and proxy-shaped, so this
module reimplements the render step in ~150 lines of numpy with a vendored
public-domain 8x8 bitmap font (ava/pipeline/_font8x8.py).

Two properties this data plane depends on:

* **Pure function of text.** No RNG, no fonts from the OS, no PIL (whose
  default font changes across versions). Same string -> same bytes, forever.
  That means page images are NEVER stored or shipped through the shard
  pipeline: the trainer re-renders on demand from the packed text. Zero new
  storage formats, zero sidecar files, zero curator changes.

* **Patch geometry matches the model.** Pages are 512x512 grayscale, split
  into 32x32 patches -> 256 patches/page, each flattened to a 1024-dim
  vector: exactly the input dimension of model_1b.VisionEncoder
  (nn.Linear(1024, d_model)). A page carries 64x64 = 4096 characters, so one
  vision token stands for 16 rendered characters (~4 BPE tokens of this
  tokenizer): ~4x optical compression at nano/mini scale, before any learned
  conv compressor.

Layout metadata (line bounding boxes) is returned alongside pixels so later
curriculum can add DeepSeek-style visual primitives -- pointing at the line
that answers a question -- without re-plumbing anything.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from dottie.pipeline._font8x8 import FONT8X8_BASIC

GLYPH = 8  # font cell, px
PAGE_SIDE = 512  # page, px
COLS = PAGE_SIDE // GLYPH  # 64 chars per line
ROWS = PAGE_SIDE // GLYPH  # 64 lines per page
CHARS_PER_PAGE = COLS * ROWS  # 4096
PATCH = 32  # px; 32*32 = 1024 = VisionEncoder input dim
GRID = PAGE_SIDE // PATCH  # 16
PATCHES_PER_PAGE = GRID * GRID  # 256 vision tokens per page
PATCH_DIM = PATCH * PATCH  # 1024

_INK, _PAPER = 0, 255

# Pre-render the font into a [128, 8, 8] uint8 mask once at import.
_GLYPHS = np.zeros((128, GLYPH, GLYPH), dtype=np.uint8)
for _c, _rows in enumerate(FONT8X8_BASIC):
    for _y, _b in enumerate(_rows):
        for _x in range(GLYPH):
            if (_b >> _x) & 1:  # LSB = leftmost pixel
                _GLYPHS[_c, _y, _x] = 1


@dataclasses.dataclass(frozen=True)
class Page:
    pixels: np.ndarray  # [PAGE_SIDE, PAGE_SIDE] uint8, ink=0 paper=255
    n_chars: int  # characters actually rendered on this page
    line_boxes: tuple  # ((row_px, col_px, w_px, text), ...) per line


def _wrap(text: str) -> list[str]:
    """Hard-wrap to COLS, preserving explicit newlines; tabs -> 4 spaces,
    non-ASCII -> '?' (the tokenizer corpus is ASCII-dominant)."""
    lines: list[str] = []
    for raw in text.replace("\t", "    ").split("\n"):
        raw = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in raw)
        if not raw:
            lines.append("")
            continue
        while raw:
            lines.append(raw[:COLS])
            raw = raw[COLS:]
    return lines


def render_pages(text: str, max_pages: int | None = None) -> list[Page]:
    """Render text onto as many 512x512 pages as it needs (or max_pages)."""
    if not text.strip():
        return []
    lines = _wrap(text)
    pages: list[Page] = []
    for start in range(0, len(lines), ROWS):
        if max_pages is not None and len(pages) >= max_pages:
            break
        chunk = lines[start : start + ROWS]
        px = np.full((PAGE_SIDE, PAGE_SIDE), _PAPER, dtype=np.uint8)
        boxes = []
        n_chars = 0
        for row, line in enumerate(chunk):
            y = row * GLYPH
            for col, ch in enumerate(line):
                g = _GLYPHS[ord(ch)]
                x = col * GLYPH
                px[y : y + GLYPH, x : x + GLYPH][g == 1] = _INK
            if line.strip():
                boxes.append((y, 0, len(line) * GLYPH, line))
            n_chars += len(line)
        pages.append(Page(pixels=px, n_chars=n_chars, line_boxes=tuple(boxes)))
    return pages


def page_to_patches(page: Page) -> np.ndarray:
    """[PATCHES_PER_PAGE, PATCH_DIM] float32 in [0,1], ink=1 paper=0.

    Row-major patch order (top-left to bottom-right), so patch index k sits at
    grid (k // GRID, k % GRID) -- the positional convention the vision-prefix
    training objective assumes.
    """
    inv = (255 - page.pixels).astype(np.float32) / 255.0
    p = inv.reshape(GRID, PATCH, GRID, PATCH).transpose(0, 2, 1, 3)
    return p.reshape(PATCHES_PER_PAGE, PATCH_DIM)


def render_to_patches(text: str, max_pages: int = 4, crop: bool = True) -> np.ndarray:
    """[n_vision_tokens, 1024] float32 -- the model-ready optical form.

    crop=True drops each page's trailing blank patch-rows (a patch-row is 16
    patches covering 4 text lines): a sparse page must not cost the full 256
    vision tokens, or short docs would be LESS efficient than plain text
    (measured 0.42x on a 429-char entity page before cropping). Dense packed
    windows still fill whole pages, so their 4x ratio is unaffected.
    """
    pages = render_pages(text, max_pages=max_pages)
    if not pages:
        return np.zeros((0, PATCH_DIM), dtype=np.float32)
    outs = []
    for p in pages:
        patches = page_to_patches(p)
        if crop:
            used = patches.reshape(GRID, GRID, PATCH_DIM).max(axis=(1, 2)) > 0
            n_rows = int(np.nonzero(used)[0].max()) + 1 if used.any() else 0
            patches = patches[: n_rows * GRID]
        outs.append(patches)
    return np.concatenate(outs, axis=0)


def compression_stats(text: str, text_tokens: int | None = None) -> dict:
    """Measured optical-compression numbers for `text`.

    `text_tokens`: pass the real BPE count when a tokenizer is on hand;
    otherwise estimated at 4 chars/token (this corpus averages ~4.0).
    """
    pages = render_pages(text)
    vision_tokens = len(pages) * PATCHES_PER_PAGE
    n_chars = len(text)
    est_tokens = text_tokens if text_tokens is not None else max(1, round(n_chars / 4))
    return {
        "chars": n_chars,
        "pages": len(pages),
        "vision_tokens": vision_tokens,
        "chars_per_vision_token": round(n_chars / max(1, vision_tokens), 2),
        "text_tokens": est_tokens,
        "compression_ratio": round(est_tokens / max(1, vision_tokens), 2),
    }
