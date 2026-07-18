# Solo personal project, no connection to employer, built with public/free-tier only
"""TorchModelPolicy tests (spec 13 T13C.5, real decode half).

REAL-TENSOR MACHINERY TESTS, honestly labeled:
  • The nano AvaModel here is RANDOM-INIT (13.8M params, CPU). It has zero capability and its
    turns are noise — expected. What these tests measure is the decode MACHINERY: tokenize ->
    left-truncate -> autoregressive pick (greedy / seeded sampling) -> stop-cut -> detokenize.
  • The loop-integration test uses a SCRIPTED-LOGITS stub LM (synthetic weights, clearly labeled)
    whose logits deterministically spell out a known valid code-act turn. It proves the full
    chain model -> TorchModelPolicy decode -> run_code_act -> REAL sandbox -> Observation ->
    FINAL executes with the real decode machinery. It is NOT a capability measurement.

Tokenizer choice (justification): a char-level duck-typed tokenizer (`CharTokenizer`, ord<->chr)
instead of an on-the-fly BPE train. The policy's tokenizer contract is duck-typed encode/decode;
char-level exercises exactly that contract, round-trips ASCII losslessly (so stop markers and
```python fences survive encode->decode byte-for-byte, which the scripted-turn test needs), needs
no training corpus, and keeps the test deterministic and fast. AvaTokenizer compatibility is
covered by the contract itself plus the `decode(ids, skip_special=...)` keyword probe, which
`_decode_text` exercises via TypeError fallback on this tokenizer.
"""

import os
import sys
from pathlib import Path
from typing import List

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ava.config import AvaConfig                          # noqa: E402
from ava.model import build_model                         # noqa: E402
from ava.rl.codeact_loop import run_code_act              # noqa: E402
from ava.rl.codeact_policy import TorchModelPolicy, _extract_logits  # noqa: E402

POSIX = os.name == "posix"
posix_only = pytest.mark.skipif(not POSIX, reason="sandbox resource caps require POSIX")

VOCAB = 8192  # nano vocab


# ---------------------------------------------------------------------------
# Minimal real tokenizer (duck-typed; see module docstring for justification)
# ---------------------------------------------------------------------------


class CharTokenizer:
    """Char-level tokenizer: ord(c) <-> chr(i), capped to the model vocab. Lossless for ASCII."""

    def __init__(self, vocab_size: int = VOCAB) -> None:
        self.vocab_size = vocab_size

    def encode(self, text: str) -> List[int]:
        return [min(ord(c), self.vocab_size - 1) for c in text]

    def decode(self, ids: List[int]) -> str:
        return "".join(chr(i) for i in ids)


# ---------------------------------------------------------------------------
# Scripted-logits stubs — SYNTHETIC weights, real decode machinery
# ---------------------------------------------------------------------------


class ScriptedSequenceLM:
    """Stub LM whose argmax at each successive forward call is the next id of a fixed script.

    Returns the AvaModel dict contract ({'lm_logits': [B, L, V]}). Peaked logits (+/-30) make
    greedy argmax unambiguous. Clearly synthetic — machinery only."""

    def __init__(self, script_ids: List[int], vocab: int = VOCAB) -> None:
        self._script = list(script_ids)
        self._i = 0
        self.vocab = vocab
        self.seen_lengths: List[int] = []          # recorded per forward, for truncation checks

    def __call__(self, *, input_ids: torch.Tensor, **kw) -> dict:
        self.seen_lengths.append(int(input_ids.shape[1]))
        L = int(input_ids.shape[1])
        logits = torch.full((1, L, self.vocab), -30.0)
        tgt = self._script[self._i] if self._i < len(self._script) else 0
        self._i += 1
        logits[0, -1, tgt] = 30.0
        return {"lm_logits": logits}


class HandComputedLM:
    """Raw-TENSOR-returning stub (exercises the non-dict adapter path) with hand-written logit
    rows keyed by the last input id. Vocab 8. Argmaxes are hand-verifiable by eye:
      last=3 -> row argmax is index 4 (0.9 largest)
      last=4 -> row argmax is index 5 (1.2 largest)
    """

    ROWS = {
        3: [0.0, 0.1, 0.2, 0.15, 0.9, 0.3, 0.1, 0.05],   # argmax = 4
        4: [0.5, 0.1, 0.2, 0.3, 0.0, 1.2, 0.4, 0.1],     # argmax = 5
        5: [2.0, 0.1, 0.2, 0.3, 0.0, 0.2, 0.4, 0.1],     # argmax = 0
    }

    def __call__(self, *, input_ids: torch.Tensor, **kw) -> torch.Tensor:
        L = int(input_ids.shape[1])
        last = int(input_ids[0, -1].item())
        logits = torch.zeros(1, L, 8)
        logits[0, -1, :] = torch.tensor(self.ROWS[last])
        return logits


class DigitTokenizer:
    """Tokens ARE digits: '3' -> [3], [4, 5] -> '45'. Vocab 8, for the hand-computed case."""

    def encode(self, text: str) -> List[int]:
        return [int(c) for c in text]

    def decode(self, ids: List[int]) -> str:
        return "".join(str(i) for i in ids)


class RecordingWrapper:
    """Pass-through around a real model that records the input length of every forward."""

    def __init__(self, model) -> None:
        self._m = model
        self.seen_lengths: List[int] = []

    def __call__(self, *, input_ids: torch.Tensor, **kw):
        self.seen_lengths.append(int(input_ids.shape[1]))
        return self._m(input_ids=input_ids, **kw)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def nano_model():
    """Real nano AvaModel, RANDOM INIT (no training): real tensors, zero capability."""
    torch.manual_seed(0)
    m = build_model(AvaConfig.load("nano"))
    m.eval()
    return m


@pytest.fixture()
def char_tok():
    return CharTokenizer()


# ---------------------------------------------------------------------------
# 1. Honest gate: constructor refuses None model / None tokenizer
# ---------------------------------------------------------------------------


class TestHonestGate:
    def test_none_model_raises(self, char_tok):
        with pytest.raises(ValueError, match="real model"):
            TorchModelPolicy(None, char_tok)

    def test_none_tokenizer_raises(self, nano_model):
        with pytest.raises(ValueError, match="real tokenizer"):
            TorchModelPolicy(nano_model, None)

    def test_bad_params_raise(self, nano_model, char_tok):
        with pytest.raises(ValueError):
            TorchModelPolicy(nano_model, char_tok, max_new_tokens=0)
        with pytest.raises(ValueError):
            TorchModelPolicy(nano_model, char_tok, temperature=-0.1)
        with pytest.raises(ValueError):
            TorchModelPolicy(nano_model, char_tok, context_window=0)


# ---------------------------------------------------------------------------
# 2. Real nano model: generate returns str; seeded determinism  [MACHINERY, random init]
# ---------------------------------------------------------------------------


class TestRealModelDecode:
    PROMPT = "<|user|>\nCompute 2 + 2 using python."

    def test_greedy_returns_string_and_is_deterministic(self, nano_model, char_tok):
        pol = TorchModelPolicy(nano_model, char_tok, max_new_tokens=12,
                               temperature=0.0, context_window=128)
        a = pol(self.PROMPT)
        b = pol(self.PROMPT)
        assert isinstance(a, str)
        assert a == b, "greedy decode must be run-to-run deterministic"

    def test_sampling_same_seed_identical(self, nano_model, char_tok):
        pol = TorchModelPolicy(nano_model, char_tok, max_new_tokens=12, temperature=1.0,
                               top_k=50, seed=123, context_window=128)
        a = pol.generate(self.PROMPT)
        b = pol.generate(self.PROMPT)
        assert isinstance(a, str)
        assert a == b, "same torch.Generator seed must reproduce the sample bit-for-bit"

    def test_sampling_different_seeds_differ(self, nano_model, char_tok):
        pol = TorchModelPolicy(nano_model, char_tok, max_new_tokens=16, temperature=1.0,
                               top_k=0, context_window=128)
        a = pol.generate(self.PROMPT, seed=1)
        b = pol.generate(self.PROMPT, seed=2)
        # 16 near-uniform draws over ~8192 ids: identical outputs across seeds would signal a
        # generator-threading bug, not chance.
        assert a != b


# ---------------------------------------------------------------------------
# 3. Stop-sequence cutting (scripted stub: exact stream is known)
# ---------------------------------------------------------------------------


class TestStopCutting:
    def test_user_marker_cuts_turn(self, char_tok):
        script = char_tok.encode("hello world<|user|>LEAKED")
        pol = TorchModelPolicy(ScriptedSequenceLM(script), char_tok, max_new_tokens=64,
                               stop_sequences=("<|user|>",), context_window=256)
        out = pol("<|user|>\nhi")
        assert out == "hello world"
        assert "LEAKED" not in out and "<|user|>" not in out

    def test_eos_id_cuts_turn(self):
        tok = DigitTokenizer()
        # script: 4, 5, then eos (7), then 6 which must never be reached
        pol = TorchModelPolicy(ScriptedSequenceLM([4, 5, 7, 6], vocab=8), tok,
                               max_new_tokens=16, eos_id=7, stop_sequences=(),
                               context_window=32)
        assert pol.generate("3") == "45"

    def test_budget_exhaustion_returns_partial_turn(self, char_tok):
        script = char_tok.encode("abcdefgh")            # no stop anywhere in the stream
        pol = TorchModelPolicy(ScriptedSequenceLM(script), char_tok, max_new_tokens=4,
                               stop_sequences=("<|user|>",), context_window=64)
        assert pol.generate("x") == "abcd"              # budget cap, honest partial


# ---------------------------------------------------------------------------
# 4. Left-truncation respects the context window (recorded on a REAL model forward)
# ---------------------------------------------------------------------------


class TestLeftTruncation:
    def test_window_enforced_on_real_model(self, nano_model, char_tok):
        rec = RecordingWrapper(nano_model)
        pol = TorchModelPolicy(rec, char_tok, max_new_tokens=4, context_window=32)
        long_prompt = "x" * 200                          # 200 tokens >> 32-token window
        pol.generate(long_prompt)
        assert rec.seen_lengths, "model was never called"
        assert max(rec.seen_lengths) <= 32
        assert rec.seen_lengths[0] == 32                 # truncated, not padded/short

    def test_left_side_is_the_side_dropped(self):
        tok = DigitTokenizer()
        # HandComputedLM keys logits on the LAST id. Prompt '73' with window=1 feeds only [3]
        # (the RIGHTMOST token) -> first pick is ROWS[3] argmax = 4. If the RIGHT side were
        # dropped instead, last id would be 7 and ROWS would KeyError.
        pol = TorchModelPolicy(HandComputedLM(), tok, max_new_tokens=1, context_window=1,
                               stop_sequences=(), )
        assert pol.generate("73") == "4"


# ---------------------------------------------------------------------------
# 5. Greedy argmax-consistency: hand-computed 2-step case, raw-tensor adapter path
# ---------------------------------------------------------------------------


class TestGreedyHandComputed:
    def test_two_step_argmax_chain(self):
        # Hand computation (see HandComputedLM.ROWS): prompt '3' -> last=3 -> argmax 4;
        # then last=4 -> argmax 5. Two steps => '45'.
        pol = TorchModelPolicy(HandComputedLM(), DigitTokenizer(), max_new_tokens=2,
                               temperature=0.0, stop_sequences=(), context_window=8)
        assert pol.generate("3") == "45"

    def test_adapter_rejects_garbage_output(self):
        class BadLM:
            def __call__(self, *, input_ids, **kw):
                return [1, 2, 3]
        pol = TorchModelPolicy(BadLM(), DigitTokenizer(), max_new_tokens=1, stop_sequences=())
        with pytest.raises(TypeError, match="logits"):
            pol.generate("3")

    def test_adapter_accepts_last_step_2d_logits(self):
        class TwoDLM:
            def __call__(self, *, input_ids, **kw):
                logits = torch.full((1, 8), -30.0)
                logits[0, 6] = 30.0
                return logits
        pol = TorchModelPolicy(TwoDLM(), DigitTokenizer(), max_new_tokens=1, stop_sequences=())
        assert pol.generate("3") == "6"

    def test_extract_logits_dict_contract(self):
        t = torch.zeros(1, 5, 8)
        assert _extract_logits({"lm_logits": t}).shape == (1, 8)
        with pytest.raises(TypeError, match="lm_logits"):
            _extract_logits({"fused": t})


# ---------------------------------------------------------------------------
# 6. LOOP INTEGRATION — full chain model->decode->REAL sandbox->observe->FINAL.
#    SCRIPTED-LOGITS stub (synthetic weights, clearly labeled): MACHINERY test, NOT capability.
# ---------------------------------------------------------------------------


class TestLoopIntegration:
    TURN_ACT = "Thought: compute it with real execution.\n```python\nprint(2 + 2)\n```"
    TURN_FINAL = "FINAL: The result is 4."

    @posix_only
    def test_scripted_policy_through_real_sandbox_reaches_final(self, char_tok):
        # The stub's logits spell out: action turn, stop marker, final turn, stop marker.
        script = char_tok.encode(self.TURN_ACT + "<|user|>" + self.TURN_FINAL + "<|user|>")
        stub = ScriptedSequenceLM(script)
        pol = TorchModelPolicy(stub, char_tok, max_new_tokens=len(script) + 8,
                               temperature=0.0, stop_sequences=("<|user|>",),
                               context_window=2048)
        res = run_code_act(pol, "What is 2 + 2? Use python.", max_steps=4)

        assert res.reached_final
        assert "4" in res.final                         # sanitized FINAL carries the answer
        assert "```python" not in res.final             # code never leaks to the user string
        assert len(res.steps) == 1                      # exactly one real sandbox execution
        obs = res.steps[0].observation
        assert obs.ok and obs.stdout.strip() == "4"     # REAL sandbox actually ran print(2+2)
        assert res.steps[0].code == "print(2 + 2)"

    @posix_only
    def test_untrained_real_model_runs_without_crashing(self, nano_model, char_tok):
        # HONEST LABEL: random-init nano has no capability; its noise turn will not contain a
        # valid fence, so the loop terminates via 'final' (noise prose) or 'policy_empty' /
        # 'step_cap'. The claim under test is only that the REAL model drives the REAL loop and
        # sandbox without exceptions — capability arrives with a trained checkpoint, not here.
        pol = TorchModelPolicy(nano_model, char_tok, max_new_tokens=16, temperature=0.0,
                               context_window=128)
        res = run_code_act(pol, "What is 2 + 2?", max_steps=2, timeout_s=5.0)
        assert res.terminated in {"final", "policy_empty", "step_cap"}
