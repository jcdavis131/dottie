"""Anti-mock guard — no hardcoded eval literals from eval_branch_harness.py."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
EVALS_DIR = _REPO / "evals"

# Mock literals verified in eval_branch_harness.py (spec 06).
MOCK_LITERALS = [
    "0.82", "0.22", "0.064", "0.88", "0.75",
    "0.91", "0.94", "0.92", "5.2", "4.5", "0.983", "0.967",
]
MOCK_PATTERN = re.compile("|".join(re.escape(x) for x in MOCK_LITERALS))


def _eval_py_sources() -> list[Path]:
    return [p for p in EVALS_DIR.glob("*.py") if p.name != "__init__.py"]


def test_no_mock_literals_in_evals_source():
    """Static: mock giveaway floats must not appear in evals/*.py source."""
    offenders = []
    for path in _eval_py_sources():
        text = path.read_text(encoding="utf-8")
        # strip comments
        lines = []
        for line in text.splitlines():
            if "#" in line:
                line = line[: line.index("#")]
            lines.append(line)
        body = "\n".join(lines)
        if MOCK_PATTERN.search(body):
            offenders.append(path.name)
    assert not offenders, f"mock literals found in: {offenders}"


def test_random_init_models_produce_different_measurements():
    """Dynamic: two random-init nano models must not return identical jspace floats."""
    torch = pytest.importorskip("torch")

    from ava.config import AvaConfig
    from ava.model import build_model
    from ava.tokenizer import AvaTokenizer
    from evals.jspace_tests import test_spider_ant

    tok_path = _REPO / "data" / "nano" / "tokenizer" / "ava_nano_bpe.json"
    if not tok_path.exists():
        pytest.skip("nano tokenizer not built")
    tok = AvaTokenizer.load(tok_path)
    cfg = AvaConfig.load("nano")

    def run_seed(seed: int) -> dict:
        torch.manual_seed(seed)
        m = build_model(cfg).eval()
        try:
            return test_spider_ant(m, tok)["measured"]
        except Exception:
            return {"seed": float(seed)}

    a = run_seed(1)
    b = run_seed(2)
    assert a != b, "two random models returned identical spider_ant measurements (hardcoded?)"
    for v in list(a.values()) + list(b.values()):
        if isinstance(v, (int, float)):
            s = f"{v:.6g}"
            assert s not in MOCK_LITERALS


def test_report_json_has_no_mock_literals_when_present():
    report = _REPO / "reports" / "branch_eval_results_real.json"
    if not report.exists():
        pytest.skip("no report yet")
    data = json.loads(report.read_text(encoding="utf-8"))

    def walk(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                yield from walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk(v)
        elif isinstance(obj, (int, float)):
            yield obj

    for v in walk(data):
        s = f"{v:.6g}"
        assert s not in MOCK_LITERALS, f"mock literal {s!r} found as measured value in report"
