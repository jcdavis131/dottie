"""
dottie/embeddings/hmlp.py — Encoder-free vision 40x40 patches via 4-layer hMLP (Touvron 2022)
Solo personal project, no connection to employer, built with public/free-tier only

Inkling steal: images as 40x40 patches via 4-layer hMLP lightweight embedding, no CLIP/ViT encoder.
Fits 04_Tennis_DINOv3 ONNX WASM 2MB distilled target.

Public pip only: torch
"""
from __future__ import annotations
import torch
import torch.nn as nn
import torch.nn.functional as F

class PatchHMLP(nn.Module):
    """
    40x40 patches -> 4-layer hMLP (Touvron: Three things everyone should know about Vision Transformers)
    Input: image [B, C, H, W] uint8/float32
    Output: [B, num_patches, d_model] patch embeddings to joint with text tokens
    """
    def __init__(self, d_model: int = 2048, patch_size: int = 40, in_channels: int = 3, hidden_mult: int = 2):
        super().__init__()
        self.patch_size = patch_size
        self.in_channels = in_channels
        patch_dim = in_channels * patch_size * patch_size
        hidden = d_model * hidden_mult
        # 4-layer hMLP
        self.net = nn.Sequential(
            nn.Linear(patch_dim, hidden, bias=False),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden, bias=False),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden, bias=False),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Linear(hidden, d_model, bias=False),
            nn.LayerNorm(d_model),
        )
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, std=0.02)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        """
        images: [B, C, H, W] float in [0,1] or uint8.
        Returns: [B, num_patches, d_model]
        Patches 40x40 non-overlap, pad if needed to multiple of patch_size.
        """
        B, C, H, W = images.shape
        if C != self.in_channels:
            # adapt if grayscale or 4ch -> take first 3 or repeat
            if C == 1 and self.in_channels == 3:
                images = images.repeat(1, 3, 1, 1)
                C = 3
            elif C == 4:
                images = images[:, :3]
                C = 3
        # Pad H,W to multiple of patch_size
        pad_h = (self.patch_size - H % self.patch_size) % self.patch_size
        pad_w = (self.patch_size - W % self.patch_size) % self.patch_size
        if pad_h or pad_w:
            images = F.pad(images, (0, pad_w, 0, pad_h), mode='constant', value=0)
        _, _, Hp, Wp = images.shape
        # Unfold patches: [B, C*patch*patch, num_patches]
        patches = F.unfold(images, kernel_size=self.patch_size, stride=self.patch_size)  # B, C*Ps*Ps, L
        patches = patches.transpose(1, 2)  # B, L, C*Ps*Ps
        # Normalize per patch (mean std) optional
        emb = self.net(patches)  # B, L, d_model
        return emb

    def forward_from_list(self, pil_images):
        # Placeholder for PIL list input, converts to tensor inside real serve
        import torchvision.transforms.functional as TF
        tensors = [TF.to_tensor(img) for img in pil_images]
        # stack if same size else pad handled in forward each? For stub, assume list of tensors same size
        # To keep offline deterministic without extra dep, expect caller to have batched tensor
        raise NotImplementedError("Use forward with batched tensor [B,C,H,W]")
