#!/usr/bin/env python3
"""Local-only Trackio wrapper for HELPER FT. Fail-open. Never a gate.

Optional: ``pip install trackio``. API is wandb-compatible
(``trackio.init`` / ``log`` / ``finish``). Missing trackio, import errors,
and any tracker exception log a warning and leave the integrity gate
unchanged. A REFUSED gate still refuses.

Trackio is a dashboard, never stamp-gate evidence. Logged values are not a
verdict. Verdicts come only from the sha-pinned results files and the HQ events.

Local only: never passes ``space_id`` / ``server_url`` / tokens, never calls
``sync`` or ``show``, never writes under ``trust/`` or dataset/factory data
paths. Storage defaults to ``<run_dir>/trackio`` and is overridden by
``DOTTIE_HELPER_FT_TRACKIO_DIR`` (or ``TRACKIO_DIR``). Set
``DOTTIE_HELPER_FT_TRACKIO=0`` to disable.
"""
from __future__ import annotations

import ast
import importlib
import json
import logging
import os
import re
import socket
import tempfile
import warnings
from pathlib import Path
from typing import Any, Mapping

PROJECT = "dottie-helper-ft"
DIR_ENV = "DOTTIE_HELPER_FT_TRACKIO_DIR"
ENABLE_ENV = "DOTTIE_HELPER_FT_TRACKIO"
TRACKIO_DIR_ENV = "TRACKIO_DIR"
SHA256_LEN = 64
_HEX = frozenset("0123456789abcdef")
# Hub / remote knobs we strip so a inherited env cannot sync.
_HUB_ENV = (
    "TRACKIO_SPACE_ID",
    "TRACKIO_DATASET_ID",
    "TRACKIO_SERVER_URL",
    "TRACKIO_WRITE_TOKEN",
)
_BLOCKED_PATH_MARKERS = (
    "/trust/",
    "/apps/dottie-os/trust",
    "/dataset/",
    "/datasets/",
    "/factory/",
    "/ava-factory/",
)
_LOSS_KEYS = ("loss", "train_loss", "eval_loss", "train/loss", "eval/loss")
_LOSS_KV = re.compile(
    r"(?i)\b((?:train[_/-]?|eval[_/-]?)?loss)\s*[=:]\s*"
    r"([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
)
_EPOCH_KV = re.compile(r"(?i)\bepoch\b\s*[=:]\s*([0-9]+(?:\.[0-9]+)?)")
_STEP_KV = re.compile(r"(?i)\bstep\b\s*[=:]\s*([0-9]+)")
_EVAL_ALIASES: dict[str, tuple[str, ...]] = {
    "choice": ("choice", "Choice", "choice_acc", "choice_score"),
    "score": ("score", "Score", "score_acc"),
    "noul": ("noul", "Noul", "noul_auc"),
    "halt_recall": ("halt_recall", "halt-recall", "haltRecall"),
    "over_halt": ("over_halt", "over-halt", "overHalt"),
    "veto_fail": ("veto_fail", "veto-fail", "veto_fail_count", "vetoFail"),
}

log = logging.getLogger(__name__)

# Optional dependency resolved at call time so tests can inject a fake module.
_trackio_mod: Any = None
_trackio_missing_warned = False
_sessions: dict[str, "RunSession"] = {}


def _enabled() -> bool:
    value = os.environ.get(ENABLE_ENV, "").strip().lower()
    return value not in {"0", "off", "false", "no", "disable", "disabled"}


def _warn(message: str) -> None:
    warnings.warn(message, RuntimeWarning, stacklevel=2)
    log.warning(message)


def _get_trackio() -> Any | None:
    """Import trackio if present. Documented optional import; fail-open."""
    global _trackio_mod, _trackio_missing_warned
    if not _enabled():
        return None
    if _trackio_mod is not None:
        return _trackio_mod
    try:
        _trackio_mod = importlib.import_module("trackio")
        return _trackio_mod
    except Exception as exc:
        if not _trackio_missing_warned:
            _trackio_missing_warned = True
            _warn(
                f"HELPER FT trackio unavailable ({type(exc).__name__}: {exc}); "
                "run proceeds without tracking"
            )
        return None


def _is_blocked_storage(path: Path) -> bool:
    try:
        text = str(path.resolve()).replace("\\", "/").lower()
    except OSError:
        text = str(path).replace("\\", "/").lower()
    if text.endswith("/trust"):
        return True
    return any(marker in text for marker in _BLOCKED_PATH_MARKERS)


def resolve_storage_dir(run_dir: Path | None = None) -> Path:
    """Pick a local storage dir outside trust/ and dataset/factory paths."""
    for env_name in (DIR_ENV, TRACKIO_DIR_ENV):
        raw = os.environ.get(env_name)
        if not raw:
            continue
        candidate = Path(raw)
        if _is_blocked_storage(candidate):
            _warn(
                f"HELPER FT trackio ignoring blocked {env_name}={candidate}; "
                "falling back to run-dir storage"
            )
            break
        return candidate
    if run_dir is not None:
        candidate = Path(run_dir) / "trackio"
        if not _is_blocked_storage(candidate):
            return candidate
        _warn(f"HELPER FT trackio run-dir storage blocked ({candidate}); using temp dir")
    return Path(tempfile.mkdtemp(prefix="helper-ft-trackio-"))


def _local_only_env(storage: Path) -> dict[str, str | None]:
    saved: dict[str, str | None] = {
        key: os.environ.get(key) for key in (*_HUB_ENV, TRACKIO_DIR_ENV, "TRACKIO_STORAGE_MODE")
    }
    os.environ[TRACKIO_DIR_ENV] = str(storage)
    os.environ["TRACKIO_STORAGE_MODE"] = "jsonl"
    for key in _HUB_ENV:
        os.environ.pop(key, None)
    return saved


def _restore_env(saved: Mapping[str, str | None]) -> None:
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _safe_call(label: str, fn: Any, *args: Any, **kwargs: Any) -> bool:
    try:
        fn(*args, **kwargs)
        return True
    except Exception as exc:
        _warn(
            f"HELPER FT trackio {label} failed ({type(exc).__name__}: {exc}); "
            "run proceeds without tracking"
        )
        return False


def _scalar(value: object) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None


def config_from_evidence(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build the init config: shas, row counts, git HEAD, host, run id."""
    ev = dict(evidence or {})
    shas = ev.get("computed_shas") if isinstance(ev.get("computed_shas"), Mapping) else {}
    expected = ev.get("expected_shas") if isinstance(ev.get("expected_shas"), Mapping) else {}
    pin = ev.get("pin") if isinstance(ev.get("pin"), Mapping) else {}
    rows = ev.get("row_counts") if isinstance(ev.get("row_counts"), Mapping) else {}
    pack_rows = rows.get("curated_pack_v2.jsonl") if isinstance(rows.get("curated_pack_v2.jsonl"), Mapping) else {}
    train_rows = (
        rows.get("curated_pack_v2_train.jsonl")
        if isinstance(rows.get("curated_pack_v2_train.jsonl"), Mapping)
        else {}
    )
    hold_rows = (
        rows.get("curated_pack_v2_holdout.jsonl")
        if isinstance(rows.get("curated_pack_v2_holdout.jsonl"), Mapping)
        else {}
    )
    trainer = ev.get("trainer_config") if isinstance(ev.get("trainer_config"), Mapping) else {}
    config: dict[str, Any] = {
        "run_id": ev.get("run_id"),
        "pack_id": ev.get("pack_id") or pin.get("pack_id"),
        "sha256_pack": shas.get("sha256_pack") or expected.get("sha256_pack") or pin.get("sha256_pack"),
        "sha256_train": shas.get("sha256_train") or expected.get("sha256_train") or pin.get("sha256_train"),
        "sha256_holdout": shas.get("sha256_holdout") or expected.get("sha256_holdout") or pin.get("sha256_holdout"),
        "rows_total": pin.get("rows_total") if pin.get("rows_total") is not None else pack_rows.get("actual"),
        "rows_train": pin.get("rows_train") if pin.get("rows_train") is not None else train_rows.get("actual"),
        "rows_holdout": pin.get("rows_holdout") if pin.get("rows_holdout") is not None else hold_rows.get("actual"),
        "git_head": ev.get("head_sha") or ev.get("script_git_sha"),
        "host": ev.get("host") or socket.gethostname(),
    }
    for key, value in trainer.items():
        if key in {"paths"} or not _scalar(value):
            continue
        config.setdefault(key, value)
    return {key: value for key, value in config.items() if value is not None}


def _reason_payload(reason: object) -> dict[str, Any]:
    if hasattr(reason, "field"):
        return {
            "status": "refused",
            "reason": str(reason),
            "field": getattr(reason, "field", None),
            "expected": getattr(reason, "expected", None),
            "actual": getattr(reason, "actual", None),
        }
    if isinstance(reason, Mapping):
        payload = {
            "status": "refused",
            "reason": str(reason.get("error") or reason.get("reason") or reason.get("field") or "refused"),
            "field": reason.get("field"),
            "expected": reason.get("expected"),
            "actual": reason.get("actual"),
        }
        return {key: value for key, value in payload.items() if value is not None}
    return {"status": "refused", "reason": str(reason)}


def parse_trainer_losses(text: str) -> list[dict[str, Any]]:
    """Extract per-step/epoch losses from trainer stdout or a run log."""
    if not text:
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = _parse_mapping_line(line)
        if parsed is not None:
            rows.append(parsed)
            continue
        kv_hits = list(_LOSS_KV.finditer(line))
        if not kv_hits:
            continue
        row: dict[str, Any] = {}
        for match in kv_hits:
            key = match.group(1).lower().replace("-", "_").replace("/", "_")
            row[key] = float(match.group(2))
        epoch = _EPOCH_KV.search(line)
        if epoch:
            row["epoch"] = float(epoch.group(1))
        step = _STEP_KV.search(line)
        if step:
            row["step"] = int(step.group(1))
        rows.append(row)
    return rows


def _parse_mapping_line(line: str) -> dict[str, Any] | None:
    text = line.strip().rstrip(",")
    if not (text.startswith("{") and text.endswith("}")):
        return None
    obj: object
    try:
        obj = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        try:
            obj = json.loads(text.replace("'", '"'))
        except ValueError:
            return None
    if not isinstance(obj, dict):
        return None
    if not any(key in obj for key in _LOSS_KEYS):
        return None
    out: dict[str, Any] = {}
    for key, value in obj.items():
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            continue
        if isinstance(value, str):
            try:
                value = float(value) if "." in value or "e" in value.lower() else int(value)
            except ValueError:
                continue
        out[str(key)] = value
    return out or None


def validate_results_sha256(value: object) -> str | None:
    """Require 64-char lowercase hex. Missing/malformed → warn and skip."""
    if type(value) is not str or not value:
        _warn(
            "HELPER FT trackio log_eval_scores missing results_sha256; "
            "skipped (Trackio is not stamp-gate evidence)"
        )
        return None
    if len(value) != SHA256_LEN or any(ch not in _HEX for ch in value):
        _warn(
            "HELPER FT trackio log_eval_scores results_sha256 must be "
            "64-char lowercase hex; skipped (Trackio is not stamp-gate evidence)"
        )
        return None
    return value


def normalize_eval_scores(scores: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical Choice/Score/Noul + halt/veto counts for Critic eval."""
    out: dict[str, Any] = {}
    for canonical, aliases in _EVAL_ALIASES.items():
        for alias in aliases:
            if alias in scores:
                out[canonical] = scores[alias]
                break
    for key, value in scores.items():
        if key in out:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[str(key)] = value
    return out


def launch_text(launched: Mapping[str, Any] | None, log_path: Path | None = None) -> str:
    parts: list[str] = []
    if isinstance(launched, Mapping):
        for key in ("stdout", "stderr", "log", "trainer_output", "output"):
            value = launched.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)
    if log_path is not None:
        path = Path(log_path)
        try:
            if path.is_file():
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "\n".join(parts)


class RunSession:
    """One HELPER FT run. All methods fail-open and never raise to the gate."""

    def __init__(self, run_id: str | None = None, run_dir: Path | None = None) -> None:
        self.run_id = run_id
        self.run_dir = Path(run_dir) if run_dir is not None else None
        self.storage_dir: Path | None = None
        self.inited = False
        self.finished = False

    def start(self, config: Mapping[str, Any] | None = None, *, run_id: str | None = None) -> bool:
        if run_id:
            self.run_id = run_id
        if not self.run_id:
            return False
        if self.inited:
            return True
        module = _get_trackio()
        if module is None:
            return False
        self.storage_dir = resolve_storage_dir(self.run_dir)
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _warn(f"HELPER FT trackio storage mkdir failed ({exc}); continuing without tracking")
            return False
        payload = dict(config or {})
        payload.setdefault("run_id", self.run_id)
        payload.setdefault("host", socket.gethostname())
        saved = _local_only_env(self.storage_dir)
        try:
            ok = _safe_call(
                "init",
                module.init,
                project=PROJECT,
                name=self.run_id,
                config=payload,
            )
            self.inited = bool(ok)
            if self.inited and self.run_id:
                _sessions[self.run_id] = self
            return self.inited
        finally:
            _restore_env(saved)

    def log(self, metrics: Mapping[str, Any], step: int | None = None) -> bool:
        if not metrics:
            return False
        if not self.inited and not self.start():
            return False
        module = _get_trackio()
        if module is None:
            return False
        saved = _local_only_env(self.storage_dir or resolve_storage_dir(self.run_dir))
        try:
            kwargs: dict[str, Any] = {}
            if step is not None:
                kwargs["step"] = step
            return bool(_safe_call("log", module.log, dict(metrics), **kwargs))
        finally:
            _restore_env(saved)

    def log_losses_from_text(self, text: str) -> int:
        rows = parse_trainer_losses(text)
        logged = 0
        for row in rows:
            step = row.get("step")
            step_i = int(step) if isinstance(step, (int, float)) else None
            if self.log(row, step=step_i):
                logged += 1
        return logged

    def log_losses_from_launch(
        self,
        launched: Mapping[str, Any] | None = None,
        log_path: Path | None = None,
    ) -> int:
        return self.log_losses_from_text(launch_text(launched, log_path))

    def log_integrity(self, record: Mapping[str, Any]) -> bool:
        payload: dict[str, Any] = {}
        for key in (
            "sha256_evidence",
            "sha256_pack",
            "sha256_train",
            "sha256_holdout",
            "result",
            "status",
            "host",
        ):
            if record.get(key) is not None:
                payload[key] = record[key]
        result = record.get("result") or record.get("status")
        if result is not None:
            payload["result"] = result
            payload["integrity_result"] = result
        if not payload:
            return False
        return self.log(payload)

    def log_eval_scores(self, scores: Mapping[str, Any], results_sha256: object) -> bool:
        digest = validate_results_sha256(results_sha256)
        if digest is None:
            return False
        payload = normalize_eval_scores(scores)
        if not payload:
            return False
        payload["eval_attached"] = 1
        payload["results_sha256"] = digest
        if self.run_id:
            payload.setdefault("run_id", self.run_id)
        return self.log(payload)

    def refuse(self, reason: object, *, config: Mapping[str, Any] | None = None) -> bool:
        if not self.inited:
            refused_config = dict(config or {})
            refused_config["status"] = "refused"
            self.start(refused_config)
        payload = _reason_payload(reason)
        self.log(payload)
        return self.finish()

    def finish(self) -> bool:
        if self.finished:
            return True
        module = _get_trackio()
        if module is None or not self.inited:
            self.finished = True
            return False
        saved = _local_only_env(self.storage_dir or resolve_storage_dir(self.run_dir))
        try:
            ok = _safe_call("finish", module.finish)
            self.finished = True
            return bool(ok)
        finally:
            _restore_env(saved)


def _session_for(run_id: str, run_dir: Path | None = None) -> RunSession:
    session = _sessions.get(run_id)
    if session is None or session.finished:
        session = RunSession(run_id=run_id, run_dir=run_dir)
        _sessions[run_id] = session
    elif run_dir is not None and session.run_dir is None:
        session.run_dir = Path(run_dir)
    return session


def init_run(
    run_id: str,
    config: Mapping[str, Any] | None = None,
    *,
    run_dir: Path | None = None,
) -> bool:
    return _session_for(run_id, run_dir).start(config, run_id=run_id)


def log_metrics(run_id: str, metrics: Mapping[str, Any], step: int | None = None) -> bool:
    return _session_for(run_id).log(metrics, step=step)


def log_eval_scores(run_id: str, scores: dict, results_sha256: object = None) -> bool:
    """Attach Critic eval scores (Choice/Score/Noul, halt, veto) to ``run_id``.

    ``results_sha256`` is required: 64-char lowercase hex of the sha-pinned
    results file. It is logged with every score. Missing or malformed values
    skip logging and warn; this function never raises.

    Trackio is a dashboard, never stamp-gate evidence. Verdicts come only
    from the sha-pinned results files and the HQ events.

    Fail-open. Safe to call after the trainer finishes; resumes the same run
    name when the kick session already finished.
    """
    try:
        if type(run_id) is not str or not run_id:
            _warn("HELPER FT trackio log_eval_scores missing run_id; skipped")
            return False
        if not isinstance(scores, Mapping):
            _warn("HELPER FT trackio log_eval_scores expected a dict; skipped")
            return False
        return _session_for(run_id).log_eval_scores(scores, results_sha256)
    except Exception as exc:
        _warn(
            f"HELPER FT trackio log_eval_scores failed ({type(exc).__name__}: {exc}); "
            "skipped (Trackio is not stamp-gate evidence)"
        )
        return False


def log_refused(
    run_id: str,
    reason: object,
    *,
    config: Mapping[str, Any] | None = None,
    run_dir: Path | None = None,
) -> bool:
    if type(run_id) is not str or not run_id:
        run_id = "helper-ft-unknown"
    return _session_for(run_id, run_dir).refuse(reason, config=config)


def log_integrity(run_id: str, record: Mapping[str, Any]) -> bool:
    return _session_for(run_id).log_integrity(record)


def finish_run(run_id: str) -> bool:
    return _session_for(run_id).finish()


def reset_for_tests() -> None:
    """Drop cached module/sessions. Tests only."""
    global _trackio_mod, _trackio_missing_warned
    _trackio_mod = None
    _trackio_missing_warned = False
    _sessions.clear()
