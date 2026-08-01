#!/usr/bin/env python3
"""Measure what this GPU actually delivers, and compare it to the MFU denominator.

WHY THIS EXISTS. `train.py::_get_gpu_peak_flops` looks its answer up by substring and has
no laptop rows, so an "RTX 4080 Laptop GPU" matches the "4080" entry and is credited
242.5 TFLOPS — the DESKTOP AD103 figure. That constant is the denominator of MFU, the
headline metric this repo reports, so getting it wrong silently rescales every MFU number
the trainer prints.

The failure is quiet in the dangerous direction. Too LARGE a denominator makes MFU read
LOW, so the box looks badly tuned rather than badly measured, and the natural reaction to
a low MFU — tune harder, chase the missing throughput — is chasing something that was
never there.

WHAT THIS MEASURES, stated precisely because the distinction is the whole point.
It measures ACHIEVED dense BF16 matmul throughput: a square `a @ b`, the most FLOP-dense
and cache-friendly kernel available, run at several sizes. It does NOT measure theoretical
peak, and it deliberately does not try to. A theoretical peak cannot be measured, only
looked up or derived from SM count and clocks — and typing in a plausible-looking TFLOPS
figure is exactly the fabricated constant this repo's numbers rule exists to keep out.

WHAT THE RESULT LICENSES YOU TO CONCLUDE. Achieved <= peak always, so this measurement is
a LOWER bound on the card's true peak and proves nothing about the 242.5 constant directly.
Read in the other direction it is much sharper: a real training step cannot beat a pure
matmul, so `achieved / constant` is a CEILING ON REPORTABLE MFU. If that ratio is 0.29,
then no training loop on this machine — however perfect — can print an MFU above ~29%, and
any target above it is unreachable by construction rather than by inefficiency.

The run also samples power and clocks concurrently, because a throttled measurement is not
a representative one. If the card is nowhere near its power limit the number is soft and
the ceiling argument is weak; near the limit, the reading is what the hardware actually
does. Read the reported watts before trusting the ratio.

    python scripts/measure_bf16_ceiling.py

Reporting tool, always exit 0. It is deliberately NOT a gate: it needs a GPU, scout-rtx is
excluded from CI (pyproject.toml:13, cu128 + Windows), and a check that cannot run where
it is enforced is the permanently-red gate this repo already learned to distrust.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading

SIZES = (4096, 8192, 12288)
ITERS = 12
WARMUP = 5
_SMI_FIELDS = "power.draw,clocks.sm,temperature.gpu,utilization.gpu"


def _sample_gpu(stop_event, out):
    """Poll nvidia-smi until stop_event; keep the peaks seen while the GPU is busy."""
    while not stop_event.is_set():
        try:
            raw = subprocess.run(
                ["nvidia-smi", f"--query-gpu={_SMI_FIELDS}",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip().splitlines()
        except (OSError, subprocess.SubprocessError):
            return
        if not raw:
            continue
        try:
            power, clock, temp, util = (float(v) for v in raw[0].split(","))
        except ValueError:
            continue
        # Idle samples would drag the peaks down and hide throttling; only count load.
        if util > 50:
            out["busy_samples"] += 1
            out["max_power_w"] = max(out["max_power_w"], power)
            out["max_clock_mhz"] = max(out["max_clock_mhz"], clock)
            out["max_temp_c"] = max(out["max_temp_c"], temp)
        # No sleep. Each nvidia-smi spawn already costs ~50-100 ms, and an added delay
        # cost real accuracy: at 0.2 s this caught 3 busy samples and reported a 122 W
        # peak for a run a tighter loop measured at 160 W. Undersampling biases the peak
        # DOWNWARD, which would understate how power-limited the card is and make the
        # ceiling below look softer than it is.


def _lookup_constant(gpu_name):
    """The TFLOPS figure train.py would use as this device's MFU denominator.

    Read from `train._get_gpu_peak_flops` rather than duplicated here — a second copy of
    the table would drift from the real one and this tool would then compare the measured
    throughput against a denominator the trainer does not actually use.

    train.py imports rustbpe/tiktoken at module level and those are absent from the cu128
    env this script runs under, so the first version silently reported a null denominator
    and printed no ceiling at all — the one number the tool exists to produce. The missing
    modules are stubbed, exactly as tests/conftest.py does, because the lookup is pure and
    touches none of them. Returns None only if the import genuinely cannot be salvaged.
    """
    import importlib
    import types

    for name in ("rustbpe", "tiktoken", "wandb"):
        if name not in sys.modules:
            try:
                importlib.import_module(name)
            except ImportError:
                sys.modules[name] = types.ModuleType(name)
    # pyarrow needs its `parquet` submodule registered separately: train.py does
    # `import pyarrow.parquet`, and a bare ModuleType fails that with "not a package".
    # Same shape tests/conftest.py already uses, for the same reason.
    if "pyarrow" not in sys.modules:
        try:
            importlib.import_module("pyarrow.parquet")
        except ImportError:
            pyarrow = types.ModuleType("pyarrow")
            parquet = types.ModuleType("pyarrow.parquet")
            pyarrow.parquet = parquet
            sys.modules["pyarrow"] = pyarrow
            sys.modules["pyarrow.parquet"] = parquet
    try:
        import train

        return train._get_gpu_peak_flops(gpu_name)
    except Exception as exc:
        # Broad on purpose: train.py's import surface is large and this tool must still
        # report the throughput it measured even when the denominator cannot be read.
        # Printed rather than swallowed — a silent None here is what made the first
        # version emit no ceiling at all, which is the number the tool exists for.
        print(f"could not read the denominator from train.py: {exc!r}", file=sys.stderr)
        return None


def main() -> int:
    try:
        import torch
    except ImportError:
        print("torch not importable — run this with the cu128 env scout-rtx pins")
        return 0
    if not torch.cuda.is_available():
        print("no CUDA device visible; nothing to measure")
        return 0

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

    props = torch.cuda.get_device_properties(0)
    dev = torch.device("cuda")
    torch.backends.cuda.matmul.allow_tf32 = True

    telemetry = {"busy_samples": 0, "max_power_w": 0.0,
                 "max_clock_mhz": 0.0, "max_temp_c": 0.0}
    stop = threading.Event()
    sampler = threading.Thread(target=_sample_gpu, args=(stop, telemetry), daemon=True)
    sampler.start()

    runs = []
    for n in SIZES:
        try:
            a = torch.randn(n, n, device=dev, dtype=torch.bfloat16)
            b = torch.randn(n, n, device=dev, dtype=torch.bfloat16)
        except torch.cuda.OutOfMemoryError:
            runs.append({"n": n, "error": "OOM"})
            continue
        for _ in range(WARMUP):
            a @ b
        torch.cuda.synchronize()

        flops = 2.0 * n * n * n
        best = 0.0
        for _ in range(ITERS):
            t0 = torch.cuda.Event(enable_timing=True)
            t1 = torch.cuda.Event(enable_timing=True)
            t0.record()
            a @ b
            t1.record()
            torch.cuda.synchronize()
            # BEST of N, not mean: the question is what the card CAN reach, and a laptop's
            # slower samples reflect power/thermal state rather than the ceiling.
            best = max(best, flops / (t0.elapsed_time(t1) / 1000.0) / 1e12)
        runs.append({"n": n, "best_tflops": round(best, 1)})
        del a, b
        torch.cuda.empty_cache()

    stop.set()
    sampler.join(timeout=2)

    achieved = max((r["best_tflops"] for r in runs if "best_tflops" in r), default=None)

    constant = _lookup_constant(props.name)

    report = {
        "device": props.name,
        "sm_count": props.multi_processor_count,
        "total_mem_gb": round(props.total_memory / 1024**3, 2),
        "capability": f"{props.major}.{props.minor}",
        "torch": torch.__version__,
        "runs": runs,
        "achieved_bf16_tflops": achieved,
        "mfu_denominator_tflops": None if constant is None else constant / 1e12,
        "telemetry_during_run": telemetry,
    }
    if achieved and constant:
        report["max_reportable_mfu"] = round(achieved / (constant / 1e12), 3)

    json.dump(report, sys.stdout, indent=2)
    print()

    if report.get("max_reportable_mfu") is not None:
        cap = report["max_reportable_mfu"]
        print(
            f"\nCEILING: a pure BF16 matmul reaches {achieved} TFLOPS while MFU is divided "
            f"by {constant / 1e12} TFLOPS,\nso no training run on this device can report an "
            f"MFU above ~{cap * 100:.0f}%. Any target above that is\nunreachable by "
            f"construction, not by tuning."
        )
        if telemetry["busy_samples"]:
            print(
                f"\nMeasurement conditions: peak {telemetry['max_power_w']:.0f} W, "
                f"{telemetry['max_clock_mhz']:.0f} MHz SM, {telemetry['max_temp_c']:.0f} C "
                f"over {telemetry['busy_samples']} busy samples.\n"
                "This wattage is a LOWER BOUND, not a reading: each nvidia-smi spawn costs "
                "~50-100 ms, so\nthe sampler misses peaks and has printed anything from "
                "121 W to 158 W for one workload\n(a tight external loop measured 160 W). "
                "A low number here therefore does NOT establish\nthrottling — re-measure "
                "with a tight loop before concluding the ceiling above is soft."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
