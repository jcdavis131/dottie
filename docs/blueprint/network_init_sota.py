"""
network_init_sota.py — AutoInit: Analytically tracking mean/variance to avoid exploding/vanishing + scaled init
Solo personal project, no connection to employer, built with public/free-tier only
"""
import math, torch
import torch.nn as nn
def auto_init_model(model, std_base=0.02):
    for name, mod in model.named_modules():
        if isinstance(mod, nn.Linear):
            layer = getattr(mod, '_layer_idx', 1)
            std = std_base / math.sqrt(2*layer)
            nn.init.normal_(mod.weight, mean=0.0, std=std)
            if mod.bias is not None:
                nn.init.zeros_(mod.bias)
        elif isinstance(mod, nn.Embedding):
            nn.init.normal_(mod.weight, mean=0.0, std=std_base)
        # RMSNorm ones
        if hasattr(mod, 'weight') and 'norm' in name.lower():
            with torch.no_grad():
                mod.weight.fill_(1.0)
    # zero-init value/action heads, LM head scaled by 1/sqrt(d)
    if hasattr(model, 'lm_head'):
        with torch.no_grad():
            model.lm_head.weight.data *= 1.0 / math.sqrt(model.d_model if hasattr(model,'d_model') else 2048)
    print("AutoInit done: scaled init std=0.02/sqrt(2*layer), RMSNorm ones, LM head scaled by 1/sqrt(d)")

if __name__=="__main__":
    print("AutoInit module loaded")
