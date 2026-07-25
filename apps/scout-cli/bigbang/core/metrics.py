# Solo personal project, no connection to employer, built with public/free-tier only
"""Metrics — host telemetry core (openswap #15: Datadog Infrastructure Monitoring).

Datadog sells two things: an agent that reads the box, and a hosted time series
you rent to keep the readings. This adapter deletes both. The agent is replaced
by three stdlib measurements (shutil.disk_usage, ctypes GlobalMemoryStatusEx /
/proc/meminfo, and a Windows performance counter read through typeperf or
Get-Counter); the hosted series is replaced by an append-only JSONL log plus a
sqlite3 rollup table on this box. There is no API key, no intake endpoint, and
the plugin manifest disables the network axis entirely, so "no telemetry left
this machine" is architectural rather than a ToS promise.

Provenance is the invariant that makes the numbers usable a month later, so it
is enforced rather than documented: reading() REFUSES to build a row that does
not name how it was measured (`how`, e.g. the exact typeperf argv) and which
mechanism produced it (`source`, one of a closed set — stdlib / ctypes / procfs
/ counter / unsupported). Aggregation does not launder that away either: every
rollup row carries the distinct `how` strings of the samples behind it, so a
mean can always be traced back to the API that produced its inputs.

The second invariant is that a failed measurement stays visible. A reading has
EITHER a numeric value OR an error, never both and never neither, and rollups
count error rows separately from the min/max/mean they exclude. A host that
could not be measured must not average out to a healthy one — that is the
failure mode a monitoring adapter cannot be allowed to have.

Real I/O boundaries are injectable, which is what keeps the suite offline and
deterministic: `sample_cpu` takes a `runner` callable (the plugin CLI supplies
the real subprocess; tests supply canned stdout — the certmon `_fetch` pattern),
`sample_memory` takes a `system` name and an optional `probe`, and every `ts` is
an explicit argument. Disk and /proc parsing are pure enough to test for real.

Platform honesty: the counter backends are Windows-only, so on Linux/macOS
`cpu.busy_pct` records source="unsupported" with the reason instead of silently
disappearing from the series. That is scope honesty, not degradation — disk and
memory still collect everywhere.

Extension points:
- More counters: typeperf_argv/powershell_argv take any counter path, and
  parse_typeperf/parse_cooked_value are pure — adding \\Memory\\Pages/sec is a
  spec entry, not new plumbing.
- Thresholds are parameters of to_diagnostics(), which emits the openswap
  diagnostic schema, so `--fail-on` gates a disk-full box exactly like a prose
  lint finding.
- The JSONL is the durable record and sqlite is derived: read_jsonl() replays
  rows in the same shape record_samples() takes, so a lost ledger is rebuildable
  from the log rather than from a vendor's retention window.
"""

from __future__ import annotations

import csv
import ctypes
import io
import json
import math
import os
import platform
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bigbang.core import openswap

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

# the append-only record and the derived store, beside the family's other
# ledgers (.scout/uptime.db is the #2 convention)
SAMPLES_REL = Path(".scout") / "metrics.jsonl"
DB_REL = Path(".scout") / "metrics.db"
SCHEMA_VERSION = "1"

# ---- provenance vocabulary (closed sets; reading() rejects anything else) ----
SRC_STDLIB = "stdlib"  # shutil.disk_usage, os.cpu_count
SRC_CTYPES = "ctypes"  # GlobalMemoryStatusEx via ctypes.windll
SRC_PROCFS = "procfs"  # /proc/meminfo
SRC_COUNTER = "counter"  # typeperf / Get-Counter subprocess
SRC_UNSUPPORTED = "unsupported"  # no mechanism exists on this platform
SOURCES = (SRC_STDLIB, SRC_CTYPES, SRC_PROCFS, SRC_COUNTER, SRC_UNSUPPORTED)

UNIT_BYTES = "bytes"
UNIT_PERCENT = "percent"
UNIT_COUNT = "count"
UNITS = (UNIT_BYTES, UNIT_PERCENT, UNIT_COUNT)

METRIC_DISK_USED_PCT = "disk.used_pct"
METRIC_DISK_FREE = "disk.free_bytes"
METRIC_DISK_TOTAL = "disk.total_bytes"
METRIC_MEM_USED_PCT = "mem.used_pct"
METRIC_MEM_AVAIL = "mem.available_bytes"
METRIC_MEM_TOTAL = "mem.total_bytes"
METRIC_CPU_BUSY_PCT = "cpu.busy_pct"
METRIC_CPU_LOGICAL = "cpu.logical"

SCOPE_HOST = "host"  # scope for machine-wide metrics; disk uses the mount path

# Windows performance counter for total CPU busy time. English counter names are
# what typeperf accepts on an English install; a localized box would need its
# own counter string, which is why the counter is a parameter everywhere.
CPU_COUNTER = r"\Processor(_Total)\% Processor Time"

DEFAULT_WINDOW_S = 300.0
DISK_WARN_PCT = 85.0
DISK_ERROR_PCT = 95.0
MEM_WARN_PCT = 90.0
MEM_ERROR_PCT = 97.0

_FLOAT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_MEMINFO_RE = re.compile(r"^(?P<key>[A-Za-z_()]+):\s+(?P<val>\d+)(?:\s+(?P<unit>kB))?$")


# ---- the row constructor: provenance is not optional -------------------------


def reading(
    *,
    ts: float,
    metric: str,
    scope: str,
    unit: str,
    how: str,
    source: str,
    value: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """One measurement, stamped with how it was taken. Raises on a dishonest row.

    Four rules, all enforced here because a metrics store that accepts
    unlabelled numbers is worthless six weeks later:
      * `how` must be non-empty — even an unsupported reading says what it tried.
      * `source` must name a mechanism from SOURCES (no free-text provenance).
      * `unit` must be one of UNITS (a percent and a byte count cannot share a
        rollup).
      * exactly one of value/error — a row with both hides the failure, a row
        with neither is a placeholder pretending to be data.
    """
    if not metric or not str(metric).strip():
        raise ValueError("reading needs a metric name")
    if not how or not str(how).strip():
        raise ValueError(f"reading {metric!r} must record how it was measured")
    if source not in SOURCES:
        raise ValueError(f"reading {metric!r}: source must be one of {SOURCES}, got {source!r}")
    if unit not in UNITS:
        raise ValueError(f"reading {metric!r}: unit must be one of {UNITS}, got {unit!r}")
    if value is None and error is None:
        raise ValueError(f"reading {metric!r}: needs a value or an error, got neither")
    if value is not None and error is not None:
        raise ValueError(
            f"reading {metric!r}: has both a value and an error — a failed "
            "measurement must not carry a number"
        )
    return {
        "ts": float(ts),
        "metric": str(metric),
        "scope": str(scope),
        "value": None if value is None else float(value),
        "unit": unit,
        "how": str(how),
        "source": source,
        "error": None if error is None else str(error),
    }


def stamp_host(rows: Iterable[dict[str, Any]], host: str) -> list[dict[str, Any]]:
    """Attach the measuring box to each row (mutates and returns the list).

    Kept separate from reading() so the samplers stay host-agnostic, but it is
    NOT optional: record_samples() refuses unstamped rows, because a series that
    forgets which machine it came from cannot be rolled up truthfully.
    """
    if not host or not str(host).strip():
        raise ValueError("host must be a non-empty name")
    out = []
    for r in rows:
        r["host"] = str(host)
        out.append(r)
    return out


# ---- disk: shutil.disk_usage -------------------------------------------------


def default_disk_paths() -> list[str]:
    """The filesystem this checkout actually lives on — derived, never hardcoded.

    Windows gives "C:\\" via the anchor; POSIX gives "/". A literal path here
    would be the self-containedness bug the repo audit exists to catch.
    """
    cwd = Path.cwd()
    return [str(Path(cwd.anchor)) if cwd.anchor else str(cwd)]


def sample_disk(paths: Sequence[str], *, ts: float) -> list[dict[str, Any]]:
    """used_pct / free / total per path, straight from shutil.disk_usage.

    used_pct is computed from used+total (not free) so a filesystem reserving
    blocks for root still reports the percentage the OS itself reports. An
    unreadable path yields one error reading per metric rather than vanishing.
    """
    rows: list[dict[str, Any]] = []
    for raw in paths:
        scope = str(raw)
        how = f"shutil.disk_usage({scope!r})"
        try:
            du = shutil.disk_usage(scope)
        except OSError as e:
            err = f"{type(e).__name__}: {e}"
            for metric, unit in (
                (METRIC_DISK_USED_PCT, UNIT_PERCENT),
                (METRIC_DISK_FREE, UNIT_BYTES),
                (METRIC_DISK_TOTAL, UNIT_BYTES),
            ):
                rows.append(
                    reading(
                        ts=ts,
                        metric=metric,
                        scope=scope,
                        unit=unit,
                        how=how,
                        source=SRC_STDLIB,
                        error=err,
                    )
                )
            continue
        pct = None if du.total <= 0 else round(100.0 * du.used / du.total, 2)
        rows.append(
            reading(
                ts=ts,
                metric=METRIC_DISK_USED_PCT,
                scope=scope,
                unit=UNIT_PERCENT,
                how=how,
                source=SRC_STDLIB,
                value=pct,
                error=None if pct is not None else "disk reports total=0 bytes",
            )
        )
        rows.append(
            reading(
                ts=ts,
                metric=METRIC_DISK_FREE,
                scope=scope,
                unit=UNIT_BYTES,
                how=how,
                source=SRC_STDLIB,
                value=float(du.free),
            )
        )
        rows.append(
            reading(
                ts=ts,
                metric=METRIC_DISK_TOTAL,
                scope=scope,
                unit=UNIT_BYTES,
                how=how,
                source=SRC_STDLIB,
                value=float(du.total),
            )
        )
    return rows


# ---- memory: ctypes on Windows, /proc/meminfo on Linux -----------------------


class MEMORYSTATUSEX(ctypes.Structure):
    """The Win32 MEMORYSTATUSEX layout GlobalMemoryStatusEx fills in.

    Declared at module scope (the ctypes idiom) but only ever instantiated on
    the Windows branch — importing this module on Linux touches nothing here.
    """

    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


HOW_WINDOWS_MEM = "ctypes.windll.kernel32.GlobalMemoryStatusEx"
HOW_PROCFS_MEM = "read /proc/meminfo (MemTotal, MemAvailable)"


def memory_windows() -> dict[str, Any]:
    """Physical memory via GlobalMemoryStatusEx. Raises OSError off Windows.

    used_pct comes from the kernel's own dwMemoryLoad rather than being derived
    from total-avail: it is the number Task Manager shows, so the series matches
    what a human sees when they go looking.
    """
    if not hasattr(ctypes, "windll"):
        raise OSError("ctypes.windll is Windows-only")
    buf = MEMORYSTATUSEX()
    buf.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(buf)):
        raise OSError(f"GlobalMemoryStatusEx failed, GetLastError={ctypes.get_last_error()}")
    return {
        "total_bytes": float(buf.ullTotalPhys),
        "available_bytes": float(buf.ullAvailPhys),
        "used_pct": float(buf.dwMemoryLoad),
        "how": HOW_WINDOWS_MEM,
        "source": SRC_CTYPES,
    }


def parse_meminfo(text: str) -> dict[str, float]:
    """/proc/meminfo -> {key: bytes}. Unit-aware (kB lines are scaled by 1024)."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        m = _MEMINFO_RE.match(line.strip())
        if not m:
            continue
        val = float(m.group("val"))
        out[m.group("key")] = val * 1024.0 if m.group("unit") == "kB" else val
    return out


def memory_procfs(text: str | None = None) -> dict[str, Any]:
    """Physical memory from /proc/meminfo (or injected text). Raises OSError.

    MemAvailable is the kernel's own estimate of what a workload can claim
    without swapping; MemFree would understate it badly on any box with a page
    cache, which is why an old free-based reading is not offered as a fallback.
    """
    if text is None:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
    info = parse_meminfo(text)
    total = info.get("MemTotal")
    avail = info.get("MemAvailable")
    if not total or avail is None:
        raise OSError("/proc/meminfo has no usable MemTotal/MemAvailable pair")
    return {
        "total_bytes": total,
        "available_bytes": avail,
        "used_pct": round(100.0 * (total - avail) / total, 2),
        "how": HOW_PROCFS_MEM,
        "source": SRC_PROCFS,
    }


def sample_memory(
    *,
    ts: float,
    system: str | None = None,
    probe: Callable[[], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """used_pct / available / total for physical memory on this platform.

    `system` (default platform.system()) selects the mechanism and `probe`
    overrides it outright, so every branch — Windows ctypes, Linux procfs, and
    the unsupported platform — is reachable from any test host. An unknown
    platform records source="unsupported" with the reason, never a zero.
    """
    system = platform.system() if system is None else system
    if probe is None:
        if system == "Windows":
            probe = memory_windows
        elif system == "Linux":
            probe = memory_procfs
    if probe is None:
        how = f"{HOW_WINDOWS_MEM} | {HOW_PROCFS_MEM}"
        err = f"no supported physical-memory API on {system!r}"
        return [
            reading(
                ts=ts,
                metric=m,
                scope=SCOPE_HOST,
                unit=u,
                how=how,
                source=SRC_UNSUPPORTED,
                error=err,
            )
            for m, u in (
                (METRIC_MEM_USED_PCT, UNIT_PERCENT),
                (METRIC_MEM_AVAIL, UNIT_BYTES),
                (METRIC_MEM_TOTAL, UNIT_BYTES),
            )
        ]
    try:
        got = probe()
    except (OSError, ValueError) as e:
        how = HOW_WINDOWS_MEM if system == "Windows" else HOW_PROCFS_MEM
        src = SRC_CTYPES if system == "Windows" else SRC_PROCFS
        err = f"{type(e).__name__}: {e}"
        return [
            reading(
                ts=ts, metric=m, scope=SCOPE_HOST, unit=u, how=how, source=src, error=err
            )
            for m, u in (
                (METRIC_MEM_USED_PCT, UNIT_PERCENT),
                (METRIC_MEM_AVAIL, UNIT_BYTES),
                (METRIC_MEM_TOTAL, UNIT_BYTES),
            )
        ]
    how, src = got["how"], got["source"]
    return [
        reading(
            ts=ts,
            metric=METRIC_MEM_USED_PCT,
            scope=SCOPE_HOST,
            unit=UNIT_PERCENT,
            how=how,
            source=src,
            value=got["used_pct"],
        ),
        reading(
            ts=ts,
            metric=METRIC_MEM_AVAIL,
            scope=SCOPE_HOST,
            unit=UNIT_BYTES,
            how=how,
            source=src,
            value=got["available_bytes"],
        ),
        reading(
            ts=ts,
            metric=METRIC_MEM_TOTAL,
            scope=SCOPE_HOST,
            unit=UNIT_BYTES,
            how=how,
            source=src,
            value=got["total_bytes"],
        ),
    ]


# ---- cpu: performance counters through an injected subprocess runner --------


def typeperf_argv(counter: str, *, path: str = "typeperf", samples: int = 1) -> list[str]:
    """`typeperf <counter> -sc N` — one CSV sample per second, then exit."""
    return [path, counter, "-sc", str(int(samples))]


def powershell_argv(counter: str, *, path: str = "powershell", samples: int = 1) -> list[str]:
    """Get-Counter reduced to a bare CookedValue, with no profile loaded.

    -NoProfile/-NonInteractive matter for a metrics probe: a user profile could
    print banners into stdout (breaking the parse) or block on a prompt.
    """
    script = (
        f"(Get-Counter -Counter '{counter}' -MaxSamples {int(samples)})"
        ".CounterSamples[0].CookedValue"
    )
    return [path, "-NoProfile", "-NonInteractive", "-Command", script]


def parse_typeperf(text: str) -> float | None:
    """Last value out of typeperf's CSV. None when there is no data row.

    typeperf writes a quoted header row, then one row per sample, then chatter
    ("Exiting, please wait...", "The command completed successfully.") which is
    NOT CSV — so rows are taken only from quoted lines with >= 2 fields whose
    first field is not the PDH header, and the newest wins.
    """
    value: float | None = None
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or not row[0] or "(PDH-CSV" in row[0]:
            continue
        try:
            value = float(row[1])
        except ValueError:
            continue
    return value


def parse_cooked_value(text: str) -> float | None:
    """First float in Get-Counter's output. None when nothing numeric came back.

    Deliberately lenient about surrounding whitespace/newlines, deliberately
    NOT lenient about locale: a comma decimal separator parses as no value
    rather than as a wrong one.
    """
    for line in text.splitlines():
        m = _FLOAT_RE.search(line.strip())
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                continue
    return None


def counter_plan(
    *, counter: str = CPU_COUNTER, which: Callable[[str], str | None] = shutil.which
) -> list[dict[str, Any]]:
    """Which counter backends exist on this PATH, best first.

    typeperf is preferred: it is a single native exe with no shell to start.
    Get-Counter is the fallback because powershell startup dominates the read.
    `which` is injectable so tests can model a box with neither, or only one.
    """
    plan: list[dict[str, Any]] = []
    tp = which("typeperf")
    if tp:
        plan.append({"kind": "typeperf", "argv": typeperf_argv(counter, path=tp)})
    ps = which("powershell")
    if ps:
        plan.append({"kind": "get-counter", "argv": powershell_argv(counter, path=ps)})
    return plan


_PARSERS: dict[str, Callable[[str], float | None]] = {
    "typeperf": parse_typeperf,
    "get-counter": parse_cooked_value,
}


def sample_cpu(
    *,
    ts: float,
    runner: Callable[[list[str]], dict[str, Any]],
    plan: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """cpu.logical (stdlib) + cpu.busy_pct (first counter backend that answers).

    `runner(argv) -> {"returncode": int, "stdout": str, "stderr": str}` is the
    only real I/O and it is injected — the CLI passes subprocess.run, tests pass
    canned output, so the suite never spawns a process. A backend that exits
    nonzero, times out, or prints something unparseable is TRIED AND RECORDED,
    then the next one runs; if none answers the row keeps the error instead of a
    zero, because 0% busy and "could not measure" are opposite facts.
    """
    cpus = os.cpu_count()
    rows = [
        reading(
            ts=ts,
            metric=METRIC_CPU_LOGICAL,
            scope=SCOPE_HOST,
            unit=UNIT_COUNT,
            how="os.cpu_count()",
            source=SRC_STDLIB,
            value=None if cpus is None else float(cpus),
            error=None if cpus is not None else "os.cpu_count() returned None",
        )
    ]
    plan = counter_plan() if plan is None else plan
    if not plan:
        rows.append(
            reading(
                ts=ts,
                metric=METRIC_CPU_BUSY_PCT,
                scope=SCOPE_HOST,
                unit=UNIT_PERCENT,
                how="typeperf | powershell Get-Counter",
                source=SRC_UNSUPPORTED,
                error="no performance-counter backend on PATH (Windows-only tools)",
            )
        )
        return rows
    problems: list[str] = []
    for step in plan:
        argv = list(step["argv"])
        how = " ".join(argv)
        try:
            got = runner(argv)
        except Exception as e:  # a runner blowing up is data, not a crash
            problems.append(f"{step['kind']}: {type(e).__name__}: {e}")
            continue
        rc = int(got.get("returncode", 1))
        out = got.get("stdout") or ""
        if rc != 0:
            tail = (got.get("stderr") or out or "").strip().splitlines()
            problems.append(f"{step['kind']}: exit {rc} {tail[0] if tail else ''}".strip())
            continue
        val = _PARSERS[step["kind"]](out)
        if val is None:
            problems.append(f"{step['kind']}: no numeric sample in output")
            continue
        rows.append(
            reading(
                ts=ts,
                metric=METRIC_CPU_BUSY_PCT,
                scope=SCOPE_HOST,
                unit=UNIT_PERCENT,
                how=how,
                source=SRC_COUNTER,
                value=round(val, 3),
            )
        )
        return rows
    rows.append(
        reading(
            ts=ts,
            metric=METRIC_CPU_BUSY_PCT,
            scope=SCOPE_HOST,
            unit=UNIT_PERCENT,
            how=" | ".join(" ".join(s["argv"]) for s in plan),
            source=SRC_COUNTER,
            error="; ".join(problems) or "every counter backend failed",
        )
    )
    return rows


def sample_host(
    *,
    runner: Callable[[list[str]], dict[str, Any]],
    ts: float | None = None,
    paths: Sequence[str] | None = None,
    host: str | None = None,
    system: str | None = None,
    plan: list[dict[str, Any]] | None = None,
    probe: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One collection pass: disk + memory + cpu, host-stamped, provenance intact.

    Returns {ts, host, system, readings, by_source, errors}. `by_source` is the
    provenance census of the pass — the answer to "was this box measured, and by
    what?" without re-reading every row. `runner` is required rather than
    defaulted so this module never launches a subprocess a caller did not choose.
    """
    ts = time.time() if ts is None else float(ts)
    host = platform.node() or "unknown-host" if host is None else host
    rows = sample_disk(default_disk_paths() if paths is None else paths, ts=ts)
    rows += sample_memory(ts=ts, system=system, probe=probe)
    rows += sample_cpu(ts=ts, runner=runner, plan=plan)
    stamp_host(rows, host)
    by_source: dict[str, int] = {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    return {
        "ts": ts,
        "host": host,
        "system": platform.system() if system is None else system,
        "readings": rows,
        "by_source": dict(sorted(by_source.items())),
        "errors": [
            {"metric": r["metric"], "scope": r["scope"], "error": r["error"]}
            for r in rows
            if r["error"]
        ],
    }


# ---- the append-only record --------------------------------------------------


def append_jsonl(path: str | Path, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Append rows as one JSON object per line. Never truncates, never rewrites.

    Opened in "a" mode with an explicit utf-8 encoding and "\\n" newline, so the
    file stays byte-identical across platforms and a crash mid-write can cost at
    most the last line. This file — not the sqlite ledger — is the record of
    what was measured; the ledger is derived from it.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    before = p.stat().st_size if p.exists() else 0
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return {
        "path": str(p),
        "rows": len(rows),
        "bytes_before": before,
        "bytes": p.stat().st_size,
    }


def read_jsonl(
    path: str | Path, *, since: float | None = None
) -> tuple[list[dict[str, Any]], int]:
    """Replay the log -> (rows, bad_lines). A truncated tail is skipped, not fatal.

    bad_lines is returned rather than swallowed: silently dropping half a log
    and reporting a clean read is the kind of quiet loss that makes a metrics
    store untrustworthy.
    """
    p = Path(path)
    if not p.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    bad = 0
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(obj, dict) or "metric" not in obj:
                bad += 1
                continue
            if since is not None and float(obj.get("ts") or 0.0) < since:
                continue
            rows.append(obj)
    return rows, bad


def jsonl_stats(path: str | Path) -> dict[str, Any]:
    """Provenance of the log itself — what `show` reports beside the numbers."""
    p = Path(path)
    if not p.exists():
        return {
            "path": str(p),
            "present": False,
            "bytes": None,
            "rows": 0,
            "bad_lines": 0,
            "newest_ts": None,
        }
    rows, bad = read_jsonl(p)
    ts = [float(r["ts"]) for r in rows if r.get("ts") is not None]
    return {
        "path": str(p),
        "present": True,
        "bytes": p.stat().st_size,
        "rows": len(rows),
        "bad_lines": bad,
        "newest_ts": max(ts) if ts else None,
    }


# ---- the derived sqlite store ------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS samples(
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    host TEXT NOT NULL,
    metric TEXT NOT NULL,
    scope TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL,
    how TEXT NOT NULL,
    source TEXT NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_samples_metric_ts ON samples(metric, scope, ts);
CREATE TABLE IF NOT EXISTS rollups(
    host TEXT NOT NULL,
    metric TEXT NOT NULL,
    scope TEXT NOT NULL,
    window_start REAL NOT NULL,
    window_s REAL NOT NULL,
    n INTEGER NOT NULL,
    errors INTEGER NOT NULL,
    min REAL,
    max REAL,
    mean REAL,
    unit TEXT NOT NULL,
    sources TEXT NOT NULL,
    computed_ts REAL NOT NULL,
    PRIMARY KEY(host, metric, scope, window_start, window_s)
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_ledger(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the metrics ledger.

    `samples` is the derived copy of the JSONL; `rollups` is the windowed
    min/max/mean keyed by (host, metric, scope, window_start, window_s) so
    recomputing a window replaces it instead of double-counting, and two boxes'
    disks can never be averaged into one number.
    """
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()
    return conn


def record_samples(conn: sqlite3.Connection, rows: Sequence[dict[str, Any]]) -> int:
    """Insert readings; returns the count. Rejects rows missing provenance.

    The same four honesty rules reading() enforces are re-checked at the storage
    boundary (plus host), because rows can also arrive from a replayed JSONL
    that some other tool appended to.
    """
    payload = []
    for r in rows:
        host = r.get("host")
        if not host:
            raise ValueError(f"reading {r.get('metric')!r} is missing its host stamp")
        if not r.get("how") or r.get("source") not in SOURCES:
            raise ValueError(f"reading {r.get('metric')!r} has no valid provenance")
        if (r.get("value") is None) == (r.get("error") is None):
            raise ValueError(
                f"reading {r.get('metric')!r} must carry exactly one of value/error"
            )
        payload.append(
            (
                float(r["ts"]),
                str(host),
                str(r["metric"]),
                str(r.get("scope") or SCOPE_HOST),
                r.get("value"),
                str(r["unit"]),
                str(r["how"]),
                str(r["source"]),
                r.get("error"),
            )
        )
    conn.executemany(
        "INSERT INTO samples(ts, host, metric, scope, value, unit, how, source, error)"
        " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        payload,
    )
    conn.commit()
    return len(payload)


def rollup(
    conn: sqlite3.Connection,
    *,
    window_s: float = DEFAULT_WINDOW_S,
    since: float | None = None,
    until: float | None = None,
    persist: bool = True,
    now: float | None = None,
) -> dict[str, Any]:
    """min/max/mean per (host, metric, scope) per fixed window. Idempotent.

    Buckets are floor(ts / window_s) * window_s — absolute, not relative to the
    first sample, so two runs over overlapping ranges produce the SAME windows
    and INSERT OR REPLACE updates them in place. Error rows are excluded from
    the statistics and counted in `errors`, and every window records the
    distinct `how` strings behind it so an aggregate stays traceable.
    """
    if window_s <= 0:
        raise ValueError("window_s must be > 0")
    now = time.time() if now is None else float(now)
    sql = (
        "SELECT ts, host, metric, scope, value, unit, how FROM samples"
        " WHERE (? IS NULL OR ts >= ?) AND (? IS NULL OR ts <= ?)"
        " ORDER BY ts"
    )
    rows = conn.execute(sql, (since, since, until, until)).fetchall()
    buckets: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        start = math.floor(float(r["ts"]) / window_s) * window_s
        key = (r["host"], r["metric"], r["scope"], start)
        b = buckets.get(key)
        if b is None:
            b = buckets[key] = {
                "host": r["host"],
                "metric": r["metric"],
                "scope": r["scope"],
                "window_start": start,
                "window_s": float(window_s),
                "unit": r["unit"],
                "values": [],
                "errors": 0,
                "hows": set(),
            }
        b["hows"].add(r["how"])
        if r["value"] is None:
            b["errors"] += 1
        else:
            b["values"].append(float(r["value"]))
    out: list[dict[str, Any]] = []
    for key in sorted(buckets, key=lambda k: (k[3], k[1], k[2], k[0])):
        b = buckets[key]
        vals = b["values"]
        out.append(
            {
                "host": b["host"],
                "metric": b["metric"],
                "scope": b["scope"],
                "window_start": b["window_start"],
                "window_s": b["window_s"],
                "n": len(vals),
                "errors": b["errors"],
                "min": min(vals) if vals else None,
                "max": max(vals) if vals else None,
                "mean": round(sum(vals) / len(vals), 4) if vals else None,
                "unit": b["unit"],
                "sources": sorted(b["hows"]),
            }
        )
    if persist and out:
        conn.executemany(
            "INSERT OR REPLACE INTO rollups(host, metric, scope, window_start,"
            " window_s, n, errors, min, max, mean, unit, sources, computed_ts)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    w["host"],
                    w["metric"],
                    w["scope"],
                    w["window_start"],
                    w["window_s"],
                    w["n"],
                    w["errors"],
                    w["min"],
                    w["max"],
                    w["mean"],
                    w["unit"],
                    json.dumps(w["sources"]),
                    now,
                )
                for w in out
            ],
        )
        conn.commit()
    return {
        "window_s": float(window_s),
        "samples": len(rows),
        "windows": out,
        "persisted": len(out) if persist else 0,
    }


def windows(
    conn: sqlite3.Connection,
    *,
    metric: str | None = None,
    window_s: float | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Read persisted rollups back, newest window first, provenance decoded."""
    rows = conn.execute(
        "SELECT * FROM rollups WHERE (? IS NULL OR metric = ?)"
        " AND (? IS NULL OR window_s = ?)"
        " ORDER BY window_start DESC, metric, scope LIMIT ?",
        (metric, metric, window_s, window_s, int(limit)),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d["sources"])
        out.append(d)
    return out


def latest(
    conn: sqlite3.Connection, *, metric: str | None = None, now: float | None = None
) -> list[dict[str, Any]]:
    """Newest reading per (host, metric, scope) with its age — the `show` board.

    Ordered so failures surface first: error rows, then the highest percentage.
    """
    now = time.time() if now is None else float(now)
    # newest per series by (ts, id) — deterministic even when a replayed JSONL
    # inserts an OLDER sample after a newer one (MAX(id) would pick the wrong row)
    rows = conn.execute(
        "SELECT s.* FROM samples s WHERE (? IS NULL OR s.metric = ?)"
        " AND NOT EXISTS (SELECT 1 FROM samples t WHERE t.host = s.host"
        "   AND t.metric = s.metric AND t.scope = s.scope"
        "   AND (t.ts > s.ts OR (t.ts = s.ts AND t.id > s.id)))",
        (metric, metric),
    ).fetchall()
    out = [dict(r) | {"age_s": round(now - float(r["ts"]), 3)} for r in rows]
    out.sort(
        key=lambda d: (
            0 if d["error"] else 1,
            -(d["value"] or 0.0) if d["unit"] == UNIT_PERCENT else 0.0,
            d["metric"],
            d["scope"],
        )
    )
    return out


def series(
    conn: sqlite3.Connection, metric: str, *, scope: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Raw newest-first history for one metric (optionally one scope)."""
    rows = conn.execute(
        "SELECT * FROM samples WHERE metric = ? AND (? IS NULL OR scope = ?)"
        " ORDER BY ts DESC, id DESC LIMIT ?",
        (metric, scope, scope, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- family gate -------------------------------------------------------------

_PCT_NAME = {METRIC_DISK_USED_PCT: "disk", METRIC_MEM_USED_PCT: "mem"}


def to_diagnostics(
    rows: Sequence[dict[str, Any]],
    *,
    disk_warn_pct: float = DISK_WARN_PCT,
    disk_error_pct: float = DISK_ERROR_PCT,
    mem_warn_pct: float = MEM_WARN_PCT,
    mem_error_pct: float = MEM_ERROR_PCT,
) -> list[dict[str, Any]]:
    """Map readings onto the openswap diagnostic schema for `--fail-on`.

    Two axes, deliberately separated:
      * pressure — disk/memory percentages at or above their budgets
        (error >= *_error_pct, warning >= *_warn_pct).
      * measurement — a backend that FAILED is a warning ("metrics:unmeasured"),
        because an unmeasured box is not a healthy box. A platform that never
        had the mechanism (source="unsupported") is only info: that is declared
        scope, not a regression, and gating cron on it would train people to
        ignore the gate.
    """
    budgets = {
        METRIC_DISK_USED_PCT: (disk_warn_pct, disk_error_pct),
        METRIC_MEM_USED_PCT: (mem_warn_pct, mem_error_pct),
    }
    diags = []
    for r in rows:
        metric, scope = r.get("metric", "?"), r.get("scope") or SCOPE_HOST
        where = f"{metric}[{scope}]"
        if r.get("error"):
            unsupported = r.get("source") == SRC_UNSUPPORTED
            diags.append(
                openswap.diagnostic(
                    path=where,
                    line=0,
                    col=0,
                    rule="metrics:unsupported" if unsupported else "metrics:unmeasured",
                    severity="info" if unsupported else "warning",
                    message=f"{where} not measured — {r['error']}",
                    suggestion=None if unsupported else f"tried: {r.get('how')}",
                    source=str(r.get("source") or "?"),
                )
            )
            continue
        budget = budgets.get(metric)
        if budget is None or r.get("value") is None:
            continue
        warn_at, error_at = budget
        val = float(r["value"])
        sev = "error" if val >= error_at else "warning" if val >= warn_at else None
        if sev is None:
            continue
        limit = error_at if sev == "error" else warn_at
        name = _PCT_NAME[metric]
        diags.append(
            openswap.diagnostic(
                path=where,
                line=0,
                col=0,
                rule=f"metrics:{name}-pressure",
                severity=sev,
                message=f"{where} at {val}% (>= {limit}%)",
                suggestion=f"measured by {r.get('how')}",
                source=str(r.get("source") or "?"),
            )
        )
    return openswap.sort_diagnostics(diags)
