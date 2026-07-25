"""Cite — openswap #33 (Zotero storage / citation SaaS -> stdlib BibTeX/CSL store
plus a deterministic formatter). Pure-logic core tests: the brace-aware
tokenizer including every refusal path, @string expansion, LaTeX-accent decoding,
BibTeX name splitting in all three comma forms with von particles, the sqlite
library and its conflict policies, the measured round-trip fidelity audit, the
CSL-JSON mapping both ways, every style's exact output, the value-XOR-error
honesty invariant on every rendering, the rules overlay, the zero-egress manifest
guard and the real CLI in a subprocess. Offline and deterministic by
construction: every input is a string or a tmp_path file, no fixture is fetched
and no socket is opened on any path."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import cite, openswap

ROOT = Path(__file__).resolve().parents[1]
BS = chr(92)  # a literal backslash, so LaTeX fixtures never depend on r"" nesting

RICH_BIB = """
@string{jcp = {J. Chem. Phys.}}
@preamble{ "\\newcommand{\\noop}[1]{}" }
@comment{this line is not an entry}

@article{doe2020,
  author   = {Doe, Jane and Roe, Richard},
  title    = {A study of studies},
  journal  = jcp,
  year     = 2020,
  volume   = {12},
  number   = {3},
  pages    = {45--67},
  doi      = {https://doi.org/10.1000/xyz123},
  keywords = {meta, review}
}

@book{fontaine2015,
  author    = {Jean de la Fontaine},
  title     = {Nested {BibTeX} Braces},
  publisher = {Univ Press},
  year      = {2015}
}
"""


def _parse(text: str, path: str = "t.bib") -> dict:
    return cite.parse_bibtex(text, path=path)


def _rules_fired(result: dict) -> set[str]:
    return {p["rule"] for p in result["problems"]}


def _entry(**fields) -> dict:
    """A hand-built entry, so a test can pin one field's effect exactly."""
    etype = fields.pop("_type", "article")
    key = fields.pop("_key", "k1")
    return {
        "key": key,
        "type": etype,
        "fields": dict(fields),
        "field_order": list(fields),
        "macros": {},
    }


# ---- brace-aware scanning ----------------------------------------------------


def test_balanced_counts_and_rejects_an_early_close():
    assert cite.balanced("") is True
    assert cite.balanced("{a}") is True
    assert cite.balanced("{{a}{b}}") is True
    assert cite.balanced("{a") is False  # never closed
    assert cite.balanced("a}") is False  # closed without opening
    assert cite.balanced("}{") is False  # order matters, not just the count
    assert cite.balanced("{}{}") is True


def test_split_top_splits_only_at_depth_zero():
    assert cite.split_top("a,b,c", ",") == ["a", "b", "c"]
    assert cite.split_top("a,{b,c},d", ",") == ["a", "{b,c}", "d"]
    assert cite.split_top("{a,{b,c}},d", ",") == ["{a,{b,c}}", "d"]
    assert cite.split_top('a,"b,c",d', ",") == ["a", '"b,c"', "d"]
    assert cite.split_top("nosep", ",") == ["nosep"]
    assert cite.split_top("a,", ",") == ["a", ""]  # trailing separator is visible


def test_split_top_ignores_a_latex_escaped_quote():
    # regression: \" is the LaTeX diaeresis, not a BibTeX string delimiter. When it
    # toggled quoting, the comma in "von Last, First" was swallowed and the surname
    # came out as the last word of the given name (observed on Sch\"onherr, Erdos).
    raw = "Sch" + BS + '"onherr, Erdos'
    assert cite.split_top(raw, ",") == ["Sch" + BS + '"onherr', " Erdos"]
    assert cite.parse_name(raw)["family"] == "Sch" + BS + '"onherr'
    assert cite.parse_name(raw)["given"] == "Erdos"


def test_split_top_still_honours_a_real_quoted_value():
    body = 'author = "Doe, Jane", year = 2020'
    assert cite.split_top(body, ",") == ['author = "Doe, Jane"', " year = 2020"]


# ---- BibTeX parsing: the happy path -----------------------------------------


def test_parse_keeps_every_field_including_ones_no_style_renders():
    res = _parse(RICH_BIB)
    doe = res["entries"][0]
    assert doe["key"] == "doe2020" and doe["type"] == "article"
    assert set(doe["fields"]) == {
        "author", "title", "journal", "year", "volume", "number", "pages", "doi", "keywords",
    }
    assert doe["fields"]["keywords"] == "meta, review"  # no style uses it; kept anyway
    assert res["rejected"] == []


def test_parse_preserves_source_field_order_rather_than_sorting():
    res = _parse(RICH_BIB)
    assert res["entries"][0]["field_order"] == [
        "author", "title", "journal", "year", "volume", "number", "pages", "doi", "keywords",
    ]
    # the source order is NOT alphabetical, so this would break if order tracking
    # were dropped and the emitter fell back to sorted()
    assert res["entries"][0]["field_order"] != sorted(res["entries"][0]["fields"])


def test_parse_expands_a_string_macro_and_records_which_one():
    res = _parse(RICH_BIB)
    doe = res["entries"][0]
    assert res["strings"] == {"jcp": "J. Chem. Phys."}
    assert doe["fields"]["journal"] == "J. Chem. Phys."
    assert doe["macros"]["journal"] == ["jcp"]
    assert doe["strings_used"] == {"jcp": "J. Chem. Phys."}
    assert doe["unresolved_macros"] == {}
    assert "cite:unknown-macro" not in _rules_fired(res)


def test_parse_seeded_macro_table_resolves_an_entry_lifted_out_of_its_file():
    lone = "@article{a,\n journal = jcp,\n title = {T}\n}"
    without = _parse(lone)["entries"][0]
    with_table = cite.parse_bibtex(lone, path="t.bib", strings={"jcp": "J. Chem. Phys."})["entries"][0]
    assert without["fields"]["journal"] == "jcp"  # literal token kept, not emptied
    assert with_table["fields"]["journal"] == "J. Chem. Phys."


def test_parse_undefined_macro_keeps_the_literal_and_warns():
    res = _parse("@article{a, journal = nosuchmacro, title = {T}}")
    entry = res["entries"][0]
    assert entry["fields"]["journal"] == "nosuchmacro"  # BibTeX would substitute ""
    assert entry["unresolved_macros"] == {"journal": ["nosuchmacro"]}
    assert "cite:unknown-macro" in _rules_fired(res)
    assert res["rejected"] == []  # a warning does not refuse the entry


def test_parse_handles_hash_concatenation():
    res = _parse('@string{a = {Jour}}\n@article{x, journal = a # " of " # {Things}, title={T}}')
    assert res["entries"][0]["fields"]["journal"] == "Jour of Things"


def test_parse_handles_a_paren_delimited_body():
    res = _parse("@article(x, title = {In parens}, year = {2001})")
    assert res["entries"][0]["fields"] == {"title": "In parens", "year": "2001"}


def test_parse_preserves_nested_and_case_protection_braces_verbatim():
    res = _parse("@book{b, title = {Nested {BibTeX} Braces}, publisher={P}, author={A, B}, year={2001}}")
    assert res["entries"][0]["fields"]["title"] == "Nested {BibTeX} Braces"
    assert cite.delatex(res["entries"][0]["fields"]["title"]) == "Nested BibTeX Braces"


def test_parse_counts_comments_preambles_and_strings_separately():
    res = _parse(RICH_BIB)
    assert res["counts"]["comments"] == 1
    assert res["counts"]["strings"] == 1
    assert res["counts"]["preambles"] == 1
    assert res["counts"]["entries"] == 2 and res["counts"]["rejected"] == 0
    assert res["counts"]["truncated"] is False


def test_parse_trailing_comma_is_legal_not_a_finding():
    # @misc requires only a title, so a clean parse here really is zero problems
    res = _parse("@misc{a, title = {T}, year = {2001},}")
    assert res["problems"] == [] and len(res["entries"]) == 1
    assert res["entries"][0]["field_order"] == ["title", "year"]
    # and the same body WITHOUT the trailing comma parses identically
    assert _parse("@misc{a, title = {T}, year = {2001}}")["entries"][0]["fields"] == res["entries"][0]["fields"]


def test_parse_records_line_numbers_for_findings():
    res = _parse("\n\n@article{a,\n  title = {T},\n  title = {U}\n}\n")
    assert [p["line"] for p in res["problems"]] == [3]
    assert res["rejected"][0]["line"] == 3


# ---- BibTeX parsing: every refusal -----------------------------------------


def test_duplicate_field_refuses_the_whole_entry():
    res = _parse("@article{dup,\n a = {1},\n title = {T},\n title = {U}\n}")
    assert res["entries"] == []  # NOT half-imported with one title picked
    assert [r["rule"] for r in res["rejected"]] == ["cite:duplicate-field"]
    assert res["rejected"][0]["key"] == "dup"
    assert "title" in res["rejected"][0]["raw"]


def test_missing_key_refuses_the_entry():
    res = _parse("@article{, title = {No key}}")
    assert res["entries"] == []
    assert [r["rule"] for r in res["rejected"]] == ["cite:missing-key"]


def test_a_field_assignment_where_the_key_belongs_is_a_missing_key():
    res = _parse("@article{title = {Oops}, year = {2001}}")
    assert res["entries"] == []
    assert res["rejected"][0]["rule"] == "cite:missing-key"


def test_duplicate_key_keeps_the_first_and_refuses_the_second():
    res = _parse("@article{k, title = {First}}\n@misc{k, title = {Second}}")
    assert [e["fields"]["title"] for e in res["entries"]] == ["First"]
    assert [r["rule"] for r in res["rejected"]] == ["cite:duplicate-key"]
    assert res["rejected"][0]["type"] == "misc"


def test_unterminated_entry_stops_the_parse_and_says_the_rest_was_not_read():
    text = (
        "@article{good, title = {Fine}, journal={J}, author={A, B}, year={2001}}\n"
        "@article{bad, title = {never closed\n"
        "@article{after, title = {Would have been fine}}\n"
    )
    res = _parse(text)
    assert [e["key"] for e in res["entries"]] == ["good"]
    assert res["counts"]["truncated"] is True
    assert res["rejected"][0]["rule"] == "cite:unterminated-entry"
    assert "after" not in {e["key"] for e in res["entries"]}


def test_malformed_value_refuses_the_entry():
    res = _parse("@article{a, title = <angle>, year = {2001}}")
    assert res["entries"] == []
    assert res["rejected"][0]["rule"] == "cite:malformed-value"


def test_element_without_an_equals_sign_refuses_the_entry():
    res = _parse("@article{a, title = {T}, orphanfield}")
    assert res["entries"] == []
    assert res["rejected"][0]["rule"] == "cite:malformed-field"


def test_a_field_name_that_is_not_an_identifier_refuses_the_entry():
    res = _parse("@article{a, 1bad = {T}}")
    assert res["entries"] == []
    assert res["rejected"][0]["rule"] == "cite:malformed-field"


def test_stray_at_sign_and_a_bodyless_type_are_reported_without_stopping():
    res = _parse("@ not-a-type\n@article\n@article{ok, title = {T}}")
    fired = _rules_fired(res)
    assert "cite:bad-entry-type" in fired and "cite:missing-body" in fired
    assert [e["key"] for e in res["entries"]] == ["ok"]  # the parse continued


def test_unknown_entry_type_is_kept_verbatim_not_coerced_to_misc():
    res = _parse("@softwareversion{sv, title = {Thing}}")
    assert res["entries"][0]["type"] == "softwareversion"
    assert "cite:unknown-type" in _rules_fired(res)


def test_empty_and_bad_doi_and_crossref_are_warned_about_not_fixed():
    res = _parse("@article{a, title={T}, note={}, doi={not-a-doi}, crossref={parent}, author={A, B}, journal={J}, year={2001}}")
    fired = _rules_fired(res)
    assert {"cite:empty-value", "cite:bad-doi", "cite:crossref-unresolved"} <= fired
    assert res["entries"][0]["fields"]["doi"] == "not-a-doi"  # kept, not repaired
    assert res["rejected"] == []


def test_string_macro_body_is_validated():
    res = _parse("@string{notanassignment}\n@string{ok = {v}}")
    assert "cite:malformed-field" in _rules_fired(res)
    assert res["strings"] == {"ok": "v"}


# ---- delatex (display only) -------------------------------------------------


def test_delatex_composes_accents():
    assert cite.delatex("Sch" + BS + '"onherr') == "Schönherr"
    assert cite.delatex("Erd" + BS + "H{o}s") == "Erdős"
    assert cite.delatex(BS + "'e") == "é"
    assert cite.delatex(BS + "c{c}") == "ç"
    assert cite.delatex(BS + "v{s}") == "š"


def test_delatex_expands_ligatures_longest_command_first():
    assert cite.delatex(BS + "ss") == "ß"
    assert cite.delatex(BS + "aa") == "å"
    assert cite.delatex(BS + "oe") == "œ"  # must not be eaten by the shorter \o
    assert cite.delatex(BS + "o") == "ø"


def test_delatex_handles_dashes_quotes_and_tie():
    assert cite.delatex("1--5") == "1–5"
    assert cite.delatex("10---20") == "10—20"
    assert cite.delatex("``x''") == "“x”"
    assert cite.delatex("a~b") == "a b"


def test_delatex_keeps_an_escaped_brace_and_strips_case_protection():
    assert cite.delatex(BS + "{x" + BS + "}") == "{x}"
    assert cite.delatex("{Protected}") == "Protected"
    assert cite.delatex(BS + "& " + BS + "% " + BS + "_") == "& % _"


def test_delatex_is_a_view_and_never_edits_the_stored_value():
    raw = "Sch" + BS + '"onherr'
    res = _parse("@article{a, author = {" + raw + "}, title={T}, journal={J}, year={2001}}")
    # the STORE keeps the backslash; only the rendering decodes it
    assert res["entries"][0]["fields"]["author"] == raw
    assert cite.render(res["entries"][0], "apa")["text"].startswith("Schönherr")


def test_delatex_empty_input_is_empty_not_none():
    assert cite.delatex("") == ""


# ---- names ------------------------------------------------------------------


def test_split_names_uses_brace_depth_to_protect_a_corporate_name():
    got = cite.split_names("A One and {Bread and Butter Institute} and B Two")
    assert got == ["A One", "{Bread and Butter Institute}", "B Two"]


def test_split_names_on_a_single_name_and_on_empty():
    assert cite.split_names("Doe, Jane") == ["Doe, Jane"]
    assert cite.split_names("   ") == []


def test_parse_name_first_von_last():
    n = cite.parse_name("Ludwig van Beethoven")
    assert (n["given"], n["von"], n["family"], n["jr"]) == ("Ludwig", "van", "Beethoven", "")
    n2 = cite.parse_name("Jean de la Fontaine")
    assert (n2["given"], n2["von"], n2["family"]) == ("Jean", "de la", "Fontaine")


def test_parse_name_von_last_comma_first():
    n = cite.parse_name("van der Berg, Jan")
    assert (n["given"], n["von"], n["family"]) == ("Jan", "van der", "Berg")


def test_parse_name_von_last_comma_jr_comma_first():
    n = cite.parse_name("Doe, Jr., John Q.")
    assert (n["given"], n["family"], n["jr"]) == ("John Q.", "Doe", "Jr.")


def test_parse_name_last_token_is_never_a_von_particle():
    # "de" is lowercase but it is the only token, so it is the surname
    assert cite.parse_name("de")["family"] == "de"
    # two lowercase tokens: the last one is still the surname
    n = cite.parse_name("de gaulle")
    assert (n["von"], n["family"]) == ("de", "gaulle")
    # same boundary on the comma form: an all-lowercase surname keeps its last token
    c = cite.parse_name("van der berg, Jan")
    assert (c["von"], c["family"], c["given"]) == ("van der", "berg", "Jan")


def test_parse_name_single_token_and_plain_two_token():
    assert cite.parse_name("Plato") == {
        "given": "", "von": "", "family": "Plato", "jr": "", "literal": None, "corporate": False,
    }
    n = cite.parse_name("John Doe")
    assert (n["given"], n["von"], n["family"]) == ("John", "", "Doe")


def test_parse_name_braced_particle_is_caseless_so_not_a_von():
    # BibTeX rule: a braced group is a "special character" and is caseless, i.e.
    # uppercase. Bracing a particle is how an author says "this is NOT a von", so
    # {de la} belongs to the given name while a bare `de la` does not.
    braced = cite.parse_name("Jean {de la} Fontaine")
    assert braced["family"] == "Fontaine" and braced["given"] == "Jean {de la}"
    assert braced["von"] == ""
    bare = cite.parse_name("Jean de la Fontaine")
    assert bare["von"] == "de la" and bare["given"] == "Jean"


def test_parse_name_accent_command_inside_braces_still_gives_a_lowercase_letter():
    n = cite.parse_name("Pierre {" + BS + "'e}tienne Dupont")
    assert n["von"] == "{" + BS + "'e}tienne" and n["family"] == "Dupont"


def test_parse_name_corporate_is_never_split_into_initials():
    n = cite.parse_name("{The Unicode Consortium}")
    assert n["corporate"] is True and n["literal"] == "The Unicode Consortium"
    assert cite.display_name(n, "family-initials") == "The Unicode Consortium"


def test_initials():
    assert cite.initials("John Ronald") == "J. R."
    assert cite.initials("Jean-Robert") == "J.-R."
    assert cite.initials("") == ""
    assert cite.initials("Erd" + BS + "H{o}s") == "E."


def test_display_name_forms_differ_and_include_the_particle():
    n = cite.parse_name("van der Berg, Jan")
    assert cite.display_name(n, "family-initials") == "van der Berg, J."
    assert cite.display_name(n, "initials-family") == "J. van der Berg"
    assert cite.display_name(n, "family-given") == "van der Berg, Jan"
    assert cite.display_name(n, "given-family") == "Jan van der Berg"


def test_display_name_appends_a_suffix():
    n = cite.parse_name("Doe, Jr., John")
    assert cite.display_name(n, "family-initials") == "Doe, J., Jr."


def test_entry_names_falls_back_to_editor_and_says_which_field():
    names, role = cite.entry_names(_entry(editor="Ed, Edna", title="T"))
    assert role == "editor" and [n["family"] for n in names] == ["Ed"]
    names2, role2 = cite.entry_names(_entry(author="Au, Ann", editor="Ed, Edna", title="T"))
    assert role2 == "author" and [n["family"] for n in names2] == ["Au"]
    assert cite.entry_names(_entry(title="T")) == ([], None)


# ---- field access -----------------------------------------------------------


def test_entry_year_from_year_then_date_then_none():
    assert cite.entry_year(_entry(year="2020")) == 2020
    assert cite.entry_year(_entry(year="c. 1999 reprint")) == 1999
    assert cite.entry_year(_entry(date="2018-03-04")) == 2018
    assert cite.entry_year(_entry(year="in press")) is None
    assert cite.entry_year(_entry(year="99")) is None  # a 2-digit year is not a year


def test_entry_month_english_names_numbers_and_rejections():
    assert cite.entry_month(_entry(month="jan")) == 1
    assert cite.entry_month(_entry(month="September")) == 9
    assert cite.entry_month(_entry(month="12")) == 12
    assert cite.entry_month(_entry(month="13")) is None
    assert cite.entry_month(_entry(month="0")) is None
    assert cite.entry_month(_entry(month="brumaire")) is None
    assert cite.entry_month(_entry()) is None


def test_normalize_doi_strips_prefixes_and_rejects_non_doi_shapes():
    assert cite.normalize_doi("10.1000/xyz123") == "10.1000/xyz123"
    assert cite.normalize_doi("https://doi.org/10.1000/XYZ") == "10.1000/xyz"
    assert cite.normalize_doi("doi:10.1000/abc") == "10.1000/abc"
    assert cite.normalize_doi("http://dx.doi.org/10.1000/abc") == "10.1000/abc"
    for bad in ("", "not-a-doi", "11.1000/x", "10.1/x", "10.1000/"):
        assert cite.normalize_doi(bad) is None, bad


def test_missing_required_uses_the_per_type_table():
    assert cite.missing_required(_entry(title="T")) == ["author", "journal", "year"]
    full = _entry(author="A, B", title="T", journal="J", year="2001")
    assert cite.missing_required(full) == []
    assert cite.required_fields("article") == ("author", "title", "journal", "year")
    assert cite.required_fields("nosuchtype") == cite.DEFAULT_REQUIRED


def test_missing_required_accepts_editor_for_author_and_institution_for_publisher():
    book = _entry(_type="book", editor="Ed, Edna", title="T", institution="Inst", year="2001")
    assert cite.missing_required(book) == []
    assert cite.missing_required(_entry(_type="book", title="T", year="2001")) == ["author", "publisher"]


def test_missing_required_treats_whitespace_as_absent():
    assert "title" in cite.missing_required(_entry(title="   ", author="A, B", journal="J", year="2001"))


# ---- emission and round-trip ------------------------------------------------


def test_to_bibtex_emits_parse_order_then_late_fields_alphabetically():
    entry = _entry(title="T", author="A, B")
    entry["fields"]["zeta"] = "z"
    entry["fields"]["alpha"] = "a"
    assert cite.ordered_fields(entry) == ["title", "author", "alpha", "zeta"]
    text = cite.to_bibtex(entry)
    assert text.startswith("@article{k1,\n")
    assert text.index("title") < text.index("author") < text.index("alpha") < text.index("zeta")


def test_to_bibtex_refuses_an_unbalanced_value_instead_of_writing_a_broken_file():
    with pytest.raises(ValueError, match="unbalanced"):
        cite.to_bibtex(_entry(title="a} b {c"))


def test_roundtrip_is_identical_for_a_rich_entry():
    entry = _parse(RICH_BIB)["entries"][0]
    rep = cite.roundtrip_report(entry)
    assert rep["identical"] is True
    assert rep["lost_fields"] == [] and rep["added_fields"] == [] and rep["changed_fields"] == []
    assert rep["type_preserved"] is True and rep["order_preserved"] is True
    assert rep["error"] is None and rep["reparsed"] is True


def test_roundtrip_reports_an_emit_failure_rather_than_claiming_identical():
    rep = cite.roundtrip_report(_entry(title="a} b {c"))
    assert rep["identical"] is False and rep["reparsed"] is False
    assert rep["error"] and "unbalanced" in rep["error"]
    assert rep["emitted"] is None


def test_roundtrip_reports_a_reparse_failure_when_a_field_name_is_unemittable():
    # a hand-built entry can carry a field name BibTeX cannot express; emitting it
    # produces text that will not parse back, and that must be measured, not assumed
    entry = _entry(title="T")
    entry["fields"]["1bad"] = "v"
    entry["field_order"].append("1bad")
    rep = cite.roundtrip_report(entry)
    assert rep["identical"] is False
    assert rep["error"] and "cite:malformed-field" in rep["error"]


def test_roundtrip_marks_a_key_or_type_change_when_the_key_is_unemittable():
    entry = _entry(title="T")
    entry["key"] = "has space"  # a key with whitespace re-parses as a missing key
    rep = cite.roundtrip_report(entry)
    assert rep["identical"] is False and rep["error"] is not None


def test_the_emitter_is_verbatim_so_no_value_can_change_across_a_round_trip():
    """Why `changed_fields` stays empty for every input the emitter accepts.

    to_bibtex wraps a value in braces and the parser strips exactly those braces
    back off, so the only ways a round-trip can fail are an unbalanced value (the
    emitter refuses) or a name/key BibTeX cannot express (the reparse refuses).
    This pins that property against the awkward values — # concatenation markers,
    quotes, nested braces, padding, an embedded @ — rather than leaving it implied.
    Noted honestly: this means the `changed_fields` conjunct of `identical` is a
    guard against a future normalizing emitter and is not reachable today.
    """
    for value in ("a # b", 'say "hi"', "{Nested {Deep}}", "  padded  ", "@article{x}", "", "1--5"):
        entry = _entry(title="T", note=value)
        rep = cite.roundtrip_report(entry)
        assert rep["changed_fields"] == [], value
        assert rep["identical"] is True, value
        reparsed = cite.parse_bibtex(rep["emitted"], path="x.bib")["entries"][0]
        assert reparsed["fields"]["note"] == value


def test_roundtrip_flags_a_field_name_whose_case_the_parser_normalizes():
    entry = _entry(title="T")
    entry["fields"]["Publisher"] = "P"  # BibTeX field names are case-insensitive
    entry["field_order"].append("Publisher")
    rep = cite.roundtrip_report(entry)
    assert rep["identical"] is False
    assert rep["lost_fields"] == ["Publisher"] and rep["added_fields"] == ["publisher"]


def test_missing_required_is_reported_at_parse_time_not_only_at_format_time():
    res = _parse("@article{thin, title = {Only a title}}")
    missing = [p for p in res["problems"] if p["rule"] == "cite:missing-required"]
    assert len(missing) == 1
    assert "missing author, journal, year" in missing[0]["message"]
    complete = _parse("@article{full, author={A, B}, title={T}, journal={J}, year={2001}}")
    assert [p for p in complete["problems"] if p["rule"] == "cite:missing-required"] == []


def test_render_bibtex_document_holds_every_entry():
    entries = _parse(RICH_BIB)["entries"]
    doc = cite.render_bibtex(entries)
    assert doc.count("@") == 2
    assert len(cite.parse_bibtex(doc, path="x.bib", strings={"jcp": "J. Chem. Phys."})["entries"]) == 2


# ---- styles -----------------------------------------------------------------


def test_apa_exact_output():
    entry = _parse(RICH_BIB)["entries"][0]
    r = cite.render(entry, "apa")
    assert r["text"] == (
        "Doe, J., & Roe, R. (2020). A study of studies. J. Chem. Phys., 12(3), 45–67. "
        "https://doi.org/10.1000/xyz123"
    )
    assert r["error"] is None and r["in_text"] == "(Doe & Roe, 2020)"


def test_mla_exact_output():
    entry = _parse(RICH_BIB)["entries"][0]
    assert cite.render(entry, "mla")["text"] == (
        'Doe, Jane, and Richard Roe. "A study of studies." J. Chem. Phys., vol. 12, no. 3, '
        "2020, pp. 45–67."
    )


def test_chicago_exact_output():
    entry = _parse(RICH_BIB)["entries"][0]
    assert cite.render(entry, "chicago")["text"] == (
        'Doe, Jane, and Richard Roe. 2020. "A study of studies." J. Chem. Phys. 12 (3): 45–67.'
    )


def test_ieee_exact_output_and_numbered_in_text():
    entry = _parse(RICH_BIB)["entries"][0]
    r = cite.render(entry, "ieee", index=7)
    assert r["text"] == (
        'J. Doe and R. Roe, "A study of studies," J. Chem. Phys., vol. 12, no. 3, pp. 45–67, 2020.'
    )
    assert r["in_text"] == "[7]"


def test_a_book_renders_its_publisher_in_every_prose_style():
    book = _parse(RICH_BIB)["entries"][1]
    for style in ("apa", "mla", "chicago", "ieee"):
        text = cite.render(book, style)["text"]
        assert "Univ Press" in text, style
        assert "de la Fontaine" in text, style


def test_ieee_joins_three_authors_with_a_final_and():
    e = _entry(author="A, Ann and B, Bob and C, Cid", title="T", journal="J", year="2001")
    assert cite.render(e, "ieee")["text"].startswith('A. A, B. B, and C. C, "T,"')


def test_missing_required_is_an_error_not_a_reference_with_a_hole():
    thin = _entry(title="Only a title", year="2022")
    for style in ("apa", "mla", "chicago", "ieee"):
        r = cite.render(thin, style)
        assert r["text"] is None
        assert "missing author, journal" in r["error"]
        assert r["missing_required"] == ["author", "journal"]


def test_every_rendering_has_either_text_or_error_never_both_never_neither():
    entries = [
        *_parse(RICH_BIB)["entries"],
        _entry(title="thin"),
        _entry(_type="misc", title="Untitled thing"),
        _entry(_type="book", author="{A Corporation}", title="T", publisher="P", year="1900"),
        _entry(title="a} broken {value", author="A, B", journal="J", year="2001"),
    ]
    for entry in entries:
        for style in cite.STYLES:
            r = cite.render(entry, style)
            assert (r["text"] is None) != (r["error"] is None), (entry["key"], style, r)


def test_an_undated_entry_gets_the_labelled_no_date_marker_and_is_reported():
    e = _entry(_type="misc", title="Undated thing")
    r = cite.render(e, "apa")
    assert cite.NO_DATE in r["text"]
    assert "year" in r["omitted"]
    assert cite.entry_year(e) is None  # nothing was guessed from anywhere


def test_omitted_lists_the_optional_fields_that_are_actually_absent():
    r = cite.render(_parse(RICH_BIB)["entries"][0], "apa")
    assert "url" in r["omitted"] and "publisher" in r["omitted"]
    assert "doi" not in r["omitted"] and "volume" not in r["omitted"]


def test_render_rejects_an_unknown_style_without_pretending():
    r = cite.render(_entry(title="T"), "harvard")
    assert r["text"] is None and "unknown style" in r["error"]


def test_bibtex_style_returns_the_re_emitted_entry():
    entry = _parse(RICH_BIB)["entries"][0]
    r = cite.render(entry, "bibtex")
    assert r["error"] is None
    assert r["text"].startswith("@article{doe2020,\n")
    assert "journal" in r["text"] and "J. Chem. Phys." in r["text"]  # the macro is expanded
    assert cite.parse_bibtex(r["text"], path="x.bib")["entries"][0]["fields"] == entry["fields"]


def test_csl_style_returns_parseable_json():
    entry = _parse(RICH_BIB)["entries"][0]
    item = json.loads(cite.render(entry, "csl")["text"])
    assert item["id"] == "doe2020" and item["type"] == "article-journal"


def test_in_text_keeps_the_von_particle():
    book = _parse(RICH_BIB)["entries"][1]
    assert cite.in_text(book, "apa") == "(de la Fontaine, 2015)"
    assert cite.in_text(book, "chicago") == "(de la Fontaine 2015)"
    assert cite.in_text(book, "mla") == "(de la Fontaine)"
    assert cite.in_text(book, "ieee", index=3) == "[3]"


def test_in_text_falls_back_to_the_key_when_there_is_no_author():
    assert cite.in_text(_entry(_key="anon2001", title="T", year="2001"), "apa") == "(anon2001, 2001)"


def test_sort_entries_orders_by_each_key_and_breaks_ties_on_the_key():
    a = _entry(_key="zz", author="Beta, B", title="T", journal="J", year="1990")
    b = _entry(_key="aa", author="Alpha, A", title="T", journal="J", year="2001")
    c = _entry(_key="mm", author="Alpha, A", title="T", journal="J", year="2001")
    entries = [a, b, c]
    assert [e["key"] for e in cite.sort_entries(entries, "key")] == ["aa", "mm", "zz"]
    assert [e["key"] for e in cite.sort_entries(entries, "year")] == ["zz", "aa", "mm"]
    # same family AND same year -> the key decides, so the order is total
    assert [e["key"] for e in cite.sort_entries(entries, "author")] == ["aa", "mm", "zz"]


def test_sort_entries_rejects_an_unknown_sort_key():
    with pytest.raises(ValueError, match="sort must be one of"):
        cite.sort_entries([], "vibes")


def test_bibliography_counts_formatted_and_failed_separately():
    entries = [*_parse(RICH_BIB)["entries"], _entry(_key="thin", title="Thin")]
    biblio = cite.bibliography(entries, "apa", sort="key")
    assert biblio["count"] == 3 and biblio["formatted"] == 2 and biblio["failed"] == 1
    assert [e["key"] for e in biblio["entries"]] == ["doe2020", "fontaine2015", "thin"]
    assert biblio["style"] == "apa" and biblio["sort"] == "key"


def test_bibliography_numbers_ieee_by_final_sorted_position():
    entries = [
        _entry(_key="zz", author="Zed, Z", title="T", journal="J", year="2001"),
        _entry(_key="aa", author="Ann, A", title="T", journal="J", year="2001"),
    ]
    biblio = cite.bibliography(entries, "ieee", sort="key")
    assert [e["in_text"] for e in biblio["entries"]] == ["[1]", "[2]"]
    assert [e["key"] for e in biblio["entries"]] == ["aa", "zz"]


# ---- CSL-JSON ---------------------------------------------------------------


def test_to_csl_maps_the_fields_it_knows_and_names_the_rest():
    entry = _parse(RICH_BIB)["entries"][0]
    out = cite.to_csl(entry)
    item = out["item"]
    assert item["type"] == "article-journal"
    assert item["author"] == [
        {"family": "Doe", "given": "Jane"},
        {"family": "Roe", "given": "Richard"},
    ]
    assert item["container-title"] == "J. Chem. Phys."
    assert item["DOI"] == "10.1000/xyz123" and item["issue"] == "3" and item["page"] == "45–67"
    assert item["issued"] == {"date-parts": [[2020]]}
    assert out["unmapped"] == ["keywords"]  # not dropped in silence


def test_to_csl_includes_the_month_when_there_is_one():
    e = _entry(author="A, B", title="T", journal="J", year="2001", month="mar")
    assert cite.to_csl(e)["item"]["issued"] == {"date-parts": [[2001, 3]]}


def test_to_csl_uses_editor_and_literal_names():
    e = _entry(_type="book", editor="{A Consortium}", title="T", publisher="P", year="2001")
    item = cite.to_csl(e)["item"]
    assert item["editor"] == [{"literal": "A Consortium"}] and "author" not in item


def test_parse_csl_json_builds_entries_with_a_stable_field_order():
    text = json.dumps([
        {
            "id": "x1",
            "type": "article-journal",
            "author": [{"family": "Doe", "given": "Jane"}],
            "title": "A CSL title",
            "container-title": "J. Csl",
            "issued": {"date-parts": [[2019, 4]]},
            "page": "1-9",
            "DOI": "10.1000/csl",
        }
    ])
    res = cite.parse_csl_json(text, path="lib.json")
    entry = res["entries"][0]
    assert entry["type"] == "article" and entry["key"] == "x1"
    assert entry["fields"]["author"] == "Doe, Jane"
    assert entry["fields"]["journal"] == "J. Csl" and entry["fields"]["year"] == "2019"
    assert entry["fields"]["month"] == "4" and entry["fields"]["doi"] == "10.1000/csl"
    assert entry["field_order"][0] == "author" and entry["field_order"][1] == "title"
    assert res["rejected"] == []


def test_parse_csl_json_refuses_an_item_with_no_id():
    res = cite.parse_csl_json(json.dumps([{"title": "no id"}, {"id": "", "title": "blank"}]))
    assert res["entries"] == []
    assert [r["rule"] for r in res["rejected"]] == ["cite:csl-missing-id"] * 2
    assert res["counts"]["rejected"] == 2


def test_parse_csl_json_refuses_a_duplicate_id():
    res = cite.parse_csl_json(json.dumps([{"id": "d", "title": "one"}, {"id": "d", "title": "two"}]))
    assert [e["fields"]["title"] for e in res["entries"]] == ["one"]
    assert [r["rule"] for r in res["rejected"]] == ["cite:duplicate-key"]


def test_parse_csl_json_accepts_a_single_object_and_maps_unknown_types_to_misc():
    res = cite.parse_csl_json(json.dumps({"id": "solo", "type": "interpretive-dance", "title": "T"}))
    assert res["entries"][0]["type"] == "misc"


def test_bibtex_to_csl_to_bibtex_preserves_every_mapped_field():
    entry = _parse(RICH_BIB)["entries"][0]
    item = cite.to_csl(entry)["item"]
    back = cite.parse_csl_json(json.dumps([item]))["entries"][0]
    for field in ("author", "title", "journal", "year", "volume", "number", "pages", "doi"):
        assert field in back["fields"], field
    assert back["fields"]["title"] == entry["fields"]["title"]
    assert back["fields"]["number"] == entry["fields"]["number"]
    # keywords was reported as unmapped, and it is genuinely gone from the CSL trip
    assert "keywords" not in back["fields"]


# ---- rules ------------------------------------------------------------------


def test_rejecting_rules_is_derived_from_the_table_not_retyped():
    assert cite.REJECTING_RULES == frozenset(r for r, s in cite.RULES.items() if s["rejects"])
    assert "cite:duplicate-field" in cite.REJECTING_RULES
    assert "cite:missing-required" not in cite.REJECTING_RULES


def test_every_rule_severity_is_a_family_severity():
    for rule, spec in cite.RULES.items():
        assert spec["severity"] in openswap.SEVERITIES, rule


def test_load_rules_default_enables_everything():
    table = cite.load_rules(None)
    assert set(table) == set(cite.RULES)
    assert all(spec["enabled"] for spec in table.values())


def test_load_rules_overlay_retunes_severity(tmp_path):
    f = tmp_path / "over.json"
    f.write_text(json.dumps({"cite:missing-required": {"severity": "error"}}), encoding="utf-8")
    table = cite.load_rules(f)
    assert table["cite:missing-required"]["severity"] == "error"
    assert cite.RULES["cite:missing-required"]["severity"] == "warning"  # table not mutated


def test_load_rules_can_disable_a_non_rejecting_rule(tmp_path):
    f = tmp_path / "over.json"
    f.write_text(json.dumps({"cite:unknown-type": {"enabled": False}}), encoding="utf-8")
    assert cite.load_rules(f)["cite:unknown-type"]["enabled"] is False


def test_load_rules_refuses_to_disable_a_rejecting_rule(tmp_path):
    f = tmp_path / "over.json"
    f.write_text(json.dumps({"cite:duplicate-field": {"enabled": False}}), encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be disabled"):
        cite.load_rules(f)


def test_load_rules_rejects_an_unknown_rule_and_a_bad_severity(tmp_path):
    bad_rule = tmp_path / "a.json"
    bad_rule.write_text(json.dumps({"cite:nope": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown rule"):
        cite.load_rules(bad_rule)
    bad_sev = tmp_path / "b.json"
    bad_sev.write_text(json.dumps({"cite:bad-doi": {"severity": "catastrophe"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="severity must be one of"):
        cite.load_rules(bad_sev)


def test_load_rules_rejects_a_non_object_file(tmp_path):
    f = tmp_path / "c.json"
    f.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        cite.load_rules(f)


def test_diagnostics_from_uses_the_table_severity_and_honours_disabled(tmp_path):
    res = _parse("@softwareversion{sv, title = {T}}")
    on = cite.diagnostics_from(res["problems"], path="t.bib")
    assert [d["rule"] for d in on] == ["cite:unknown-type"]
    assert on[0]["severity"] == "warning" and on[0]["source"] == "cite"
    f = tmp_path / "off.json"
    f.write_text(json.dumps({"cite:unknown-type": {"enabled": False}}), encoding="utf-8")
    off = cite.diagnostics_from(res["problems"], path="t.bib", rules=cite.load_rules(f))
    assert off == []


def test_diagnostics_are_sorted_and_summarizable():
    res = _parse(
        "@article{a, title={T}, title={U}}\n@softwareversion{b, title={T}}\n@article{, title={T}}"
    )
    diags = cite.diagnostics_from(res["problems"], path="t.bib")
    assert [d["line"] for d in diags] == sorted(d["line"] for d in diags)
    summary = openswap.summarize(diags)
    assert summary["by_severity"]["error"] == 2 and summary["by_severity"]["warning"] == 1


# ---- store ------------------------------------------------------------------


@pytest.fixture()
def store():
    return cite.open_store(":memory:")


def test_open_store_records_the_schema_version(store):
    row = store.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    assert row["value"] == cite.SCHEMA_VERSION


def test_import_then_load_preserves_type_fields_and_order(store):
    entries = _parse(RICH_BIB)["entries"]
    res = cite.import_entries(store, entries, source="t.bib", now=1000.0)
    assert res["imported"] == ["doe2020", "fontaine2015"]
    back = cite.load_entry(store, "doe2020")
    assert back["type"] == "article"
    assert back["fields"] == entries[0]["fields"]
    assert back["field_order"] == entries[0]["field_order"]
    assert back["added_ts"] == 1000.0 and back["source"] == "t.bib"


def test_load_entry_returns_none_for_an_absent_key(store):
    assert cite.load_entry(store, "nope") is None


def test_import_skip_leaves_the_original_and_reports_the_conflict(store):
    first = _parse("@article{k, title = {First}, author={A, B}, journal={J}, year={2001}}")["entries"]
    second = _parse("@article{k, title = {Second}, author={C, D}, journal={J}, year={2002}}")["entries"]
    cite.import_entries(store, first, now=1.0)
    res = cite.import_entries(store, second, on_conflict="skip", now=2.0)
    assert res["skipped"] == ["k"] and res["imported"] == []
    assert cite.load_entry(store, "k")["fields"]["title"] == "First"
    assert [p["rule"] for p in res["problems"]] == ["cite:key-conflict"]


def test_import_replace_overwrites_and_drops_the_old_fields(store):
    cite.import_entries(store, _parse("@article{k, title={First}, extra={gone}}")["entries"], now=1.0)
    res = cite.import_entries(
        store, _parse("@article{k, title={Second}}")["entries"], on_conflict="replace", now=2.0
    )
    assert res["replaced"] == ["k"]
    back = cite.load_entry(store, "k")
    assert back["fields"] == {"title": "Second"}  # `extra` did not survive a replace
    assert back["added_ts"] == 2.0


def test_import_fail_writes_nothing_at_all(store):
    cite.import_entries(store, _parse("@article{k, title={First}}")["entries"], now=1.0)
    incoming = _parse("@article{k, title={Second}}\n@article{fresh, title={New}}")["entries"]
    with pytest.raises(ValueError, match="already in the library"):
        cite.import_entries(store, incoming, on_conflict="fail", now=2.0)
    assert cite.load_entry(store, "k")["fields"]["title"] == "First"
    assert cite.load_entry(store, "fresh") is None  # not a partial import


def test_import_rejects_an_unknown_conflict_policy(store):
    with pytest.raises(ValueError, match="on_conflict must be one of"):
        cite.import_entries(store, [], on_conflict="merge")


def test_import_dry_run_reports_but_writes_nothing(store):
    entries = _parse(RICH_BIB)["entries"]
    res = cite.import_entries(store, entries, record=False, now=1.0)
    assert res["recorded"] is False and res["imported"] == ["doe2020", "fontaine2015"]
    assert store.execute("SELECT COUNT(*) AS n FROM entries").fetchone()["n"] == 0


def test_duplicate_doi_under_two_keys_is_reported(store):
    bib = (
        "@article{a, title={T1}, doi={10.1000/x}, author={A, B}, journal={J}, year={2001}}\n"
        "@article{b, title={T2}, doi={https://doi.org/10.1000/X}, author={C, D}, journal={J}, year={2002}}"
    )
    res = cite.import_entries(store, _parse(bib)["entries"], now=1.0)
    dupes = [p for p in res["problems"] if p["rule"] == "cite:duplicate-doi"]
    # ONE finding for a symmetric relation, not one per side
    assert len(dupes) == 1
    assert dupes[0]["message"] == "DOI 10.1000/x is under 2 keys: a, b"


def test_duplicate_doi_is_also_found_against_an_earlier_import(store):
    cite.import_entries(
        store,
        _parse("@article{old, title={T}, doi={10.1000/x}, author={A, B}, journal={J}, year={2001}}")["entries"],
        now=1.0,
    )
    res = cite.import_entries(
        store,
        _parse("@article{new, title={U}, doi={10.1000/x}, author={C, D}, journal={J}, year={2002}}")["entries"],
        now=2.0,
    )
    dupes = [p for p in res["problems"] if p["rule"] == "cite:duplicate-doi"]
    assert len(dupes) == 1 and "new, old" in dupes[0]["message"]


def test_distinct_dois_are_not_reported_as_duplicates(store):
    bib = (
        "@article{a, title={T1}, doi={10.1000/x}, author={A, B}, journal={J}, year={2001}}\n"
        "@article{b, title={T2}, doi={10.1000/y}, author={C, D}, journal={J}, year={2002}}"
    )
    res = cite.import_entries(store, _parse(bib)["entries"], now=1.0)
    assert [p for p in res["problems"] if p["rule"] == "cite:duplicate-doi"] == []


def test_query_filters_by_type_key_author_and_doi(store):
    bib = (
        "@article{doe2020, author={Doe, Jane}, title={A}, journal={J}, year={2020}, doi={10.1000/x}}\n"
        "@book{roe1990, author={Roe, Richard}, title={B}, publisher={P}, year={1990}}\n"
        "@book{berg2005, author={van der Berg, Jan}, title={C}, publisher={P}, year={2005}}"
    )
    cite.import_entries(store, _parse(bib)["entries"], now=1.0)
    assert [e["key"] for e in cite.query(store, entry_type="book")] == ["berg2005", "roe1990"]
    assert [e["key"] for e in cite.query(store, key_contains="20")] == ["berg2005", "doe2020"]
    assert [e["key"] for e in cite.query(store, author_contains="berg")] == ["berg2005"]
    assert [e["key"] for e in cite.query(store, doi="https://doi.org/10.1000/X")] == ["doe2020"]
    assert cite.query(store, doi="10.9999/nope") == []


def test_query_refuses_a_doi_filter_that_could_never_match(store):
    # regression: an unparseable --doi normalized to None and the comparison was
    # then skipped, so the filter silently returned the WHOLE library
    cite.import_entries(store, _parse(RICH_BIB)["entries"], now=1.0)
    with pytest.raises(ValueError, match="could never match"):
        cite.query(store, doi="10.1/typo")
    assert len(cite.query(store)) == 2  # the library itself is fine


def test_query_year_bounds_are_inclusive_and_exclude_undated(store):
    bib = (
        "@misc{y1990, title={A}, year={1990}}\n"
        "@misc{y2000, title={B}, year={2000}}\n"
        "@misc{y2010, title={C}, year={2010}}\n"
        "@misc{undated, title={D}}"
    )
    cite.import_entries(store, _parse(bib)["entries"], now=1.0)
    assert [e["key"] for e in cite.query(store, year_min=2000)] == ["y2000", "y2010"]
    assert [e["key"] for e in cite.query(store, year_max=2000)] == ["y1990", "y2000"]
    assert [e["key"] for e in cite.query(store, year_min=2000, year_max=2000)] == ["y2000"]
    assert "undated" not in {e["key"] for e in cite.query(store, year_min=1)}


def test_query_limit_and_offset_walk_a_stable_order(store):
    bib = "\n".join(f"@misc{{k{i}, title={{T{i}}}}}" for i in range(5))
    cite.import_entries(store, _parse(bib)["entries"], now=1.0)
    assert [e["key"] for e in cite.query(store, limit=2)] == ["k0", "k1"]
    assert [e["key"] for e in cite.query(store, limit=2, offset=2)] == ["k2", "k3"]
    assert [e["key"] for e in cite.query(store, limit=-1)] == ["k0", "k1", "k2", "k3", "k4"]
    assert cite.query(store, limit=2, offset=99) == []


def test_library_stats_counts_what_is_really_there(store):
    cite.import_entries(store, _parse(RICH_BIB)["entries"], now=1.0)
    stats = cite.library_stats(store)
    assert stats["entries"] == 2
    assert stats["by_type"] == {"article": 1, "book": 1}
    assert stats["field_counts"]["title"] == 2
    assert stats["year_range"] == [2015, 2020]
    assert cite.library_stats(cite.open_store(":memory:"))["year_range"] is None


def test_delete_entries_separates_hits_from_misses(store):
    cite.import_entries(store, _parse(RICH_BIB)["entries"], now=1.0)
    res = cite.delete_entries(store, ["doe2020", "nosuchkey"])
    assert res == {"deleted": ["doe2020"], "not_found": ["nosuchkey"]}
    assert cite.load_entry(store, "doe2020") is None
    assert store.execute("SELECT COUNT(*) AS n FROM fields WHERE key='doe2020'").fetchone()["n"] == 0
    assert cite.load_entry(store, "fontaine2015") is not None


def test_store_roundtrip_is_clean_and_keeps_the_macro_table(store):
    cite.import_entries(store, _parse(RICH_BIB)["entries"], source="t.bib", now=1.0)
    res = cite.store_roundtrip(store)
    assert res["checked"] == 2 and res["identical"] == 2 and res["store_faithful"] == 2
    assert res["lost_fields"] == []
    assert cite.load_entry(store, "doe2020")["strings_used"] == {"jcp": "J. Chem. Phys."}


def test_store_roundtrip_would_flag_a_macro_whose_definition_was_not_kept(store):
    """The differential that proves store_faithful is measuring something.

    Same entry, same raw text; the only difference is that the @string table was
    thrown away. Without it the raw text re-parses `journal = jcp` as the literal
    token, and the audit must SAY the stored value differs rather than shrug.
    """
    cite.import_entries(store, _parse(RICH_BIB)["entries"], source="t.bib", now=1.0)
    store.execute("UPDATE entries SET strings = '{}' WHERE key = 'doe2020'")
    store.commit()
    res = cite.store_roundtrip(store, ["doe2020"])
    report = res["reports"][0]
    assert report["store_faithful"] is False
    assert report["store_diff"]["changed"] == ["journal"]
    assert report["identical"] is True  # emit/reparse still fine — the two axes differ
    assert res["store_faithful"] == 0


def test_store_roundtrip_reports_an_unmeasurable_entry_as_none_not_as_pass(store):
    cite.import_entries(store, _parse("@article{a, title={T}}")["entries"], now=1.0)
    store.execute("UPDATE entries SET raw = 'not bibtex at all' WHERE key = 'a'")
    store.commit()
    report = cite.store_roundtrip(store)["reports"][0]
    assert report["store_faithful"] is None
    assert "does not re-parse" in report["store_diff"]["reason"]


def test_store_roundtrip_names_a_key_that_is_not_in_the_library(store):
    report = cite.store_roundtrip(store, ["ghost"])["reports"][0]
    assert report["identical"] is False and report["error"] == "not in the library"


def test_store_roundtrip_detects_a_field_the_store_dropped(store):
    cite.import_entries(store, _parse(RICH_BIB)["entries"], now=1.0)
    store.execute("DELETE FROM fields WHERE key='doe2020' AND name='keywords'")
    store.commit()
    report = cite.store_roundtrip(store, ["doe2020"])["reports"][0]
    assert report["store_faithful"] is False
    assert report["store_diff"]["missing_from_store"] == ["keywords"]


# ---- capability, manifest, egress guard -------------------------------------


def test_capability_reports_fallback_and_never_claims_a_native_run():
    from bigbang.plugins.cite import cli as cite_cli

    cap = cite_cli._capability()
    assert cap["adapter"] == "cite"
    assert cap["native_used"] is False
    # the tier must follow the probe, and the probe must be honest about PATH
    assert cap["tier"] == (openswap.TIER_NATIVE if cap["native"]["found"] else openswap.TIER_FALLBACK)
    assert set(cap["extras"]) == {"pandoc", "biber", "bibtool"}
    assert "never executed" in cap["native_never_executed"].lower()
    assert cap["styles"] == list(cite.STYLES)


def test_manifest_is_zero_egress_and_writes_only_under_scout():
    import yaml

    mf = yaml.safe_load(
        (ROOT / "bigbang" / "plugins" / "cite" / "manifest.yaml").read_text(encoding="utf-8")
    )
    caps = mf["capabilities"]
    assert mf["name"] == "cite"
    assert caps["network"]["enabled"] is False and caps["network"]["domains"] == []
    assert caps["filesystem"]["write"] is True and caps["filesystem"]["paths"] == [".scout"]
    assert caps["secrets"]["allow"] == []


def test_egress_guard_refuses_a_widened_manifest(monkeypatch):
    import typer

    from bigbang.plugins.cite import cli as cite_cli

    assert cite_cli._egress_guard("test")["network_enabled"] is False
    for widened in (
        {"capabilities": {"network": {"enabled": True, "domains": []}}},
        {"capabilities": {"network": {"enabled": False, "domains": ["api.crossref.org"]}}},
    ):
        monkeypatch.setattr(cite_cli, "_MANIFEST", widened)
        with pytest.raises(typer.Exit):
            cite_cli._egress_guard("test")


def test_format_resolution_prefers_the_extension_then_sniffs(tmp_path):
    from bigbang.plugins.cite import cli as cite_cli

    assert cite_cli._resolve_format("csl", Path("x.bib"), "@article{}") == "csl"  # explicit wins
    assert cite_cli._resolve_format("auto", Path("x.bib"), "[]") == "bibtex"
    assert cite_cli._resolve_format("auto", Path("x.json"), "@article{}") == "csl"
    assert cite_cli._resolve_format("auto", Path("refs"), "  [ {} ]") == "csl"
    assert cite_cli._resolve_format("auto", Path("refs"), "  @article{a}") == "bibtex"


# ---- stdlib-only invariant (the whole point of the openswap family) ----------


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_imports_are_stdlib_only():
    roots = _import_roots(ROOT / "bigbang" / "core" / "cite.py")
    allowed = set(sys.stdlib_module_names) | {"bigbang"}
    assert roots <= allowed, f"non-stdlib imports: {sorted(roots - allowed)}"


def test_plugin_cli_adds_no_dependency_beyond_typer():
    roots = _import_roots(ROOT / "bigbang" / "plugins" / "cite" / "cli.py")
    allowed = set(sys.stdlib_module_names) | {"bigbang", "typer"}
    assert roots <= allowed, f"new dependency: {sorted(roots - allowed)}"


def test_no_network_module_is_reachable_from_the_core():
    roots = _import_roots(ROOT / "bigbang" / "core" / "cite.py")
    assert roots & {"socket", "urllib", "http", "ssl", "ftplib", "requests", "httpx"} == set()


# ---- the real CLI in a subprocess (offline on every path) --------------------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(cwd or ROOT),
    )


def _bib(tmp_path: Path, name: str = "refs.bib", body: str = RICH_BIB) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def _db(tmp_path: Path) -> str:
    return str(tmp_path / "lib.db")


def test_cli_hello_envelope():
    r = _cli(["cite", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert data["data"]["plugin"] == "cite" and "example" in data


def test_cli_detect_reports_zero_egress_and_no_native_run():
    r = _cli(["cite", "detect"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["native_used"] is False
    assert data["egress"] == {
        "network_enabled": False,
        "domains": [],
        "reads": "local .bib/.csl-json files only",
        "doi": "shape-checked, never resolved",
    }
    assert "never resolved" in data["scope_limits"]


def test_cli_rules_publishes_the_table_and_the_required_fields():
    r = _cli(["cite", "rules"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert set(data["rules"]) == set(cite.RULES)
    assert data["required_fields"]["article"] == ["author", "title", "journal", "year"]
    assert data["styles"] == list(cite.STYLES)
    assert "cite:duplicate-field" in data["rejecting_rules"]
    assert data["no_date_marker"] == cite.NO_DATE


def test_cli_import_stores_the_good_and_refuses_the_bad(tmp_path):
    body = RICH_BIB + "\n@article{broken, title={A}, title={B}}\n@article{, title={C}}\n"
    bib = _bib(tmp_path, body=body)
    r = _cli(["cite", "import", str(bib), "--db", _db(tmp_path)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["imported"] == ["doe2020", "fontaine2015"]
    assert {x["rule"] for x in data["rejected"]} == {"cite:duplicate-field", "cite:missing-key"}
    assert data["counts"]["entries"] == 2 and data["counts"]["rejected"] == 2
    assert data["macros_defined"] == ["jcp"]
    assert data["summary"]["by_severity"]["error"] == 2
    assert Path(_db(tmp_path)).exists()


def test_cli_import_gate_exits_one_on_a_rejected_entry(tmp_path):
    bib = _bib(tmp_path, body="@article{a, title={A}, title={B}}")
    r = _cli(["cite", "import", str(bib), "--db", _db(tmp_path), "--fail-on", "error"])
    assert r.returncode == 1, r.stdout
    assert json.loads(r.stdout)["data"]["imported"] == []


def test_cli_import_clean_file_passes_the_gate(tmp_path):
    bib = _bib(tmp_path)
    r = _cli(["cite", "import", str(bib), "--db", _db(tmp_path), "--fail-on", "error"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["data"]["summary"]["by_severity"]["error"] == 0


def test_cli_import_dry_run_creates_no_library_file(tmp_path):
    bib = _bib(tmp_path)
    db = tmp_path / "never.db"
    r = _cli(["cite", "import", str(bib), "--db", str(db), "--no-record"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["recorded"] is False and data["db"] is None
    assert len(data["imported"]) == 2
    assert not db.exists()  # a dry run that creates the library is not a dry run


def test_cli_import_on_conflict_fail_writes_nothing(tmp_path):
    bib = _bib(tmp_path)
    db = _db(tmp_path)
    assert _cli(["cite", "import", str(bib), "--db", db]).returncode == 0
    r = _cli(["cite", "import", str(bib), "--db", db, "--on-conflict", "fail"])
    assert r.returncode == 1
    assert "already in the library" in json.loads(r.stdout)["error"]
    listing = _cli(["cite", "list", "--db", db])
    assert json.loads(listing.stdout)["data"]["count"] == 2  # unchanged


def test_cli_import_rejects_bad_flags_actionably(tmp_path):
    bib = _bib(tmp_path)
    for flag, value, needle in (
        ("--format", "yaml", "--format must be"),
        ("--on-conflict", "merge", "--on-conflict must be"),
        ("--fail-on", "catastrophe", "--fail-on must be"),
    ):
        r = _cli(["cite", "import", str(bib), "--db", _db(tmp_path), flag, value])
        assert r.returncode == 1, (flag, r.stdout)
        payload = json.loads(r.stdout)
        assert needle in payload["error"] and "example" in payload


def test_cli_import_missing_file_fails_actionably(tmp_path):
    r = _cli(["cite", "import", str(tmp_path / "nope.bib"), "--db", _db(tmp_path)])
    assert r.returncode == 1
    assert "file not found" in json.loads(r.stdout)["error"]


def test_cli_import_invalid_json_names_the_file(tmp_path):
    bad = tmp_path / "lib.json"
    bad.write_text("{not json", encoding="utf-8")
    r = _cli(["cite", "import", str(bad), "--db", _db(tmp_path)])
    assert r.returncode == 1
    assert "not valid csl" in json.loads(r.stdout)["error"]


def test_cli_import_csl_json_round_trips_into_the_library(tmp_path):
    items = [
        {
            "id": "csl1",
            "type": "article-journal",
            "author": [{"family": "Doe", "given": "Jane"}],
            "title": "From CSL",
            "container-title": "J. Csl",
            "issued": {"date-parts": [[2021]]},
        }
    ]
    src = tmp_path / "lib.json"
    src.write_text(json.dumps(items), encoding="utf-8")
    db = _db(tmp_path)
    r = _cli(["cite", "import", str(src), "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    assert json.loads(r.stdout)["data"]["format"] == "csl"
    f = _cli(["cite", "format", "--key", "csl1", "--style", "apa", "--db", db])
    assert json.loads(f.stdout)["data"]["text"] == "Doe, J. (2021). From CSL. J. Csl."


def test_cli_format_renders_the_library_in_apa(tmp_path):
    bib = _bib(tmp_path)
    db = _db(tmp_path)
    assert _cli(["cite", "import", str(bib), "--db", db]).returncode == 0
    r = _cli(["cite", "format", "--style", "apa", "--sort", "author", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["count"] == 2 and data["formatted"] == 2 and data["failed"] == 0
    assert [e["key"] for e in data["entries"]] == ["doe2020", "fontaine2015"]
    assert data["entries"][0]["text"].startswith("Doe, J., & Roe, R. (2020).")
    assert "de la Fontaine, J. (2015)" in data["text"]


def test_cli_format_from_a_file_needs_no_library(tmp_path):
    bib = _bib(tmp_path)
    r = _cli(["cite", "format", "--file", str(bib), "--style", "ieee", "--db", str(tmp_path / "absent.db")])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["formatted"] == 2 and data["source"].endswith("refs.bib")
    assert not (tmp_path / "absent.db").exists()


def test_cli_format_strict_exits_one_when_an_entry_cannot_render(tmp_path):
    bib = _bib(tmp_path, body="@article{thin, title = {No author, no journal}, year={2022}}")
    r = _cli(["cite", "format", "--file", str(bib), "--style", "apa", "--strict"])
    assert r.returncode == 1, r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["failed"] == 1 and data["entries"][0]["text"] is None
    assert "missing author, journal" in data["entries"][0]["error"]
    loose = _cli(["cite", "format", "--file", str(bib), "--style", "apa"])
    assert loose.returncode == 0  # without --strict it reports and exits 0


def test_cli_format_rejects_a_bad_style_and_sort(tmp_path):
    bib = _bib(tmp_path)
    r = _cli(["cite", "format", "--file", str(bib), "--style", "harvard"])
    assert r.returncode == 1 and "--style must be one of" in json.loads(r.stdout)["error"]
    r2 = _cli(["cite", "format", "--file", str(bib), "--sort", "vibes"])
    assert r2.returncode == 1 and "--sort must be one of" in json.loads(r2.stdout)["error"]


def test_cli_format_unknown_key_fails_actionably(tmp_path):
    bib = _bib(tmp_path)
    db = _db(tmp_path)
    assert _cli(["cite", "import", str(bib), "--db", db]).returncode == 0
    r = _cli(["cite", "format", "--key", "ghost", "--db", db])
    assert r.returncode == 1
    assert "not in the library: ghost" in json.loads(r.stdout)["error"]


def test_cli_commands_need_a_library_and_say_so(tmp_path):
    absent = str(tmp_path / "absent.db")
    for args in (["cite", "list"], ["cite", "roundtrip"], ["cite", "forget", "--key", "x"]):
        r = _cli([*args, "--db", absent])
        assert r.returncode == 1, args
        assert "no citation library" in json.loads(r.stdout)["error"]


def test_cli_list_filters_and_reports_library_stats(tmp_path):
    bib = _bib(tmp_path)
    db = _db(tmp_path)
    assert _cli(["cite", "import", str(bib), "--db", db]).returncode == 0
    r = _cli(["cite", "list", "--author", "fontaine", "--db", db])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["count"] == 1
    row = data["entries"][0]
    assert row["key"] == "fontaine2015" and row["first_author"] == "de la Fontaine, Jean"
    assert row["title"] == "Nested BibTeX Braces" and row["missing_required"] == []
    assert data["library"]["entries"] == 2
    empty = _cli(["cite", "list", "--year-min", "3000", "--db", db])
    assert json.loads(empty.stdout)["data"]["count"] == 0
    bad_doi = _cli(["cite", "list", "--doi", "10.1/typo", "--db", db])
    assert bad_doi.returncode == 1
    assert "could never match" in json.loads(bad_doi.stdout)["error"]


def test_cli_roundtrip_is_clean_on_a_real_library(tmp_path):
    bib = _bib(tmp_path)
    db = _db(tmp_path)
    assert _cli(["cite", "import", str(bib), "--db", db]).returncode == 0
    r = _cli(["cite", "roundtrip", "--db", db, "--fail-on", "error"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["checked"] == 2 and data["identical"] == 2 and data["store_faithful"] == 2
    assert data["lost_fields"] == [] and data["diagnostics"] == []


def test_cli_roundtrip_on_a_file_does_not_claim_a_store_measurement(tmp_path):
    bib = _bib(tmp_path)
    r = _cli(["cite", "roundtrip", "--file", str(bib)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["checked"] == 2 and data["identical"] == 2
    assert data["store_faithful"] is None  # no store was involved, so nothing is claimed


def test_cli_forget_needs_yes_then_deletes(tmp_path):
    bib = _bib(tmp_path)
    db = _db(tmp_path)
    assert _cli(["cite", "import", str(bib), "--db", db]).returncode == 0
    dry = _cli(["cite", "forget", "--key", "doe2020", "--key", "ghost", "--db", db])
    assert dry.returncode == 0
    dry_data = json.loads(dry.stdout)["data"]
    assert dry_data["dry_run"] is True
    assert dry_data["would_delete"] == ["doe2020"] and dry_data["not_found"] == ["ghost"]
    assert json.loads(_cli(["cite", "list", "--db", db]).stdout)["data"]["count"] == 2
    real = _cli(["cite", "forget", "--key", "doe2020", "--yes", "--db", db])
    assert json.loads(real.stdout)["data"]["deleted"] == ["doe2020"]
    assert json.loads(_cli(["cite", "list", "--db", db]).stdout)["data"]["count"] == 1


def test_cli_rules_overlay_that_disables_a_rejecting_rule_is_refused(tmp_path):
    bad = tmp_path / "over.json"
    bad.write_text(json.dumps({"cite:missing-key": {"enabled": False}}), encoding="utf-8")
    r = _cli(["cite", "rules", "--rules", str(bad)])
    assert r.returncode == 1
    assert "bad rules overlay" in json.loads(r.stdout)["error"]
    assert "cannot be disabled" in json.loads(r.stdout)["error"]


def test_a_type_the_parser_normalizes_is_reported_as_a_key_or_type_change():
    """The `type_preserved` conjunct of `identical` IS reachable — pin it.

    test_roundtrip_marks_a_key_or_type_change_when_the_key_is_unemittable claims this
    ground but never reaches it: it uses an unemittable key, so roundtrip_report
    returns early with `error` set and the key/type comparison never runs. Any failure
    mode satisfies its assertion.

    This reaches the branch. A mixed-case type round-trips SUCCESSFULLY (error None,
    reparsed True) and still comes back changed, because the parser normalizes the
    entry type to lower case. That is a real fidelity loss the audit must report
    rather than call the entry identical — unlike `changed_fields`, which the module
    documents as unreachable while the emitter stays verbatim.
    """
    for declared in ("Article", "ARTICLE"):
        rep = cite.roundtrip_report(
            {"key": "k1", "type": declared, "fields": {"title": "T", "year": "2020"}}
        )
        assert rep["error"] is None, "the round trip must SUCCEED, or the branch is skipped"
        assert rep["reparsed"] is True
        assert rep["type_preserved"] is False, declared
        assert rep["identical"] is False
        # and the loss is in the type, not smuggled in as a field diff
        assert rep["lost_fields"] == [] and rep["added_fields"] == []

    # `type_preserved` is a CONJUNCTION of two comparisons (type AND key), so each half
    # needs a case that isolates it. The loop above only moves the TYPE, which is why a
    # mutation dropping the KEY half survived all 153 tests. A padded key is the
    # reachable case: to_bibtex emits "@article{k1 ," and the parser strips the padding,
    # so the round trip SUCCEEDS and the key still comes back changed. Under the mutant
    # the audit called such an entry identical while its citation key had silently moved.
    padded = cite.roundtrip_report(
        {"key": "k1 ", "type": "article", "fields": {"title": "T", "year": "2020"}}
    )
    assert padded["error"] is None and padded["reparsed"] is True
    assert padded["type_preserved"] is False, "a changed KEY must not read as preserved"
    assert padded["identical"] is False
    assert padded["lost_fields"] == [] and padded["added_fields"] == []

    # the all-lowercase, unpadded control round-trips clean, so the assertions above are
    # a contrast rather than a property of every input
    ok = cite.roundtrip_report(
        {"key": "k1", "type": "article", "fields": {"title": "T", "year": "2020"}}
    )
    assert ok["type_preserved"] is True and ok["identical"] is True
