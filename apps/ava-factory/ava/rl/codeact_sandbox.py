# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeActSandbox (spec 13 T13C.1) — the LLM-VM: code as the model's action substrate.

A stepwise Python interpreter with a **persistent namespace across turns**. The model's
action is a code block; `.step(code)` executes it in the retained namespace and returns an
`Observation` (stdout, last-expression value, error, wall_ms, tool_calls). Tools are bound as
callables; their calls are recorded per step.

Design — the tension resolved:
  "persistent namespace across turns" + "each step isolated in a subprocess" cannot both hold
  if every step is a *fresh* subprocess (a new interpreter has no prior namespace). So the VM is
  a **single long-lived worker subprocess** that holds the namespace and executes code blocks
  sent over a pipe. The parent enforces the per-step wall-clock cap by killing the worker's
  process group when a step exceeds it (the hung step ends the episode; later `.step()` calls
  return an error Observation instead of hanging).

Threat model (honest): this is reasonable isolation for *our own model's* code at training time
— determinism, and prevention of accidents/obvious abuse (no network sockets, no writes outside a
scratch dir, no shelling out, no fork bombs, wall/CPU/memory caps). It is **not** a hostile-code
jail; true isolation against a determined adversary needs OS-level sandboxing (containers/seccomp),
tracked as a spec-13 follow-up. Extends the single-shot in-process precedent
`ava/datagen/code_gen.py::run_sandboxed` to multi-turn with real subprocess isolation.

GPU-free, stdlib-only. POSIX (Linux container) enforces all limits; on a non-POSIX dev box the
resource/process-group limits are skipped (documented) and only the wall timeout applies.
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_POSIX = os.name == "posix"
if _POSIX:
    import resource  # top-level: never run import machinery inside a post-fork preexec_fn
STDOUT_CAP = 8192   # keep protocol lines under the POSIX pipe atomic-write limit
VALUE_CAP = 2048
DEFAULT_FREEZE_EPOCH = 1_700_000_000.0  # fixed clock so trajectories replay byte-identically


@dataclass(frozen=True)
class Observation:
    """Result of one CodeAct step. `error is None` ⇒ the block executed cleanly."""

    stdout: str = ""
    value: Optional[str] = None          # repr of the last top-level expression, truncated
    error: Optional[str] = None          # traceback / reason string, or None
    wall_ms: float = 0.0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------------------
# Worker source — runs in the isolated subprocess. Communicates via one-line
# JSON over stdout/stdin (JSON escapes newlines, so code blocks travel intact).
# ---------------------------------------------------------------------------

_WORKER_SRC = r'''
import ast, io, json, os, sys, time, random

# Private protocol channel: dup fd 1 BEFORE user code can touch it, then repoint raw fd 1 at
# /dev/null so user `os.write(1, ...)` can't inject bytes into the protocol pipe (which would
# desync framing / defeat the wall cap). All protocol writes go through the dup'd _PROTO fd.
_PROTO = os.fdopen(os.dup(1), "w", buffering=1)
try:
    _devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(_devnull, 1)
except OSError:
    pass

def _send(obj):
    _PROTO.write(json.dumps(obj) + "\n"); _PROTO.flush()

def _read():
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return json.loads(line)

STDOUT_CAP = %(stdout_cap)d
VALUE_CAP = %(value_cap)d

def _safe_repr(x, cap=VALUE_CAP):
    try:
        r = repr(x)
    except Exception as e:
        r = "<unreprable: %%s>" %% (e,)
    return r if len(r) <= cap else r[:cap] + "...<truncated>"

def _install_guards(scratch):
    import builtins, io, socket
    scratch = os.path.realpath(scratch)
    def _under_scratch(path):
        rp = os.path.realpath(path)
        return rp == scratch or rp.startswith(scratch + os.sep)
    # Guard EVERY write entry point, not just builtins.open: io.open is a distinct binding, and
    # pathlib routes through io.open — rebinding only builtins.open left both open. os.open is the
    # low-level path.
    _real_bopen, _real_ioopen, _real_osopen = builtins.open, io.open, os.open
    def _guarded_open(file, mode="r", *a, **k):
        if any(w in mode for w in ("w", "a", "x", "+")) and not _under_scratch(file):
            raise PermissionError("write outside sandbox scratch dir is blocked: %%s" %% file)
        return _real_bopen(file, mode, *a, **k)
    def _guarded_ioopen(file, mode="r", *a, **k):
        if any(w in mode for w in ("w", "a", "x", "+")) and not _under_scratch(file):
            raise PermissionError("write outside sandbox scratch dir is blocked: %%s" %% file)
        return _real_ioopen(file, mode, *a, **k)
    def _guarded_osopen(path, flags, *a, **k):
        if (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)) and not _under_scratch(path):
            raise PermissionError("write outside sandbox scratch dir is blocked: %%s" %% path)
        return _real_osopen(path, flags, *a, **k)
    builtins.open = _guarded_open
    io.open = _guarded_ioopen
    os.open = _guarded_osopen
    def _blocked(*a, **k):
        raise PermissionError("network/process access is blocked in the CodeAct sandbox")
    socket.socket = _blocked
    for name in ("system", "popen", "fork", "forkpty", "spawnl", "spawnv", "execv", "execvp"):
        if hasattr(os, name):
            setattr(os, name, _blocked)

_TOOL_CALLS = []
MAX_TOOL_CALLS = 256  # bound the result line so a call-spamming step can't produce a huge frame
def _wrap_tool(name, fn):
    def w(*a, **k):
        if len(_TOOL_CALLS) < MAX_TOOL_CALLS:
            _TOOL_CALLS.append({"tool": name, "args": [_safe_repr(x, 200) for x in a],
                                "kwargs": {kk: _safe_repr(vv, 200) for kk, vv in k.items()}})
        return fn(*a, **k)
    return w

def main():
    init = _read()
    if init.get("type") != "init":
        _send({"type": "error", "error": "expected init"}); return
    random.seed(init["seed"])
    try:
        import numpy as _np  # optional; seed if present for determinism
        _np.random.seed(init["seed"] & 0x7FFFFFFF)
    except Exception:
        pass
    scratch = init["scratch"]
    _install_guards(scratch)

    # Frozen clock tool so time-dependent trajectories replay identically.
    freeze = float(init.get("freeze_epoch", 0.0))
    def get_clock():
        return freeze
    ns = {"__name__": "ava_codeact_vm", "get_clock": _wrap_tool("get_clock", get_clock)}

    # Bind tools: importable (module:qualname) and source-defined.
    for tname, spec in (init.get("import_tools") or {}).items():
        try:
            mod, _, qual = spec.partition(":")
            obj = __import__(mod, fromlist=["_"])
            for part in qual.split("."):
                obj = getattr(obj, part)
            ns[tname] = _wrap_tool(tname, obj)
        except Exception as e:
            _send({"type": "error", "error": "tool import failed for %%s: %%s" %% (tname, e)}); return
    for tname, src in (init.get("tool_sources") or {}).items():
        tns = {}
        try:
            exec(src, tns)
            fn = tns.get(tname)
            if not callable(fn):
                raise ValueError("source did not define callable %%r" %% tname)
            ns[tname] = _wrap_tool(tname, fn)
        except Exception as e:
            _send({"type": "error", "error": "tool source failed for %%s: %%s" %% (tname, e)}); return

    _send({"type": "ready"})

    while True:
        try:
            msg = _read()
        except EOFError:
            break
        if msg.get("type") == "close":
            break
        if msg.get("type") != "step":
            _send({"type": "result", "stdout": "", "value": None,
                   "error": "bad message", "wall_ms": 0.0, "tool_calls": []}); continue

        code = msg["code"]
        _TOOL_CALLS.clear()
        buf = io.StringIO()
        real_stdout = sys.stdout
        value = None
        error = None
        t0 = time.perf_counter()
        try:
            tree = ast.parse(code, mode="exec")
            last_expr = None
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                last_expr = tree.body.pop()
            sys.stdout = buf
            exec(compile(tree, "<codeact>", "exec"), ns)
            if last_expr is not None:
                v = eval(compile(ast.Expression(last_expr.value), "<codeact>", "eval"), ns)
                if v is not None:
                    value = _safe_repr(v)
        except BaseException as e:
            import traceback
            error = "".join(traceback.format_exception_only(type(e), e)).strip()
        finally:
            sys.stdout = real_stdout
        wall_ms = (time.perf_counter() - t0) * 1000.0
        out = buf.getvalue()
        if len(out) > STDOUT_CAP:
            out = out[:STDOUT_CAP] + "...<truncated>"
        _send({"type": "result", "stdout": out, "value": value, "error": error,
               "wall_ms": round(wall_ms, 3), "tool_calls": list(_TOOL_CALLS)})

main()
''' % {"stdout_cap": STDOUT_CAP, "value_cap": VALUE_CAP}


def _preexec(mem_mb: int, cpu_s: int):  # pragma: no cover - POSIX child setup, exercised via subprocess
    """Runs in the child between fork and exec: ONLY async-signal-safe calls (no import, no alloc —
    `resource` is imported at module top). New process group + hard resource caps."""
    os.setsid()  # own process group → parent can kill the whole tree on timeout
    mem = mem_mb * 1024 * 1024
    for res, lim in (
        (resource.RLIMIT_AS, mem),
        (resource.RLIMIT_CPU, cpu_s),          # SIGXCPU backstop for CPU-bound infinite loops
        (resource.RLIMIT_NPROC, 64),           # blunt the fork bomb even if os.fork is re-bound
        (resource.RLIMIT_FSIZE, 64 * 1024 * 1024),
    ):
        try:
            soft, hard = resource.getrlimit(res)
            resource.setrlimit(res, (lim, hard if hard != resource.RLIM_INFINITY else lim))
        except (ValueError, OSError):
            pass


class Sandbox:
    """Persistent multi-turn CodeAct interpreter (the LLM-VM).

    Args:
        tools: name -> importable callable (resolved to module:qualname and re-imported in the
               worker; lambdas/closures aren't importable — use `tool_sources` for those).
        tool_sources: name -> source string that defines a callable of that name.
        timeout_s: per-step wall-clock cap; a step exceeding it kills the VM (episode ends).
        mem_mb / max_steps: memory cap and hard step count.
        seed: determinism seed (also fixes the worker's PYTHONHASHSEED so repr ordering is stable).
        scratch_dir: the only writable directory; a temp dir is created if omitted.
        freeze_epoch: value returned by the injected `get_clock()` tool.

    A bound `get_clock()` tool is always available (returns `freeze_epoch`).
    """

    def __init__(
        self,
        tools: Optional[Dict[str, Callable]] = None,
        *,
        tool_sources: Optional[Dict[str, str]] = None,
        timeout_s: float = 3.0,
        mem_mb: int = 512,
        max_steps: int = 32,
        seed: int = 0,
        scratch_dir: Optional[str] = None,
        freeze_epoch: float = DEFAULT_FREEZE_EPOCH,
    ):
        self.timeout_s = float(timeout_s)
        self.mem_mb = int(mem_mb)
        self.max_steps = int(max_steps)
        self.seed = int(seed)
        self.freeze_epoch = float(freeze_epoch)
        self._import_tools = self._resolve_import_tools(tools or {})
        self._tool_sources = dict(tool_sources or {})
        self._steps_used = 0
        self._alive = False
        self._dead_reason: Optional[str] = None
        self._proc: Optional[subprocess.Popen] = None

        import tempfile
        self._owns_scratch = scratch_dir is None
        self._scratch = Path(scratch_dir) if scratch_dir else Path(tempfile.mkdtemp(prefix="codeact-"))
        self._scratch.mkdir(parents=True, exist_ok=True)
        self._start()

    # -- construction helpers -----------------------------------------------------
    @staticmethod
    def _resolve_import_tools(tools: Dict[str, Callable]) -> Dict[str, str]:
        specs: Dict[str, str] = {}
        for name, fn in tools.items():
            mod = getattr(fn, "__module__", None)
            qual = getattr(fn, "__qualname__", None)
            if not mod or not qual or "<locals>" in qual or mod == "__main__":
                raise ValueError(
                    f"tool {name!r} is not importable (module={mod}, qualname={qual}); "
                    "pass it via tool_sources= instead of tools="
                )
            specs[name] = f"{mod}:{qual}"
        return specs

    def _start(self) -> None:
        self._rbuf = b""  # raw-fd read buffer for _read_line
        env = {
            "PYTHONHASHSEED": str(self.seed),   # stable set/hash-repr ordering across replays
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LC_ALL": "C", "LANG": "C",
        }
        cpu_s = int(self.timeout_s) + 2
        popen_kw: Dict[str, Any] = dict(
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=str(self._scratch), env=env, text=True,
        )
        if _POSIX:
            popen_kw["preexec_fn"] = lambda: _preexec(self.mem_mb, cpu_s)
        self._proc = subprocess.Popen([sys.executable, "-S", "-c", _WORKER_SRC], **popen_kw)
        self._send({
            "type": "init", "seed": self.seed, "scratch": str(self._scratch.resolve()),
            "freeze_epoch": self.freeze_epoch,
            "import_tools": self._import_tools, "tool_sources": self._tool_sources,
        })
        ready = self._read_line(timeout=max(5.0, self.timeout_s))
        if not ready or ready.get("type") != "ready":
            reason = (ready or {}).get("error", "worker failed to start")
            self._kill(f"init failed: {reason}")
            raise RuntimeError(f"CodeAct sandbox init failed: {reason}")
        self._alive = True

    # -- io -----------------------------------------------------------------------
    def _send(self, obj: Dict[str, Any]) -> None:
        assert self._proc and self._proc.stdin
        try:
            self._proc.stdin.write(json.dumps(obj) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            self._alive = False

    def _read_line(self, timeout: float) -> Optional[Dict[str, Any]]:
        """Read one JSON protocol line, enforcing `timeout` across the WHOLE read.

        Reads the raw fd in a deadline loop (not select()+buffered-readline, which only gated the
        first byte — a slow or oversized line could then block past the wall cap). Returns None on
        deadline, EOF, or a malformed line; the caller kills the VM on None during a step.
        """
        assert self._proc and self._proc.stdout
        fd = self._proc.stdout.fileno()
        deadline = time.monotonic() + timeout
        while True:
            nl = self._rbuf.find(b"\n")
            if nl != -1:
                line, self._rbuf = self._rbuf[:nl], self._rbuf[nl + 1:]
                try:
                    return json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None  # deadline reached mid-line — the step overran its wall cap
            if _POSIX:
                r, _, _ = select.select([fd], [], [], remaining)
                if not r:
                    return None
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                return None
            if not chunk:
                return None  # worker died / EOF
            self._rbuf += chunk

    # -- public API ---------------------------------------------------------------
    def step(self, code: str) -> Observation:
        """Execute `code` in the persistent VM namespace and return an Observation.

        Never raises on user-code errors, timeouts, or a dead VM — those are reported in
        `Observation.error` so the RL rollout can append the observation and continue.
        """
        if not self._alive:
            return Observation(error=f"sandbox not alive: {self._dead_reason or 'closed'}")
        if self._steps_used >= self.max_steps:
            return Observation(error=f"max_steps ({self.max_steps}) exceeded")
        self._steps_used += 1

        self._send({"type": "step", "code": code})
        if not self._alive:
            return Observation(error="sandbox pipe broken while sending step")
        resp = self._read_line(timeout=self.timeout_s)
        if resp is None:
            # timeout or worker death → the step hung or crashed; kill the VM group.
            self._kill(f"step exceeded {self.timeout_s}s wall cap or worker died")
            return Observation(error=f"step timed out after {self.timeout_s}s (VM terminated)")
        if resp.get("type") != "result":
            return Observation(error=f"protocol error: {resp}")
        return Observation(
            stdout=resp.get("stdout", ""), value=resp.get("value"),
            error=resp.get("error"), wall_ms=float(resp.get("wall_ms", 0.0)),
            tool_calls=list(resp.get("tool_calls", [])),
        )

    @property
    def alive(self) -> bool:
        return self._alive

    @property
    def steps_used(self) -> int:
        return self._steps_used

    @property
    def scratch_dir(self) -> str:
        return str(self._scratch)

    def _close_pipes(self) -> None:
        # Release the two parent-side pipe fds immediately, not at Popen finalization — a
        # pooled/retained Sandbox would otherwise leak 2 fds each until GC.
        if self._proc:
            for f in (self._proc.stdin, self._proc.stdout):
                try:
                    if f:
                        f.close()
                except Exception:
                    pass

    def _reap_zombies(self) -> None:
        # killpg SIGKILLs grandchildren but only the direct child is auto-reaped; if the trainer is
        # a subreaper (PID 1 in a container), reparented grandchildren become zombies. Drain them.
        if not _POSIX:
            return
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except (ChildProcessError, OSError):
                break
            if pid == 0:
                break

    def _kill(self, reason: str) -> None:
        self._alive = False
        self._dead_reason = reason
        if not self._proc:
            return
        try:
            if _POSIX:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            else:  # pragma: no cover
                self._proc.kill()
        except (ProcessLookupError, OSError):
            pass
        try:
            self._proc.wait(timeout=2)
        except Exception:
            pass
        self._reap_zombies()
        self._close_pipes()

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            if self._alive:
                self._send({"type": "close"})
                try:
                    self._proc.wait(timeout=1)
                except Exception:
                    pass
            self._kill("closed")
        self._alive = False
        self._close_pipes()
        if self._owns_scratch:
            import shutil
            shutil.rmtree(self._scratch, ignore_errors=True)

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
