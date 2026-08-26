# Solo personal project, no connection to employer, built with public/free-tier only
"""infer plugin — colibri-inspired tiered inference harness, zero-deps stdlib-only.

Tiny engine, immense model: treats VRAM/RAM/disk as one hierarchy, streams experts,
never silently downcasts, same front for many families. Distilled from colibri,
not copied — principle only: one hierarchy, honest semantics, I/O is part of engine,
experiments earn place via measurement.

Pattern mirrors ollama/forge: stdlib only, optional torch via probe, honest 503.

Zero-deps true: stdlib only at import time. Typer/Rich are optional for Scout CLI
wiring; `python -m bigbang.plugins.infer.cli` works without them.
"""

from __future__ import annotations

import json
import mmap
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

# ---------------------------------------------------------------------------
# stdlib-only helpers — no typer/rich at import time
# ---------------------------------------------------------------------------

DEFAULT_DISK_ROOT = Path.home() / ".cache" / "dottie" / "models"
DENSE_RESIDENT_GB = 9.9  # colibri dense int4 resident
LRU_SLOTS = 128
PINNED_TOPK = 512

SUPPORTED_FAMILIES = {
    "glm52": {"params": "744B", "experts": 19456, "dense_gb": 9.9, "arch": "moe", "file": "glm52_i4"},
    "inkling": {"params": "975B", "experts": 20480, "dense_gb": 11.2, "arch": "moe", "file": "inkling_i4"},
    "kimi_k3": {"params": "2.8T", "experts": 32768, "dense_gb": 14.1, "arch": "moe", "file": "kimi_k3_i4"},
    "deepseek_v4": {"params": "284B", "experts": 8192, "dense_gb": 6.4, "arch": "moe", "file": "ds_v4_i4"},
    "qwen3": {"params": "35B-A3B", "experts": 128, "dense_gb": 2.1, "arch": "moe", "file": "qwen3_i4"},
    "olmoe": {"params": "7B", "experts": 64, "dense_gb": 1.8, "arch": "moe", "file": "olmoe_i4"},
}

# --- ok / emit fallbacks ---------------------------------------------------

def _ok_fallback(data, *, command: str, example: str | None = None, discover: str | None = None, **extra):
    payload = {"ok": True, "command": command}
    if data is not None:
        payload["data"] = data
    if example:
        payload["example"] = example
    if discover:
        payload["discover"] = discover
    payload.update(extra)
    return payload

def _emit_fallback(data, command: str = "unknown"):
    try:
        from bigbang.core.output import emit as real_emit  # type: ignore
        real_emit(data, command=command)
        return
    except Exception:
        pass
    try:
        json.dump(data, __import__("sys").stdout, indent=2, default=str)
        __import__("sys").stdout.write("\n")
    except Exception:
        print(str(data))

def _load_ok_emit():
    try:
        from bigbang.core.contract import ok as real_ok  # type: ignore
        from bigbang.core.output import emit as real_emit  # type: ignore
        return real_ok, real_emit
    except Exception:
        return _ok_fallback, _emit_fallback

ok, emit = _load_ok_emit()

def _load_manifest_fallback():
    try:
        from bigbang.core.policy import load_manifest  # type: ignore
        return load_manifest
    except Exception:
        return None

def _load_enforce():
    try:
        from bigbang.core.policy import enforce_or_raise  # type: ignore
        return enforce_or_raise
    except Exception:
        return None

load_manifest = _load_manifest_fallback()
enforce_or_raise = _load_enforce()

_MANIFEST = None
_MANIFEST_LOADED = False

def _manifest():
    global _MANIFEST, _MANIFEST_LOADED
    if not _MANIFEST_LOADED:
        _MANIFEST_LOADED = True
        if load_manifest is None:
            _MANIFEST = {}
        else:
            try:
                _MANIFEST = load_manifest(Path(__file__).parent)
            except Exception:
                _MANIFEST = {}
    return _MANIFEST or {}


@dataclass
class TierPlacement:
    vram_free_mb: int | None = None
    ram_free_mb: int | None = None
    disk_root: str = str(DEFAULT_DISK_ROOT)
    dense_resident: bool = False
    tier_bar: Dict[str, int] = field(default_factory=dict)


def _probe_tiers(disk_root: Path) -> TierPlacement:
    """Probe VRAM/RAM/disk without assuming anything — colibri honesty."""
    vram = None
    ram = None
    try:
        if Path("/proc/meminfo").exists():
            txt = Path("/proc/meminfo").read_text()[:2000]
            for line in txt.splitlines():
                if line.startswith("MemAvailable:"):
                    ram = int(line.split()[1]) // 1024
                    break
    except Exception:
        ram = None

    try:
        stat = os.statvfs(str(disk_root)) if disk_root.exists() else os.statvfs(str(Path.home()))
        disk_free_mb = (stat.f_bavail * stat.f_frsize) // (1024 * 1024)
    except Exception:
        disk_free_mb = None

    try:
        import subprocess
        import shutil

        if shutil.which("nvidia-smi"):
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if out.returncode == 0:
                vram = int(out.stdout.strip().split()[0])
    except Exception:
        vram = None

    bar = {}
    if vram is not None:
        bar["vram"] = vram
    if ram is not None:
        bar["ram"] = ram
    if disk_free_mb is not None:
        bar["disk"] = disk_free_mb
    return TierPlacement(vram_free_mb=vram, ram_free_mb=ram, disk_root=str(disk_root), tier_bar=bar)


def _disk_cache_check(model: str, disk_root: Path) -> dict:
    meta = SUPPORTED_FAMILIES.get(model, {})
    model_dir = disk_root / model
    dense_path = model_dir / "dense.int4"
    experts_dir = model_dir / "experts"
    count = 0
    if experts_dir.exists():
        try:
            count = len([p for p in experts_dir.iterdir() if p.is_file()])
        except Exception:
            count = 0
    return {
        "model": model,
        "params": meta.get("params", "unknown"),
        "dense_exists": dense_path.exists(),
        "dense_path": str(dense_path),
        "experts_dir": str(experts_dir),
        "experts_on_disk": count,
        "experts_total": meta.get("experts", 0),
        "resident_ratio": round(count / max(1, meta.get("experts", 1)), 3),
        "disk_root": str(disk_root),
    }


class TieredCache:
    """Colibri-inspired: LRU RAM + pinned hot-store + one-ahead prefetch, stdlib only."""

    def __init__(self, disk_root: Path, lru_slots: int = LRU_SLOTS, pinned: List[str] | None = None):
        self.disk_root = disk_root
        self.lru_slots = lru_slots
        self.pinned = set(pinned or [])
        self._lru: Dict[str, bytes] = {}
        self._order: List[str] = []
        self.hits = 0
        self.misses = 0
        self.bytes_read = 0
        self._lock = threading.Lock()
        self._prefetch_thread: threading.Thread | None = None

    def get(self, expert_id: str, model: str, no_downcast: bool = True) -> bytes | None:
        key = f"{model}/{expert_id}"
        with self._lock:
            if key in self._lru:
                try:
                    self._order.remove(key)
                except ValueError:
                    pass
                self._order.append(key)
                self.hits += 1
                return self._lru[key]
            self.misses += 1

        exp_path = self.disk_root / model / "experts" / f"{expert_id}.int4"
        if not exp_path.exists():
            return None
        if no_downcast and "int4" not in exp_path.name:
            if exp_path.suffix == ".fp16":
                return None
        try:
            with open(exp_path, "rb") as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    data = mm[:]
                    self.bytes_read += len(data)
                    with self._lock:
                        if len(self._lru) >= self.lru_slots and self._order:
                            for evict in list(self._order):
                                if evict not in self.pinned:
                                    try:
                                        self._order.remove(evict)
                                    except ValueError:
                                        pass
                                    self._lru.pop(evict, None)
                                    break
                        self._lru[key] = data
                        self._order.append(key)
                    return data
        except Exception:
            return None

    def get_batch(self, expert_ids: List[str], model: str, no_downcast: bool = True) -> Dict[str, bytes | None]:
        return {eid: self.get(eid, model, no_downcast=no_downcast) for eid in expert_ids}

    def prefetch(self, layer_experts: List[str], model: str):
        def _do():
            for eid in layer_experts[:8]:
                self.get(eid, model, no_downcast=True)

        t = threading.Thread(target=_do, daemon=True)
        t.start()
        self._prefetch_thread = t

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / max(1, total), 3)

    def tier_bar(self) -> dict:
        return {"vram_cached": 0, "ram_cached": len(self._lru), "pinned": len(self.pinned), "bytes_read": self.bytes_read}


def cmd_hello() -> dict:
    return ok(
        {"ready": True, "plugin": "infer", "pattern": "colibri: tiny engine, immense model, honest semantics"},
        command="infer hello",
        example="scout --json infer list",
        discover="scout infer status",
    )


def cmd_list() -> dict:
    disk_root = DEFAULT_DISK_ROOT
    rows = []
    for name, meta in SUPPORTED_FAMILIES.items():
        cache = _disk_cache_check(name, disk_root)
        rows.append({**meta, **cache, "front": "coli chat/serve/web → scout infer chat/serve/web"})
    return ok(
        {"models": rows, "count": len(rows), "disk_root": str(disk_root), "principle": "one-file-per-model, same front, streaming from disk"},
        command="infer list",
        example="scout --json infer status",
        discover="scout infer run",
    )


def cmd_status(disk_root_str: str = str(DEFAULT_DISK_ROOT)) -> dict:
    root = Path(disk_root_str)
    placement = _probe_tiers(root)
    caches = [_disk_cache_check(m, root) for m in SUPPORTED_FAMILIES]
    total_experts = sum(c["experts_on_disk"] for c in caches)
    return ok(
        {
            "placement": {
                "vram_free_mb": placement.vram_free_mb,
                "ram_free_mb": placement.ram_free_mb,
                "disk_root": placement.disk_root,
                "tier_bar": placement.tier_bar,
                "note": "limited fast memory changes speed, not semantics — colibri guarantee",
            },
            "caches": caches,
            "total_experts_on_disk": total_experts,
            "dense_resident_gb": DENSE_RESIDENT_GB,
            "lru_slots": LRU_SLOTS,
            "pinned_topk": PINNED_TOPK,
            "honest": "semantics never silently changes precision/router, no SLA on speed",
        },
        command="infer status",
        example="scout --json infer run --model glm52 --prompt 'hi'",
        discover="scout infer run",
    )


def cmd_run(
    model: str = "glm52",
    prompt: str = "",
    disk_root_str: str = str(DEFAULT_DISK_ROOT),
    no_downcast: bool = True,
    tier: str = "",
    max_experts: int = 8,
) -> dict:
    if model not in SUPPORTED_FAMILIES:
        return {
            "ok": False,
            "error": f"unknown model {model!r} — pick from {list(SUPPORTED_FAMILIES)}",
            "command": "infer run",
            "example": "scout --json infer list",
            "errorClass": "BAD_ARGS",
        }

    root = Path(disk_root_str)

    cache_info = _disk_cache_check(model, root)
    if not cache_info["dense_exists"]:
        return {
            "ok": False,
            "error": f"dense tier missing for {model} at {cache_info['dense_path']} — run scout infer status, then place model",
            "errorClass": "IO_MISSING",
            "model": model,
            "cache": cache_info,
            "hint": f"mkdir -p {root}/{model}/experts && place dense.int4 + experts/*.int4",
            "semantics_guard": "no silent downcast — failing closed per colibri guarantee",
            "command": "infer run",
            "example": "scout --json infer status",
        }

    if no_downcast and cache_info["experts_on_disk"] == 0:
        return {
            "ok": False,
            "error": f"experts tier empty for {model} — 0/{cache_info['experts_total']} on disk, streaming requires disk tier",
            "errorClass": "SEMANTICS_GUARD",
            "cache": cache_info,
            "guard": "never silently changes precision/router — insufficient memory reduces speed, not correctness",
            "command": "infer run",
        }

    budget = {}
    if tier:
        try:
            for kv in tier.split(","):
                k, v = kv.split("=")
                budget[k.strip()] = int(v.strip())
        except Exception:
            return {
                "ok": False,
                "error": f"bad --tier {tier!r} — use ram=1024,vram=0",
                "errorClass": "BAD_ARGS",
                "command": "infer run",
                "example": "scout infer run --tier ram=1024",
            }

    # Real forward not wired — honest 503, never synthetic text.
    return {
        "ok": False,
        "error": f"inference engine not wired for {model} — dense exists at {cache_info['dense_path']} but forward pass requires numpy parity ≤1e-4 (real MLP router + dense mmap) — honest 503",
        "errorClass": "NOT_IMPLEMENTED",
        "model": model,
        "cache": cache_info,
        "budget": budget,
        "max_experts": max_experts,
        "prompt_len": len(prompt),
        "placement": _probe_tiers(root).__dict__,
        "semantics_guard": "hard guarantee on semantics — never silently changes precision/router; no SLA on speed — insufficient memory reduces speed only",
        "hint": "wire real forward in infer/cli.py cmd_run — remove this 503 when numpy parity ≤1e-4 verified",
        "command": "infer run",
        "example": "scout --json infer status",
    }


def _try_make_typer_app():
    try:
        import typer  # type: ignore

        from bigbang.core.cli_ux import examples_epilog  # type: ignore
        from bigbang.core.contract import make_plugin_app  # type: ignore
    except Exception:
        return None

    app = make_plugin_app(
        "infer",
        "Tiny engine, immense model — colibri-inspired tiered inference (stdlib-only, honest semantics, streaming from disk)",
        examples=[
            "scout --json infer hello",
            "scout --json infer list",
            "scout --json infer status",
            "scout --json infer run --model glm52 --prompt 'ciao'",
            "scout --json infer run --model glm52 --prompt 'hi' --no-downcast --tier ram=1024",
        ],
    )

    @app.command("hello", epilog=examples_epilog(["scout --json infer hello"]))
    def hello():
        emit(cmd_hello(), command="infer hello")

    @app.command("list", epilog=examples_epilog(["scout --json infer list"]))
    def list_cmd():
        emit(cmd_list(), command="infer list")

    @app.command("status", epilog=examples_epilog(["scout --json infer status"]))
    def status_cmd(
        disk_root: str = typer.Option(str(DEFAULT_DISK_ROOT), "--disk-root", help="disk tier root"),
    ):
        emit(cmd_status(disk_root), command="infer status")

    @app.command("run", epilog=examples_epilog(["scout infer run --model glm52 --prompt 'ciao'"]))
    def run_cmd(
        model: str = typer.Option("glm52", "--model", "-m", help="model family"),
        prompt: str = typer.Option(..., "--prompt", "-p", help="prompt text"),
        disk_root: str = typer.Option(str(DEFAULT_DISK_ROOT), "--disk-root"),
        no_downcast: bool = typer.Option(True, "--no-downcast/--allow-downcast", help="hard guarantee: never silently change precision"),
        tier: str = typer.Option("", "--tier", help="budget override e.g. ram=1024,vram=0"),
        max_experts: int = typer.Option(8, "--max-experts", help="experts per token (MoE sparsity)"),
    ):
        res = cmd_run(model=model, prompt=prompt, disk_root_str=disk_root, no_downcast=no_downcast, tier=tier, max_experts=max_experts)
        if isinstance(res, dict) and res.get("ok") is False:
            emit(res, command="infer run")
            raise typer.Exit(1)
        emit(res, command="infer run")

    @app.command("chat", epilog=examples_epilog(["scout infer chat --model glm52"]))
    def chat_cmd(
        model: str = typer.Option("glm52", "--model"),
        disk_root: str = typer.Option(str(DEFAULT_DISK_ROOT), "--disk-root"),
    ):
        emit(
            ok(
                {"front": "chat", "model": model, "disk_root": disk_root, "note": "stub — wires to run loop with persistent KV (57× smaller MLA) + readline, same as coli chat", "example": f"scout infer run --model {model} --prompt 'ciao'"},
                command="infer chat",
            ),
            command="infer chat",
        )

    @app.command("serve", epilog=examples_epilog(["scout infer serve --model glm52 --port 8787"]))
    def serve_cmd(
        model: str = typer.Option("glm52", "--model"),
        port: int = typer.Option(8787, "--port"),
    ):
        emit(ok({"front": "serve", "model": model, "port": port, "note": "stub — http.server stdlib, same as coli serve"}, command="infer serve"), command="infer serve")

    return app


app = _try_make_typer_app()


def register(root):
    if app is not None:
        try:
            root.add_typer(app, name="infer")
        except Exception:
            pass


def _argparse_main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="scout infer", description="Tiny engine, immense model — colibri-inspired tiered inference")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_hello = sub.add_parser("hello", help="smoke check")
    p_list = sub.add_parser("list", help="list families")
    p_status = sub.add_parser("status", help="tier placement")
    p_status.add_argument("--disk-root", default=str(DEFAULT_DISK_ROOT))

    p_run = sub.add_parser("run", help="run inference")
    p_run.add_argument("--model", "-m", default="glm52")
    p_run.add_argument("--prompt", "-p", required=True)
    p_run.add_argument("--disk-root", default=str(DEFAULT_DISK_ROOT))
    p_run.add_argument("--no-downcast", dest="no_downcast", action="store_true", default=True)
    p_run.add_argument("--allow-downcast", dest="no_downcast", action="store_false")
    p_run.add_argument("--tier", default="")
    p_run.add_argument("--max-experts", type=int, default=8)
    p_run.add_argument("--json", action="store_true", help="json output")

    args = parser.parse_args()

    if args.cmd == "hello":
        res = cmd_hello()
    elif args.cmd == "list":
        res = cmd_list()
    elif args.cmd == "status":
        res = cmd_status(args.disk_root)
    elif args.cmd == "run":
        res = cmd_run(model=args.model, prompt=args.prompt, disk_root_str=args.disk_root, no_downcast=args.no_downcast, tier=args.tier, max_experts=args.max_experts)
        if isinstance(res, dict) and res.get("ok") is False and res.get("errorClass") in ("IO_MISSING", "SEMANTICS_GUARD", "NOT_IMPLEMENTED"):
            print(json.dumps(res, indent=2))
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)

    try:
        from bigbang.core.output import is_json

        if is_json():
            print(json.dumps(res, indent=2))
        else:
            _emit_fallback(res, command=f"infer {args.cmd}")
    except Exception:
        print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    _argparse_main()
