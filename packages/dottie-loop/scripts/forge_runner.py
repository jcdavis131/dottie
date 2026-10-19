#!/usr/bin/env python3
"""forge_runner — the single file an operator copies to the GPU box (spec §27).

Runner protocol, in order:

1. advertise hostname, GPU, VRAM, CUDA, torch, platform and a heartbeat under
   ``runners/<host>.json`` in the queue repository
2. poll pending jobs and filter by declared requirements
3. claim atomically (rename pending → claimed with runner identity)
4. clone or update the target repository and check out the immutable ref
5. verify input hashes and execute ``argv`` without a shell
6. capture stdout/stderr, parse ``FORGE_METRIC`` lines, enforce the timeout
7. write result JSON + log, hash outputs, push to the queue repository

No inbound ports, no VPN, no ad hoc shell: the queue repository is the conveyor
and every git operation is an argument array. Repository allowlist, one job per
tick, disk preflight, heartbeat and a manual ``--once`` path are built in.

Usage (on the box)::

    python forge_runner.py --queue-repo git@github.com:owner/forge-queue.git \\
        --workdir ~/forge --allow owner/repo --gpu "RTX 4090" --vram-gb 24 --once

Needs ``dottie_loop`` importable (``pip install -e packages/dottie-loop`` or the
uv workspace). Everything else is stdlib + git.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any

from dottie_loop.execution import run_argv
from dottie_loop.forge import ForgeQueue, RunnerRecord
from dottie_loop.hashing import now_iso

MIN_FREE_GB = 5.0


def probe_hardware(gpu: str | None, vram_gb: float | None) -> dict[str, Any]:
    """Advertise what the box really has. torch is optional; its absence is reported, not guessed."""
    cuda = None
    torch_v = None
    try:  # optional, never required
        import torch  # type: ignore[import-not-found]

        torch_v = str(torch.__version__)
        if torch.cuda.is_available():
            cuda = str(torch.version.cuda)
            gpu = gpu or torch.cuda.get_device_name(0)
            vram_gb = vram_gb if vram_gb is not None else round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1)
    except Exception:
        pass
    return {"gpu": gpu or "none", "vram_gb": float(vram_gb or 0.0), "cuda": cuda, "torch": torch_v, "platform": platform.platform()}


def git(args: list[str], cwd: Path, timeout_s: float = 300.0) -> dict[str, Any]:
    res = run_argv(["git", *args], cwd=cwd, timeout_s=timeout_s, env_allow=["PATH", "HOME", "LANG", "SSH_AUTH_SOCK", "GIT_SSH_COMMAND"])
    if res["exit_code"] != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res['stderr'][-400:]}")
    return res


def sync_queue(queue_repo: str, queue_dir: Path) -> None:
    if not (queue_dir / ".git").exists():
        queue_dir.parent.mkdir(parents=True, exist_ok=True)
        git(["clone", "--quiet", queue_repo, str(queue_dir)], cwd=queue_dir.parent)
    else:
        git(["pull", "--quiet", "--rebase"], cwd=queue_dir)


def push_queue(queue_dir: Path, message: str) -> bool:
    git(["add", "-A"], cwd=queue_dir)
    status = git(["status", "--porcelain"], cwd=queue_dir)
    if not status["stdout"].strip():
        return False
    git(["-c", "user.name=forge-runner", "-c", "user.email=forge-runner@local", "commit", "--quiet", "-m", message], cwd=queue_dir)
    git(["push", "--quiet"], cwd=queue_dir)
    return True


def checkout_target(repo: str, ref: str, workdir: Path, remote_base: str) -> Path:
    """Clone/update ``repo`` into workdir and check out the immutable ref."""
    dest = workdir / "checkouts" / repo.replace("/", "__")
    url = remote_base.rstrip("/") + "/" + repo if not remote_base.startswith("git@") else f"{remote_base}:{repo}.git"
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        git(["clone", "--quiet", url, str(dest)], cwd=dest.parent)
    else:
        git(["fetch", "--quiet", "--all"], cwd=dest)
    git(["checkout", "--quiet", "--detach", ref], cwd=dest)
    head = git(["rev-parse", "HEAD"], cwd=dest)["stdout"].strip()
    if not head.startswith(ref):
        raise RuntimeError(f"checked out {head}, expected {ref}")
    return dest


def disk_preflight(path: Path) -> tuple[bool, float]:
    free_gb = shutil.disk_usage(path).free / 2**30
    return free_gb >= MIN_FREE_GB, round(free_gb, 1)


def tick(args: argparse.Namespace) -> dict[str, Any]:
    workdir = Path(args.workdir).expanduser()
    queue_dir = workdir / "queue"
    sync_queue(args.queue_repo, queue_dir)
    q = ForgeQueue(queue_dir, repo_allowlist=args.allow)
    hw = probe_hardware(args.gpu, args.vram_gb)
    runner = RunnerRecord(hostname=args.hostname or socket.gethostname(), heartbeat_at=now_iso(), **hw)
    q.advertise(runner)
    ok_disk, free_gb = disk_preflight(workdir)
    if not ok_disk:
        push_queue(queue_dir, f"runner {runner.hostname}: heartbeat (disk low {free_gb}GB, not claiming)")
        return {"claimed": None, "reason": f"disk preflight failed: {free_gb}GB free < {MIN_FREE_GB}GB"}
    spec = q.claim(runner)
    push_queue(queue_dir, f"runner {runner.hostname}: heartbeat" + (f", claimed {spec.job_id}" if spec else ""))
    if spec is None:
        return {"claimed": None, "reason": "no claimable job"}
    if args.dry_run:
        return {"claimed": spec.job_id, "dry_run": True, "argv": spec.argv}
    try:
        checkout = checkout_target(spec.repo, spec.ref, workdir, args.remote_base)
    except RuntimeError as e:
        res = q._write_result(spec, status="failed", reason=f"checkout: {e}", runner=runner.hostname)
        q._finish(spec)
        push_queue(queue_dir, f"runner {runner.hostname}: {spec.job_id} checkout failed")
        return {"claimed": spec.job_id, "result": res}
    res = q.execute(spec, checkout, runner)
    push_queue(queue_dir, f"runner {runner.hostname}: {spec.job_id} {res['status']}")
    return {"claimed": spec.job_id, "result": res}


def _helper_ft_kickoff_path() -> Path | None:
    here = Path(__file__).resolve()
    if len(here.parents) >= 4:
        candidate = here.parents[3] / "apps" / "dottie-os" / "scripts" / "lab" / "helper_ft_kickoff.py"
        if candidate.is_file():
            return candidate
    return None


def _load_helper_ft_kickoff():
    path = _helper_ft_kickoff_path()
    if path is None:
        return None
    spec = importlib.util.spec_from_file_location("helper_ft_kickoff", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_STATE_LEAK_KEYS = frozenset(
    {"risk_hint", "halt_class", "provenance", "agent_config", "category"}
)


def _fallback_state_leaks(body: dict[str, Any]) -> list[str]:
    """Off-tree runner still refuses leaked gold values when jsonl paths exist."""
    paths = body.get("paths")
    if not isinstance(paths, dict):
        return []
    pack_dir = body.get("source_pack_dir")
    evidence = body.get("evidence")
    if pack_dir is None and isinstance(evidence, dict):
        pack_dir = evidence.get("source_pack_dir")
    helper = _load_helper_ft_kickoff()
    if helper is not None:
        try:
            return helper.kick_helper_ft.collect_state_leaks(paths, pack_dir=pack_dir)
        except Exception:
            pass
    found: list[str] = []
    seen: set[str] = set()

    def walk(value: object, path: str, row_id: str) -> None:
        if len(found) >= 10:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                key_s = str(key)
                child_path = f"{path}.{key_s}"
                if key_s in _STATE_LEAK_KEYS:
                    item = f"{row_id}:{child_path}"
                    if item not in seen:
                        seen.add(item)
                        found.append(item)
                        if len(found) >= 10:
                            return
                walk(child, child_path, row_id)
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                walk(child, f"{path}[{idx}]", row_id)

    for key in ("pack", "train", "holdout"):
        raw = paths.get(key)
        if not isinstance(raw, str) or not raw:
            continue
        path = Path(raw)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            row_id = obj.get("id") or obj.get("trajectory_id") or "?"
            walk(obj.get("state"), "state", str(row_id))
            if len(found) >= 10:
                return found
    return found


def _inbox_is_latest(value: str) -> bool:
    """Refuse ``latest`` as a whole path, component, or ``_``/``-`` token."""
    text = value.replace("\\", "/").lower().strip().replace(" ", "")
    aliases = {"latest", "inbox_latest", "inbox-latest", "inbox:latest"}
    if text in aliases:
        return True
    for part in text.split("/"):
        if part in aliases or part == "latest":
            return True
        for token in part.replace("-", "_").split("_"):
            if token == "latest":
                return True
    return False


def handle_train_kickoff(body: dict[str, Any] | None) -> dict[str, Any]:
    """HELPER FT ``POST /train/kickoff``. Never accepts ``inbox: latest``.

    Canonical implementation: ``apps/dottie-os/scripts/lab/helper_ft_kickoff.py``.
    Checks run before any GPU launch. When this runner is copied off-tree,
    still refuse latest/missing evidence.
    """
    mod = _load_helper_ft_kickoff()
    if mod is not None:
        return mod.handle_train_kickoff(body)
    if not isinstance(body, dict):
        return {"ok": False, "field": "body", "expected": "object", "actual": type(body).__name__}
    inbox = body.get("inbox")
    if "inbox_latest" in body:
        return {"ok": False, "field": "inbox_latest", "expected": "absent", "actual": "present"}
    if isinstance(inbox, str) and _inbox_is_latest(inbox):
        return {"ok": False, "field": "inbox", "expected": "named pack_id", "actual": inbox}
    if body.get("mode") == "inbox-validate":
        return {"ok": False, "field": "mode", "expected": "helper-ft", "actual": "inbox-validate"}
    if body.get("not_for_train") is True or (
        isinstance(body.get("evidence"), dict) and body["evidence"].get("not_for_train") is True
    ):
        if body.get("smoke") is not True and body.get("mode") != "helper-ft-smoke":
            return {"ok": False, "field": "not_for_train", "expected": False, "actual": True}
    leaks = _fallback_state_leaks(body)
    if leaks:
        return {"ok": False, "field": "state.leak", "expected": "absent", "actual": leaks[:10]}
    if not body.get("evidence"):
        return {"ok": False, "field": "evidence", "expected": "present", "actual": "missing"}
    return {"ok": False, "field": "handler", "expected": "helper_ft_kickoff.py", "actual": "missing"}


def helper_ft_wsgi_app(*, launch_trainer=None):
    """WSGI app for the in-repo :8765 HELPER FT route."""
    mod = _load_helper_ft_kickoff()
    if mod is None:
        raise RuntimeError("helper_ft_kickoff.py missing")
    return mod.make_app(launch_trainer=launch_trainer)


def serve_helper_ft_kickoff(host: str = "127.0.0.1", port: int = 8765, *, launch_trainer=None) -> None:
    """Bind :8765 and run HELPER FT checks before any wired trainer launch."""
    mod = _load_helper_ft_kickoff()
    if mod is None:
        raise RuntimeError("helper_ft_kickoff.py missing")
    mod.serve(host, port, launch_trainer=launch_trainer)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--helper-ft-serve":
        serve_helper_ft_kickoff()
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queue-repo", required=True, help="git URL of the private forge queue repository")
    ap.add_argument("--workdir", default="~/forge")
    ap.add_argument("--allow", action="append", required=True, help="repo allowlist entry owner/name (repeatable)")
    ap.add_argument("--remote-base", default="https://github.com", help="base for target repo URLs (or git@github.com)")
    ap.add_argument("--hostname")
    ap.add_argument("--gpu")
    ap.add_argument("--vram-gb", type=float)
    ap.add_argument("--interval", type=float, default=60.0, help="seconds between polls")
    ap.add_argument("--once", action="store_true", help="one tick, then exit (the harmless first job)")
    ap.add_argument("--dry-run", action="store_true", help="claim but do not execute")
    args = ap.parse_args(argv)
    while True:
        try:
            out = tick(args)
        except Exception as e:
            out = {"error": e.__class__.__name__, "detail": str(e)[:300]}
        sys.stdout.write(json.dumps({"at": now_iso(), **out}, sort_keys=True) + "\n")
        sys.stdout.flush()
        if args.once:
            return 0 if "error" not in out else 1
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
