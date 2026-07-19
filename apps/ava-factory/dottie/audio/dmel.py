"""
dottie/audio/dmel.py — Encoder-free dMel spectrogram (He Bai et al 2024)
Solo personal project, no connection to employer, built with public/free-tier only

Inkling steal: audio as dMel spectrograms encoder-free, no Whisper encoder.
Public pip only: torch, optional librosa (fallback to torch STFT)

Mapping to Dottie: audio->dMel 128 bins -> linear proj -> joint sequence with text tokens.
Gated behind multimodal_mode="inkling_encoderfree" default off.

For free-tier/offline deterministic: uses torch.stft + mel filterbank, no external download.
"""
from __future__ import annotations
import math
import torch
import torch.nn as nn

def mel_filterbank(sr=16000, n_fft=1024, n_mels=128, fmin=0, fmax=8000):
    """Mel filterbank triangular filters, offline deterministic, public pip only"""
    # From librosa formula approximation, simplified
    mel_min = 2595 * math.log10(1 + fmin / 700)
    mel_max = 2595 * math.log10(1 + fmax / 700)
    mel_points = torch.linspace(mel_min, mel_max, n_mels + 2)
    hz_points = 700 * (10**(mel_points / 2595) - 1)
    bin_points = torch.floor((n_fft + 1) * hz_points / sr).long()
    # Build triangular filters
    fb = torch.zeros(n_mels, n_fft // 2 + 1)
    for m in range(1, n_mels + 1):
        f_m_minus = bin_points[m - 1]
        f_m = bin_points[m]
        f_m_plus = bin_points[m + 1]
        if f_m_minus >= f_m or f_m >= f_m_plus:
            continue
        # left slope
        for k in range(f_m_minus, f_m):
            fb[m-1, k] = (k - f_m_minus) / (f_m - f_m_minus + 1e-6)
        for k in range(f_m, f_m_plus):
            fb[m-1, k] = (f_m_plus - k) / (f_m_plus - f_m + 1e-6)
    return fb

class DMelExtractor(nn.Module):
    """Encoder-free dMel: waveform [B, T] -> log mel [B, n_mels, frames] -> projected [B, frames, d_model]"""
    def __init__(self, d_model: int = 2048, sr: int = 16000, n_fft: int = 1024, hop_length: int = 256, n_mels: int = 128):
        super().__init__()
        self.sr = sr
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.n_mels = n_mels
        mel_fb = mel_filterbank(sr=sr, n_fft=n_fft, n_mels=n_mels)
        self.register_buffer("mel_fb", mel_fb)
        self.proj = nn.Linear(n_mels, d_model, bias=False)
        self.norm = nn.LayerNorm(d_model)
        nn.init.normal_(self.proj.weight, std=0.02)

    def forward_waveform(self, wav: torch.Tensor) -> torch.Tensor:
        """wav: [B, T] float32, returns [B, frames, d_model]"""
        B = wav.shape[0]
        # STFT
        window = torch.hann_window(self.n_fft, device=wav.device, dtype=wav.dtype)
        spec = torch.stft(wav, n_fft=self.n_fft, hop_length=self.hop_length, window=window, return_complex=True)  # B, F, frames
        mag = spec.abs()  # power? magnitude
        # Apply mel filterbank: mel_fb [n_mels, F]
        mel = torch.einsum("mf,bft->bmt", self.mel_fb.to(mag.device), mag)  # B, n_mels, frames
        log_mel = torch.log(mel.clamp_min(1e-6))
        # [B, n_mels, frames] -> [B, frames, n_mels] -> proj
        log_mel = log_mel.permute(0, 2, 1)  # B, frames, n_mels
        emb = self.proj(log_mel)
        emb = self.norm(emb)
        return emb

    def forward(self, wav=None, log_mel=None, **kwargs):
        if wav is not None:
            return self.forward_waveform(wav)
        if log_mel is not None:
            # already mel, just proj
            return self.norm(self.proj(log_mel))
        raise ValueError("Need wav or log_mel")
