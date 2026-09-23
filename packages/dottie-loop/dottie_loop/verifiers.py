"""Automatic verifiers: did an executor's answer actually satisfy the goal?

A verifier is a pure check of an executor result against a spec written down
before the run (the benchmark goal's ``verifier`` object). It never asks a
model. ``scout router probe`` labels a goal with the cheapest tier whose
result passes its verifier; nothing else turns into a label.

Result shape a verifier reads (every executor returns it)::

    {"answer": str, "text": str, "sources": [{"id", "url", "title"}], "meta": {...}}

Spec shape::

    {"type": "<name>", ...type-specific keys...}

Registry (:data:`VERIFIERS`):

``exact``       normalised answer equals ``expected`` (or one of ``accept``)
``contains``    every string in ``expected`` (str or list) occurs in the answer
``regex``       ``pattern`` matches the answer (``fullmatch`` when ``full``)
``numeric``     first number in the answer within ``abs_tol`` / ``rel_tol`` of ``expected``
``json_schema`` the answer parses as JSON and satisfies ``schema`` (a small
                JSON-Schema subset: type, required, properties, items, enum,
                minimum, maximum, minLength, minItems)
``unit_tests``  the answer's Python code passes ``tests`` in a separate,
                isolated interpreter with a timeout
``citations``   at least ``min_sources`` sources, the answer cites them
                (a source id or ``[n]`` marker), and the optional nested
                ``answer_check`` spec passes
``exit_code``   ``meta.exit_code`` is 0 and ``expected_output`` (regex) is in the text

:data:`TASK_VERIFIERS` maps a goal's ``task_type`` to its default verifier.
Stdlib only.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

UNIT_TEST_TIMEOUT_S = 10.0
_NUM = re.compile(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)
_CITE = re.compile(r"\[(\d+)\]")


def _norm(text: Any) -> str:
    t = str(text if text is not None else "").strip().casefold()
    t = re.sub(r"\s+", " ", t)
    return t.rstrip(".").strip().strip("'\"`").strip()


def _out(passed: bool, name: str, detail: str) -> dict[str, Any]:
    return {"passed": bool(passed), "verifier": name, "detail": detail[:300]}


def v_exact(result: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    got = _norm(result.get("answer"))
    accept = [spec["expected"], *spec.get("accept", [])]
    ok = any(got == _norm(a) for a in accept)
    return _out(ok, "exact", f"answer={got[:80]!r} expected={_norm(spec['expected'])[:80]!r}")


def v_contains(result: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    want = spec["expected"] if isinstance(spec["expected"], list) else [spec["expected"]]
    got = _norm(result.get("answer"))
    missing = [w for w in want if _norm(w) not in got]
    return _out(not missing, "contains", f"missing={missing[:5]}")


def v_regex(result: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    flags = re.I if spec.get("ignore_case", True) else 0
    ans = str(result.get("answer") or "").strip()
    m = re.fullmatch(spec["pattern"], ans, flags) if spec.get("full") else re.search(spec["pattern"], ans, flags)
    return _out(m is not None, "regex", f"pattern={spec['pattern'][:80]!r} answer={ans[:80]!r}")


def first_number(text: str) -> float | None:
    m = _NUM.search(str(text or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def v_numeric(result: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    got = first_number(result.get("answer", ""))
    want = float(spec["expected"])
    if got is None:
        return _out(False, "numeric", "no number in the answer")
    tol = max(float(spec.get("abs_tol", 1e-9)), float(spec.get("rel_tol", 0.0)) * abs(want))
    return _out(math.isclose(got, want, rel_tol=0.0, abs_tol=tol), "numeric", f"answer={got} expected={want} tol={tol}")


_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,), "array": (list,), "string": (str,), "integer": (int,),
    "number": (int, float), "boolean": (bool,), "null": (type(None),),
}


def schema_errors(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Errors of ``value`` against the JSON-Schema subset this module supports."""
    errs: list[str] = []
    t = schema.get("type")
    if t:
        ok = isinstance(value, _JSON_TYPES.get(t, (object,)))
        if t in ("integer", "number") and isinstance(value, bool):
            ok = False
        if not ok:
            return [f"{path}: expected {t}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in enum")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, str) and len(value) < int(schema.get("minLength", 0)):
        errs.append(f"{path}: shorter than minLength")
    if isinstance(value, dict):
        errs += [f"{path}: missing {k!r}" for k in schema.get("required", []) if k not in value]
        for k, sub in (schema.get("properties") or {}).items():
            if k in value:
                errs += schema_errors(value[k], sub, f"{path}.{k}")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            errs.append(f"{path}: fewer than minItems")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                errs += schema_errors(item, schema["items"], f"{path}[{i}]")
    return errs


def extract_json(text: str) -> Any:
    """The first JSON value in ``text`` (a fenced block, the whole text, or the first {...}/[...])."""
    candidates = [m.group(1) for m in re.finditer(r"```(?:json)?\s*\n(.*?)```", text or "", re.S)]
    candidates.append(text or "")
    for c in candidates:
        c = c.strip()
        for start in [i for i, ch in enumerate(c) if ch in "{["][:3] or [0]:
            try:
                return json.JSONDecoder().raw_decode(c[start:])[0]
            except ValueError:
                continue
    raise ValueError("no JSON value found")


def v_json_schema(result: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    try:
        value = extract_json(str(result.get("answer") or ""))
    except ValueError as exc:
        return _out(False, "json_schema", str(exc))
    errs = schema_errors(value, spec["schema"])
    if not errs and "expected" in spec and value != spec["expected"]:
        errs.append("value differs from expected")
    return _out(not errs, "json_schema", "; ".join(errs[:5]) or "valid")


def extract_code(text: str) -> str:
    blocks = _FENCE.findall(text or "")
    return max(blocks, key=len) if blocks else str(text or "")


def v_unit_tests(result: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Run the answer's code plus ``tests`` in ``python -I`` (isolated mode), cwd a temp dir, timeout."""
    code = extract_code(str(result.get("answer") or ""))
    if not code.strip():
        return _out(False, "unit_tests", "no code in the answer")
    program = code + "\n\n" + str(spec["tests"]) + "\nprint('UNIT_TESTS_OK')\n"
    timeout = float(spec.get("timeout_s", UNIT_TEST_TIMEOUT_S))
    with tempfile.TemporaryDirectory(prefix="dottie-verify-") as tmp:
        path = Path(tmp) / "candidate.py"
        path.write_text(program, encoding="utf-8")
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0", "HOME": tmp}
        try:
            proc = subprocess.run([sys.executable, "-I", str(path)], cwd=tmp, env=env, capture_output=True,
                                  text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return _out(False, "unit_tests", f"timed out after {timeout}s")
    ok = proc.returncode == 0 and "UNIT_TESTS_OK" in proc.stdout
    return _out(ok, "unit_tests", f"exit={proc.returncode} {proc.stderr.strip()[-200:]}")


def v_citations(result: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    sources = [s for s in (result.get("sources") or []) if isinstance(s, dict)]
    k = int(spec.get("min_sources", 1))
    if len(sources) < k:
        return _out(False, "citations", f"{len(sources)} source(s) < {k}")
    answer = str(result.get("answer") or "")
    text = answer + "\n" + str(result.get("text") or "")
    markers = {int(n) for n in _CITE.findall(answer)}
    cited = [i for i, s in enumerate(sources, 1) if i in markers or (s.get("id") and str(s["id"]) in answer)]
    if len(cited) < min(k, len(sources)):
        return _out(False, "citations", f"answer cites {len(cited)} of {len(sources)} sources (need {k})")
    inner = spec.get("answer_check")
    if inner:
        sub = verify({**result, "text": text}, inner)
        return _out(sub["passed"], "citations", f"{len(cited)} cited; {sub['verifier']}: {sub['detail']}")
    return _out(True, "citations", f"{len(cited)} cited")


def v_exit_code(result: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    code = (result.get("meta") or {}).get("exit_code")
    if code != 0:
        return _out(False, "exit_code", f"exit_code={code}")
    pat = spec.get("expected_output")
    if pat and not re.search(pat, str(result.get("text") or ""), re.S):
        return _out(False, "exit_code", f"output does not match {pat!r}")
    return _out(True, "exit_code", "exit 0" + (" and output matches" if pat else ""))


VERIFIERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "exact": v_exact,
    "contains": v_contains,
    "regex": v_regex,
    "numeric": v_numeric,
    "json_schema": v_json_schema,
    "unit_tests": v_unit_tests,
    "citations": v_citations,
    "exit_code": v_exit_code,
}

#: A goal's task type -> the verifier it defaults to when its spec names none.
TASK_VERIFIERS: dict[str, str] = {
    "arithmetic": "numeric",
    "unit_conversion": "numeric",
    "numeric_reasoning": "numeric",
    "text_transform": "exact",
    "regex_extraction": "exact",
    "fact_exact": "exact",
    "code": "unit_tests",
    "json": "json_schema",
    "lookup": "citations",
    "command": "exit_code",
}


def verifier_for(goal: dict[str, Any]) -> dict[str, Any]:
    """The spec for a benchmark goal: its own ``verifier``, typed from ``task_type`` when untyped."""
    spec = dict(goal.get("verifier") or {})
    if "type" not in spec:
        spec["type"] = TASK_VERIFIERS.get(str(goal.get("task_type")), "exact")
    return spec


def verify(result: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Run the named verifier. An unknown type or a malformed spec fails (never passes)."""
    fn = VERIFIERS.get(str(spec.get("type")))
    if fn is None:
        return _out(False, str(spec.get("type")), "unknown verifier type")
    try:
        return fn(result, spec)
    except (KeyError, TypeError, ValueError) as exc:
        return _out(False, str(spec.get("type")), f"malformed spec or result: {type(exc).__name__}: {exc}")


def validate_spec(spec: dict[str, Any]) -> list[str]:
    """Static check of a spec (the benchmark builder and its test use it)."""
    need = {"exact": ["expected"], "contains": ["expected"], "regex": ["pattern"], "numeric": ["expected"],
            "json_schema": ["schema"], "unit_tests": ["tests"], "citations": [], "exit_code": []}
    t = spec.get("type")
    if t not in need:
        return [f"unknown type {t!r}"]
    errs = [f"{t}: missing {k!r}" for k in need[t] if k not in spec]
    if t == "citations" and spec.get("answer_check"):
        errs += validate_spec(spec["answer_check"])
    return errs
