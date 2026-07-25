"""Readability — openswap #21 (Hemingway Editor Plus -> local arithmetic).

Shipped as a MODULE OF #1 (`scout prose score` / `prose report` + a `readability`
rule inside `prose lint`), so these tests cover bigbang/core/readability.py, its
integration into prose's check registry and rules overlay, and the two new CLI
surfaces. Offline and deterministic by construction: the scorer is pure
arithmetic, the plugin manifest denies the network axis, and the only I/O is a
tmp_path HTML write whose capability gate is exercised in both directions.

Every expected number below was computed by hand from the published formula (the
test docstrings carry the arithmetic) rather than recorded from a run, so a
change in tokenizing, syllable counting or sentence splitting fails the test
instead of quietly re-baselining it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import typer
import yaml

from bigbang.core import openswap, prose, readability

ROOT = Path(__file__).resolve().parents[1]

# 33 words, one sentence, dense polysyllables: over every default budget.
HARD_TEXT = (
    "The implementation of the readability configuration documentation was "
    "subsequently approved by the administration committee, which unfortunately "
    "determined that the organizational communication infrastructure required "
    "additional documentation before the international collaboration initiative "
    "could be operationalized."
)
# 40 words in 8 monosyllabic sentences (4 of 6 words, 4 of 4): under every budget.
PLAIN_TEXT = "The cat sat on the mat. The dog ran fast. " * 4
# 34 words, 4 sentences, consensus grade ~6.7: passes the default gate at 12 and
# fails a tightened one, which is what makes --target-grade falsifiable.
MEDIUM_TEXT = (
    "The team shipped the new release to every customer last week. "
    "The next update will land soon. "
) * 2


def _rules(**readability_overrides):
    rules = prose.load_rules(None)
    rules["readability"].update(readability_overrides)
    return rules


def _rule_ids(diags):
    return [d["rule"] for d in diags]


# ---- syllables: the documented heuristic, hand-checked --------------------


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("cat", 1),          # <=3 letters short-circuit
        ("the", 1),
        ("apple", 2),        # -le keeps its syllable
        ("syllable", 3),
        ("readability", 5),
        ("make", 1),         # silent final -e dropped
        ("walked", 1),       # silent -ed
        ("wanted", 2),       # -ed after t is spoken
        ("makes", 1),        # silent -es
        ("houses", 2),       # -es after a sibilant is spoken
        ("prices", 2),
        ("immediately", 5),
        ("utilize", 3),
        ("sophisticated", 5),
        ("infrastructure", 4),
        ("documentation", 5),
        ("readable", 3),
        ("quickly", 2),
        ("really", 2),
        ("coffee", 2),       # -ee is not a silent e
    ],
)
def test_syllable_heuristic_matches_hand_counts(word, expected):
    assert readability.count_syllables(word) == expected


@pytest.mark.parametrize("word", sorted(readability.SYLLABLE_EXCEPTIONS))
def test_syllable_exceptions_are_used(word):
    """The pinned list must actually win over the vowel-group count."""
    assert readability.count_syllables(word) == readability.SYLLABLE_EXCEPTIONS[word]


def test_syllable_exceptions_fix_the_known_wrong_cases():
    # vowel-group counting alone would say 1 for these (adjacent vowels + silent e)
    assert readability.count_syllables("create") == 2
    assert readability.count_syllables("science") == 2
    assert readability.count_syllables("idea") == 3
    assert readability.count_syllables("area") == 3
    assert readability.count_syllables("business") == 2


def test_syllables_ignore_case_and_punctuation():
    assert readability.count_syllables("Documentation!") == 5
    assert readability.count_syllables("READABILITY") == 5
    assert readability.count_syllables("re-run") == 2


def test_numerals_have_no_syllables_and_words_have_at_least_one():
    assert readability.count_syllables("2026") == 0
    assert readability.count_syllables("9.5") == 0
    assert readability.count_syllables("") == 0
    assert readability.count_syllables("rhythms") >= 1


# ---- tokenizing -----------------------------------------------------------


def test_words_exclude_pure_numerals_and_numerals_are_reported():
    text = "We shipped 3 builds in 2026 without regressions."
    assert readability.words_of(text) == [
        "We", "shipped", "builds", "in", "without", "regressions",
    ]
    assert readability.numeric_tokens(text) == ["3", "2026"]


def test_word_definition_is_shared_with_prose():
    """A second tokenizer would let the linter and the scorer disagree."""
    assert readability.words_of("it's re-run") == prose.WORD_RE.findall("it's re-run")


def test_numeric_exclusion_shows_up_in_the_counts():
    rep = readability.score_text("We shipped 3 builds in 2026.", path="d.md")
    assert rep["counts"]["words"] == 4  # "3" and "2026" are not words here
    assert rep["counts"]["numeric_excluded"] == 2


# ---- sentence splitting: the denominator of every formula ------------------


def test_plain_sentence_split():
    assert readability.split_sentences("One. Two. Three.") == ["One.", "Two.", "Three."]


def test_split_handles_question_and_exclamation():
    assert len(readability.split_sentences("Really? Yes! Fine.")) == 3


def test_abbreviation_is_not_a_sentence_end():
    out = readability.split_sentences("Dr. Smith left. He returned.")
    assert out == ["Dr. Smith left.", "He returned."]


def test_initials_are_not_sentence_ends():
    out = readability.split_sentences("See e.g. the docs. Then stop.")
    assert out == ["See e.g. the docs.", "Then stop."]


def test_decimal_is_not_a_sentence_end():
    assert readability.split_sentences("Version 9.5 shipped clean.") == [
        "Version 9.5 shipped clean."
    ]


def test_lowercase_continuation_is_not_a_sentence_end():
    assert readability.split_sentences("Wait... it works.") == ["Wait... it works."]


def test_closing_quote_after_terminator_still_ends_a_sentence():
    out = readability.split_sentences('He said "stop." Then he left.')
    assert len(out) == 2
    assert out[0].endswith('"')


def test_unterminated_tail_is_still_a_sentence():
    assert readability.split_sentences("no terminator here") == ["no terminator here"]
    assert readability.split_sentences("") == []


def test_abbreviation_guard_changes_the_grade():
    """The guard is load-bearing: naive splitting halves words-per-sentence."""
    text = "Ship the docs e.g. the release notes and the changelog to the team."
    assert len(readability.split_sentences(text)) == 1


# ---- gunning fog's complex-word rule --------------------------------------


@pytest.mark.parametrize(
    ("word", "complex_"),
    [
        ("documentation", True),
        ("readable", True),
        ("beautiful", True),
        ("cat", False),
        ("houses", False),
        ("created", False),    # 3 syllables only because of -ed
        ("processes", False),  # 3 syllables only because of -es
    ],
)
def test_complex_word_rule(word, complex_):
    assert readability.is_complex(word) is complex_


# ---- adverb + passive flags ----------------------------------------------


def test_adverbs_flag_ly_words_only():
    text = "She quickly and unfortunately replied badly to the family supply."
    assert readability.adverbs_of(text) == ["quickly", "unfortunately", "badly"]


def test_short_ly_words_are_not_adverbs():
    assert readability.adverbs_of("only the ugly holy fly can rely") == []


def test_non_adverb_ly_list_is_all_reachable():
    """Dead policy data is a defect: every entry must match the -ly pattern."""
    for word in readability.NON_ADVERB_LY:
        assert readability._LY_RE.match(word), word
        assert readability.adverbs_of(f"the {word} here") == []


def test_passive_hits_use_the_prose_matcher():
    rules = prose.load_rules(None)
    assert readability.passive_hits("The report was written by the team.", rules) == [
        "was written"
    ]
    # tuning PROSE's rule must change the SCORER's answer — one matcher, not two
    rules["passive_voice"]["irregular_participles"] = []
    assert readability.passive_hits("The report was written by the team.", rules) == []
    assert readability.passive_hits("The build was completed today.", rules) == [
        "was completed"
    ]


def test_passive_respects_prose_not_participles():
    assert readability.passive_hits("The light is red.", prose.load_rules(None)) == []


def test_passive_falls_back_to_prose_defaults_without_rules():
    assert readability.passive_hits("The bug was fixed.") == ["was fixed"]


# ---- the formulas, from the published definitions -------------------------


def test_flesch_reading_ease_formula():
    """206.835 - 1.015*(100/10) - 84.6*(150/100) = 69.785"""
    assert readability.flesch_reading_ease(100, 10, 150) == pytest.approx(69.785)


def test_flesch_kincaid_formula():
    """0.39*(100/10) + 11.8*(150/100) - 15.59 = 6.01"""
    assert readability.flesch_kincaid_grade(100, 10, 150) == pytest.approx(6.01)


def test_gunning_fog_formula():
    """0.4*[(100/10) + 100*(20/100)] = 12.0"""
    assert readability.gunning_fog(100, 10, 20) == pytest.approx(12.0)


def test_coleman_liau_formula():
    """0.0588*500 - 0.296*10 - 15.8 = 10.64 (letters/sentences per 100 words)"""
    assert readability.coleman_liau(100, 10, 500) == pytest.approx(10.64)


def test_formulas_return_none_on_empty_input():
    for fn in (
        readability.flesch_reading_ease,
        readability.flesch_kincaid_grade,
        readability.gunning_fog,
        readability.coleman_liau,
    ):
        assert fn(0, 0, 0) is None
        assert fn(10, 0, 10) is None
        assert fn(0, 2, 10) is None


@pytest.mark.parametrize(
    ("ease", "label"),
    [
        (95.0, "very easy"),
        (85.0, "easy"),
        (75.0, "fairly easy"),
        (65.0, "plain english"),
        (55.0, "fairly difficult"),
        (40.0, "difficult"),
        (10.0, "very confusing"),
        (-20.0, "very confusing"),
        (None, "no data"),
    ],
)
def test_ease_bands(ease, label):
    assert readability.ease_label(ease) == label


# ---- document scoring: exact counts --------------------------------------


def test_document_counts_and_scores_are_exact():
    """10 words / 2 sentences / 10 syllables / 30 letters:
    ease  = 206.835 - 1.015*5 - 84.6*1.0   = 117.16
    fk    = 0.39*5 + 11.8*1.0 - 15.59      =  -1.84
    fog   = 0.4*(5 + 100*0/10)             =   2.00
    cl    = 0.0588*300 - 0.296*20 - 15.8   =  -4.08
    """
    rep = readability.score_text("The cat sat on the mat. The dog ran fast.", path="d.md")
    c = rep["counts"]
    assert c["words"] == 10
    assert c["sentences"] == 2
    assert c["paragraphs"] == 1
    assert c["syllables"] == 10
    assert c["letters"] == 30
    assert c["complex_words"] == 0
    a = rep["averages"]
    assert a["words_per_sentence"] == 5.0
    assert a["syllables_per_word"] == 1.0
    assert a["letters_per_word"] == 3.0
    s = rep["scores"]
    assert s["flesch_reading_ease"] == pytest.approx(117.16, abs=0.01)
    assert s["flesch_kincaid_grade"] == pytest.approx(-1.84, abs=0.01)
    assert s["gunning_fog"] == pytest.approx(2.0, abs=0.01)
    assert s["coleman_liau"] == pytest.approx(-4.08, abs=0.01)
    assert s["consensus_grade"] == pytest.approx(-1.84, abs=0.01)
    assert rep["ease_label"] == "very easy"
    assert rep["path"] == "d.md"
    assert rep["format"] == "markdown"


def test_consensus_grade_is_the_median_of_the_three_grade_metrics():
    rep = readability.score_text(HARD_TEXT, path="d.md")
    s = rep["scores"]
    grades = sorted([s["flesch_kincaid_grade"], s["gunning_fog"], s["coleman_liau"]])
    assert s["consensus_grade"] == pytest.approx(grades[1], abs=0.01)


def test_empty_text_scores_to_no_data_instead_of_zero():
    rep = readability.score_text("", path="d.md")
    assert rep["counts"]["words"] == 0
    assert rep["counts"]["sentences"] == 0
    assert rep["scores"]["flesch_kincaid_grade"] is None
    assert rep["scores"]["consensus_grade"] is None
    assert rep["ease_label"] == "no data"
    assert rep["over_target"] is False
    assert rep["reliable"] is False
    assert rep["paragraphs"] == []


def test_hard_text_is_over_target_and_plain_text_is_not():
    hard = readability.score_text(HARD_TEXT, path="h.md")
    plain = readability.score_text(PLAIN_TEXT, path="p.md")
    assert hard["counts"]["words"] == 33
    assert hard["counts"]["sentences"] == 1
    assert hard["scores"]["consensus_grade"] > 12.0
    assert hard["over_target"] is True
    assert hard["reliable"] is True
    assert plain["counts"]["words"] == 40
    assert plain["counts"]["sentences"] == 8
    assert plain["over_target"] is False
    assert plain["reliable"] is True
    assert plain["target_grade"] == readability.DEFAULT_CONFIG["max_grade"]


def test_target_grade_is_config_not_hardcoded():
    strict = readability.score_text(PLAIN_TEXT, path="p.md", rules=_rules(max_grade=-5.0))
    assert strict["target_grade"] == -5.0
    assert strict["over_target"] is True


def test_min_words_floor_marks_short_samples_unreliable():
    rep = readability.score_text("The cat sat on the mat.", path="d.md")
    assert rep["counts"]["words"] < readability.DEFAULT_CONFIG["min_words"]
    assert rep["reliable"] is False
    assert any("below min_words" in n for n in rep["notes"])
    # the scores are still reported — unreliable is not the same as hidden
    assert rep["scores"]["flesch_kincaid_grade"] is not None


def test_notes_always_declare_the_heuristics():
    notes = " ".join(readability.score_text(PLAIN_TEXT, path="p.md")["notes"])
    assert "syllables are heuristic" in notes
    assert "coleman_liau" in notes
    assert "gunning_fog omits" in notes
    assert "numerals" in notes
    assert "passive ratio as a floor" in notes


# ---- sentence histogram --------------------------------------------------


def test_histogram_covers_every_bucket_and_sums_to_the_sentence_count():
    rep = readability.score_text(PLAIN_TEXT, path="p.md")
    hist = rep["histogram"]
    assert [row["bucket"] for row in hist] == [b[0] for b in readability.HISTOGRAM_BUCKETS]
    assert sum(row["count"] for row in hist) == rep["counts"]["sentences"] == 8
    counts = {row["bucket"]: row["count"] for row in hist}
    assert counts["1-5"] == 4  # "The dog ran fast." x4
    assert counts["6-10"] == 4  # "The cat sat on the mat." x4
    assert {row["pct"] for row in hist if row["count"]} == {50.0}
    assert all(row["count"] == 0 for row in hist if row["bucket"] not in ("1-5", "6-10"))


def test_histogram_bucket_boundaries():
    counts = {row["bucket"]: row["count"] for row in readability.histogram([1, 5, 6, 10, 41, 200])}
    assert counts["1-5"] == 2
    assert counts["6-10"] == 2
    assert counts["41+"] == 2
    assert counts["11-15"] == 0


def test_histogram_of_nothing_is_all_zeros():
    rows = readability.histogram([])
    assert len(rows) == len(readability.HISTOGRAM_BUCKETS)
    assert all(row["count"] == 0 and row["pct"] == 0.0 for row in rows)


def test_long_sentence_lands_in_the_long_bucket_and_is_reported():
    rep = readability.score_text(" ".join(["word"] * 45) + ".", path="d.md")
    counts = {row["bucket"]: row["count"] for row in rep["histogram"]}
    assert counts["41+"] == 1
    assert rep["sentences"]["longest"]["words"] == 45


# ---- per-sentence and per-paragraph difficulty ---------------------------


def test_hard_sentence_is_banded_and_counted():
    rep = readability.score_text(HARD_TEXT, path="h.md")
    assert rep["sentences"]["total"] == 1
    assert rep["sentences"]["very_hard"] == 1
    assert rep["sentences"]["hard"] == 0
    worst = rep["sentences"]["worst"]
    assert len(worst) == 1
    assert worst[0]["band"] == readability.BAND_VERY_HARD
    assert worst[0]["grade"] > readability.DEFAULT_CONFIG["very_hard_grade"]


def test_plain_sentences_are_never_banded_hard():
    rep = readability.score_text(PLAIN_TEXT, path="p.md")
    assert rep["sentences"]["hard"] == 0
    assert rep["sentences"]["very_hard"] == 0
    assert rep["sentences"]["worst"] == []
    assert all(p["band"] == readability.BAND_PLAIN for p in rep["paragraphs"])


def test_short_sentence_floor_suppresses_the_band_but_reports_the_grade():
    rep = readability.score_text("Immediately!", path="d.md")
    row = rep["sentences"]["longest"]
    assert row["words"] == 1
    assert row["graded"] is False
    assert row["band"] == readability.BAND_PLAIN
    assert row["grade"] > readability.DEFAULT_CONFIG["very_hard_grade"]
    assert rep["sentences"]["ungraded_short"] == 1


def test_min_sentence_words_is_config_not_hardcoded():
    rep = readability.score_text(
        "Immediately!", path="d.md", rules=_rules(min_sentence_words=1)
    )
    assert rep["sentences"]["very_hard"] == 1
    assert rep["sentences"]["longest"]["band"] == readability.BAND_VERY_HARD


def test_band_thresholds_are_config():
    rep = readability.score_text(
        PLAIN_TEXT, path="p.md", rules=_rules(hard_grade=-3.0, very_hard_grade=99.0)
    )
    # the four 6-word sentences band hard; the four 4-word ones stay under the
    # min_sentence_words floor and are never banded at all
    assert rep["sentences"]["hard"] == 4
    assert rep["sentences"]["very_hard"] == 0
    assert rep["sentences"]["ungraded_short"] == 4
    assert len(rep["sentences"]["worst"]) == 4


def test_paragraphs_keep_real_line_numbers_and_their_own_scores():
    text = "The cat sat on the mat.\n\n" + HARD_TEXT + "\n"
    rep = readability.score_text(text, path="d.md")
    paras = rep["paragraphs"]
    assert len(paras) == 2
    assert [p["index"] for p in paras] == [1, 2]
    assert paras[0]["line"] == 1
    assert paras[1]["line"] == 3
    assert paras[0]["band"] == readability.BAND_PLAIN
    assert paras[1]["band"] == readability.BAND_VERY_HARD
    assert paras[1]["very_hard"] == 1
    assert paras[0]["very_hard"] == 0
    assert paras[1]["words"] == 33
    # document sentence total is the sum of the paragraph splits
    assert rep["counts"]["sentences"] == sum(p["sentences"] for p in paras)


def test_paragraph_preview_is_truncated_not_dropped():
    rep = readability.score_text("word " * 200 + ".", path="d.md")
    text = rep["paragraphs"][0]["text"]
    assert len(text) <= 240
    assert text.endswith("...")


# ---- flags: adverb and passive budgets -----------------------------------


def test_hard_text_blows_both_budgets():
    flags = readability.score_text(HARD_TEXT, path="h.md")["flags"]
    adv = flags["adverbs"]
    assert adv["count"] == 2
    assert adv["examples"] == ["subsequently", "unfortunately"]
    assert adv["per_100_words"] == pytest.approx(100 * 2 / 33, abs=0.01)
    assert adv["over_budget"] is True
    pas = flags["passive"]
    # "could be operationalized" is caught; "was subsequently approved" is NOT —
    # the shared matcher needs the participle adjacent to the auxiliary, which is
    # exactly the limitation the report's notes declare.
    assert pas["count"] == 1
    assert pas["examples"] == ["be operationalized"]
    assert pas["pct_of_sentences"] == 100.0
    assert pas["over_budget"] is True


def test_plain_text_is_inside_both_budgets():
    flags = readability.score_text(PLAIN_TEXT, path="p.md")["flags"]
    assert flags["adverbs"]["count"] == 0
    assert flags["adverbs"]["over_budget"] is False
    assert flags["passive"]["count"] == 0
    assert flags["passive"]["over_budget"] is False


def test_budgets_are_config():
    flags = readability.score_text(
        HARD_TEXT, path="h.md", rules=_rules(adverbs_per_100_words=50.0, passive_pct=100.0)
    )["flags"]
    assert flags["adverbs"]["budget_per_100_words"] == 50.0
    assert flags["adverbs"]["over_budget"] is False
    assert flags["passive"]["over_budget"] is False


def test_examples_are_capped_by_config():
    text = "It was quickly, sadly, badly, wildly, gladly, harshly done. " * 2
    flags = readability.score_text(text, path="d.md", rules=_rules(examples=2))["flags"]
    assert flags["adverbs"]["count"] == 12
    assert len(flags["adverbs"]["examples"]) == 2


# ---- extraction is inherited from prose ----------------------------------


def test_markdown_code_fences_are_not_scored():
    text = (
        "Plain words here.\n\n"
        "```\n"
        "utilize sophisticated infrastructure documentation immediately\n"
        "```\n"
    )
    rep = readability.score_text(text, path="d.md", fmt="markdown")
    assert rep["counts"]["words"] == 3
    assert rep["counts"]["paragraphs"] == 1
    # the same bytes as plain text DO count the snippet — proof the fence rule ran
    raw = readability.score_text(text, path="d.txt", fmt="text")
    assert raw["counts"]["words"] == 8


def test_inline_code_and_urls_are_not_scored():
    rep = readability.score_text(
        "Run `utilize documentation` at https://example.com/documentation now.",
        path="d.md",
    )
    assert rep["counts"]["words"] == 3


def test_markdown_table_rows_are_not_scored_as_sentences():
    """A table row has no terminator and would read as one enormous sentence."""
    text = (
        "The release is ready.\n\n"
        "| service | state | note |\n"
        "|---|---|---|\n"
        "| api | up | responded to every probe within the configured budget |\n"
    )
    rep = readability.score_text(text, path="d.md")
    assert rep["counts"]["words"] == 4
    assert rep["counts"]["sentences"] == 1
    assert rep["counts"]["paragraphs"] == 1
    assert rep["counts"]["table_rows_skipped"] == 3
    assert rep["sentences"]["longest"]["words"] == 4


def test_strip_tables_keeps_line_numbers():
    lines = ["Prose here.", "| a | b |", "More prose."]
    assert readability.strip_tables(lines) == ["Prose here.", "", "More prose."]
    rep = readability.score_lines(lines, path="d.md")
    assert [p["line"] for p in rep["paragraphs"]] == [1, 3]


def test_blanked_code_sentinels_never_reach_the_output():
    rep = readability.score_text("Run `scout prose lint README.md` now please.", path="d.md")
    text = rep["paragraphs"][0]["text"]
    assert "\x00" not in text
    assert text == "Run now please."
    assert readability.clean_text("a\x00\x00\x00b") == "a b"


def test_html_script_is_not_scored():
    text = "<p>Hello there world.</p>\n<script>utilize documentation immediately</script>"
    rep = readability.score_text(text, path="d.html", fmt="html")
    assert rep["counts"]["words"] == 3
    assert rep["format"] == "html"


# ---- diagnostics ride the family schema ----------------------------------


def test_diagnostics_for_hard_text_cover_grade_sentence_and_budgets():
    rep = readability.score_text(HARD_TEXT, path="h.md")
    diags = readability.to_diagnostics(rep)
    rules_seen = _rule_ids(diags)
    assert "readability:grade" in rules_seen
    assert "readability:very_hard-sentence" in rules_seen
    assert "readability:adverbs" in rules_seen
    assert "readability:passive" in rules_seen
    for d in diags:
        assert d["path"] == "h.md"
        assert d["severity"] in openswap.SEVERITIES
        assert d["source"] == "core"
        assert d["line"] >= 1
    grade = next(d for d in diags if d["rule"] == "readability:grade")
    assert "above target 12.0" in grade["message"]
    assert grade["severity"] == "suggestion"


def test_capped_example_list_says_so():
    """Five findings out of eleven must never read as "that was all of them"."""
    rep = readability.score_text(" ".join([HARD_TEXT] * 6), path="h.md")
    assert rep["sentences"]["very_hard"] == 6
    assert len(rep["sentences"]["worst"]) == 5
    note = next(
        d for d in readability.to_diagnostics(rep) if d["rule"] == "readability:sentences"
    )
    assert "6 sentences over the difficulty threshold" in note["message"]
    assert "6 very hard, 0 hard" in note["message"]
    assert "the 5 worst are listed above" in note["message"]
    assert note["severity"] == "info"


def test_no_cap_note_when_everything_is_shown():
    rep = readability.score_text(HARD_TEXT, path="h.md")
    assert rep["sentences"]["very_hard"] == 1
    assert [
        d for d in readability.to_diagnostics(rep) if d["rule"] == "readability:sentences"
    ] == []


def test_plain_text_produces_no_diagnostics():
    rep = readability.score_text(PLAIN_TEXT, path="p.md")
    assert readability.to_diagnostics(rep) == []


def test_unreliable_sample_raises_no_document_finding():
    rep = readability.score_text("Utilize documentation immediately.", path="d.md")
    assert rep["reliable"] is False
    assert [d for d in readability.to_diagnostics(rep) if d["rule"] == "readability:grade"] == []


def test_sentence_diagnostic_anchors_to_its_paragraph_line():
    text = "The cat sat on the mat.\n\n" + HARD_TEXT + "\n"
    diags = readability.to_diagnostics(readability.score_text(text, path="d.md"))
    sentence = next(d for d in diags if d["rule"].endswith("-sentence"))
    assert sentence["line"] == 3


def test_diagnostic_severity_is_config():
    rep = readability.score_text(HARD_TEXT, path="h.md", rules=_rules(severity="error"))
    diags = readability.to_diagnostics(rep, rules=_rules(severity="error"))
    grade = next(d for d in diags if d["rule"] == "readability:grade")
    assert grade["severity"] == "error"


def test_diagnostics_summarize_under_the_shared_contract():
    diags = readability.to_diagnostics(readability.score_text(HARD_TEXT, path="h.md"))
    summary = openswap.summarize(diags)
    assert summary["total"] == len(diags)
    assert summary["files"] == ["h.md"]
    assert summary["by_rule"]["readability:grade"] == 1


# ---- integration with prose (#1) -----------------------------------------


def test_readability_is_registered_once_in_prose_checks():
    assert prose._check_readability in prose.CHECKS
    assert prose.CHECKS.count(prose._check_readability) == 1


def test_prose_lint_emits_readability_findings():
    rules_seen = {d["rule"] for d in prose.lint_text(HARD_TEXT)}
    assert "readability:grade" in rules_seen
    assert "readability:very_hard-sentence" in rules_seen
    # and the grammar rules still fire on the same text
    assert "passive_voice" in rules_seen


def test_prose_lint_on_empty_text_stays_empty():
    assert prose.lint_text("") == []
    assert prose.lint_text("\n\n   \n") == []


def test_load_rules_injects_readability_defaults_as_a_copy():
    rules = prose.load_rules(None)
    assert rules["readability"]["max_grade"] == readability.DEFAULT_CONFIG["max_grade"]
    assert rules["readability"]["enabled"] is True
    rules["readability"]["max_grade"] = 1.0
    assert readability.DEFAULT_CONFIG["max_grade"] != 1.0


def test_rules_overlay_tunes_readability_without_losing_defaults(tmp_path):
    overlay = tmp_path / "org.json"
    overlay.write_text(json.dumps({"readability": {"max_grade": 4.0}}), encoding="utf-8")
    rules = prose.load_rules(str(overlay))
    assert rules["readability"]["max_grade"] == 4.0
    assert rules["readability"]["hard_grade"] == readability.DEFAULT_CONFIG["hard_grade"]
    # the overlaid target reaches the scorer, not just the rules dump
    grade = next(
        d for d in prose.lint_text(HARD_TEXT, rules=rules) if d["rule"] == "readability:grade"
    )
    assert "above target 4.0" in grade["message"]
    # MEDIUM_TEXT is over 4.0 but under the shipped 12.0 default
    assert any(
        d["rule"] == "readability:grade" for d in prose.lint_text(MEDIUM_TEXT, rules=rules)
    )
    assert not any(
        d["rule"] == "readability:grade" for d in prose.lint_text(MEDIUM_TEXT)
    )


def test_rules_overlay_can_disable_readability(tmp_path):
    overlay = tmp_path / "org.json"
    overlay.write_text(json.dumps({"readability": False}), encoding="utf-8")
    rules = prose.load_rules(str(overlay))
    assert rules["readability"]["enabled"] is False
    diags = prose.lint_text(HARD_TEXT, rules=rules)
    assert [d for d in diags if d["rule"].startswith("readability:")] == []
    assert diags, "disabling readability must not disable the grammar rules"


def test_readability_check_signature_matches_the_registry():
    lines = prose.extract_markdown(HARD_TEXT)
    diags = readability.readability_check(lines, prose.load_rules(None), "h.md")
    assert diags and all(d["rule"].startswith("readability:") for d in diags)
    assert readability.readability_check([], prose.load_rules(None), "h.md") == []
    assert readability.readability_check(["   ", ""], prose.load_rules(None), "h.md") == []


def test_paragraph_boundaries_are_shared_with_prose():
    lines = ["First line.", "", "Second block."]
    assert list(prose.paragraphs(lines)) == [(1, "First line."), (3, "Second block.")]
    rep = readability.score_lines(lines, path="d.md")
    assert [p["line"] for p in rep["paragraphs"]] == [1, 3]


# ---- the HTML artifact ---------------------------------------------------


def test_render_html_is_self_contained():
    page = readability.render_html([readability.score_text(HARD_TEXT, path="h.md")])
    assert page.startswith("<!DOCTYPE html>")
    assert "<style>" in page
    assert "http://" not in page
    assert "https://" not in page
    assert "<script" not in page.lower()
    assert "src=" not in page
    assert "@import" not in page


def test_render_html_carries_every_paragraph_with_its_band():
    text = "The cat sat on the mat.\n\n" + HARD_TEXT + "\n"
    page = readability.render_html(
        [readability.score_text(text, path="d.md")], title="digest draft"
    )
    assert "<title>digest draft</title>" in page
    assert "digest draft" in page
    assert "Per-paragraph difficulty" in page
    assert 'class="para b-very_hard"' in page
    assert 'class="para b-plain"' in page
    assert "The cat sat on the mat." in page
    assert "flesch reading ease" in page
    assert "coleman-liau" in page
    assert 'class="bar"' in page
    assert "syllables are heuristic" in page


def test_render_html_escapes_prose_that_contains_markup():
    rep = readability.score_text("<b>bold</b> & <i>italic</i> words here.", path="d.txt", fmt="text")
    page = readability.render_html([rep])
    assert "&lt;b&gt;bold&lt;/b&gt;" in page
    assert "<b>bold</b>" not in page
    assert "&amp;" in page


def test_render_html_states_the_no_data_case():
    page = readability.render_html([])
    assert "No files scored" in page
    assert "invented score" in page


def test_render_html_flags_a_sample_too_small_to_gate():
    page = readability.render_html([readability.score_text("Short doc here.", path="d.md")])
    assert "Sample too small to gate" in page
    assert "no finding is raised" in page


def test_render_html_shows_the_flag_counts():
    page = readability.render_html([readability.score_text(HARD_TEXT, path="h.md")])
    assert "Adverbs 2" in page
    assert "budget 2.0" in page


# ---- manifest: capabilities stay declared and default-deny ---------------


def test_manifest_denies_network_and_declares_only_the_report_write():
    mf = yaml.safe_load(
        (ROOT / "bigbang" / "plugins" / "prose" / "manifest.yaml").read_text(encoding="utf-8")
    )
    caps = mf["capabilities"]
    assert caps["network"]["enabled"] is False
    assert caps["network"]["domains"] == []
    assert caps["filesystem"]["write"] is True
    assert caps["filesystem"]["paths"] == [".scout"]
    assert caps["secrets"]["allow"] == []
    from bigbang.core.policy import check_permission

    assert check_permission(mf, "fs_write", ".scout/readability.html")[0] is True
    assert check_permission(mf, "network", "https://example.com")[0] is False


def test_report_write_is_capability_gated(monkeypatch, tmp_path):
    """Remove the declared capability and the page must NOT be written."""
    from bigbang.plugins.prose import cli as prose_cli

    src = tmp_path / "doc.md"
    src.write_text(PLAIN_TEXT, encoding="utf-8")
    out = tmp_path / "denied.html"
    monkeypatch.setattr(
        prose_cli,
        "_MANIFEST",
        {"name": "prose", "capabilities": {"filesystem": {"write": False}}},
    )
    with pytest.raises(typer.Exit) as exc:
        prose_cli.report(
            [str(src)], out=str(out), title="x", rules_file=None,
            target_grade=None, fail_on=None,
        )
    assert exc.value.exit_code == 1
    assert not out.exists()


# ---- the real CLI in a subprocess (offline: no network surface exists) ----


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        cwd=str(cwd or ROOT),
    )


def _doc(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_cli_score_envelope_and_payload(tmp_path):
    doc = _doc(tmp_path, "hard.md", HARD_TEXT + "\n")
    r = _cli(["prose", "score", str(doc)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["command"] == "prose score"
    assert "example" in data
    body = data["data"]
    assert body["scorer"] == "stdlib-readability"
    assert body["tier"] in ("native", "fallback")
    assert body["files"] == [str(doc)]
    assert body["target_grade"] == 12.0
    assert body["hardest"]["path"] == str(doc)
    assert body["hardest"]["consensus_grade"] > 12.0
    report = body["reports"][0]
    assert report["counts"]["words"] == 33
    assert report["over_target"] is True
    assert report["histogram"]
    assert report["notes"]
    assert body["summary"]["by_rule"]["readability:grade"] == 1


def test_cli_score_of_plain_prose_reports_nothing_to_fix(tmp_path):
    doc = _doc(tmp_path, "plain.md", PLAIN_TEXT + "\n")
    r = _cli(["prose", "score", str(doc)])
    assert r.returncode == 0, r.stderr + r.stdout
    body = json.loads(r.stdout)["data"]
    assert body["summary"]["total"] == 0
    assert body["diagnostics"] == []
    assert body["reports"][0]["over_target"] is False


def test_cli_score_gate_respects_severity(tmp_path):
    doc = _doc(tmp_path, "hard.md", HARD_TEXT + "\n")
    assert _cli(["prose", "score", str(doc), "--fail-on", "suggestion"]).returncode == 1
    # nothing here is error-severity, so the strict gate must PASS
    assert _cli(["prose", "score", str(doc), "--fail-on", "error"]).returncode == 0
    plain = _doc(tmp_path, "plain.md", PLAIN_TEXT + "\n")
    assert _cli(["prose", "score", str(plain), "--fail-on", "info"]).returncode == 0


def test_cli_score_target_grade_flips_the_gate(tmp_path):
    doc = _doc(tmp_path, "medium.md", MEDIUM_TEXT + "\n")
    loose = _cli(["prose", "score", str(doc), "--fail-on", "suggestion"])
    assert loose.returncode == 0, loose.stdout
    grade = json.loads(loose.stdout)["data"]["reports"][0]["scores"]["consensus_grade"]
    assert 5.0 < grade < 12.0
    tight = _cli([
        "prose", "score", str(doc), "--target-grade", "5", "--fail-on", "suggestion"
    ])
    assert tight.returncode == 1
    assert json.loads(tight.stdout)["data"]["target_grade"] == 5.0


def test_cli_score_rejects_bad_flags(tmp_path):
    doc = _doc(tmp_path, "plain.md", PLAIN_TEXT + "\n")
    bad_sev = _cli(["prose", "score", str(doc), "--fail-on", "loud"])
    assert bad_sev.returncode == 1
    assert "--fail-on must be one of" in bad_sev.stdout
    bad_grade = _cli(["prose", "score", str(doc), "--target-grade", "0"])
    assert bad_grade.returncode == 1
    assert "--target-grade must be > 0" in bad_grade.stdout
    missing = _cli(["prose", "score", str(tmp_path / "nope.md")])
    assert missing.returncode == 1
    assert "path not found" in missing.stdout


def test_cli_score_caps_paragraph_rows(tmp_path):
    body = "\n\n".join([f"Paragraph number {i} sits here." for i in range(6)])
    doc = _doc(tmp_path, "many.md", body + "\n")
    data = json.loads(_cli(["prose", "score", str(doc), "--max-paragraphs", "2"]).stdout)
    report = data["data"]["reports"][0]
    assert len(report["paragraphs"]) == 2
    assert report["paragraphs_truncated"] is True
    assert report["counts"]["paragraphs"] == 6  # counts stay complete


def test_cli_report_writes_a_page(tmp_path):
    doc = _doc(tmp_path, "hard.md", HARD_TEXT + "\n")
    out = tmp_path / "nested" / "readability.html"
    r = _cli(["prose", "report", str(doc), "--out", str(out), "--title", "draft check"])
    assert r.returncode == 0, r.stderr + r.stdout
    body = json.loads(r.stdout)["data"]
    assert body["out"] == str(out)
    assert out.is_file()
    page = out.read_text(encoding="utf-8")
    # "bytes" is the real file size (>= char count once newlines are translated)
    assert body["bytes"] == out.stat().st_size
    assert body["chars"] == len(page)
    assert body["bytes"] >= body["chars"]
    assert body["grades"][str(doc)] > 12.0
    assert "draft check" in page
    assert "Per-paragraph difficulty" in page
    assert "The implementation of the readability configuration" in page
    assert 'class="para b-very_hard"' in page


def test_cli_report_gate_runs_after_the_write(tmp_path):
    doc = _doc(tmp_path, "hard.md", HARD_TEXT + "\n")
    out = tmp_path / "gated.html"
    r = _cli(["prose", "report", str(doc), "--out", str(out), "--fail-on", "suggestion"])
    assert r.returncode == 1
    assert out.is_file(), "the page must be written before the gate fires"


def test_cli_lint_includes_readability_rules(tmp_path):
    doc = _doc(tmp_path, "hard.md", HARD_TEXT + "\n")
    r = _cli(["prose", "lint", str(doc)])
    assert r.returncode == 0, r.stderr + r.stdout
    rules_seen = {d["rule"] for d in json.loads(r.stdout)["data"]["diagnostics"]}
    assert "readability:grade" in rules_seen


def test_cli_rules_lists_readability(tmp_path):
    data = json.loads(_cli(["prose", "rules"]).stdout)
    entry = data["data"]["rules"]["readability"]
    assert entry["enabled"] is True
    assert entry["severity"] == "suggestion"


def test_cli_detect_surfaces_the_scoring_scope_and_extras():
    data = json.loads(_cli(["prose", "detect"]).stdout)["data"]
    assert data["adapter"] == "prose"
    assert "style" in data["extras"]
    if data["tier"] == "fallback":
        assert "readability scorer" in data["fallback_scope"]
