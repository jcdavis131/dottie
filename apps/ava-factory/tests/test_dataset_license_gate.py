"""License gate for dataset discovery — deny by default.

Every case in TestAdmittedByTheOldSubstringGate was ADMITTED by the gate this
replaces, measured 2026-07-25. That gate was
`any(lp in lic_lower for lp in [..., "cc-by"])`, and "cc-by" is a substring of
"cc-by-nc-4.0", "cc-by-nd-4.0" and "cc-by-nc-nd-4.0". Two standing rules were
being broken silently: NoDerivatives is ALWAYS excluded because training a model
on a work is a derivative use, and NonCommercial is excluded by default because
this project has a revenue mission.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

# dataset_discovery.py is a script, not an importable package module.
_SPEC = importlib.util.spec_from_file_location(
    "dataset_discovery",
    Path(__file__).resolve().parents[1] / "scripts" / "dataset_discovery.py",
)
dataset_discovery = importlib.util.module_from_spec(_SPEC)
sys.modules["dataset_discovery"] = dataset_discovery
_SPEC.loader.exec_module(dataset_discovery)

gate_license = dataset_discovery.gate_license


class TestAdmittedByTheOldSubstringGate:
    """Regression. Each of these passed the substring gate."""

    @pytest.mark.parametrize(
        "ident",
        [
            "cc-by-nd-4.0",
            "cc-by-nc-nd-4.0",
            "cc-by-nd-3.0",
            "CC-BY-ND-4.0",  # case must not matter
        ],
    )
    def test_nd_is_always_denied(self, ident):
        ok, reason = gate_license(ident)
        assert not ok, f"{ident} admitted — ND must never train"
        assert "NoDerivatives" in reason

    @pytest.mark.parametrize(
        "ident", ["cc-by-nc-4.0", "cc-by-nc-sa-4.0", "cc-by-nc-2.0"]
    )
    def test_nc_is_denied_by_default(self, ident):
        ok, reason = gate_license(ident)
        assert not ok, f"{ident} admitted — NC conflicts with the revenue mission"
        assert "NonCommercial" in reason

    def test_multi_license_record_denies_if_any_value_denies(self):
        """The OAPEN lesson: reading only the first value admitted a work that
        was CC-BY *and* ND. Order must not matter."""
        for raw in (
            ["cc-by-4.0", "cc-by-nd-4.0"],
            ["cc-by-nd-4.0", "cc-by-4.0"],
            ["mit", "apache-2.0", "cc-by-nc-4.0"],
        ):
            ok, reason = gate_license(raw)
            assert not ok, f"{raw} admitted — the most restrictive term governs"
            assert "NoDerivatives" in reason or "NonCommercial" in reason

    def test_stringified_list_is_not_how_we_gate(self):
        """meta["license"] is str()'d for display. Gating that string is how the
        pair used to pass, so a str that merely CONTAINS a permissive id must
        still be denied."""
        ok, _ = gate_license("['cc-by-4.0', 'cc-by-nd-4.0']")
        assert not ok


class TestPermissiveStillPasses:
    """The gate has to stay useful, not just strict."""

    @pytest.mark.parametrize(
        "ident",
        [
            "mit",
            "apache-2.0",
            "cc0-1.0",
            "cc-by-4.0",
            "cc-by-sa-4.0",
            "bsd-3-clause",
            "odc-by",
            "MIT",
            "  apache-2.0  ",  # HF fields carry stray whitespace
        ],
    )
    def test_allowed(self, ident):
        ok, reason = gate_license(ident)
        assert ok, f"{ident} denied: {reason}"

    def test_multi_license_all_permissive_passes(self):
        ok, reason = gate_license(["mit", "apache-2.0"])
        assert ok, reason
        assert "mit" in reason and "apache-2.0" in reason


class TestUnverifiedIsNotPermissive:
    @pytest.mark.parametrize(
        "raw", [None, "", "   ", "unknown", "other", "proprietary", [], "assumed permissive"]
    )
    def test_denied(self, raw):
        ok, reason = gate_license(raw)
        assert not ok, f"{raw!r} admitted — unverified is not permissive"
        assert reason


class TestTokenBoundaries:
    """Component matching, not substring — the whole point of the fix."""

    def test_nd_token_does_not_match_inside_a_word(self):
        # a hypothetical id containing the letters "nd" must not be denied for it
        dataset_discovery.LICENSE_ALLOW.add("mozilla-android-1.0")
        try:
            ok, reason = gate_license("mozilla-android-1.0")
            assert ok, f"denied for containing the letters nd: {reason}"
        finally:
            dataset_discovery.LICENSE_ALLOW.discard("mozilla-android-1.0")

    def test_permissive_family_prefix_does_not_admit_its_restricted_members(self):
        # "cc-by" must never act as a wildcard over the cc-by-* family
        assert gate_license("cc-by-4.0")[0]
        assert not gate_license("cc-by-nd-4.0")[0]
        assert not gate_license("cc-by-nc-4.0")[0]

    def test_a_bare_family_prefix_is_not_itself_allowed(self):
        ok, _ = gate_license("cc-by")
        assert not ok, "unversioned 'cc-by' is ambiguous — require a versioned id"


class TestDryRunManufacturesNoVerdict:
    """--dry-run makes no API call, so it has no evidence. It used to set
    license_ok=True for math/code/reasoning with license "assumed permissive" —
    exactly the "code corpora are permissive" inference the gate exists to
    refuse."""

    @pytest.mark.parametrize("domain", ["math", "code", "reasoning", "logic", "finance"])
    def test_dry_run_never_clears_a_candidate(self, domain):
        cands = dataset_discovery.search_hf_datasets_free(
            domain, ["some-dataset"], ["mit"], dry_run=True
        )
        assert cands, "dry run produced no candidates at all"
        for c in cands:
            assert c["license_ok"] is False, (
                f"{domain}: dry run cleared {c.get('dataset_id')} without checking"
            )
            assert "not checked" in c.get("license_reason", "")


class TestDownloadManifestNeverListsAnUngatedDataset:
    """The manifest is the path that actually fetches training data, so it is
    where the gate matters most — and it is where the gate was weakest.

    The skip was guarded by `not cand.get("license_ok") and not args.dry_run`,
    so in dry-run mode the skip never fired and every top-12 candidate was
    listed regardless of license. --dry-run is exactly what
    docs/crons/dataset-discovery-daily.md prescribes for the daily cron.
    """

    def _manifest_lines(self, candidates, dry_run):
        """Reproduce the manifest loop over supplied candidates."""
        lines = []
        ranked = sorted(candidates, key=lambda x: x["relevance_score"], reverse=True)
        for cand in ranked[:12]:
            if not cand.get("license_ok", False):
                lines.append(f"# SKIP {cand['name']}")
                continue
            lines.append(f"echo \"Downloading {cand['name']}\"")
        return lines

    def _cand(self, name, license_ok, score=0.9):
        return {
            "name": name,
            "license": "cc-by-nd-4.0",
            "license_ok": license_ok,
            "relevance_score": score,
            "license_reason": "test",
        }

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_ungated_candidate_is_skipped_in_both_modes(self, dry_run):
        lines = self._manifest_lines([self._cand("evil/nd-corpus", False)], dry_run)
        assert any("# SKIP evil/nd-corpus" in ln for ln in lines)
        assert not any("Downloading evil/nd-corpus" in ln for ln in lines), (
            "an ungated dataset reached the download manifest"
        )

    def test_gated_candidate_is_listed(self):
        lines = self._manifest_lines([self._cand("good/mit-corpus", True)], False)
        assert any("Downloading good/mit-corpus" in ln for ln in lines)

    def test_real_script_has_no_dry_run_escape_in_the_skip(self):
        """Pins the source, not a reimplementation — the bug WAS the extra
        conjunct, so a copy of the loop in this test cannot catch its return."""
        src = (
            Path(__file__).resolve().parents[1] / "scripts" / "dataset_discovery.py"
        ).read_text(encoding="utf-8")
        assert 'if not cand.get("license_ok", False):' in src, (
            "the manifest skip must depend on license_ok ALONE"
        )
        assert 'license_ok", False) and not args.dry_run' not in src, (
            "the dry-run escape is back — ungated datasets would reach the manifest"
        )


class TestDenyTokensAreDeclaredNotHardcoded:
    def test_nd_and_nc_are_both_declared(self):
        assert set(dataset_discovery.LICENSE_DENY_TOKENS) >= {"nd", "nc"}

    def test_allowlist_contains_no_denied_token(self):
        """Guards against someone adding e.g. cc-by-nc-4.0 to LICENSE_ALLOW: the
        deny check runs first, so the entry would be dead AND misleading."""
        offenders = [
            ident
            for ident in dataset_discovery.LICENSE_ALLOW
            if set(ident.split("-")) & set(dataset_discovery.LICENSE_DENY_TOKENS)
        ]
        assert offenders == [], f"allowlist entries that can never pass: {offenders}"
