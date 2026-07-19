# Solo personal project, no connection to employer, built with public/free-tier only
"""Implementation worker (worker 2) — hypothesis -> validated, drop-in PyTorch.

The highest-failure-rate stage: LLMs mangle tensor shapes and numerical stability. The worker
calls the real model, then runs the generated code through the 4-level validator with up to
``max_retries`` self-correction passes (each pass hands the exact traceback back to the model).
Only code that passes every runnable level is written to an experiment workspace and advanced to
``ready_for_training``; code that fails all retries is marked ``failed_validation`` honestly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from dottie.research import prompts, validate
from dottie.research.ledger import (
    Ledger, PENDING, READY_FOR_TRAINING, FAILED_VALIDATION,
)

Policy = Callable[[str], str]


def _safe_basename(target_file: Optional[str], fallback: str) -> str:
    name = Path(str(target_file or "")).name
    if not name.endswith(".py") or not name[:-3].isidentifier():
        name = f"{fallback}.py"
    return name


def run_implementation(ledger: Ledger, policy: Policy, *, workspace_root: str | Path,
                       max_retries: int = 3, ts: Optional[float] = None
                       ) -> Optional[Dict[str, Any]]:
    """Implement the oldest pending hypothesis. Returns a summary, or None if none pending.

    Raises ``DottiePolicyUnavailable`` if the model is unreachable on the FIRST call (nothing to
    implement without it) — the experiment stays ``pending`` and is retried later."""
    exp = ledger.next_in_state(PENDING)
    if exp is None:
        return None

    text = policy(prompts.implementation_prompt(exp.hypothesis))  # unavailability propagates
    impl = dry = None
    parse_attempts = 0
    while True:
        try:
            impl, dry = prompts.parse_implementation(text)
            break
        except ValueError as e:
            # Unparseable draft: feed the exact parse failure back through the same correction
            # path validation failures use, consuming the same retry budget. All-unparseable is
            # recorded as an honest failed_validation dead end, never an unhandled crash.
            parse_attempts += 1
            if parse_attempts > max_retries:
                ledger.transition(
                    exp.id, FAILED_VALIDATION, attempts=parse_attempts,
                    failure=f"implementation output unparseable after {parse_attempts} "
                            f"attempt(s): {e}", ts=ts)
                return {"experiment": exp.id, "state": FAILED_VALIDATION,
                        "level": "parse", "attempts": parse_attempts}
            feedback = (f"Validation failed at level 'parse' (fail). Detail:\n{e}\n"
                        "Your entire response must be ONE JSON object matching the "
                        "implementation schema — no markdown fences, no prose, and every "
                        "string field valid JSON (escape backslashes and newlines).")
            text = policy(prompts.correction_prompt(text, feedback))

    # Holder tracks the latest parsed impl/dry as the corrector re-calls the model, so the final
    # written module matches outcome.code.
    latest = {"impl": impl, "dry": dry}

    def corrector(prev_code: str, feedback: str) -> str:
        new_text = policy(prompts.correction_prompt(prev_code, feedback))
        new_impl, new_dry = prompts.parse_implementation(new_text)
        latest["impl"], latest["dry"] = new_impl, new_dry
        return new_impl["code"]

    ws = Path(workspace_root) / exp.id
    ws.mkdir(parents=True, exist_ok=True)
    outcome = validate.validate_with_correction(
        impl["code"], corrector, max_retries=max_retries,
        class_name=dry["class_name"], init_kwargs=dry["init_kwargs"],
        input_shape=dry["input_shape"], workdir=ws,
    )

    final_impl = dict(latest["impl"])
    final_dry = dict(latest["dry"])
    final_impl["code"] = outcome.code  # authoritative final code
    final_impl["dry_run"] = final_dry
    final_impl["validation"] = {
        "ok": outcome.ok, "attempts": outcome.attempts,
        "level": outcome.result.level, "status": outcome.result.status,
        "per_level": outcome.result.per_level, "history": outcome.history,
    }

    if outcome.ok:
        module_path = ws / _safe_basename(final_impl.get("target_file"), exp.id)
        module_path.write_text(outcome.code, encoding="utf-8")
        ledger.transition(exp.id, READY_FOR_TRAINING, implementation=final_impl,
                          workspace=str(ws), attempts=outcome.attempts, ts=ts)
        return {"experiment": exp.id, "state": READY_FOR_TRAINING,
                "module": final_impl.get("module_name"), "attempts": outcome.attempts,
                "module_path": str(module_path)}

    ledger.transition(exp.id, FAILED_VALIDATION, implementation=final_impl, workspace=str(ws),
                      attempts=outcome.attempts,
                      failure=f"validation failed at '{outcome.result.level}' after "
                              f"{outcome.attempts} self-correction attempt(s): "
                              f"{outcome.result.detail[:500]}", ts=ts)
    return {"experiment": exp.id, "state": FAILED_VALIDATION,
            "level": outcome.result.level, "attempts": outcome.attempts}
