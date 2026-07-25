#!/usr/bin/env python3
"""Throwaway test-honesty harness: gut a behavior, prove the suite notices.

Not a deliverable — this file is deleted after the run. Every mutation below
removes ONE honesty guarantee from bigbang/core/ollama.py; a mutation that
leaves the suite green is a defect in the tests, not a pass.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent / "bigbang" / "core" / "ollama.py"

MUTATIONS = [
    (
        "banner: degraded output stops announcing itself",
        '    lines = [\n        DEGRADED_BANNER,',
        '    lines = [\n        "Here is the answer:",',
    ),
    (
        "placement: an absent size_vram is reported as gpu",
        "    if size_vram is None:\n        return PLACEMENT_UNKNOWN",
        "    if size_vram is None:\n        return PLACEMENT_GPU",
    ),
    (
        "pick_model: a named-but-absent model is silently substituted",
        '        return None, f"{want!r} is not installed — installed: {names}"',
        '        return names[0], "substituted"',
    ),
    (
        "ledger: the prompt text is stored after all",
        '            rec.get("prompt_sha256", ""),',
        '            str(rec.get("text") or "")[:200],',
    ),
    (
        "candidate_bases: an explicit base becomes a mere first guess",
        "    if explicit and str(explicit).strip():\n        try:\n            return [normalize_base(explicit)]\n        except ValueError:\n            return []",
        "    pass",
    ),
    (
        "parse_completion: reasoning is passed off as the answer",
        '    if not isinstance(text, str) or not text.strip():\n        return None\n    model = payload.get("model")',
        '    if not isinstance(text, str) or not text.strip():\n        text = payload.get("thinking") or ""\n        if not text.strip():\n            return None\n    model = payload.get("model")',
    ),
    (
        "usage: an empty ledger reports 0% model share instead of None",
        '        "model_share_pct": (\n            round(100.0 * by_source[SOURCE_MODEL] / total, 2) if total else None\n        ),',
        '        "model_share_pct": round(100.0 * by_source[SOURCE_MODEL] / max(1, total), 2),',
    ),
    (
        "no_answer_reason: the thinking-budget case is reported as a broken daemon",
        '    if payload.get("done_reason") == "length":',
        '    if False:',
    ),
]


def run_subset() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_ollama.py", "-q", "-x",
         "-k", "not test_cli_", "--no-header", "-p", "no:cacheprovider"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(CORE.parents[2]), timeout=600,
    )
    tail = [ln for ln in r.stdout.splitlines() if "passed" in ln or "failed" in ln]
    return r.returncode, (tail[-1] if tail else r.stdout[-200:])


def main() -> int:
    original = CORE.read_text(encoding="utf-8")
    baseline_rc, baseline = run_subset()
    print(f"baseline: rc={baseline_rc}  {baseline}")
    if baseline_rc != 0:
        print("baseline is not green — fix that first")
        return 1
    survivors = []
    try:
        for label, old, new in MUTATIONS:
            if old not in original:
                print(f"SKIP (anchor missing): {label}")
                survivors.append(label)
                continue
            CORE.write_text(original.replace(old, new, 1), encoding="utf-8")
            rc, summary = run_subset()
            verdict = "caught" if rc != 0 else "SURVIVED"
            print(f"{verdict:9} {label}  ({summary})")
            if rc == 0:
                survivors.append(label)
    finally:
        CORE.write_text(original, encoding="utf-8")
    rc2, restored = run_subset()
    print(f"restored: rc={rc2}  {restored}")
    print(f"\nsurvivors: {len(survivors)}/{len(MUTATIONS)}")
    for s in survivors:
        print(f"  - {s}")
    return 0 if not survivors and rc2 == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
