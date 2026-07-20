"""Network visualizer: architecture graph + live training peel (CPU-safe).

Does **not** load ServeEngine or touch the trainer GPU. Sources:

* static structure from ``DottieConfig`` (always)
* live J-Space / grad / route signals from ``/pipeline/status`` trainer.last
* optional sparse weight-group RMS norms from the latest checkpoint
  (``torch.load(..., map_location="cpu")`` on the ``model`` state only)

Keep ``AVA_SKIP_ENGINE_BOOT=1`` during training; this module is the peeker.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any

# Soft cache for ckpt group norms keyed by (path, mtime_ns, size).
_NORM_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}
_NORM_CACHE_MAX = 4

_SPACES = ("system1", "system2", "critic", "planner")
_ROUTE_NAMES = ("automatic", "deliberate", "critic", "planner")

# Prefix → visual group for weight-norm peeking.
_GROUP_PREFIXES: tuple[tuple[str, str], ...] = (
    ("embed", "embed"),
    ("text_layers", "text"),
    ("fusion_layers", "fusion"),
    ("fusion_norm", "fusion"),
    ("multi_jspace", "jspace"),
    ("reasoning_layers", "reasoning"),
    ("lm_head", "lm_head"),
    ("vision", "vision"),
)


def build_architecture(preset: str | None = None) -> dict[str, Any]:
    """Config-only network graph: nodes + edges + analytic param count."""
    from dottie.config import DottieConfig

    preset = preset or os.environ.get("AVA_PRESET", "mini")
    cfg = DottieConfig.load(preset)
    m = cfg.model
    j = cfg.jspace

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []

    def add(nid: str, label: str, kind: str, **meta: Any) -> None:
        nodes.append({"id": nid, "label": label, "kind": kind, **meta})

    add("embed", f"embed\nvocab {m.vocab_size}", "io", d_model=m.d_model)
    prev = "embed"
    for i in range(m.n_text_layers):
        nid = f"text_{i}"
        add(
            nid,
            f"text L{i}\n{m.n_heads}h · {m.mlp}",
            "text",
            layer_index=i,
            regime="text",
        )
        edges.append({"from": prev, "to": nid})
        prev = nid

    for i in range(m.n_fusion_layers):
        nid = f"fusion_{i}"
        add(
            nid,
            f"fusion L{i}\n{m.n_heads}h · {m.mlp}",
            "fusion",
            layer_index=i,
            regime="fusion",
        )
        edges.append({"from": prev, "to": nid})
        prev = nid

    add(
        "jspace",
        "Multi-J-Space\n" + " · ".join(f"{s}:{j.slots[s]}" for s in _SPACES),
        "jspace",
        slots=dict(j.slots),
        half_life_target=dict(j.half_life),
        chunk_size=j.chunk_size,
    )
    edges.append({"from": prev, "to": "jspace"})
    prev = "jspace"

    for space in _SPACES:
        sid = f"ws_{space}"
        add(
            sid,
            f"{space}\n{j.slots[space]} slots · hl*{j.half_life[space]:.0f}",
            "workspace",
            space=space,
            slots=j.slots[space],
            hl_target=j.half_life[space],
        )
        edges.append({"from": "jspace", "to": sid})

    add("router", "router\n4 task priors", "router")
    edges.append({"from": "jspace", "to": "router"})

    for i in range(m.n_reasoning_layers):
        nid = f"reason_{i}"
        add(
            nid,
            f"reason L{i}\n{m.n_heads}h · {m.mlp}",
            "reasoning",
            layer_index=i,
            regime="reasoning",
        )
        edges.append({"from": prev if i == 0 else f"reason_{i - 1}", "to": nid})
        if i == 0:
            prev = nid
        else:
            prev = nid

    add("lm_head", f"lm_head\n→ vocab {m.vocab_size}", "io", tied=m.tie_lm_head)
    edges.append({"from": prev, "to": "lm_head"})

    return {
        "preset": cfg.preset,
        "d_model": m.d_model,
        "n_heads": m.n_heads,
        "head_dim": m.head_dim,
        "kv_heads": m.kv_heads,
        "mlp": m.mlp,
        "n_layers": m.n_layers,
        "n_text": m.n_text_layers,
        "n_fusion": m.n_fusion_layers,
        "n_reasoning": m.n_reasoning_layers,
        "params_analytic": cfg.analytic_param_count(),
        "multimodal": m.multimodal,
        "nodes": nodes,
        "edges": edges,
        "spaces": list(_SPACES),
        "route_names": list(_ROUTE_NAMES),
    }


def live_signals_from_trainer_last(last: dict[str, Any] | None) -> dict[str, Any]:
    """Peel live signals the trainer already writes into metrics.jsonl."""
    if not last:
        return {"available": False}
    routes = last.get("route_probs")
    route_map: dict[str, float] = {}
    if isinstance(routes, (list, tuple)) and len(routes) >= 4:
        route_map = {_ROUTE_NAMES[i]: float(routes[i]) for i in range(4)}
    hl = last.get("hl_est") if isinstance(last.get("hl_est"), dict) else {}
    return {
        "available": True,
        "step": last.get("step"),
        "phase": last.get("phase"),
        "lm_loss": last.get("lm_loss") or last.get("lm"),
        "total": last.get("total"),
        "grad_norm": last.get("grad_norm"),
        "tok_s": last.get("tok_s"),
        "lr": last.get("lr"),
        "verbalizable_mass": last.get("verbalizable_mass"),
        "broadcast_strength": last.get("broadcast_strength"),
        "route_probs": route_map,
        "hl_est": {k: float(v) for k, v in hl.items() if _is_num(v)},
        "tokens": last.get("tokens"),
    }


def _is_num(v: Any) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _group_for_key(key: str) -> str:
    for prefix, group in _GROUP_PREFIXES:
        if (
            key == prefix
            or key.startswith(prefix + ".")
            or key.startswith(prefix + "_")
        ):
            return group
    return "other"


def peek_ckpt_group_norms(
    ckpt_path: str | Path,
    *,
    max_bytes: int = 8_000_000_000,
) -> dict[str, Any] | None:
    """CPU-only: RMS norms per param group from ``blob['model']``.

    Returns None if file missing, too large, or torch unavailable. Results
    cached by (path, mtime, size) so polling does not re-scan every request.
    """
    path = Path(ckpt_path)
    if not path.is_file():
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    if st.st_size > max_bytes:
        return {
            "path": str(path),
            "skipped": True,
            "reason": f"ckpt {st.st_size} bytes > max_bytes {max_bytes}",
        }
    cache_key = (str(path.resolve()), int(st.st_mtime_ns), int(st.st_size))
    hit = _NORM_CACHE.get(cache_key)
    if hit is not None:
        return hit

    try:
        import torch
    except ImportError:
        return None

    t0 = time.time()
    try:
        blob = torch.load(path, map_location="cpu", weights_only=False)
    except Exception as exc:
        return {"path": str(path), "error": str(exc)[:240]}

    state = blob.get("model") if isinstance(blob, dict) else None
    if not isinstance(state, dict):
        return {"path": str(path), "error": "no model state_dict in checkpoint"}

    groups: dict[str, list[float]] = {}
    n_tensors = 0
    n_params = 0
    for key, tensor in state.items():
        if not hasattr(tensor, "numel"):
            continue
        n_tensors += 1
        n = int(tensor.numel())
        n_params += n
        # RMS = sqrt(mean(x^2)); float() for bf16 safety.
        try:
            t = tensor.detach().float().reshape(-1)
            rms = float(torch.sqrt(torch.mean(t * t)).item())
        except Exception:
            continue
        if not math.isfinite(rms):
            continue
        groups.setdefault(_group_for_key(key), []).append(rms)

    # Free large blobs ASAP.
    del blob, state

    summary = {
        g: {
            "n": len(vals),
            "rms_mean": sum(vals) / len(vals),
            "rms_max": max(vals),
            "rms_min": min(vals),
        }
        for g, vals in groups.items()
        if vals
    }
    out: dict[str, Any] = {
        "path": str(path),
        "step": None,
        "n_tensors": n_tensors,
        "n_params": n_params,
        "groups": summary,
        "elapsed_s": round(time.time() - t0, 3),
        "skipped": False,
    }
    # Prefer step from filename step_*.pt if present in companion metadata —
    # caller may overwrite.
    if len(_NORM_CACHE) >= _NORM_CACHE_MAX:
        # Drop an arbitrary old entry (insertion order on 3.7+).
        _NORM_CACHE.pop(next(iter(_NORM_CACHE)))
    _NORM_CACHE[cache_key] = out
    return out


def resolve_latest_ckpt(ckpt_dir: str | Path | None = None) -> Path | None:
    """Follow ``latest`` pointer or newest ``*.pt`` under the ckpt volume."""
    root = Path(ckpt_dir or os.environ.get("AVA_CKPT_DIR", "ckpt"))
    if not root.is_dir():
        return None
    pointer = root / "latest"
    if pointer.is_file():
        name = pointer.read_text(encoding="utf-8").strip()
        if name:
            cand = root / name if not Path(name).is_absolute() else Path(name)
            if cand.is_file():
                return cand
    pts = sorted(root.glob("*.pt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return pts[0] if pts else None


def collect_network_status(
    *,
    preset: str | None = None,
    include_ckpt_norms: bool = True,
    pipeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full payload for ``GET /network/status``."""
    preset = preset or os.environ.get("AVA_PRESET", "mini")
    arch = build_architecture(preset)

    trainer_last: dict[str, Any] | None = None
    watch: dict[str, Any] = {}
    ckpt_meta: dict[str, Any] = {}
    if pipeline is None:
        try:
            from dottie.pipeline_status import collect_status

            pipeline = collect_status()
        except Exception:
            pipeline = None
    if pipeline:
        trainer = pipeline.get("trainer") or {}
        trainer_last = (
            trainer.get("last") if isinstance(trainer.get("last"), dict) else None
        )
        watch = pipeline.get("watch") or {}
        ckpt_meta = pipeline.get("ckpt") or {}

    live = live_signals_from_trainer_last(trainer_last)
    # Prefer watch.tokens_per_param when present.
    tpp = watch.get("tokens_per_param") if isinstance(watch, dict) else None

    norms = None
    if include_ckpt_norms:
        path = resolve_latest_ckpt()
        if path is not None:
            norms = peek_ckpt_group_norms(path)
            if norms and live.get("step") is not None:
                norms = {**norms, "step": live.get("step")}

    return {
        "ts": time.time(),
        "preset": preset,
        "architecture": arch,
        "live": live,
        "tokens_per_param": tpp,
        "ckpt": {
            "latest_pointer": ckpt_meta.get("latest_pointer"),
            "norms": norms,
        },
        "mode": (pipeline or {}).get("mode"),
        "hint": (
            "Architecture is config-static; live panel peels trainer metrics; "
            "weight-group RMS comes from the latest checkpoint on CPU (no GPU)."
        ),
    }
