"""Stdlib loader and validator for frozen ``jev-decision-schema-1.0.0``.

No torch, no Hugging Face, no network. Both ``train_pointer_lora.py --dry-run``
and ``serve_decide.py`` import this module so the schema stays one file.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

SCHEMA_ID = "jev-decision-schema-1.0.0"
QUESTION_TYPES = frozenset({"choice", "score", "noul"})
APP_ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEMA = APP_ROOT / "schema" / "decision_schema.json"
DEFAULT_FIXTURES = APP_ROOT / "fixtures" / "synthetic_decisions.jsonl"

# Fixtures and live requests must stay operational text. The freeze note
# "no virus content" is enforced here, not left as README prose.
_FORBIDDEN = re.compile(
    r"\b(virus|malware|ransomware|trojan|rootkit|spyware|worm)\b",
    re.IGNORECASE,
)

_MAX_QUESTIONS = 32
_MAX_CHOICE = 255
_MIN_OPTIONS = 2
_MAX_SCORE_LEVELS = 10
_MAX_INSTRUCTION = 512
_MAX_CRITERION = 256


class SchemaError(ValueError):
    """A record does not satisfy the frozen decision schema."""


def load_schema(path: Path | None = None) -> dict[str, Any]:
    """Load ``decision_schema.json`` and refuse a drifted ``$id``."""
    schema_path = path or DEFAULT_SCHEMA
    raw = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SchemaError("schema file must be a JSON object")
    if raw.get("$id") != SCHEMA_ID:
        raise SchemaError(f"schema $id must stay {SCHEMA_ID!r} (frozen)")
    return raw


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_strings(item))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_strings(item))
        return out
    return []


def reject_forbidden_content(record: dict[str, Any], *, field: str = "record") -> None:
    """Refuse virus/malware wording. Synthetic fixtures stay operational."""
    for text in _strings(record):
        if _FORBIDDEN.search(text):
            raise SchemaError(f"{field}: forbidden content (virus/malware wording)")


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError(f"{field} must be an object")
    return value


def _require_str(value: Any, field: str, *, max_len: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{field} must be a non-empty string")
    if len(value) > max_len:
        raise SchemaError(f"{field} exceeds {max_len} characters (refuse, do not truncate)")
    return value


def _unit(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaError(f"{field} must be a number in [0, 1]")
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        raise SchemaError(f"{field} must be a finite number in [0, 1]")
    return number


def validate_question(qid: str, raw: Any) -> dict[str, Any]:
    question = _require_dict(raw, f"questions.{qid}")
    qtype = question.get("type")
    if qtype not in QUESTION_TYPES:
        raise SchemaError(f"questions.{qid}.type must be one of {sorted(QUESTION_TYPES)}")
    instructions = _require_str(
        question.get("instructions"), f"questions.{qid}.instructions", max_len=_MAX_INSTRUCTION
    )
    if qtype == "choice":
        criteria = _require_dict(question.get("criteria"), f"questions.{qid}.criteria")
        if not _MIN_OPTIONS <= len(criteria) <= _MAX_CHOICE:
            raise SchemaError(
                f"questions.{qid}.criteria must have {_MIN_OPTIONS}–{_MAX_CHOICE} options"
            )
        cleaned: dict[str, str] = {}
        for key, desc in criteria.items():
            _require_str(key, f"questions.{qid}.criteria key", max_len=64)
            cleaned[key] = _require_str(desc, f"questions.{qid}.criteria.{key}", max_len=_MAX_CRITERION)
        return {"type": "choice", "instructions": instructions, "criteria": cleaned}
    if qtype == "score":
        criteria = question.get("criteria")
        if not isinstance(criteria, list) or not _MIN_OPTIONS <= len(criteria) <= _MAX_SCORE_LEVELS:
            raise SchemaError(
                f"questions.{qid}.criteria must be a list of {_MIN_OPTIONS}–{_MAX_SCORE_LEVELS} levels"
            )
        levels = [
            _require_str(item, f"questions.{qid}.criteria[{i}]", max_len=_MAX_CRITERION)
            for i, item in enumerate(criteria)
        ]
        return {"type": "score", "instructions": instructions, "criteria": levels}
    if qtype == "noul":
        out: dict[str, Any] = {"type": "noul", "instructions": instructions}
        if "criteria" in question and question["criteria"] is not None:
            criteria = _require_dict(question.get("criteria"), f"questions.{qid}.criteria")
            out["criteria"] = {
                _require_str(k, f"questions.{qid}.criteria key", max_len=64): _require_str(
                    v, f"questions.{qid}.criteria.{k}", max_len=_MAX_CRITERION
                )
                for k, v in criteria.items()
            }
        return out
    impossible: str = qtype  # pragma: no cover - QUESTION_TYPES is closed
    raise SchemaError(f"questions.{qid}.type unhandled: {impossible!r}")


def validate_questions(raw: Any) -> dict[str, dict[str, Any]]:
    questions = _require_dict(raw, "questions")
    if not 1 <= len(questions) <= _MAX_QUESTIONS:
        raise SchemaError(f"questions must have 1–{_MAX_QUESTIONS} entries")
    return {qid: validate_question(qid, body) for qid, body in questions.items()}


def option_keys(question: dict[str, Any]) -> list[str]:
    """Closed option set a pointer head scores over."""
    qtype = question["type"]
    if qtype == "choice":
        return list(question["criteria"].keys())
    if qtype == "score":
        return [str(i) for i in range(len(question["criteria"]))]
    if qtype == "noul":
        return ["true", "false"]
    impossible: str = qtype
    raise SchemaError(f"unhandled question type {impossible!r}")


def validate_label(qid: str, question: dict[str, Any], raw: Any) -> dict[str, Any]:
    label = _require_dict(raw, f"labels.{qid}")
    if label.get("type") != question["type"]:
        raise SchemaError(f"labels.{qid}.type must match questions.{qid}.type")
    qtype = question["type"]
    if qtype == "choice":
        choice = _require_str(label.get("choice"), f"labels.{qid}.choice", max_len=64)
        if choice not in question["criteria"]:
            raise SchemaError(f"labels.{qid}.choice {choice!r} is not in the offered set")
        return {"type": "choice", "choice": choice}
    if qtype == "score":
        score = label.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            raise SchemaError(f"labels.{qid}.score must be a finite number")
        high = float(len(question["criteria"]) - 1)
        value = float(score)
        if value < 0.0 or value > high:
            raise SchemaError(f"labels.{qid}.score must sit in [0, {high}]")
        return {"type": "score", "score": value}
    if qtype == "noul":
        return {"type": "noul", "noul": _unit(label.get("noul"), f"labels.{qid}.noul")}
    impossible: str = qtype
    raise SchemaError(f"unhandled label type {impossible!r}")


def validate_record(raw: Any) -> dict[str, Any]:
    """Validate one training JSONL object."""
    record = _require_dict(raw, "record")
    reject_forbidden_content(record)
    if record.get("schema") != SCHEMA_ID:
        raise SchemaError(f"schema must be {SCHEMA_ID!r} (frozen)")
    record_id = _require_str(record.get("id"), "id", max_len=128)
    state = _require_dict(record.get("state"), "state")
    if not state:
        raise SchemaError("state must have at least one field")
    questions = validate_questions(record.get("questions"))
    labels_raw = _require_dict(record.get("labels"), "labels")
    if set(labels_raw) != set(questions):
        raise SchemaError("labels keys must match questions keys exactly")
    labels = {qid: validate_label(qid, questions[qid], labels_raw[qid]) for qid in questions}
    return {
        "schema": SCHEMA_ID,
        "id": record_id,
        "state": state,
        "questions": questions,
        "labels": labels,
    }


def validate_request(raw: Any) -> dict[str, Any]:
    """Validate a ``POST /decide`` body."""
    request = _require_dict(raw, "request")
    reject_forbidden_content(request, field="request")
    if request.get("schema") != SCHEMA_ID:
        raise SchemaError(f"schema must be {SCHEMA_ID!r} (frozen)")
    state = _require_dict(request.get("state"), "state")
    if not state:
        raise SchemaError("state must have at least one field")
    questions = validate_questions(request.get("questions"))
    return {"schema": SCHEMA_ID, "state": state, "questions": questions}


def shape_concentration(probabilities: dict[str, float]) -> float:
    """Peakedness of a closed distribution. Not TypeSafe's undisclosed confidence."""
    if not probabilities:
        return 0.0
    return max(probabilities.values())


def normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0.0:
        n = len(weights)
        return {key: 1.0 / n for key in weights} if n else {}
    return {key: value / total for key, value in weights.items()}


def untrained_answer(question: dict[str, Any]) -> dict[str, Any]:
    """Schema-valid uniform answer. Honest: no weights, no calibration claim."""
    qtype = question["type"]
    keys = option_keys(question)
    uniform = {key: 1.0 / len(keys) for key in keys}
    concentration = shape_concentration(uniform)
    if qtype == "choice":
        return {
            "type": "choice",
            "choice": keys[0],
            "probabilities": uniform,
            "shape_concentration": concentration,
        }
    if qtype == "score":
        legend = {str(i): label for i, label in enumerate(question["criteria"])}
        expected = sum(int(key) * prob for key, prob in uniform.items())
        return {
            "type": "score",
            "score": expected,
            "legend": legend,
            "probabilities": uniform,
            "shape_concentration": concentration,
        }
    if qtype == "noul":
        return {"type": "noul", "noul": uniform["true"]}
    impossible: str = qtype
    raise SchemaError(f"unhandled question type {impossible!r}")


def load_fixtures(path: Path | None = None) -> list[dict[str, Any]]:
    """Read and validate the synthetic JSONL. Empty / bad lines fail closed."""
    fixture_path = path or DEFAULT_FIXTURES
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(fixture_path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SchemaError(f"{fixture_path}:{lineno}: invalid JSON ({exc})") from exc
        try:
            records.append(validate_record(payload))
        except SchemaError as exc:
            raise SchemaError(f"{fixture_path}:{lineno}: {exc}") from exc
    if not records:
        raise SchemaError(f"{fixture_path}: no decision records")
    return records


def type_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in sorted(QUESTION_TYPES)}
    for record in records:
        for question in record["questions"].values():
            counts[question["type"]] += 1
    return counts


def answer_from_probabilities(question: dict[str, Any], probabilities: dict[str, float]) -> dict[str, Any]:
    """Shape a trained head's closed distribution into a schema answer.

    Same shape as :func:`untrained_answer`, from real probabilities. Choice and
    Score carry ``shape_concentration``; nothing here is called confidence and
    nothing claims calibration.
    """
    keys = option_keys(question)
    if set(probabilities) != set(keys):
        raise SchemaError("probabilities must cover exactly the offered option set")
    probs = normalize({key: max(0.0, float(probabilities[key])) for key in keys})
    qtype = question["type"]
    if qtype == "choice":
        return {
            "type": "choice",
            "choice": max(keys, key=lambda k: probs[k]),
            "probabilities": probs,
            "shape_concentration": shape_concentration(probs),
        }
    if qtype == "score":
        legend = {str(i): label for i, label in enumerate(question["criteria"])}
        return {
            "type": "score",
            "score": sum(int(key) * prob for key, prob in probs.items()),
            "legend": legend,
            "probabilities": probs,
            "shape_concentration": shape_concentration(probs),
        }
    if qtype == "noul":
        return {"type": "noul", "noul": probs["true"]}
    impossible: str = qtype
    raise SchemaError(f"unhandled question type {impossible!r}")


def checkpoint_identity(path: Path) -> str:
    """sha256 naming a checkpoint's bytes (``scout router promote`` stamps this).

    Sorted ``relative/path:sha256`` lines of every file under ``path`` except
    ``eval_summary.json`` and ``stamps/``. Must stay identical to
    ``dottie_loop.router_artifacts.artifact_identity`` for directories.
    """
    import hashlib

    def file_sha(p: Path) -> str:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    if path.is_file():
        return file_sha(path)
    lines = []
    for p in sorted(q for q in path.rglob("*") if q.is_file()):
        rel = p.relative_to(path).as_posix()
        if rel == "eval_summary.json" or rel.startswith("stamps/"):
            continue
        lines.append(f"{rel}:{file_sha(p)}")
    if not lines:
        raise SchemaError(f"checkpoint directory is empty: {path}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
