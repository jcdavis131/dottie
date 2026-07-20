"""Mutation audit for the research loop's gate tests.

    apps/dottie> .venv/Scripts/python.exe scripts/mutation_audit.py

Every gate in this loop exists because the loop once reported a result that looked right
and was not. The tests guarding those gates deserve the same suspicion: a test that only
goes red with AttributeError/KeyError/ImportError is proving a symbol EXISTS, not that
the logic works — and three tests written on 2026-07-20 turned out to be exactly that
before being rewritten (TODOS §5.3.R7).

Each mutation below leaves every symbol in place and breaks only behaviour, so a test
that survives is hollow. Verdicts:

    GOOD    — test failed on an assertion about behaviour
    WEAK    — test failed, but on a structural error (proves little)
    HOLLOW  — test PASSED with the logic broken; it is not guarding anything

Mutations are applied one at a time and always reverted in a `finally`. Add a row to
MUTANTS whenever a new gate lands.
"""
import pathlib
import re
import subprocess

APP = pathlib.Path(__file__).resolve().parents[1]
PY = APP / ".venv" / "Scripts" / "python.exe"

MUTANTS = [
    ("evaluate.py", "        base_sem = baseline.metric_sem",
     "        base_sem = None",
     "two_sample_significance", "gate ignores the baseline's recorded SEM"),
    # Anchor on the RETURN of the contaminated verdict, not on the `if res.ok:` guard the
    # R14 fix rewrote around. That rewrite silently turned this row into a SKIP, leaving the
    # contamination gate unaudited until the SKIP line was read — which is the whole reason
    # this script prints SKIP loudly instead of just omitting the row.
    # NB: `return None or (...)` would be a NO-OP mutation — `None or X` is `X`. Writing it
    # that way produced a HOLLOW verdict that was true of the mutant, not of the test. An
    # unconditional early return is the real suppression.
    ("evaluate.py", '    return (f"CONTAMINATED BASELINE — the experiment that set it',
     '    return None\n    return (f"CONTAMINATED BASELINE — the experiment that set it',
     "contaminated_baseline", "contamination verdict suppressed"),
    ("implementation.py", "    for entry in reversed(getattr(outcome, \"history\", []) or []):",
     "    for entry in []:",
     "corrector_failure_is_distinguished", "corrector error never found in history"),
    ("evaluate.py", "                                metric_sem=None if sp is None else sp[\"sem\"],",
     "                                metric_sem=None,",
     "records_the_baselines_spread", "promotion drops the winning run's spread"),
    ("validate.py", "        if in_spread > 1e-6 and out_spread <= 1e-6:",
     "        if False:",
     "rank_collapsing_block", "rank-collapse gate disabled"),
    ("validate.py", "        if n_params == 0:\n            return ValidationResult(\n"
                    "                False, \"dry_run\", \"fail\",\n"
                    "                \"no learnable parameters:",
     "        if False:\n            return ValidationResult(\n"
     "                False, \"dry_run\", \"fail\",\n"
     "                \"no learnable parameters:",
     "zero_parameter_block", "zero-parameter gate disabled"),
    ("validate.py", "        if tuple(out.shape) != tuple(x.shape):",
     "        if False:",
     "shape_change_that_only", "residual-stream shape check disabled"),
    ("validate.py", "        base = torch.randn(*shape, generator=torch.Generator().manual_seed(1234),\n"
                    "                           requires_grad=True)",
     "        base = torch.randn(*shape, generator=torch.Generator().manual_seed(1234),\n"
     "                           requires_grad=False)",
     "reading_input_grad", "probe input no longer requires grad (the whole point)"),
    # Gates added after the first audit. Each leaves every symbol in place and breaks only
    # behaviour, per the rule at the top of this file.
    ("validate.py", "    target = [shape[0], int(seq), int(width)]",
     "    target = [shape[0], shape[1], int(width)]",
     "sequence_sized_parameter", "integration probe stops using the real seq (R28)"),
    ("train.py", "    finals = [p for p in pys if not p.name.startswith(\"candidate_\")]\n"
                 "    pool = finals or pys",
     "    finals = []\n    pool = finals or pys",
     "loads_the_validated_module", "loader stops preferring the real module (R49)"),
    ("__main__.py", "    if avail is None or avail >= floor:",
     "    if True:",
     "memory_guard_refuses", "memory guard never refuses (R52)"),
    ("ideation.py", "            except Exception as dump_err:",
     "            except ZeroDivisionError as dump_err:",
     "failing_dump", "dump failure escapes and masks the parse error (R58)"),
    ("train.py", "        return TrainResult(True, False, metrics={\"integration\": \"proxy_micro_benchmark\",\n"
                 "                                                 \"detail\": \"candidate module not loadable\"},",
     "        return TrainResult(False, False, metrics={\"integration\": \"proxy_micro_benchmark\",\n"
     "                                                 \"detail\": \"candidate module not loadable\"},",
     "unloadable_candidate", "load failure treated as retryable infra again"),
]

STRUCTURAL = ("AttributeError", "KeyError", "ImportError", "ModuleNotFoundError", "NameError")

for fname, old, new, testk, desc in MUTANTS:
    target = APP / "dottie" / "research" / fname
    src = target.read_text(encoding="utf-8")
    if old not in src:
        print(f"SKIP  {testk:38s} (anchor not in {fname})")
        continue
    backup = src
    target.write_text(src.replace(old, new, 1), encoding="utf-8")
    try:
        r = subprocess.run([str(PY), "-m", "pytest", "tests/test_research.py", "-k", testk,
                            "-x", "--no-header", "-q", "--color=no"],
                           cwd=str(APP), capture_output=True, text=True, timeout=300)
        out = re.sub(r"\[[0-9;]*m", "", r.stdout + r.stderr)
        passed = " 1 passed" in out or ("passed" in out and "failed" not in out)
        structural = [s for s in STRUCTURAL if s in out]
        if passed:
            verdict = "HOLLOW — test SURVIVED the mutation"
        elif structural:
            verdict = f"WEAK — failed on {structural[0]}, not behaviour"
        else:
            m = re.search(r"^E\s+\W*(.*)$", out, re.M)
            verdict = f"GOOD — behavioural: {(m.group(1).strip()[:60] if m else '?')}"
        print(f"{verdict}\n      test={testk}  mutation={desc}\n")
    finally:
        target.write_text(backup, encoding="utf-8")
print("all mutations reverted")
