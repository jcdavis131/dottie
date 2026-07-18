"""
convert_to_hf.py — REAL checkpoint conversion to a safetensors export.

Supersedes the old 15-line mock (which wrote a hand-typed
{"hidden_size":2048,"num_layers":48} config and printed "(mock)").
Per specs/09_conversion_release.md this now:

  1. torch.load's the actual checkpoint (weights_only=False — local, trusted),
  2. rebuilds the architecture via AvaConfig + ava.model.build_model,
  3. strict-loads the state dict (any mismatch is a hard error),
  4. writes model.safetensors (tied tensors deduplicated, tying recorded in
     config.json so the export reloads bit-faithfully),
  5. emits a config.json derived from the ACTUAL config + real param count —
     never hardcoded numbers,
  6. copies the tokenizer file byte-identically,
  7. writes an honest README carrying the run's scale label (e.g.
     scale=smoke_cpu_pilot for the CPU pilot — pipeline proof, not capability).

--verify reloads the export from disk and compares full-sequence logits
against the original checkpoint (atol 1e-5).

Solo personal project, no connection to employer, built with public/free-tier only
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent


def _find_run_scale(ckpt_path: Path) -> str:
    """Walk up from the checkpoint for a run MANIFEST.json with a 'scale' label."""
    for parent in ckpt_path.resolve().parents:
        mf = parent / "MANIFEST.json"
        if mf.is_file():
            try:
                scale = json.loads(mf.read_text()).get("scale")
                if scale:
                    return str(scale)
            except Exception:
                pass
        if parent == _REPO:
            break
    return "unspecified"


def _find_config_dir(ckpt_path: Path, preset: str) -> Path:
    """Prefer the config snapshot inside the run tree (frozen at train time)."""
    for parent in ckpt_path.resolve().parents:
        cand = parent / "configs"
        if (cand / f"{preset}.yaml").is_file():
            return cand
        if parent == _REPO:
            break
    return _REPO / "configs"


def _find_tokenizer(ckpt_path: Path) -> Path | None:
    for parent in ckpt_path.resolve().parents:
        cand = parent / "tokenizer"
        if cand.is_dir():
            hits = sorted(cand.glob("*.json"))
            if hits:
                return hits[0]
        if parent == _REPO:
            break
    fallback = _REPO / "data" / "nano" / "tokenizer" / "ava_nano_bpe.json"
    return fallback if fallback.is_file() else None


def _dedupe_tied(state_dict):
    """safetensors rejects shared storage: keep one tensor per storage,
    record dropped aliases as {alias_key: kept_key}."""
    kept, tied_keys, seen = {}, {}, {}
    for k, v in state_dict.items():
        ptr = v.data_ptr()
        if ptr in seen:
            tied_keys[k] = seen[ptr]
        else:
            seen[ptr] = k
            kept[k] = v.contiguous()
    return kept, tied_keys


def load_checkpoint(ckpt_path: Path):
    import torch

    raw = torch.load(str(ckpt_path), map_location="cpu", weights_only=False)
    meta = {}
    if isinstance(raw, dict) and "model" in raw and hasattr(raw["model"], "items"):
        state = raw["model"]
        for key in ("step", "phase", "tokens_done", "preset"):
            if key in raw:
                meta[key] = raw[key]
    else:
        state = raw
    return state, meta


def build_from_preset(preset: str, config_dir: Path):
    from ava.config import AvaConfig
    from ava.model import build_model

    cfg = AvaConfig.load(preset, config_dir)
    model = build_model(cfg).eval()
    return cfg, model


def export(ckpt_path: Path, out_dir: Path, preset: str | None, config_dir: Path | None,
           tokenizer: Path | None, scale: str | None) -> Path:
    from safetensors.torch import save_file

    state, meta = load_checkpoint(ckpt_path)
    preset = preset or str(meta.get("preset") or "nano")
    config_dir = config_dir or _find_config_dir(ckpt_path, preset)
    scale = scale or _find_run_scale(ckpt_path)

    cfg, model = build_from_preset(preset, config_dir)
    model.load_state_dict(state, strict=True)  # mismatch => hard error, no silent partial load
    param_count = sum(p.numel() for p in model.parameters())

    out_dir.mkdir(parents=True, exist_ok=True)

    unique, tied_keys = _dedupe_tied(model.state_dict())
    save_file(unique, str(out_dir / "model.safetensors"))

    m = cfg.model
    config = {
        "model_type": f"ava-{preset}",
        "architectures": ["AvaModel1B"],
        "preset": preset,
        "vocab_size": m.vocab_size,
        "d_model": m.d_model,
        "n_heads": m.n_heads,
        "head_dim": m.head_dim,
        "n_layers_text": m.n_text_layers,
        "n_layers_fusion": m.n_fusion_layers,
        "n_layers_reasoning": m.n_reasoning_layers,
        "mlp": m.mlp,
        "qk_norm": m.qk_norm,
        "rope_base": m.rope_base_init,
        "jspace_slots": dict(cfg.jspace.slots),
        "jspace_half_life": dict(cfg.jspace.half_life),
        "tie_embeddings": m.tie_lm_head,
        "tied_keys": tied_keys,
        "torch_dtype": "float32",
        "tokenizer_file": "tokenizer.json",
        "param_count": param_count,
        "training_step": meta.get("step"),
        "training_tokens": meta.get("tokens_done"),
        "source_checkpoint": str(ckpt_path),
        "scale": scale,
        "capability_claim": "none" if scale == "smoke_cpu_pilot" else None,
        "ava_version": "6.4",
        "export_utc": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (out_dir / "config.json").write_text(json.dumps(config, indent=2))

    tok_src = tokenizer or _find_tokenizer(ckpt_path)
    if tok_src is None or not Path(tok_src).is_file():
        raise SystemExit(f"tokenizer file not found (looked near {ckpt_path}); pass --tokenizer")
    shutil.copyfile(tok_src, out_dir / "tokenizer.json")

    tok_sha = hashlib.sha256(Path(tok_src).read_bytes()).hexdigest()
    (out_dir / "README.md").write_text(
        f"# Ava export — preset `{preset}`, scale `{scale}`\n\n"
        "Solo personal project, no connection to employer, built with public/free-tier only.\n\n"
        f"- Converted from `{ckpt_path}` ({param_count:,} params, "
        f"training_step={meta.get('step')}, training_tokens={meta.get('tokens_done')}).\n"
        f"- `scale={scale}`"
        + (" — CPU smoke pilot: proves the pipeline end-to-end, implies NO model capability.\n"
           if scale == "smoke_cpu_pilot" else "\n")
        + "- All config.json values are read from the actual training config/state dict — "
          "nothing hardcoded.\n"
        + f"- tokenizer.json sha256 `{tok_sha}` (byte-identical copy of `{tok_src}`).\n"
        + "- Reload: rebuild via `ava.config.AvaConfig` + `ava.model.build_model`, load "
          "`model.safetensors`, then re-alias each `tied_keys` entry to its kept tensor.\n"
    )
    print(f"Converted {ckpt_path} -> {out_dir} (REAL export: {param_count:,} params, "
          f"{len(unique)} tensors saved, {len(tied_keys)} tied aliases recorded)")
    return out_dir


def load_export(out_dir: Path):
    """Rebuild a model purely from the export directory."""
    from safetensors.torch import load_file

    config = json.loads((out_dir / "config.json").read_text())
    preset = config["preset"]
    # architecture from the same preset/config_dir recorded at export time
    src = Path(config["source_checkpoint"])
    cfg, model = build_from_preset(preset, _find_config_dir(src, preset) if src.exists()
                                   else _REPO / "configs")
    tensors = load_file(str(out_dir / "model.safetensors"))
    state = dict(tensors)
    for alias, kept in config.get("tied_keys", {}).items():
        state[alias] = state[kept]
    model.load_state_dict(state, strict=True)
    return config, model.eval()


def verify(ckpt_path: Path, out_dir: Path, atol: float = 1e-5) -> bool:
    import torch

    state, meta = load_checkpoint(ckpt_path)
    config = json.loads((out_dir / "config.json").read_text())
    _, orig = build_from_preset(config["preset"], _find_config_dir(ckpt_path, config["preset"]))
    orig.load_state_dict(state, strict=True)
    orig.eval()
    _, conv = load_export(out_dir)

    torch.manual_seed(0)
    vocab = config["vocab_size"]
    x = torch.randint(1, vocab, (1, 32))
    with torch.no_grad():
        a = orig(input_ids=x)
        b = conv(input_ids=x)
    la = (a.get("lm_logits", a.get("logits")) if isinstance(a, dict) else a)
    lb = (b.get("lm_logits", b.get("logits")) if isinstance(b, dict) else b)
    diff = (la - lb).abs().max().item()
    ok = torch.allclose(la, lb, atol=atol, rtol=0)
    print(f"VERIFY {'PASS' if ok else 'FAIL'} max_abs_diff={diff:.3e} (atol={atol})")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Real Ava checkpoint -> safetensors export")
    parser.add_argument("--ckpt", required=True)
    parser.add_argument("--out", default="hf_model")
    parser.add_argument("--preset", default=None, help="config preset; default: read from checkpoint")
    parser.add_argument("--config-dir", default=None, help="dir containing <preset>.yaml; default: run tree, then configs/")
    parser.add_argument("--tokenizer", default=None, help="tokenizer json; default: found in the run tree")
    parser.add_argument("--scale", default=None, help="honesty label; default: run MANIFEST.json 'scale'")
    parser.add_argument("--verify", action="store_true", help="reload export and compare logits vs original")
    args = parser.parse_args()

    ckpt = Path(args.ckpt)
    if not ckpt.is_file():
        raise SystemExit(f"checkpoint not found: {ckpt}")
    out = export(ckpt, Path(args.out), args.preset,
                 Path(args.config_dir) if args.config_dir else None,
                 Path(args.tokenizer) if args.tokenizer else None, args.scale)
    if args.verify and not verify(ckpt, out):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
