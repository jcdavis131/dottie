"""A11y — openswap #25 (Siteimprove -> stdlib html.parser + WCAG 2.x contrast
arithmetic over LOCAL html). Pure-logic core tests: color parsing, the sRGB
luminance/ratio math against published reference values, the large-text
threshold boundaries, the value-XOR-error honesty invariant on every reading,
the tiny CSS resolver, fact extraction, every rule firing AND every rule staying
quiet on a clean page, the rules overlay, the zero-egress manifest guard and the
real CLI in a subprocess. Offline and deterministic by construction: every input
is a string, no fixture is fetched and no socket is opened on any path."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import a11y, openswap

ROOT = Path(__file__).resolve().parents[1]
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# rgb(22,132,132) on white is 4.4989:1 — it ROUNDS to 4.50 for display but must
# never be reported as passing AA (WCAG forbids rounding a near-miss up).
NEAR_MISS = "rgb(22,132,132)"

CLEAN_PAGE = """<!doctype html>
<html lang="en">
<head><title>Clean</title><style>body { background: #ffffff; color: #111111; }</style></head>
<body>
<header><nav><a href="/">Home</a></nav></header>
<main>
<h1>Heading one</h1>
<h2>Heading two</h2>
<img src="cat.jpg" alt="A tabby cat asleep on a keyboard">
<img src="line.png" alt="">
<p>Body copy that is plainly readable.</p>
<form>
  <label for="q">Search</label>
  <input id="q" type="search" name="q">
  <button>Go</button>
</form>
</main>
<footer><p>Footer</p></footer>
</body>
</html>
"""


def _report(html: str, path: str = "p.html", rules=None) -> dict:
    return a11y.page_report(html, path=path, rules=rules)


def _rules_fired(html: str, rules=None) -> set[str]:
    return {d["rule"] for d in _report(html, rules=rules)["diagnostics"]}


# ---- color parsing ----------------------------------------------------------


def test_parse_color_hex_forms():
    assert a11y.parse_color("#fff") == (255, 255, 255, 1.0)
    assert a11y.parse_color("#FFFFFF") == (255, 255, 255, 1.0)
    assert a11y.parse_color("#000000") == (0, 0, 0, 1.0)
    assert a11y.parse_color("  #abc  ") == (170, 187, 204, 1.0)  # 3-digit expands by 17
    assert a11y.parse_color("#12345678")[:3] == (18, 52, 86)
    assert a11y.parse_color("#12345678")[3] == pytest.approx(120 / 255.0)
    assert a11y.parse_color("#ffff")[3] == 1.0  # 4-digit alpha nibble


def test_parse_color_hex_rejects_bad_lengths_and_digits():
    for bad in (
        "#",
        "#f",
        "#ff",
        "#fffff",
        "#fffffff",
        "#ffffffffff",
        "#gggggg",
        "#12 34 56",
    ):
        assert a11y.parse_color(bad) is None, bad


def test_parse_color_rgb_functional_forms():
    assert a11y.parse_color("rgb(1,2,3)") == (1, 2, 3, 1.0)
    assert a11y.parse_color("RGB( 1 , 2 , 3 )") == (1, 2, 3, 1.0)
    assert a11y.parse_color("rgb(1 2 3)") == (1, 2, 3, 1.0)  # modern space syntax
    assert a11y.parse_color("rgba(1,2,3,0.5)") == (1, 2, 3, 0.5)
    assert a11y.parse_color("rgb(1 2 3 / 50%)") == (1, 2, 3, 0.5)
    assert a11y.parse_color("rgb(100%, 0%, 0%)") == (255, 0, 0, 1.0)
    assert a11y.parse_color("rgb(300, -20, 3)") == (255, 0, 3, 1.0)  # clamped
    assert a11y.parse_color("rgba(0,0,0,9)")[3] == 1.0  # alpha clamped


def test_parse_color_rgb_rejects_malformed():
    for bad in (
        "rgb(1,2)",
        "rgb(1,2,3,4,5)",
        "rgb(a,b,c)",
        "rgb(1,2,3",
        "hsl(0,0%,0%)",
        "var(--brand)",
        "currentColor",
        "",
        "   ",
        None,
        12345,
        "url(x.png)",
    ):
        assert a11y.parse_color(bad) is None, bad


def test_parse_color_keywords_and_transparent():
    assert a11y.parse_color("white") == (255, 255, 255, 1.0)
    assert a11y.parse_color("  BLACK ") == (0, 0, 0, 1.0)
    assert a11y.parse_color("grey") == a11y.parse_color("gray")
    assert a11y.parse_color("transparent") == (0, 0, 0, 0.0)  # alpha 0, not a backdrop
    assert a11y.parse_color("rebeccapurple") is None  # outside the honest keyword set


def test_first_color_token_finds_the_color_in_a_shorthand():
    assert a11y.first_color_token("#fff url(bg.png) no-repeat") == "#fff"
    assert a11y.first_color_token("rgb(1, 2, 3)") == "rgb(1, 2, 3)"
    assert a11y.first_color_token("url(bg.png) no-repeat") is None
    assert a11y.first_color_token("") is None


# ---- WCAG arithmetic --------------------------------------------------------


def test_black_on_white_is_21_and_the_ratio_is_symmetric():
    assert a11y.contrast_ratio(BLACK, WHITE) == pytest.approx(21.0)
    assert a11y.contrast_ratio(WHITE, BLACK) == pytest.approx(21.0)
    assert a11y.contrast_ratio(WHITE, WHITE) == pytest.approx(1.0)
    assert a11y.relative_luminance(WHITE) == pytest.approx(1.0)
    assert a11y.relative_luminance(BLACK) == pytest.approx(0.0)


def test_known_wcag_reference_ratios():
    # #767676 on white is the canonical "just passes AA" gray (4.54:1)
    assert round(a11y.contrast_ratio((0x76, 0x76, 0x76), WHITE), 2) == 4.54
    assert round(a11y.contrast_ratio((0x77, 0x77, 0x77), WHITE), 2) == 4.48
    assert round(a11y.contrast_ratio((0, 0, 0xFF), WHITE), 2) == 8.59  # blue on white
    # the green channel dominates the luminance sum, red barely moves it
    assert a11y.relative_luminance((0, 255, 0)) > a11y.relative_luminance((255, 0, 0))


def test_channel_luminance_uses_both_branches_at_the_threshold():
    low = a11y.SRGB_THRESHOLD * 255.0 - 0.01
    high = a11y.SRGB_THRESHOLD * 255.0 + 0.01
    assert a11y.channel_luminance(low) == pytest.approx((low / 255.0) / 12.92)
    assert a11y.channel_luminance(high) == pytest.approx(
        ((high / 255.0 + 0.055) / 1.055) ** 2.4
    )
    # the two branches meet, so the curve has no step at the join
    assert a11y.channel_luminance(high) == pytest.approx(
        a11y.channel_luminance(low), abs=1e-4
    )
    assert a11y.channel_luminance(0.0) == 0.0
    assert a11y.channel_luminance(255.0) == pytest.approx(1.0)


def test_is_large_text_boundaries():
    assert a11y.is_large_text(24.0, False) is True
    assert a11y.is_large_text(23.99, False) is False
    assert a11y.is_large_text(18.66, True) is True
    assert a11y.is_large_text(18.65, True) is False
    assert a11y.is_large_text(20.0, False) is False  # 20px normal weight is not large
    assert (
        a11y.is_large_text(None, True) is False
    )  # undeclared judged at the strict bar


def test_required_ratio_matrix_and_unknown_level():
    assert a11y.required_ratio(False, "AA") == 4.5
    assert a11y.required_ratio(True, "AA") == 3.0
    assert a11y.required_ratio(False, "AAA") == 7.0
    assert a11y.required_ratio(True, "aaa") == 4.5  # case-insensitive
    with pytest.raises(ValueError):
        a11y.required_ratio(False, "AAAA")


# ---- the reading honesty invariant -----------------------------------------


def test_every_reading_is_value_xor_error():
    cases = [
        ("#000", "#fff"),
        ("#fff", "#fff"),
        ("white", "black"),
        ("rgb(1,2,3)", "rgb(4,5,6)"),
        (None, "#fff"),
        ("#fff", None),
        ("", ""),
        ("var(--x)", "#fff"),
        ("#fff", "var(--x)"),
        ("rgba(0,0,0,0.5)", "#fff"),
        ("#000", "rgba(255,255,255,0.2)"),
        ("transparent", "#fff"),
        ("#000", "transparent"),
        ("#000", "url(bg.png) no-repeat"),
        ("hotpink", "#fff"),
    ]
    for fg, bg in cases:
        r = a11y.contrast_reading(fg, bg)
        has_value = r["ratio"] is not None
        has_error = r["error"] is not None
        assert has_value != has_error, (fg, bg, r)
        if has_error:  # a failed measurement never carries a verdict
            assert r["passes_aa"] is None and r["passes_aaa"] is None
        else:
            assert isinstance(r["passes_aa"], bool) and isinstance(
                r["passes_aaa"], bool
            )


def test_display_rounding_never_creates_a_pass():
    r = a11y.contrast_reading(NEAR_MISS, "#ffffff")
    assert r["ratio"] == 4.5  # what a human reads
    assert r["passes_aa"] is False  # what the gate decides, unrounded
    ok_pair = a11y.contrast_reading("#767676", "#ffffff")
    assert ok_pair["ratio"] == 4.54 and ok_pair["passes_aa"] is True
    assert ok_pair["passes_aaa"] is False  # 4.54 < 7.0


def test_large_text_lowers_the_bar_only_at_the_real_boundary():
    small = a11y.contrast_reading("#9a9a9a", "#fff", font_px=23.0)
    large = a11y.contrast_reading("#9a9a9a", "#fff", font_px=24.0)
    assert small["required_aa"] == 4.5 and large["required_aa"] == 3.0
    assert small["large"] is False and large["large"] is True
    assert small["ratio"] == large["ratio"]  # same colors, same measurement
    bold = a11y.contrast_reading("#949494", "#fff", font_px=19.0, bold=True)
    assert bold["large"] is True and bold["passes_aa"] is True


def test_unknown_colors_report_why_and_never_a_number():
    alpha = a11y.contrast_reading("#000", "rgba(255,255,255,0.4)")
    assert alpha["ratio"] is None and "alpha 0.4" in alpha["error"]
    image = a11y.contrast_reading("#000", "url(hero.jpg) center")
    assert image["ratio"] is None and "is an image" in image["error"]
    missing = a11y.contrast_reading("#000", None)
    assert missing["ratio"] is None and "not declared" in missing["error"]
    junk = a11y.contrast_reading("#000", "chartreuse")
    assert junk["ratio"] is None and "not a hex/rgb/keyword color" in junk["error"]
    assert a11y.contrast_reading("transparent", "#fff")["error"].endswith(
        "fully transparent"
    )


# ---- the (deliberately tiny) CSS resolver -----------------------------------


def test_parse_declarations():
    d = a11y.parse_declarations("color:#fff; background : #000 ;;font-size:12px")
    assert d == {"color": "#fff", "background": "#000", "font-size": "12px"}
    assert a11y.parse_declarations("background:url(http://x/y.png)") == {
        "background": "url(http://x/y.png)"  # only the FIRST colon splits
    }
    assert (
        a11y.parse_declarations("color:red;color:blue")["color"] == "blue"
    )  # last wins
    assert a11y.parse_declarations("no-colon-here") == {}
    assert a11y.parse_declarations(None) == {}


def test_iter_rules_tracks_at_depth_and_strips_comments():
    css = """/* c */ body { color: #111 }
    @media (prefers-color-scheme: dark) { body { color: #eee } }
    .card { color: red }"""
    rules = a11y.iter_rules(css)
    by_selector = [(sel.strip(), depth) for sel, _body, depth in rules]
    assert ("body", 0) in by_selector
    assert ("body", 1) in by_selector  # the @media copy is marked conditional
    # the first disjunct was DEAD: by_selector is built with sel.strip() above, so a
    # leading-whitespace key can never be in it, and the second disjunct re-stripped
    # already-stripped values. Assert the one reachable claim.
    assert (".card", 0) in by_selector
    assert a11y.iter_rules("") == []
    assert a11y.iter_rules("body { color: #111") == [
        ("body", " color: #111", 0)
    ]  # unclosed


def test_root_style_applies_the_base_rule_and_flags_conditional_props():
    css = """html { color: #222 } body { background: #fff }
    @media print { body { background: #ccc } }
    .hero { background: #000 }"""
    rs = a11y.root_style(css)
    assert rs["declarations"]["color"] == "#222"
    assert rs["declarations"]["background"] == "#fff"  # the unconditional rule applies
    assert rs["conditional"] == ["background"]  # the @media one is named, not applied
    assert a11y.root_style(".only-classes { color: red }") == {
        "declarations": {},
        "conditional": [],
    }


def test_parse_font_size_units_and_invalid_values():
    assert a11y.parse_font_size("12px") == 12.0
    assert a11y.parse_font_size("12pt") == pytest.approx(16.0)
    assert a11y.parse_font_size("1in") == 96.0
    assert a11y.parse_font_size("2rem") == 32.0
    assert a11y.parse_font_size("2em", parent_px=10.0) == 20.0
    assert a11y.parse_font_size("50%", parent_px=20.0) == 10.0
    assert a11y.parse_font_size("large") == 18.0
    assert a11y.parse_font_size("larger", parent_px=10.0) == pytest.approx(12.0)
    assert a11y.parse_font_size("smaller", parent_px=12.0) == pytest.approx(10.0)
    assert a11y.parse_font_size("0") == 0.0
    for bad in ("12", "-4px", "", None, "calc(1rem + 2px)", "12kg"):
        assert a11y.parse_font_size(bad) is None, bad


def test_parse_font_weight():
    assert a11y.parse_font_weight("bold") is True
    assert a11y.parse_font_weight("700") is True
    assert a11y.parse_font_weight("699") is False
    assert a11y.parse_font_weight("normal") is False
    assert a11y.parse_font_weight("lighter") is False
    assert a11y.parse_font_weight("bolder") is True
    assert (
        a11y.parse_font_weight("heavy") is None and a11y.parse_font_weight(None) is None
    )


# ---- fact extraction --------------------------------------------------------


def test_style_block_after_the_markup_still_applies():
    """The two-pass contract: a trailing <style> must colour the text above it."""
    html = "<html><body><p>hi</p><style>body{color:#999;background:#fff}</style></body></html>"
    readings = a11y.contrast_readings(a11y.parse_document(html))
    assert len(readings) == 1
    assert readings[0]["ratio"] == 2.85 and readings[0]["passes_aa"] is False


def test_transparent_background_keeps_the_ancestor_backdrop():
    html = (
        "<body style='background:#000'><div style='background:transparent'>"
        "<span style='color:#fff'>x</span></div></body>"
    )
    readings = a11y.contrast_readings(a11y.parse_document(html))
    assert [r["bg"] for r in readings] == ["#000"]
    assert readings[0]["ratio"] == 21.0


def test_font_size_and_weight_inherit_down_the_chain():
    html = (
        "<body style='font-size:20px'><div style='font-size:1.5em'>"
        "<span style='color:#999;background:#fff'>x</span></div></body>"
    )
    reading = a11y.contrast_readings(a11y.parse_document(html))[0]
    assert reading["font_px"] == 30.0 and reading["large"] is True
    assert reading["font_source"] == "declared"


def test_ua_defaults_make_an_unstyled_h1_large_text():
    html = "<body style='background:#fff'><h1 style='color:#9a9a9a'>T</h1></body>"
    reading = a11y.contrast_readings(a11y.parse_document(html))[0]
    assert reading["font_px"] == 32.0 and reading["bold"] is True
    assert reading["large"] is True and reading["font_source"] == "ua-default"
    # honesty: the threshold rests on a UA default and the reading says so
    assert reading["required_aa"] == 3.0


def test_hidden_subtrees_are_skipped_and_counted():
    html = """<body>
    <div hidden><img src="a.png"><input name="a"><h2></h2><p style="color:#eee">x</p></div>
    <div aria-hidden="true"><img src="b.png"></div>
    <div style="display:none"><img src="c.png"></div>
    <div style="visibility:hidden"><img src="d.png"></div>
    <img src="visible.png">
    </body>"""
    facts = a11y.parse_document(html)
    assert [i["src"] for i in facts["images"]] == ["visible.png"]
    assert facts["hidden_skipped"]["images"] == 4
    assert facts["hidden_skipped"]["controls"] == 1
    assert facts["hidden_skipped"]["headings"] == 1
    assert facts["hidden_skipped"]["text_runs"] == 1
    report = _report(html)
    assert any("hidden images" in s for s in report["skipped"])


def test_image_alt_states_are_distinguished():
    html = (
        '<img src="a.png">'
        '<img src="b.png" alt="">'
        '<img src="c.png" alt="A cat">'
        '<img src="d.png" alt="d.png">'
        '<img src="e.png" role="presentation">'
        '<input type="image" src="f.png">'
    )
    facts = a11y.parse_document(html)
    alts = {i["src"]: i["alt"] for i in facts["images"]}
    assert alts["a.png"] is None and alts["b.png"] == "" and alts["c.png"] == "A cat"
    assert [i["src"] for i in facts["images"] if i["presentational"]] == ["e.png"]
    assert any(
        i["tag"] == "input" for i in facts["images"]
    )  # input type=image needs alt too


def test_alt_is_generic_detection():
    assert a11y.alt_is_generic("", "x.png") == (False, None)  # decorative, not generic
    assert a11y.alt_is_generic("A tabby cat", "cat.png")[0] is False
    assert a11y.alt_is_generic("image", "cat.png")[0] is True
    assert a11y.alt_is_generic("cat.png", "img/cat.png")[0] is True
    assert a11y.alt_is_generic("cat", "img/cat.png?v=2")[0] is True  # repeats the stem
    assert a11y.alt_is_generic("hero.JPG", "x")[0] is True
    assert a11y.alt_is_generic("2026", "x.png")[0] is True


def test_headings_capture_text_including_nested_image_alt():
    html = '<h1><img src="logo.png" alt="Acme"> <em>Home</em></h1><h2></h2>'
    facts = a11y.parse_document(html)
    assert facts["headings"][0]["text"] == "Acme Home"
    assert facts["headings"][0]["level"] == 1
    assert facts["headings"][1]["text"] == ""  # nothing to announce


def test_control_labelling_sources():
    html = """<form>
    <label for="a">A</label><input id="a" name="a">
    <label>B <input name="b"></label>
    <input name="c" aria-label="C">
    <input name="d" aria-labelledby="lbl"><span id="lbl">D</span>
    <input name="e" aria-labelledby="gone">
    <input name="f" title="F">
    <input name="g" placeholder="G">
    <input type="submit" value="Send">
    <input type="hidden" name="csrf">
    <button>Go</button><button></button>
    </form>"""
    facts = a11y.parse_document(html)
    names = [c["name"] or c["tag"] for c in facts["controls"]]
    assert "csrf" not in names  # hidden inputs are not exposed, so not audited
    fired = _rules_fired(html)
    unlabeled = [
        d["message"]
        for d in _report(html)["diagnostics"]
        if d["rule"] == "a11y:control-unlabeled"
    ]
    assert "a11y:control-unlabeled" in fired
    assert any("name=e" in m and "missing id" in m for m in unlabeled)
    assert any("name=g" in m for m in unlabeled)
    assert any("button" in m for m in unlabeled)
    for named in ("name=a", "name=b", "name=c", "name=d", "name=f", "Send"):
        assert not any(named in m for m in unlabeled), named


def test_wrapping_label_counts_and_orphans_are_reported():
    html = "<label for='nope'>x</label><label>wrapped <input name='w'></label><label>lonely</label>"
    facts = a11y.parse_document(html)
    assert [lb["wraps"] for lb in facts["labels"]] == [0, 1, 0]
    messages = [
        d["message"]
        for d in _report(html)["diagnostics"]
        if d["rule"] == "a11y:label-orphan"
    ]
    assert len(messages) == 2  # the for-mismatch and the lonely one, not the wrapper
    assert any("matches no element id" in m for m in messages)
    assert any("wraps no form control" in m for m in messages)


def test_landmarks_implicit_explicit_and_named():
    html = """<header>h</header><nav>n</nav><main>m</main><footer>f</footer>
    <aside>a</aside><div role="search">s</div><section>plain</section>
    <section aria-label="Pricing">named</section><form>f</form>
    <form aria-label="Signup">f2</form>"""
    facts = a11y.parse_document(html)
    roles = sorted(lm["role"] for lm in facts["landmarks"])
    assert roles == [
        "banner",
        "complementary",
        "contentinfo",
        "form",
        "main",
        "navigation",
        "region",
        "search",
    ]
    # a bare <section>/<form> without a name is NOT a landmark, and is not counted
    assert sum(1 for lm in facts["landmarks"] if lm["tag"] == "section") == 1


def test_duplicate_ids_and_document_language():
    facts = a11y.parse_document(
        "<html lang='en-GB'><p id='x'></p><p id='x'></p><p id='y'></p>"
    )
    assert facts["lang"] == "en-GB" and facts["html_seen"] is True
    assert facts["ids"]["x"] == [1, 1] and facts["ids"]["y"] == [1]
    assert a11y.parse_document("<html><body></body></html>")["lang"] is None
    assert a11y.parse_document("<p>fragment</p>")["html_seen"] is False


def test_parser_tolerates_malformed_soup():
    for junk in (
        "",
        "<<<>>>",
        "<html><body><p>unclosed",
        "<img src=",
        "<div><span></div></span>",
        "<h1>a<h2>b",
        "<!-- comment only -->",
        "<style>body{color:</style>",
        "<html lang=en><body style=color:#fff>x",
    ):
        facts = a11y.parse_document(junk)
        assert isinstance(facts, dict) and "images" in facts
        assert facts["parse_error"] is None or isinstance(facts["parse_error"], str)


# ---- rules ------------------------------------------------------------------


def test_a_clean_page_produces_no_findings():
    """The guard that makes every other rule test meaningful."""
    report = _report(CLEAN_PAGE, path="clean.html")
    assert report["diagnostics"] == [], report["diagnostics"]
    assert report["counts"]["contrast_measured"] > 0  # it really did measure something
    assert report["counts"]["contrast_unknown"] == 0
    assert report["skipped"] == []


def test_every_rule_fires_on_its_own_minimal_case():
    cases = {
        "a11y:html-lang-missing": "<html><body><p>x</p></body></html>",
        "a11y:img-alt-missing": '<img src="a.png">',
        "a11y:img-alt-generic": '<img src="a.png" alt="photo">',
        "a11y:control-unlabeled": "<input name='q'>",
        "a11y:control-placeholder-only": "<input name='q' placeholder='Q'>",
        "a11y:label-orphan": "<label for='nope'>x</label>",
        "a11y:duplicate-id": "<p id='a'></p><p id='a'></p>",
        "a11y:heading-empty": "<h1></h1>",
        "a11y:heading-first-not-h1": "<h2>x</h2>",
        "a11y:heading-skipped-level": "<h1>a</h1><h3>b</h3>",
        "a11y:heading-none": "<p>no headings here</p>",
        "a11y:landmark-main-missing": "<nav>n</nav>",
        "a11y:landmark-main-multiple": "<main>a</main><main>b</main>",
        "a11y:contrast-aa": "<p style='color:#999;background:#fff'>x</p>",
        "a11y:contrast-aaa": "<p style='color:#767676;background:#fff'>x</p>",
        "a11y:contrast-unknown": "<p style='color:#999'>x</p>",
    }
    for rule, html in cases.items():
        assert rule in _rules_fired(html), f"{rule} did not fire on {html}"


def test_rules_that_must_stay_quiet():
    quiet = {
        "a11y:img-alt-missing": '<img src="a.png" alt="A cat">',
        "a11y:img-alt-generic": '<img src="a.png" alt="">',
        "a11y:control-unlabeled": "<label for='a'>A</label><input id='a'>",
        "a11y:control-placeholder-only": "<label for='a'>A</label><input id='a' placeholder='x'>",
        "a11y:label-orphan": "<label>wrap <input name='a'></label>",
        "a11y:duplicate-id": "<p id='a'></p><p id='b'></p>",
        "a11y:heading-skipped-level": "<h1>a</h1><h2>b</h2><h3>c</h3><h2>d</h2>",
        "a11y:heading-first-not-h1": "<h1>a</h1><h2>b</h2>",
        "a11y:landmark-main-multiple": "<main>a</main>",
        "a11y:contrast-aa": "<p style='color:#000;background:#fff'>x</p>",
        "a11y:contrast-unknown": "<p style='color:#000;background:#fff'>x</p>",
        "a11y:html-lang-missing": "<html lang='en'><body>x</body></html>",
    }
    for rule, html in quiet.items():
        assert rule not in _rules_fired(html), f"{rule} false-positived on {html}"


def test_presentational_and_decorative_images_are_exempt():
    html = '<img src="a.png" role="presentation"><img src="b.png" role="none">'
    fired = _rules_fired(html)
    assert "a11y:img-alt-missing" not in fired and "a11y:img-alt-generic" not in fired


def test_diagnostics_carry_the_wcag_criterion_and_family_schema():
    diag = next(
        d
        for d in _report("<img src='a.png'>")["diagnostics"]
        if d["rule"] == "a11y:img-alt-missing"
    )
    assert set(diag) == {
        "path",
        "line",
        "col",
        "rule",
        "severity",
        "message",
        "suggestion",
        "source",
    }
    assert diag["path"] == "p.html" and diag["severity"] == "error"
    assert "WCAG 1.1.1" in diag["message"] and diag["suggestion"]
    assert diag["severity"] in openswap.SEVERITIES


def test_diagnostics_are_sorted_by_position():
    html = "<body><p style='color:#999;background:#fff'>x</p>\n<img src='a.png'>\n<h2>late</h2></body>"
    lines = [d["line"] for d in _report(html)["diagnostics"]]
    assert lines == sorted(lines)


def test_rules_overlay_can_disable_and_change_severity(tmp_path):
    overlay = tmp_path / "org.json"
    overlay.write_text(
        json.dumps(
            {
                "a11y:img-alt-missing": {"severity": "warning"},
                "a11y:heading-none": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    rules = a11y.load_rules(overlay)
    diags = _report('<img src="a.png">', rules=rules)["diagnostics"]
    by_rule = {d["rule"]: d["severity"] for d in diags}
    assert by_rule["a11y:img-alt-missing"] == "warning"  # downgraded by policy
    assert "a11y:heading-none" not in by_rule  # disabled by policy
    assert (
        a11y.load_rules()["a11y:img-alt-missing"]["severity"] == "error"
    )  # defaults intact


def test_load_rules_rejects_typos_and_bad_severity(tmp_path):
    bad_id = tmp_path / "a.json"
    bad_id.write_text('{"a11y:img-alt-mising": {"enabled": false}}', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown rule id"):
        a11y.load_rules(bad_id)
    bad_sev = tmp_path / "b.json"
    bad_sev.write_text(
        '{"a11y:img-alt-missing": {"severity": "critical"}}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="severity"):
        a11y.load_rules(bad_sev)
    not_object = tmp_path / "c.json"
    not_object.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        a11y.load_rules(not_object)
    every_rule_has_a_severity = all(
        cfg["severity"] in openswap.SEVERITIES for cfg in a11y.RULES.values()
    )
    assert every_rule_has_a_severity


def test_conditional_root_background_is_named_in_the_unknown_message():
    html = (
        "<html><head><style>@media print { body { background:#fff } }</style></head>"
        "<body><p style='color:#999'>x</p></body></html>"
    )
    diags = [
        d for d in _report(html)["diagnostics"] if d["rule"] == "a11y:contrast-unknown"
    ]
    assert len(diags) == 1
    assert "@media/@supports block" in diags[0]["message"]


# ---- reports ----------------------------------------------------------------


def test_page_report_counts_match_the_facts():
    report = _report(CLEAN_PAGE, path="clean.html")
    counts = report["counts"]
    assert counts["images"] == 2 and counts["images_missing_alt"] == 0
    assert counts["headings"] == 2 and counts["landmarks"] == 4
    assert counts["controls"] == 2 and counts["labels"] == 1
    assert counts["stylesheet_bytes"] > 0
    assert report["lang"] == "en" and report["unreadable"] is None
    assert (
        counts["text_styles"]
        == counts["contrast_measured"] + counts["contrast_unknown"]
    )


def test_unreadable_report_has_no_counts_and_one_error():
    report = a11y.unreadable_report("gone.html", "OSError: nope")
    assert report["counts"] is None  # zero images would be a fabricated measurement
    assert report["unreadable"] == "OSError: nope"
    assert [d["rule"] for d in report["diagnostics"]] == ["a11y:file-unreadable"]
    assert report["diagnostics"][0]["severity"] == "error"
    assert report["skipped"] == ["file not audited: OSError: nope"]


def test_aggregate_separates_unread_pages_from_clean_ones():
    good = _report(CLEAN_PAGE, path="a.html")
    bad = a11y.unreadable_report("b.html", "OSError: nope")
    agg = a11y.aggregate([good, bad, good])
    assert (
        agg["pages"] == 3 and agg["pages_audited"] == 2 and agg["pages_unreadable"] == 1
    )
    assert agg["totals"]["images"] == 4  # summed over the audited pages only
    assert a11y.aggregate([])["totals"]["images"] == 0


# ---- capability, manifest, egress guard -------------------------------------


def test_detection_fallback_is_the_expected_steady_state(monkeypatch):
    from bigbang.plugins.a11y import cli as a11y_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = a11y_cli._capability()
    assert cap["adapter"] == "a11y" and cap["tier"] == openswap.TIER_FALLBACK
    assert cap["native"]["binary"] == "axe" and cap["native"]["found"] is False
    assert cap["extras"]["pa11y"]["found"] is False  # browser-driven, never executed
    assert cap["extras"]["tidy"]["found"] is False
    assert cap["native_used"] is False  # true on EVERY tier, by contract
    assert "NEVER executed" in cap["native_never_executed"]
    assert "complete product" in cap["fallback_scope"]


def test_manifest_is_zero_egress_and_read_only():
    import yaml

    mf = yaml.safe_load(
        (ROOT / "bigbang" / "plugins" / "a11y" / "manifest.yaml").read_text(
            encoding="utf-8"
        )
    )
    caps = mf["capabilities"]
    assert mf["name"] == "a11y"
    assert caps["network"]["enabled"] is False and caps["network"]["domains"] == []
    assert caps["filesystem"]["write"] is False and caps["filesystem"]["paths"] == []
    assert caps["secrets"]["allow"] == []


def test_egress_guard_refuses_a_widened_manifest(monkeypatch):
    import typer

    from bigbang.plugins.a11y import cli as a11y_cli

    assert a11y_cli._egress_guard("test")["network_enabled"] is False
    for widened in (
        {"capabilities": {"network": {"enabled": True, "domains": []}}},
        {"capabilities": {"network": {"enabled": False, "domains": ["example.com"]}}},
    ):
        monkeypatch.setattr(a11y_cli, "_MANIFEST", widened)
        with pytest.raises(typer.Exit):
            a11y_cli._egress_guard("test")


def test_read_html_reports_why_instead_of_raising(tmp_path):
    from bigbang.plugins.a11y import cli as a11y_cli

    good = tmp_path / "ok.html"
    good.write_text("<p>hi</p>", encoding="utf-8")
    text, error = a11y_cli._read_html(good)
    assert text == "<p>hi</p>" and error is None
    text, error = a11y_cli._read_html(tmp_path)  # a directory is not readable text
    assert text == "" and error and ("Error" in error or "error" in error)


# ---- stdlib-only invariant (the whole point of the openswap family) ----------


def test_core_imports_are_stdlib_only():
    tree = ast.parse(
        (ROOT / "bigbang" / "core" / "a11y.py").read_text(encoding="utf-8")
    )
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    allowed = set(sys.stdlib_module_names) | {"bigbang"}
    assert roots <= allowed, f"non-stdlib imports: {sorted(roots - allowed)}"


def test_plugin_cli_adds_no_dependency_beyond_typer():
    tree = ast.parse(
        (ROOT / "bigbang" / "plugins" / "a11y" / "cli.py").read_text(encoding="utf-8")
    )
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    allowed = set(sys.stdlib_module_names) | {"bigbang", "typer"}
    assert roots <= allowed, f"new dependency: {sorted(roots - allowed)}"


def test_html_extension_list_is_derived_from_seo_not_retyped():
    from bigbang.core import seo

    assert a11y.HTML_EXTS is seo.HTML_EXTS  # identity: drift is impossible


# ---- the real CLI in a subprocess (offline on every path) --------------------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(cwd or ROOT),
    )


def _page(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_cli_a11y_hello_envelope():
    r = _cli(["a11y", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert data["data"]["plugin"] == "a11y" and "example" in data


def test_cli_a11y_detect_reports_fallback_and_zero_egress():
    r = _cli(["a11y", "detect"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["tier"] == "fallback" and data["native_used"] is False
    assert data["egress"] == {
        "network_enabled": False,
        "domains": [],
        "reads": "local files only",
    }
    assert "contrast-unknown" in data["scope_limits"]


def test_cli_a11y_check_finds_real_defects_and_gates(tmp_path):
    page = _page(
        tmp_path,
        "bad.html",
        '<html><body><h2>Late</h2><img src="a.png">'
        '<p style="color:#999;background:#fff">low</p>'
        "<input name='q' placeholder='q'></body></html>",
    )
    r = _cli(["a11y", "check", str(page), "--fail-on", "error"])
    assert r.returncode == 1  # the gate fires on the errors below
    data = json.loads(r.stdout)["data"]
    fired = {d["rule"] for d in data["diagnostics"]}
    assert {
        "a11y:img-alt-missing",
        "a11y:contrast-aa",
        "a11y:control-unlabeled",
    } <= fired
    assert data["summary"]["by_severity"]["error"] >= 3
    assert data["aggregate"]["pages_audited"] == 1
    assert data["tier"] == "fallback" and data["native_used"] is False
    assert "contrast" not in data["pages"][0]  # readings are opt-in


def test_cli_a11y_check_clean_page_exits_zero(tmp_path):
    page = _page(tmp_path, "clean.html", CLEAN_PAGE)
    r = _cli(["a11y", "check", str(page), "--fail-on", "info", "--contrast"])
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)["data"]
    assert data["diagnostics"] == [] and data["summary"]["total"] == 0
    assert data["pages"][0]["contrast"]  # --contrast surfaced the readings
    assert all(rd["ratio"] is not None for rd in data["pages"][0]["contrast"])


def test_cli_a11y_check_walks_a_directory(tmp_path):
    _page(tmp_path, "one.html", '<img src="a.png">')
    _page(tmp_path, "two.htm", '<img src="b.png">')
    _page(tmp_path, "notes.txt", '<img src="c.png">')
    r = _cli(["a11y", "check", str(tmp_path)])
    assert r.returncode == 0
    data = json.loads(r.stdout)["data"]
    assert data["aggregate"]["pages"] == 2  # the .txt is not HTML and was not read
    assert data["aggregate"]["totals"]["images_missing_alt"] == 2


def test_cli_a11y_check_missing_path_fails_actionably(tmp_path):
    r = _cli(["a11y", "check", str(tmp_path / "nope.html")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "path not found" in data["error"] and "example" in data


def test_cli_a11y_check_empty_directory_fails_actionably(tmp_path):
    (tmp_path / "empty").mkdir()
    r = _cli(["a11y", "check", str(tmp_path / "empty")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no HTML files found" in data["error"]


def test_cli_a11y_check_rejects_a_bad_fail_on(tmp_path):
    page = _page(tmp_path, "x.html", "<p>x</p>")
    r = _cli(["a11y", "check", str(page), "--fail-on", "catastrophe"])
    assert r.returncode == 1
    assert "--fail-on must be one of" in json.loads(r.stdout)["error"]


def test_cli_a11y_contrast_gate_fails_on_an_unknown_reading():
    r = _cli(
        [
            "a11y",
            "contrast",
            "--fg",
            "var(--brand)",
            "--bg",
            "#fff",
            "--fail-below",
            "AA",
        ]
    )
    assert r.returncode == 1  # unknown must never pass a gate
    data = json.loads(r.stdout)["data"]
    assert data["ratio"] is None and data["error"]
    passing = _cli(
        ["a11y", "contrast", "--fg", "#000", "--bg", "#fff", "--fail-below", "AAA"]
    )
    assert passing.returncode == 0
    assert json.loads(passing.stdout)["data"]["ratio"] == 21.0


def test_cli_a11y_rules_publishes_the_table():
    r = _cli(["a11y", "rules"])
    assert r.returncode == 0
    data = json.loads(r.stdout)["data"]
    assert set(data["rules"]) == set(a11y.RULES)
    assert data["rules"]["a11y:contrast-aa"]["wcag"] == "1.4.3"
    assert data["overlay"] is None and data["severities"] == list(openswap.SEVERITIES)


def test_cli_a11y_rules_rejects_a_bad_overlay(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"a11y:not-a-rule": {}}', encoding="utf-8")
    r = _cli(["a11y", "rules", "--rules", str(bad)])
    assert r.returncode == 1
    assert "bad rules overlay" in json.loads(r.stdout)["error"]
