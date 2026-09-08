"""Torch-free integrity and reproducibility contract tests."""

from __future__ import annotations

import ast
import builtins
import importlib.util
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

if importlib.util.find_spec("zstandard") is None:
    sys.modules["zstandard"] = SimpleNamespace()

from dottie import provenance
from dottie.license_policy import (
    LicensePolicyError,
    gate_license,
    validate_dataset_source,
)
from dottie.pipeline import collector
from dottie.pipeline.collector import SourceSpec
from dottie.pipeline.manifest import Manifest

HEX40 = "a" * 40
HEX64 = "b" * 64


def _facts() -> dict:
    return {
        "tokenizer_sha256": HEX64,
        "config": {"preset": "nano", "model": {"d_model": 64}},
        "curriculum": [{"phase": 0, "tokens": 1024}],
        "shards": [
            {
                "id": "shard-b",
                "packed_bin_sha256": "e" * 64,
                "packed_idx_sha256": "f" * 64,
                "source_kind": "hf",
                "source_license": "mit",
                "source_gated": False,
                "source_revision": "b" * 40,
                "source_entry_sha256": "c" * 64,
            },
            {
                "id": "shard-a",
                "packed_bin_sha256": "d" * 64,
                "packed_idx_sha256": "a" * 64,
                "source_kind": "hf",
                "source_license": "apache-2.0",
                "source_gated": False,
                "source_revision": "a" * 40,
                "source_entry_sha256": "b" * 64,
            },
        ],
    }


@pytest.mark.parametrize(
    ("gated", "license_id", "revision"),
    [
        (True, "mit", HEX40),
        (None, "mit", HEX40),
        (False, None, HEX40),
        (False, "unknown", HEX40),
        (False, "mit", None),
        (False, "mit", "main"),
        (False, "mit", "A" * 40),
        (False, "mit", "a" * 39),
    ],
)
def test_dataset_policy_denies_before_network(
    monkeypatch, gated, license_id, revision
):
    called = False

    def load_dataset(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network loader must not run")

    monkeypatch.setitem(
        sys.modules,
        "datasets",
        SimpleNamespace(load_dataset=load_dataset),
    )
    spec = SourceSpec(
        name="denied",
        kind="hf",
        dataset="owner/data",
        license=license_id,
        gated=gated,
        revision=revision,
    )
    with pytest.raises(LicensePolicyError):
        collector._hf_stream(spec, 0)
    assert called is False


def test_dataset_policy_denies_before_importing_network_loader(monkeypatch):
    real_import = builtins.__import__
    imported_datasets = False

    def guarded_import(name, *args, **kwargs):
        nonlocal imported_datasets
        if name == "datasets":
            imported_datasets = True
            raise AssertionError("datasets must not be imported before policy validation")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "datasets", raising=False)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    spec = SourceSpec(
        name="denied-before-import",
        kind="hf",
        dataset="owner/data",
        license="mit",
        gated=True,
        revision=HEX40,
    )
    with pytest.raises(LicensePolicyError, match="gated: false"):
        collector._hf_stream(spec, 0)
    assert imported_datasets is False


@pytest.mark.parametrize(
    "license_id",
    ["mit-license", "apache-2.0-extra", "cc-by", "odc", "openrail"],
)
def test_license_policy_requires_exact_allowlisted_identifier(license_id):
    allowed, _ = gate_license(license_id)
    assert allowed is False


@pytest.mark.parametrize("gated", [0, "", "false"])
def test_dataset_policy_requires_boolean_false(gated):
    with pytest.raises(LicensePolicyError, match="gated: false"):
        validate_dataset_source(
            gated=gated,
            license_id="mit",
            revision=HEX40,
        )


def test_dataset_policy_passes_full_revision_to_loader(monkeypatch):
    calls = []

    class Dataset:
        def __iter__(self):
            return iter(())

    def load_dataset(*args, **kwargs):
        calls.append((args, kwargs))
        return Dataset()

    monkeypatch.setitem(sys.modules, "datasets", SimpleNamespace(load_dataset=load_dataset))
    spec = SourceSpec(
        name="pinned",
        kind="hf",
        dataset="owner/data",
        config="default",
        license="apache-2.0",
        gated=False,
        revision=HEX40,
    )
    list(collector._hf_stream(spec, 0))
    assert calls[0][1]["revision"] == HEX40


def test_unpinned_hf_source_is_inactive():
    spec = SourceSpec(
        name="unpinned",
        kind="hf",
        dataset="owner/data",
        license="mit",
        gated=False,
        revision=None,
        phases=(2,),
        weight={2: 1.0},
    )
    assert collector.sources_for_phase([spec], 2) == []
    with pytest.raises(LicensePolicyError):
        validate_dataset_source(
            gated=spec.gated,
            license_id=spec.license,
            revision=spec.revision,
        )


def test_collector_persists_exact_source_revision_and_entry_hash(tmp_path):
    raw_entry = {
        "name": "pinned",
        "kind": "hf",
        "dataset": "owner/data",
        "license": "mit",
        "gated": False,
        "revision": HEX40,
    }
    spec = SourceSpec.from_dict(raw_entry)
    info = collector.ShardInfo(
        shard_id="raw-1",
        path="raw-1.zst",
        bytes=10,
        docs=1,
        sha256="d" * 64,
    )
    writer = SimpleNamespace(publish=lambda: info)
    with Manifest(tmp_path / "manifest.db") as manifest:
        collector._commit_shard(
            writer, spec, 1, manifest, 1, lambda *args, **kwargs: None
        )
        row = manifest.db.execute(
            """SELECT source_kind, source_license, source_gated,
                      source_revision, source_entry_sha256
                 FROM shards WHERE id='raw-1'"""
        ).fetchone()
    assert row["source_kind"] == "hf"
    assert row["source_license"] == "mit"
    assert row["source_gated"] == 0
    assert row["source_revision"] == HEX40
    assert row["source_entry_sha256"] == provenance.hash_facts(raw_entry)


def test_lineage_digest_is_canonical_and_tracks_sorted_shards():
    facts = _facts()
    facts["config"] = {"model": {"d_model": 64}, "preset": "nano"}
    lineage_a = provenance.create_lineage(**facts)
    facts["shards"].reverse()
    facts["config"] = {"preset": "nano", "model": {"d_model": 64}}
    lineage_b = provenance.create_lineage(**facts)
    assert lineage_a == lineage_b
    assert [row["id"] for row in lineage_a["shards"]] == ["shard-a", "shard-b"]
    assert provenance.validate_lineage(lineage_a) == lineage_a["digest"]


@pytest.mark.parametrize("field", ["config", "curriculum"])
def test_lineage_generation_refuses_unavailable_required_facts(field):
    facts = _facts()
    facts[field] = None
    with pytest.raises(provenance.IntegrityError, match=field):
        provenance.create_lineage(**facts)


def test_lineage_generation_refuses_no_observed_shards():
    facts = _facts()
    facts["shards"] = []
    with pytest.raises(provenance.IntegrityError, match="observed shard"):
        provenance.create_lineage(**facts)


def test_lineage_validation_rejects_signed_but_incomplete_facts():
    lineage = provenance.create_lineage(**_facts())
    lineage.pop("config")
    lineage["digest"] = provenance.hash_facts(
        {key: value for key, value in lineage.items() if key != "digest"}
    )
    with pytest.raises(provenance.IntegrityError, match="config"):
        provenance.validate_lineage(lineage)


def test_lineage_generation_refuses_missing_manifest_hash():
    facts = _facts()
    facts["shards"][0]["packed_bin_sha256"] = None
    with pytest.raises(provenance.IntegrityError, match="sha256"):
        provenance.create_lineage(**facts)


def test_lineage_tamper_is_detected():
    lineage = provenance.create_lineage(**_facts())
    lineage["curriculum"][0]["tokens"] += 1
    with pytest.raises(provenance.IntegrityError, match="digest"):
        provenance.validate_lineage(lineage)


def test_registry_edit_does_not_invalidate_persisted_lineage(tmp_path, monkeypatch):
    registry = tmp_path / "sources.yaml"
    registry.write_text("sources: [original]", encoding="utf-8")
    monkeypatch.setenv("AVA_SOURCES_CONFIG", str(registry))
    lineage = provenance.create_lineage(**_facts())
    registry.write_text("sources: [edited]", encoding="utf-8")
    assert provenance.validate_lineage(lineage) == lineage["digest"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_kind", "synthetic"),
        ("source_revision", "synthetic-seed:1234"),
        ("source_gated", True),
        ("source_license", None),
        ("source_license", "unknown"),
    ],
)
def test_policy_ineligible_lineage_is_diagnostic_only(field, value):
    facts = _facts()
    facts["shards"][0][field] = value
    lineage = provenance.create_lineage(**facts)
    assert lineage["claim_eligible"] is False
    with pytest.raises(provenance.IntegrityError, match="claim eligible"):
        provenance.validate_lineage(lineage)
    assert (
        provenance.validate_lineage(lineage, require_claim_eligible=False)
        == lineage["digest"]
    )


def test_synthetic_checkpoint_probe_is_rejected_by_product_validation():
    facts = _facts()
    facts["shards"][0].update(
        {
            "source_kind": "synthetic",
            "source_license": "synthetic",
            "source_revision": "synthetic-seed:1234",
        }
    )
    lineage = provenance.create_lineage(**facts)
    content = {"model": {"weight": [1, 2]}, "diagnostic": True}
    blob = {
        **content,
        **provenance.checkpoint_metadata(
            lineage, asserted_parent=None, content=content
        ),
    }
    assert blob["lineage"]["claim_eligible"] is False
    with pytest.raises(provenance.IntegrityError, match="claim eligible"):
        provenance.validate_checkpoint(blob)
    assert provenance.validate_checkpoint(
        blob, require_claim_eligible=False
    ) == blob["digest"]


def test_checkpoint_metadata_requires_lineage_digest_and_parent():
    lineage = provenance.create_lineage(**_facts())
    content = {
        "model": {"weight": [1, 2]},
        "optimizer": {"state": {"step": 10}},
        "sampler": {"rng": [1, 2]},
        "rng": {"numpy": [3, 4], "torch": b"rng", "cuda": None},
        "step": 10,
        "phase": 0,
        "tokens_done": 100,
        "preset": "nano",
    }
    metadata = provenance.checkpoint_metadata(
        lineage,
        asserted_parent={"checkpoint_digest": "f" * 64},
        content=content,
    )
    blob = {**content, **metadata}
    assert metadata["lineage"] == lineage
    assert metadata["asserted_parent"] == {"checkpoint_digest": "f" * 64}
    assert len(metadata["content_digest"]) == 64
    assert provenance.validate_checkpoint(blob) == metadata["digest"]


def test_checkpoint_asserted_parent_is_not_called_proven_predecessor():
    lineage = provenance.create_lineage(**_facts())
    content = {"model": {"weight": [1, 2]}, "step": 1}
    metadata = provenance.checkpoint_metadata(
        lineage,
        asserted_parent={"checkpoint_digest": "f" * 64},
        content=content,
    )
    assert "parent" not in metadata
    assert provenance.validate_checkpoint({**content, **metadata}) == metadata["digest"]


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("model", "weight"),
        ("optimizer", "step"),
        ("sampler", "cursor"),
        ("rng", "numpy"),
    ],
)
def test_checkpoint_resume_content_tamper_is_detected(section, key):
    lineage = provenance.create_lineage(**_facts())
    content = {
        "model": {"weight": [1, 2]},
        "optimizer": {"step": 1},
        "sampler": {"cursor": 2},
        "rng": {"numpy": [3, 4], "torch": b"rng"},
        "step": 1,
        "phase": 0,
        "tokens_done": 8,
        "preset": "nano",
    }
    blob = {
        **content,
        **provenance.checkpoint_metadata(
            lineage,
            asserted_parent=None,
            content=content,
        ),
    }
    blob[section][key] = 9
    with pytest.raises(provenance.IntegrityError, match="content digest"):
        provenance.validate_checkpoint(blob)


def test_typed_digest_rejects_unsupported_values():
    with pytest.raises(provenance.IntegrityError, match="unsupported"):
        provenance.typed_digest({"bad": object()})


def test_typed_digest_is_deterministic_and_type_sensitive():
    first = {"array": np.asarray([[1, 2]], dtype=np.int32), "value": [True, 1]}
    second = {"value": [True, 1], "array": np.asarray([[1, 2]], dtype=np.int32)}
    assert provenance.typed_digest(first) == provenance.typed_digest(second)
    assert provenance.typed_digest([1, 2]) != provenance.typed_digest((1, 2))
    assert provenance.typed_digest(True) != provenance.typed_digest(1)
    with pytest.raises(provenance.IntegrityError, match="object-dtype"):
        provenance.typed_digest(np.asarray([object()], dtype=object))


def test_typed_digest_streams_large_array_in_bounded_updates(monkeypatch):
    real_sha256 = provenance.hashlib.sha256
    update_sizes: list[int] = []

    class TrackingHash:
        def __init__(self):
            self._inner = real_sha256()

        def update(self, chunk):
            update_sizes.append(len(chunk))
            self._inner.update(chunk)

        def hexdigest(self):
            return self._inner.hexdigest()

    monkeypatch.setattr(provenance.hashlib, "sha256", TrackingHash)
    value = np.arange(2_000_000, dtype=np.uint32)
    provenance.typed_digest({"large": value})
    assert update_sizes
    assert max(update_sizes) <= provenance.HASH_CHUNK_BYTES
    assert sum(size > 100_000 for size in update_sizes) > 1


def test_production_checkpoint_loads_are_restricted():
    root = Path(__file__).resolve().parents[1]
    seen: set[str] = set()
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if "tests" in relative.parts:
            continue
        source = path.read_text(encoding="utf-8")
        if "torch.load(" not in source:
            continue
        tree = ast.parse(source, filename=str(relative))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "torch"
                and node.func.attr == "load"
            ):
                continue
            seen.add(relative.as_posix())
            weights_only = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "weights_only"),
                None,
            )
            assert isinstance(weights_only, ast.Constant), relative
            assert weights_only.value is True, relative
    assert {
        "dottie/train.py",
        "dottie/serve_engine.py",
        "dottie/grow.py",
        "dottie/network_viz.py",
        "dottie/memory/openwiki_adapter.py",
        "research/memory/openwiki_adapter.py",
        "evals/common.py",
        "evals/tool_gate.py",
        "scripts/rl_smoke_update.py",
    } <= seen


def test_growth_validates_input_before_model_build_and_signs_output():
    source = (
        Path(__file__).resolve().parents[1] / "dottie" / "grow.py"
    ).read_text(encoding="utf-8")
    assert source.index("validate_checkpoint(blob") < source.index(
        "src_model = build_model"
    )
    assert "create_lineage(" in source
    assert "checkpoint_metadata(" in source
    assert '"artifact_sha256": sha256_file(args.src)' in source
    assert '"lineage_digest": blob["lineage"]["digest"]' in source


def _load_retired_distillation(monkeypatch):
    real_import = builtins.__import__

    def reject_training_imports(name, *args, **kwargs):
        if (
            name == "torch"
            or name.startswith("torch.")
            or name == "streaming_data"
            or name.startswith("dottie.")
        ):
            raise AssertionError(f"retired entrypoint imported {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_training_imports)
    return runpy.run_path(
        Path(__file__).resolve().parents[1] / "on_policy_distill.py"
    )


def test_retired_distillation_train_loop_fails_before_artifact_access(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    namespace = _load_retired_distillation(monkeypatch)

    with pytest.raises(RuntimeError, match="dottie.config.*Manifest"):
        namespace["train_loop"](SimpleNamespace(student_ckpt="must-not-be-read.pt"))

    assert list(tmp_path.iterdir()) == []


def test_retired_distillation_main_fails_before_artifact_access(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    namespace = _load_retired_distillation(monkeypatch)

    with pytest.raises(RuntimeError, match="tokenizers CVE/assets blockers"):
        namespace["main"](["--student-ckpt", "must-not-be-read.pt"])

    assert list(tmp_path.iterdir()) == []


def test_retired_distillation_cli_exits_nonzero_without_artifacts(tmp_path):
    entrypoint = Path(__file__).resolve().parents[1] / "on_policy_distill.py"
    result = subprocess.run(
        [
            sys.executable,
            str(entrypoint),
            "--student-ckpt",
            "must-not-be-read.pt",
            "--data_root",
            "must-not-be-read",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "on-policy distillation is unavailable" in result.stderr
    assert "Manifest/StreamingShardSampler provenance pipeline" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_hot_reload_status_exposes_sanitized_rejection_fields():
    engine_source = (
        Path(__file__).resolve().parents[1] / "dottie" / "serve_engine.py"
    ).read_text(encoding="utf-8")
    server_source = (
        Path(__file__).resolve().parents[1] / "server.py"
    ).read_text(encoding="utf-8")
    assert '"rejected_target": self._rejected_target' in engine_source
    assert '"last_reload_error": self._last_reload_error' in engine_source
    assert "_sanitized_error(exc)" in engine_source
    assert '"rejected_target": st.get("rejected_target")' in server_source
    assert '"last_reload_error": st.get("last_reload_error")' in server_source


@pytest.mark.parametrize(
    "blob",
    [
        {},
        {"lineage": {}, "digest": HEX64, "parent": None},
        {"lineage": {"schema": "dottie.lineage/v1"}, "digest": HEX64, "parent": None},
    ],
)
def test_checkpoint_validation_rejects_missing_or_malformed(blob):
    with pytest.raises(provenance.IntegrityError):
        provenance.validate_checkpoint(blob)


def test_eval_report_contract_marks_integrity_error_non_claimable():
    report = provenance.integrity_report(
        status="integrity_error",
        errors=["checkpoint digest mismatch"],
    )
    assert report["claim_eligible"] is False
    assert provenance.exit_code(report) == 2
    assert provenance.exit_code({"claim_eligible": True, "measured_failures": 1}) == 1
    assert provenance.exit_code({"claim_eligible": True, "measured_failures": 0}) == 0


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (
            {
                "claim_eligible": True,
                "measured_failures": 0,
                "branches": [{"checks": {"error": "unavailable"}}],
            },
            2,
        ),
        (
            {
                "claim_eligible": True,
                "measured_failures": 0,
                "errors": ["checkpoint mismatch"],
            },
            2,
        ),
        (
            {
                "claim_eligible": True,
                "measured_failures": 0,
                "branches": [{"checks": [{"pass": False}]}],
            },
            1,
        ),
        (
            {
                "claim_eligible": True,
                "measured_failures": "not-an-integer",
            },
            2,
        ),
    ],
)
def test_exit_code_classifies_nested_results_fail_closed(report, expected):
    assert provenance.exit_code(report) == expected


def test_make_smoke_uses_existing_cpu_pilot_without_running_it():
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text(
        encoding="utf-8"
    )
    assert "python scripts/cpu_pilot_e2e.py" in makefile
    assert "scripts/smoke_e2e.sh" not in makefile
    assert "smoke-static:" in makefile
    assert "--help" in makefile
