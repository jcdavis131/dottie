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


def _corrector_error(outcome) -> Optional[str]:
    """The corrector's own exception, if the retry loop stopped because of one.

    `validate_with_correction` breaks out early when the CORRECTOR raises (Ollama
    unreachable, read timeout, unparseable reply) and records it only in `history`. The
    stored failure was built from the last validation result alone, so an experiment
    abandoned because the LLM was down looked identical to one that genuinely failed
    validation on its merits — and its `attempts` count silently stopped short of
    `max_retries` with no explanation (observed 2026-07-20: 48e0f39d8225, attempts=2 of 5).
    That distinction matters: one is the candidate's fault, the other is infrastructure."""
    for entry in reversed(getattr(outcome, "history", []) or []):
        if isinstance(entry, dict) and entry.get("corrector_error"):
            return str(entry["corrector_error"])[:300]
    return None


def _corrector_note(outcome) -> str:
    err = _corrector_error(outcome)
    return f" — STOPPED EARLY, the corrector itself failed: {err}" if err else ""


def _keep_tail(detail: str, limit: int = 800) -> str:
    """Keep the END of a failure detail, not the start.

    Python puts the exception type and message on the LAST line of a traceback, so the
    previous `detail[:500]` stored the "Traceback (most recent call last):" header and the
    outermost frames while discarding the only line that says what actually broke.
    Measured 2026-07-20: 36 of the 40 most recent `failed_validation` records were
    unclassifiable for exactly this reason, which makes conversion-rate analysis (TODOS
    §5.2) impossible. Short details are returned untouched."""
    if len(detail) <= limit:
        return detail
    return "...[head truncated]... " + detail[-limit:]


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
                              f"{outcome.attempts} self-correction attempt(s)"
                              f"{_corrector_note(outcome)}: "
                              f"{_keep_tail(outcome.result.detail)}", ts=ts)
    return {"experiment": exp.id, "state": FAILED_VALIDATION,
            "level": outcome.result.level, "attempts": outcome.attempts,
            "corrector_error": _corrector_error(outcome)}
