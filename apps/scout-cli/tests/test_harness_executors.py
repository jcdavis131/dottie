"""Real executors, the tier probe and the runner's real/stub tagging.

Every network and model call is mocked: the suite runs with
DOTTIE_EXECUTORS=stub (conftest) and opts in per test.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from bigbang.core import llm
from bigbang.plugins.harness import executors, runner
from bigbang.plugins.harness.executors import deterministic, llm_exec, probe, research
from bigbang.plugins.harness.executors.base import (
    ExecResult,
    ExecutorUnavailable,
    NotApplicable,
    price,
)

# --- deterministic -------------------------------------------------------------------------


@pytest.mark.parametrize(("goal", "answer"), [
    ("What is 17 * 23 + 4?", "395"),
    ("What is 12.5% of 640?", "80"),
    ("Convert 3 miles to km.", "4.828032"),
    ("Convert -40 celsius to fahrenheit.", "-40"),
    ("How many minutes are in 2.5 hours?", "150"),
    ("Convert 255 to hexadecimal.", "ff"),
    ("Convert the binary number 1010 to decimal.", "10"),
    ("How many days are there between 2024-01-01 and 2024-03-01?", "60"),
    ("What day of the week was 2000-01-01?", "Saturday"),
    ("Convert 1994 to roman numerals.", "MCMXCIV"),
    ("What is the least common multiple of 4 and 6?", "12"),
    ("Is 91 a prime number?", "no"),
    ("Sort the numbers 3, -1, 2 in descending order.", "3, 2, -1"),
    ("Extract all hashtags from: ship #fast and #safe", "#fast, #safe"),
    ("Reverse the string 'abc'.", "cba"),
])
def test_deterministic_solvers(goal, answer):
    res = deterministic.run(goal)
    assert res.answer == answer and res.tier == "deterministic" and res.tokens["total"] == 0 and res.cost_usd == 0.0


def test_deterministic_refuses_prose_and_never_evals_code():
    with pytest.raises(NotApplicable):
        deterministic.run("Summarize the history of the Roman empire.")
    with pytest.raises(NotApplicable):
        deterministic.run("What is __import__('os').system('true')?")
    with pytest.raises(ValueError):
        deterministic.safe_eval("(1).__class__")
    with pytest.raises(ValueError):
        deterministic.safe_eval("2 ** 100000")


def test_scout_commands_are_allowlisted():
    with pytest.raises(NotApplicable, match="not an allowlisted"):
        deterministic.run("Run the read-only scout command `scout forge rm core`.")


# --- llm -----------------------------------------------------------------------------------


def _no_keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "DOTTIE_ANTHROPIC_MODEL", "OPENAI_API_KEY", "DOTTIE_OPENAI_MODEL",
              "DOTTIE_LLM_MODEL", "DOTTIE_LLM_PRICE_PER_MTOK_IN", "DOTTIE_LLM_PRICE_PER_MTOK_OUT"):
        monkeypatch.delenv(k, raising=False)


def test_llm_uses_ollama_first_and_records_measured_usage(monkeypatch):
    _no_keys(monkeypatch)
    monkeypatch.setattr(llm, "get_ollama_base", lambda **kw: "http://ollama.test:11434")
    seen = {}

    def gen(model, messages, base, **kw):
        seen.update(model=model, base=base)
        return {"content": "thinking...\nANSWER: 42", "completion_tokens": 5, "prompt_tokens": 31}

    monkeypatch.setattr(llm, "_ollama_generate", gen)
    res = llm_exec.run("What is six times seven?")
    assert res.answer == "42" and res.backend == "ollama:qwen2.5:7b-instruct"
    assert res.tokens == {"prompt": 31, "completion": 5, "total": 36}
    assert res.cost_usd == 0.0 and res.cost_basis == "local" and res.latency_ms >= 0
    assert seen == {"model": "qwen2.5:7b-instruct", "base": "http://ollama.test:11434"}


def test_llm_without_any_backend_is_unavailable_and_says_why(monkeypatch):
    _no_keys(monkeypatch)
    monkeypatch.setattr(llm, "get_ollama_base", lambda **kw: None)
    with pytest.raises(ExecutorUnavailable) as exc:
        llm_exec.run("anything")
    msg = str(exc.value)
    assert "ollama not reachable" in msg and "ANTHROPIC_API_KEY" in msg and "OPENAI_API_KEY" in msg


def test_llm_falls_back_to_anthropic_with_a_key_and_prices_only_from_env(monkeypatch):
    _no_keys(monkeypatch)
    monkeypatch.setattr(llm, "get_ollama_base", lambda **kw: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("DOTTIE_ANTHROPIC_MODEL", "some-model")
    monkeypatch.setattr(llm, "anthropic_chat",
                        lambda model, messages, key, **kw: {"content": "ANSWER: yes", "prompt_tokens": 1000, "completion_tokens": 500})
    res = llm_exec.run("q")
    assert res.backend == "anthropic:some-model" and res.cost_usd is None and res.cost_basis.startswith("unpriced")
    monkeypatch.setenv("DOTTIE_LLM_PRICE_PER_MTOK_IN", "3")
    monkeypatch.setenv("DOTTIE_LLM_PRICE_PER_MTOK_OUT", "15")
    assert llm_exec.run("q").cost_usd == pytest.approx(0.0105)
    assert price(10, 10, local=True) == (0.0, "local")


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _Client:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        return self.resp

    def close(self):
        pass


def test_anthropic_and_openai_clients_parse_usage(monkeypatch):
    c = _Client(_Resp(200, {"content": [{"type": "text", "text": "hi"}], "usage": {"input_tokens": 9, "output_tokens": 2}}))
    monkeypatch.setattr(llm, "_httpx_client", lambda timeout=0: c)
    out = llm.anthropic_chat("m", [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], "key")
    assert out == {"content": "hi", "completion_tokens": 2, "prompt_tokens": 9}
    url, body, headers = c.calls[0]
    assert url.endswith("/v1/messages") and body["system"] == "s" and headers["x-api-key"] == "key"
    o = _Client(_Resp(200, {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 4, "completion_tokens": 1}}))
    monkeypatch.setattr(llm, "_httpx_client", lambda timeout=0: o)
    assert llm.openai_chat("m", [], "https://api.example.com/v1", api_key="sk")["prompt_tokens"] == 4
    assert o.calls[0][0] == "https://api.example.com/v1/chat/completions"
    assert o.calls[0][2] == {"Authorization": "Bearer sk"}


# --- deep_research -------------------------------------------------------------------------

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry><id>http://arxiv.org/abs/1706.03762v7</id><published>2017-06-12T17:57:34Z</published>
<title>Attention Is All
 You Need</title><summary>The dominant sequence transduction models.</summary>
<author><name>Ashish Vaswani</name></author><author><name>Noam Shazeer</name></author>
<arxiv:primary_category term="cs.CL"/></entry></feed>"""


@pytest.fixture
def fast_arxiv(monkeypatch):
    monkeypatch.setenv("DOTTIE_ARXIV_MIN_INTERVAL", "0")
    monkeypatch.setattr(research.time, "sleep", lambda s: None)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_URL", raising=False)
    monkeypatch.setattr(llm_exec, "complete", lambda *a, **k: (_ for _ in ()).throw(ExecutorUnavailable("no llm")))


def test_research_extractive_answer_is_cited_and_verifiable(monkeypatch, fast_arxiv):
    from dottie_loop.verifiers import verify

    urls = []
    monkeypatch.setattr(research, "_get", lambda url, **kw: urls.append(url) or FEED)
    res = research.run("Who is the first author of arXiv paper 1706.03762?")
    assert res.answer == "Ashish Vaswani [1]" and res.sources[0]["primary_category"] == "cs.CL"
    assert res.backend == "arxiv" and res.meta["synthesis"] == "extractive" and res.tokens["total"] == 0
    assert urls == ["https://export.arxiv.org/api/query?id_list=1706.03762"]
    spec = {"type": "citations", "min_sources": 1, "answer_check": {"type": "contains", "expected": "Vaswani"}}
    assert verify(res.verifier_input(), spec)["passed"]


def test_research_title_search_is_form_encoded_and_prefers_the_exact_title(monkeypatch, fast_arxiv):
    urls = []
    monkeypatch.setattr(research, "_get", lambda url, **kw: urls.append(url) or FEED)
    res = research.run('Find the arXiv identifier of the paper titled "Attention Is All You Need".')
    assert res.answer == "1706.03762 [1]"
    assert "search_query=ti%3A%22Attention+Is+All+You+Need%22" in urls[0] and "%20" not in urls[0]


def test_research_falls_back_to_the_abs_page_when_the_api_refuses(monkeypatch, fast_arxiv):
    page = ('<meta name="citation_title" content="Deep Residual Learning for Image Recognition" />'
            '<meta name="citation_author" content="He, Kaiming" /><meta name="citation_date" content="2015/12/10" />'
            '<span class="primary-subject">Computer Vision and Pattern Recognition (cs.CV)</span>')

    def get(url, **kw):
        if "export.arxiv.org" in url:
            raise urllib.error.HTTPError(url, 406, "Not Acceptable", {}, None)
        return page.encode()

    monkeypatch.setattr(research, "_get", get)
    res = research.run("In which year was arXiv paper 1512.03385 first submitted?")
    assert res.answer == "2015 [1]" and res.sources[0]["authors"] == ["Kaiming He"]
    assert res.sources[0]["primary_category"] == "cs.CV"


def test_research_network_down_is_unavailable(monkeypatch, fast_arxiv):
    def down(url, **kw):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(research, "_get", down)
    with pytest.raises(ExecutorUnavailable, match="arXiv unreachable"):
        research.run("Who is the first author of arXiv paper 1706.03762?")


def test_research_synthesises_with_an_llm_when_one_is_up(monkeypatch, fast_arxiv):
    monkeypatch.setattr(research, "_get", lambda url, **kw: FEED)
    monkeypatch.setattr(llm_exec, "complete", lambda prompt, **kw: ExecResult(
        tier="deep_research", backend="ollama:m", answer="Vaswani et al. [1]", text="Vaswani et al. [1]",
        tokens={"prompt": 50, "completion": 6, "total": 56}))
    res = research.run("Who is the first author of arXiv paper 1706.03762?")
    assert res.backend == "arxiv+ollama:m" and res.meta["synthesis"] == "llm" and res.tokens["total"] == 56


# --- the tier probe ------------------------------------------------------------------------

GOAL = {"id": "g1", "goal": "q", "task_type": "fact_exact", "verifier": {"type": "exact", "expected": "42"}}


def _runner(answer=None, exc=None, calls=None, tier="x"):
    def run(goal):
        if calls is not None:
            calls.append(tier)
        if exc is not None:
            raise exc
        return ExecResult(tier=tier, backend=f"fake-{tier}", answer=answer)
    return run


def test_probe_labels_the_cheapest_tier_that_passes_its_verifier():
    calls = []
    runners = {"deterministic": _runner(exc=NotApplicable("no solver"), calls=calls, tier="deterministic"),
               "llm": _runner(answer="41", calls=calls, tier="llm"),
               "deep_research": _runner(answer="42", calls=calls, tier="deep_research")}
    p = probe.probe_goal(GOAL, runners=runners)
    assert p["status"] == "labeled" and p["minimal_tier"] == "deep_research"
    assert [a["status"] for a in p["attempts"]] == ["not_applicable", "failed", "passed"]
    assert calls == ["deterministic", "llm", "deep_research"]
    assert "answer" not in p["attempts"][2] and len(p["attempts"][2]["answer_sha256"]) == 64  # no text opt-in


def test_probe_stops_at_an_unavailable_tier_unless_told_otherwise():
    calls = []
    runners = {"deterministic": _runner(exc=NotApplicable("no"), calls=calls, tier="deterministic"),
               "llm": _runner(exc=ExecutorUnavailable("no ollama"), calls=calls, tier="llm"),
               "deep_research": _runner(answer="42", calls=calls, tier="deep_research")}
    p = probe.probe_goal(GOAL, runners=runners)
    assert p["status"] == "unavailable" and p["minimal_tier"] is None and calls == ["deterministic", "llm"]
    out = probe.outcome_for(p, GOAL, "sha", "run")
    assert out["executor"] == "unavailable" and out["verified"] is False and out["provenance"] == "benchmark-verified"
    up = probe.probe_goal(GOAL, runners=runners, past_unavailable=True)
    assert up["status"] == "labeled_upper_bound" and up["minimal_tier"] == "deep_research" and up["unknown_tiers"] == ["llm"]


def test_probe_is_bounded_and_never_runs_side_effect_tiers():
    runners = {t: _runner(answer="nope", tier=t) for t in ("deterministic", "llm", "deep_research")}
    p = probe.probe_goal(GOAL, runners=runners, max_tier="llm")
    assert p["status"] == "insufficient" and [a["tier"] for a in p["attempts"]] == ["deterministic", "llm"]
    for tier in ("action_operator", "agentic_epic"):
        with pytest.raises(ValueError, match="side effects"):
            probe.probe_goal(GOAL, runners=runners, max_tier=tier)


def test_run_probe_writes_benchmark_verified_traces_that_pack(tmp_path, monkeypatch):
    from dottie_loop import router_training
    from dottie_loop.traces import read_traces

    monkeypatch.setenv("DOTTIE_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("DOTTIE_TRACE_SOURCE", "production")
    bench = tmp_path / "bench.jsonl"
    goals = [{"id": f"b{i}", "goal": f"What is {i} * 3 + 1?", "task_type": "arithmetic",
              "verifier": {"type": "numeric", "expected": i * 3 + 1}} for i in range(1, 11)]
    goals.append({"id": "b-llm", "goal": "Explain the tides.", "task_type": "fact_exact",
                  "verifier": {"type": "exact", "expected": "moon"}})
    bench.write_text("\n".join(json.dumps(g) for g in goals) + "\n", encoding="utf-8")
    runners = {"deterministic": deterministic.run, "llm": _runner(exc=ExecutorUnavailable("no ollama")),
               "deep_research": _runner(answer="x")}
    s = probe.run_probe(bench, runners=runners)
    assert s["status"] == {"labeled": 10, "unavailable": 1} and s["minimal_tier"] == {"deterministic": 10}
    rows, bad = read_traces(sorted((tmp_path / "traces").glob("route-*.jsonl")))
    assert bad == 0 and {r["provenance"] for r in rows} == {"benchmark-verified"}
    assert all("goal_text" not in r for r in rows)
    # under pytest every line is source=test, so the pack must refuse them; retag to exercise the labels
    for r in rows:
        r["source"] = "production"
    src = tmp_path / "retagged" / "route-x.jsonl"
    src.parent.mkdir()
    src.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    m = router_training.pack([src], tmp_path / "pack", seed=1, bench_files=[bench])
    assert m["provenance"] == {"benchmark-verified": 10} and m["labels"]["tier"] == {"deterministic": 10}
    assert m["rejected"] == {"refused: executor 'unavailable' is not real work": 1}


# --- the runner: real where the backend is up, stub (tagged) where not ---------------------


def _fake_role(ctx):
    return ExecResult(tier="llm", backend="fake", answer=f"real work for {ctx['node']['id']}",
                      tokens={"prompt": 3, "completion": 4, "total": 7},
                      sources=[{"id": "s1"}] if ctx["node"]["role"] == "deep-researcher" else [])


def _run(tmp_path, monkeypatch, mode, roles):
    monkeypatch.setenv("DOTTIE_EXECUTORS", mode)
    monkeypatch.setattr(executors, "ROLE_RUNNERS", {**executors.ROLE_RUNNERS, **roles})
    return runner.run_goal("compare Stripe vs Lemon Squeezy", runs_dir=tmp_path / "runs")


def test_runner_all_real_nodes_make_a_real_outcome(tmp_path, monkeypatch):
    fake = dict.fromkeys(("deep-researcher", "strategist", "synthesist"), _fake_role)
    d = _run(tmp_path, monkeypatch, "auto", fake)
    kinds = {n["role"]: n["executor"] for n in d["nodes"]}
    assert kinds == {"deep-researcher": "real", "strategist": "real", "synthesist": "real", "builder": "real"}
    assert d["provenance"]["executors"] == {"real": 4}
    assert sum(n["tokens"] for n in d["nodes"]) == 21


def test_runner_unavailable_backend_falls_back_to_a_tagged_stub(tmp_path, monkeypatch):
    def down(ctx):
        raise ExecutorUnavailable("no ollama")

    fake = {"deep-researcher": _fake_role, "strategist": down, "synthesist": _fake_role}
    d = _run(tmp_path, monkeypatch, "auto", fake)
    by = {n["role"]: n for n in d["nodes"]}
    assert by["strategist"]["executor"] == "stub" and "no ollama" in by["strategist"]["fallback"]
    assert by["builder"]["executor"] == "stub"  # composition over a stub artifact is not real work
    assert d["passed"] is True and d["provenance"]["executors"] == {"real": 2, "stub": 2}


def test_runner_real_mode_fails_the_node_instead(tmp_path, monkeypatch):
    def down(ctx):
        raise ExecutorUnavailable("no ollama")

    d = _run(tmp_path, monkeypatch, "real", {"deep-researcher": _fake_role, "strategist": down, "synthesist": _fake_role})
    by = {n["role"]: n for n in d["nodes"]}
    assert by["strategist"]["status"] == "failed" and by["strategist"]["executor"] == "real"


def test_runner_stub_mode_never_calls_a_real_executor(tmp_path, monkeypatch):
    def boom(ctx):
        raise AssertionError("real executor called under DOTTIE_EXECUTORS=stub")

    d = _run(tmp_path, monkeypatch, "stub", dict.fromkeys(("deep-researcher", "strategist", "synthesist"), boom))
    assert {n["executor"] for n in d["nodes"]} == {"stub"}
