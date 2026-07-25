"""CVE — openswap #29 (Snyk/Dependabot -> stdlib manifest parsing + PEP 440 /
SemVer ordering + OSV range matching + CVSS v3 arithmetic against a CACHED
snapshot file). Pure-logic core tests: version ordering against the PEP 440 and
SemVer 2.0.0 specs' own examples, CVSS base scores against published reference
vectors, the value-XOR-error honesty invariant on every reading, manifest and
lockfile parsing, the OSV interval walk including the two failure modes that
would fabricate a verdict (a dropped range boundary, a withdrawn advisory),
every rule firing AND every rule staying quiet on a clean tree, the rules
overlay, the zero-egress manifest guard, the no-snapshot refusal, and the real
CLI in a subprocess. Offline and deterministic by construction: every input is a
string or a dict, nothing is fetched, and no socket is opened on any path."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import cve, openswap

ROOT = Path(__file__).resolve().parents[1]

# A fixed clock so snapshot-age arithmetic is deterministic: 2026-07-19T00:00:00Z.
NOW = 1784419200.0
FRESH = "2026-07-18T00:00:00Z"  # one day before NOW
OLD = "2024-01-01T00:00:00Z"


def _rng(*events, kind: str = "ECOSYSTEM") -> dict:
    return {"type": kind, "events": [dict([e]) for e in events]}


def _osv(vid: str, eco: str, name: str, *ranges, **extra) -> dict:
    record = {
        "id": vid,
        "affected": [{"package": {"ecosystem": eco, "name": name}, "ranges": list(ranges)}],
    }
    record.update(extra)
    return record


def _snap(records: list[dict], generated: str | None = FRESH) -> dict:
    payload: dict = {"advisories": records}
    if generated is not None:
        payload["generated"] = generated
    return cve.load_snapshot(payload)


REQUESTS_ADVISORY = _osv(
    "GHSA-requests-1",
    "PyPI",
    "requests",
    _rng(("introduced", "2.3.0"), ("fixed", "2.31.0")),
    aliases=["CVE-2023-32681"],
    summary="Proxy-Authorization leak",
    severity=[{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:N/A:N"}],
)
LODASH_ADVISORY = _osv(
    "GHSA-lodash-1",
    "npm",
    "lodash",
    _rng(("introduced", "0"), ("fixed", "4.17.21"), kind="SEMVER"),
    database_specific={"severity": "HIGH"},
)
SNAPSHOT = _snap([REQUESTS_ADVISORY, LODASH_ADVISORY])


def _report(text: str, filename: str, snapshot: dict | None = None, rules=None) -> dict:
    return cve.audit_manifest(
        cve.parse_manifest(text, filename),
        snapshot if snapshot is not None else SNAPSHOT,
        path=filename,
        rules=rules,
    )


def _rules_fired(text: str, filename: str, snapshot: dict | None = None, rules=None) -> set[str]:
    return {d["rule"] for d in _report(text, filename, snapshot, rules)["diagnostics"]}


# ---- name normalization -----------------------------------------------------


def test_pypi_names_collapse_per_pep503_and_npm_names_only_lowercase():
    same = {cve.normalize_name(n, cve.ECO_PYPI) for n in ("Flask_Login", "flask.login", "FLASK--LOGIN")}
    assert same == {"flask-login"}  # every spelling reaches ONE lookup key
    assert cve.normalize_name("flask", cve.ECO_PYPI) != cve.normalize_name("flask-login", cve.ECO_PYPI)
    assert cve.normalize_name("@babel/Core", cve.ECO_NPM) == "@babel/core"  # scope kept
    # npm does NOT collapse separators: left-pad and left_pad are different packages
    assert cve.normalize_name("left_pad", cve.ECO_NPM) != cve.normalize_name("left-pad", cve.ECO_NPM)


def test_canonical_ecosystem_maps_osv_spellings_and_refuses_the_rest():
    assert cve.canonical_ecosystem("PyPI") == cve.ECO_PYPI
    assert cve.canonical_ecosystem("pypi") == cve.ECO_PYPI
    assert cve.canonical_ecosystem("npm") == cve.ECO_NPM
    for out_of_scope in ("Maven", "Go", "Alpine:v3.16", "crates.io", None, 7, ""):
        assert cve.canonical_ecosystem(out_of_scope) is None, out_of_scope


# ---- PEP 440 ordering -------------------------------------------------------

PEP440_ASCENDING = (
    "1.0.dev1", "1.0a1", "1.0a2", "1.0b1", "1.0rc1", "1.0", "1.0+local",
    "1.0.post1", "1.0.1", "1.1", "2!0.1", "2!1.0",
)


def test_pep440_orders_the_canonical_sequence():
    keys = [cve.parse_pep440(v) for v in PEP440_ASCENDING]
    assert all(k is not None for k in keys), PEP440_ASCENDING
    ascending = [
        (PEP440_ASCENDING[i], PEP440_ASCENDING[i + 1])
        for i in range(len(keys) - 1)
        if not keys[i] < keys[i + 1]
    ]
    assert ascending == [], f"out of order: {ascending}"


def test_pep440_equivalences_and_dev_post_interaction():
    assert cve.parse_pep440("1.0") == cve.parse_pep440("1.0.0")  # trailing zeros
    assert cve.parse_pep440("1.0alpha1") == cve.parse_pep440("1.0a1")  # spelling alias
    assert cve.parse_pep440("1.0preview2") == cve.parse_pep440("1.0rc2")
    assert cve.parse_pep440("v1.2.3") == cve.parse_pep440("1.2.3")  # optional v prefix
    # a dev release of a post release sorts BELOW that post release, not below 1.0
    assert cve.parse_pep440("1.0.post1.dev1") < cve.parse_pep440("1.0.post1")
    assert cve.parse_pep440("1.0") < cve.parse_pep440("1.0.post1.dev1")
    assert cve.parse_pep440("1.0-1") == cve.parse_pep440("1.0.post1")  # implicit post


def test_pep440_rejects_non_versions():
    for bad in ("", "   ", "abc", "1..2", "1.0.x", "next", "latest", "1.0-beta-gamma",
                "==1.0", ">=1.0", None, 12, "1.0 2.0"):
        assert cve.parse_pep440(bad) is None, bad


# ---- SemVer 2.0.0 ordering --------------------------------------------------

# The precedence example printed in the SemVer 2.0.0 specification itself.
SEMVER_ASCENDING = (
    "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
    "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.0.1", "1.1.0", "2.0.0",
)


def test_semver_orders_the_specs_own_precedence_example():
    keys = [cve.parse_semver(v) for v in SEMVER_ASCENDING]
    assert all(k is not None for k in keys), SEMVER_ASCENDING
    ascending = [
        (SEMVER_ASCENDING[i], SEMVER_ASCENDING[i + 1])
        for i in range(len(keys) - 1)
        if not keys[i] < keys[i + 1]
    ]
    assert ascending == [], f"out of order: {ascending}"
    # numeric identifiers compare numerically, not as strings (11 > 2)
    assert cve.parse_semver("1.0.0-beta.2") < cve.parse_semver("1.0.0-beta.11")


def test_semver_discards_build_metadata_and_rejects_non_semver():
    assert cve.parse_semver("1.0.0+build.1") == cve.parse_semver("1.0.0+build.2")
    assert cve.parse_semver("1.0.0+build.1") == cve.parse_semver("1.0.0")
    for bad in ("1.2", "0", "01.2.3", "1.2.3.4", "v", "x", "", None, "^1.2.3", "1.2.3-"):
        assert cve.parse_semver(bad) is None, bad


def test_version_key_and_compare_are_ecosystem_scoped():
    assert cve.version_key("1.2", cve.ECO_PYPI) is not None  # valid PEP 440
    assert cve.version_key("1.2", cve.ECO_NPM) is None  # NOT valid semver
    assert cve.compare_versions("1.2.0", "1.10.0", cve.ECO_NPM) == -1
    assert cve.compare_versions("1.10.0", "1.2.0", cve.ECO_NPM) == 1
    assert cve.compare_versions("1.0", "1.0.0", cve.ECO_PYPI) == 0
    assert cve.compare_versions("1.0", "nope", cve.ECO_PYPI) is None
    assert cve.version_key("1.0", "Maven") is None  # no comparator for it here


# ---- CVSS v3 arithmetic -----------------------------------------------------

# Published base scores for these vectors (FIRST's CVSS v3.1 examples and the
# calculator). Each one is external reference data, not a restatement of the code.
CVSS_REFERENCE = {
    "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H": 9.8,
    "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H": 10.0,
    "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H": 9.9,
    "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H": 7.8,
    "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N": 7.5,
    "CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N": 6.1,
    "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:N/A:H": 5.9,
    "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N": 5.3,
    "CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:L/A:L": 3.5,
    "CVSS:3.1/AV:L/AC:H/PR:H/UI:R/S:U/C:N/I:N/A:L": 1.8,
    "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N": 0.0,
    "CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H": 9.8,
}


def test_cvss_base_scores_match_published_reference_vectors():
    for vector, expected in CVSS_REFERENCE.items():
        metrics = cve.parse_cvss_vector(vector)
        assert metrics is not None, vector
        assert cve.cvss_base_score(metrics) == expected, vector


def test_cvss_scope_change_raises_the_score_for_identical_impact():
    unchanged = cve.parse_cvss_vector("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H")
    changed = cve.parse_cvss_vector("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H")
    assert cve.cvss_base_score(changed) > cve.cvss_base_score(unchanged)
    # zero impact short-circuits to 0.0 whatever the exploitability metrics say
    easy_no_impact = cve.parse_cvss_vector("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N")
    assert cve.cvss_base_score(easy_no_impact) == 0.0


def test_cvss_roundup_takes_the_ceiling_to_one_decimal():
    assert cve._roundup(8.0) == 8.0  # already exact, must not gain 0.1
    assert cve._roundup(4.02) == 4.1
    assert cve._roundup(4.0999) == 4.1
    assert cve._roundup(0.0) == 0.0
    assert cve._roundup(9.999) == 10.0


def test_cvss_rating_bands_are_the_v31_scale():
    assert [cve.cvss_rating(s) for s in (0.0, 0.1, 3.9)] == ["none", "low", "low"]
    assert [cve.cvss_rating(s) for s in (4.0, 6.9)] == ["medium", "medium"]
    assert [cve.cvss_rating(s) for s in (7.0, 8.9)] == ["high", "high"]
    assert [cve.cvss_rating(s) for s in (9.0, 10.0)] == ["critical", "critical"]


def test_parse_cvss_vector_refuses_what_it_cannot_score():
    for bad in (
        "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",           # no version prefix
        "CVSS:2.0/AV:N/AC:L/Au:N/C:P/I:P/A:P",           # v2 uses different weights
        "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H",  # v4 has a new formula
        "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H",      # A missing
        "CVSS:3.1/AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",  # AV:X is not a metric value
        "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:X/C:H/I:H/A:H",  # bad scope
        "CVSS:3.1/AV:N/AC:L/PR:X/UI:N/S:U/C:H/I:H/A:H",  # bad privileges
        "", None, 3,
    ):
        assert cve.parse_cvss_vector(bad) is None, bad


def test_privileges_required_weight_depends_on_scope():
    """PR:L is worth more when scope changes — the one scope-coupled metric."""
    u = cve.parse_cvss_vector("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N")
    c = cve.parse_cvss_vector("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:L/I:N/A:N")
    assert cve._PR_WEIGHTS["C"]["L"] > cve._PR_WEIGHTS["U"]["L"]
    assert cve.cvss_base_score(c) > cve.cvss_base_score(u)


# ---- the reading honesty invariant -----------------------------------------


def test_reading_helper_refuses_both_and_neither():
    assert cve._reading(3, None)["value"] == 3
    assert cve._reading(None, "why")["error"] == "why"
    with pytest.raises(ValueError, match="exactly one"):
        cve._reading(3, "why")
    with pytest.raises(ValueError, match="exactly one"):
        cve._reading(None, None)


def test_advisory_severity_score_and_rating_are_separate_readings():
    computed = cve.advisory_severity(REQUESTS_ADVISORY)
    assert computed["score"]["value"] == 5.9 and computed["score"]["error"] is None
    assert computed["score"]["vector"].startswith("CVSS:3.1/")
    assert computed["rating"]["value"] == "medium"
    assert "computed from the CVSS" in computed["rating"]["source"]

    # a GHSA export with a textual severity and NO vector: rating real, score errored
    textual = cve.advisory_severity(LODASH_ADVISORY)
    assert textual["score"]["value"] is None
    assert "no severity vector" in textual["score"]["error"]
    assert textual["rating"]["value"] == "high"
    assert textual["rating"]["source"] == "database_specific.severity"

    # nothing declared at all: BOTH readings are errors, neither invents a number
    silent = cve.advisory_severity({"id": "X"})
    assert silent["score"]["value"] is None and silent["score"]["error"]
    assert silent["rating"]["value"] is None and silent["rating"]["error"]

    # a vector this core cannot score names the versions it saw
    v4 = cve.advisory_severity(
        {"id": "X", "severity": [{"type": "CVSS_V4", "score": "CVSS:4.0/AV:N/AC:L"}]}
    )
    assert v4["score"]["value"] is None and "CVSS_V4" in v4["score"]["error"]


def test_every_severity_reading_is_value_xor_error():
    records = [
        REQUESTS_ADVISORY,
        LODASH_ADVISORY,
        {"id": "a"},
        {"id": "b", "severity": []},
        {"id": "c", "severity": [{"type": "CVSS_V3", "score": "garbage"}]},
        {"id": "d", "database_specific": {"severity": "nonsense"}},
        {"id": "e", "database_specific": {"severity": "CRITICAL"}},
        {"id": "f", "severity": [{"type": "CVSS_V2", "score": "AV:N/AC:L/Au:N/C:P/I:P/A:P"}]},
    ]
    for record in records:
        sev = cve.advisory_severity(record)
        for kind in ("score", "rating"):
            reading = sev[kind]
            assert (reading["value"] is None) != (reading["error"] is None), (record, kind)


# ---- pinning: version XOR pin_reason ----------------------------------------


def test_pypi_pin_only_accepts_an_exact_equals():
    assert cve.pypi_pin("==2.30.0") == ("2.30.0", None)
    assert cve.pypi_pin("===1.0-legacy")[0] == "1.0-legacy"  # arbitrary-equality pin
    assert cve.pypi_pin(" == 2.30.0 ")[0] == "2.30.0"
    assert cve.pypi_pin("==2.30.0,!=2.30.1")[0] == "2.30.0"  # pin plus an exclusion
    for ranged in (">=2.0", "<3", "~=2.1", "!=2.0", "==2.*", "==2.30.*", ">=1,<2", ""):
        version, reason = cve.pypi_pin(ranged)
        assert version is None and reason, ranged
    conflicting, reason = cve.pypi_pin("==1.0,==2.0")
    assert conflicting is None and "conflicting pins" in reason


def test_npm_pin_only_accepts_an_exact_semver():
    assert cve.npm_pin("4.17.20") == ("4.17.20", None)
    assert cve.npm_pin("=4.17.20")[0] == "4.17.20"
    assert cve.npm_pin("1.0.0-rc.1")[0] == "1.0.0-rc.1"
    for ranged in ("^1.3.0", "~1.3.0", ">=1.0.0", "<2.0.0", "1.x", "*", "latest", "next",
                   "1.0.0 - 2.0.0", "1.0.0 || 2.0.0", "", "1.2"):
        version, reason = cve.npm_pin(ranged)
        assert version is None and reason, ranged
    for protocol in ("file:../a", "git+https://example.invalid/x.git", "workspace:*",
                     "npm:other@1.0.0", "link:../b", "https://example.invalid/x.tgz"):
        version, reason = cve.npm_pin(protocol)
        assert version is None and "reference, not a registry version" in reason, protocol


def test_pin_reasons_name_the_construct_that_made_the_version_unknown():
    assert "caret" in cve.npm_pin("^1.0.0")[1]
    assert "tilde" in cve.npm_pin("~1.0.0")[1]
    assert "range, not a pin" in cve.pypi_pin(">=1.0")[1]
    assert "no version specifier at all" in cve.pypi_pin("")[1]


def test_exact_pin_routes_through_the_ecosystems_own_rule():
    assert cve.exact_pin("2.30.0", cve.ECO_PYPI) == ("2.30.0", None)
    assert cve.exact_pin("4.17.20", cve.ECO_NPM) == ("4.17.20", None)
    # a range typed at the CLI is refused, not treated as a literal version
    assert cve.exact_pin("2.*", cve.ECO_PYPI)[0] is None
    assert cve.exact_pin("^1.0.0", cve.ECO_NPM)[0] is None
    assert cve.exact_pin("", cve.ECO_PYPI)[0] is None
    assert cve.exact_pin("1.0", "Maven") == (None, "ecosystem 'Maven' has no pin rule in this core")


def test_dependency_requires_exactly_one_of_version_and_pin_reason():
    good = cve.dependency(
        name="Flask_Login", ecosystem=cve.ECO_PYPI, specifier="==1.0",
        version="1.0", pin_reason=None, field="requirements", line=3,
    )
    assert good["key"] == "flask-login" and good["name"] == "Flask_Login"
    assert good["line"] == 3 and good["version"] == "1.0"
    with pytest.raises(ValueError, match="exactly one"):
        cve.dependency(name="x", ecosystem=cve.ECO_PYPI, specifier="", version="1.0",
                       pin_reason="also a reason", field="f")
    with pytest.raises(ValueError, match="exactly one"):
        cve.dependency(name="x", ecosystem=cve.ECO_PYPI, specifier="", version=None,
                       pin_reason=None, field="f")


# ---- requirements.txt -------------------------------------------------------

REQUIREMENTS = """\
# a comment line
requests==2.30.0
flask >= 2.0, <3     # trailing comment after a range
Django[bcrypt]==4.2.1 ; python_version >= "3.8"
-r extra.txt
--constraint pins.txt
-e .
--index-url https://example.invalid/simple
--totally-unknown-option
urllib3 @ https://example.invalid/urllib3.whl
pinned-with-hashes==1.0 --hash=sha256:aaa \
    --hash=sha256:bbb
!!! not a requirement !!!
"""


def test_parse_requirements_reads_specifiers_extras_markers_and_line_numbers():
    parsed = cve.parse_requirements(REQUIREMENTS)
    by_name = {d["name"]: d for d in parsed["dependencies"]}
    assert by_name["requests"]["version"] == "2.30.0" and by_name["requests"]["line"] == 2
    assert by_name["flask"]["version"] is None and by_name["flask"]["line"] == 3
    assert "range, not a pin" in by_name["flask"]["pin_reason"]
    assert by_name["Django"]["version"] == "4.2.1" and by_name["Django"]["extras"] == "bcrypt"
    assert by_name["Django"]["marker"] == 'python_version >= "3.8"'
    # a line continuation keeps the FIRST physical line number and drops the hashes
    assert by_name["pinned-with-hashes"]["version"] == "1.0"
    assert by_name["pinned-with-hashes"]["line"] == 11  # not 12, the continuation
    assert parsed["ecosystem"] == cve.ECO_PYPI and parsed["error"] is None


def test_parse_requirements_labels_every_line_it_did_not_audit():
    parsed = cve.parse_requirements(REQUIREMENTS)
    notes = {n["kind"] for n in parsed["notes"]}
    assert notes == {"unresolved-include", "ecosystem-unsupported", "option-ignored",
                     "unparsed-line"}
    includes = [n for n in parsed["notes"] if n["kind"] == "unresolved-include"]
    assert {n["line"] for n in includes} == {5, 6}  # -r AND --constraint both counted
    assert all("NOT audited" in n["detail"] for n in includes)
    unknown = [n for n in parsed["notes"] if "unrecognized" in n["detail"]]
    assert [n["line"] for n in unknown] == [9]  # only the unknown option says so
    # a direct URL reference is a dependency with no auditable version
    url_dep = next(d for d in parsed["dependencies"] if d["name"] == "urllib3")
    assert url_dep["version"] is None and "direct URL reference" in url_dep["pin_reason"]


def test_parse_requirements_keeps_a_hash_inside_a_url_fragment():
    parsed = cve.parse_requirements("pkg @ https://example.invalid/a.whl#sha256=abc\n")
    assert len(parsed["dependencies"]) == 1
    assert "sha256=abc" in parsed["dependencies"][0]["pin_reason"]
    assert parsed["notes"] == []


def test_parse_requirements_tolerates_empty_and_comment_only_bodies():
    for body in ("", "\n\n", "# only a comment\n", "   \n\t\n"):
        parsed = cve.parse_requirements(body)
        assert parsed["dependencies"] == [] and parsed["notes"] == [], body
        assert parsed["error"] is None


# ---- pyproject / TOML locks / package.json / package-lock.json --------------

PYPROJECT = """\
[project]
name = "demo"
dependencies = ["requests==2.30.0", "flask>=2.0"]

[project.optional-dependencies]
dev = ["pytest==8.0.0"]

[tool.poetry.dependencies]
python = "^3.11"
urllib3 = "1.26.5"
lodash-py = { version = "2.0.0" }
caret = "^1.2.3"
"""


def test_parse_pyproject_reads_pep621_and_poetry_tables():
    parsed = cve.parse_pyproject(PYPROJECT)
    by_name = {d["name"]: d for d in parsed["dependencies"]}
    assert by_name["requests"]["version"] == "2.30.0"
    assert by_name["requests"]["field"] == "project.dependencies"
    assert by_name["flask"]["version"] is None
    assert by_name["pytest"]["field"] == "project.optional-dependencies.dev"
    assert by_name["urllib3"]["version"] == "1.26.5"
    assert by_name["lodash-py"]["version"] == "2.0.0"  # table form with a version key
    assert by_name["caret"]["version"] is None
    assert "range, not a pin" in by_name["caret"]["pin_reason"]
    assert "python" not in by_name  # the interpreter constraint is not a PyPI package
    # every JSON/TOML dependency carries line 0: tomllib reports no source offsets
    assert {d["line"] for d in parsed["dependencies"]} == {0}


def test_parse_pyproject_reports_bad_toml_instead_of_raising():
    broken = cve.parse_pyproject("[project\nname = ")
    assert broken["dependencies"] == [] and broken["error"]
    assert broken["kind"] == "pyproject.toml"
    empty = cve.parse_pyproject("")
    assert empty["error"] is None and empty["dependencies"] == []


def test_parse_pyproject_says_why_when_tomllib_is_missing(monkeypatch):
    """A 3.10 interpreter must degrade with a labelled reason, not crash."""
    monkeypatch.setattr(cve, "tomllib", None)
    degraded = cve.parse_pyproject(PYPROJECT)
    assert degraded["dependencies"] == []
    assert "tomllib is unavailable" in degraded["error"]
    assert cve.parse_python_lock("[[package]]\nname='x'\nversion='1.0'")["error"]


UV_LOCK = """\
version = 1

[[package]]
name = "requests"
version = "2.30.0"

[[package]]
name = "Flask-Login"
version = "0.6.3"

[[package]]
name = "no-version-here"
"""


def test_parse_python_lock_pins_every_resolved_package():
    parsed = cve.parse_python_lock(UV_LOCK)
    pins = {d["key"]: d["version"] for d in parsed["dependencies"]}
    assert pins == {"requests": "2.30.0", "flask-login": "0.6.3"}
    assert all(d["pin_reason"] is None for d in parsed["dependencies"])
    assert [n["kind"] for n in parsed["notes"]] == ["unparsed-line"]
    assert "no resolved version" in parsed["notes"][0]["detail"]


PACKAGE_JSON = """\
{
  "name": "demo",
  "dependencies": {"lodash": "4.17.20", "left-pad": "^1.3.0"},
  "devDependencies": {"jest": "29.0.0"},
  "peerDependencies": {"react": ">=17"},
  "optionalDependencies": {"fsevents": "2.3.2"},
  "resolutions": {"ignored": "1.0.0"}
}
"""


def test_parse_package_json_reads_every_dependency_table():
    parsed = cve.parse_package_json(PACKAGE_JSON)
    by_field: dict[str, set] = {}
    for d in parsed["dependencies"]:
        by_field.setdefault(d["field"], set()).add(d["name"])
    assert by_field == {
        "dependencies": {"lodash", "left-pad"},
        "devDependencies": {"jest"},
        "peerDependencies": {"react"},
        "optionalDependencies": {"fsevents"},
    }
    assert "ignored" not in {d["name"] for d in parsed["dependencies"]}
    pinned = {d["name"] for d in parsed["dependencies"] if d["version"] is not None}
    assert pinned == {"lodash", "jest", "fsevents"}  # the ranges got no version


def test_parse_package_json_reports_bad_json_instead_of_raising():
    for bad in ("{", "[]", "null", "not json"):
        parsed = cve.parse_package_json(bad)
        assert parsed["dependencies"] == [] and parsed["error"], bad


PACKAGE_LOCK_V3 = """\
{
  "name": "demo",
  "lockfileVersion": 3,
  "packages": {
    "": {"name": "demo", "version": "1.0.0"},
    "node_modules/lodash": {"version": "4.17.20"},
    "node_modules/@babel/core": {"version": "7.24.0"},
    "node_modules/a/node_modules/nested": {"version": "1.0.0"},
    "node_modules/no-version": {"resolved": "https://example.invalid/x.tgz"}
  }
}
"""
PACKAGE_LOCK_V1 = """\
{
  "lockfileVersion": 1,
  "dependencies": {
    "lodash": {"version": "4.17.20",
               "dependencies": {"deep": {"version": "2.0.0"}}}
  }
}
"""


def test_parse_package_lock_v3_resolves_names_and_excludes_the_root():
    parsed = cve.parse_package_lock(PACKAGE_LOCK_V3)
    pins = {d["name"]: d["version"] for d in parsed["dependencies"]}
    assert pins == {"lodash": "4.17.20", "@babel/core": "7.24.0", "nested": "1.0.0"}
    assert "demo" not in pins  # the "" entry is the project, not a dependency
    assert parsed["lockfile_version"] == 3
    assert [n["kind"] for n in parsed["notes"]] == ["unparsed-line"]
    assert "no-version" in parsed["notes"][0]["detail"]


def test_parse_package_lock_v1_walks_nested_dependencies():
    parsed = cve.parse_package_lock(PACKAGE_LOCK_V1)
    pins = {d["name"]: d["version"] for d in parsed["dependencies"]}
    assert pins == {"lodash": "4.17.20", "deep": "2.0.0"}  # transitive included
    assert parsed["lockfile_version"] == 1


def test_lock_name_strips_only_the_last_node_modules_segment():
    assert cve._lock_name("node_modules/a/node_modules/b") == "b"
    assert cve._lock_name("node_modules/@scope/pkg") == "@scope/pkg"
    assert cve._lock_name("") == ""  # the root project entry


# ---- manifest dispatch ------------------------------------------------------


def test_manifest_kind_dispatches_on_the_file_name_only():
    expected = {
        "requirements.txt": "requirements.txt",
        "requirements-dev.txt": "requirements.txt",
        "dev-requirements.txt": "requirements.txt",
        "requirements.in": "requirements.txt",
        "a/b/pyproject.toml": "pyproject.toml",
        "a\\b\\package.json": "package.json",
        "package-lock.json": "package-lock.json",
        "uv.lock": "python-lock",
        "poetry.lock": "python-lock",
        "PACKAGE.JSON": "package.json",
    }
    assert {n: cve.manifest_kind(n) for n in expected} == expected
    for unknown in ("notes.md", "Cargo.toml", "go.mod", "yarn.lock", "", "requirements"):
        assert cve.manifest_kind(unknown) is None, unknown


def test_parse_manifest_refuses_a_name_it_does_not_own():
    parsed = cve.parse_manifest("anything", "Cargo.toml")
    assert parsed["dependencies"] == [] and parsed["ecosystem"] is None
    assert "not a manifest this core reads" in parsed["error"]
    # dispatch really is by name: requirements content in a package.json name fails
    mislabelled = cve.parse_manifest("requests==2.30.0", "package.json")
    assert mislabelled["dependencies"] == [] and mislabelled["error"]


def test_poetry_dialect_treats_a_bare_version_as_exact():
    assert cve.poetry_pin("1.26.5") == ("1.26.5", None)
    assert cve.poetry_pin("==1.26.5") == ("1.26.5", None)
    for ranged in ("^1.2.3", "~1.2", "*", "1.*", ">=1,<2", ">=1.0", ""):
        version, reason = cve.poetry_pin(ranged)
        assert version is None and reason, ranged
    assert "wildcard" in cve.poetry_pin("1.*")[1]
    assert "range, not a pin" in cve.poetry_pin("^1.0")[1]


# ---- snapshot indexing ------------------------------------------------------


def test_load_snapshot_indexes_by_normalized_name_and_ecosystem():
    snap = _snap([REQUESTS_ADVISORY, LODASH_ADVISORY])
    assert set(snap["index"]) == {("PyPI", "requests"), ("npm", "lodash")}
    assert snap["counts"]["records"] == 2 and snap["counts"]["packages"] == 2
    assert snap["meta"]["generated"] == FRESH
    # the PyPI lookup is normalized on BOTH sides of the join
    odd = _snap([_osv("X", "PyPI", "Flask_Login", _rng(("introduced", "0")))])
    assert ("PyPI", "flask-login") in odd["index"]


def test_load_snapshot_accepts_a_bare_list_and_reports_it_undated():
    snap = cve.load_snapshot([REQUESTS_ADVISORY])
    assert snap["meta"] == {} and snap["counts"]["records"] == 1
    age = cve.snapshot_age(snap["meta"], NOW)
    assert age["age_days"] is None and "no generation date" in age["error"]


def test_load_snapshot_counts_what_it_could_not_use_instead_of_dropping_it():
    snap = _snap(
        [
            REQUESTS_ADVISORY,
            _osv("MAVEN-1", "Maven", "org.x:y", _rng(("introduced", "0"))),
            _osv("GO-1", "Go", "example.com/x", _rng(("introduced", "0"))),
            _osv("WD-1", "PyPI", "flask", _rng(("introduced", "0")), withdrawn=OLD),
            {"id": "NO-AFFECTED"},
            {"id": "EMPTY-AFFECTED", "affected": []},
        ]
    )
    counts = snap["counts"]
    assert counts["records"] == 6
    assert counts["out_of_scope_ecosystems"] == {"Go": 1, "Maven": 1}
    assert counts["withdrawn"] == 1  # still indexed, but flagged
    assert counts["unusable"] == 2  # the two records with no affected entry
    assert ("PyPI", "flask") in snap["index"]  # withdrawn records ARE indexed


def test_load_snapshot_rejects_shapes_that_would_read_as_a_clean_audit():
    for bad in ({"foo": 1}, {}, "a string", 7, None, {"advisories": {"not": "a list"}}):
        with pytest.raises(cve.SnapshotError):
            cve.load_snapshot(bad)
    # the alternate key names OSV exports use are accepted
    assert cve.load_snapshot({"vulns": [REQUESTS_ADVISORY]})["counts"]["records"] == 1
    assert cve.load_snapshot({"records": []})["counts"]["records"] == 0


def test_an_empty_advisory_list_is_a_real_but_empty_index():
    """Legal, and NOT an error — but every package then has no records."""
    snap = _snap([])
    assert snap["index"] == {} and snap["counts"]["records"] == 0
    report = _report("requests==2.30.0\n", "requirements.txt", snapshot=snap)
    assert report["counts"]["checked"] == 1
    assert report["counts"]["packages_without_records"] == 1
    assert report["counts"]["vulnerable"] == 0


# ---- timestamps and staleness ----------------------------------------------


def test_parse_timestamp_handles_rfc3339_forms_and_refuses_the_rest():
    assert cve.parse_timestamp("2026-07-19T00:00:00Z") == NOW
    assert cve.parse_timestamp("2026-07-19T00:00:00+00:00") == NOW
    assert cve.parse_timestamp("2026-07-19T01:00:00+01:00") == NOW
    assert cve.parse_timestamp("2026-07-19") == NOW  # a naive date is read as UTC
    for bad in ("", "   ", "yesterday", "2026-13-40", None, 17, "2026/07/19"):
        assert cve.parse_timestamp(bad) is None, bad


def test_snapshot_age_is_days_xor_error():
    fresh = cve.snapshot_age({"generated": FRESH}, NOW)
    assert fresh["age_days"] == 1.0 and fresh["error"] is None and fresh["key"] == "generated"
    old = cve.snapshot_age({"generated": OLD}, NOW)
    assert old["age_days"] > 900 and old["error"] is None
    undated = cve.snapshot_age({}, NOW)
    assert undated["age_days"] is None and "age is unknown" in undated["error"]
    garbage = cve.snapshot_age({"generated": "soon"}, NOW)
    assert garbage["age_days"] is None and "not an RFC3339 timestamp" in garbage["error"]
    assert garbage["generated"] == "soon"  # the unusable value is still reported
    # any of the accepted keys works, and the reading names which one it used
    alt = cve.snapshot_age({"snapshot_date": FRESH}, NOW)
    assert alt["key"] == "snapshot_date" and alt["age_days"] == 1.0


def test_snapshot_diagnostics_gate_stale_and_undated_but_stay_quiet_when_fresh():
    fresh = cve.snapshot_age({"generated": FRESH}, NOW)
    assert cve.snapshot_diagnostics(fresh, snapshot_path="s.json", max_age_days=30) == []
    stale = cve.snapshot_diagnostics(fresh, snapshot_path="s.json", max_age_days=0.5)
    assert [d["rule"] for d in stale] == ["cve:snapshot-stale"]
    assert stale[0]["severity"] == "error" and "1.0 days old" in stale[0]["message"]
    undated = cve.snapshot_diagnostics(
        cve.snapshot_age({}, NOW), snapshot_path="s.json", max_age_days=30
    )
    assert [d["rule"] for d in undated] == ["cve:snapshot-undated"]
    # max_age_days=None disables the staleness bound but NOT the undated warning
    assert cve.snapshot_diagnostics(fresh, snapshot_path="s.json", max_age_days=None) == []
    assert cve.snapshot_diagnostics(
        cve.snapshot_age({}, NOW), snapshot_path="s.json", max_age_days=None
    )


# ---- OSV range intervals ----------------------------------------------------


def test_range_intervals_pairs_introduced_with_its_boundary():
    intervals, problems = cve.range_intervals(
        _rng(("introduced", "2.3.0"), ("fixed", "2.31.0")), cve.ECO_PYPI
    )
    assert problems == []
    assert [(i["introduced_raw"], i["end_raw"], i["inclusive"]) for i in intervals] == [
        ("2.3.0", "2.31.0", False)
    ]


def test_range_intervals_sorts_events_it_was_given_out_of_order():
    shuffled = _rng(
        ("fixed", "3.0"), ("introduced", "2.0"), ("fixed", "1.5"), ("introduced", "1.0")
    )
    intervals, problems = cve.range_intervals(shuffled, cve.ECO_PYPI)
    assert problems == []
    assert [(i["introduced_raw"], i["end_raw"]) for i in intervals] == [
        ("1.0", "1.5"),
        ("2.0", "3.0"),
    ]


def test_introduced_zero_is_the_beginning_of_time():
    intervals, problems = cve.range_intervals(
        _rng(("introduced", "0"), ("fixed", "4.17.21"), kind="SEMVER"), cve.ECO_NPM
    )
    assert problems == [] and intervals[0]["introduced"] == cve._MIN_KEY
    # "0" is not valid semver, so only the introduced special case makes this work
    assert cve.parse_semver("0") is None


def test_an_unclosed_introduced_is_an_unbounded_affected_range():
    intervals, problems = cve.range_intervals(_rng(("introduced", "1.0")), cve.ECO_PYPI)
    assert problems == [] and len(intervals) == 1
    assert intervals[0]["end"] is None and intervals[0]["end_raw"] is None


def test_introduced_equals_fixed_is_empty_and_last_affected_is_inclusive():
    """The tie-break at a shared version, which decides one real release."""
    empty = {"ranges": [_rng(("introduced", "1.2"), ("fixed", "1.2"))]}
    assert cve.evaluate_block(empty, "1.2", cve.ECO_PYPI)["value"] is False
    inclusive = {"ranges": [_rng(("introduced", "1.2"), ("last_affected", "1.2"))]}
    reading = cve.evaluate_block(inclusive, "1.2", cve.ECO_PYPI)
    assert reading["value"] is True and "through 1.2" in reading["evidence"]
    # and the version AFTER a last_affected bound is clean
    assert cve.evaluate_block(inclusive, "1.3", cve.ECO_PYPI)["value"] is False


def test_the_tie_break_holds_when_a_boundary_is_declared_before_its_introduced():
    """OSV events are UNORDERED, so `fixed` may be listed first.

    Found by mutation testing: with the event rank flattened, a stable sort keeps
    the declared order, the leading `fixed` closes an interval from the beginning
    of time (falsely condemning every earlier release) and the trailing
    `introduced` is left open (falsely condemning every later one) — turning the
    empty range `[1.2, 1.2)` into two unbounded ones.
    """
    reversed_events = {"ranges": [_rng(("fixed", "1.2"), ("introduced", "1.2"))]}
    for version in ("1.1", "1.2", "1.3"):
        assert cve.evaluate_block(reversed_events, version, cve.ECO_PYPI)["value"] is False
    forward = {"ranges": [_rng(("introduced", "1.2"), ("fixed", "1.2"))]}
    for version in ("1.1", "1.2", "1.3"):
        assert (
            cve.evaluate_block(reversed_events, version, cve.ECO_PYPI)["value"]
            == cve.evaluate_block(forward, version, cve.ECO_PYPI)["value"]
        ), version
    # the rank itself is what makes the two declaration orders agree
    assert cve._EVENT_RANK["introduced"] < cve._EVENT_RANK["fixed"]
    assert cve._EVENT_RANK["introduced"] < cve._EVENT_RANK["last_affected"]

def test_range_intervals_reports_every_boundary_it_could_not_order():
    intervals, problems = cve.range_intervals(
        _rng(("introduced", "1.0"), ("fixed", "next")), cve.ECO_PYPI
    )
    assert len(problems) == 1 and "not a valid PEP 440 version" in problems[0]
    assert [i["end_raw"] for i in intervals] == [None]  # the fixed event is NOT there
    unsupported, issues = cve.range_intervals(
        {"events": [{"limit": "*"}, {"introduced": "1.0"}]}, cve.ECO_PYPI
    )
    assert any("limit" in p for p in issues) and len(unsupported) == 1
    malformed, issues = cve.range_intervals({"events": [{}, "nope"]}, cve.ECO_PYPI)
    assert malformed == [] and len(issues) == 2


def test_a_dropped_boundary_never_becomes_an_affected_verdict():
    """Regression: an unreadable `fixed` must not leave an unbounded interval.

    Dropping the event and walking on turns every later release into a false
    positive, which is the exact fabrication this module promises not to make.
    """
    broken = {"ranges": [_rng(("introduced", "1.0"), ("fixed", "next"))]}
    for version in ("1.5", "99.0", "1.0"):
        reading = cve.evaluate_block(broken, version, cve.ECO_PYPI)
        assert reading["value"] is None, version
        assert "no verdict is possible" in reading["error"]
    # a clean sibling range still decides, because its own events are complete
    mixed = {
        "ranges": [
            _rng(("introduced", "1.0"), ("fixed", "bogus")),
            _rng(("introduced", "5.0"), ("fixed", "5.5")),
        ]
    }
    assert cve.evaluate_block(mixed, "5.2", cve.ECO_PYPI)["value"] is True
    assert cve.evaluate_block(mixed, "9.0", cve.ECO_PYPI)["value"] is None


def test_evaluate_block_uses_an_explicit_versions_list():
    listed = {"versions": ["1.0", "2.0.0"]}
    hit = cve.evaluate_block(listed, "1.0", cve.ECO_PYPI)
    assert hit["value"] is True and "affected.versions" in hit["evidence"]
    # the match is by parsed KEY, so 2.0 and 2.0.0 are the same release
    assert cve.evaluate_block(listed, "2.0", cve.ECO_PYPI)["value"] is True
    miss = cve.evaluate_block(listed, "3.0", cve.ECO_PYPI)
    assert miss["value"] is False and "not among the 2 listed" in miss["evidence"]


def test_evaluate_block_refuses_range_types_it_cannot_order():
    git_only = {"ranges": [{"type": "GIT", "events": [{"introduced": "abc123"}]}]}
    reading = cve.evaluate_block(git_only, "1.0", cve.ECO_PYPI)
    assert reading["value"] is None and "GIT" in reading["error"]
    assert cve.canonical_range_type({"type": "GIT"}, cve.ECO_PYPI) is False
    assert cve.canonical_range_type({"type": "SEMVER"}, cve.ECO_NPM) is True
    assert cve.canonical_range_type({}, cve.ECO_PYPI) is True  # untyped means ECOSYSTEM


def test_evaluate_block_refuses_an_entry_with_nothing_to_match_on():
    reading = cve.evaluate_block({"package": {"name": "x"}}, "1.0", cve.ECO_PYPI)
    assert reading["value"] is None
    assert "neither ranges nor versions" in reading["error"]


def test_evaluate_block_refuses_an_unorderable_installed_version():
    reading = cve.evaluate_block({"versions": ["1.0"]}, "not-a-version", cve.ECO_PYPI)
    assert reading["value"] is None and "not a valid PEP 440 version" in reading["error"]


# ---- advisory-level evaluation ----------------------------------------------


def test_evaluate_advisory_reports_the_fix_and_the_evidence():
    hit = cve.evaluate_advisory(
        REQUESTS_ADVISORY, name="requests", version="2.30.0", ecosystem=cve.ECO_PYPI
    )
    assert hit["affected"] is True and hit["error"] is None
    assert hit["fixed"] == "2.31.0" and "introduced 2.3.0" in hit["evidence"]
    assert hit["aliases"] == ["CVE-2023-32681"] and hit["id"] == "GHSA-requests-1"
    clean = cve.evaluate_advisory(
        REQUESTS_ADVISORY, name="requests", version="2.31.0", ecosystem=cve.ECO_PYPI
    )
    assert clean["affected"] is False and clean["error"] is None
    below = cve.evaluate_advisory(
        REQUESTS_ADVISORY, name="requests", version="2.2.0", ecosystem=cve.ECO_PYPI
    )
    assert below["affected"] is False  # older than the introduced boundary


def test_a_withdrawn_advisory_gives_no_verdict_at_all():
    """Regression: a retracted record must not report affected true."""
    withdrawn = _osv("WD-1", "PyPI", "requests", _rng(("introduced", "0")), withdrawn=OLD)
    verdict = cve.evaluate_advisory(
        withdrawn, name="requests", version="2.30.0", ecosystem=cve.ECO_PYPI
    )
    assert verdict["affected"] is None  # NOT True, even though the range matches
    assert "WITHDRAWN" in verdict["error"] and OLD in verdict["error"]
    # the same record without the withdrawal DOES match, proving the range would hit
    live = dict(withdrawn)
    live.pop("withdrawn")
    assert (
        cve.evaluate_advisory(
            live, name="requests", version="2.30.0", ecosystem=cve.ECO_PYPI
        )["affected"]
        is True
    )


def test_evaluate_advisory_refuses_a_record_that_is_about_another_package():
    verdict = cve.evaluate_advisory(
        LODASH_ADVISORY, name="requests", version="2.30.0", ecosystem=cve.ECO_PYPI
    )
    assert verdict["affected"] is None and "no affected entry" in verdict["error"]


def test_a_definite_hit_outranks_an_undecidable_sibling_entry():
    record = {
        "id": "MULTI-1",
        "affected": [
            {"package": {"ecosystem": "PyPI", "name": "requests"}},  # undecidable
            {
                "package": {"ecosystem": "PyPI", "name": "requests"},
                "ranges": [_rng(("introduced", "1.0"), ("fixed", "2.0"))],
            },
        ],
    }
    hit = cve.evaluate_advisory(record, name="requests", version="1.5", ecosystem=cve.ECO_PYPI)
    assert hit["affected"] is True
    # but with no hit, the undecidable entry blocks a "clean" verdict
    unknown = cve.evaluate_advisory(
        record, name="requests", version="9.0", ecosystem=cve.ECO_PYPI
    )
    assert unknown["affected"] is None and unknown["error"]


def test_every_advisory_evaluation_is_affected_xor_error():
    cases = [
        REQUESTS_ADVISORY,
        LODASH_ADVISORY,
        _osv("A", "PyPI", "requests", _rng(("introduced", "0"))),
        _osv("B", "PyPI", "requests", _rng(("introduced", "1.0"), ("fixed", "nope"))),
        _osv("C", "PyPI", "requests", {"type": "GIT", "events": [{"introduced": "abc"}]}),
        _osv("D", "PyPI", "requests"),
        _osv("E", "PyPI", "requests", withdrawn=OLD),
        {
            "id": "F",
            "affected": [
                {"package": {"ecosystem": "PyPI", "name": "requests"},
                 "versions": ["2.30.0"]}
            ],
        },
        {"id": "G"},
        {"id": "H", "affected": []},
    ]
    for record in cases:
        for version in ("2.30.0", "9.9.9"):
            verdict = cve.evaluate_advisory(
                record, name="requests", version=version, ecosystem=cve.ECO_PYPI
            )
            assert (verdict["affected"] is None) != (verdict["error"] is None), (record, version)
            if verdict["affected"] is None:
                assert verdict["error"].strip(), record
            else:
                assert verdict["evidence"].strip(), record


def test_advisories_for_looks_up_by_the_normalized_key():
    snap = _snap([REQUESTS_ADVISORY])
    dep = cve.dependency(
        name="ReQuests", ecosystem=cve.ECO_PYPI, specifier="==2.30.0",
        version="2.30.0", pin_reason=None, field="f",
    )
    assert [r["id"] for r in cve.advisories_for(snap, dep)] == ["GHSA-requests-1"]
    other = cve.dependency(
        name="requests", ecosystem=cve.ECO_NPM, specifier="2.30.0",
        version="2.30.0", pin_reason=None, field="f",
    )
    assert cve.advisories_for(snap, other) == []  # right name, wrong ecosystem


# ---- rules ------------------------------------------------------------------

CLEAN_REQUIREMENTS = "requests==2.31.0\n"


def test_a_clean_manifest_produces_no_findings():
    """The guard that makes every other rule test meaningful."""
    report = _report(CLEAN_REQUIREMENTS, "requirements.txt")
    assert report["diagnostics"] == [], report["diagnostics"]
    assert report["counts"]["checked"] == 1  # it really did evaluate something
    assert report["counts"]["with_records"] == 1  # against a real advisory
    assert report["counts"]["vulnerable"] == 0 and report["counts"]["unevaluable"] == 0
    assert report["unreadable"] is None


def test_every_rule_fires_on_its_own_minimal_case():
    unpinned = _snap([REQUESTS_ADVISORY])
    broken = _snap([_osv("BR-1", "PyPI", "requests", _rng(("introduced", "1.0"), ("fixed", "x")))])
    dropped = _snap([_osv("WD-1", "PyPI", "requests", _rng(("introduced", "0")), withdrawn=OLD)])
    cases = {
        "cve:vulnerable": ("requests==2.30.0\n", "requirements.txt", SNAPSHOT),
        "cve:version-unpinned": ("requests>=2.0\n", "requirements.txt", unpinned),
        "cve:version-unparseable": ("requests==not-a-version\n", "requirements.txt", unpinned),
        "cve:advisory-unevaluable": ("requests==1.5\n", "requirements.txt", broken),
        "cve:advisory-withdrawn": ("requests==2.30.0\n", "requirements.txt", dropped),
        "cve:unresolved-include": ("-r other.txt\n", "requirements.txt", SNAPSHOT),
        "cve:ecosystem-unsupported": ("-e .\n", "requirements.txt", SNAPSHOT),
        "cve:manifest-unparseable": ("{", "package.json", SNAPSHOT),
    }
    for rule, (text, name, snap) in cases.items():
        assert rule in _rules_fired(text, name, snapshot=snap), f"{rule} did not fire on {text!r}"


def test_rules_that_must_stay_quiet():
    quiet = {
        "cve:vulnerable": "requests==2.31.0\n",  # the fixed release
        "cve:version-unpinned": "requests==2.31.0\n",
        "cve:version-unparseable": "requests==2.31.0\n",
        "cve:advisory-unevaluable": "requests==2.31.0\n",
        "cve:advisory-withdrawn": "requests==2.31.0\n",
        "cve:unresolved-include": "requests==2.31.0\n",
        "cve:package-not-in-snapshot": "totally-unknown-pkg==1.0\n",  # default OFF
    }
    for rule, text in quiet.items():
        assert rule not in _rules_fired(text, "requirements.txt"), f"{rule} false-positived"


def test_package_not_in_snapshot_is_opt_in_and_says_absence_is_not_safety():
    text = "totally-unknown-pkg==1.0\n"
    assert "cve:package-not-in-snapshot" not in _rules_fired(text, "requirements.txt")
    enabled = cve.load_rules()
    enabled["cve:package-not-in-snapshot"]["enabled"] = True
    diags = _report(text, "requirements.txt", rules=enabled)["diagnostics"]
    assert [d["rule"] for d in diags] == ["cve:package-not-in-snapshot"]
    assert "not the same as the package being safe" in diags[0]["message"]
    assert diags[0]["severity"] == "info"


def test_findings_carry_the_family_schema_and_a_real_position():
    diag = next(
        d
        for d in _report("# c\nrequests==2.30.0\n", "requirements.txt")["diagnostics"]
        if d["rule"] == "cve:vulnerable"
    )
    assert set(diag) == {
        "path", "line", "col", "rule", "severity", "message", "suggestion", "source"
    }
    assert diag["path"] == "requirements.txt" and diag["line"] == 2
    assert diag["severity"] in openswap.SEVERITIES
    assert "GHSA-requests-1" in diag["message"] and "CVSS 5.9 (medium)" in diag["message"]
    assert diag["suggestion"] == "upgrade to 2.31.0 or later"


def test_a_vulnerable_finding_with_no_fix_says_so_instead_of_inventing_one():
    unfixed = _snap([_osv("NF-1", "PyPI", "requests", _rng(("introduced", "0")))])
    diag = _report("requests==2.30.0\n", "requirements.txt", snapshot=unfixed)["diagnostics"][0]
    assert diag["rule"] == "cve:vulnerable"
    assert "no fixed version is declared" in diag["suggestion"]
    assert "unbounded" in diag["message"]


def test_severity_comes_from_the_advisory_cvss_band_when_one_exists():
    # requests -> CVSS 5.9 medium -> warning; lodash -> declared HIGH -> error
    py = _report("requests==2.30.0\n", "requirements.txt")["diagnostics"][0]
    assert py["severity"] == "warning"
    npm = _report(
        '{"dependencies": {"lodash": "4.17.20"}}', "package.json"
    )["diagnostics"][0]
    assert npm["severity"] == "error"
    # no rating at all falls back to the rule table default, and says which band
    silent = _snap([_osv("S-1", "PyPI", "requests", _rng(("introduced", "0")))])
    fallback = _report("requests==2.30.0\n", "requirements.txt", snapshot=silent)
    assert fallback["diagnostics"][0]["severity"] == cve.RULES["cve:vulnerable"]["severity"]
    assert "no severity declared" in fallback["diagnostics"][0]["message"]


def test_map_rating_off_pins_the_severity_to_policy():
    rules = cve.load_rules()
    rules["cve:vulnerable"].update({"map_rating": False, "severity": "suggestion"})
    diag = _report("requests==2.30.0\n", "requirements.txt", rules=rules)["diagnostics"][0]
    assert diag["severity"] == "suggestion"  # NOT the medium->warning mapping
    assert cve.RATING_SEVERITY["critical"] == "error"
    assert cve.RATING_SEVERITY["low"] == "suggestion"


def test_emitter_severity_reason_names_where_the_severity_came_from():
    emitter = cve._Emitter(cve.load_rules(), "p")
    mapped, why = emitter.severity_for("cve:vulnerable", "critical")
    assert mapped == "error" and "CVSS band critical" in why
    low, why_low = emitter.severity_for("cve:vulnerable", "low")
    assert low == "suggestion" and "CVSS band low" in why_low
    default, why_default = emitter.severity_for("cve:vulnerable", None)
    assert default == "error" and "from the rule table" in why_default
    off = cve.load_rules()
    off["cve:vulnerable"]["map_rating"] = False
    pinned, why_pinned = cve._Emitter(off, "p").severity_for("cve:vulnerable", "low")
    assert pinned == "error" and "map_rating off" in why_pinned


def test_rules_overlay_can_disable_and_change_severity(tmp_path):
    overlay = tmp_path / "org.json"
    overlay.write_text(
        json.dumps(
            {
                "cve:version-unpinned": {"severity": "error"},
                "cve:unresolved-include": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    rules = cve.load_rules(overlay)
    diags = _report("flask>=2.0\n-r more.txt\n", "requirements.txt", rules=rules)["diagnostics"]
    by_rule = {d["rule"]: d["severity"] for d in diags}
    assert by_rule["cve:version-unpinned"] == "error"  # escalated by policy
    assert "cve:unresolved-include" not in by_rule  # disabled by policy
    assert cve.load_rules()["cve:version-unpinned"]["severity"] == "warning"  # defaults intact


def test_load_rules_rejects_typos_and_bad_severity(tmp_path):
    bad_id = tmp_path / "a.json"
    bad_id.write_text('{"cve:vulnerabel": {"enabled": false}}', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown rule id"):
        cve.load_rules(bad_id)
    bad_sev = tmp_path / "b.json"
    bad_sev.write_text('{"cve:vulnerable": {"severity": "catastrophic"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="severity"):
        cve.load_rules(bad_sev)
    not_object = tmp_path / "c.json"
    not_object.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        cve.load_rules(not_object)
    not_settings = tmp_path / "d.json"
    not_settings.write_text('{"cve:vulnerable": "error"}', encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        cve.load_rules(not_settings)
    assert all(cfg["severity"] in openswap.SEVERITIES for cfg in cve.RULES.values())


# ---- reports ----------------------------------------------------------------


def test_audit_counts_bucket_every_advisory_row_exactly_once():
    snap = _snap(
        [
            REQUESTS_ADVISORY,
            _osv("BR-1", "PyPI", "requests", _rng(("introduced", "0"), ("fixed", "x"))),
            _osv("WD-1", "PyPI", "requests", _rng(("introduced", "0")), withdrawn=OLD),
            _osv("CL-1", "PyPI", "requests", _rng(("introduced", "0"), ("fixed", "0.1"))),
        ]
    )
    report = _report("requests==2.30.0\n", "requirements.txt", snapshot=snap)
    counts = report["counts"]
    rows = report["dependencies"][0]["advisories"]
    assert len(rows) == 4
    assert counts["vulnerable"] == 1 and counts["unevaluable"] == 1
    assert counts["withdrawn"] == 1
    clean = len(rows) - counts["vulnerable"] - counts["unevaluable"] - counts["withdrawn"]
    assert clean == 1  # every row landed in exactly one bucket


def test_audit_counts_split_the_reasons_a_dependency_was_not_checked():
    body = "requests==2.30.0\nflask>=2.0\nbroken==not-a-version\n-e .\n"
    counts = _report(body, "requirements.txt")["counts"]
    assert counts["dependencies"] == 3  # the editable line is a note, not a dependency
    assert counts["checked"] == 1 and counts["unpinned"] == 1 and counts["unparseable"] == 1
    assert counts["unsupported"] == 0
    assert counts["checked"] + counts["unpinned"] + counts["unparseable"] == 3


def test_diagnostics_are_sorted_by_position():
    body = "requests==2.30.0\nflask>=2.0\n-r more.txt\n"
    lines = [d["line"] for d in _report(body, "requirements.txt")["diagnostics"]]
    assert lines == sorted(lines) and len(lines) == 3


def test_unreadable_report_has_no_counts_and_one_error():
    report = cve.unreadable_report("requirements.txt", "OSError: nope")
    assert report["counts"] is None  # zero dependencies would be a fabricated count
    assert report["unreadable"] == "OSError: nope"
    assert [d["rule"] for d in report["diagnostics"]] == ["cve:manifest-unreadable"]
    assert report["diagnostics"][0]["severity"] == "error"
    assert report["kind"] == "requirements.txt"  # the name still tells us what it was


def test_unparseable_manifest_report_has_no_counts_either():
    report = _report("{", "package.json")
    assert report["counts"] is None and report["unreadable"]
    assert [d["rule"] for d in report["diagnostics"]] == ["cve:manifest-unparseable"]


def test_aggregate_separates_unread_manifests_from_clean_ones():
    good = _report("requests==2.30.0\n", "a/requirements.txt")
    bad = cve.unreadable_report("b/requirements.txt", "OSError: nope")
    agg = cve.aggregate([good, bad, good])
    assert agg["manifests"] == 3
    assert agg["manifests_audited"] == 2 and agg["manifests_unreadable"] == 1
    assert agg["totals"]["vulnerable"] == 2  # summed over the audited files only
    assert agg["totals"]["dependencies"] == 2
    assert cve.aggregate([])["totals"]["vulnerable"] == 0
    assert cve.aggregate([])["manifests"] == 0


# ---- capability, manifest, egress guard -------------------------------------


def test_detection_fallback_is_the_expected_steady_state(monkeypatch):
    from bigbang.plugins.cve import cli as cve_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = cve_cli._capability()
    assert cap["adapter"] == "cve" and cap["tier"] == openswap.TIER_FALLBACK
    assert cap["native"]["binary"] == "osv-scanner" and cap["native"]["found"] is False
    assert cap["extras"]["pip-audit"]["found"] is False  # fetches at scan time
    assert cap["extras"]["safety"]["found"] is False
    assert cap["native_used"] is False  # true on EVERY tier, by contract
    assert "NEVER" in cap["native_never_executed"]
    assert "complete product" in cap["fallback_scope"]
    assert "CACHED FILE" in cap["scope_limits"]


def test_a_present_native_binary_still_never_produces_a_finding(monkeypatch):
    """tier=native must never imply a binary was executed."""
    from bigbang.plugins.cve import cli as cve_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda b: f"/fake/{b}")
    monkeypatch.setattr(
        openswap.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("blocked"))
    )
    cap = cve_cli._capability()
    assert cap["tier"] == openswap.TIER_NATIVE and cap["native"]["found"] is True
    assert cap["native_used"] is False


def test_manifest_is_zero_egress_and_read_only():
    import yaml

    mf = yaml.safe_load(
        (ROOT / "bigbang" / "plugins" / "cve" / "manifest.yaml").read_text(encoding="utf-8")
    )
    caps = mf["capabilities"]
    assert mf["name"] == "cve"
    assert caps["network"]["enabled"] is False and caps["network"]["domains"] == []
    assert caps["filesystem"]["write"] is False and caps["filesystem"]["paths"] == []
    assert caps["secrets"]["allow"] == []


def test_egress_guard_refuses_a_widened_manifest(monkeypatch):
    import typer

    from bigbang.plugins.cve import cli as cve_cli

    assert cve_cli._egress_guard("test")["network_enabled"] is False
    assert cve_cli._egress_guard("test")["snapshot_fetched"] is False
    for widened in (
        {"capabilities": {"network": {"enabled": True, "domains": []}}},
        {"capabilities": {"network": {"enabled": False, "domains": ["osv.dev"]}}},
    ):
        monkeypatch.setattr(cve_cli, "_MANIFEST", widened)
        with pytest.raises(typer.Exit):
            cve_cli._egress_guard("test")


def test_read_text_reports_why_instead_of_raising(tmp_path):
    from bigbang.plugins.cve import cli as cve_cli

    good = tmp_path / "requirements.txt"
    good.write_text("requests==2.30.0\n", encoding="utf-8")
    text, error = cve_cli._read_text(good)
    assert text.startswith("requests==") and error is None
    text, error = cve_cli._read_text(tmp_path)  # a directory is not readable text
    # the contract is "ExceptionName: message", not a substring lottery — the
    # disjunct ("Error" in error or "error" in error) that reads naturally here
    # has an unreachable second branch, since every OSError subclass name ends
    # in "Error" and the first branch already matched it
    assert text == ""
    assert error and error.split(":")[0].endswith("Error"), error


def test_snapshot_path_prefers_the_flag_then_the_env(monkeypatch):
    from bigbang.plugins.cve import cli as cve_cli

    monkeypatch.delenv(cve_cli.SNAPSHOT_ENV, raising=False)
    assert cve_cli._snapshot_path(None) == Path(cve_cli.SNAPSHOT_REL)
    monkeypatch.setenv(cve_cli.SNAPSHOT_ENV, "from-env.json")
    assert cve_cli._snapshot_path(None) == Path("from-env.json")
    assert cve_cli._snapshot_path("from-flag.json") == Path("from-flag.json")
    # no HOME assumption anywhere in the default
    assert not Path(cve_cli.SNAPSHOT_REL).is_absolute()


def test_the_directory_walk_skips_installed_trees(tmp_path):
    from bigbang.plugins.cve import cli as cve_cli

    (tmp_path / "requirements.txt").write_text("a==1.0\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("not a manifest\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "package.json").write_text("{}", encoding="utf-8")
    for junk in ("node_modules", ".venv", "__pycache__"):
        (tmp_path / junk).mkdir()
        (tmp_path / junk / "package.json").write_text("{}", encoding="utf-8")
    found = {p.name for p in cve_cli._collect_manifests([str(tmp_path)], "t")}
    assert found == {"requirements.txt", "package.json"}
    parents = {p.parent.name for p in cve_cli._collect_manifests([str(tmp_path)], "t")}
    assert "node_modules" not in parents and ".venv" not in parents
    assert cve_cli.SKIP_DIRS >= {"node_modules", ".venv", "site-packages"}
    # a file named explicitly is taken whatever its name, so `audit notes.md` is
    # a per-file cve:manifest-unparseable rather than a silent no-op
    named = cve_cli._collect_manifests([str(tmp_path / "notes.md")], "t")
    assert [p.name for p in named] == ["notes.md"]


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
    roots = _import_roots(ROOT / "bigbang" / "core" / "cve.py")
    allowed = set(sys.stdlib_module_names) | {"bigbang"}
    assert roots <= allowed, f"non-stdlib imports: {sorted(roots - allowed)}"
    assert "tomllib" in roots  # the TOML path really is stdlib, not a dependency


def test_plugin_cli_adds_no_dependency_beyond_typer():
    roots = _import_roots(ROOT / "bigbang" / "plugins" / "cve" / "cli.py")
    allowed = set(sys.stdlib_module_names) | {"bigbang", "typer"}
    assert roots <= allowed, f"new dependency: {sorted(roots - allowed)}"


def test_core_opens_no_socket_and_no_url_on_any_path():
    """The architectural claim, asserted against the source rather than promised."""
    source = (ROOT / "bigbang" / "core" / "cve.py").read_text(encoding="utf-8")
    for forbidden in ("import socket", "urllib.request", "http.client", "httpx",
                      "requests.get", "urlopen"):
        assert forbidden not in source, forbidden
    cli_source = (ROOT / "bigbang" / "plugins" / "cve" / "cli.py").read_text(encoding="utf-8")
    for forbidden in ("import socket", "urllib.request", "http.client", "httpx", "urlopen"):
        assert forbidden not in cli_source, forbidden


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


def _write_snapshot(tmp_path: Path, records=None, generated: str | None = None) -> Path:
    payload: dict = {"advisories": records if records is not None else
                     [REQUESTS_ADVISORY, LODASH_ADVISORY]}
    if generated is not None:
        payload["generated"] = generated
    path = tmp_path / "osv.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cli_cve_hello_envelope():
    r = _cli(["cve", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True and data["data"]["ready"] is True
    assert data["data"]["plugin"] == "cve"
    assert data["example"].startswith("scout ") and "cve audit" in data["example"]


def test_cli_cve_detect_reports_fallback_and_zero_egress():
    r = _cli(["cve", "detect"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["native_used"] is False
    assert data["egress"]["network_enabled"] is False
    assert data["egress"]["domains"] == []
    assert data["egress"]["snapshot_fetched"] is False
    assert data["snapshot_env"] == "SCOUT_CVE_SNAPSHOT"
    assert "CACHED FILE" in data["scope_limits"]


def test_cli_cve_audit_without_a_snapshot_fails_instead_of_reporting_clean(tmp_path):
    """The failure mode this plugin exists to prevent."""
    req = tmp_path / "requirements.txt"
    req.write_text("requests==2.30.0\n", encoding="utf-8")
    r = _cli(["cve", "audit", str(req), "--snapshot", str(tmp_path / "missing.json")])
    assert r.returncode == 1, r.stdout
    payload = json.loads(r.stdout)
    assert "ok" not in payload  # never a success envelope
    assert "no OSV snapshot at" in payload["error"]
    assert "not the same answer" in payload["error"]
    assert payload["example"].startswith("scout ") and "cve" in payload["example"]
    assert "cve snapshot" in payload["discover"]


def test_cli_cve_audit_rejects_an_unusable_snapshot(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("requests==2.30.0\n", encoding="utf-8")
    for body, needle in (("not json", "JSONDecodeError"), ('{"foo": 1}', "SnapshotError")):
        snap = tmp_path / "bad.json"
        snap.write_text(body, encoding="utf-8")
        r = _cli(["cve", "audit", str(req), "--snapshot", str(snap)])
        assert r.returncode == 1, body
        assert needle in json.loads(r.stdout)["error"], body


def test_cli_cve_audit_finds_real_defects_and_gates(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "requests==2.30.0\nflask>=2.0\n", encoding="utf-8"
    )
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"lodash": "4.17.20"}}', encoding="utf-8"
    )
    snap = _write_snapshot(tmp_path, generated=FRESH)
    r = _cli(["cve", "audit", str(tmp_path), "--snapshot", str(snap),
              "--max-age-days", "36500", "--fail-on", "error"])
    assert r.returncode == 1, r.stdout  # the lodash HIGH finding is an error
    data = json.loads(r.stdout)["data"]
    fired = {d["rule"] for d in data["diagnostics"]}
    assert {"cve:vulnerable", "cve:version-unpinned"} <= fired
    assert data["aggregate"]["manifests_audited"] == 2
    assert data["aggregate"]["totals"]["vulnerable"] == 2
    assert data["snapshot"]["fetched"] is False and data["native_used"] is False
    assert data["snapshot"]["age"]["age_days"] is not None
    assert "dependencies" not in data["manifests"][0]  # rows are opt-in
    # NOT `>= 0`: a perf_counter delta can never be negative, so that assertion
    # could not fail. What can regress is the field's type.
    assert isinstance(data["elapsed_ms"], (int, float))


def test_cli_cve_audit_clean_tree_exits_zero(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    snap = _write_snapshot(tmp_path, generated=FRESH)
    r = _cli(["cve", "audit", str(tmp_path / "requirements.txt"), "--snapshot", str(snap),
              "--max-age-days", "36500", "--fail-on", "info", "--deps"])
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)["data"]
    assert data["diagnostics"] == [] and data["summary"]["total"] == 0
    rows = data["manifests"][0]["dependencies"]
    assert [row["name"] for row in rows] == ["requests"]
    assert rows[0]["advisories"][0]["affected"] is False  # really evaluated, not skipped


def test_cli_cve_audit_gates_on_a_stale_snapshot_even_with_a_clean_tree(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    snap = _write_snapshot(tmp_path, generated=OLD)
    r = _cli(["cve", "audit", str(tmp_path / "requirements.txt"), "--snapshot", str(snap),
              "--max-age-days", "30", "--fail-on", "error"])
    assert r.returncode == 1, r.stdout
    data = json.loads(r.stdout)["data"]
    assert [d["rule"] for d in data["diagnostics"]] == ["cve:snapshot-stale"]
    assert data["aggregate"]["totals"]["vulnerable"] == 0  # the tree itself IS clean
    assert data["snapshot"]["age"]["age_days"] > 30


def test_cli_cve_audit_undated_snapshot_is_a_warning_not_a_pass(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    snap = _write_snapshot(tmp_path, generated=None)
    r = _cli(["cve", "audit", str(tmp_path / "requirements.txt"), "--snapshot", str(snap),
              "--fail-on", "warning"])
    assert r.returncode == 1, r.stdout
    data = json.loads(r.stdout)["data"]
    assert [d["rule"] for d in data["diagnostics"]] == ["cve:snapshot-undated"]
    assert data["snapshot"]["age"]["age_days"] is None
    assert data["snapshot"]["age"]["error"]


def test_cli_cve_audit_missing_path_and_empty_directory_fail_actionably(tmp_path):
    snap = _write_snapshot(tmp_path, generated=FRESH)
    gone = _cli(["cve", "audit", str(tmp_path / "nope.txt"), "--snapshot", str(snap)])
    assert gone.returncode == 1
    assert "path not found" in json.loads(gone.stdout)["error"]
    (tmp_path / "empty").mkdir()
    empty = _cli(["cve", "audit", str(tmp_path / "empty"), "--snapshot", str(snap)])
    assert empty.returncode == 1
    assert "no dependency manifests found" in json.loads(empty.stdout)["error"]
    bad_gate = _cli(["cve", "audit", str(tmp_path), "--snapshot", str(snap),
                     "--fail-on", "catastrophe"])
    assert bad_gate.returncode == 1
    assert "--fail-on must be one of" in json.loads(bad_gate.stdout)["error"]


def test_cli_cve_snapshot_reports_the_cache_it_read(tmp_path):
    snap = _write_snapshot(tmp_path, generated=FRESH)
    r = _cli(["cve", "snapshot", "--snapshot", str(snap), "--max-age-days", "36500"])
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)["data"]
    assert data["counts"]["records"] == 2 and data["counts"]["packages"] == 2
    # sorted() on the "eco:name" keys: uppercase P sorts before lowercase n
    assert data["packages_sample"] == ["PyPI:requests", "npm:lodash"]
    assert data["fetched"] is False and data["diagnostics"] == []
    assert data["meta"]["generated"] == FRESH


def test_cli_cve_match_one_package_and_gates(tmp_path):
    snap = _write_snapshot(tmp_path, generated=FRESH)
    hit = _cli(["cve", "match", "--package", "ReQuests", "--version", "2.30.0",
                "--snapshot", str(snap), "--fail-on", "warning"])
    assert hit.returncode == 1, hit.stdout
    data = json.loads(hit.stdout)["data"]
    advisory = data["dependency"]["advisories"][0]
    assert advisory["id"] == "GHSA-requests-1" and advisory["affected"] is True
    assert advisory["severity"]["score"]["value"] == 5.9
    clean = _cli(["cve", "match", "--package", "requests", "--version", "2.31.0",
                  "--snapshot", str(snap), "--fail-on", "warning"])
    assert clean.returncode == 0, clean.stdout
    assert json.loads(clean.stdout)["data"]["dependency"]["advisories"][0]["affected"] is False
    npm = _cli(["cve", "match", "--package", "lodash", "--version", "4.17.20",
                "--ecosystem", "npm", "--snapshot", str(snap)])
    assert npm.returncode == 0
    assert json.loads(npm.stdout)["data"]["dependency"]["advisories"][0]["affected"] is True
    bad = _cli(["cve", "match", "--package", "x", "--version", "1", "--ecosystem", "Maven",
                "--snapshot", str(snap)])
    assert bad.returncode == 1
    assert "--ecosystem must be one of" in json.loads(bad.stdout)["error"]


def test_cli_cve_rules_publishes_the_table():
    r = _cli(["cve", "rules"])
    assert r.returncode == 0
    data = json.loads(r.stdout)["data"]
    assert set(data["rules"]) == set(cve.RULES)
    assert data["rules"]["cve:vulnerable"]["map_rating"] is True
    assert data["rules"]["cve:package-not-in-snapshot"]["enabled"] is False
    assert data["overlay"] is None and data["severities"] == list(openswap.SEVERITIES)
    assert data["ecosystems"] == {"PyPI": "PEP 440", "npm": "SemVer 2.0.0"}
    assert "requirements*.txt" in data["manifests"] and "uv.lock" in data["manifests"]


def test_cli_cve_rules_rejects_a_bad_overlay(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"cve:not-a-rule": {}}', encoding="utf-8")
    r = _cli(["cve", "rules", "--rules", str(bad)])
    assert r.returncode == 1
    assert "bad rules overlay" in json.loads(r.stdout)["error"]
