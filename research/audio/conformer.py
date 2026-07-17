"""
Audio Conformer encoder + vision projector — Gemma 4 E4B phone 10s encode +10-20s description
Native conformer encoder transcribes audio, tool calling fragile but phone sees/hears/calls tools locally
"""
import torch.nn as nn
class AudioConformer(nn.Module):
    def __init__(self, d_model=512):
        super().__init__()
        self.conv = nn.Conv1d(80, d_model, 3, padding=1)
        self.enc = nn.TransformerEncoder(nn.TransformerEncoderLayer(d_model, 8, batch_first=True), 4)
    def forward(self, mel):
        x = self.conv(mel.transpose(1,2)).transpose(1,2)
        return self.enc(x)
