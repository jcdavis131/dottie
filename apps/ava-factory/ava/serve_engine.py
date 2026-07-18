"""Live serving engine — real generate / inspect / intervene against a checkpoint.

Thread-safety
-------------
* ``get_engine()`` is a process-wide singleton guarded by ``_ENGINE_LOCK``.
* Every public ``ServeEngine`` method that touches the model acquires
  ``self._lock`` (same lock the hot-reload watcher uses).
* Hot-reload (when ``AVA_CKPT`` points at a ``latest`` pointer file) polls
  mtime + content every ~5s on a daemon thread. On change it resolves the
  target ``.pt``, loads weights under ``self._lock``, then swaps them in.
  Concurrent generate/inspect/intervene wait for the swap to finish.
* Trainer writes ``ckpt/latest`` as a **text file** (filename of the target),
  atomically via ``latest.tmp`` → ``os.replace`` (see ``ava.train._point_latest_at``).
  This engine never opens ``*.tmp``; it only reads the settled ``latest`` file
  and the named ``.pt`` it points at.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Generator, Optional

import torch
import torch.nn.functional as F

from ava.config import AvaConfig
from ava.model import build_model, count_params
from ava.tokenizer import AvaTokenizer
from evals.common import greedy_decode, logprob_of, prep_eval
from evals.interventions import (
    BroadcastSwap,
    WorkspaceSwap,
    concept_vector,
    resolve_space,
    top_concept_trace,
)
from multi_jspace_module import SPACE_NAMES

_REPO = Path(__file__).resolve().parent.parent
_DEFAULT_CKPT = "runs/chat/ava_nano_chat.pt"
_DEFAULT_TOKENIZER_CANDIDATES = (
    "/state/tokenizer.json",
    "data/nano/tokenizer/ava_nano_bpe.json",
)


def _resolve_tokenizer_path(explicit: str | Path | None) -> Path:
    if explicit is not None:
        return _repo_path(explicit)
    env = os.environ.get("AVA_TOKENIZER")
    if env:
        return _repo_path(env)
    for cand in _DEFAULT_TOKENIZER_CANDIDATES:
        p = _repo_path(cand)
        if p.is_file():
            return p
    return _repo_path(_DEFAULT_TOKENIZER_CANDIDATES[-1])
_AUDIT_PATH = _REPO / "runs" / "serve_audit.jsonl"
_HOT_RELOAD_INTERVAL_S = 5.0

_SAFETY_WORDS = [
    "leverage", "blackmail", "threat", "scandal", "shutdown", "fake",
    "secretly", "trick", "unsafe", "dangerous",
]
_ROUTE_KEYS = ("S1", "S2", "Critic", "Planner")

_ENGINE_LOCK = threading.Lock()
_ENGINE: Optional["ServeEngine"] = None


def _repo_path(p: str | Path) -> Path:
    path = Path(p)
    if not path.is_absolute():
        path = _REPO / path
    return path


def resolve_ckpt_path(ckpt: str | Path) -> Path:
    """Resolve ``AVA_CKPT`` to a real ``.pt`` file.

    ``ckpt/latest`` is a text pointer (not a symlink). Never follow ``*.tmp``.
    """
    path = _repo_path(ckpt)
    if path.name.endswith(".tmp") or path.suffix == ".tmp":
        raise FileNotFoundError(f"refusing to read incomplete checkpoint {path}")
    if path.is_file() and path.name == "latest":
        target_name = path.read_text(encoding="utf-8").strip()
        if not target_name or target_name.endswith(".tmp"):
            raise FileNotFoundError(f"latest pointer empty or points at tmp: {path}")
        resolved = path.parent / target_name
        if resolved.name.endswith(".tmp"):
            raise FileNotFoundError(f"refusing to read incomplete checkpoint {resolved}")
        if not resolved.is_file():
            raise FileNotFoundError(
                f"latest points at missing file {resolved} (from {path})"
            )
        return resolved
    return path


def _route_dict(probs: torch.Tensor) -> dict[str, float]:
    vals = probs.detach().float().cpu().tolist()
    if len(vals) != 4:
        raise ValueError(f"expected 4 route probs, got {len(vals)}")
    return {k: float(v) for k, v in zip(_ROUTE_KEYS, vals)}


class ServeEngine:
    """Loads checkpoint + tokenizer once; all inference under ``torch.no_grad``."""

    def __init__(
        self,
        ckpt_path: str | Path | None = None,
        *,
        tokenizer_path: str | Path | None = None,
        device: str = "cpu",
        preset: str = "nano",
        enable_hot_reload: bool | None = None,
    ) -> None:
        raw = ckpt_path if ckpt_path is not None else os.environ.get("AVA_CKPT", _DEFAULT_CKPT)
        self._ckpt_env = str(raw)
        self._ckpt_pointer = _repo_path(raw)
        self._tokenizer_path = _resolve_tokenizer_path(tokenizer_path)
        self.device = torch.device(device)
        self.preset = preset
        self._lock = threading.RLock()
        self._stop_watch = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._pointer_mtime: float | None = None
        self._pointer_content: str | None = None

        if not self._tokenizer_path.is_file():
            raise FileNotFoundError(
                f"tokenizer missing at {self._tokenizer_path}"
            )

        resolved = self._require_ckpt(self._ckpt_pointer)
        self.tokenizer = AvaTokenizer.load(self._tokenizer_path)
        self.model, self.ckpt = self._load_model(resolved)
        self._params = count_params(self.model)
        self._d_model = int(self.model.d_model)
        self._vocab = int(self.model.vocab_size)

        if self._ckpt_pointer.is_file() and self._ckpt_pointer.name == "latest":
            self._pointer_mtime = self._ckpt_pointer.stat().st_mtime
            self._pointer_content = self._ckpt_pointer.read_text(encoding="utf-8")

        do_watch = enable_hot_reload
        if do_watch is None:
            do_watch = self._ckpt_pointer.name == "latest"
        if do_watch:
            self._start_hot_reload()

    def _require_ckpt(self, pointer: Path) -> Path:
        try:
            resolved = resolve_ckpt_path(pointer)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"checkpoint missing at {pointer} "
                f"(set AVA_CKPT to a .pt path or a ckpt/latest pointer; "
                f"current AVA_CKPT={self._ckpt_env!r})"
            ) from None
        if not resolved.is_file():
            raise FileNotFoundError(
                f"checkpoint missing at {resolved} "
                f"(set AVA_CKPT; current AVA_CKPT={self._ckpt_env!r})"
            )
        return resolved

    def _load_model(self, ckpt_file: Path):
        cfg = AvaConfig.load(self.preset)
        model = build_model(cfg, use_memory=False)
        blob = torch.load(ckpt_file, map_location=self.device, weights_only=False)
        state = blob["model"] if isinstance(blob, dict) and "model" in blob else blob
        model.load_state_dict(state)
        model.eval().to(self.device)
        return model, str(ckpt_file)

    def _start_hot_reload(self) -> None:
        t = threading.Thread(
            target=self._hot_reload_loop,
            name="serve-engine-hot-reload",
            daemon=True,
        )
        self._watch_thread = t
        t.start()

    def _hot_reload_loop(self) -> None:
        while not self._stop_watch.wait(_HOT_RELOAD_INTERVAL_S):
            try:
                self._maybe_reload()
            except Exception:
                # Keep serving the previous weights; next poll retries.
                continue

    def _maybe_reload(self) -> None:
        pointer = self._ckpt_pointer
        if not (pointer.is_file() and pointer.name == "latest"):
            return
        mtime = pointer.stat().st_mtime
        content = pointer.read_text(encoding="utf-8")
        if mtime == self._pointer_mtime and content == self._pointer_content:
            return
        resolved = resolve_ckpt_path(pointer)
        with self._lock:
            model, ckpt = self._load_model(resolved)
            self.model = model
            self.ckpt = ckpt
            self._params = count_params(self.model)
            self._d_model = int(self.model.d_model)
            self._vocab = int(self.model.vocab_size)
            self._pointer_mtime = mtime
            self._pointer_content = content

    def stop_hot_reload(self) -> None:
        self._stop_watch.set()
        if self._watch_thread is not None:
            self._watch_thread.join(timeout=2.0)
            self._watch_thread = None

    # -- public API ----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ckpt": self.ckpt,
                "params": int(self._params),
                "vocab": int(self._vocab),
                "d_model": int(self._d_model),
            }

    def generate(
        self,
        text: str,
        max_tokens: int = 64,
        temperature: float = 0.8,
        task_type: str = "chat",
        *,
        seed: int | None = None,
    ) -> dict[str, Any]:
        if not text:
            raise ValueError("text must be non-empty")
        max_tokens = max(1, min(int(max_tokens), 256))
        t0 = time.perf_counter()
        with self._lock:
            with torch.no_grad():
                if seed is not None:
                    torch.manual_seed(int(seed))
                prep_eval(self.model, seed=seed if seed is not None else 1234)
                prompt_ids = self.tokenizer.encode(text)
                ids = list(prompt_ids)
                route_steps: list[dict[str, float]] = []
                for _ in range(max_tokens):
                    x = torch.tensor([ids], dtype=torch.long, device=self.device)
                    out = self.model(input_ids=x, task_type=task_type)
                    logits = out["lm_logits"][0, -1].float()
                    rp = out["jspace"]["route_probs"][0]
                    route_steps.append(_route_dict(rp))
                    if temperature <= 0:
                        nxt = int(logits.argmax().item())
                    else:
                        probs = F.softmax(logits / float(temperature), dim=-1)
                        nxt = int(torch.multinomial(probs, 1).item())
                    ids.append(nxt)
                cont = self.tokenizer.decode(ids[len(prompt_ids) :])
                latency_ms = (time.perf_counter() - t0) * 1000.0
                return {
                    "text": cont,
                    "tokens": len(ids) - len(prompt_ids),
                    "route_probs": route_steps,
                    "latency_ms": float(latency_ms),
                }

    def inspect(self, text: str) -> dict[str, Any]:
        with self._lock:
            with torch.no_grad():
                prep_eval(self.model)
                ids = self.tokenizer.encode(text)
                x = torch.tensor([ids], dtype=torch.long, device=self.device)
                out = self.model(input_ids=x, task_type="deliberate")
                jm = out["jspace"]
                fused = out["fused"]

                # Mean workspace across spaces → verbalizer top-8.
                ws_stack = torch.stack(
                    [jm[n]["workspace"].mean(dim=1) for n in SPACE_NAMES], dim=0
                )  # [4, B, D]
                mean_ws = ws_stack.mean(dim=0)  # [B, D]
                logits = self.model.lm_head(mean_ws).float()
                probs = F.softmax(logits, dim=-1)[0]
                top_p, top_i = probs.topk(8)
                top_concepts = [
                    {"concept": self.tokenizer.decode([int(i)]), "p": float(p)}
                    for i, p in zip(top_i.tolist(), top_p.tolist())
                ]
                verbalizable_mass = float(top_p.sum().item())

                bc = jm["broadcast"]
                broadcast_strength = float(
                    (bc.norm(dim=-1).mean() / (fused.norm(dim=-1).mean() + 1e-6)).item()
                )

                per_space: dict[str, dict[str, float]] = {}
                for n in SPACE_NAMES:
                    space = getattr(self.model.multi_jspace, n)
                    per_space[n] = {
                        "broadcast": float(jm[n]["broadcast_strength"].item()),
                        "hl_est": float(space.hl_est()),
                        "mass": float(jm[n]["verbalizable_mass"].item()),
                    }

                route = jm["route_probs"][0].float()
                route_probs = [float(x) for x in route.tolist()]
                if abs(sum(route_probs) - 1.0) > 1e-4:
                    s = sum(route_probs) or 1.0
                    route_probs = [p / s for p in route_probs]

                # Critic verbalizer mass on safety token set.
                critic_ws = jm["critic"]["workspace"].mean(dim=1)
                critic_probs = F.softmax(
                    self.model.multi_jspace.critic.verbalizer(critic_ws).float(), dim=-1
                )[0]
                safety_scan: dict[str, float] = {}
                total = 0.0
                for w in _SAFETY_WORDS:
                    tid = self._safety_token_id(w)
                    p = float(critic_probs[tid].item())
                    safety_scan[w] = p
                    total += p
                safety_scan["total"] = total

                # Exercise shipped per-space decoder (mass already from probe above).
                _ = top_concept_trace(self.model, self.tokenizer, out, k=8)

                return {
                    "top_concepts": top_concepts,
                    "verbalizable_mass": verbalizable_mass,
                    "broadcast_strength": broadcast_strength,
                    "per_space": per_space,
                    "route_probs": route_probs,
                    "safety_scan": safety_scan,
                }

    def _safety_token_id(self, word: str) -> int:
        ids = self.tokenizer.encode(word)
        if len(ids) == 1:
            return ids[0]
        return self.tokenizer.concept_token(word)

    def intervene(
        self,
        text: str,
        from_concept: str,
        to_concept: str,
        space: str = "system2",
        *,
        seed: int = 1234,
    ) -> dict[str, Any]:
        space = resolve_space(space)
        prompt_ids = self.tokenizer.encode(text)
        max_tokens = 32

        with self._lock:
            # Baseline (no hook) under fixed seed.
            with torch.no_grad():
                prep_eval(self.model, seed=seed)
                base_ids = greedy_decode(
                    self.model,
                    prompt_ids,
                    max_new=max_tokens,
                    task_type="deliberate",
                    device=self.device,
                )
                baseline_text = self.tokenizer.decode(base_ids[len(prompt_ids) :])
                lp_from_base = logprob_of(
                    self.model, prompt_ids, from_concept, self.tokenizer,
                    task_type="deliberate", device=self.device,
                )
                lp_to_base = logprob_of(
                    self.model, prompt_ids, to_concept, self.tokenizer,
                    task_type="deliberate", device=self.device,
                )

            # Planner broadcast interventions match evals/jspace_tests France→China;
            # other spaces edit workspace slot state (Spider→Ant).
            swap_cls = BroadcastSwap if space == "planner" else WorkspaceSwap
            with swap_cls(
                self.model, self.tokenizer, space, from_concept, to_concept
            ):
                with torch.no_grad():
                    prep_eval(self.model, seed=seed)
                    int_ids = greedy_decode(
                        self.model,
                        prompt_ids,
                        max_new=max_tokens,
                        task_type="deliberate",
                        device=self.device,
                    )
                    intervened_text = self.tokenizer.decode(
                        int_ids[len(prompt_ids) :]
                    )
                    lp_from_int = logprob_of(
                        self.model, prompt_ids, from_concept, self.tokenizer,
                        task_type="deliberate", device=self.device,
                    )
                    lp_to_int = logprob_of(
                        self.model, prompt_ids, to_concept, self.tokenizer,
                        task_type="deliberate", device=self.device,
                    )

            delta_logprob = (lp_to_int - lp_from_int) - (lp_to_base - lp_from_base)
            changed = baseline_text != intervened_text
            self._append_audit(
                from_concept=from_concept,
                to_concept=to_concept,
                space=space,
                text=text,
                delta_logprob=delta_logprob,
                changed=changed,
            )
            # concept_vector is the shared addressing used by both swap classes.
            _ = concept_vector(self.model, self.tokenizer, from_concept)
            return {
                "baseline_text": baseline_text,
                "intervened_text": intervened_text,
                "delta_logprob": float(delta_logprob),
                "space": space,
                "changed": changed,
                "audit_logged": True,
            }

    def _append_audit(
        self,
        *,
        from_concept: str,
        to_concept: str,
        space: str,
        text: str,
        delta_logprob: float,
        changed: bool,
    ) -> None:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": time.time(),
            "from": from_concept,
            "to": to_concept,
            "space": space,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "delta_logprob": float(delta_logprob),
            "changed": bool(changed),
        }
        with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def block_stream(self, text: str) -> Generator[dict[str, Any], None, None]:
        """Yield one dict per transformer block from a single real forward."""
        with self._lock:
            with torch.no_grad():
                prep_eval(self.model)
                ids = self.tokenizer.encode(text)
                x = torch.tensor([ids], dtype=torch.long, device=self.device)

                captures: list[dict[str, Any]] = []
                handles = []

                def _make_hook(block_i: int, regime: str):
                    def hook(_module, _inp, out):
                        # TransformerBlock1B returns a Tensor [B, L, D].
                        h = out[0] if isinstance(out, tuple) else out
                        hn = float(h.detach().norm(dim=-1).mean().item())
                        mean_h = h.detach().mean(dim=1)  # [B, D]
                        logits = self.model.lm_head(mean_h).float()
                        probs = F.softmax(logits, dim=-1)[0]
                        top_id = int(probs.argmax().item())
                        top_concept = self.tokenizer.decode([top_id])
                        captures.append(
                            {
                                "block": block_i,
                                "regime": regime,
                                "hidden_norm": hn,
                                "top_concept": top_concept,
                                "route_probs": None,
                            }
                        )

                    return hook

                block_i = 0
                for blk in self.model.text_layers:
                    handles.append(blk.register_forward_hook(_make_hook(block_i, "text")))
                    block_i += 1
                for blk in self.model.fusion_layers:
                    handles.append(blk.register_forward_hook(_make_hook(block_i, "fusion")))
                    block_i += 1
                for blk in self.model.reasoning_layers:
                    handles.append(
                        blk.register_forward_hook(_make_hook(block_i, "reasoning"))
                    )
                    block_i += 1

                try:
                    out = self.model(input_ids=x, task_type="deliberate")
                    route = _route_dict(out["jspace"]["route_probs"][0])
                    for cap in captures:
                        if cap["regime"] == "fusion":
                            cap["route_probs"] = route
                        yield cap
                finally:
                    for h in handles:
                        h.remove()


def get_engine() -> ServeEngine:
    """Lazy, thread-safe process singleton."""
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = ServeEngine()
        return _ENGINE


def reset_engine_for_tests() -> None:
    """Drop the singleton (tests only)."""
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            _ENGINE.stop_hot_reload()
        _ENGINE = None


__all__ = [
    "ServeEngine",
    "get_engine",
    "resolve_ckpt_path",
    "reset_engine_for_tests",
]
