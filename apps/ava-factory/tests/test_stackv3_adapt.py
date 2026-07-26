"""stack-v3 adapter — the per-file licence gate is the point.

The dataset is published `odc-by`, but that is the licence of the COLLECTION.
Individual source files carry whatever their authors chose, which is why the
schema ships `detected_licenses` per file. Gating only on the dataset tag would
train on files whose own terms forbid it.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "stackv3_adapt",
    Path(__file__).resolve().parents[1] / "dottie" / "datagen" / "stackv3_adapt.py",
)
stackv3 = importlib.util.module_from_spec(_SPEC)
sys.modules["stackv3_adapt"] = stackv3
_SPEC.loader.exec_module(stackv3)

adapt_record = stackv3.adapt_record
keep_file = stackv3.keep_file


def _file(content="def f():\n    return 1\n" * 4, **kw):
    base = {
        "content": content,
        "file_path": "src/a.py",
        "language": "Python",
        "is_vendor": False,
        "license_type": "permissive",
        "detected_licenses": ["mit"],
        "size_bytes": len(content),
    }
    base.update(kw)
    return base


def _repo(files, repo_path="octo/widget"):
    return {"repo_path": repo_path, "repo_id": 1, "commit_id": "abc", "files": files}


class TestPerFileLicenceGate:
    def test_mit_file_is_kept(self):
        ok, _ = keep_file(_file(detected_licenses=["mit"]))
        assert ok

    @pytest.mark.parametrize(
        "licences",
        [
            ["cc-by-nd-4.0"],
            ["cc-by-nc-4.0"],
            ["cc-by-nc-nd-4.0"],
            ["mit", "cc-by-nd-4.0"],  # permissive AND restrictive -> denied
            ["gpl-3.0"],  # not on the permissive allowlist
            ["unknown"],
            ["other"],
        ],
    )
    def test_restricted_or_unverified_file_is_dropped(self, licences):
        ok, reason = keep_file(_file(detected_licenses=licences))
        assert not ok, f"{licences} kept: {reason}"

    def test_file_with_no_detected_licence_is_dropped(self):
        ok, reason = keep_file(
            _file(detected_licenses=[], license_type=None)
        )
        assert not ok
        assert "unverified" in reason

    def test_detected_licenses_takes_precedence_over_license_type(self):
        """license_type is a coarse bucket ("permissive"); detected_licenses is
        the actual finding. A file labelled permissive but detected ND is ND."""
        ok, _ = keep_file(
            _file(license_type="permissive", detected_licenses=["cc-by-nd-4.0"])
        )
        assert not ok, "coarse license_type must not override a detected ND"


class TestRepoLevelAdaptation:
    def test_only_permitted_files_reach_the_text(self):
        rec = _repo(
            [
                _file(content="A" * 80, file_path="ok.py", detected_licenses=["mit"]),
                _file(
                    content="B" * 80,
                    file_path="bad.py",
                    detected_licenses=["cc-by-nd-4.0"],
                ),
            ]
        )
        out = adapt_record(rec)
        assert out is not None
        assert "ok.py" in out["text"]
        assert "bad.py" not in out["text"], "an ND-licensed file reached training text"
        assert "B" * 80 not in out["text"]
        assert out["_stackv3_files_kept"] == 1
        assert out["_stackv3_files_dropped"] == 1

    def test_repo_with_no_permitted_files_returns_none(self):
        rec = _repo([_file(detected_licenses=["cc-by-nd-4.0"])])
        assert adapt_record(rec) is None

    def test_vendored_files_are_dropped(self):
        rec = _repo(
            [
                _file(content="V" * 80, file_path="vendor/x.py", is_vendor=True),
                _file(content="K" * 80, file_path="src/k.py"),
            ]
        )
        out = adapt_record(rec)
        assert "vendor/x.py" not in out["text"]
        assert out["_stackv3_files_kept"] == 1

    def test_tiny_and_empty_files_are_dropped(self):
        for content in ["", "   \n ", "x"]:
            ok, reason = keep_file(_file(content=content))
            assert not ok, f"{content!r} kept"
            assert "empty" in reason or "short" in reason

    def test_repo_path_and_file_paths_are_in_the_text(self):
        out = adapt_record(_repo([_file(file_path="src/a.py", content="Z" * 80)]))
        assert "# repository: octo/widget" in out["text"]
        assert "# src/a.py" in out["text"]

    def test_multiple_kept_files_are_separated(self):
        rec = _repo(
            [
                _file(content="A" * 80, file_path="a.py"),
                _file(content="B" * 80, file_path="b.py"),
            ]
        )
        out = adapt_record(rec)
        assert out["_stackv3_files_kept"] == 2
        assert "# a.py" in out["text"] and "# b.py" in out["text"]


class TestMalformedInput:
    @pytest.mark.parametrize(
        "rec", [None, {}, {"files": None}, {"files": "notalist"}, [], "x", 3]
    )
    def test_never_raises(self, rec):
        assert adapt_record(rec) is None

    def test_non_dict_file_entries_are_skipped_not_fatal(self):
        rec = _repo([None, "x", 7, _file(content="Q" * 80, file_path="good.py")])
        out = adapt_record(rec)
        assert out is not None and out["_stackv3_files_kept"] == 1


class TestGateIsImportedNotDuplicated:
    def test_uses_the_same_gate_as_dataset_discovery(self):
        """A second copy of a licence allowlist is the drifting-constant bug
        class that has already produced real bugs here. Same object, one source
        of truth."""
        spec = importlib.util.spec_from_file_location(
            "dd_check",
            Path(__file__).resolve().parents[1] / "scripts" / "dataset_discovery.py",
        )
        dd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dd)
        # identical verdicts on the cases that matter
        for value in (["mit"], ["cc-by-nd-4.0"], ["cc-by-4.0", "cc-by-nd-4.0"], []):
            assert stackv3.gate_license(value)[0] == dd.gate_license(value)[0]

    def test_no_second_allowlist_literal_in_the_adapter(self):
        src = (
            Path(__file__).resolve().parents[1] / "dottie" / "datagen" / "stackv3_adapt.py"
        ).read_text(encoding="utf-8")
        assert "LICENSE_ALLOW" not in src, "adapter must not re-declare the allowlist"
        assert "cc-by-4.0" not in src, "adapter must not hardcode licence ids"


class TestDatasetLevelLicenceIsNotEnough:
    def test_odc_by_collection_does_not_admit_an_nd_file(self):
        """The whole reason this adapter exists. `odc-by` passes the dataset
        gate; it must not carry an ND-licensed FILE into training."""
        dd_ok, _ = stackv3.gate_license(["odc-by"])
        assert dd_ok, "dataset-level odc-by should pass"
        rec = _repo([_file(content="N" * 80, detected_licenses=["cc-by-nd-4.0"])])
        assert adapt_record(rec) is None
