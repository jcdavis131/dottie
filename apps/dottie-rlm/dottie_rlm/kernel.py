"""PersistentKernel — the model's ONE tool.

An in-process IPython InteractiveShell whose namespace PERSISTS across calls.
No zmq, no second process: one namespace the model builds up over a session,
which is the whole point of the RLM design (`x = load()` in step 1 is still
`x` in step 9).

Deliberate scope statement, because this module executes model-authored code:
the kernel runs whatever it is handed IN THIS PROCESS. It is not a sandbox and
does not pretend to be one. The gates that bound what that code can reach live
in :mod:`dottie_rlm.policy` and are applied by the injected surface functions
(`sh`, `edit_file`, `rlm`) in :mod:`dottie_rlm.rlm` -- shell off by default,
writes confined to a workspace root, sub-agent depth and fanout capped,
secret-shaped env removed from children and redacted from output. Run this
against a workspace you would hand a new contractor, not against a machine
whose whole disk you need intact.

Timeouts: a watchdog thread raises KeyboardInterrupt inside the executing
thread via PyThreadState_SetAsyncExc. That interrupts pure-Python loops
promptly; it CANNOT interrupt a blocking C call (a socket read, time.sleep in
some builds, a native library). When the watchdog fires but the thread does not
yield, run() returns a TimeoutError result and marks the kernel `wedged` --
honest about the fact that the code may still be running, rather than
pretending the timeout was clean.
"""

from __future__ import annotations

import ctypes
import io
import threading
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TIMEOUT_S = 120.0
MAX_CAPTURE_CHARS = 20_000


def _clip(text: str, limit: int = MAX_CAPTURE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


@dataclass
class ExecResult:
    stdout: str = ""
    stderr: str = ""
    result_repr: str = ""
    error: str | None = None
    duration_s: float = 0.0
    timed_out: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "result_repr": self.result_repr,
            "error": self.error,
            "duration_s": round(self.duration_s, 4),
            "timed_out": self.timed_out,
        }


class KernelError(RuntimeError):
    """The kernel itself could not be created or driven."""


def _async_raise(thread_id: int, exc_type: type[BaseException]) -> None:
    ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(thread_id), ctypes.py_object(exc_type)
    )


@dataclass
class PersistentKernel:
    """One persistent IPython namespace.

    `run()` is serialized by a lock: two threads executing into one namespace
    would interleave unpredictably, and the RLM design already has concurrent
    children -- each child gets its OWN kernel, so contention here means a bug
    upstream, not something to paper over with silent interleaving.
    """

    max_capture_chars: int = MAX_CAPTURE_CHARS
    _shell: Any = field(default=None, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    wedged: bool = field(default=False, init=False)
    exec_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        try:
            from IPython.core.interactiveshell import InteractiveShell
        except Exception as exc:  # pragma: no cover - dependency is declared
            raise KernelError(
                f"IPython is required for the persistent kernel ({exc}). "
                f"Install it: python -m pip install ipython"
            ) from exc
        # instance(), not InteractiveShell(): the class is a SingletonConfigurable
        # and constructing a second one clears the first one's namespace, which
        # would silently wipe a live session's state. We take a private
        # namespace dict instead of sharing the singleton's user_ns.
        try:
            self._shell = InteractiveShell.instance()
        except Exception as exc:  # pragma: no cover
            raise KernelError(f"could not start an IPython shell: {exc}") from exc
        self.namespace: dict[str, Any] = {"__name__": "__dottie_rlm__"}

    # -- namespace ----------------------------------------------------------

    def inject(self, name: str, obj: Any) -> None:
        """Install `obj` in the namespace under `name` (the surface functions)."""
        if not isinstance(name, str) or not name.isidentifier():
            raise KernelError(f"{name!r} is not a valid identifier to inject")
        self.namespace[name] = obj

    def get(self, name: str, default: Any = None) -> Any:
        return self.namespace.get(name, default)

    # -- execution ----------------------------------------------------------

    def run(self, code: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> ExecResult:
        if not isinstance(code, str):
            return ExecResult(error=f"code must be a string, got {type(code).__name__}")
        if self.wedged:
            return ExecResult(
                error="KernelWedged: a previous call timed out and did not yield; "
                "this kernel's namespace can no longer be trusted. Start a new session."
            )
        with self._lock:
            return self._run_locked(code, float(timeout_s))

    def _run_locked(self, code: str, timeout_s: float) -> ExecResult:
        out_buf, err_buf = io.StringIO(), io.StringIO()
        holder: dict[str, Any] = {}
        started = time.monotonic()

        def target() -> None:
            try:
                with redirect_stdout(out_buf), redirect_stderr(err_buf):
                    holder["value"] = self._exec(code)
            except KeyboardInterrupt:
                holder["interrupted"] = True
            except BaseException as exc:
                holder["error"] = f"{type(exc).__name__}: {exc}"

        worker = threading.Thread(target=target, daemon=True, name="rlm-kernel-exec")
        worker.start()
        worker.join(timeout=timeout_s if timeout_s > 0 else None)

        timed_out = False
        if worker.is_alive():
            timed_out = True
            ident = worker.ident
            if ident is not None:
                _async_raise(ident, KeyboardInterrupt)
            # Give the interrupt a moment to land; if the thread is in a
            # blocking C call it never will, and we say so instead of lying.
            worker.join(timeout=2.0)
            if worker.is_alive():
                self.wedged = True

        duration = time.monotonic() - started
        self.exec_count += 1
        stdout = _clip(out_buf.getvalue(), self.max_capture_chars)
        stderr = _clip(err_buf.getvalue(), self.max_capture_chars)

        if timed_out:
            note = (
                " The thread did not yield (blocking call); the kernel is now "
                "marked wedged." if self.wedged else " Execution was interrupted."
            )
            return ExecResult(
                stdout=stdout,
                stderr=stderr,
                error=f"TimeoutError: code exceeded {timeout_s}s.{note}",
                duration_s=duration,
                timed_out=True,
            )
        if "error" in holder:
            return ExecResult(
                stdout=stdout, stderr=stderr, error=holder["error"], duration_s=duration
            )
        if holder.get("interrupted"):
            return ExecResult(
                stdout=stdout,
                stderr=stderr,
                error="KeyboardInterrupt: execution was interrupted",
                duration_s=duration,
            )
        value = holder.get("value")
        return ExecResult(
            stdout=stdout,
            stderr=stderr,
            result_repr="" if value is None else _clip(repr(value), 4000),
            duration_s=duration,
        )

    def _exec(self, code: str) -> Any:
        """Compile+exec in the persistent namespace, returning the last value.

        IPython's own transformer runs first so magics and `!shell` syntax
        behave as the model expects; the exec itself uses OUR namespace dict so
        the singleton shell cannot leak state between kernels.
        """
        src = code
        transform = getattr(self._shell, "transform_cell", None)
        if transform is not None:
            try:
                src = transform(code)
            except Exception:
                # A transform failure is a syntax problem in the model's code;
                # let compile() below produce the real, actionable message
                # rather than reporting an IPython internal.
                src = code
        try:
            block = compile(src, "<rlm-cell>", "exec", flags=0, dont_inherit=False)
        except SyntaxError as exc:
            raise SyntaxError(f"{exc.msg} (line {exc.lineno})") from None

        lines = src.strip().splitlines()
        last = lines[-1].strip() if lines else ""
        # Echo the last line's value like a REPL when it is a bare expression.
        if last and not last.startswith((" ", "\t")):
            try:
                expr = compile(last, "<rlm-cell-expr>", "eval")
            except SyntaxError:
                exec(block, self.namespace)  # noqa: S102 - executing model code IS the tool
                return None
            head = "\n".join(lines[:-1])
            if head:
                exec(  # noqa: S102
                    compile(head, "<rlm-cell>", "exec"), self.namespace
                )
            return eval(expr, self.namespace)  # noqa: S307 - same contract
        exec(block, self.namespace)  # noqa: S102
        return None
