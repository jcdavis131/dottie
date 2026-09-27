# Solo personal project, no connection to employer, built with public/free-tier only
"""VerifiedTaskProvider tests — per-family determinism, automated no-answer-leakage
self-checks, and verify_fn correctness on hand-built right AND wrong finals."""

from __future__ import annotations

import hashlib
import re

import pytest

from dottie.tasks import FAMILIES, VerifiedTaskProvider, answer_token_present

provider = VerifiedTaskProvider()

LEAK_SEEDS = range(15)


@pytest.mark.parametrize("family", FAMILIES)
def test_family_deterministic_per_seed(family):
    a = provider.build(family, 7)
    b = provider.build(family, 7)
    assert a.prompt == b.prompt
    assert a.expected == b.expected
    assert a.tool_sources == b.tool_sources
    assert a.verifier_detail() == b.verifier_detail()
    # A different seed produces a different task (parameters really vary).
    c = provider.build(family, 8)
    assert c.prompt != a.prompt


@pytest.mark.parametrize("family", FAMILIES)
def test_no_answer_leakage_self_check(family):
    """The scoring token must never appear in the prompt — so echoing the prompt can't score."""
    for seed in LEAK_SEEDS:
        task = provider.build(family, seed)
        # Every token the verifier accepts is guarded, not just the canonical one.
        for token in (task.expected, *task.alt_expected):
            assert not answer_token_present(token, task.prompt, ignore_case=True), (
                f"{family} seed {seed} leaked accepted token {token!r} into its prompt"
            )
        # The exact guarantee the echo e2e test relies on: grading the prompt itself scores 0.
        assert task.verify(task.prompt, []) == 0.0


def test_unknown_family_rejected():
    with pytest.raises(ValueError):
        provider.build("mind_reading", 0)


# -- verify_fn correctness on hand-built finals --------------------------------------


def test_compute_verify_right_and_wrong():
    t = provider.build("compute", 0)
    assert t.verify(f"After running the code, the result is {t.expected}.", []) == 1.0
    assert t.verify(f"The result is {int(t.expected) + 1}.", []) == 0.0
    # Boundary guard: the expected value embedded inside a longer number must NOT match.
    assert t.verify(f"The result is 9{t.expected}9.", []) == 0.0
    assert t.verify("", []) == 0.0


def test_extract_verify_right_and_wrong():
    t = provider.build("extract", 4)
    assert t.verify(f"Total value: {t.expected} cents.", []) == 1.0
    assert t.verify("Total value: unknown.", []) == 0.0


def test_tool_chain_verify_requires_value_and_real_tool_calls():
    t = provider.build("tool_chain", 2)
    both = [{"ok": True, "tool_calls": [{"tool": "part_lookup"}, {"tool": "bin_rate"}]}]
    one = [{"ok": True, "tool_calls": [{"tool": "part_lookup"}]}]
    failed_step = [
        {"ok": False, "tool_calls": [{"tool": "part_lookup"}, {"tool": "bin_rate"}]}
    ]
    right = f"The shipping score is {t.expected}."
    assert t.verify(right, both) == 1.0
    assert t.verify(f"The shipping score is {int(t.expected) + 3}.", both) == 0.0
    assert t.verify(right, one) == 0.0  # value without both real tool calls scores 0
    assert t.verify(right, []) == 0.0
    assert t.verify(right, failed_step) == 0.0  # calls on an errored step don't count


def test_file_ops_expected_digest_rederivable_from_prompt():
    """Independently re-derive the digest from the prompt's rendered lines per the stated
    spec — proves the verifier expectation is computed from the same values the prompt shows."""
    t = provider.build("file_ops", 5)
    body = t.prompt.split("take these lines:\n", 1)[1].split("\nWrite them", 1)[0]
    lines = body.splitlines()
    content = "\n".join(line.upper() for line in lines) + "\n"
    digest12 = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    assert digest12 == t.expected
    assert t.verify(f"Digest prefix: {digest12}", []) == 1.0
    assert (
        t.verify(f"Digest prefix: {digest12.upper()}", []) == 1.0
    )  # hex case-insensitive
    corrupted = ("0" if digest12[0] != "0" else "1") + digest12[1:]
    assert t.verify(f"Digest prefix: {corrupted}", []) == 0.0


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _file_ops_content(t) -> str:
    """The expected file content, re-derived from the prompt per its stated spec."""
    body = t.prompt.split("take these lines:\n", 1)[1].split("\nWrite them", 1)[0]
    return "\n".join(line.upper() for line in body.splitlines()) + "\n"


@pytest.mark.parametrize("seed", LEAK_SEEDS)
def test_file_ops_scores_windows_text_mode_crlf_bytes(seed):
    """A Windows text-mode write (``open('report.txt', 'w')``) stores every '\\n' as
    '\\r\\n', so a model that hashes the bytes it really wrote reports the digest of the
    CRLF form. The 2026-09-27 local-LLM A/B (Windows host) scored file_ops 0/10 on all five
    arms because of this; no final in 50 carried the LF digest. The verifier must credit
    the correct content whichever line ending the sandbox's OS gave it."""
    t = provider.build("file_ops", seed)
    content = _file_ops_content(t)
    lf, crlf = _sha12(content), _sha12(content.replace("\n", "\r\n"))
    assert lf == t.expected and crlf != lf
    assert t.verify(f"Digest prefix: {crlf}", []) == 1.0
    assert t.verify(f"Digest prefix: {crlf.upper()}", []) == 1.0  # hex case-insensitive
    # The LF (POSIX) form still scores.
    assert t.verify(f"Digest prefix: {lf}", []) == 1.0
    # CRLF bytes of the WRONG content still score 0: no trailing newline, not uppercased.
    for wrong in (content.rstrip("\n"), content.lower()):
        wrong_crlf = _sha12(wrong.replace("\n", "\r\n"))
        assert t.verify(f"Digest prefix: {wrong_crlf}", []) == 0.0
    corrupted = ("0" if crlf[0] != "0" else "1") + crlf[1:]
    assert t.verify(f"Digest prefix: {corrupted}", []) == 0.0


def test_constraint_verify_graded_and_token_gated():
    t = provider.build("constraint", 9)
    m = re.search(r"between (\d+) and (\d+) words", t.prompt)
    lo, hi = int(m.group(1)), int(m.group(2))
    filler = ["workshop"] * (lo + 2)
    good = " ".join([t.expected] + filler[: lo + 1])  # token + in-band + clean
    assert lo <= len(good.split()) <= hi
    assert t.verify(good, []) == 1.0
    # Token present but word count out of band -> 2/3.
    short = f"{t.expected} done."
    assert t.verify(short, []) == pytest.approx(2 / 3, abs=1e-3)
    # Token + in-band but forbidden word used -> 2/3.
    forb = re.search(r"Do not use the word '(\w+)'", t.prompt).group(1)
    bad_word = " ".join([t.expected, forb] + filler[:lo])
    assert t.verify(bad_word, []) == pytest.approx(2 / 3, abs=1e-3)
    # No computed token -> gated to 0.0 regardless of the other constraints.
    assert t.verify(" ".join(filler[: lo + 1]), []) == 0.0


# -- batch helper --------------------------------------------------------------------


def test_batch_seeds_single_family_and_defaults():
    pairs = provider.batch_seeds("compute", 3)
    assert pairs == [("compute", 0), ("compute", 1), ("compute", 2)]
    pairs = provider.batch_seeds("file_ops", 2, seeds=[11, 12])
    assert pairs == [("file_ops", 11), ("file_ops", 12)]


def test_batch_seeds_mixed_cycles_families():
    pairs = provider.batch_seeds("mixed", 7)
    assert [f for f, _ in pairs] == list(FAMILIES) + list(FAMILIES[:2])
    assert [s for _, s in pairs] == list(range(7))


def test_batch_seeds_validation():
    with pytest.raises(ValueError):
        provider.batch_seeds("compute", 3, seeds=[1])
    with pytest.raises(ValueError):
        provider.batch_seeds("not_a_family", 3)
