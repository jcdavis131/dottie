"""Ollama — openswap #17 (ChatGPT Plus / hosted LLM APIs -> a loopback daemon).

Offline and deterministic by construction. Every HTTP boundary is injected: the
GET probe and the POST completer are fakes returning canned
{"status","json","error"} dicts, exactly the shape plugins/ollama/cli.py::_request
produces, so no test in this file opens a socket to a daemon. The subprocess
tests aim the CLI at a CLOSED loopback port (127.0.0.1:1) — connection refused
without a single packet leaving the box — which is also the real degraded path
this adapter exists to get right, and an explicit --base is exclusive so a
daemon that happens to be running on :11434 can never be reached instead.

What these tests refuse to allow:
- model-shaped prose that no model produced (the DEGRADED banner, the
  NOT ANSWERED marker, source/degraded fields, --fail-on-degraded)
- "gpu" inferred from anything other than ollama's own size_vram
- a substituted model when the caller named one that is not installed
- a usage ledger that quietly becomes a prompt log
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bigbang.core import ollama, openswap

ROOT = Path(__file__).resolve().parents[1]

BASE = "http://127.0.0.1:11434"
DEAD = "http://127.0.0.1:1"  # closed loopback port: refused, never routed
REFUSED = {
    "status": None,
    "json": None,
    "error": "ConnectionRefusedError: [WinError 10061] no daemon",
}

TAGS = {
    "models": [
        {
            "name": "qwen3:32b",
            "model": "qwen3:32b",
            "size": 20_000_000_000,
            "modified_at": "2026-07-01T10:00:00Z",
            "details": {
                "family": "qwen3",
                "parameter_size": "32.8B",
                "quantization_level": "Q4_K_M",
            },
        },
        {
            "name": "qwen3:8b",
            "model": "qwen3:8b",
            "size": 5_200_000_000,
            "modified_at": "2026-07-02T10:00:00Z",
            "details": {
                "family": "qwen3",
                "parameter_size": "8.2B",
                "quantization_level": "Q4_K_M",
            },
        },
        {
            "name": "gemma3:4b",
            "model": "gemma3:4b",
            "size": 3_300_000_000,
            "modified_at": "2026-07-03T10:00:00Z",
            "details": {"family": "gemma3", "parameter_size": "4.3B"},
        },
    ]
}

# the box's real shape: resident in SYSTEM RAM, size_vram 0 (NUM_GPU=0)
PS_CPU = {
    "models": [
        {
            "name": "qwen3:8b",
            "size": 6_000_000_000,
            "size_vram": 0,
            "expires_at": "2026-07-24T12:05:00Z",
        }
    ]
}

GENERATED = {
    "model": "qwen3:8b",
    "response": "The ratchet banked bf16 wins because fp32 measured 35 min/step.",
    "done": True,
    "done_reason": "stop",
    "prompt_eval_count": 31,
    "eval_count": 64,
    "eval_duration": 8_000_000_000,  # 8s -> 8 tok/s
    "total_duration": 9_100_000_000,
}


# MEASURED on this box (ollama 0.31.1, qwen3:8b, NUM_GPU=0): --num-predict 24
# against a thinking model returns 200 with a full `thinking` field, an EMPTY
# response and done_reason "length". Reasoning is not a reply.
THINKING_ONLY = {
    "model": "qwen3:8b",
    "response": "",
    "thinking": "Okay, the user is asking if the box is using its GPU. I need to check",
    "done": True,
    "done_reason": "length",
    "prompt_eval_count": 22,
    "eval_count": 24,
    "eval_duration": 12_000_000_000,  # 2 tok/s — system RAM, not a 4080
}


def _ok(payload):
    return {"status": 200, "json": payload, "error": None}


def _prober(mapping):
    """Injected GET boundary. Unmapped (base, path) pairs are connection-refused."""
    calls: list[tuple[str, str]] = []

    def probe(base, path):
        calls.append((base, path))
        return mapping.get((base, path), REFUSED)

    probe.calls = calls
    return probe


def _poster(result):
    """Injected POST boundary returning one canned result; records every call."""
    calls: list[tuple[str, str, dict]] = []

    def post(base, path, payload):
        calls.append((base, path, payload))
        return result

    post.calls = calls
    return post


def _clock(*values):
    """Deterministic monotonic stand-in so elapsed_s is asserted, not tolerated."""
    seq = iter(values)
    return lambda: next(seq)


# ---- endpoints: an explicit base is exclusive --------------------------------


def test_normalize_base_accepts_every_shape_people_actually_paste():
    assert ollama.normalize_base("127.0.0.1") == "http://127.0.0.1:11434"
    assert ollama.normalize_base("127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert ollama.normalize_base("http://localhost:11434/") == "http://localhost:11434"
    assert ollama.normalize_base("http://box:11434/api/tags") == "http://box:11434"
    assert ollama.normalize_base("https://box") == "https://box:11434"
    assert ollama.normalize_base("  127.0.0.1:9999  ") == "http://127.0.0.1:9999"


def test_normalize_base_refuses_what_it_cannot_understand():
    for bad in ("", "   ", "http://", "://x"):
        with pytest.raises(ValueError):
            ollama.normalize_base(bad)
    with pytest.raises(ValueError, match="http"):
        ollama.normalize_base("ftp://box:11434")
    with pytest.raises(ValueError, match="http"):
        ollama.normalize_base("file:///etc/passwd")


def test_explicit_base_suppresses_the_discovery_chain():
    """Naming :1 and answering from :11434 would be the quiet lie."""
    env = {"OLLAMA_HOST": "http://elsewhere:11434"}
    assert ollama.candidate_bases("127.0.0.1:1", env) == ["http://127.0.0.1:1"]
    assert ollama.candidate_bases("http://127.0.0.1:1/", env) == ["http://127.0.0.1:1"]
    # an unparseable explicit base yields NO candidates rather than falling back
    assert ollama.candidate_bases("ftp://x", env) == []


def test_discovery_chain_is_env_then_loopback_deduped():
    assert ollama.candidate_bases(None, {}) == list(ollama.DEFAULT_BASES)
    chain = ollama.candidate_bases(None, {"OLLAMA_HOST": "box:11434"})
    assert chain[0] == "http://box:11434"
    assert chain[1:] == list(ollama.DEFAULT_BASES)
    # env precedence follows ENV_BASES order
    both = ollama.candidate_bases(
        None, {"OLLAMA_BASE": "first:11434", "OLLAMA_HOST": "second:11434"}
    )
    assert both[:2] == ["http://first:11434", "http://second:11434"]
    # an already-default env value does not appear twice
    assert ollama.candidate_bases(None, {"OLLAMA_HOST": "127.0.0.1:11434"}) == list(
        ollama.DEFAULT_BASES
    )


def test_a_typo_in_env_never_takes_out_the_loopback_default():
    chain = ollama.candidate_bases(None, {"OLLAMA_HOST": "ftp://nope"})
    assert chain == list(ollama.DEFAULT_BASES)


def test_is_loopback_is_strict_so_the_stricter_gate_wins_by_default():
    for good in (BASE, "http://localhost:11434", "http://[::1]:11434"):
        assert ollama.is_loopback(good) is True
    for off_box in (
        "http://10.0.0.5:11434",
        "http://127.0.0.2:11434",
        "https://api.openai.com:11434",
        "http://127.0.0.1.evil.com:11434",
    ):
        assert ollama.is_loopback(off_box) is False


# ---- resolution keeps the evidence ------------------------------------------


def test_resolve_stops_at_the_first_answer_and_records_the_attempts():
    probe = _prober({(BASE, ollama.VERSION_PATH): _ok({"version": "0.6.2"})})
    res = ollama.resolve(probe, ["http://box:11434", BASE], path=ollama.VERSION_PATH)
    assert res["reachable"] is True and res["base"] == BASE
    assert ollama.parse_version(res["payload"]) == "0.6.2"
    assert [t["base"] for t in res["tried"]] == ["http://box:11434", BASE]
    assert res["tried"][0]["ok"] is False and res["tried"][0]["status"] is None
    assert "ConnectionRefused" in res["tried"][0]["error"]
    assert res["tried"][1]["ok"] is True and res["tried"][1]["status"] == 200
    # it stopped: nothing was probed after the answer
    assert probe.calls == [
        ("http://box:11434", ollama.VERSION_PATH),
        (BASE, ollama.VERSION_PATH),
    ]


def test_resolve_treats_non_200_and_bodyless_200_as_no_answer():
    for bad in (
        {"status": 404, "json": {"error": "not found"}, "error": "HTTP 404"},
        {"status": 500, "json": None, "error": "HTTP 500"},
        {"status": 200, "json": None, "error": None},  # a proxy's HTML login page
    ):
        res = ollama.resolve(
            _prober({(BASE, ollama.TAGS_PATH): bad}), [BASE], path=ollama.TAGS_PATH
        )
        assert res["reachable"] is False and res["base"] is None
        assert res["payload"] is None
        assert res["tried"][0]["ok"] is False


def test_unreachable_reason_names_every_endpoint_and_how_it_failed():
    res = ollama.resolve(
        _prober(
            {(BASE, ollama.TAGS_PATH): {"status": 503, "json": None, "error": None}}
        ),
        ["http://box:11434", BASE],
        path=ollama.TAGS_PATH,
    )
    why = ollama.unreachable_reason(res)
    assert "http://box:11434" in why and BASE in why
    assert "ConnectionRefusedError" in why  # the stopped-daemon case, quoted
    assert "HTTP 503" in why  # the wrong-thing-listening case, distinguished
    assert ollama.TAGS_PATH in why


def test_resolve_with_no_candidates_is_unreachable_not_a_crash():
    res = ollama.resolve(_prober({}), [], path=ollama.TAGS_PATH)
    assert res["reachable"] is False and res["tried"] == []
    assert "no candidate endpoints" in ollama.unreachable_reason(res)


# ---- catalog: what a tag listing does and does NOT know ----------------------


def test_parse_models_normalizes_and_sorts_the_catalog():
    rows = ollama.parse_models(TAGS)
    assert [r["name"] for r in rows] == ["gemma3:4b", "qwen3:32b", "qwen3:8b"]
    q8 = next(r for r in rows if r["name"] == "qwen3:8b")
    assert q8["family"] == "qwen3" and q8["parameter_size"] == "8.2B"
    assert q8["quantization"] == "Q4_K_M"
    assert q8["size_bytes"] == 5_200_000_000 and q8["size_gb"] == 5.2
    assert q8["modified"] == "2026-07-02T10:00:00Z"
    # a listing without details keeps the row and reports the gaps as None
    g4 = next(r for r in rows if r["name"] == "gemma3:4b")
    assert g4["quantization"] is None and g4["family"] == "gemma3"


def test_catalog_rows_carry_no_placement_because_tags_cannot_know_it():
    for row in ollama.parse_models(TAGS):
        assert "placement" not in row
        assert "vram_bytes" not in row and "gpu" not in row


def test_parse_models_survives_hostile_and_empty_payloads():
    assert ollama.parse_models(None) == []
    assert ollama.parse_models({}) == []
    assert ollama.parse_models({"models": None}) == []
    assert ollama.parse_models("not a dict") == []
    junk = {"models": ["bare string", 42, None, {}, {"name": "   "}, {"model": "ok:1"}]}
    rows = ollama.parse_models(junk)
    assert [r["name"] for r in rows] == ["ok:1"]
    assert rows[0]["size_bytes"] is None and rows[0]["size_gb"] is None


# ---- placement: never assume GPU --------------------------------------------


def test_placement_matrix_never_guesses_gpu():
    assert ollama.placement(6_000_000_000, None) == ollama.PLACEMENT_UNKNOWN
    assert ollama.placement(6_000_000_000, 0) == ollama.PLACEMENT_CPU
    assert ollama.placement(6_000_000_000, 6_000_000_000) == ollama.PLACEMENT_GPU
    assert ollama.placement(6_000_000_000, 7_000_000_000) == ollama.PLACEMENT_GPU
    assert ollama.placement(6_000_000_000, 2_000_000_000) == ollama.PLACEMENT_SPLIT
    # vram reported but total unknown: the split is unknown, not assumed
    assert ollama.placement(None, 2_000_000_000) == ollama.PLACEMENT_UNKNOWN
    assert ollama.placement(None, None) == ollama.PLACEMENT_UNKNOWN
    assert ollama.PLACEMENT_UNKNOWN != ollama.PLACEMENT_GPU


def test_parse_loaded_reports_this_box_as_cpu_resident():
    rows = ollama.parse_loaded(PS_CPU)
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "qwen3:8b"
    assert row["placement"] == ollama.PLACEMENT_CPU
    assert row["vram_bytes"] == 0 and row["vram_gb"] == 0.0
    assert row["size_bytes"] == 6_000_000_000 and row["size_gb"] == 6.0
    assert row["expires_at"] == "2026-07-24T12:05:00Z"


def test_parse_loaded_handles_absent_vram_key_and_junk():
    rows = ollama.parse_loaded({"models": [{"name": "m:1", "size": 100}]})
    assert rows[0]["placement"] == ollama.PLACEMENT_UNKNOWN
    assert rows[0]["vram_bytes"] is None
    assert ollama.parse_loaded(None) == []
    assert ollama.parse_loaded({"models": [{}, 7, "x"]}) == []
    two = ollama.parse_loaded(
        {
            "models": [
                {"name": "b:1", "size": 2, "size_vram": 2},
                {"name": "a:1", "size": 2, "size_vram": 0},
            ]
        }
    )
    assert [r["name"] for r in two] == ["a:1", "b:1"]
    assert two[0]["placement"] == ollama.PLACEMENT_CPU
    assert two[1]["placement"] == ollama.PLACEMENT_GPU


# ---- model choice is cost-first AND explained --------------------------------


def test_default_pick_is_the_smallest_installed_model_not_the_biggest():
    catalog = ollama.parse_models(TAGS)
    name, why = ollama.pick_model(catalog)
    assert name == "gemma3:4b"  # 3.3 GB, not the 20 GB qwen3:32b
    assert "smallest" in why and "NUM_GPU=0" in why


def test_a_resident_model_beats_a_smaller_cold_one():
    catalog = ollama.parse_models(TAGS)
    name, why = ollama.pick_model(catalog, loaded=ollama.parse_loaded(PS_CPU))
    assert name == "qwen3:8b"
    assert "resident" in why and ollama.PLACEMENT_CPU in why
    # a resident model that is not installed anymore is ignored
    stale = [{"name": "deleted:1", "placement": "cpu"}]
    assert ollama.pick_model(catalog, loaded=stale)[0] == "gemma3:4b"


def test_explicit_request_wins_exactly_or_by_unique_prefix():
    catalog = ollama.parse_models(TAGS)
    assert ollama.pick_model(catalog, want="qwen3:8b")[0] == "qwen3:8b"
    assert "explicit" in ollama.pick_model(catalog, want="qwen3:8b")[1]
    assert ollama.pick_model(catalog, want="QWEN3:8B")[0] == "qwen3:8b"
    name, why = ollama.pick_model(catalog, want="gemma")
    assert name == "gemma3:4b" and "unique prefix" in why
    # explicit beats residency
    assert (
        ollama.pick_model(
            catalog, want="gemma3:4b", loaded=ollama.parse_loaded(PS_CPU)
        )[0]
        == "gemma3:4b"
    )


def test_a_named_model_that_is_absent_or_ambiguous_is_never_substituted():
    catalog = ollama.parse_models(TAGS)
    name, why = ollama.pick_model(catalog, want="llama3.1:70b")
    assert name is None
    assert "not installed" in why and "gemma3:4b" in why
    name2, why2 = ollama.pick_model(catalog, want="qwen3")
    assert name2 is None and "ambiguous" in why2
    assert "qwen3:32b" in why2 and "qwen3:8b" in why2


def test_pick_model_on_an_empty_catalog_says_what_to_do():
    name, why = ollama.pick_model([])
    assert name is None and "no models installed" in why
    assert "ollama pull" in why
    assert ollama.pick_model(None)[0] is None
    # no sizes reported at all still yields a usable choice
    name3, why3 = ollama.pick_model([{"name": "only:1"}])
    assert name3 == "only:1" and "no sizes reported" in why3


# ---- completion parsing ------------------------------------------------------


def test_parse_completion_reads_generate_shape_and_computes_server_tok_per_s():
    got = ollama.parse_completion(GENERATED)
    assert got["text"] == GENERATED["response"]
    assert got["model"] == "qwen3:8b" and got["done_reason"] == "stop"
    assert got["prompt_tokens"] == 31 and got["eval_tokens"] == 64
    assert got["eval_seconds"] == 8.0
    assert got["tok_per_s"] == 8.0  # 64 tokens / 8s, from eval_duration


def test_parse_completion_also_reads_the_chat_shape():
    got = ollama.parse_completion(
        {"model": "m:1", "message": {"role": "assistant", "content": "hi"}}
    )
    assert got["text"] == "hi" and got["model"] == "m:1"
    assert got["tok_per_s"] is None and got["eval_tokens"] is None


def test_parse_completion_returns_none_rather_than_an_empty_answer():
    for empty in (
        None,
        {},
        "text",
        {"response": ""},
        {"response": "   "},
        {"response": None},
        {"message": {}},
        {"message": {"content": ""}},
        {"error": "model not found"},
    ):
        assert ollama.parse_completion(empty) is None


def test_tok_per_s_is_omitted_rather_than_guessed():
    assert (
        ollama.parse_completion({"response": "x", "eval_count": 10})["tok_per_s"]
        is None
    )
    assert (
        ollama.parse_completion(
            {"response": "x", "eval_duration": 0, "eval_count": 10}
        )["tok_per_s"]
        is None
    )
    assert (
        ollama.parse_completion({"response": "x", "eval_count": 0, "eval_duration": 1})[
            "tok_per_s"
        ]
        is None
    )


def test_reasoning_is_never_accepted_as_an_answer():
    """The regression this adapter was caught on live: thinking is not a reply."""
    assert ollama.parse_completion(THINKING_ONLY) is None
    why = ollama.no_answer_reason(THINKING_ONLY)
    assert "reasoning" in why
    assert "24 tokens" in why and "done_reason=length" in why
    assert "--num-predict" in why  # the actual fix, not "restart the daemon"
    assert "broken" not in why


def test_no_answer_reason_separates_the_causes_it_can_prove():
    capped = ollama.no_answer_reason({"done_reason": "length", "eval_count": 8})
    assert "token cap" in capped and "8 tokens" in capped
    assert "reasoning" not in capped
    thought = ollama.no_answer_reason({"thinking": "hmm", "done_reason": "stop"})
    assert thought == "the model returned reasoning but no answer text"
    # nothing it can prove -> no invented explanation
    assert ollama.no_answer_reason({"done_reason": "stop"}) is None
    assert ollama.no_answer_reason({"thinking": "   "}) is None
    assert ollama.no_answer_reason(None) is None
    assert ollama.no_answer_reason("not a dict") is None


def test_telemetry_is_read_from_any_payload_answer_or_not():
    t = ollama.telemetry(THINKING_ONLY)
    assert t["eval_tokens"] == 24 and t["prompt_tokens"] == 22
    assert t["eval_seconds"] == 12.0 and t["tok_per_s"] == 2.0
    empty = ollama.telemetry(None)
    assert set(empty) == {"prompt_tokens", "eval_tokens", "eval_seconds", "tok_per_s"}
    assert all(v is None for v in empty.values())


def test_a_thinking_only_attempt_is_degraded_but_its_cost_is_recorded():
    rec = ollama.complete(
        _poster(_ok(THINKING_ONLY)),
        "is this box using its GPU?",
        model="qwen3:8b",
        base=BASE,
        now=1.0,
    )
    assert rec["degraded"] is True and rec["source"] == ollama.SOURCE_TEMPLATE
    assert rec["text"].startswith(ollama.DEGRADED_BANNER)
    assert (
        THINKING_ONLY["thinking"] not in rec["text"]
    )  # reasoning is not shown as an answer
    assert "raise --num-predict" in rec["reason"]
    assert rec["http_status"] == 200
    # the compute really happened, so the record must say so
    assert rec["eval_tokens"] == 24 and rec["tok_per_s"] == 2.0
    assert rec["prompt_tokens"] == 22 and rec["eval_seconds"] == 12.0


# ---- honest degradation ------------------------------------------------------


def test_template_is_banner_led_and_says_it_did_not_answer():
    out = ollama.assemble_template(
        "summarize the ratchet decision", reason="daemon down"
    )
    lines = out["text"].splitlines()
    assert lines[0] == ollama.DEGRADED_BANNER
    assert "TEMPLATE ASSEMBLY" in lines[0] and "not inference" in lines[0]
    assert lines[1] == "reason: daemon down"
    assert any(ollama.NOT_ANSWERED in ln for ln in lines)
    assert any("No model reasoned about the request" in ln for ln in lines)
    assert "keyword match, not comprehension" in out["text"]


def test_template_echoes_the_request_verbatim_so_you_see_what_was_missed():
    prompt = "why did fp32 measure 35 min/step on the 4080 box?"
    out = ollama.assemble_template(prompt, reason="r")
    assert prompt in out["text"]
    assert "--- your request, verbatim ---" in out["text"]
    assert out["prompt_truncated"] is False


def test_a_long_prompt_is_truncated_and_flagged():
    prompt = "x" * (ollama.PROMPT_ECHO_CHARS + 50)
    out = ollama.assemble_template(prompt, reason="r")
    assert out["prompt_truncated"] is True
    assert "…[truncated]" in out["text"]
    assert prompt not in out["text"]
    assert "x" * ollama.PROMPT_ECHO_CHARS in out["text"]
    # an unbroken wall of characters is not a "term" and must not sneak the
    # whole prompt back in through the salient-terms line
    assert out["terms"] == []
    assert ollama.salient_terms("y" * (ollama.MAX_TERM_CHARS + 1)) == []
    assert ollama.salient_terms("y" * ollama.MAX_TERM_CHARS) == [
        "y" * ollama.MAX_TERM_CHARS
    ]


def test_template_is_byte_identical_across_runs():
    """A degraded answer that varies between runs would look like a model."""
    a = ollama.assemble_template("compare bf16 versus fp32 throughput", reason="r")
    b = ollama.assemble_template("compare bf16 versus fp32 throughput", reason="r")
    assert a["text"] == b["text"]
    assert a["terms"] == b["terms"] and a["intent"] == b["intent"]


def test_salient_terms_come_only_from_the_prompts_own_words():
    prompt = "The trainer step time regressed; the trainer clocks sit at 780MHz."
    terms = ollama.salient_terms(prompt)
    low = prompt.lower()
    assert terms, "expected extracted terms"
    for t in terms:
        assert t in low, t
    assert terms[0] == "trainer"  # frequency-ranked
    assert not ({"the", "at"} & set(terms))  # stopwords dropped
    assert all(len(t) >= 3 for t in terms)
    assert ollama.salient_terms("the and of it") == []
    assert ollama.salient_terms("alpha beta gamma", limit=2) == ["alpha", "beta"]


def test_intent_is_keyword_matched_and_drives_the_scaffold_slots():
    cases = {
        "summarize this thread": "summarize",
        "give me a tl;dr": "summarize",
        "list the top options for storage": "list",
        "compare bf16 versus fp32": "compare",
        "write a regex for semver": "code",
        "why is the step time 35 minutes": "explain",
        "fix this traceback": "debug",
        "draft an email to the operator": "draft",
        "banana": "other",
    }
    for prompt, want in cases.items():
        out = ollama.assemble_template(prompt, reason="r")
        assert out["intent"] == want, prompt
        for slot in ollama._INTENT_SLOTS[want]:
            assert f"- {slot}" in out["text"], (prompt, slot)
    debug = ollama.assemble_template("fix this traceback", reason="r")["text"]
    assert "exact error text:" in debug
    assert "audience:" not in debug  # slots are intent-specific, not a superset


def test_scaffold_lines_are_slots_and_never_assertions():
    out = ollama.assemble_template("explain the ratchet", reason="r")
    tail = out["text"].split("--- scaffold to fill in", 1)[1].splitlines()[1:]
    body = [ln for ln in tail if ln.strip()]
    assert body, "expected scaffold lines"
    for ln in body:
        assert ln.startswith("- "), ln
    assert all(ln.rstrip().endswith(":") for ln in body)


# ---- complete(): the boundary between an answer and a scaffold --------------


def test_complete_returns_a_model_record_when_the_daemon_answers():
    post = _poster(_ok(GENERATED))
    rec = ollama.complete(
        post,
        "why did fp32 lose?",
        model="qwen3:8b",
        base=BASE,
        system="be terse",
        options={"num_predict": 128},
        clock=_clock(999.0, 1000.0, 1002.5),
    )
    assert rec["ts"] == 999.0  # stamped from the clock, not wall time
    assert rec["source"] == ollama.SOURCE_MODEL and rec["degraded"] is False
    assert rec["text"] == GENERATED["response"]
    assert ollama.DEGRADED_BANNER not in rec["text"]
    assert rec["model"] == "qwen3:8b" and rec["base"] == BASE
    assert rec["http_status"] == 200
    assert rec["eval_tokens"] == 64 and rec["tok_per_s"] == 8.0
    assert rec["prompt_tokens"] == 31 and rec["eval_seconds"] == 8.0
    assert rec["elapsed_s"] == 2.5  # measured, from the injected clock
    assert rec["intent"] is None and rec["terms"] == []
    assert "answered via" in rec["reason"] and ollama.GENERATE_PATH in rec["reason"]
    # the request the daemon actually got
    base_sent, path_sent, payload = post.calls[0]
    assert (base_sent, path_sent) == (BASE, ollama.GENERATE_PATH)
    assert payload["model"] == "qwen3:8b" and payload["stream"] is False
    assert payload["prompt"] == "why did fp32 lose?"
    assert payload["system"] == "be terse"
    assert payload["options"] == {"num_predict": 128}


def test_complete_omits_optional_blocks_it_was_not_given():
    post = _poster(_ok(GENERATED))
    ollama.complete(post, "p", model="m:1", base=BASE, now=1.0)
    payload = post.calls[0][2]
    assert "system" not in payload and "options" not in payload


def test_complete_degrades_and_quotes_the_failure_for_every_bad_answer():
    prompt = "summarize the checkpoint cadence change"
    for result, expect in (
        (REFUSED, "ConnectionRefusedError"),
        (
            {"status": 404, "json": {"error": "model not found"}, "error": "HTTP 404"},
            "HTTP 404",
        ),
        ({"status": 200, "json": {"response": ""}, "error": None}, "HTTP 200"),
        ({"status": 500, "json": None, "error": None}, "HTTP 500"),
    ):
        post = _poster(result)
        rec = ollama.complete(post, prompt, model="qwen3:8b", base=BASE, now=5.0)
        assert rec["source"] == ollama.SOURCE_TEMPLATE
        assert rec["degraded"] is True
        assert rec["text"].startswith(ollama.DEGRADED_BANNER)
        assert ollama.NOT_ANSWERED in rec["text"]
        assert expect in rec["reason"], result
        assert "did not complete" in rec["reason"]
        assert rec["eval_tokens"] is None and rec["tok_per_s"] is None
        assert rec["intent"] == "summarize"
        assert prompt in rec["text"]
        assert len(post.calls) == 1  # it really did try


def test_complete_attempts_nothing_when_there_is_no_base_or_no_model():
    post = _poster(_ok(GENERATED))
    for base, model in ((None, "qwen3:8b"), (BASE, None), (None, None)):
        rec = ollama.complete(
            post, "p?", model=model, base=base, reason="nothing to call", now=1.0
        )
        assert rec["degraded"] is True and rec["source"] == ollama.SOURCE_TEMPLATE
        assert rec["reason"] == "nothing to call"
        assert "reason: nothing to call" in rec["text"]
        assert rec["http_status"] is None and rec["elapsed_s"] is None
    assert post.calls == []  # no socket was even considered


def test_complete_records_provenance_without_the_prompt():
    rec = ollama.complete(
        _poster(REFUSED), "secret plan alpha", model="m:1", base=BASE, now=2.0
    )
    assert rec["prompt_sha256"] == ollama.prompt_fingerprint("secret plan alpha")
    assert len(rec["prompt_sha256"]) == 16
    assert rec["prompt_chars"] == len("secret plan alpha")
    assert rec["prompt_sha256"] != ollama.prompt_fingerprint("secret plan beta")
    assert rec["ts"] == 2.0


def test_complete_never_raises_when_the_boundary_misbehaves():
    rec = ollama.complete(lambda b, p, body: None, "p", model="m:1", base=BASE, now=1.0)
    assert rec["degraded"] is True and "no response" in rec["reason"]


# ---- the ledger is a usage audit, not a prompt log --------------------------


def test_open_ledger_creates_its_own_file_and_is_idempotent(tmp_path):
    db = tmp_path / "nested" / "ollama.db"
    conn = ollama.open_ledger(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(completions)")}
    assert db.exists()
    assert {"ts", "source", "degraded", "model", "prompt_sha256", "tok_per_s"} <= cols
    assert (
        conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        == "1"
    )
    conn.close()
    again = ollama.open_ledger(db)  # re-open must not wipe or fail
    assert again.execute("SELECT COUNT(*) FROM completions").fetchone()[0] == 0
    again.close()
    assert ollama.DB_REL == Path(".scout") / "ollama.db"
    assert str(ollama.DB_REL) != "uptime.db"


def test_the_ledger_has_no_column_that_could_hold_a_transcript(tmp_path):
    conn = ollama.open_ledger(tmp_path / "o.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(completions)")}
    for forbidden in ("prompt", "text", "response", "completion", "messages"):
        assert forbidden not in cols
    assert {"prompt_sha256", "prompt_chars", "text_chars"} <= cols
    conn.close()


def test_recorded_rows_contain_neither_the_prompt_nor_the_answer(tmp_path):
    db = tmp_path / "o.db"
    confidential = "the codeword is bluehenre and the price is 4.2 million"
    answer = "Acknowledged: bluehenre-at-four-point-two."
    conn = ollama.open_ledger(db)
    rec = ollama.complete(
        _poster(
            _ok(
                {
                    "model": "qwen3:8b",
                    "response": answer,
                    "eval_count": 9,
                    "eval_duration": 3_000_000_000,
                }
            )
        ),
        confidential,
        model="qwen3:8b",
        base=BASE,
        now=1000.0,
    )
    rid = ollama.record_completion(conn, rec)
    conn.close()
    assert rid == 1
    raw = db.read_bytes()
    assert confidential.encode() not in raw
    assert b"bluehenre" not in raw
    assert answer.encode() not in raw
    # ...but the correlation handle and the measurements are there
    assert ollama.prompt_fingerprint(confidential).encode() in raw
    conn2 = ollama.open_ledger(db)
    row = ollama.history(conn2)[0]
    assert row["prompt_chars"] == len(confidential) and row["text_chars"] == len(answer)
    assert row["source"] == ollama.SOURCE_MODEL and row["degraded"] == 0
    assert row["eval_tokens"] == 9 and row["tok_per_s"] == 3.0
    conn2.close()


def test_degraded_attempts_are_recorded_too(tmp_path):
    conn = ollama.open_ledger(tmp_path / "o.db")
    ollama.record_completion(
        conn, ollama.complete(_poster(REFUSED), "p", model="m:1", base=BASE, now=1.0)
    )
    row = ollama.history(conn)[0]
    assert row["degraded"] == 1 and row["source"] == ollama.SOURCE_TEMPLATE
    assert row["eval_tokens"] is None
    assert "ConnectionRefused" in row["reason"]
    assert row["intent"] == "other"
    conn.close()


def test_history_is_newest_first_and_filterable_by_source(tmp_path):
    conn = ollama.open_ledger(tmp_path / "o.db")
    for i, src in enumerate(
        [ollama.SOURCE_MODEL, ollama.SOURCE_TEMPLATE, ollama.SOURCE_MODEL], start=1
    ):
        ollama.record_completion(
            conn,
            {
                "ts": 100.0 * i,
                "source": src,
                "degraded": src == ollama.SOURCE_TEMPLATE,
                "text": "t",
                "model": f"m:{i}",
                "prompt_sha256": f"h{i}",
                "prompt_chars": 3,
            },
        )
    assert [r["ts"] for r in ollama.history(conn)] == [300.0, 200.0, 100.0]
    assert [r["ts"] for r in ollama.history(conn, limit=2)] == [300.0, 200.0]
    only_model = ollama.history(conn, source=ollama.SOURCE_MODEL)
    assert [r["model"] for r in only_model] == ["m:3", "m:1"]
    assert all(r["source"] == ollama.SOURCE_MODEL for r in only_model)
    conn.close()


def test_usage_on_an_empty_ledger_reports_none_not_zero_percent(tmp_path):
    conn = ollama.open_ledger(tmp_path / "o.db")
    roll = ollama.usage(conn)
    assert roll["total"] == 0
    assert roll["model_share_pct"] is None  # not 0.0, not 100.0
    assert roll["by_source"] == {ollama.SOURCE_MODEL: 0, ollama.SOURCE_TEMPLATE: 0}
    assert roll["eval_tokens"] == 0 and roll["by_model"] == {}
    assert roll["tok_per_s"] == {"p50": None, "max": None}
    assert roll["first_ts"] is None and roll["last_ts"] is None
    conn.close()


def test_usage_is_the_honesty_audit_model_versus_template(tmp_path):
    conn = ollama.open_ledger(tmp_path / "o.db")
    rows = [
        (ollama.SOURCE_MODEL, "qwen3:8b", 10, 5.0, 100.0),
        (ollama.SOURCE_MODEL, "qwen3:8b", 30, 15.0, 200.0),
        (ollama.SOURCE_MODEL, "gemma3:4b", 20, 25.0, 300.0),
        (ollama.SOURCE_TEMPLATE, None, None, None, 400.0),
    ]
    for src, model, toks, rate, ts in rows:
        ollama.record_completion(
            conn,
            {
                "ts": ts,
                "source": src,
                "degraded": src == ollama.SOURCE_TEMPLATE,
                "text": "x",
                "model": model,
                "prompt_sha256": "h",
                "prompt_chars": 1,
                "eval_tokens": toks,
                "tok_per_s": rate,
            },
        )
    roll = ollama.usage(conn)
    assert roll["total"] == 4
    assert roll["by_source"] == {ollama.SOURCE_MODEL: 3, ollama.SOURCE_TEMPLATE: 1}
    assert roll["model_share_pct"] == 75.0
    assert roll["eval_tokens"] == 60
    assert roll["by_model"] == {"gemma3:4b": 1, "qwen3:8b": 2}
    assert roll["tok_per_s"]["p50"] == 15.0  # model rows only
    assert roll["tok_per_s"]["max"] == 25.0
    assert roll["first_ts"] == 100.0 and roll["last_ts"] == 400.0
    windowed = ollama.usage(conn, since=300.0)
    assert windowed["total"] == 2
    assert windowed["model_share_pct"] == 50.0
    assert windowed["eval_tokens"] == 20
    conn.close()


def test_usage_counts_compute_that_produced_no_answer(tmp_path):
    """24 tokens burned reasoning is a real cost; hiding it understates the box."""
    conn = ollama.open_ledger(tmp_path / "o.db")
    ollama.record_completion(
        conn,
        ollama.complete(
            _poster(_ok(THINKING_ONLY)), "p?", model="qwen3:8b", base=BASE, now=1.0
        ),
    )
    roll = ollama.usage(conn)
    assert roll["by_source"] == {ollama.SOURCE_MODEL: 0, ollama.SOURCE_TEMPLATE: 1}
    assert roll["model_share_pct"] == 0.0  # it answered nothing
    assert roll["eval_tokens"] == 24  # ...but it spent this much
    assert roll["tok_per_s"]["p50"] == 2.0
    assert roll["by_model"] == {}  # a scaffold has no model
    conn.close()


# ---- family diagnostics ------------------------------------------------------


def test_unreachable_is_a_warning_with_an_actionable_suggestion():
    res = ollama.resolve(_prober({}), [BASE], path=ollama.VERSION_PATH)
    diags = ollama.endpoint_diagnostics(res)
    assert [d["rule"] for d in diags] == ["ollama:unreachable"]
    assert diags[0]["severity"] == "warning"  # a stopped daemon is not an error
    assert diags[0]["path"] == "ollama" and diags[0]["source"] == "ollama"
    assert "ollama serve" in diags[0]["suggestion"]
    assert BASE in diags[0]["message"]
    assert openswap.summarize(diags)["by_severity"]["warning"] == 1
    assert openswap.summarize(diags)["by_severity"]["error"] == 0


def test_cpu_placement_is_info_and_never_silent():
    res = ollama.resolve(
        _prober({(BASE, ollama.VERSION_PATH): _ok({"version": "0.6.2"})}),
        [BASE],
        path=ollama.VERSION_PATH,
    )
    diags = ollama.endpoint_diagnostics(res, loaded=ollama.parse_loaded(PS_CPU))
    assert [d["rule"] for d in diags] == ["ollama:cpu-placement"]
    assert diags[0]["severity"] == "info"  # NUM_GPU=0 is config, not a fault
    assert "qwen3:8b" in diags[0]["message"]
    assert "do not assume GPU" in diags[0]["message"]
    assert "cpu" in diags[0]["message"]
    # a genuinely GPU-resident model produces no placement finding at all
    gpu = ollama.parse_loaded(
        {"models": [{"name": "q:1", "size": 10, "size_vram": 10}]}
    )
    assert ollama.endpoint_diagnostics(res, loaded=gpu) == []


def test_no_models_is_only_claimed_when_we_actually_asked():
    live = ollama.resolve(
        _prober({(BASE, ollama.TAGS_PATH): _ok({"models": []})}),
        [BASE],
        path=ollama.TAGS_PATH,
    )
    diags = ollama.endpoint_diagnostics(live, models=[])
    assert [d["rule"] for d in diags] == ["ollama:no-models"]
    assert diags[0]["severity"] == "warning"
    assert "ollama pull" in diags[0]["suggestion"]
    # unreachable: we never got to ask, so it must NOT say "no models installed"
    dead = ollama.resolve(_prober({}), [BASE], path=ollama.TAGS_PATH)
    rules = [d["rule"] for d in ollama.endpoint_diagnostics(dead, models=[])]
    assert rules == ["ollama:unreachable"]
    assert "ollama:no-models" not in rules


def test_a_degraded_answer_is_a_warning_and_a_real_one_is_silent():
    good = ollama.complete(
        _poster(_ok(GENERATED)), "p", model="m:1", base=BASE, now=1.0
    )
    bad = ollama.complete(_poster(REFUSED), "p", model="m:1", base=BASE, now=1.0)
    assert ollama.to_diagnostics([good]) == []
    diags = ollama.to_diagnostics([bad])
    assert [d["rule"] for d in diags] == ["ollama:degraded"]
    assert diags[0]["severity"] == "warning"
    assert "template assembly, not inference" in diags[0]["message"]
    assert "fail-on-degraded" in diags[0]["suggestion"]
    mixed = ollama.to_diagnostics([good, bad, bad])
    assert len(mixed) == 2
    assert openswap.summarize(mixed)["by_rule"] == {"ollama:degraded": 2}
    assert ollama.to_diagnostics([]) == []


# ---- capability detection ----------------------------------------------------


def test_detection_reports_native_when_the_binary_is_on_path(monkeypatch):
    from bigbang.plugins.ollama import cli as ollama_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda b: f"/usr/local/bin/{b}")
    monkeypatch.setattr(
        openswap.subprocess,
        "run",
        lambda *a, **k: type(
            "R", (), {"returncode": 0, "stdout": "ollama version 0.6.2", "stderr": ""}
        )(),
    )
    cap = ollama_cli._capability()
    assert cap["adapter"] == "ollama"
    assert cap["tier"] == openswap.TIER_NATIVE
    assert cap["native"]["binary"] == "ollama"
    assert cap["native"]["version"] == "ollama version 0.6.2"
    assert "fallback_scope" not in cap  # native tier does not advertise the fallback


def test_detection_falls_back_and_the_scope_admits_it_cannot_answer(monkeypatch):
    from bigbang.plugins.ollama import cli as ollama_cli

    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = ollama_cli._capability()
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert cap["native"]["found"] is False
    assert "CANNOT answer questions" in cap["fallback_scope"]
    assert "does not pretend" in cap["fallback_scope"]
    assert "ollama pull qwen3:8b" in cap["install_hint"]
    assert "no API key" in cap["install_hint"]
    # local alternatives are surfaced, never executed
    assert cap["extras"]["llama-cli"]["found"] is False
    assert cap["extras"]["llamafile"]["found"] is False


# ---- policy: loopback only, no secrets --------------------------------------


def test_manifest_allows_loopback_only_and_holds_no_secrets():
    from bigbang.core.policy import check_permission, load_manifest

    mf = load_manifest(ROOT / "bigbang" / "plugins" / "ollama")
    assert mf["name"] == "ollama"
    net = mf["capabilities"]["network"]
    assert net["enabled"] is True
    assert set(net["domains"]) == {"127.0.0.1", "localhost", "::1"}
    for allowed in (f"{BASE}/api/tags", "http://localhost:11434/api/generate"):
        assert check_permission(mf, "network", allowed)[0] is True
    for denied in (
        "https://api.openai.com/v1/chat/completions",
        "https://api.anthropic.com/v1/messages",
        "http://10.0.0.5:11434/api/generate",
        "http://127.0.0.1.evil.com/api/tags",
    ):
        ok_, reason = check_permission(mf, "network", denied)
        assert ok_ is False, denied
        assert "not in allowlist" in reason
    assert mf["capabilities"]["secrets"]["allow"] == []
    assert check_permission(mf, "secret", "OPENAI_API_KEY")[0] is False
    assert check_permission(mf, "fs_write", ".scout/ollama.db")[0] is True


def test_plugin_is_discoverable():
    from bigbang.core.plugin_loader import list_plugin_names

    assert "ollama" in list_plugin_names()


# ---- the real CLI in a subprocess -------------------------------------------


def _cli(args, *, env=None, stdin=None, cwd=None):
    import os

    e = dict(os.environ)
    # the discovery chain must never be steered by the developer's shell
    for k in ollama.ENV_BASES:
        e.pop(k, None)
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin,
        timeout=120,
        cwd=str(cwd or ROOT),
        env=e,
    )


def test_cli_ollama_hello_envelope():
    r = _cli(["ollama", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True
    assert data["data"]["needs_api_key"] is False
    assert "example" in data


def test_cli_detect_against_a_closed_port_is_honest_and_gateable():
    r = _cli(["ollama", "detect", "--base", DEAD, "--timeout", "2"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    ep = data["endpoint"]
    assert ep["reachable"] is False and ep["base"] is None
    assert ep["version"] is None
    assert [t["base"] for t in ep["tried"]] == [DEAD]  # exclusive: no :11434 fallback
    assert ep["tried"][0]["ok"] is False
    assert "a binary on PATH is not a daemon that answers" in ep["note"]
    assert data["resident"] == []
    assert data["capability"]["adapter"] == "ollama"
    assert [d["rule"] for d in data["diagnostics"]] == ["ollama:unreachable"]
    assert data["summary"]["by_severity"]["warning"] == 1
    assert "uptime (#2)" in data["monitoring"]

    gated = _cli(
        ["ollama", "detect", "--base", DEAD, "--timeout", "2", "--fail-on", "warning"]
    )
    assert gated.returncode == 1
    assert json.loads(gated.stdout)["data"]["endpoint"]["reachable"] is False


def test_cli_rejects_a_bad_fail_on_before_doing_any_work():
    r = _cli(["ollama", "detect", "--base", DEAD, "--fail-on", "bogus"])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "--fail-on must be one of" in data["error"]
    assert "example" in data
    assert "capability" not in data  # nothing ran


def test_cli_rejects_an_unparseable_base():
    r = _cli(["ollama", "detect", "--base", "ftp://nope"])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "bad --base" in data["error"]
    assert "http" in data["error"]
    assert "example" in data


def test_cli_denies_an_off_loopback_endpoint_before_any_socket(tmp_path):
    """An off-box 'ollama' URL is a hosted API in disguise — denied by policy."""
    r = _cli(
        [
            "ollama",
            "run",
            "--prompt",
            "hi",
            "--base",
            "http://10.0.0.5:11434",
            "--no-record",
        ],
        env={"BIGBANG_POLICY_FILE": str(tmp_path / "policy.yaml")},
    )
    assert r.returncode == 1
    assert "denied" in (r.stdout + r.stderr).lower()
    assert "10.0.0.5" in (r.stdout + r.stderr)


def test_cli_models_does_not_claim_an_empty_catalog_it_never_saw():
    r = _cli(["ollama", "models", "--base", DEAD, "--timeout", "2"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["reachable"] is False and data["models"] == [] and data["count"] == 0
    assert data["would_pick"]["model"] is None
    assert "no ollama endpoint answered" in data["would_pick"]["reason"]
    assert "no models installed" not in data["would_pick"]["reason"]
    assert "never assumed" in data["placement_note"]
    assert [d["rule"] for d in data["diagnostics"]] == ["ollama:unreachable"]


def test_cli_run_degrades_honestly_and_records_it(tmp_path):
    db = tmp_path / "ollama.db"
    prompt = "summarize why the checkpoint cadence moved 25 to 15"
    r = _cli(
        [
            "ollama",
            "run",
            "--prompt",
            prompt,
            "--base",
            DEAD,
            "--timeout",
            "2",
            "--db",
            str(db),
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout  # degrading is not an error
    data = json.loads(r.stdout)["data"]
    assert data["degraded"] is True
    assert data["source"] == "template"
    assert data["text"].startswith(ollama.DEGRADED_BANNER)
    assert ollama.NOT_ANSWERED in data["text"]
    assert prompt in data["text"]  # echoed verbatim
    assert "checkpoint" in data["text"] and "cadence" in data["text"]
    assert data["model"] is None and data["base"] is None
    assert "no ollama endpoint answered" in data["selection_reason"]
    assert data["tokens"] == {"prompt": None, "eval": None, "tok_per_s": None}
    assert data["recorded"] == str(db)
    assert data["prompt_sha256"] == ollama.prompt_fingerprint(prompt)
    assert [d["rule"] for d in data["diagnostics"]] == ["ollama:degraded"]
    assert data["summary"]["by_severity"]["warning"] == 1
    assert db.exists()
    # the ledger recorded the attempt but not the prompt
    assert prompt.encode() not in db.read_bytes()
    conn = ollama.open_ledger(db)
    row = ollama.history(conn)[0]
    assert row["source"] == "template" and row["degraded"] == 1
    assert row["prompt_chars"] == len(prompt)
    assert row["text_chars"] == len(data["text"])
    conn.close()

    # the CI/cron hook: same run, nonzero exit, same honest payload
    gated = _cli(
        [
            "ollama",
            "run",
            "--prompt",
            prompt,
            "--base",
            DEAD,
            "--timeout",
            "2",
            "--db",
            str(db),
            "--fail-on-degraded",
        ]
    )
    assert gated.returncode == 1
    assert json.loads(gated.stdout)["data"]["degraded"] is True


def test_cli_run_reads_stdin_when_no_prompt_flag(tmp_path):
    r = _cli(
        ["ollama", "run", "--base", DEAD, "--timeout", "2", "--no-record"],
        stdin="why did fp32 lose the throughput test?\n",
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert "why did fp32 lose the throughput test?" in data["text"]
    assert data["recorded"] is None  # --no-record wrote nothing
    assert data["degraded"] is True


def test_cli_run_without_a_prompt_at_all_fails_actionably():
    r = _cli(["ollama", "run", "--base", DEAD, "--no-record"], stdin="")
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no prompt" in data["error"]
    assert "--prompt" in data["error"] or "--prompt" in data["example"]
    assert "example" in data


def test_cli_usage_reports_the_model_share_and_stores_no_prompts(tmp_path):
    db = tmp_path / "ollama.db"
    for prompt in ("first question about clocks", "second question about clocks"):
        run = _cli(
            [
                "ollama",
                "run",
                "--prompt",
                prompt,
                "--base",
                DEAD,
                "--timeout",
                "2",
                "--db",
                str(db),
            ]
        )
        assert run.returncode == 0, run.stderr + run.stdout
    r = _cli(["ollama", "usage", "--db", str(db)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["stores_prompts"] is False
    assert data["db"] == str(db)
    assert data["usage"]["total"] == 2
    assert data["usage"]["by_source"] == {"model": 0, "template": 2}
    assert data["usage"]["model_share_pct"] == 0.0  # this box answered nothing
    assert data["usage"]["eval_tokens"] == 0
    assert data["usage"]["by_model"] == {}
    assert len(data["recent"]) == 2
    assert all(row["source"] == "template" for row in data["recent"])
    assert "first question about clocks" not in json.dumps(data)


def test_cli_usage_without_a_ledger_fails_actionably(tmp_path):
    r = _cli(["ollama", "usage", "--db", str(tmp_path / "none.db")])
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert "no usage ledger" in data["error"]
    assert "example" in data
