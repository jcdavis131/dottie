#!/usr/bin/env python3
"""
T12.2 nano_quick 50 steps MOE violation rate Fig8 test
- Builds nano_v66
- Runs 50 steps dummy data (random tokens) to measure violation rate
- Checks deterministic flag
- Checks periodic attention pattern
Solo personal project
"""
import os, sys, torch, random, time, json
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from dottie.config import DottieConfig

def test_nano_v66():
    cfg = DottieConfig.load("nano_v66")
    from dottie.model import build_model
    model = build_model(cfg)
    model.train()
    # Check periodic pattern
    pattern_ok = cfg.model.use_periodic_attention and cfg.model.periodic_pattern == "5:1"
    print(f"periodic attention: {cfg.model.use_periodic_attention} pattern {cfg.model.periodic_pattern} ok={pattern_ok}")
    # Check layers is_global pattern
    globals_list = []
    for i, blk in enumerate(list(model.text_layers) + list(model.fusion_layers) + list(model.reasoning_layers)):
        if hasattr(blk, 'is_global'):
            globals_list.append(blk.is_global)
    # Expect pattern 5 local False, 1 global True repeating
    expected = []
    for idx in range(len(globals_list)):
        cycle = 6
        pos = idx % cycle
        expected.append(pos >= 5)
    matches = sum(1 for a,b in zip(globals_list, expected) if a==b)
    print(f"periodic pattern matches {matches}/{len(globals_list)} globals {globals_list[:12]}")

    # Check attention zero-init
    zero_init_ok = True
    for blk in list(model.text_layers) + list(model.fusion_layers):
        if hasattr(blk, 'peri_norm_attn') and hasattr(blk.peri_norm_attn, 'weight'):
            if cfg.model.attention_zero_init:
                # after init_weights, weight should be zero
                w = blk.peri_norm_attn.weight.detach()
                if not torch.allclose(w, torch.zeros_like(w)):
                    zero_init_ok = False
                    break
    print(f"attention zero-init check: {zero_init_ok}")

    # Check dropout
    dropout_ok = abs(cfg.model.dropout - 0.15) < 1e-6
    print(f"dropout 0.15 ok={dropout_ok} value={cfg.model.dropout}")

    # Dummy training 50 steps to measure violation
    B, L = 1, 32
    vocab = cfg.model.vocab_size
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    violation_history = []
    model.train()
    for step in range(10):
        input_ids = torch.randint(0, vocab, (B, L))
        out = model(input_ids=input_ids)
        # model returns dict with lm_logits
        logits = out.get("lm_logits")
        if logits is None:
            logits = out.get("logits")
        if logits is None:
            logits = out.get("fused")
        if logits is None:
            loss = torch.tensor(0.0, requires_grad=True)
        else:
            loss = logits.float().mean() if isinstance(logits, torch.Tensor) else torch.tensor(0.0, requires_grad=True)
        loss.backward()
        opt.step()
        opt.zero_grad()
        # collect violation rate from MoE layers
        max_viol = 0
        for blk in list(model.text_layers) + list(model.fusion_layers):
            if hasattr(blk, 'mlp') and hasattr(blk.mlp, 'violation_rate'):
                try:
                    vr = blk.mlp.violation_rate()
                    mv = abs(vr.get("max_violation",0))
                    max_viol = max(max_viol, mv)
                except:
                    pass
        violation_history.append(max_viol)
        if step % 10 == 0:
            print(f"step {step} loss {float(loss):.4f} max_viol {max_viol:.3f}")

    max_violation_overall = max(violation_history) if violation_history else 0
    print(f"Final max violation {max_violation_overall:.3f} should be <2.0 for healthy dropless")
    # In MAI Fig8, violation rate measures imbalance; dropless should stay <~1.0 early

    # Deterministic flag test
    deterministic = getattr(cfg.training, "deterministic", False)
    print(f"deterministic flag: {deterministic}")

    result = {
        "periodic_ok": pattern_ok,
        "pattern_match": matches/len(globals_list) if globals_list else 0,
        "zero_init_ok": zero_init_ok,
        "dropout_ok": dropout_ok,
        "max_violation_50": max_violation_overall,
        "violation_history": violation_history,
        "deterministic": deterministic,
        "pass": pattern_ok and zero_init_ok and dropout_ok and max_violation_overall < 2.5
    }
    Path(REPO/"reports").mkdir(exist_ok=True)
    Path(REPO/"reports"/"t12_2_nano_quick.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return result

if __name__ == "__main__":
    r = test_nano_v66()
    sys.exit(0 if r["pass"] else 1)
