"""
Compressed Convolutional Attention — Zaya1-8B style 8x KV compression
Solo personal project, no connection to employer, built with public/free-tier only

From review: squeezes Q,K,V into shared latent space and sequence mixing with convolutions → eight-fold KV-cache compression
MoE 8.4B 760M active
"""
from typing import Optional
import math, torch, torch.nn as nn, torch.nn.functional as F

class CompressedConvAttention(nn.Module):
    def __init__(self, d_model=2048, n_heads=16, head_dim=128, latent_dim=64, conv_kernel=7, compression=8):
        super().__init__()
        self.d_model=d_model; self.n_heads=n_heads; self.head_dim=head_dim; self.latent=latent_dim; self.compression=compression
        self.q_latent = nn.Linear(d_model, n_heads*latent_dim, bias=False)
        self.k_latent = nn.Linear(d_model, n_heads*latent_dim, bias=False)
        self.v_latent = nn.Linear(d_model, n_heads*latent_dim, bias=False)
        # conv for sequence mixing
        self.conv_q = nn.Conv1d(n_heads*latent_dim, n_heads*latent_dim, kernel_size=conv_kernel, padding=conv_kernel//2, groups=n_heads)
        self.conv_k = nn.Conv1d(n_heads*latent_dim, n_heads*latent_dim, kernel_size=conv_kernel, padding=conv_kernel//2, groups=n_heads)
        self.out = nn.Linear(n_heads*latent_dim, d_model, bias=False)
        # deconv back to head_dim for compat
        self.latent_to_head = nn.Linear(latent_dim, head_dim, bias=False)

    def forward(self, x, cos=None, sin=None, attn_factor=1.0):
        B,L,_=x.shape
        q = self.q_latent(x).view(B,L,self.n_heads,self.latent)
        k = self.k_latent(x).view(B,L,self.n_heads,self.latent)
        v = self.v_latent(x).view(B,L,self.n_heads,self.latent)
        # conv mixing: [B,L, H*latent] -> [B, H*latent, L]
        q_c = self.conv_q(q.reshape(B,L,-1).transpose(1,2)).transpose(1,2).view(B,L,self.n_heads,self.latent)
        k_c = self.conv_k(k.reshape(B,L,-1).transpose(1,2)).transpose(1,2).view(B,L,self.n_heads,self.latent)
        # attention in latent space — compressed KV
        q_c = q_c.transpose(1,2) # B,H,L,latent
        k_c = k_c.transpose(1,2)
        v = v.transpose(1,2)
        scores = torch.einsum('b h l d, b h m d -> b h l m', q_c, k_c) / math.sqrt(self.latent) * attn_factor
        causal = torch.ones(L,L, device=x.device).tril().bool()
        scores = scores.masked_fill(~causal.unsqueeze(0).unsqueeze(0), float('-inf'))
        attn = F.softmax(scores, dim=-1)
        out_lat = torch.einsum('b h l m, b h m d -> b h l d', attn, v)
        # back to head_dim
        out_head = self.latent_to_head(out_lat) # B,H,L,head_dim
        out = out_head.transpose(1,2).reshape(B,L,-1)
        out = self.out(out_head.reshape(B,L,-1) if False else out.reshape(B,L,-1)) if False else self.out(out_lat.reshape(B,L,-1))
        # simplified: out_lat -> d_model
        out = self.out(out_lat.reshape(B,L,-1))
        return out

class MarkovianRecursiveAggregator(nn.Module):
    """
    Test-time reasoning that combines tail end of multiple parallel traces into bounded aggregation context
    """
    def __init__(self, d_model=2048, k_traces=4, tail=256, entropy_tau=0.7):
        super().__init__()
        self.k=k_traces; self.tail=tail; self.tau=entropy_tau
        self.router = nn.Linear(d_model, k_traces)

    def forward(self, traces): # List[Tensor B,L,D]
        # aggregate tail 256 tokens
        tails = [t[:, -self.tail:] for t in traces]  # k x [B,tail,D]
        stacked = torch.stack(tails, dim=0) # k,B,tail,D
        # entropy-temp routing
        mean_tail = stacked.mean(dim=2).mean(dim=1) # k,D? Actually k,B,D -> mean B -> etc simplify
        # simple mean aggregation for now — keep-or-revert will learn
        agg = stacked.mean(dim=0) # B,tail,D
        return agg
