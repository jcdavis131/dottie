"""Stage 5: S-EMBER causal memory / provenance evaluation."""

from __future__ import annotations

import json

import pytest

from dottie_loop import ember, errors, evaluation, memory
from dottie_loop.cli import EXIT_ERROR, EXIT_OK, main
from dottie_loop.schema import active


def _measured(kind: str = "gate_result", value: float = 1.0) -> dict:
    return {"kind": kind, "value": value, "source": "hidden-eval"}


def _ptr(kind: str = "eval", ident: str = "rubric_1") -> dict:
    return {"kind": kind, "id": ident}


def _catalog(*ids: str) -> dict:
    out = {}
    for ident in ids:
        kind, _, rest = ident.partition(":")
        out[ident] = {"kind": kind, "id": rest, "valid": True}
    return out


def test_causal_edge_requires_evidence_and_measured():
    store = memory.MemoryStore()
    with pytest.raises(errors.InvalidInputError, match="add_causal_edge"):
        store.add_edge("a", "caused", "b", graph="history", source="x", confidence=0.9)
    with pytest.raises(errors.InvalidInputError, match="evidence"):
        store.add_causal_edge(
            "a", "caused", "b", graph="history", source="x", confidence=0.9,
            evidence_ptr={}, measured=_measured(),
        )
    with pytest.raises(errors.InvalidInputError, match="measured"):
        store.add_causal_edge(
            "a", "caused", "b", graph="history", source="x", confidence=0.9,
            evidence_ptr=_ptr(), measured={},
        )
    with pytest.raises(errors.PolicyDeniedError, match=r"0\.4"):
        store.add_causal_edge(
            "a", "caused", "b", graph="history", source="x", confidence=0.3,
            evidence_ptr=_ptr(), measured=_measured(),
        )
    with pytest.raises(errors.PolicyDeniedError, match="synthetic"):
        store.add_causal_edge(
            "a", "caused", "b", graph="history", source="synthetic", confidence=0.9,
            evidence_ptr=_ptr(), measured=_measured(),
        )


def test_provenance_preserved_and_scored():
    store = memory.MemoryStore()
    edge = store.add_causal_edge(
        "intervention",
        "caused",
        "metric",
        graph="history",
        source="hidden_eval",
        confidence=0.8,
        evidence_ptr=_ptr("eval", "hid-1"),
        measured=_measured("hidden_eval_mean", 0.91),
    )
    assert edge.evidence_ptr == {"kind": "eval", "id": "hid-1"}
    assert edge.measured["kind"] == "hidden_eval_mean"
    catalog = _catalog("eval:hid-1")
    ev = ember.evaluate_causal_memory(store, evidence_catalog=catalog)
    assert ev["schema"] == active("ember-eval")
    assert ev["gate"] == "open"
    assert ev["gated_score"] == 1.0
    assert ev["n_broken"] == 0
    assert ev["quality_from_provenance"] is False
    # retrieval still exposes evidence; causal ptr is on the edge
    assert store.causal_edges()[0].evidence_ptr["id"] == "hid-1"


def test_missing_and_broken_provenance_fail_closed():
    store = memory.MemoryStore()
    store.add_causal_edge(
        "a", "blocked", "b", graph="history", source="gate", confidence=0.9,
        evidence_ptr=_ptr("incident", "inc_1"), measured=_measured("gate_result", "fail"),
    )
    missing = ember.evaluate_causal_memory(store, evidence_catalog={})
    assert missing["gate"] == "provenance_broken"
    assert missing["gated_score"] == 0.0
    assert missing["n_broken"] == 1

    revoked = ember.evaluate_causal_memory(
        store, evidence_catalog={"incident:inc_1": {"kind": "incident", "valid": False}}
    )
    assert revoked["gate"] == "provenance_broken"
    assert revoked["gated_score"] == 0.0

    empty = ember.evaluate_causal_memory(memory.MemoryStore(), evidence_catalog={})
    assert empty["gate"] == "empty"
    assert empty["gated_score"] is None


def test_ember_refuses_synthetic_and_merges_into_eval_gates():
    with pytest.raises(errors.PolicyDeniedError, match="synthetic"):
        ember.evaluate_causal_memory(memory.MemoryStore(), evidence_catalog={}, synthetic=True)
    with pytest.raises(errors.PolicyDeniedError, match="mock"):
        ember.evaluate_from_records([], evidence_catalog={}, mock=True)

    store = memory.MemoryStore()
    store.add_causal_edge(
        "a", "confounded", "b", graph="history", source="gate", confidence=1.0,
        evidence_ptr=_ptr("trace", "trc_1"), measured=_measured("reward_component", 0.0),
    )
    broken = ember.evaluate_causal_memory(store, evidence_catalog={})
    passing = {"failed": [], "verdict": "pass", "bundle_id": "eval_x"}
    merged = evaluation.merge_ember_verdict(passing, broken)
    assert merged["verdict"] == "fail"
    assert "provenance" in merged["failed"]
    ok = ember.evaluate_causal_memory(store, evidence_catalog=_catalog("trace:trc_1"))
    still = evaluation.merge_ember_verdict(passing, ok)
    assert still["verdict"] == "pass"


def test_hint_facts_remain_non_actionable():
    store = memory.MemoryStore()
    hint = store.remember(
        "maybe", "x", evidence=["weak"], provenance="inferred", confidence=0.2
    )
    assert hint.hint and not store.actionable(hint)
    ev = ember.evaluate_causal_memory(store, evidence_catalog={})
    assert hint.fact_id in ev["hint_facts"]


def test_ember_cli(tmp_path, capsys):
    payload = {
        "edges": [
            {
                "src": "a",
                "rel": "caused",
                "dst": "b",
                "graph": "history",
                "source": "recorded",
                "confidence": 0.9,
                "evidence_ptr": _ptr("eval", "e1"),
                "measured": _measured(),
            }
        ],
        "evidence_catalog": _catalog("eval:e1"),
    }
    p = tmp_path / "ember.json"
    p.write_text(json.dumps(payload))
    rc = main(["research", "ember", "--file", str(p)])
    out = json.loads(capsys.readouterr().out)
    assert rc == EXIT_OK and out["data"]["gate"] == "open"
    p.write_text(json.dumps({**payload, "synthetic": True}))
    rc = main(["research", "ember", "--file", str(p)])
    assert rc == EXIT_ERROR
