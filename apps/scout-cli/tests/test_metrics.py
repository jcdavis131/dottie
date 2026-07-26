"""Metrics — openswap #15 (Datadog Infrastructure Monitoring -> stdlib host
collection into an append-only JSONL log + sqlite min/max/mean rollups).

Offline and deterministic by construction: every `ts` is explicit, the counter
subprocess is an INJECTED runner replaying stdout captured from a real typeperf
/ Get-Counter run on this box, the memory mechanism is selected by an injected
`system` name so the Windows, Linux and unsupported-platform branches are all
reachable from any host, and no test opens a socket. Disk and /proc parsing are
exercised for real against tmp_path and a real meminfo fixture.

What these tests refuse to allow is a number without a provenance stamp or a
failed measurement that reads as a healthy one: several assert that a reading
carries EITHER a value or an error, that rollups exclude error rows from
min/max/mean while counting them, and that an aggregate still names the exact
API/argv behind it.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import metrics, openswap

ROOT = Path(__file__).resolve().parents[1]

T0 = 1_800_000_000.0  # fixed epoch base; every ts below is derived from it
HOST = "testbox"

# stdout captured from a real `typeperf "\Processor(_Total)\% Processor Time" -sc 1`
# on this box (Windows 11) — header, one data row, then non-CSV chatter
TYPEPERF_OUT = (
    '\n"(PDH-CSV 4.0)","\\\\NUGATRON\\Processor(_Total)\\% Processor Time"\n'
    '"07/24/2026 21:02:29.374","75.409893"\n'
    "Exiting, please wait...                         \n"
    "The command completed successfully.\n\n\n"
)
# stdout captured from a real Get-Counter CookedValue read
COOKED_OUT = "51.7406473743205\n"

# a real /proc/meminfo head (kB units, plus a unitless line that must not break)
MEMINFO = """MemTotal:       16384000 kB
MemFree:          512000 kB
MemAvailable:    4096000 kB
Buffers:           16000 kB
Cached:          2048000 kB
HugePages_Total:       0
HugePages_Free:        0
Hugepagesize:       2048 kB
"""


def _runner(script):
    """Counter-runner fake replaying canned results in order (offline invariant)."""
    calls = []

    def run(argv):
        calls.append(list(argv))
        step = script[len(calls) - 1]
        if isinstance(step, Exception):
            raise step
        return step

    run.calls = calls
    return run


def _ok(stdout):
    return {"returncode": 0, "stdout": stdout, "stderr": ""}


def _plan(*kinds, counter=metrics.CPU_COUNTER):
    """A counter plan without touching PATH — the dispatch boundary, injected."""
    argv = {
        "typeperf": lambda: metrics.typeperf_argv(counter, path="typeperf"),
        "get-counter": lambda: metrics.powershell_argv(counter, path="powershell"),
    }
    return [{"kind": k, "argv": argv[k]()} for k in kinds]


def _row(
    metric,
    value,
    *,
    ts=T0,
    scope=metrics.SCOPE_HOST,
    unit=metrics.UNIT_PERCENT,
    error=None,
    source=metrics.SRC_STDLIB,
    how="test",
):
    return metrics.reading(
        ts=ts,
        metric=metric,
        scope=scope,
        unit=unit,
        how=how,
        source=source,
        value=value,
        error=error,
    )


def _pick(rows, metric):
    """The one reading for a metric — proves there is exactly one, then returns it."""
    got = [r for r in rows if r["metric"] == metric]
    assert len(got) == 1, f"expected exactly one {metric} reading, got {len(got)}"
    return got[0]


def _ledger(tmp_path, rows=()):
    conn = metrics.open_ledger(tmp_path / "metrics.db")
    if rows:
        metrics.record_samples(conn, metrics.stamp_host(list(rows), HOST))
    return conn


# ---- provenance is enforced at the constructor, not asked for in review ------


def test_reading_carries_the_full_provenance_shape():
    r = metrics.reading(
        ts=T0,
        metric="disk.used_pct",
        scope="C:\\",
        unit=metrics.UNIT_PERCENT,
        how="shutil.disk_usage('C:\\\\')",
        source=metrics.SRC_STDLIB,
        value=41.5,
    )
    assert r["ts"] == T0 and r["metric"] == "disk.used_pct"
    assert r["scope"] == "C:\\" and r["unit"] == "percent"
    assert r["value"] == 41.5 and r["error"] is None
    assert r["source"] == "stdlib" and "shutil.disk_usage" in r["how"]
    assert set(r) == {
        "ts",
        "metric",
        "scope",
        "value",
        "unit",
        "how",
        "source",
        "error",
    }


def test_reading_refuses_a_row_that_does_not_say_how_it_was_measured():
    with pytest.raises(ValueError, match="how it was measured"):
        metrics.reading(
            ts=T0,
            metric="cpu.busy_pct",
            scope="host",
            unit=metrics.UNIT_PERCENT,
            how="",
            source=metrics.SRC_COUNTER,
            value=1.0,
        )
    with pytest.raises(ValueError, match="how it was measured"):
        metrics.reading(
            ts=T0,
            metric="cpu.busy_pct",
            scope="host",
            unit=metrics.UNIT_PERCENT,
            how="   ",
            source=metrics.SRC_COUNTER,
            value=1.0,
        )


def test_reading_rejects_free_text_provenance_and_unknown_units():
    with pytest.raises(ValueError, match="source must be one of"):
        metrics.reading(
            ts=T0,
            metric="cpu.busy_pct",
            scope="host",
            unit=metrics.UNIT_PERCENT,
            how="magic",
            source="vibes",
            value=1.0,
        )
    with pytest.raises(ValueError, match="unit must be one of"):
        metrics.reading(
            ts=T0,
            metric="cpu.busy_pct",
            scope="host",
            unit="jiffies",
            how="os.times()",
            source=metrics.SRC_STDLIB,
            value=1.0,
        )
    with pytest.raises(ValueError, match="needs a metric name"):
        metrics.reading(
            ts=T0,
            metric="  ",
            scope="host",
            unit=metrics.UNIT_COUNT,
            how="os.cpu_count()",
            source=metrics.SRC_STDLIB,
            value=1.0,
        )
    assert "vibes" not in metrics.SOURCES and "jiffies" not in metrics.UNITS


def test_reading_forbids_a_value_and_an_error_on_the_same_row():
    """A failed measurement carrying a number is how a monitor starts lying."""
    with pytest.raises(ValueError, match="both a value and an error"):
        metrics.reading(
            ts=T0,
            metric="mem.used_pct",
            scope="host",
            unit=metrics.UNIT_PERCENT,
            how=metrics.HOW_PROCFS_MEM,
            source=metrics.SRC_PROCFS,
            value=0.0,
            error="OSError: boom",
        )
    with pytest.raises(ValueError, match="needs a value or an error"):
        metrics.reading(
            ts=T0,
            metric="mem.used_pct",
            scope="host",
            unit=metrics.UNIT_PERCENT,
            how=metrics.HOW_PROCFS_MEM,
            source=metrics.SRC_PROCFS,
        )


def test_stamp_host_marks_every_row_and_refuses_an_empty_name():
    rows = [_row("cpu.busy_pct", 1.0), _row("mem.used_pct", 2.0)]
    out = metrics.stamp_host(rows, "nugatron")
    assert [r["host"] for r in out] == ["nugatron", "nugatron"]
    assert rows[0]["host"] == "nugatron"  # stamps in place, no silent copy
    with pytest.raises(ValueError, match="non-empty name"):
        metrics.stamp_host([_row("cpu.busy_pct", 1.0)], "")


# ---- disk: shutil.disk_usage, measured for real ------------------------------


def test_sample_disk_reports_pct_free_and_total_with_provenance(tmp_path):
    rows = metrics.sample_disk([str(tmp_path)], ts=T0)
    by_metric = {r["metric"]: r for r in rows}
    assert sorted(by_metric) == ["disk.free_bytes", "disk.total_bytes", "disk.used_pct"]
    du = shutil.disk_usage(str(tmp_path))
    assert by_metric["disk.total_bytes"]["value"] == float(du.total)
    assert by_metric["disk.total_bytes"]["unit"] == "bytes"
    assert by_metric["disk.free_bytes"]["value"] > 0
    pct = by_metric["disk.used_pct"]
    assert pct["value"] == round(100.0 * du.used / du.total, 2)
    assert 0.0 <= pct["value"] <= 100.0 and pct["unit"] == "percent"
    for r in rows:
        assert r["ts"] == T0 and r["error"] is None
        assert r["source"] == metrics.SRC_STDLIB
        assert r["how"].startswith("shutil.disk_usage(")
        assert str(tmp_path) in r["how"] and r["scope"] == str(tmp_path)


def test_sample_disk_records_an_unreadable_path_as_errors_not_zeros(tmp_path):
    rows = metrics.sample_disk([str(tmp_path / "no-such-volume")], ts=T0)
    assert len(rows) == 3
    for r in rows:
        assert r["value"] is None and r["error"]
        # the exception CLASS survives, so a missing path stays distinguishable
        # from a permissions failure in the history
        assert r["error"].split(":")[0].endswith("Error")
        assert r["how"].startswith("shutil.disk_usage(")  # still says what it tried
    assert {r["metric"] for r in rows} == {
        "disk.used_pct",
        "disk.free_bytes",
        "disk.total_bytes",
    }


def test_sample_disk_keeps_each_filesystem_in_its_own_scope(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    rows = metrics.sample_disk([str(a), str(b)], ts=T0)
    assert len(rows) == 6
    assert {r["scope"] for r in rows} == {str(a), str(b)}


def test_default_disk_paths_is_derived_not_hardcoded():
    paths = metrics.default_disk_paths()
    assert len(paths) == 1 and Path(paths[0]).exists()
    assert paths[0] == str(Path(Path.cwd().anchor))


# ---- memory: three branches, all reachable from any host --------------------


def test_parse_meminfo_scales_kb_and_ignores_noise():
    info = metrics.parse_meminfo(MEMINFO)
    assert info["MemTotal"] == 16384000 * 1024.0
    assert info["MemAvailable"] == 4096000 * 1024.0
    assert info["HugePages_Total"] == 0.0  # unitless line, not scaled
    assert metrics.parse_meminfo("not a meminfo file\n") == {}
    assert metrics.parse_meminfo("") == {}


def test_memory_procfs_uses_memavailable_not_memfree():
    got = metrics.memory_procfs(MEMINFO)
    assert got["total_bytes"] == 16384000 * 1024.0
    assert got["available_bytes"] == 4096000 * 1024.0
    assert got["used_pct"] == 75.0  # (16384000-4096000)/16384000, NOT MemFree's 96.9
    assert got["source"] == metrics.SRC_PROCFS and "/proc/meminfo" in got["how"]


def test_memory_procfs_refuses_a_meminfo_without_the_pair():
    with pytest.raises(OSError, match="MemTotal/MemAvailable"):
        metrics.memory_procfs("MemFree: 512000 kB\n")


def test_sample_memory_linux_branch_records_procfs_provenance():
    rows = metrics.sample_memory(
        ts=T0, system="Linux", probe=lambda: metrics.memory_procfs(MEMINFO)
    )
    by_metric = {r["metric"]: r for r in rows}
    assert sorted(by_metric) == [
        "mem.available_bytes",
        "mem.total_bytes",
        "mem.used_pct",
    ]
    assert by_metric["mem.used_pct"]["value"] == 75.0
    assert by_metric["mem.total_bytes"]["value"] == 16384000 * 1024.0
    for r in rows:
        assert r["source"] == metrics.SRC_PROCFS and r["error"] is None
        assert r["scope"] == metrics.SCOPE_HOST and r["ts"] == T0
        assert "/proc/meminfo" in r["how"]


def test_sample_memory_on_an_unsupported_platform_says_so(tmp_path):
    """Scope honesty: no mechanism means an explicit reason, never a zero."""
    rows = metrics.sample_memory(ts=T0, system="Plan9")
    assert len(rows) == 3
    for r in rows:
        assert r["value"] is None
        assert r["source"] == metrics.SRC_UNSUPPORTED
        assert "Plan9" in r["error"]
        # it still names both mechanisms it would have used
        assert "GlobalMemoryStatusEx" in r["how"] and "/proc/meminfo" in r["how"]


def test_sample_memory_turns_a_probe_failure_into_error_rows():
    def boom():
        raise OSError("GlobalMemoryStatusEx failed, GetLastError=8")

    rows = metrics.sample_memory(ts=T0, system="Windows", probe=boom)
    assert len(rows) == 3
    for r in rows:
        assert r["value"] is None and "GetLastError=8" in r["error"]
        assert r["source"] == metrics.SRC_CTYPES  # a real mechanism that failed
        assert r["how"] == metrics.HOW_WINDOWS_MEM


def test_sample_memory_dispatches_by_platform_name():
    seen = []

    def probe():
        seen.append("called")
        return metrics.memory_procfs(MEMINFO)

    metrics.sample_memory(ts=T0, system="Windows", probe=probe)
    assert seen == ["called"]  # an explicit probe overrides platform dispatch
    rows = metrics.sample_memory(ts=T0, system="Darwin")
    assert rows[0]["source"] == metrics.SRC_UNSUPPORTED
    assert "Darwin" in rows[0]["error"]


@pytest.mark.skipif(
    platform.system() != "Windows", reason="ctypes windll is Windows-only"
)
def test_memory_windows_reads_the_real_kernel_struct():
    got = metrics.memory_windows()
    assert got["total_bytes"] > 0
    assert 0.0 < got["available_bytes"] <= got["total_bytes"]
    assert 0.0 <= got["used_pct"] <= 100.0
    assert got["source"] == metrics.SRC_CTYPES
    assert got["how"] == metrics.HOW_WINDOWS_MEM
    assert ctypes.sizeof(metrics.MEMORYSTATUSEX) == 64  # the documented Win32 layout


# ---- cpu: argv builders and pure parsers ------------------------------------


def test_typeperf_argv_asks_for_one_sample_then_exits():
    argv = metrics.typeperf_argv(metrics.CPU_COUNTER, path="typeperf")
    assert argv == ["typeperf", r"\Processor(_Total)\% Processor Time", "-sc", "1"]
    assert metrics.typeperf_argv("\\X", path="tp", samples=3)[-1] == "3"


def test_powershell_argv_disables_the_profile_and_prompts():
    argv = metrics.powershell_argv(metrics.CPU_COUNTER, path="powershell")
    assert argv[0] == "powershell"
    assert "-NoProfile" in argv and "-NonInteractive" in argv and "-Command" in argv
    script = argv[-1]
    assert "Get-Counter" in script and metrics.CPU_COUNTER in script
    assert "CookedValue" in script and "-MaxSamples 1" in script


def test_parse_typeperf_takes_the_sample_and_ignores_header_and_chatter():
    assert metrics.parse_typeperf(TYPEPERF_OUT) == 75.409893
    two = TYPEPERF_OUT.replace(
        '"07/24/2026 21:02:29.374","75.409893"',
        '"07/24/2026 21:02:29.374","75.409893"\n"07/24/2026 21:02:30.374","12.5"',
    )
    assert metrics.parse_typeperf(two) == 12.5  # newest sample wins


def test_parse_typeperf_returns_none_rather_than_inventing_a_zero():
    assert metrics.parse_typeperf("") is None
    assert metrics.parse_typeperf("The command completed successfully.\n") is None
    header_only = '"(PDH-CSV 4.0)","\\\\H\\Processor(_Total)\\% Processor Time"\n'
    assert metrics.parse_typeperf(header_only) is None
    assert metrics.parse_typeperf('"07/24/2026 21:02:29.374","  "') is None


def test_parse_cooked_value_reads_get_counter_and_refuses_a_locale_guess():
    assert metrics.parse_cooked_value(COOKED_OUT) == 51.7406473743205
    assert metrics.parse_cooked_value("  3 \n") == 3.0
    assert metrics.parse_cooked_value("") is None
    assert metrics.parse_cooked_value("Get-Counter : path not valid\n") is None
    # a comma decimal separator is refused, NOT truncated to a plausible 51
    assert metrics.parse_cooked_value("51,7406473743205\n") is None
    assert metrics.parse_cooked_value("no digits here") is None


def test_counter_plan_prefers_typeperf_and_reports_an_empty_box():
    both = metrics.counter_plan(which=lambda b: f"/usr/bin/{b}")
    assert [s["kind"] for s in both] == ["typeperf", "get-counter"]
    assert both[0]["argv"][0] == "/usr/bin/typeperf"
    only_ps = metrics.counter_plan(
        which=lambda b: None if b == "typeperf" else "ps.exe"
    )
    assert [s["kind"] for s in only_ps] == ["get-counter"]
    assert metrics.counter_plan(which=lambda b: None) == []


# ---- cpu: the injected runner boundary --------------------------------------


def test_sample_cpu_records_the_backend_that_answered():
    run = _runner([_ok(TYPEPERF_OUT)])
    rows = metrics.sample_cpu(ts=T0, runner=run, plan=_plan("typeperf"))
    by_metric = {r["metric"]: r for r in rows}
    busy = by_metric["cpu.busy_pct"]
    assert busy["value"] == 75.41  # rounded to 3dp -> 75.41 has 2 sig decimals
    assert busy["source"] == metrics.SRC_COUNTER and busy["error"] is None
    assert busy["how"].startswith("typeperf ") and "-sc 1" in busy["how"]
    logical = by_metric["cpu.logical"]
    assert logical["value"] == float(os.cpu_count())
    assert logical["unit"] == "count" and logical["source"] == metrics.SRC_STDLIB
    assert logical["how"] == "os.cpu_count()"
    assert len(run.calls) == 1  # the second backend is never run after a success


def test_sample_cpu_falls_through_to_the_next_backend(tmp_path):
    run = _runner(
        [
            {"returncode": 1, "stdout": "", "stderr": "Error: counter not found"},
            _ok(COOKED_OUT),
        ]
    )
    rows = metrics.sample_cpu(ts=T0, runner=run, plan=_plan("typeperf", "get-counter"))
    # _pick asserts uniqueness: one reading per series, not one per attempt
    busy = _pick(rows, "cpu.busy_pct")
    assert busy["value"] == 51.741 and busy["error"] is None
    assert "Get-Counter" in busy["how"]  # provenance names the WINNING backend
    assert len(run.calls) == 2 and run.calls[0][0] == "typeperf"


def test_sample_cpu_keeps_the_error_when_every_backend_fails():
    run = _runner(
        [
            {"returncode": 1, "stdout": "", "stderr": "typeperf: no counters"},
            _ok("Get-Counter : The specified object was not found\n"),
        ]
    )
    rows = metrics.sample_cpu(ts=T0, runner=run, plan=_plan("typeperf", "get-counter"))
    busy = _pick(rows, "cpu.busy_pct")
    assert busy["value"] is None, "an unmeasured CPU must not read as 0% busy"
    assert busy["source"] == metrics.SRC_COUNTER
    assert "exit 1" in busy["error"] and "no counters" in busy["error"]
    assert "no numeric sample" in busy["error"]  # both attempts are reported
    assert "typeperf" in busy["how"] and "Get-Counter" in busy["how"]


def test_sample_cpu_treats_a_runner_explosion_as_data():
    run = _runner([FileNotFoundError("typeperf missing"), _ok(COOKED_OUT)])
    rows = metrics.sample_cpu(ts=T0, runner=run, plan=_plan("typeperf", "get-counter"))
    busy = _pick(rows, "cpu.busy_pct")
    assert busy["value"] == 51.741  # recovered on the second backend
    run2 = _runner([TimeoutError("wedged perf subsystem")])
    rows2 = metrics.sample_cpu(ts=T0, runner=run2, plan=_plan("typeperf"))
    busy2 = _pick(rows2, "cpu.busy_pct")
    assert busy2["value"] is None and "TimeoutError" in busy2["error"]


def test_sample_cpu_on_a_box_with_no_counter_backend_never_runs_anything():
    run = _runner([_ok(TYPEPERF_OUT)])
    rows = metrics.sample_cpu(ts=T0, runner=run, plan=[])
    busy = _pick(rows, "cpu.busy_pct")
    assert run.calls == []  # nothing was executed
    assert busy["value"] is None and busy["source"] == metrics.SRC_UNSUPPORTED
    assert "no performance-counter backend" in busy["error"]
    assert "typeperf" in busy["how"] and "Get-Counter" in busy["how"]
    # cpu.logical still collects — the stdlib half is platform-independent
    assert _pick(rows, "cpu.logical")["value"] > 0


# ---- one full pass ----------------------------------------------------------


def test_sample_host_stamps_every_row_and_censuses_provenance(tmp_path):
    got = metrics.sample_host(
        runner=_runner([_ok(TYPEPERF_OUT)]),
        ts=T0,
        paths=[str(tmp_path)],
        host=HOST,
        system="Linux",
        plan=_plan("typeperf"),
        probe=lambda: metrics.memory_procfs(MEMINFO),
    )
    assert got["ts"] == T0 and got["host"] == HOST and got["system"] == "Linux"
    rows = got["readings"]
    assert len(rows) == 8  # 3 disk + 3 memory + cpu.logical + cpu.busy_pct
    assert all(r["host"] == HOST for r in rows)
    assert all(r["ts"] == T0 for r in rows)
    assert got["by_source"] == {"counter": 1, "procfs": 3, "stdlib": 4}
    assert got["errors"] == []
    assert {r["metric"] for r in rows} == {
        "disk.used_pct",
        "disk.free_bytes",
        "disk.total_bytes",
        "mem.used_pct",
        "mem.available_bytes",
        "mem.total_bytes",
        "cpu.logical",
        "cpu.busy_pct",
    }


def test_sample_host_surfaces_what_it_could_not_measure(tmp_path):
    got = metrics.sample_host(
        runner=_runner([]),
        ts=T0,
        paths=[str(tmp_path / "gone")],
        host=HOST,
        system="Plan9",
        plan=[],
    )
    errs = {(e["metric"], bool(e["error"])) for e in got["errors"]}
    assert len(got["errors"]) == 7  # 3 disk + 3 memory + cpu.busy_pct
    assert ("cpu.busy_pct", True) in errs and ("mem.used_pct", True) in errs
    assert got["by_source"]["unsupported"] == 4
    # the census proves the pass happened even though almost nothing measured
    assert sum(got["by_source"].values()) == 8


def test_sample_host_defaults_to_the_volume_this_process_runs_on():
    got = metrics.sample_host(runner=_runner([]), ts=T0, host=HOST, plan=[])
    disk = _pick(got["readings"], "disk.total_bytes")
    assert disk["scope"] == metrics.default_disk_paths()[0]
    assert disk["value"] > 0


# ---- the append-only record -------------------------------------------------


def test_append_jsonl_is_append_only_and_creates_its_directory(tmp_path):
    log = tmp_path / "nested" / "metrics.jsonl"
    first = metrics.append_jsonl(log, [_row("cpu.busy_pct", 1.0, ts=T0)])
    assert log.exists() and first["rows"] == 1
    assert first["bytes_before"] == 0 and first["bytes"] > 0
    second = metrics.append_jsonl(
        log,
        [_row("cpu.busy_pct", 2.0, ts=T0 + 1), _row("cpu.busy_pct", 3.0, ts=T0 + 2)],
    )
    assert second["rows"] == 2
    assert second["bytes_before"] == first["bytes"], (
        "the log was rewritten, not appended"
    )
    assert second["bytes"] > first["bytes"]
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [json.loads(x)["value"] for x in lines] == [1.0, 2.0, 3.0]
    assert json.loads(lines[0])["metric"] == "cpu.busy_pct"


def test_read_jsonl_round_trips_and_counts_damaged_lines(tmp_path):
    log = tmp_path / "metrics.jsonl"
    metrics.append_jsonl(log, [_row("cpu.busy_pct", 1.0, ts=T0)])
    with log.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
        fh.write('{"ts": 1, "value": 2}\n')  # no metric -> not a reading
        fh.write("\n")
        fh.write("[1, 2, 3]\n")
    rows, bad = metrics.read_jsonl(log)
    assert [r["value"] for r in rows] == [1.0]
    assert bad == 3, "a truncated tail must be reported, not silently dropped"
    assert metrics.read_jsonl(tmp_path / "absent.jsonl") == ([], 0)


def test_read_jsonl_since_filters_by_timestamp(tmp_path):
    log = tmp_path / "metrics.jsonl"
    metrics.append_jsonl(
        log,
        [
            _row("cpu.busy_pct", 1.0, ts=T0),
            _row("cpu.busy_pct", 2.0, ts=T0 + 60),
            _row("cpu.busy_pct", 3.0, ts=T0 + 120),
        ],
    )
    rows, bad = metrics.read_jsonl(log, since=T0 + 60)
    assert [r["value"] for r in rows] == [2.0, 3.0] and bad == 0


def test_jsonl_stats_is_honest_about_an_absent_log(tmp_path):
    absent = metrics.jsonl_stats(tmp_path / "never.jsonl")
    assert absent["present"] is False and absent["rows"] == 0
    assert absent["bytes"] is None and absent["newest_ts"] is None
    log = tmp_path / "metrics.jsonl"
    metrics.append_jsonl(
        log, [_row("cpu.busy_pct", 1.0, ts=T0), _row("cpu.busy_pct", 2.0, ts=T0 + 5)]
    )
    with log.open("a", encoding="utf-8") as fh:
        fh.write("garbage\n")
    stats = metrics.jsonl_stats(log)
    assert stats["present"] is True and stats["rows"] == 2 and stats["bad_lines"] == 1
    assert stats["newest_ts"] == T0 + 5 and stats["bytes"] > 0
    assert stats["path"] == str(log)


# ---- the derived sqlite store ----------------------------------------------


def test_open_ledger_creates_the_schema_and_is_reopenable(tmp_path):
    db = tmp_path / "sub" / "metrics.db"
    conn = metrics.open_ledger(db)
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"samples", "rollups", "meta"} <= tables
    version = conn.execute(
        "SELECT value FROM meta WHERE key='schema_version'"
    ).fetchone()
    assert version["value"] == metrics.SCHEMA_VERSION
    conn.close()
    again = metrics.open_ledger(db)  # idempotent, no duplicate meta row
    assert again.execute("SELECT COUNT(*) AS n FROM meta").fetchone()["n"] == 1
    again.close()


def test_record_samples_stores_provenance_verbatim(tmp_path):
    rows = metrics.stamp_host(
        [
            _row("disk.used_pct", 42.0, scope="C:\\", how="shutil.disk_usage('C:')"),
            _row(
                "cpu.busy_pct",
                None,
                error="exit 1",
                source=metrics.SRC_COUNTER,
                how="typeperf -sc 1",
            ),
        ],
        HOST,
    )
    conn = metrics.open_ledger(tmp_path / "m.db")
    assert metrics.record_samples(conn, rows) == 2
    stored = conn.execute("SELECT * FROM samples ORDER BY metric").fetchall()
    assert [r["metric"] for r in stored] == ["cpu.busy_pct", "disk.used_pct"]
    assert stored[0]["value"] is None and stored[0]["error"] == "exit 1"
    assert stored[0]["how"] == "typeperf -sc 1" and stored[0]["source"] == "counter"
    assert stored[1]["value"] == 42.0 and stored[1]["scope"] == "C:\\"
    assert stored[1]["host"] == HOST and stored[1]["unit"] == "percent"


def test_record_samples_rejects_rows_that_lost_their_provenance(tmp_path):
    conn = metrics.open_ledger(tmp_path / "m.db")
    unstamped = _row("cpu.busy_pct", 1.0)
    with pytest.raises(ValueError, match="missing its host stamp"):
        metrics.record_samples(conn, [unstamped])
    laundered = metrics.stamp_host([_row("cpu.busy_pct", 1.0)], HOST)[0] | {"how": ""}
    with pytest.raises(ValueError, match="no valid provenance"):
        metrics.record_samples(conn, [laundered])
    forged = metrics.stamp_host([_row("cpu.busy_pct", 1.0)], HOST)[0] | {
        "source": "guess"
    }
    with pytest.raises(ValueError, match="no valid provenance"):
        metrics.record_samples(conn, [forged])
    both = metrics.stamp_host([_row("cpu.busy_pct", 1.0)], HOST)[0] | {"error": "boom"}
    with pytest.raises(ValueError, match="exactly one of value/error"):
        metrics.record_samples(conn, [both])
    assert conn.execute("SELECT COUNT(*) AS n FROM samples").fetchone()["n"] == 0


def test_rollup_computes_min_max_mean_per_window(tmp_path):
    rows = [
        _row("cpu.busy_pct", 10.0, ts=T0 + 0),
        _row("cpu.busy_pct", 30.0, ts=T0 + 100),
        _row("cpu.busy_pct", 50.0, ts=T0 + 200),
        _row("cpu.busy_pct", 90.0, ts=T0 + 400),  # next 300s window
    ]
    conn = _ledger(tmp_path, rows)
    res = metrics.rollup(conn, window_s=300.0, now=T0 + 500)
    assert res["samples"] == 4 and res["window_s"] == 300.0
    ws = res["windows"]
    assert len(ws) == 2 and res["persisted"] == 2
    first, second = ws
    assert first["window_start"] == T0 // 300 * 300  # absolute bucket, not relative
    assert first["n"] == 3 and first["errors"] == 0
    assert (first["min"], first["max"], first["mean"]) == (10.0, 50.0, 30.0)
    assert second["n"] == 1 and second["mean"] == 90.0
    assert second["window_start"] == first["window_start"] + 300.0
    assert first["unit"] == "percent" and first["host"] == HOST


def test_rollup_excludes_errors_from_the_statistics_but_counts_them(tmp_path):
    rows = [
        _row("cpu.busy_pct", 20.0, ts=T0),
        _row("cpu.busy_pct", 40.0, ts=T0 + 10),
        _row(
            "cpu.busy_pct",
            None,
            ts=T0 + 20,
            error="exit 1",
            source=metrics.SRC_COUNTER,
            how="typeperf -sc 1",
        ),
    ]
    w = metrics.rollup(_ledger(tmp_path, rows), window_s=300.0)["windows"][0]
    assert w["n"] == 2 and w["errors"] == 1
    assert w["mean"] == 30.0, "a failed sample must not be averaged in as 0"
    assert w["min"] == 20.0 and w["max"] == 40.0


def test_rollup_that_measured_nothing_reports_no_statistics(tmp_path):
    rows = [
        _row(
            "cpu.busy_pct",
            None,
            ts=T0,
            error="exit 1",
            source=metrics.SRC_COUNTER,
            how="typeperf",
        ),
        _row(
            "cpu.busy_pct",
            None,
            ts=T0 + 5,
            error="exit 1",
            source=metrics.SRC_COUNTER,
            how="typeperf",
        ),
    ]
    w = metrics.rollup(_ledger(tmp_path, rows), window_s=300.0)["windows"][0]
    assert w["n"] == 0 and w["errors"] == 2
    assert w["min"] is None and w["max"] is None and w["mean"] is None


def test_rollup_windows_keep_the_provenance_of_their_inputs(tmp_path):
    rows = [
        _row(
            "cpu.busy_pct",
            10.0,
            ts=T0,
            how="typeperf -sc 1",
            source=metrics.SRC_COUNTER,
        ),
        _row(
            "cpu.busy_pct",
            20.0,
            ts=T0 + 5,
            how="powershell Get-Counter",
            source=metrics.SRC_COUNTER,
        ),
        _row(
            "cpu.busy_pct",
            30.0,
            ts=T0 + 10,
            how="typeperf -sc 1",
            source=metrics.SRC_COUNTER,
        ),
    ]
    w = metrics.rollup(_ledger(tmp_path, rows), window_s=300.0)["windows"][0]
    assert w["sources"] == ["powershell Get-Counter", "typeperf -sc 1"]
    assert w["mean"] == 20.0  # the aggregate is still traceable to both backends


def test_rollup_is_idempotent_and_updates_in_place(tmp_path):
    conn = _ledger(tmp_path, [_row("cpu.busy_pct", 10.0, ts=T0)])
    metrics.rollup(conn, window_s=300.0, now=T0)
    stored = conn.execute("SELECT COUNT(*) AS n FROM rollups").fetchone()["n"]
    assert stored == 1
    metrics.record_samples(
        conn, metrics.stamp_host([_row("cpu.busy_pct", 30.0, ts=T0 + 10)], HOST)
    )
    metrics.rollup(conn, window_s=300.0, now=T0 + 20)
    after = conn.execute("SELECT * FROM rollups").fetchall()
    assert len(after) == 1, "re-rolling the same window must replace, not duplicate"
    assert after[0]["n"] == 2 and after[0]["mean"] == 20.0
    assert after[0]["computed_ts"] == T0 + 20


def test_rollup_never_merges_two_hosts_into_one_number(tmp_path):
    conn = metrics.open_ledger(tmp_path / "m.db")
    metrics.record_samples(
        conn, metrics.stamp_host([_row("cpu.busy_pct", 10.0, ts=T0)], "a")
    )
    metrics.record_samples(
        conn, metrics.stamp_host([_row("cpu.busy_pct", 90.0, ts=T0)], "b")
    )
    ws = metrics.rollup(conn, window_s=300.0)["windows"]
    assert len(ws) == 2
    assert {w["host"]: w["mean"] for w in ws} == {"a": 10.0, "b": 90.0}


def test_rollup_honours_the_window_and_the_range(tmp_path):
    rows = [_row("cpu.busy_pct", float(i), ts=T0 + i * 60) for i in range(5)]
    conn = _ledger(tmp_path, rows)
    assert len(metrics.rollup(conn, window_s=60.0, persist=False)["windows"]) == 5
    narrowed = metrics.rollup(
        conn, window_s=3600.0, since=T0 + 120, until=T0 + 180, persist=False
    )
    assert narrowed["samples"] == 2 and len(narrowed["windows"]) == 1
    assert narrowed["windows"][0]["mean"] == 2.5 and narrowed["persisted"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM rollups").fetchone()["n"] == 0
    with pytest.raises(ValueError, match="window_s must be > 0"):
        metrics.rollup(conn, window_s=0.0)


def test_windows_reads_back_persisted_rollups_newest_first(tmp_path):
    rows = [
        _row("cpu.busy_pct", 10.0, ts=T0),
        _row("cpu.busy_pct", 20.0, ts=T0 + 400),
        _row("disk.used_pct", 50.0, ts=T0, scope="C:\\"),
    ]
    conn = _ledger(tmp_path, rows)
    metrics.rollup(conn, window_s=300.0, now=T0)
    got = metrics.windows(conn)
    assert len(got) == 3
    assert got[0]["window_start"] > got[-1]["window_start"]
    assert isinstance(got[0]["sources"], list) and got[0]["sources"] == ["test"]
    cpu_only = metrics.windows(conn, metric="cpu.busy_pct")
    assert {w["metric"] for w in cpu_only} == {"cpu.busy_pct"} and len(cpu_only) == 2
    assert metrics.windows(conn, window_s=999.0) == []
    assert len(metrics.windows(conn, limit=1)) == 1


def test_latest_is_newest_per_series_with_failures_first(tmp_path):
    rows = [
        _row("cpu.busy_pct", 5.0, ts=T0),
        _row("cpu.busy_pct", 95.0, ts=T0 + 60),
        _row("disk.used_pct", 99.0, ts=T0, scope="C:\\"),
        _row(
            "mem.used_pct",
            None,
            ts=T0,
            error="GlobalMemoryStatusEx failed",
            source=metrics.SRC_CTYPES,
            how=metrics.HOW_WINDOWS_MEM,
        ),
    ]
    conn = _ledger(tmp_path, rows)
    board = metrics.latest(conn, now=T0 + 90)
    assert len(board) == 3, "one row per (host, metric, scope), not one per sample"
    assert board[0]["metric"] == "mem.used_pct"  # the failure sorts first
    assert board[0]["error"]
    assert [r["metric"] for r in board[1:]] == ["disk.used_pct", "cpu.busy_pct"]
    cpu = board[2]
    assert cpu["value"] == 95.0 and cpu["age_s"] == 30.0  # newest sample, real age
    assert board[1]["age_s"] == 90.0
    filtered = metrics.latest(conn, metric="cpu.busy_pct", now=T0)
    assert len(filtered) == 1 and filtered[0]["value"] == 95.0


def test_latest_picks_the_newest_ts_even_when_inserted_out_of_order(tmp_path):
    conn = _ledger(tmp_path, [_row("cpu.busy_pct", 99.0, ts=T0 + 60)])
    metrics.record_samples(
        conn, metrics.stamp_host([_row("cpu.busy_pct", 1.0, ts=T0)], HOST)
    )
    board = metrics.latest(conn, now=T0 + 60)
    assert len(board) == 1 and board[0]["value"] == 99.0 and board[0]["age_s"] == 0.0


def test_series_is_newest_first_and_scope_aware(tmp_path):
    rows = [
        _row("disk.used_pct", 10.0, ts=T0, scope="C:\\"),
        _row("disk.used_pct", 20.0, ts=T0 + 60, scope="C:\\"),
        _row("disk.used_pct", 80.0, ts=T0 + 60, scope="D:\\"),
    ]
    conn = _ledger(tmp_path, rows)
    hist = metrics.series(conn, "disk.used_pct")
    # ORDER BY ts DESC, id DESC — the tie at T0+60 breaks toward the later insert
    assert [r["value"] for r in hist] == [80.0, 20.0, 10.0]
    c_only = metrics.series(conn, "disk.used_pct", scope="C:\\")
    assert [r["value"] for r in c_only] == [20.0, 10.0]
    assert len(metrics.series(conn, "disk.used_pct", limit=1)) == 1
    assert metrics.series(conn, "cpu.busy_pct") == []


# ---- the family gate --------------------------------------------------------


def test_to_diagnostics_gates_disk_pressure_on_its_budget():
    assert metrics.to_diagnostics([_row("disk.used_pct", 50.0, scope="C:\\")]) == []
    warn = metrics.to_diagnostics([_row("disk.used_pct", 88.0, scope="C:\\")])
    assert len(warn) == 1 and warn[0]["severity"] == "warning"
    assert warn[0]["rule"] == "metrics:disk-pressure"
    assert warn[0]["path"] == "disk.used_pct[C:\\]" and "88.0%" in warn[0]["message"]
    assert ">= 85.0%" in warn[0]["message"]
    err = metrics.to_diagnostics([_row("disk.used_pct", 96.0, scope="C:\\")])
    assert err[0]["severity"] == "error" and ">= 95.0%" in err[0]["message"]
    assert "measured by" in err[0]["suggestion"]


def test_to_diagnostics_gives_memory_its_own_looser_budget():
    at_88 = _row("mem.used_pct", 88.0)
    assert metrics.to_diagnostics([at_88]) == [], (
        "88% memory is normal, 88% disk is not"
    )
    assert (
        metrics.to_diagnostics([_row("disk.used_pct", 88.0)])[0]["severity"]
        == "warning"
    )
    assert (
        metrics.to_diagnostics([_row("mem.used_pct", 91.0)])[0]["severity"] == "warning"
    )
    hot = metrics.to_diagnostics([_row("mem.used_pct", 99.0)])
    assert hot[0]["severity"] == "error" and hot[0]["rule"] == "metrics:mem-pressure"


def test_to_diagnostics_thresholds_are_parameters():
    row = _row("disk.used_pct", 60.0, scope="C:\\")
    assert metrics.to_diagnostics([row]) == []
    tight = metrics.to_diagnostics([row], disk_warn_pct=50.0, disk_error_pct=55.0)
    assert tight[0]["severity"] == "error"
    loose = metrics.to_diagnostics([row], disk_warn_pct=99.0, disk_error_pct=99.9)
    assert loose == []
    mem = metrics.to_diagnostics([_row("mem.used_pct", 60.0)], mem_warn_pct=10.0)
    assert mem[0]["severity"] == "warning"


def test_to_diagnostics_separates_unmeasured_from_unsupported():
    failed = _row(
        "cpu.busy_pct",
        None,
        error="exit 1: typeperf: no counters",
        source=metrics.SRC_COUNTER,
        how="typeperf -sc 1",
    )
    unsupported = _row(
        "cpu.busy_pct",
        None,
        error="no counter backend on PATH",
        source=metrics.SRC_UNSUPPORTED,
        how="typeperf | Get-Counter",
    )
    d1 = metrics.to_diagnostics([failed])[0]
    assert d1["severity"] == "warning" and d1["rule"] == "metrics:unmeasured"
    assert "no counters" in d1["message"] and "typeperf -sc 1" in d1["suggestion"]
    assert d1["source"] == "counter"
    d2 = metrics.to_diagnostics([unsupported])[0]
    assert d2["severity"] == "info", (
        "a platform that never had the mechanism is not a page"
    )
    assert d2["rule"] == "metrics:unsupported" and d2["suggestion"] is None
    assert d2["source"] == "unsupported"


def test_to_diagnostics_ignores_metrics_without_a_budget():
    rows = [
        _row("disk.free_bytes", 12.0, unit=metrics.UNIT_BYTES),
        _row("cpu.logical", 32.0, unit=metrics.UNIT_COUNT),
        _row("cpu.busy_pct", 100.0),  # a busy CPU is not an incident by itself
    ]
    assert metrics.to_diagnostics(rows) == []


def test_to_diagnostics_feeds_the_family_summary():
    rows = [
        _row("disk.used_pct", 99.0, scope="C:\\"),
        _row("mem.used_pct", 92.0),
        _row(
            "cpu.busy_pct",
            None,
            error="exit 1",
            source=metrics.SRC_COUNTER,
            how="typeperf",
        ),
    ]
    diags = metrics.to_diagnostics(rows)
    summary = openswap.summarize(diags)
    assert summary["total"] == 3
    assert summary["by_severity"]["error"] == 1
    assert summary["by_severity"]["warning"] == 2
    assert set(summary["by_rule"]) == {
        "metrics:disk-pressure",
        "metrics:mem-pressure",
        "metrics:unmeasured",
    }
    assert diags == openswap.sort_diagnostics(diags)  # stable order for gates


# ---- capability detection ---------------------------------------------------


def test_capability_report_is_honest_about_the_counter_tier():
    from bigbang.plugins.metrics import cli as metrics_cli

    cap = metrics_cli._capability()
    assert cap["adapter"] == "metrics"
    assert cap["tier"] in (openswap.TIER_NATIVE, openswap.TIER_FALLBACK)
    assert cap["native"]["binary"] == "typeperf"
    assert set(cap["extras"]) == {"powershell", "netdata", "telegraf"}
    if cap["native"]["found"]:
        assert cap["tier"] == openswap.TIER_NATIVE
        assert cap["native"]["path"]
    else:
        assert cap["tier"] == openswap.TIER_FALLBACK
        assert "disk and memory" in cap["fallback_scope"]
        assert cap["install_hint"]


def test_metrics_is_discovered_as_a_plugin():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "metrics" in list_plugin_names()


def test_manifest_declares_zero_egress_and_a_scoped_write():
    from bigbang.core.policy import check_permission, load_manifest

    mf = load_manifest(ROOT / "bigbang" / "plugins" / "metrics")
    assert mf["name"] == "metrics"
    assert mf["capabilities"]["network"]["enabled"] is False
    assert mf["capabilities"]["network"]["domains"] == []
    assert mf["capabilities"]["secrets"]["allow"] == []
    assert mf["capabilities"]["filesystem"]["write"] is True
    allowed, _ = check_permission(mf, "fs_write", ".scout/metrics.jsonl")
    assert allowed is True
    denied, reason = check_permission(mf, "network", "https://api.datadoghq.com")
    assert denied is False and "network disabled" in reason
    no_secret, _ = check_permission(mf, "secret", "DD_API_KEY")
    assert no_secret is False


# ---- the CLI envelope (subprocess; local only, no sockets) -----------------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(cwd or ROOT),
    )


def test_cli_metrics_hello_envelope():
    r = _cli(["metrics", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    doc = json.loads(r.stdout)
    assert doc["ok"] is True and doc["command"] == "metrics hello"
    assert doc["data"]["ready"] is True and doc["data"]["plugin"] == "metrics"
    assert doc["data"]["system"] == platform.system()
    assert "example" in doc and "discover" in doc


def test_cli_detect_reports_a_tier():
    r = _cli(["metrics", "detect"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["adapter"] == "metrics"
    assert data["tier"] in ("native", "fallback")
    assert data["native"]["binary"] == "typeperf"


def test_cli_collect_measures_records_and_rolls_up(tmp_path):
    """One real end-to-end pass: measure this box, persist, aggregate, read back."""
    db, log = tmp_path / "m.db", tmp_path / "m.jsonl"
    r = _cli(
        [
            "metrics",
            "collect",
            "--path",
            str(tmp_path),
            "--db",
            str(db),
            "--log",
            str(log),
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["recorded"] is True and data["db"] == str(db)
    assert data["log"]["path"] == str(log) and data["log"]["rows"] == len(
        data["readings"]
    )
    assert data["host"] and data["ts"] > 0
    metrics_seen = {x["metric"] for x in data["readings"]}
    assert {
        "disk.used_pct",
        "disk.free_bytes",
        "mem.used_pct",
        "cpu.logical",
    } <= metrics_seen
    for row in data["readings"]:
        assert row["how"], "a recorded reading with no provenance"
        assert row["source"] in metrics.SOURCES
        assert (row["value"] is None) != (row["error"] is None)
    disk = _pick(data["readings"], "disk.used_pct")
    assert disk["scope"] == str(tmp_path) and 0.0 <= disk["value"] <= 100.0
    assert sum(data["by_source"].values()) == len(data["readings"])

    # the JSONL is the durable record and holds exactly what was reported
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(data["readings"])
    assert json.loads(lines[0])["host"] == data["host"]

    # a second pass appends rather than replacing
    r2 = _cli(
        [
            "metrics",
            "collect",
            "--path",
            str(tmp_path),
            "--db",
            str(db),
            "--log",
            str(log),
        ]
    )
    assert r2.returncode == 0, r2.stderr + r2.stdout
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2 * len(lines)
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 2 * len(lines)
    conn.close()

    # rollup folds them, and re-running does not double-count
    r3 = _cli(["metrics", "rollup", "--db", str(db), "--window", "3600"])
    assert r3.returncode == 0, r3.stderr + r3.stdout
    roll = json.loads(r3.stdout)["data"]
    assert (
        roll["samples"] == 2 * len(lines) and roll["persisted"] == roll["windows_total"]
    )
    assert roll["window_s"] == 3600.0
    first_window = roll["windows"][0]
    assert first_window["sources"] and first_window["n"] + first_window["errors"] >= 1
    again = json.loads(
        _cli(["metrics", "rollup", "--db", str(db), "--window", "3600"]).stdout
    )
    assert again["data"]["windows_total"] == roll["windows_total"]
    conn = sqlite3.connect(str(db))
    assert (
        conn.execute("SELECT COUNT(*) FROM rollups").fetchone()[0]
        == roll["windows_total"]
    )
    conn.close()

    # show reads it back with the log's provenance beside the numbers
    r4 = _cli(["metrics", "show", "--db", str(db), "--log", str(log)])
    assert r4.returncode == 0, r4.stderr + r4.stdout
    show = json.loads(r4.stdout)["data"]
    assert show["log"]["present"] is True and show["log"]["rows"] == 2 * len(lines)
    assert show["log"]["bad_lines"] == 0
    board = show["board"]
    assert board and len(board) == len(lines)  # newest per series, not every sample
    assert all(row["age_s"] >= 0 for row in board)
    assert "summary" in show and "diagnostics" in show

    # persisted windows are readable through show too
    r5 = _cli(["metrics", "show", "--db", str(db), "--windows", "--window", "3600"])
    assert json.loads(r5.stdout)["data"]["windows"], "rollups did not persist"

    # one metric's raw history
    r6 = _cli(
        [
            "metrics",
            "show",
            "--db",
            str(db),
            "--metric",
            "disk.used_pct",
            "--history",
            "5",
        ]
    )
    hist = json.loads(r6.stdout)["data"]["history"]
    assert len(hist) == 2 and all(h["metric"] == "disk.used_pct" for h in hist)
    assert hist[0]["ts"] >= hist[1]["ts"]


def test_cli_no_record_measures_without_touching_disk(tmp_path):
    db, log = tmp_path / "m.db", tmp_path / "m.jsonl"
    r = _cli(
        [
            "metrics",
            "collect",
            "--no-record",
            "--path",
            str(tmp_path),
            "--db",
            str(db),
            "--log",
            str(log),
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["recorded"] is False and data["db"] is None
    assert data["log"]["rows"] == 0 and data["readings"]
    assert not db.exists() and not log.exists()


def test_cli_gate_fires_on_a_budget_the_host_must_exceed(tmp_path):
    """Host-independent gate proof: a 0% warn budget must always trip."""
    r = _cli(
        [
            "metrics",
            "collect",
            "--no-record",
            "--path",
            str(tmp_path),
            "--warn-pct",
            "0",
            "--error-pct",
            "200",
            "--fail-on",
            "warning",
        ]
    )
    assert r.returncode == 1
    data = json.loads(r.stdout)["data"]
    assert data["summary"]["by_severity"]["warning"] >= 1
    assert data["summary"]["by_severity"]["error"] == 0
    assert any(d["rule"] == "metrics:disk-pressure" for d in data["diagnostics"])
    # the same readings under a budget nothing can exceed raise no pressure at all
    loose = _cli(
        [
            "metrics",
            "collect",
            "--no-record",
            "--path",
            str(tmp_path),
            "--warn-pct",
            "100.1",
            "--error-pct",
            "200",
        ]
    )
    assert loose.returncode == 0, loose.stderr + loose.stdout
    loose_diags = json.loads(loose.stdout)["data"]["diagnostics"]
    assert not any(d["rule"].endswith("-pressure") for d in loose_diags)


def test_cli_rejects_a_bad_severity_and_a_bad_window(tmp_path):
    r = _cli(["metrics", "collect", "--no-record", "--fail-on", "sometimes"])
    assert r.returncode == 1
    assert "--fail-on must be one of" in json.loads(r.stdout)["error"]
    db = tmp_path / "m.db"
    metrics.open_ledger(db).close()
    r2 = _cli(["metrics", "rollup", "--db", str(db), "--window", "0"])
    assert r2.returncode == 1
    assert "--window must be > 0" in json.loads(r2.stdout)["error"]
    assert "example" in json.loads(r2.stdout)


def test_cli_show_refuses_to_invent_a_board_without_a_ledger(tmp_path):
    r = _cli(["metrics", "show", "--db", str(tmp_path / "never.db")])
    assert r.returncode == 1
    doc = json.loads(r.stdout)
    assert "no metrics ledger" in doc["error"] and "collect" in doc["example"]
    db = tmp_path / "m.db"
    metrics.open_ledger(db).close()
    r2 = _cli(
        [
            "metrics",
            "show",
            "--db",
            str(db),
            "--metric",
            "disk.used_pct",
            "--history",
            "5",
        ]
    )
    assert r2.returncode == 1
    assert "no samples recorded" in json.loads(r2.stdout)["error"]
