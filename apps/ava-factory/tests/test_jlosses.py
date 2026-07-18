"""J-Space objective tests.

The one that matters: EVERY term must be able to be nonzero, and must produce a
gradient. `modulation` originally computed `cos(bc, bc.detach())` against
`cos(0, bc)` -- and cos(x,x) is identically 1, so the hinge was `relu(0.5-1.0)`
= 0 for every input that has ever existed. A loss term that cannot fire looks
exactly like a loss term that is satisfied.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from ava.config import AvaConfig
from ava.jlosses import JSpaceObjective
from ava.model import build_model
from ava.pipeline.pack import UNTAGGED_CONCEPT

TERMS = ("lm", "report", "broadcast", "selectivity", "modulation",
         "half_life", "inter_mi", "routing")


@pytest.fixture(scope="module")
def setup():
    torch.manual_seed(0)
    cfg = AvaConfig.load("nano")
    model = build_model(cfg)
    obj = JSpaceObjective(cfg)
    return cfg, model, obj


def _run(cfg, model, obj, *, task_type="deliberate", concept=None, B=2, T=64):
    ids = torch.randint(0, cfg.model.vocab_size, (B, T))
    out = model(input_ids=ids, task_type=task_type)
    cids = concept if concept is not None else torch.randint(1, 100, (B,))
    return obj(model, out, ids, phase=0, task_type=task_type, concept_ids=cids)


def test_all_terms_finite(setup):
    parts = _run(*setup)
    for k, v in parts.as_floats().items():
        assert v == v and abs(v) != float("inf"), f"{k} is not finite: {v}"


def test_modulation_can_be_nonzero(setup):
    """The regression. A constant term is indistinguishable from a satisfied one."""
    parts = _run(*setup)
    assert parts.modulation.abs().item() > 0.0, "modulation cannot fire -- it is a constant"


def test_selectivity_is_scale_invariant(setup):
    """Raw slot variance is gameable: the model can minimize it by shrinking every
    activation instead of by making the slots agree. Normalizing by the
    workspace's own scale removes that shortcut.

    (Its magnitude is genuinely ~1e-7 at init -- the slots start nearly
    identical, so there is little inter-slot variance to measure. That is an
    observation about the model, not a defect in the term.)
    """
    cfg, model, obj = setup
    jm = {"workspaces": {"system2": torch.randn(2, 8, 16)}}
    a = obj._selectivity_loss(jm, "deliberate")
    jm_scaled = {"workspaces": {"system2": jm["workspaces"]["system2"] * 100.0}}
    b = obj._selectivity_loss(jm_scaled, "deliberate")
    torch.testing.assert_close(a, b, rtol=1e-4, atol=1e-6)
    assert a.abs().item() > 0.1, "on genuinely varied slots the term must be substantial"


def test_selectivity_sign_flips_with_task_type(setup):
    """automatic -> penalize slot variance; deliberate -> reward it."""
    cfg, model, obj = setup
    jm = {"workspaces": {"system1": torch.randn(2, 8, 16), "system2": torch.randn(2, 8, 16)}}
    assert obj._selectivity_loss(jm, "automatic").item() > 0
    assert obj._selectivity_loss(jm, "deliberate").item() < 0


def test_every_term_produces_a_gradient(setup):
    """A term with no gradient path trains nothing, whatever its value."""
    cfg, model, obj = setup
    for term in TERMS:
        model.zero_grad(set_to_none=True)
        parts = _run(cfg, model, obj)
        loss = getattr(parts, term)
        if loss.requires_grad is False:
            pytest.fail(f"{term} has no grad_fn")
        loss.backward(retain_graph=False)
        got = any(p.grad is not None and p.grad.abs().sum() > 0
                  for p in model.parameters() if p.requires_grad)
        assert got, f"{term} produced no gradient anywhere in the model"


def test_report_loss_masks_untagged_docs(setup):
    """HF docs carry no concept. Training them toward a placeholder token would
    teach the workspace to report that placeholder -- HF dominates the corpus."""
    cfg, model, obj = setup
    all_untagged = torch.full((2,), UNTAGGED_CONCEPT, dtype=torch.long)
    parts = _run(cfg, model, obj, concept=all_untagged)
    assert parts.report.item() == 0.0

    mixed = torch.tensor([UNTAGGED_CONCEPT, 42])
    assert _run(cfg, model, obj, concept=mixed).report.item() > 0.0


def test_j_weight_switches_at_phase_3(setup):
    cfg, _, _ = setup
    assert cfg.jspace.j_weight_for_phase(2) == 0.08
    assert cfg.jspace.j_weight_for_phase(3) == 0.15


def test_routing_target_depends_on_task_type(setup):
    cfg, model, obj = setup
    losses = {tt: _run(cfg, model, obj, task_type=tt).routing.item()
              for tt in ("automatic", "deliberate", "safety", "temporal")}
    assert len(set(round(v, 6) for v in losses.values())) > 1, \
        "routing loss ignores task_type"


def test_total_is_the_weighted_sum(setup):
    cfg, model, obj = setup
    p = _run(cfg, model, obj, task_type="deliberate")
    w = cfg.jspace.base_loss_weights
    jw = cfg.jspace.j_weight_for_phase(0)
    aux = (p.report * w["report"] + p.broadcast * w["broadcast"]
           + p.selectivity * w["selectivity"] + p.modulation * w["modulation"])
    expect = (p.lm + aux * jw + p.half_life
              + p.inter_mi * cfg.jspace.inter_mi_weight
              + p.routing * cfg.jspace.routing_weight)
    torch.testing.assert_close(p.total, expect, atol=1e-5, rtol=1e-5)
