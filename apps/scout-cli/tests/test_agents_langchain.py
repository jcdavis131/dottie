"""Tests for agents plugin — deep LangChain/LangGraph/CrewAI/OpenAI/AutoGen with ACNE 5-layer cache"""

import json
import sys
from pathlib import Path

def test_agents_list():
    from bigbang.plugins.agents.adapters import list_adapters
    ads=list_adapters()
    assert "langchain" in ads
    assert "langgraph" in ads
    assert "crewai" in ads
    assert "openai" in ads
    assert "autogen" in ads
    assert len(ads)==5

def test_langchain_adapter():
    from bigbang.plugins.agents.adapters import get_adapter
    lc=get_adapter("langchain")
    tools=lc.list_tools()
    assert len(tools)>=6
    assert any(t["name"]=="contacts_resolve" for t in tools)
    res=lc.run("test goal Stripe vs Lemon Squeezy", intent="deep_research")
    assert res["ok"] is True
    assert res["adapter"]=="langchain"
    assert 0.5 <= res["confidence"] <= 0.99
    assert "provenance" in res
    assert "acne_layers" in res or "token_savings" in res
    # second run should hit cache
    res2=lc.run("test goal Stripe vs Lemon Squeezy", intent="deep_research")
    assert res2.get("cache_hit") is True or res2.get("confidence")>=0.88

def test_langgraph_adapter():
    from bigbang.plugins.agents.adapters import get_adapter
    lg=get_adapter("langgraph")
    nodes=lg.list_nodes()
    assert len(nodes)==5
    assert nodes[0]["id"]=="observe"
    res=lg.run_graph("build Stripe vs Lemon pipeline")
    assert res["ok"] is True
    assert res["adapter"]=="langgraph"
    assert "graph" in res
    assert res["graph"]["dag_version"]==3
    assert res["confidence"]>=0.8

def test_crewai_adapter():
    from bigbang.plugins.agents.adapters import get_adapter
    ca=get_adapter("crewai")
    crews=ca.list_crews()
    assert len(crews)>=5
    res=ca.run("launch campaign", caps=5)
    assert res["ok"] is True
    assert res["crews_count"]==5
    assert res["confidence"]>=0.8
    # cap guard
    res6=ca.run("epic launch", caps=7)
    assert res6["guard"] is not None or res6["cap"]==7

def test_openai_adapter():
    from bigbang.plugins.agents.adapters import get_adapter
    oa=get_adapter("openai")
    tools=oa.list_tools()
    assert len(tools)>=3
    res=oa.run("test prompt for openai tool", model="gpt-4o-mini")
    assert res["ok"] is True
    assert res["network"] is False
    assert res["confidence"]>=0.8

def test_autogen_adapter():
    from bigbang.plugins.agents.adapters import get_adapter
    ag=get_adapter("autogen")
    agents=ag.list_agents()
    assert len(agents)==5
    res=ag.run_conversation("solve task", max_rounds=2)
    assert res["ok"] is True
    assert len(res["turns"])==2
    assert res["confidence"]>=0.8

def test_token_cache_5_layers():
    from bigbang.plugins.agents.adapters.base import TokenCache5
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp)
        cache=TokenCache5(base/"test", price_per_1k=0.015)
        # doc dedup
        cache.put_doc("abc123","doc1")
        assert cache.get_doc("abc123")=="doc1"
        # emb
        cache.put_emb("hello world", [0.1,0.2,0.3])
        assert cache.get_emb("hello world")==[0.1,0.2,0.3]
        # extraction
        cache.put_extraction("chunk1", {"entities":["Acme"]})
        assert cache.get_extraction("chunk1")["result"]["entities"]==["Acme"]
        # query
        cache.put_query("what is Acme?", {"answer":"Acme is ORG"})
        got=cache.get_query("what is Acme?")
        assert got is not None
        assert got["result"]["answer"]=="Acme is ORG"
        stats=cache.stats()
        assert stats["doc_hits"]>=1
        assert stats["tokens_saved"]>0
        assert "hit_rate" in stats

def test_agents_cli_import():
    from bigbang.plugins.agents.cli import app
    assert app.info.name=="agents"

def test_agents_cli_json_list():
    r=__import__("subprocess").run(
        [sys.executable,"-m","bigbang.cli","--json","agents","langchain","list"],
        capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=10
    )
    assert r.returncode==0, r.stderr[:500]
    data=json.loads(r.stdout)
    assert data["ok"] is True
    assert "tools" in data
    assert data["count"]>=6

def test_agents_deep_list_json():
    r=__import__("subprocess").run(
        [sys.executable,"-m","bigbang.cli","--json","agents","deep","list"],
        capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=10
    )
    assert r.returncode==0, r.stderr[:500]
    data=json.loads(r.stdout)
    assert data["ok"] is True
    assert "adapters" in data
    assert len(data["adapters"])==5
    assert "langchain" in data["adapters"]

def test_agents_langchain_run_json():
    r=__import__("subprocess").run(
        [sys.executable,"-m","bigbang.cli","--json","agents","langchain","run","test run Stripe vs Lemon","--intent","deep_research"],
        capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=10
    )
    assert r.returncode==0, r.stderr[:500]
    data=json.loads(r.stdout)
    assert data["ok"] is True
    assert data["adapter"]=="langchain"
    assert "confidence" in data
    assert "provenance" in data

def test_agents_cache_stats_json():
    r=__import__("subprocess").run(
        [sys.executable,"-m","bigbang.cli","--json","agents","cache","stats"],
        capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=10
    )
    assert r.returncode==0, r.stderr[:500]
    data=json.loads(r.stdout)
    assert data["ok"] is True
    assert "caches" in data
    assert data["layers"]==5

def test_triple_write_exists():
    # after running commands above, triple-write dirs should exist
    roots=[
        Path.home()/ "workspace"/ "bundles"/ "ultra"/ "runs",
        Path.home()/ "workspace"/ "dottie"/ "pipeline"/ "runs",
        Path.home()/ "workspace"/ "dottie"/ "bundles"/ "ultra"/ "runs",
    ]
    found=0
    for base in roots:
        if base.exists():
            matches=list(base.glob("agents-langchain-*"))+list(base.glob("agents-deep-*"))
            if matches:
                found+=1
                # check timeline has 7-field
                tl=(matches[0]/"timeline.jsonl")
                if tl.exists():
                    line=tl.read_text().splitlines()[0]
                    obj=json.loads(line)
                    assert "nodeId" in obj and "agentId" in obj and "attempt" in obj
                    assert "status" in obj and "errorClass" in obj
    assert found>=1
