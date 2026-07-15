"""
serve.py — MCP server (SOTA: HTTP + stdio) exposing personal-graphify as tools
Tools: query, path, explain, impact, task, onboard

Solo personal project, no connection to employer, built with public/free-tier only
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict
import argparse

# Try to use existing query module
from .query import (
    load_graph_json,
    search_nodes,
    format_query_answer,
    format_path_answer,
    explain_node,
    impact_analysis,
    task_compiler,
    onboard_report,
    format_onboard_answer
)

def load_graph(graph_path: str):
    p = Path(graph_path)
    # search up if not found
    if not p.exists():
        # try cwd graphify-out
        cand = Path("graphify-out/graph.json")
        if cand.exists():
            p = cand
        else:
            # rglob
            found = list(Path(".").rglob("graph.json"))
            if found:
                p = found[0]
    if not p.exists():
        raise FileNotFoundError(f"graph.json not found at {graph_path}, tried {p}")
    return load_graph_json(p), p

# MCP tool definitions
MCP_TOOLS = [
    {
        "name": "graphify_query",
        "description": "Query knowledge graph for scoped subgraph — returns ~1.5k tokens vs naive ~100k, 70x+ reduction. Always use before grepping. Personal ecosystem: Turnover Shield, Family Brain, Ava AGI, MTNN Vector Hoops.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Natural question: where is X, how does A connect to B, retention logic etc"},
                "limit": {"type": "integer", "default": 12},
                "graph": {"type": "string", "default": "graphify-out/graph.json"}
            },
            "required": ["question"]
        }
    },
    {
        "name": "graphify_path",
        "description": "Shortest path between two concepts/files — traces hop-by-hop with EXTRACTED vs INFERRED. Use for 'how does Stripe webhook connect to MRR?'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "target": {"type": "string"},
                "graph": {"type": "string", "default": "graphify-out/graph.json"}
            },
            "required": ["source","target"]
        }
    },
    {
        "name": "graphify_explain",
        "description": "Explain a node: incoming/outgoing edges, degree, community, file, plus code snippet if available. Use to understand god nodes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {"type": "string"},
                "graph": {"type": "string", "default": "graphify-out/graph.json"},
                "include_snippet": {"type": "boolean", "default": False}
            },
            "required": ["node"]
        }
    },
    {
        "name": "graphify_impact",
        "description": "Impact analysis: what breaks if you change this node? Returns downstream (what it affects) + upstream (dependencies) + file hotspots. SOTA for safe edits.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {"type": "string"},
                "direction": {"type": "string", "enum": ["downstream","upstream","both"], "default": "both"},
                "depth": {"type": "integer", "default": 3},
                "graph": {"type": "string", "default": "graphify-out/graph.json"}
            },
            "required": ["node"]
        }
    },
    {
        "name": "graphify_task",
        "description": "Task compiler: given natural task description, returns minimal relevant files (priority order) + action plan + token savings + copy-paste context. Most useful for agents to get stuff done with minimal context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "e.g. 'add retention playbook to Turnover Shield', 'fix churn calc', 'onboard new dev to Ava'"},
                "graph": {"type": "string", "default": "graphify-out/graph.json"}
            },
            "required": ["task"]
        }
    },
    {
        "name": "graphify_onboard",
        "description": "Senior-dev onboarding: god nodes, hot files, entry points, communities, suggested questions. Use for new repo in 30s.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph": {"type": "string", "default": "graphify-out/graph.json"}
            }
        }
    }
]

def handle_tool_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    graph_path = arguments.get("graph", "graphify-out/graph.json")
    try:
        G, resolved = load_graph(graph_path)
    except Exception as e:
        return {"error": str(e), "graph": graph_path}

    if name == "graphify_query":
        q = arguments.get("question","")
        sub_answer = format_query_answer(G, q)
        # also return structured top matches
        matches = search_nodes(G, q, limit=arguments.get("limit",12))
        return {"text": sub_answer, "matches": matches[:12], "graph": str(resolved)}

    elif name == "graphify_path":
        src = arguments.get("source",""); tgt = arguments.get("target","")
        ans = format_path_answer(G, src, tgt)
        return {"text": ans, "graph": str(resolved)}

    elif name == "graphify_explain":
        node = arguments.get("node","")
        info = explain_node(G, node, include_code_snippet=arguments.get("include_snippet", False))
        if not info:
            return {"error": f"Node '{node}' not found"}
        return info

    elif name == "graphify_impact":
        node = arguments.get("node","")
        direction = arguments.get("direction","both")
        depth = arguments.get("depth",3)
        impact = impact_analysis(G, node, direction=direction, depth=depth)
        return impact

    elif name == "graphify_task":
        task = arguments.get("task","")
        result = task_compiler(G, task)
        return result

    elif name == "graphify_onboard":
        report = onboard_report(G)
        return report

    else:
        return {"error": f"Unknown tool {name}"}

# -- STDIO MCP transport --
def run_stdio():
    """
    Minimal MCP stdio transport: reads JSON-RPC lines, responds.
    Supports initialize, tools/list, tools/call
    """
    import sys
    for line in sys.stdin:
        line=line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except:
            continue
        rpc_id = req.get("id")
        method = req.get("method")
        params = req.get("params",{})

        if method == "initialize":
            resp = {
                "jsonrpc":"2.0",
                "id": rpc_id,
                "result": {
                    "protocolVersion":"2024-11-05",
                    "capabilities":{"tools":{"listChanged": False}},
                    "serverInfo":{"name":"personal-graphify","version":"0.2.0-sota"}
                }
            }
            print(json.dumps(resp), flush=True)

        elif method == "tools/list":
            resp = {
                "jsonrpc":"2.0",
                "id": rpc_id,
                "result": {"tools": MCP_TOOLS}
            }
            print(json.dumps(resp), flush=True)

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments",{})
            result = handle_tool_call(tool_name, arguments)
            resp = {
                "jsonrpc":"2.0",
                "id": rpc_id,
                "result": {
                    "content": [{"type":"text","text": json.dumps(result, indent=2)[:15000]}],
                    "isError": "error" in result
                }
            }
            print(json.dumps(resp), flush=True)

        elif method == "ping":
            resp = {"jsonrpc":"2.0","id":rpc_id,"result":{}}
            print(json.dumps(resp), flush=True)

        else:
            # unknown
            resp = {"jsonrpc":"2.0","id":rpc_id,"error":{"code":-32601,"message":f"Method {method} not found"}}
            print(json.dumps(resp), flush=True)

# -- HTTP transport via FastAPI --
def run_http(port: int, graph_path: str):
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
        import uvicorn
    except ImportError:
        print("[personal-graphify] fastapi/uvicorn not installed, falling back to stdio")
        run_stdio()
        return

    app = FastAPI(title="Personal Graphify MCP", version="0.2.0-sota")

    @app.get("/")
    def root():
        return {"name":"personal-graphify","version":"0.2.0-sota","tools":[t["name"] for t in MCP_TOOLS], "graph": graph_path, "note":"Solo personal project, no connection to employer"}

    @app.get("/mcp/tools")
    def list_tools():
        return {"tools": MCP_TOOLS}

    @app.post("/mcp/call")
    async def call_tool(request: Request):
        body = await request.json()
        name = body.get("name") or body.get("tool") or body.get("method")
        args = body.get("arguments") or body.get("args") or {}
        if "graph" not in args:
            args["graph"] = graph_path
        result = handle_tool_call(name, args)
        return JSONResponse(result)

    @app.post("/query")
    async def http_query(request: Request):
        body = await request.json()
        q = body.get("question") or body.get("q") or ""
        G,_ = load_graph(body.get("graph", graph_path))
        matches = search_nodes(G, q, limit=body.get("limit",12))
        return {"question": q, "matches": matches, "subgraph": {"text": format_query_answer(G,q)}}

    @app.post("/task")
    async def http_task(request: Request):
        body = await request.json()
        task = body.get("task","")
        G,_ = load_graph(body.get("graph", graph_path))
        result = task_compiler(G, task)
        return result

    @app.post("/impact")
    async def http_impact(request: Request):
        body = await request.json()
        G,_ = load_graph(body.get("graph", graph_path))
        result = impact_analysis(G, body.get("node",""), direction=body.get("direction","both"), depth=body.get("depth",3))
        return result

    print(f"[personal-graphify] HTTP MCP serving on http://0.0.0.0:{port} — graph {graph_path}")
    print(f"Endpoints: GET /mcp/tools, POST /mcp/call, POST /query, POST /task, POST /impact")
    uvicorn.run(app, host="0.0.0.0", port=port)

def main(args=None):
    # args may be argparse namespace from cli.py
    if args is None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--transport", default="http", choices=["http","stdio"])
        parser.add_argument("--port", type=int, default=8080)
        parser.add_argument("--graph", default="graphify-out/graph.json")
        args = parser.parse_args()

    transport = getattr(args, "transport", "http")
    port = getattr(args, "port", 8080)
    graph = getattr(args, "graph", "graphify-out/graph.json")

    if transport == "stdio":
        run_stdio()
    else:
        run_http(port, graph)

if __name__ == "__main__":
    main()
