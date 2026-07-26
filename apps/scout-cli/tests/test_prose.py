"""Prose — openswap #1 (Grammarly Premium -> fully local linting). Pure-logic
core tests + capability-detection fallback + the subprocess envelope. Offline
and deterministic by construction: the manifest default-denies the network,
detection is monkeypatched, and no test touches the harper binary."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bigbang.core import openswap, prose

ROOT = Path(__file__).resolve().parents[1]


def _rules_of(diags):
    return [d["rule"] for d in diags]


def _only(diags, rule):
    return [d for d in diags if d["rule"] == rule]


# ---- core checks ------------------------------------------------------------


def test_doubled_word_position():
    diags = _only(prose.lint_text("This is is a test."), "doubled_word")
    assert len(diags) == 1
    assert diags[0]["line"] == 1 and diags[0]["col"] == 6
    assert diags[0]["suggestion"] == "is"


def test_doubled_word_allowed_pairs_pass():
    assert _only(prose.lint_text("He said that that was fine."), "doubled_word") == []


def test_a_an_both_directions():
    d1 = _only(prose.lint_text("I ate a apple today."), "a_an")
    assert d1 and d1[0]["suggestion"] == "an"
    d2 = _only(prose.lint_text("I ate an banana today."), "a_an")
    assert d2 and d2[0]["suggestion"] == "a"


def test_a_an_exceptions_pass():
    text = "It took an hour for a user to make a unique choice."
    assert _only(prose.lint_text(text), "a_an") == []


def test_wordiness_phrase_suggests_replacement():
    diags = _only(prose.lint_text("We did this in order to win."), "wordiness")
    assert len(diags) == 1
    assert diags[0]["suggestion"] == "to"
    assert diags[0]["severity"] == "suggestion"


def test_passive_voice_irregular_participle():
    diags = _only(
        prose.lint_text("The report was written by the team."), "passive_voice"
    )
    assert len(diags) == 1
    assert diags[0]["severity"] == "suggestion"


def test_passive_voice_skips_ed_adjectives():
    assert _only(prose.lint_text("The light is red."), "passive_voice") == []


def test_sentence_length_outlier():
    long_sentence = " ".join(["word"] * 40) + "."
    diags = _only(prose.lint_text(long_sentence), "sentence_length")
    assert len(diags) == 1 and "40-word" in diags[0]["message"]
    assert _only(prose.lint_text("Short sentence."), "sentence_length") == []


def test_misspelling_exact_map():
    diags = _only(prose.lint_text("That is definately wrong."), "misspelling")
    assert len(diags) == 1
    assert diags[0]["suggestion"] == "definitely"
    assert diags[0]["severity"] == "warning"


def test_misspelling_inflected_form():
    diags = _only(prose.lint_text("She recieved the package."), "misspelling")
    assert len(diags) == 1 and diags[0]["suggestion"] == "receive"


def test_spellcheck_near_miss_suggests():
    diags = _only(prose.lint_text("It is not necesary at all."), "spellcheck")
    assert len(diags) == 1
    assert diags[0]["suggestion"] == "necessary"
    assert diags[0]["severity"] == "suggestion"


def test_spellcheck_skips_known_inflections():
    text = "The features and services got updates without problems."
    assert _only(prose.lint_text(text), "spellcheck") == []


def test_hygiene_double_space_and_mixed_quotes():
    diags = _only(prose.lint_text("Hello  world."), "hygiene")
    assert any("consecutive spaces" in d["message"] for d in diags)
    mixed = _only(prose.lint_text('He said "yes" and “no” loudly.'), "hygiene")
    assert any("mixed straight and curly" in d["message"] for d in mixed)


def test_hygiene_skips_markdown_table_alignment():
    assert _only(prose.lint_text("| a  | b   |"), "hygiene") == []


# ---- extraction keeps real line numbers, drops code -------------------------


def test_markdown_fence_excluded_line_numbers_kept():
    text = "\n".join(
        [
            "Intro line.",
            "```",
            "teh teh = definately_code",
            "```",
            "This word is definately prose.",
        ]
    )
    diags = prose.lint_text(text)
    assert all(d["line"] != 3 for d in diags)  # nothing from inside the fence
    miss = _only(diags, "misspelling")
    assert len(miss) == 1 and miss[0]["line"] == 5


def test_markdown_inline_code_excluded():
    assert _only(prose.lint_text("Run `definately` now."), "misspelling") == []


def test_html_extraction_skips_script_keeps_lines():
    text = "\n".join(
        [
            "<html><body>",
            "<p>Hello hello world.</p>",
            "<script>var teh = teh;</script>",
            "</body></html>",
        ]
    )
    diags = prose.lint_text(text, fmt="html")
    doubled = _only(diags, "doubled_word")
    assert len(doubled) == 1 and doubled[0]["line"] == 2
    assert _only(diags, "misspelling") == []


def test_empty_text_no_diags():
    assert prose.lint_text("") == []


# ---- rules are policy-as-config ---------------------------------------------


def test_load_rules_overlay_merges_extends_disables(tmp_path):
    overlay = tmp_path / "org.json"
    overlay.write_text(
        json.dumps(
            {
                "passive_voice": False,
                "wordiness": {"phrases": {"circle back": "follow up"}},
                "misspelling": {"map": {"dottie": "Dottie"}},
            }
        ),
        encoding="utf-8",
    )
    rules = prose.load_rules(str(overlay))
    assert rules["passive_voice"]["enabled"] is False
    assert rules["wordiness"]["phrases"]["circle back"] == "follow up"
    assert rules["wordiness"]["phrases"]["in order to"] == "to"  # defaults kept
    assert rules["misspelling"]["map"]["teh"] == "the"

    text = "We should circle back. The report was written by the team."
    diags = prose.lint_text(text, rules=rules)
    assert _only(diags, "passive_voice") == []  # disabled by overlay
    assert any(d["suggestion"] == "follow up" for d in _only(diags, "wordiness"))


def test_load_rules_rejects_non_object(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    try:
        prose.load_rules(str(bad))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# ---- openswap family base ---------------------------------------------------


def test_diagnostic_normalizes_unknown_severity():
    d = openswap.diagnostic(path="x", line=1, rule="r", message="m", severity="wat")
    assert d["severity"] == "warning"


def test_sort_and_summarize():
    diags = [
        openswap.diagnostic(
            path="b.md", line=1, rule="r2", message="m", severity="info"
        ),
        openswap.diagnostic(
            path="a.md", line=9, rule="r1", message="m", severity="error"
        ),
        openswap.diagnostic(
            path="a.md", line=2, rule="r1", message="m", severity="warning"
        ),
    ]
    s = openswap.sort_diagnostics(diags)
    assert [d["path"] for d in s] == ["a.md", "a.md", "b.md"]
    assert s[0]["line"] == 2
    summary = openswap.summarize(diags)
    assert summary["total"] == 3
    assert summary["by_severity"]["error"] == 1
    assert summary["by_rule"] == {"r1": 2, "r2": 1}
    assert summary["files"] == ["a.md", "b.md"]


def test_detection_fallback_when_binary_absent(monkeypatch):
    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    native = openswap.probe_binary("harper-cli", probe_args=("core-version",))
    assert native["found"] is False and native["version"] is None
    cap = openswap.capability_report(
        "prose",
        native=native,
        fallback_scope="stdlib heuristics",
        install_hint="install harper-cli",
    )
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert cap["fallback_scope"] == "stdlib heuristics"
    assert cap["install_hint"] == "install harper-cli"


def test_detection_native_when_binary_present(monkeypatch):
    class _R:
        returncode = 0
        stdout = "harper-core 0.34.0\n"
        stderr = ""

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: "C:/fake/harper-cli.exe")
    monkeypatch.setattr(openswap.subprocess, "run", lambda *a, **k: _R())
    native = openswap.probe_binary("harper-cli", probe_args=("core-version",))
    assert native["found"] is True
    assert native["version"] == "harper-core 0.34.0"
    cap = openswap.capability_report("prose", native=native, fallback_scope="x")
    assert cap["tier"] == openswap.TIER_NATIVE
    assert "install_hint" not in cap


def test_detection_unavailable_without_fallback():
    cap = openswap.capability_report(
        "x", native={"found": False}, install_hint="get it"
    )
    assert cap["tier"] == openswap.TIER_UNAVAILABLE
    assert cap["install_hint"] == "get it"


# ---- harper output normalizes into the same schema --------------------------


def test_parse_harper_output_normalizes():
    raw = json.dumps(
        [
            {
                "lint_kind": "Spelling",
                "message": "Did you mean 'the'?",
                "line": 3,
                "suggestions": ["the"],
            },
            {"kind": "Grammar", "message": "Doubled word.", "span": {"start_line": 7}},
            "not-a-dict",
            {"no_message": True},
        ]
    )
    diags = prose.parse_harper_output(raw, path="doc.md")
    assert len(diags) == 2
    assert diags[0]["rule"] == "harper:spelling"
    assert diags[0]["source"] == "harper"
    assert diags[0]["line"] == 3 and diags[0]["suggestion"] == "the"
    assert diags[1]["line"] == 7


def test_parse_harper_output_garbage_degrades_to_empty():
    assert prose.parse_harper_output("not json at all", path="x") == []
    assert prose.parse_harper_output('{"lints": 42}', path="x") == []


# ---- the real CLI in a subprocess -------------------------------------------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(cwd or ROOT),
    )


def test_cli_prose_hello_envelope():
    r = _cli(["prose", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True
    assert "example" in data


def test_cli_prose_lint_and_gate(tmp_path):
    doc = tmp_path / "sample.md"
    doc.write_text(
        "This is is definately a test in order to check the the linter.\n",
        encoding="utf-8",
    )
    r = _cli(["prose", "lint", str(doc)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    body = data["data"]
    assert body["tier"] in ("native", "fallback")
    assert body["summary"]["total"] >= 3
    rules_seen = {d["rule"] for d in body["diagnostics"]}
    assert {"doubled_word", "misspelling", "wordiness"} <= rules_seen
    # the pre-publish gate hook: same file, gated on warnings -> exit 1
    gated = _cli(["prose", "lint", str(doc), "--fail-on", "warning"])
    assert gated.returncode == 1
