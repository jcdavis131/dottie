"""
j_space_module.py — Explicit Global Workspace (v4 compat)
Solo personal project, no connection to employer, built with public/free-tier only

JacobianLens: verbalizer d_model->vocab maps J-space vectors to words
GlobalWorkspace: 32 slots (vs 65k LTM), competition via attention to enter workspace, self-attention, modulation_gate
"""
import math, hashlib
import torch
import torch.nn as nn
import torch.nn.functional as F

class JacobianLens(nn.Module):
    def __init__(self, d_model=2048, vocab_size=128000):
        super().__init__()
        self.verbalizer = nn.Linear(d_model, vocab_size, bias=False)  # W [V][D] approximates d(logit)/d(hidden)
        self.d_model = d_model
        self.vocab_size = vocab_size
    def top_concepts(self, hidden, k=8):
        # hidden: [B,S,D] -> logits -> topk words
        logits = self.verbalizer(hidden.mean(dim=1))  # [B,V]
        probs = F.softmax(logits, dim=-1)
        vals, idx = probs.topk(k, dim=-1)
        mass = vals.sum(dim=-1).mean()
        return idx, vals, mass
    def concept_vector(self, concept: str):
        # deterministic vector via sha256(concept) % vocab
        tok_id = int(hashlib.sha256(concept.encode()).hexdigest(),16) % self.vocab_size
        vec = self.verbalizer.weight[tok_id]  # [D]
        return F.normalize(vec, dim=0), tok_id

class GlobalWorkspace(nn.Module):
    def __init__(self, d_model=2048, slots=32, vocab_size=128000):
        super().__init__()
        self.slots = slots
        self.d_model = d_model
        self.slot_emb = nn.Parameter(torch.randn(1, slots, d_model)*0.02)
        self.attn = nn.MultiheadAttention(d_model, num_heads=8, batch_first=True)
        self.self_attn = nn.MultiheadAttention(d_model, num_heads=8, batch_first=True)
        self.modulation_gate = nn.Sequential(nn.Linear(d_model, d_model), nn.Sigmoid())
        self.broadcast_proj = nn.Linear(d_model, d_model)
        self.lens = JacobianLens(d_model, vocab_size)
        self.decay_logit = nn.Parameter(torch.zeros(1))  # learnable decay -> half-life
    @property
    def half_life(self):
        decay = torch.sigmoid(self.decay_logit).item() * 0.99 + 0.01
        hl = -math.log(2)/math.log(decay) if decay<1 else 1000
        return hl
    def forward(self, fused):
        B,L,D = fused.shape
        # competition via attention to enter workspace (spotlight)
        slots = self.slot_emb.expand(B,-1,-1)
        ws, _ = self.attn(slots, fused, fused)  # [B,slots,D]
        # self-attention among concepts (holding arithmetic→nine→seven)
        ws2, _ = self.self_attn(ws, ws, ws)
        ws = ws + ws2
        gate = self.modulation_gate(ws.mean(dim=1, keepdim=True))
        ws = ws * gate
        broadcast = self.broadcast_proj(ws.mean(dim=1, keepdim=True)).expand(-1,L,-1)
        # metrics
        _, _, v_mass = self.lens.top_concepts(ws)
        b_strength = broadcast.norm(dim=-1).mean() / (fused.norm(dim=-1).mean()+1e-6)
        return fused + broadcast*0.2, {"workspace": ws, "broadcast": broadcast, "broadcast_strength": b_strength,
                "verbalizable_mass": v_mass, "top_concepts_idx": None, "half_life": self.half_life}

class JSpaceModule(nn.Module):
    def __init__(self, d_model=2048, vocab_size=128000):
        super().__init__()
        self.ws = GlobalWorkspace(d_model, slots=32, vocab_size=vocab_size)
    def forward(self, fused, task_type="deliberate"):
        return self.ws(fused)
