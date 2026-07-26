# Solo personal project, no connection to employer, built with public/free-tier only
"""A11y — static WCAG 2.x checker over LOCAL html (openswap #25: Siteimprove).

Everything deterministic lives here: the html.parser fact extractor (images,
headings, form controls, labels, landmarks, ids, styled text runs), the WCAG
2.x contrast arithmetic (sRGB relative luminance -> ratio -> AA/AAA thresholds
with the large-text rule), the tiny inline/root CSS resolver that feeds it, and
the rule pass that maps facts onto the family diagnostic schema. The plugin CLI
owns the ONE real I/O call (reading a local file) and nothing else.

Zero network on every path — Siteimprove's whole architecture is "point our
crawler at your site and we will tell you"; deleting the crawler IS the product,
so the manifest disables the network axis and the checker only ever reads files
you already have. That also means the scope is honestly narrower than a headless
browser: no layout, no cascade, no JavaScript.

WHY THIS IS NOT PART OF `seo` (#3), whose docstring nominates a11y as an
extension point: the two audits differ on their input axis, not just their rules.
`seo` is a NETWORK crawler with a resumable sqlite frontier and a
network-enabled manifest; this adapter reads local files with the network axis
switched off, which is the guarantee being sold. Of the five checks here only
"is there an alt attribute" touches seo at all, and seo's rule is a per-page
COUNT for a Screaming Frog export (`seo:img-alt`) while this one is a per-image
WCAG 1.1.1 verdict that honours role=presentation, aria-hidden and placeholder
alt text. The two overlaps that would have been duplicates are deliberately NOT
implemented here and say so at their rule sites: single-h1 (an SEO rule, not a
WCAG one — heading ORDER is what 1.3.1 asks for) and page <title> (WCAG 2.4.2,
already covered by `seo:title-missing`). HTML_EXTS is DERIVED from seo, not
retyped, because extension-list drift between modules is a known bug class in
this repo.

Honesty rules that shape the code:
- A contrast reading has EITHER `ratio` OR `error`, never both, never neither.
  There is no default backdrop: if no ancestor and no root rule declares a
  background, the reading is an ERROR naming that fact. Assuming white would
  invent a number, and a fabricated pass is worse than a stated unknown.
- The CSS understood is inline `style` attributes plus the `html`/`:root`/`body`
  rules of `<style>` blocks. Class/descendant selectors, @media/@supports blocks,
  linked stylesheets and JS-applied styles are OUT OF SCOPE and produce
  `a11y:contrast-unknown` with the reason, never a guess.
- Hidden subtrees (`hidden`, `aria-hidden=true`, `display:none`,
  `visibility:hidden`) are skipped and COUNTED, so "0 findings" can be
  distinguished from "nothing was looked at".
- UA defaults for h1-h6/small/b/strong/th sizes and weights are applied so the
  large-text threshold is right on unstyled headings; every reading carries
  `font_source` so a threshold resting on a UA default is visible, not implied.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from bigbang.core import openswap, seo

# Derived, never retyped: a divergent extension list between core modules is
# exactly how links #4's DOC_EXTS drifted from seo.HTML_EXTS. Directory walks
# use this; an explicitly named file is checked whatever its extension.
HTML_EXTS = seo.HTML_EXTS

# ---- WCAG 2.x constants -----------------------------------------------------

# The threshold printed in the WCAG 2.x relative-luminance formula itself. The
# mathematically continuous value is 0.04045; the normative text says 0.03928
# and this is a conformance checker, so it follows the text.
SRGB_THRESHOLD = 0.03928
AA_NORMAL = 4.5
AA_LARGE = 3.0
AAA_NORMAL = 7.0
AAA_LARGE = 4.5
# WCAG "large scale" = 18pt, or 14pt bold, at the 96dpi CSS reference pixel.
LARGE_PX = 24.0
LARGE_BOLD_PX = 18.66
ROOT_FONT_PX = 16.0
# Float noise only: a ratio that lands exactly on 3.0 or 4.5 must pass, but a
# ratio of 4.4999 must NOT be rounded up into a pass (WCAG is explicit).
_EPSILON = 1e-9

LEVELS = ("AA", "AAA")

# The CSS Level-1/2 keyword set that actually turns up in hand-written markup.
# A keyword outside it is reported unknown rather than guessed.
NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "silver": (192, 192, 192),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "white": (255, 255, 255),
    "maroon": (128, 0, 0),
    "red": (255, 0, 0),
    "purple": (128, 0, 128),
    "fuchsia": (255, 0, 255),
    "magenta": (255, 0, 255),
    "green": (0, 128, 0),
    "lime": (0, 255, 0),
    "olive": (128, 128, 0),
    "yellow": (255, 255, 0),
    "navy": (0, 0, 128),
    "blue": (0, 0, 255),
    "teal": (0, 128, 128),
    "aqua": (0, 255, 255),
    "cyan": (0, 255, 255),
    "orange": (255, 165, 0),
}

_HEX_RE = re.compile(r"^[0-9a-f]+$")
_FUNC_RE = re.compile(r"^rgba?\((.*)\)$", re.S)
_NUM_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)$")
_LENGTH_RE = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+))([a-z%]*)$")
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


# ---- color parsing ----------------------------------------------------------


def _parse_hex(digits: str) -> tuple[int, int, int, float] | None:
    d = digits.strip()
    if not _HEX_RE.match(d) or len(d) not in (3, 4, 6, 8):
        return None
    if len(d) in (3, 4):
        vals = [int(c, 16) * 17 for c in d]
    else:
        vals = [int(d[i : i + 2], 16) for i in range(0, len(d), 2)]
    if len(vals) == 3:
        return (vals[0], vals[1], vals[2], 1.0)
    return (vals[0], vals[1], vals[2], vals[3] / 255.0)


def _num(token: str, *, scale: float) -> float | None:
    """One numeric color component: a percentage of `scale`, or a raw number."""
    t = token.strip()
    if t.endswith("%"):
        head = t[:-1].strip()
        return float(head) / 100.0 * scale if _NUM_RE.match(head) else None
    return float(t) if _NUM_RE.match(t) else None


def _parse_rgb_func(body: str) -> tuple[int, int, int, float] | None:
    head, _, tail = body.partition("/")  # modern rgb(r g b / a) syntax
    parts = [p for p in re.split(r"[,\s]+", head.strip()) if p]
    alpha_token = tail.strip() or None
    if alpha_token is None and len(parts) == 4:  # legacy rgba(r, g, b, a)
        alpha_token = parts.pop()
    if len(parts) != 3:
        return None
    chans: list[float] = []
    for part in parts:
        channel = _num(part, scale=255.0)
        if channel is None:
            return None
        chans.append(channel)
    alpha = 1.0
    if alpha_token is not None:
        a = _num(alpha_token, scale=1.0)
        if a is None:
            return None
        alpha = min(1.0, max(0.0, a))
    r, g, b = (round(min(255.0, max(0.0, c))) for c in chans)
    return (r, g, b, alpha)


def parse_color(value: str | None) -> tuple[int, int, int, float] | None:
    """(r, g, b, alpha) for a CSS color, or None when this core cannot resolve it.

    None is a real answer meaning "unknown" — callers must record WHY rather
    than substituting a default, because a guessed color invents a ratio.
    `transparent` parses to alpha 0.0, which callers treat as "keeps whatever is
    behind it", not as a backdrop of its own.
    """
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if not v:
        return None
    if v == "transparent":
        return (0, 0, 0, 0.0)
    if v in NAMED_COLORS:
        r, g, b = NAMED_COLORS[v]
        return (r, g, b, 1.0)
    if v.startswith("#"):
        return _parse_hex(v[1:])
    m = _FUNC_RE.match(v)
    return _parse_rgb_func(m.group(1)) if m else None


def first_color_token(value: str | None) -> str | None:
    """First whitespace-separated token of a shorthand that IS a color.

    `background: #fff url(x.png) no-repeat` -> "#fff". Returns None when no
    token is a color, so the caller can report the declaration as unresolved
    instead of pretending the element has no background at all.
    """
    if not value:
        return None
    raw = value.strip()
    if parse_color(raw) is not None:  # whole value (handles "rgb(1, 2, 3)")
        return raw
    for token in raw.split():
        if parse_color(token) is not None:
            return token
    return None


# ---- WCAG arithmetic --------------------------------------------------------


def channel_luminance(component: float) -> float:
    """One 0-255 sRGB channel -> its linear-light value (WCAG 2.x formula)."""
    c = component / 255.0
    if c <= SRGB_THRESHOLD:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(
    rgb: tuple[int, int, int] | tuple[int, int, int, float],
) -> float:
    """WCAG relative luminance of an opaque sRGB triple."""
    r, g, b = rgb[0], rgb[1], rgb[2]
    return (
        0.2126 * channel_luminance(r)
        + 0.7152 * channel_luminance(g)
        + 0.0722 * channel_luminance(b)
    )


def contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    """(L_lighter + 0.05) / (L_darker + 0.05) — symmetric, 1.0 .. 21.0."""
    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    if l2 > l1:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def is_large_text(font_px: float | None, bold: bool) -> bool:
    """WCAG "large scale": >= 24px, or >= 18.66px when bold."""
    if font_px is None:
        return False  # undeclared size is judged at the stricter normal threshold
    return font_px >= (LARGE_BOLD_PX if bold else LARGE_PX)


def required_ratio(large: bool, level: str = "AA") -> float:
    """The minimum ratio for a text size at a conformance level."""
    lv = level.upper()
    if lv not in LEVELS:
        raise ValueError(f"level must be one of {'|'.join(LEVELS)}, got {level!r}")
    if lv == "AAA":
        return AAA_LARGE if large else AAA_NORMAL
    return AA_LARGE if large else AA_NORMAL


def _color_problem(value: str | None, role: str) -> str | None:
    """Why `value` cannot become an opaque color, or None when it can."""
    if not value or not value.strip():
        return f"{role} color is not declared on the element or any ancestor"
    raw = value.strip()
    parsed = parse_color(raw)
    if parsed is None:
        if "url(" in raw.lower():
            return (
                f"{role} is an image ({raw[:60]}): contrast over an image cannot be"
                " computed statically"
            )
        return f"{role} color {raw[:60]!r} is not a hex/rgb/keyword color this core resolves"
    if parsed[3] == 0.0:
        return f"{role} color {raw[:60]!r} is fully transparent"
    if parsed[3] < 1.0:
        return (
            f"{role} color {raw[:60]!r} has alpha {parsed[3]:.3g}, so the composited"
            " color needs the rendered backdrop"
        )
    return None


def contrast_reading(
    fg: str | None,
    bg: str | None,
    *,
    font_px: float | None = None,
    bold: bool = False,
    font_source: str = "declared",
) -> dict[str, Any]:
    """One contrast reading: EITHER `ratio` OR `error`, never both, never neither.

    `ratio` is rounded to 2dp for display only; the AA/AAA verdicts use the
    unrounded value, because WCAG forbids rounding a near-miss up into a pass.
    """
    large = is_large_text(font_px, bold)
    reading: dict[str, Any] = {
        "fg": fg,
        "bg": bg,
        "font_px": font_px,
        "font_source": font_source,
        "bold": bold,
        "large": large,
        "required_aa": required_ratio(large, "AA"),
        "required_aaa": required_ratio(large, "AAA"),
        "ratio": None,
        "passes_aa": None,
        "passes_aaa": None,
        "error": None,
    }
    problem = _color_problem(fg, "foreground") or _color_problem(bg, "background")
    if problem is not None:
        reading["error"] = problem
        return reading
    fg_rgb = parse_color(fg)
    bg_rgb = parse_color(bg)
    if fg_rgb is None or bg_rgb is None:  # _color_problem proved both resolvable
        reading["error"] = (
            "color resolution disagreed with validation, so no ratio is reported"
        )
        return reading
    ratio = contrast_ratio(
        (fg_rgb[0], fg_rgb[1], fg_rgb[2]), (bg_rgb[0], bg_rgb[1], bg_rgb[2])
    )
    reading["ratio"] = round(ratio, 2)
    reading["passes_aa"] = ratio + _EPSILON >= reading["required_aa"]
    reading["passes_aaa"] = ratio + _EPSILON >= reading["required_aaa"]
    return reading


# ---- the (deliberately tiny) CSS resolver -----------------------------------


def parse_declarations(style: str | None) -> dict[str, str]:
    """Declarations of ONE inline style attribute; later duplicates win."""
    out: dict[str, str] = {}
    for chunk in (style or "").split(";"):
        if ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        key = prop.strip().lower()
        if key:
            out[key] = value.strip()
    return out


def iter_rules(css: str) -> list[tuple[str, str, int]]:
    """(selector, declarations, at_depth) for every rule in a stylesheet.

    Not a CSS parser — a brace scanner. `at_depth > 0` means the rule sits
    inside an @media/@supports block, which this core refuses to resolve
    (the effective value depends on the rendering context) rather than
    applying unconditionally and reporting a ratio that may not be on screen.
    """
    text = _COMMENT_RE.sub("", css or "")
    rules: list[tuple[str, str, int]] = []
    buf: list[str] = []
    at_depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "{":
            selector = "".join(buf).strip()
            buf = []
            if selector.startswith("@"):
                at_depth += 1
                i += 1
                continue
            j = i + 1
            while j < n and text[j] not in "{}":
                j += 1
            rules.append((selector, text[i + 1 : j], at_depth))
            i = j + 1 if j < n and text[j] == "}" else j
            continue
        if ch == "}":
            if at_depth:
                at_depth -= 1
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    return rules


ROOT_SELECTORS = ("html", ":root", "body")


def root_style(css: str) -> dict[str, Any]:
    """Document-root declarations only, plus the props this core refuses to resolve.

    Returns {"declarations": {...}, "conditional": [props]}. A root property set
    inside an @-block lands in `conditional` and is NOT applied: a dark-mode
    body background is a different backdrop, and picking one would fabricate the
    verdict for whichever mode the reader is not in.
    """
    decls: dict[str, str] = {}
    conditional: set[str] = set()
    for selector, body, at_depth in iter_rules(css):
        parts = [s.strip().lower() for s in selector.split(",")]
        if not any(p in ROOT_SELECTORS for p in parts):
            continue
        found = parse_declarations(body)
        if at_depth:
            conditional.update(found)
        else:
            decls.update(found)
    return {"declarations": decls, "conditional": sorted(conditional)}


# UA defaults from the HTML rendering spec, so an unstyled <h1> is judged at the
# LARGE threshold (32px) instead of the normal one. A reset stylesheet this core
# cannot read would change them — hence `font_source` on every reading.
_UA_FONT_EM = {
    "h1": 2.0,
    "h2": 1.5,
    "h3": 1.17,
    "h4": 1.0,
    "h5": 0.83,
    "h6": 0.67,
    "small": 0.8125,
    "big": 1.2,
}
_UA_BOLD_TAGS = frozenset(
    {"b", "strong", "th", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "summary"}
)
_ABSOLUTE_SIZES = {
    "xx-small": 9.0,
    "x-small": 10.0,
    "small": 13.0,
    "medium": 16.0,
    "large": 18.0,
    "x-large": 24.0,
    "xx-large": 32.0,
}
_UNIT_PX = {
    "px": 1.0,
    "pt": 4.0 / 3.0,
    "pc": 16.0,
    "in": 96.0,
    "cm": 96.0 / 2.54,
    "mm": 96.0 / 25.4,
}


def parse_font_size(
    value: str | None, *, parent_px: float | None = None, root_px: float = ROOT_FONT_PX
) -> float | None:
    """A CSS font-size -> px, or None when it is not resolvable here."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if v in _ABSOLUTE_SIZES:
        return _ABSOLUTE_SIZES[v]
    base = parent_px if parent_px is not None else root_px
    if v == "smaller":
        return base / 1.2
    if v == "larger":
        return base * 1.2
    m = _LENGTH_RE.match(v)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    if num < 0:
        return None  # a negative font-size is invalid CSS, not a small font
    if not unit:
        return 0.0 if num == 0 else None  # unitless non-zero lengths are invalid
    if unit in _UNIT_PX:
        return num * _UNIT_PX[unit]
    if unit == "rem":
        return num * root_px
    if unit == "em":
        return num * base
    if unit == "%":
        return base * num / 100.0
    return None


def parse_font_weight(value: str | None) -> bool | None:
    """True/False for bold, or None when the declaration is not resolvable."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if v in ("bold", "bolder"):
        return True
    if v in ("normal", "lighter"):
        return False
    return float(v) >= 700.0 if _NUM_RE.match(v) else None


def _background_declaration(decls: dict[str, str]) -> str | None:
    """The later of `background` / `background-color` in one declaration block."""
    raw = None
    for prop, value in decls.items():
        if prop in ("background", "background-color"):
            raw = value
    return raw


# ---- fact extraction --------------------------------------------------------

VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
# ARIA landmark roles, and the elements that map onto them implicitly. `section`
# and `form` only become landmarks when they carry an accessible name, which is
# why they are handled separately rather than listed here.
LANDMARK_TAGS = {
    "main": "main",
    "nav": "navigation",
    "header": "banner",
    "footer": "contentinfo",
    "aside": "complementary",
    "search": "search",
}
NAMED_LANDMARK_TAGS = {"section": "region", "form": "form"}
LANDMARK_ROLES = frozenset(
    {
        "main",
        "navigation",
        "banner",
        "contentinfo",
        "complementary",
        "search",
        "form",
        "region",
    }
)
LABELABLE_TAGS = frozenset(
    {"input", "select", "textarea", "button", "meter", "progress"}
)
# UA-supplied labels: a submit/reset button reads as "Submit"/"Reset" with no
# author markup at all, so demanding a label would be a false positive.
UA_LABELED_INPUT_TYPES = frozenset({"submit", "reset"})
PRESENTATIONAL_ROLES = frozenset({"presentation", "none"})
_NON_TEXT_TAGS = frozenset({"script", "style", "title", "template", "noscript", "head"})
_TEXT_CAPTURE_TAGS = frozenset({*HEADING_TAGS, "label", "button"})
_GENERIC_ALT = frozenset(
    {
        "image",
        "images",
        "photo",
        "picture",
        "graphic",
        "icon",
        "logo",
        "img",
        "spacer",
        "untitled",
        "alt",
        "thumbnail",
        "banner",
    }
)
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif")


def _initial_context() -> dict[str, Any]:
    return {
        "color": None,
        "background": None,
        "font_px": ROOT_FONT_PX,
        "font_source": "initial",
        "bold": False,
        "hidden": False,
        "hidden_reason": None,
    }


def alt_is_generic(alt: str, src: str) -> tuple[bool, str | None]:
    """Does this alt text merely restate the file, or say nothing? (verdict, why)."""
    text = " ".join((alt or "").split())
    low = text.lower()
    if not low:
        return False, None  # alt="" is a deliberate decorative signal, not generic
    if low in _GENERIC_ALT:
        return True, f"alt={text!r} names a category, not the content"
    if low.endswith(_IMAGE_SUFFIXES):
        return True, f"alt={text!r} is a file name"
    name = (src or "").replace("\\", "/").rsplit("/", 1)[-1].split("?", 1)[0].lower()
    if name and low in (name, name.rsplit(".", 1)[0]):
        return True, f"alt={text!r} repeats the src file name"
    if low.isdigit():
        return True, f"alt={text!r} is a bare number"
    return False, None


class _DocParser(HTMLParser):
    """Tolerant single-pass fact extractor (html.parser never chokes on soup)."""

    def __init__(self, root: dict[str, Any] | None = None) -> None:
        super().__init__(convert_charrefs=True)
        rs = root or {"declarations": {}, "conditional": []}
        self.root_conditional: list[str] = list(rs.get("conditional") or [])
        self.css_parts: list[str] = []
        self.html_seen = False
        self.lang: str | None = None
        self.lang_line = 0
        self.images: list[dict[str, Any]] = []
        self.headings: list[dict[str, Any]] = []
        self.controls: list[dict[str, Any]] = []
        self.labels: list[dict[str, Any]] = []
        self.landmarks: list[dict[str, Any]] = []
        self.ids: dict[str, list[int]] = {}
        self.runs: dict[tuple, dict[str, Any]] = {}
        self.hidden_skipped = {
            "images": 0,
            "controls": 0,
            "headings": 0,
            "text_runs": 0,
        }
        self._root_px = ROOT_FONT_PX
        self._root_ctx = self._apply(
            _initial_context(), rs.get("declarations") or {}, tag=None
        )
        self._root_px = self._root_ctx["font_px"] or ROOT_FONT_PX
        self._stack: list[dict[str, Any]] = []
        self._capturing: list[dict[str, Any]] = []
        self._in_style = False

    # -- context -------------------------------------------------------------

    def _apply(
        self, ctx: dict[str, Any], decls: dict[str, str], *, tag: str | None
    ) -> dict[str, Any]:
        """Fold UA defaults then inline declarations onto an inherited context."""
        parent_px = ctx["font_px"]
        if tag in _UA_FONT_EM:
            ctx["font_px"] = round((parent_px or self._root_px) * _UA_FONT_EM[tag], 2)
            ctx["font_source"] = "ua-default"
        if tag in _UA_BOLD_TAGS:
            ctx["bold"] = True
        if "color" in decls and decls["color"].strip():
            ctx["color"] = first_color_token(decls["color"]) or decls["color"].strip()
        raw_bg = _background_declaration(decls)
        if raw_bg is not None and raw_bg.strip():
            token = first_color_token(raw_bg)
            parsed = parse_color(token) if token else None
            if parsed is not None and parsed[3] == 0.0:
                pass  # `transparent` shows the inherited backdrop, so keep it
            else:
                ctx["background"] = token or raw_bg.strip()
        if "font-size" in decls:
            px = parse_font_size(
                decls["font-size"], parent_px=parent_px, root_px=self._root_px
            )
            if px is not None:
                ctx["font_px"] = px
                ctx["font_source"] = "declared"
        if "font-weight" in decls:
            bold = parse_font_weight(decls["font-weight"])
            if bold is not None:
                ctx["bold"] = bold
        return ctx

    def _context_for(self, tag: str, attrs: dict[str, str]) -> dict[str, Any]:
        parent = self._stack[-1] if self._stack else self._root_ctx
        ctx = {k: v for k, v in parent.items() if k != "tag"}
        decls = parse_declarations(attrs.get("style"))
        ctx = self._apply(ctx, decls, tag=tag)
        if not ctx["hidden"]:
            reason = None
            if "hidden" in attrs:
                reason = "hidden attribute"
            elif (attrs.get("aria-hidden") or "").strip().lower() == "true":
                reason = "aria-hidden=true"
            elif decls.get("display", "").strip().lower() == "none":
                reason = "display:none"
            elif decls.get("visibility", "").strip().lower() == "hidden":
                reason = "visibility:hidden"
            if reason:
                ctx["hidden"] = True
                ctx["hidden_reason"] = reason
        return ctx

    # -- tags ----------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list) -> None:
        line, offset = self.getpos()
        col = offset + 1
        a: dict[str, str] = {}
        for key, value in attrs:
            k = (key or "").strip().lower()
            if k and k not in a:  # first occurrence wins, as browsers do
                a[k] = value if value is not None else ""
        ctx = self._context_for(tag, a)
        if tag == "style":
            self._in_style = True
        elif tag == "html":
            self.html_seen = True
            if self.lang is None:
                self.lang = (a.get("lang") or "").strip() or None
                self.lang_line = line
        if a.get("id", "").strip():
            self.ids.setdefault(a["id"].strip(), []).append(line)
        sink = self._record(tag, a, ctx, line, col)
        if tag in _TEXT_CAPTURE_TAGS:
            self._capturing.append(
                {
                    "tag": tag,
                    "line": line,
                    "col": col,
                    "parts": [],
                    "sink": sink,
                    "hidden": ctx["hidden"],
                }
            )
        if tag not in VOID_TAGS:
            self._stack.append({"tag": tag, **ctx})

    def _record(
        self, tag: str, a: dict[str, str], ctx: dict[str, Any], line: int, col: int
    ) -> dict[str, Any] | None:
        """Record this element's facts; return the record whose accessible NAME
        the text capture should fill in (None when the element has no name)."""
        role = (a.get("role") or "").strip().lower()
        sink: dict[str, Any] | None = None
        if tag == "img" or (
            tag == "input" and (a.get("type") or "").lower() == "image"
        ):
            self._record_image(tag, a, ctx, line, col, role)
        if tag in LABELABLE_TAGS:
            sink = self._record_control(tag, a, ctx, line, col)
        if tag == "label":
            sink = {
                "for": (a.get("for") or "").strip(),
                "line": line,
                "col": col,
                "wraps": 0,
                "text": "",
            }
            self.labels.append(sink)
        landmark = LANDMARK_TAGS.get(tag) or (role if role in LANDMARK_ROLES else None)
        if landmark is None and tag in NAMED_LANDMARK_TAGS:
            named = (a.get("aria-label") or a.get("aria-labelledby") or "").strip()
            landmark = NAMED_LANDMARK_TAGS[tag] if named else None
        if landmark:
            self.landmarks.append(
                {
                    "role": landmark,
                    "tag": tag,
                    "line": line,
                    "col": col,
                    "label": (a.get("aria-label") or "").strip(),
                    "hidden": ctx["hidden"],
                }
            )
        return sink

    def _record_image(
        self,
        tag: str,
        a: dict[str, str],
        ctx: dict[str, Any],
        line: int,
        col: int,
        role: str,
    ) -> None:
        if ctx["hidden"]:
            self.hidden_skipped["images"] += 1
            return
        alt = a.get("alt")
        if alt is not None and self._capturing:
            # an image inside a heading/label/button contributes its alt to that
            # element's accessible name, so an "empty" heading is not flagged
            for target in self._capturing:
                target["parts"].append(f" {alt} ")
        self.images.append(
            {
                "tag": tag,
                "src": (a.get("src") or "").strip(),
                "alt": alt,
                "line": line,
                "col": col,
                "presentational": role in PRESENTATIONAL_ROLES,
            }
        )

    def _record_control(
        self, tag: str, a: dict[str, str], ctx: dict[str, Any], line: int, col: int
    ) -> dict[str, Any] | None:
        ctype = (a.get("type") or "").strip().lower()
        if tag == "input" and ctype == "hidden":
            return None  # not exposed to anyone; a label would be meaningless
        if ctx["hidden"]:
            self.hidden_skipped["controls"] += 1
            return None
        wrapped = any(frame["tag"] == "label" for frame in self._stack)
        record = {
            "tag": tag,
            "type": ctype,
            "id": (a.get("id") or "").strip(),
            "name": (a.get("name") or "").strip(),
            "aria_label": (a.get("aria-label") or "").strip(),
            "aria_labelledby": (a.get("aria-labelledby") or "").strip(),
            "title": (a.get("title") or "").strip(),
            "alt": (a.get("alt") or "").strip(),
            "value": (a.get("value") or "").strip(),
            "placeholder": (a.get("placeholder") or "").strip(),
            "wrapped_by_label": wrapped,
            "text": "",
            "line": line,
            "col": col,
        }
        self.controls.append(record)
        if wrapped and self.labels:
            # the most recently opened label is the innermost one wrapping this
            # control, and wrapping is what makes a for-less label legitimate
            self.labels[-1]["wraps"] += 1
        return record if tag == "button" else None

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False
        if tag in _TEXT_CAPTURE_TAGS:
            self._close_capture(tag)
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]["tag"] == tag:
                del self._stack[i:]
                return

    def _close_capture(self, tag: str) -> None:
        """Finalize the innermost open capture for `tag`; drop unclosed inner ones."""
        for i in range(len(self._capturing) - 1, -1, -1):
            if self._capturing[i]["tag"] != tag:
                continue
            target = self._capturing[i]
            del self._capturing[i:]  # this frame plus any never-closed descendants
            text = " ".join("".join(target["parts"]).split())
            if tag in HEADING_TAGS:
                if target["hidden"]:
                    self.hidden_skipped["headings"] += 1
                else:
                    self.headings.append(
                        {
                            "level": int(tag[1]),
                            "text": text,
                            "line": target["line"],
                            "col": target["col"],
                        }
                    )
            elif target["sink"] is not None:
                target["sink"]["text"] = text
            return

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.css_parts.append(data)
            return
        for target in self._capturing:
            target["parts"].append(data)
        if not data.strip():
            return
        if any(f["tag"] in _NON_TEXT_TAGS for f in self._stack):
            return
        ctx = self._stack[-1] if self._stack else self._root_ctx
        if ctx["hidden"]:
            self.hidden_skipped["text_runs"] += 1
            return
        if ctx["color"] is None and ctx["background"] is None:
            return  # no authored color anywhere in the chain: nothing to audit
        key = (
            ctx["color"],
            ctx["background"],
            ctx["font_px"],
            ctx["bold"],
            ctx["font_source"],
        )
        line, offset = self.getpos()
        run = self.runs.get(key)
        if run is None:
            self.runs[key] = {
                "fg": ctx["color"],
                "bg": ctx["background"],
                "font_px": ctx["font_px"],
                "font_source": ctx["font_source"],
                "bold": ctx["bold"],
                "line": line,
                "col": offset + 1,
                "sample": " ".join(data.split())[:48],
                "count": 1,
            }
        else:
            run["count"] += 1


def parse_document(html_text: str) -> dict[str, Any]:
    """Every fact the rules need, from a tolerant html.parser pass (never raises).

    Two passes on purpose: a `<style>` block may appear AFTER the markup it
    styles, so the first pass exists only to collect stylesheets and the second
    runs with the root declarations already resolved.
    """
    errors: list[str] = []

    def feed(parser: _DocParser) -> _DocParser:
        try:
            parser.feed(html_text or "")
            parser.close()
        except Exception as e:  # tolerant by contract: soup must not kill a pass
            errors.append(f"{type(e).__name__}: {e}")
        return parser

    css = "".join(feed(_DocParser()).css_parts)
    root = root_style(css)
    p = feed(_DocParser(root=root))
    return {
        "lang": p.lang,
        "lang_line": p.lang_line,
        "html_seen": p.html_seen,
        "images": p.images,
        "headings": p.headings,
        "controls": p.controls,
        "labels": p.labels,
        "landmarks": p.landmarks,
        "ids": p.ids,
        "text_runs": sorted(p.runs.values(), key=lambda r: (r["line"], r["col"])),
        "hidden_skipped": p.hidden_skipped,
        "root_conditional": p.root_conditional,
        "stylesheet_bytes": len(css),
        "parse_error": errors[0] if errors else None,
    }


# ---- rules (policy-as-config) ----------------------------------------------

RULES: dict[str, dict[str, Any]] = {
    "a11y:html-lang-missing": {"enabled": True, "severity": "error", "wcag": "3.1.1"},
    "a11y:img-alt-missing": {"enabled": True, "severity": "error", "wcag": "1.1.1"},
    "a11y:img-alt-generic": {"enabled": True, "severity": "warning", "wcag": "1.1.1"},
    "a11y:control-unlabeled": {"enabled": True, "severity": "error", "wcag": "4.1.2"},
    "a11y:control-placeholder-only": {
        "enabled": True,
        "severity": "warning",
        "wcag": "3.3.2",
    },
    "a11y:label-orphan": {"enabled": True, "severity": "warning", "wcag": "1.3.1"},
    "a11y:duplicate-id": {"enabled": True, "severity": "warning", "wcag": "4.1.1"},
    "a11y:heading-empty": {"enabled": True, "severity": "warning", "wcag": "1.3.1"},
    "a11y:heading-first-not-h1": {
        "enabled": True,
        "severity": "warning",
        "wcag": "1.3.1",
    },
    "a11y:heading-skipped-level": {
        "enabled": True,
        "severity": "warning",
        "wcag": "1.3.1",
    },
    "a11y:heading-none": {"enabled": True, "severity": "suggestion", "wcag": "1.3.1"},
    "a11y:landmark-main-missing": {
        "enabled": True,
        "severity": "warning",
        "wcag": "1.3.6",
    },
    "a11y:landmark-main-multiple": {
        "enabled": True,
        "severity": "warning",
        "wcag": "1.3.6",
    },
    "a11y:contrast-aa": {"enabled": True, "severity": "error", "wcag": "1.4.3"},
    "a11y:contrast-aaa": {"enabled": True, "severity": "suggestion", "wcag": "1.4.6"},
    "a11y:contrast-unknown": {"enabled": True, "severity": "info", "wcag": "1.4.3"},
    # not a WCAG success criterion: a file that could not be READ has not been
    # audited, and it must never leave the pass/fail gate looking clean
    "a11y:file-unreadable": {"enabled": True, "severity": "error", "wcag": None},
}


def load_rules(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """RULES with an optional JSON overlay (org policy needs no code edit).

    Overlay shape: {"a11y:contrast-aaa": {"enabled": false}, ...}. An unknown
    rule id or a bad severity is a hard error — silently ignoring a typo in a
    policy file would mean shipping a gate that does not gate.
    """
    merged = {rid: dict(cfg) for rid, cfg in RULES.items()}
    if path is None:
        return merged
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("rules overlay must be a JSON object of rule -> settings")
    for rid, cfg in raw.items():
        if rid not in merged:
            raise ValueError(f"unknown rule id {rid!r} (see: scout a11y rules)")
        if not isinstance(cfg, dict):
            raise ValueError(f"rule {rid!r}: settings must be a JSON object")
        sev = cfg.get("severity")
        if sev is not None and sev not in openswap.SEVERITIES:
            raise ValueError(
                f"rule {rid!r}: severity must be one of {'|'.join(openswap.SEVERITIES)}"
            )
        merged[rid].update(cfg)
    return merged


def contrast_readings(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """One reading per distinct (color, background, size, weight) text style."""
    out = []
    for run in facts.get("text_runs") or []:
        reading = contrast_reading(
            run["fg"],
            run["bg"],
            font_px=run["font_px"],
            bold=run["bold"],
            font_source=run["font_source"],
        )
        reading.update(
            {
                "line": run["line"],
                "col": run["col"],
                "sample": run["sample"],
                "runs": run["count"],
            }
        )
        out.append(reading)
    return out


def _accessible_name(
    control: dict[str, Any], label_ids: set[str], ids: set[str]
) -> tuple[str | None, str | None]:
    """(source of the control's name, why the candidate source failed) — either
    the first component is a source name or the second explains the absence."""
    if control["aria_label"]:
        return "aria-label", None
    if control["aria_labelledby"]:
        targets = control["aria_labelledby"].split()
        missing = [t for t in targets if t not in ids]
        if missing:
            return None, f"aria-labelledby points at missing id(s) {', '.join(missing)}"
        return "aria-labelledby", None
    if control["id"] and control["id"] in label_ids:
        return "label[for]", None
    if control["wrapped_by_label"]:
        return "wrapping <label>", None
    if control["tag"] == "button" and (control["text"] or control["value"]):
        return "button text", None
    if control["tag"] == "input" and control["type"] in UA_LABELED_INPUT_TYPES:
        return "user-agent default", None
    if control["tag"] == "input" and control["type"] == "image" and control["alt"]:
        return "alt", None
    if control["type"] == "button" and control["value"]:
        return "value", None
    if control["title"]:
        return "title", None
    return None, None


def _describe(control: dict[str, Any]) -> str:
    bits = [control["tag"] + (f"[type={control['type']}]" if control["type"] else "")]
    if control["name"]:
        bits.append(f"name={control['name']}")
    elif control["id"]:
        bits.append(f"id={control['id']}")
    return " ".join(bits)


def audit_document(
    facts: dict[str, Any], *, path: str, rules: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Facts -> family diagnostics. Pure; every finding carries its WCAG SC."""
    rs = rules or load_rules()
    diags: list[dict[str, Any]] = []

    def add(
        rule: str,
        message: str,
        *,
        line: int = 0,
        col: int = 1,
        suggestion: str | None = None,
    ) -> None:
        cfg = rs.get(rule) or {}
        if not cfg.get("enabled", True):
            return
        sc = cfg.get("wcag")
        diags.append(
            openswap.diagnostic(
                path=path,
                line=line,
                col=col,
                rule=rule,
                severity=cfg.get("severity", "warning"),
                message=f"{message} (WCAG {sc})" if sc else message,
                suggestion=suggestion,
            )
        )

    _audit_document_structure(facts, add)
    _audit_images(facts, add)
    _audit_forms(facts, add)
    _audit_contrast(facts, add)
    return openswap.sort_diagnostics(diags)


def _audit_document_structure(facts: dict[str, Any], add: Any) -> None:
    # NOTE: page <title> (2.4.2) is deliberately NOT checked here — seo #3's
    # `seo:title-missing` already owns it, and a second rule for the same defect
    # would be a duplicate. Same for single-h1, which is an SEO rule; 1.3.1 asks
    # about heading ORDER, which is what this pass checks.
    if facts.get("html_seen") and not facts.get("lang"):
        add(
            "a11y:html-lang-missing",
            "<html> has no lang attribute, so a screen reader cannot pick a voice",
            line=facts.get("lang_line") or 0,
            suggestion='add lang="en" (or the document language) to <html>',
        )
    for element_id, lines in sorted(facts.get("ids", {}).items()):
        if len(lines) > 1:
            add(
                "a11y:duplicate-id",
                f"id={element_id!r} is used {len(lines)} times, so label[for] and"
                " aria-labelledby references are ambiguous",
                line=lines[1],
            )
    headings = facts.get("headings") or []
    if not headings:
        add(
            "a11y:heading-none",
            "no headings at all, so there is no outline to navigate by",
            suggestion="add an <h1> and section headings",
        )
    else:
        if headings[0]["level"] != 1:
            add(
                "a11y:heading-first-not-h1",
                f"first heading is h{headings[0]['level']}, not h1",
                line=headings[0]["line"],
                col=headings[0]["col"],
            )
        previous = headings[0]["level"]
        for heading in headings:
            if heading["level"] > previous + 1:
                add(
                    "a11y:heading-skipped-level",
                    f"h{previous} is followed by h{heading['level']},"
                    f" skipping h{previous + 1}",
                    line=heading["line"],
                    col=heading["col"],
                    suggestion=f"use h{previous + 1} or restructure the section",
                )
            previous = heading["level"]
        for heading in headings:
            if not heading["text"]:
                add(
                    "a11y:heading-empty",
                    f"h{heading['level']} has no text or image alt to announce",
                    line=heading["line"],
                    col=heading["col"],
                )
    mains = [lm for lm in facts.get("landmarks") or [] if lm["role"] == "main"]
    if not mains:
        total = len(facts.get("landmarks") or [])
        add(
            "a11y:landmark-main-missing",
            f"no main landmark ({total} landmark(s) found), so skip-to-content"
            " has no target",
            suggestion="wrap the primary content in <main>",
        )
    elif len(mains) > 1:
        add(
            "a11y:landmark-main-multiple",
            f"{len(mains)} main landmarks, but exactly one is allowed",
            line=mains[1]["line"],
            col=mains[1]["col"],
        )


def _audit_images(facts: dict[str, Any], add: Any) -> None:
    for image in facts.get("images") or []:
        where = image["src"] or "<no src>"
        if image["presentational"]:
            continue  # role=presentation removes it from the accessibility tree
        if image["alt"] is None:
            add(
                "a11y:img-alt-missing",
                f"{image['tag']} {where} has no alt attribute",
                line=image["line"],
                col=image["col"],
                suggestion='describe it, or alt="" if it is purely decorative',
            )
            continue
        generic, why = alt_is_generic(image["alt"], image["src"])
        if generic:
            add(
                "a11y:img-alt-generic",
                f"{image['tag']} {where}: {why}",
                line=image["line"],
                col=image["col"],
            )


def _audit_forms(facts: dict[str, Any], add: Any) -> None:
    ids = set(facts.get("ids") or {})
    label_ids = {lb["for"] for lb in facts.get("labels") or [] if lb["for"]}
    for label in facts.get("labels") or []:
        if label["for"] and label["for"] not in ids:
            add(
                "a11y:label-orphan",
                f"<label for={label['for']!r}> matches no element id",
                line=label["line"],
                col=label["col"],
            )
        elif not label["for"] and not label["wraps"]:
            add(
                "a11y:label-orphan",
                "<label> has no for attribute and wraps no form control",
                line=label["line"],
                col=label["col"],
            )
    for control in facts.get("controls") or []:
        source, failure = _accessible_name(control, label_ids, ids)
        if source is None:
            detail = failure or "no label[for], wrapping label, aria-label or title"
            add(
                "a11y:control-unlabeled",
                f"{_describe(control)} has no accessible name: {detail}",
                line=control["line"],
                col=control["col"],
                suggestion="add <label for=...> or aria-label",
            )
        elif control["placeholder"] and source == "title":
            add(
                "a11y:control-placeholder-only",
                f"{_describe(control)} is named only by title/placeholder, which"
                " disappears once the field has content",
                line=control["line"],
                col=control["col"],
            )
        if source is None and control["placeholder"]:
            add(
                "a11y:control-placeholder-only",
                f"{_describe(control)} has a placeholder but no label, and a"
                " placeholder is not an accessible name",
                line=control["line"],
                col=control["col"],
            )


def _audit_contrast(facts: dict[str, Any], add: Any) -> None:
    conditional = [
        p
        for p in facts.get("root_conditional") or []
        if "background" in p or "color" in p
    ]
    for reading in contrast_readings(facts):
        where = f"{reading['fg'] or '<inherited>'} on {reading['bg'] or '<undeclared>'}"
        scale = "large" if reading["large"] else "normal"
        size = f"{reading['font_px']:g}px{' bold' if reading['bold'] else ''}"
        if reading["error"] is not None:
            note = reading["error"]
            if conditional and "background color is not declared" in note:
                note += (
                    f"; the root rule sets {', '.join(conditional)} inside an"
                    " @media/@supports block, which this core will not resolve"
                )
            add(
                "a11y:contrast-unknown",
                f"contrast not computable for {where}: {note}",
                line=reading["line"],
                col=reading["col"],
                suggestion=f"sample text: {reading['sample']!r}",
            )
        elif not reading["passes_aa"]:
            add(
                "a11y:contrast-aa",
                f"contrast {reading['ratio']}:1 for {where} at {size}"
                f" ({reading['font_source']}) is below the AA minimum"
                f" {reading['required_aa']}:1 for {scale} text",
                line=reading["line"],
                col=reading["col"],
                suggestion=f"{reading['runs']} text run(s), first: {reading['sample']!r}",
            )
        elif not reading["passes_aaa"]:
            add(
                "a11y:contrast-aaa",
                f"contrast {reading['ratio']}:1 for {where} at {size} passes AA but"
                f" is below the AAA target {reading['required_aaa']}:1 for {scale} text",
                line=reading["line"],
                col=reading["col"],
            )


SCOPE_LIMITS = (
    "inline style attributes plus the html/:root/body rules of <style> blocks are"
    " resolved; class and descendant selectors, @media/@supports blocks, linked"
    " stylesheets and JavaScript-applied styles are not, and text they colour is"
    " reported as a11y:contrast-unknown with the reason instead of a guessed ratio"
)


def page_report(
    html_text: str, *, path: str, rules: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """One local page -> counts, contrast readings, diagnostics, skip reasons."""
    facts = parse_document(html_text)
    diags = audit_document(facts, path=path, rules=rules)
    readings = contrast_readings(facts)
    skipped: list[str] = []
    if not facts["html_seen"]:
        skipped.append(
            "no <html> element (fragment?): the document-language check (3.1.1)"
            " cannot apply and was not counted as a pass"
        )
    for kind, count in facts["hidden_skipped"].items():
        if count:
            skipped.append(
                f"{count} hidden {kind} not audited (not exposed to assistive tech)"
            )
    if facts["root_conditional"]:
        skipped.append(
            "root style properties declared inside @media/@supports and left"
            f" unresolved: {', '.join(facts['root_conditional'])}"
        )
    if facts["parse_error"]:
        skipped.append(f"html.parser reported {facts['parse_error']}")
    return {
        "path": path,
        "unreadable": None,
        "counts": {
            "images": len(facts["images"]),
            "images_missing_alt": sum(1 for i in facts["images"] if i["alt"] is None),
            "headings": len(facts["headings"]),
            "controls": len(facts["controls"]),
            "labels": len(facts["labels"]),
            "landmarks": len(facts["landmarks"]),
            "text_styles": len(readings),
            "contrast_measured": sum(1 for r in readings if r["ratio"] is not None),
            "contrast_unknown": sum(1 for r in readings if r["error"] is not None),
            "stylesheet_bytes": facts["stylesheet_bytes"],
        },
        "lang": facts["lang"],
        "contrast": readings,
        "skipped": skipped,
        "diagnostics": diags,
    }


def unreadable_report(
    path: str, error: str, *, rules: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """A file that could not be READ is not a file that passed.

    `counts` is None rather than a row of zeros: zero images is a measurement,
    and no measurement was taken. The finding rides the same diagnostic schema
    so --fail-on treats an unreadable page as the failure it is.
    """
    rs = rules or load_rules()
    cfg = rs.get("a11y:file-unreadable") or {}
    diags = []
    if cfg.get("enabled", True):
        diags.append(
            openswap.diagnostic(
                path=path,
                line=0,
                col=1,
                rule="a11y:file-unreadable",
                severity=cfg.get("severity", "error"),
                message=f"could not read the file, so nothing was audited: {error}",
                suggestion="check the path, permissions and encoding",
            )
        )
    return {
        "path": path,
        "unreadable": error,
        "counts": None,
        "lang": None,
        "contrast": [],
        "skipped": [f"file not audited: {error}"],
        "diagnostics": diags,
    }


_COUNT_KEYS = (
    "images",
    "images_missing_alt",
    "headings",
    "controls",
    "labels",
    "landmarks",
    "text_styles",
    "contrast_measured",
    "contrast_unknown",
)


def aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals across pages. Unread pages are counted as unread, not as zeros."""
    totals = dict.fromkeys(_COUNT_KEYS, 0)
    audited = 0
    unreadable = 0
    for report in reports:
        counts = report.get("counts")
        if counts is None:
            unreadable += 1
            continue
        audited += 1
        for key in _COUNT_KEYS:
            totals[key] += int(counts.get(key, 0))
    return {
        "pages": len(reports),
        "pages_audited": audited,
        "pages_unreadable": unreadable,
        "totals": totals,
    }
