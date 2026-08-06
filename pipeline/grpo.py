"""dottie/pipeline/grpo.py — GRPO-lite numpy-only math, re-exports canonical dottie.rl.grpo
Solo personal project, no torch.
Implements same API as dottie/rl/grpo.py but torch-free, importable from dottie/pipeline.
"""

from __future__ import annotations
import math, random
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

_ADV_STD_EPS = 1e-8

def group_advantages(returns: Sequence[float], eps: float = _ADV_STD_EPS) -> List[float]:
    n=len(returns)
    if n==0: return []
    mean=sum(returns)/n
    var=sum((r-mean)**2 for r in returns)/n
    std=math.sqrt(var)
    return [(r-mean)/(std+eps) for r in returns]

def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

@dataclass
class EntropyThermostat:
    kappa: float
    h_target: float
    eps: float = 0.2
    k_max: float = 4.0
    k: float = 0.0
    def update(self, h_policy: float) -> float:
        self.k = _clamp(self.k + self.kappa*(self.h_target - h_policy), 0.0, self.k_max)
        return self.k
    def clip_bounds(self) -> Tuple[float,float]:
        upper=(1.0+self.eps)*(1.0+self.k)
        lower=1.0/(1.0+self.eps)
        return lower, upper

def importance_weighted_entropy(logp_new: Sequence[float], logp_old: Sequence[float]) -> float:
    if not logp_new: return 0.0
    if len(logp_new)!=len(logp_old):
        return sum(-x for x in logp_new)/max(1,len(logp_new))
    weights=[math.exp(ln-lo) for ln, lo in zip(logp_new, logp_old)]
    wsum=sum(weights)
    if wsum<=0: return 0.0
    return sum(w*(-ln) for w,ln in zip(weights, logp_new))/wsum

@dataclass(frozen=True)
class SurrogateResult:
    objective: float
    inner_clipped: bool
    outer_clipped: bool

def clipped_surrogate(ratio: float, advantage: float, *, lower: float, upper: float, r_outer: float) -> SurrogateResult:
    outer_lo, outer_hi = 1.0-r_outer, 1.0+r_outer
    r_safe=_clamp(ratio, outer_lo, outer_hi)
    outer_clipped=r_safe!=ratio
    clipped_ratio=_clamp(r_safe, lower, upper)
    unclipped_obj=r_safe*advantage
    clipped_obj=clipped_ratio*advantage
    objective=min(unclipped_obj, clipped_obj)
    inner_clipped=clipped_obj < unclipped_obj
    return SurrogateResult(objective, inner_clipped, outer_clipped)

# TraceBank minimal for pipeline use
@dataclass(frozen=True)
class BankedTrace:
    prompt: str
    tokens: Tuple[int,...]
    rl_return: float
    family_id: str
    pass_rate: float
    step: int
    verified_by: str = "exec"

@dataclass
class TraceBank:
    traces: List[BankedTrace] = field(default_factory=list)
    def append(self, trace: BankedTrace) -> None:
        self.traces.append(trace)
    def __len__(self): return len(self.traces)
    def sample_uniform(self, k: int, rng: random.Random|None=None) -> List[BankedTrace]:
        rng = rng or random.Random(7)
        if not self.traces: return []
        if k>=len(self.traces): return list(self.traces)
        return rng.sample(self.traces, k)

def simulate_entropy_control(kappa=0.5, h_target=0.3, steps=100) -> List[float]:
    """Synthetic control-systems plant proving thermostat drives H→H_target, NOT Ava training."""
    therm=EntropyThermostat(kappa=kappa, h_target=h_target)
    h=0.6
    hist=[]
    for _ in range(steps):
        k=therm.update(h)
        # toy dynamics: entropy decays toward 0.1 unless k widens
        h=0.9*h + 0.1*(h_target + 0.05*k) + (random.random()-0.5)*0.02
        hist.append(h)
    return hist
