"""
Discrete text diffusion — DiffusionGemma Gemma 4 26B/4B-active MoE
Starts from canvas 256 random tokens refines whole block in parallel bidirectional not left-to-right, whole block resolves at once like image from noise
Flappy Bird Flask 138s 123 steps 9 blocks, 1000+ tok/s H100 4x speedup vs bandwidth-bound Apple Silicon
"""
import torch, torch.nn as nn
class DiscreteDiffusionDecoder(nn.Module):
    def __init__(self, vocab=128000, d_model=2048, block=256, steps=123, blocks=9):
        super().__init__()
        self.vocab=vocab; self.block=block; self.steps=steps; self.n_blocks=blocks
        self.embed=nn.Embedding(vocab,d_model)
        self.layers=nn.TransformerEncoder(nn.TransformerEncoderLayer(d_model,8,batch_first=True), num_layers=4)
        self.head=nn.Linear(d_model,vocab)
    def forward(self, canvas=None, B=1):
        # canvas 256 random tokens
        if canvas is None:
            canvas = torch.randint(0,self.vocab,(B,self.block))
        x=self.embed(canvas)
        # refine whole block in parallel bidirectional attention so start/end influence before locked
        for _ in range(self.steps):
            x=self.layers(x)
        logits=self.head(x)
        return logits
