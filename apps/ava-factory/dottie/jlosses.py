"""Combined training objective: LM loss + the Multi-J-Space auxiliary losses.

Weights come from configs/*.yaml (`jspace:`), which mirror dolma_config.yaml:

    loss = lm
         + (report*1.0 + broadcast*0.5 + selectivity*0.3 + modulation*0.5) * j_weight
         + sum_space  half_life_loss(space)      * hl_weight[space]
         + inter_mi(cos(S1,S2), 0.45)            * 0.3
         + routing_KL(route_probs | task_type)   * 0.4

j_weight is 0.08 for phases 0-2 and 0.15 for 3-5.

Reuses MultiJSpaceLosses from multi_jspace_module.py rather than reimplementing
its formulas.
"""

from __future__ import annotations

import dataclasses
from typing import Mapping

import torch
import torch.nn.functional as F

from dottie.config import SPACES, DottieConfig
from multi_jspace_module import MultiJSpaceLosses


@dataclasses.dataclass
class LossBreakdown:
    total: torch.Tensor
    lm: torch.Tensor
    report: torch.Tensor
    broadcast: torch.Tensor
    selectivity: torch.Tensor
    modulation: torch.Tensor
    half_life: torch.Tensor
    inter_mi: torch.Tensor
    routing: torch.Tensor

    def as_floats(self) -> dict[str, float]:
        return {f.name: float(getattr(self, f.name)) for f in dataclasses.fields(self)}


class JSpaceObjective(torch.nn.Module):
    def __init__(self, cfg: DottieConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.j = cfg.jspace
        self.losses = MultiJSpaceLosses()

    # -- pieces --------------------------------------------------------------

    def _lm_loss(self, logits: torch.Tensor, input_ids: torch.Tensor) -> torch.Tensor:
        # next-token prediction; float() so bf16 autocast doesn't degrade the CE
        return F.cross_entropy(
            logits[:, :-1].reshape(-1, logits.shape[-1]).float(),
            input_ids[:, 1:].reshape(-1),
        )

    def _report_loss(self, model, jm: Mapping, concept_ids: torch.Tensor | None) -> torch.Tensor:
        """CE(verbalizer(S2 workspace mean) -> concept token), over TAGGED docs only.

        Only synthetic docs carry a concept; HF records arrive as
        UNTAGGED_CONCEPT (-1). Those rows are dropped rather than mapped onto a
        real token -- HF dominates the corpus, so a placeholder target would
        teach the workspace to report that placeholder.
        """
        device = jm["route_probs"].device
        if concept_ids is None:
            return torch.zeros((), device=device)

        tagged = concept_ids >= 0
        if not bool(tagged.any()):
            return torch.zeros((), device=device)

        ws = jm["workspaces"]["system2"][tagged]
        jlens = model.multi_jspace.system2.jlens
        return self.losses.reportability_loss(ws, concept_ids[tagged], jlens)

    def _broadcast_loss(self, jm: Mapping) -> torch.Tensor:
        # per-space broadcast strength toward its configured target
        terms = [
            self.losses.broadcast_loss(jm[s]["broadcast_strength"], self.j.broadcast_target[s])
            for s in SPACES
        ]
        return torch.stack(terms).mean()

    def _selectivity_loss(self, jm: Mapping, task_type: str) -> torch.Tensor:
        """automatic -> low workspace variance (habitual), deliberate -> high.

        Normalized by the workspace's own scale. Raw variance is meaningless as a
        target: at init the workspace activations are ~1e-3, so var ~1e-6 and the
        term rounds to zero regardless of what the slots are doing. The model
        could also trivially minimize it by shrinking every activation.
        """
        s = "system1" if task_type == "automatic" else "system2"
        ws = jm["workspaces"][s]
        scale = ws.pow(2).mean() + 1e-8
        ws_var = ws.var(dim=1).mean() / scale
        return self.losses.selectivity_loss(ws_var, task_type)

    def _modulation_loss(self, out: Mapping, jm: Mapping) -> torch.Tensor:
        """Hinge: the broadcast must actually modulate the residual stream.

        sim_with    = cos(fused + broadcast, broadcast)
        sim_without = cos(fused,             broadcast)

        A workspace that broadcasts a vector the stream already points at, or a
        vanishingly small one, gets no credit.

        (Written first as `cos(bc, bc.detach())` vs `cos(0, bc)`. cos(x, x) is
        identically 1, so the hinge was `relu(0.5 - 1.0) == 0` for every input --
        a loss term that could never fire. Exactly the defect class this project
        exists to remove.)
        """
        bc = jm["broadcast"]
        fused = out["fused"]
        sim_with = F.cosine_similarity(fused + bc, bc, dim=-1).mean()
        sim_without = F.cosine_similarity(fused, bc, dim=-1).mean()
        return self.losses.modulation_loss(sim_with, sim_without)

    def _half_life_loss(self, model) -> torch.Tensor:
        mj = model.multi_jspace
        terms = [
            self.losses.half_life_loss(getattr(mj, s), self.j.half_life[s]) * self.j.hl_weight[s]
            for s in SPACES
        ]
        return torch.stack(terms).sum()

    def _inter_mi(self, jm: Mapping) -> torch.Tensor:
        return self.losses.inter_space_mi_regularizer(
            jm["workspaces"]["system1"], jm["workspaces"]["system2"], self.j.inter_mi_cos_target
        )

    def _routing(self, jm: Mapping, task_type: str) -> torch.Tensor:
        return self.losses.routing_loss(jm["route_probs"], task_type)

    # -- entry point ---------------------------------------------------------

    def forward(self, model, out: Mapping, input_ids: torch.Tensor, *, phase: int,
                task_type: str, concept_ids: torch.Tensor | None = None) -> LossBreakdown:
        jm = out["jspace"]
        w = self.j.base_loss_weights
        jw = self.j.j_weight_for_phase(phase)

        lm = self._lm_loss(out["lm_logits"], input_ids)
        report = self._report_loss(model, jm, concept_ids)
        broadcast = self._broadcast_loss(jm)
        selectivity = self._selectivity_loss(jm, task_type)
        modulation = self._modulation_loss(out, jm)
        half_life = self._half_life_loss(model)
        inter_mi = self._inter_mi(jm)
        routing = self._routing(jm, task_type)

        aux = (report * w["report"] + broadcast * w["broadcast"]
               + selectivity * w["selectivity"] + modulation * w["modulation"])

        total = (lm + aux * jw
                 + half_life
                 + inter_mi * self.j.inter_mi_weight
                 + routing * self.j.routing_weight)

        return LossBreakdown(total=total, lm=lm, report=report, broadcast=broadcast,
                             selectivity=selectivity, modulation=modulation,
                             half_life=half_life, inter_mi=inter_mi, routing=routing)
