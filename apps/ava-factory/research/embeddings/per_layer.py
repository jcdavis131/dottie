"""
Per-Layer Embeddings + MatFormer Matryoshka nesting — Gemma 4 E2B/E4B
E2B ~2B E4B ~4.5B effective params phone enough
MatFormer: smaller E2B co-trained inside larger E4B pull smaller without retraining one download multiple targets
Per-Layer Embeddings: each decoder layer its own token embeddings cheap lookup tables
Phone: Oppo Find N5 Snapdragon 8 Elite 16GB llama.cpp Termux Q8_0 4.3GB +900MB projector 6GB RAM 7-8 tok/s sub-sec TTFT
"""
import torch, torch.nn as nn
class PerLayerEmbedding(nn.Module):
    def __init__(self, vocab=128000, d_model=2048, n_layers=24):
        super().__init__()
        self.n_layers=n_layers
        self.layers = nn.ModuleList([nn.Embedding(vocab, d_model//4) for _ in range(n_layers)]) # cheap lookup
        self.proj = nn.ModuleList([nn.Linear(d_model//4, d_model) for _ in range(n_layers)])
    def forward(self, ids, layer_idx):
        e = self.layers[layer_idx](ids)
        return self.proj[layer_idx](e)

class MatFormerNest(nn.Module):
    def __init__(self, d_model=2048):
        super().__init__()
        # E2B inside E4B co-trained nesting
        self.e2b = nn.Linear(d_model, d_model//2)
        self.e4b = nn.Linear(d_model, d_model)
    def extract(self, level='e2b'):
        return self.e2b if level=='e2b' else self.e4b
