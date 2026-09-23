"""Exact process launch, identity, cancellation, and host resource helpers."""

from __future__ import annotations

import contextlib
import ctypes
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from factory.config import FactoryError

if TYPE_CHECKING:
    from collections.abc import Iterator

_WINDOWS_JOBS: dict[tuple[int, str], int] = {}
_WINDOWS_JOBS_LOCK = threading.Lock()


def available_ram_mb() -> int | None:
    if os.name != "nt":
        try:
            pages = os.sysconf("SC_AVPHYS_PAGES")
            size = os.sysconf("SC_PAGE_SIZE")
            return int(pages * size / (1024 * 1024))
        except (AttributeError, OSError, ValueError):
            return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("load", ctypes.c_ulong),
            ("total", ctypes.c_ulonglong),
            ("available", ctypes.c_ulonglong),
            ("total_page", ctypes.c_ulonglong),
            ("available_page", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.available / (1024 * 1024))


@contextlib.contextmanager
def _keep_awake() -> Iterator[None]:
    previous: int | None = None
    if os.name == "nt":
        continuous = 0x80000000
        system_required = 0x00000001
        previous = ctypes.windll.kernel32.SetThreadExecutionState(
            continuous | system_required
        )
        if not previous:
            raise FactoryError("Windows keep-awake request failed")
    try:
        yield
    finally:
        if os.name == "nt" and previous:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


def run_capture(
    argv: tuple[str, ...],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    ledger: Any,
    mission_id: str,
    attempt_id: str,
    phase: str,
) -> tuple[int, float]:
    started = time.monotonic()
    process: subprocess.Popen[Any] | None = None
    identity: str | None = None
    recorded = False
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr:
        try:
            with _keep_awake():
                popen_kwargs: dict[str, Any] = {}
                if os.name == "nt":
                    popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    popen_kwargs["start_new_session"] = True
                process = subprocess.Popen(
                    list(argv),
                    cwd=cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    shell=False,
                    **popen_kwargs,
                )
                identity = process_identity(process.pid)
                if identity is None:
                    raise FactoryError("could not establish launched process identity")
                _retain_windows_job(process, identity)
                recorded = ledger.register_process(
                    mission_id,
                    attempt_id,
                    phase,
                    process.pid,
                    identity,
                )
                if not recorded:
                    _terminate_launched(process, identity)
                    return process.returncode, time.monotonic() - started
                return_code = process.wait()
        except BaseException:
            if process is not None and process.poll() is None:
                _terminate_launched(process, identity)
            raise
        finally:
            if process is not None and process.poll() is None:
                _terminate_launched(process, identity)
            if recorded:
                ledger.clear_process(attempt_id, process.pid, identity)
            if process is not None and identity is not None:
                _release_windows_job(process.pid, identity)
    return return_code, time.monotonic() - started


def _terminate_launched(
    process: subprocess.Popen[Any], identity: str | None
) -> None:
    if process.poll() is not None:
        return
    if identity is not None:
        terminate_process_tree(process.pid, identity)
    elif os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _retain_windows_job(
    process: subprocess.Popen[Any], identity: str
) -> None:
    if os.name != "nt":
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return
    if not kernel32.AssignProcessToJobObject(
        job, ctypes.c_void_p(process._handle)
    ):
        kernel32.CloseHandle(job)
        return
    with _WINDOWS_JOBS_LOCK:
        _WINDOWS_JOBS[(process.pid, identity)] = int(job)


def _release_windows_job(pid: int, identity: str) -> None:
    if os.name != "nt":
        return
    with _WINDOWS_JOBS_LOCK:
        job = _WINDOWS_JOBS.pop((pid, identity), None)
    if job:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(job))


def process_identity(pid: int) -> str | None:
    if os.name != "nt":
        stat = Path(f"/proc/{pid}/stat")
        if stat.is_file():
            try:
                return stat.read_text(encoding="ascii").split()[21]
            except (OSError, IndexError):
                return None
        probe = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        return probe.stdout.strip() or None
    process_query_limited_information = 0x1000
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return None
    creation = ctypes.c_ulonglong()
    exit_time = ctypes.c_ulonglong()
    kernel = ctypes.c_ulonglong()
    user = ctypes.c_ulonglong()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        return str(creation.value)
    finally:
        kernel32.CloseHandle(handle)


def terminate_process_tree(pid: int, expected_identity: str) -> None:
    if process_identity(pid) != expected_identity:
        raise FactoryError("refusing cancellation: recorded process is no longer exact")
    if os.name == "nt":
        with _WINDOWS_JOBS_LOCK:
            job = _WINDOWS_JOBS.get((pid, expected_identity))
        if job:
            if not ctypes.windll.kernel32.TerminateJobObject(
                ctypes.c_void_p(job), 1
            ):
                raise FactoryError("Windows Job Object cancellation failed")
            return
        if process_identity(pid) != expected_identity:
            raise FactoryError(
                "refusing cancellation: process identity changed before taskkill"
            )
        terminated = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        if terminated.returncode != 0 and process_identity(pid) == expected_identity:
            raise FactoryError(
                f"process-tree cancellation failed: {terminated.stderr.strip()}"
            )
        return
    if os.getpgid(pid) != pid:
        raise FactoryError("refusing cancellation: process group identity is unsafe")
    os.killpg(pid, signal.SIGTERM)
