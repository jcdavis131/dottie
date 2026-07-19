"""
GRPO with adaptive entropy, outer clip, reward decomposition – MAI Sec 3
Solo personal project, no connection to employer, built with public/free-tier only

Implements:
- Token-level policy gradient J = E 1/|y| sum_t min(r_t A, clip(r,1-eps,1+eps)A)
- response-level advantage A_i = (R_i - mean)/std shared across tokens
- Importance ratio r = pi_theta/pi_old Eq6
- Adaptive entropy control Eq7-8 target H*0.3 k_max2.5 delta0.25 eps0.6 init k0 sym log-ratio
- Outer ratio clip Eq9 r_out = clip(r, r_min=0, r_max=50)
- Reward decomposition Eq10-12 R = R_task + 0.5*R_lang -0.25*R_len
- Problem sampling early exit G_early=16 G=128 pass rate filter [0.05,0.8] early full [0.1,0.8]
- Length curriculum 8k->128k powers of two
- Top-p 0.97 mask replay (placeholder)

Scaled for Dottie 1B: batch 128-256, G 32 (16 early), LR 1e-6->9e-7
"""
from __future__ import annotations
import math, random
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
import torch
import torch.nn.functional as F

@dataclass
class GRPOConfig:
    eps_clip: float = 0.6  # epsilon for inner clip
    r_min: float = 0.0
    r_max: float = 50.0
    target_entropy: float = 0.3
    k_max: float = 2.5
    delta: float = 0.25
    entropy_eps: float = 0.6
    w_lang: float = 0.5
    alpha_non_english: float = 0.005
    w_len: float = 0.25
    g_early: int = 16
    g_full: int = 128
    pass_rate_low_early: float = 0.05
    pass_rate_high_early: float = 0.8
    pass_rate_low_full: float = 0.1
    pass_rate_high_full: float = 0.8
    top_p: float = 0.97
    max_gen_tokens: int = 8192  # start 8k, curriculum ->128k
    lr: float = 1e-6

class AdaptiveEntropyController:
    """Eq7-8 symmetric log-ratio controller"""
    def __init__(self, cfg: GRPOConfig, k_init: float = 1.0):
        self.cfg = cfg
        self.k = k_init  # entropy coefficient

    def update(self, current_entropy: float) -> float:
        # error = target - current
        err = self.cfg.target_entropy - current_entropy
        # symmetric log-ratio: delta * sign * log(1+|err|/eps)
        sign = 1 if err > 0 else -1
        adjustment = self.cfg.delta * sign * math.log1p(abs(err)/self.cfg.entropy_eps)
        self.k = max(0.0, min(self.cfg.k_max, self.k + adjustment))
        return self.k

def compute_importance_ratio(logprob_new: torch.Tensor, logprob_old: torch.Tensor) -> torch.Tensor:
    return torch.exp(logprob_new - logprob_old)

def outer_clip(r: torch.Tensor, r_min: float, r_max: float) -> torch.Tensor:
    return torch.clamp(r, min=r_min, max=r_max)

def grpo_loss(
    logprob_new: torch.Tensor,  # [B, L]
    logprob_old: torch.Tensor,  # [B, L]
    advantages: torch.Tensor,   # [B] or [B,1]
    mask: torch.Tensor,         # [B, L] 1 for valid tokens
    cfg: GRPOConfig,
) -> Tuple[torch.Tensor, Dict[str,float]]:
    """
    Token-level GRPO with global batch normalization: every token contributes equally regardless response length.
    advantages: response-level (B) shared across tokens after broadcast
    """
    if advantages.dim()==1:
        advantages = advantages.unsqueeze(1)  # [B,1]
    r = compute_importance_ratio(logprob_new, logprob_old)  # [B,L]
    r_clipped_outer = outer_clip(r, cfg.r_min, cfg.r_max)
    # inner clip like PPO
    r_inner_clipped = torch.clamp(r_clipped_outer, 1-cfg.eps_clip, 1+cfg.eps_clip)
    # token advantage: broadcast
    adv = advantages.expand_as(r_clipped_outer)
    # unclipped and clipped objectives
    obj1 = r_clipped_outer * adv
    obj2 = r_inner_clipped * adv
    token_obj = torch.min(obj1, obj2)  # [B,L]
    # normalize over all tokens in global batch
    total_tokens = mask.sum().clamp(min=1)
    loss = - (token_obj * mask).sum() / total_tokens
    # stats
    with torch.no_grad():
        entropy = -(logprob_new * mask).sum()/total_tokens  # approximate
        clip_frac = ((r < 1-cfg.eps_clip) | (r > 1+cfg.eps_clip)).float().mean().item()
        r_max_observed = r.max().item()
    return loss, {"entropy": float(entropy), "clip_frac": clip_frac, "r_max": r_max_observed, "total_tokens": float(total_tokens)}

def reward_lang(text: str, alpha: float = 0.005) -> float:
    """Eq11 max(1 - alpha * n_non_english, 0) — simple heuristic non-ASCII count"""
    try:
        non_en = sum(1 for c in text if ord(c)>127)
        return max(1.0 - alpha*non_en, 0.0)
    except:
        return 1.0

def reward_len(pass_rate: float, response_len: int, l_max: int, w_len: float = 0.25) -> float:
    """Eq12 rho_q*|y|/l_max, rho_q = pass rate difficulty proxy"""
    # higher pass_rate => easier => stronger length penalty
    rho_q = pass_rate
    penalty = rho_q * response_len / max(1,l_max)
    return w_len * penalty

def reward_decomposition(r_task: float, text: str, pass_rate: float, response_len: int, l_max: int, cfg: GRPOConfig) -> Tuple[float, Dict]:
    r_lang = reward_lang(text, cfg.alpha_non_english)
    r_len = reward_len(pass_rate, response_len, l_max, cfg.w_len)
    total = r_task + cfg.w_lang * r_lang - r_len  # Eq10, note minus on len per spec v2 (R = R_task + w_lang R_lang - w_len R_len)
    return total, {"r_task":r_task,"r_lang":r_lang,"r_len":r_len,"total":total}

def problem_sampling_filter(pass_rates: List[float], cfg: GRPOConfig, stage: str="early") -> List[int]:
    """Return indices within acceptable range"""
    if stage=="early":
        low, high = cfg.pass_rate_low_early, cfg.pass_rate_high_early
    else:
        low, high = cfg.pass_rate_low_full, cfg.pass_rate_high_full
    keep=[]
    for i,pr in enumerate(pass_rates):
        if low <= pr <= high:
            keep.append(i)
    return keep

def length_curriculum_stage(step: int) -> int:
    """8k ->16k->32k->64k->128k powers of two"""
    stages=[8192,16384,32768,65536,131072]
    # advance every e.g. 200 steps for demo
    idx = min(step//200, len(stages)-1)
    return stages[idx]

# ------------------ Ollama judge hook (qwen3:32b) ------------------
def ollama_judge(prompt: str, response: str, model: str="qwen3:32b") -> float:
    """Placeholder judge – in prod call Ollama API, here heuristic"""
    # Simple heuristic: if response contains final answer marker and length reasonable, task reward 1
    # Real implementation would POST to http://localhost:11434/api/generate
    if "final answer" in response.lower() or "therefore" in response.lower():
        return 1.0
    return 0.2

# ------------------ Unit tests ------------------
def _test_grpo():
    cfg=GRPOConfig()
    B, L = 4, 16
    logp_new=torch.randn(B,L, requires_grad=True)
    logp_old=logp_new.detach()+torch.randn(B,L)*0.01
    mask=torch.ones(B,L)
    rewards=torch.tensor([1.0,0.0,0.5,0.8])
    adv = (rewards - rewards.mean())/(rewards.std()+1e-6)
    loss, stats = grpo_loss(logp_new, logp_old, adv, mask, cfg)
    assert loss.requires_grad
    print(f"grpo loss {loss.item():.4f} stats {stats}")

    ctrl=AdaptiveEntropyController(cfg)
    k1=ctrl.update(current_entropy=0.5)
    k2=ctrl.update(current_entropy=0.2)
    assert 0 <= k2 <= cfg.k_max
    print(f"entropy controller k {k1:.3f}->{k2:.3f} PASS")

    # outer clip
    r=torch.tensor([0.1, 60.0, 2.0])
    rc=outer_clip(r,0,50)
    assert rc.max().item()<=50.0

    # reward decomp
    total,d=reward_decomposition(1.0,"hello world α",0.8,100,8192,cfg)
    print(f"reward decomp {d} total {total:.3f}")

    # problem sampling
    pr=[0.01,0.2,0.5,0.9]
    keep=problem_sampling_filter(pr,cfg,"early")
    assert 0 not in keep and 3 not in keep
    print(f"problem sampling keep {keep} PASS")
    print("GRPO unit tests PASS")

if __name__=="__main__":
    _test_grpo()
