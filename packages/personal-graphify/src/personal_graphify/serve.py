"""
serve.py — MCP server (SOTA: HTTP + stdio) exposing personal-graphify as tools
Tools: query, path, explain, impact, task, onboard, cost
SOTA: semantic rerank (Ollama mxbai-embed-large), hooks, cost dashboard
Solo personal project, no connection to employer, built with public/free-tier only
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict
import argparse

from .security import ensure_containment
from .query import (
    load_graph_json,
    search_nodes,
    format_query_answer,
    format_path_answer,
    explain_node,
    impact_analysis,
    task_compiler,
    onboard_report,
    format_onboard_answer,
    format_cost_dashboard,
    _cost_path_for_graph
)

def load_graph(graph_path: str, allowed_root: Path = None):
    p = Path(graph_path)
    if allowed_root is not None:
        # Caller-supplied graph paths (e.g. /mcp/call arguments) must stay inside the
        # server's root — reject ../../etc traversal before touching the filesystem.
        p = ensure_containment(p, allowed_root)
    if not p.exists():
        cand = Path("graphify-out/graph.json")
        if cand.exists():
            p = cand
        else:
            found = list(Path(".").rglob("graph.json"))
            if found:
                p = found[0]
    if not p.exists():
        raise FileNotFoundError(f"graph.json not found at {graph_path}, tried {p}")
    return load_graph_json(p), p

MCP_TOOLS = [
    {
        "name": "graphify_query",
        "description": "Query knowledge graph for scoped subgraph — ~1.5k vs ~100k 70x+ reduction. SOTA: lexical + optional semantic rerank via Ollama mxbai-embed-large local. Always use before grepping. Ecosystem: Turnover Shield $79-149/mo, Family Brain, Ava AGI, MTNN Vector Hoops.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Natural question: where is X, how does A connect to B, retention logic etc"},
                "limit": {"type": "integer", "default": 12},
                "semantic": {"type": "boolean", "default": False, "description": "Use Ollama mxbai-embed-large semantic rerank (free local, needs ollama pull mxbai-embed-large)"},
                "embed_model": {"type": "string", "default": "mxbai-embed-large"},
                "graph": {"type": "string", "default": "graphify-out/graph.json"}
            },
            "required": ["question"]
        }
    },
    {
        "name": "graphify_path",
        "description": "Shortest path between two concepts/files — hop-by-hop EXTRACTED vs INFERRED. Use for 'how does Stripe webhook connect to MRR?'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "target": {"type": "string"},
                "semantic": {"type": "boolean", "default": False},
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
                "include_snippet": {"type": "boolean", "default": False},
                "semantic": {"type": "boolean", "default": False}
            },
            "required": ["node"]
        }
    },
    {
        "name": "graphify_impact",
        "description": "Impact analysis: what breaks if you change this node? Downstream + upstream + file hotspots. SOTA for safe edits.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {"type": "string"},
                "direction": {"type": "string", "enum": ["downstream","upstream","both"], "default": "both"},
                "depth": {"type": "integer", "default": 3},
                "semantic": {"type": "boolean", "default": False},
                "graph": {"type": "string", "default": "graphify-out/graph.json"}
            },
            "required": ["node"]
        }
    },
    {
        "name": "graphify_task",
        "description": "Task compiler: given natural task, returns minimal files (priority) + action plan + token savings + copy-paste context. Most useful for agents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "e.g. 'add retention playbook to Turnover Shield'"},
                "semantic": {"type": "boolean", "default": False},
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
    },
    {
        "name": "graphify_cost",
        "description": "Cost dashboard: shows token savings from cost.json — total saved, $ avoided, recent queries. SOTA tracking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph": {"type": "string", "default": "graphify-out/graph.json"}
            }
        }
    }
]

def handle_tool_call(name: str, arguments: Dict[str, Any], allowed_root: Path = None) -> Dict[str, Any]:
    graph_path = arguments.get("graph", "graphify-out/graph.json")
    if allowed_root is None:
        allowed_root = Path.cwd()
    try:
        G, resolved = load_graph(graph_path, allowed_root=allowed_root)
    except Exception as e:
        return {"error": str(e), "graph": graph_path}

    semantic = arguments.get("semantic", False)
    embed_model = arguments.get("embed_model", "mxbai-embed-large")

    if name == "graphify_query":
        q = arguments.get("question","")
        sub_answer = format_query_answer(G, q, graph_path=resolved, semantic=semantic, embed_model=embed_model)
        matches = search_nodes(G, q, limit=arguments.get("limit",12), semantic=semantic, embed_model=embed_model)
        return {"text": sub_answer, "matches": matches[:12], "graph": str(resolved), "semantic": semantic}

    elif name == "graphify_path":
        src = arguments.get("source",""); tgt = arguments.get("target","")
        ans = format_path_answer(G, src, tgt, semantic=semantic)
        return {"text": ans, "graph": str(resolved)}

    elif name == "graphify_explain":
        node = arguments.get("node","")
        info = explain_node(G, node, include_code_snippet=arguments.get("include_snippet", False), semantic=semantic, graph_path=resolved)
        if not info:
            return {"error": f"Node '{node}' not found"}
        return info

    elif name == "graphify_impact":
        node = arguments.get("node","")
        direction = arguments.get("direction","both")
        depth = arguments.get("depth",3)
        impact = impact_analysis(G, node, direction=direction, depth=depth, semantic=semantic)
        return impact

    elif name == "graphify_task":
        task = arguments.get("task","")
        result = task_compiler(G, task, semantic=semantic)
        return result

    elif name == "graphify_onboard":
        report = onboard_report(G)
        return report

    elif name == "graphify_cost":
        cost_path = _cost_path_for_graph(resolved)
        try:
            text = format_cost_dashboard(cost_path)
            raw = {}
            if cost_path.exists():
                raw = json.loads(cost_path.read_text()) 
            return {"text": text, "cost_path": str(cost_path), "raw": raw}
        except Exception as e:
            return {"error": str(e), "cost_path": str(cost_path)}

    else:
        return {"error": f"Unknown tool {name}"}

def handle_stdio_line(line: str):
    """Handle one JSON-RPC line. Returns a response dict, or None when no response
    must be sent (blank/garbage input, or a notification — a request without an id)."""
    line = line.strip()
    if not line:
        return None
    try:
        req = json.loads(line)
    except Exception:
        return None
    is_notification = "id" not in req  # JSON-RPC: notifications carry no id and get NO reply
    rpc_id = req.get("id")
    method = req.get("method")
    params = req.get("params",{})

    if is_notification:
        # e.g. notifications/initialized — process nothing, reply nothing
        return None

    if method == "initialize":
        return {
            "jsonrpc":"2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion":"2024-11-05",
                "capabilities":{"tools":{"listChanged": False}},
                "serverInfo":{"name":"personal-graphify","version":"0.3.0-sota-semantic"}
            }
        }

    elif method == "tools/list":
        return {
            "jsonrpc":"2.0",
            "id": rpc_id,
            "result": {"tools": MCP_TOOLS}
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments",{})
        result = handle_tool_call(tool_name, arguments)
        return {
            "jsonrpc":"2.0",
            "id": rpc_id,
            "result": {
                "content": [{"type":"text","text": json.dumps(result, indent=2)[:18000]}],
                "isError": "error" in result
            }
        }

    elif method == "ping":
        return {"jsonrpc":"2.0","id":rpc_id,"result":{}}

    return {"jsonrpc":"2.0","id":rpc_id,"error":{"code":-32601,"message":f"Method {method} not found"}}

def run_stdio():
    for line in sys.stdin:
        resp = handle_stdio_line(line)
        if resp is not None:
            print(json.dumps(resp), flush=True)

def run_http(port: int, graph_path: str, host: str = "127.0.0.1"):
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
        import uvicorn
    except ImportError:
        print("[personal-graphify] fastapi/uvicorn not installed, falling back to stdio")
        run_stdio()
        return

    app = FastAPI(title="Personal Graphify MCP SOTA", version="0.3.0")
    allowed_root = Path.cwd().resolve()

    @app.get("/")
    def root():
        return {"name":"personal-graphify","version":"0.3.0-sota-semantic","tools":[t["name"] for t in MCP_TOOLS], "graph": graph_path, "features": ["lexical+degree","semantic-mxbai-embed-large","impact","task-compiler","hooks","cost-dashboard"], "note":"Solo personal project, no connection to employer"}

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
        result = handle_tool_call(name, args, allowed_root=allowed_root)
        return JSONResponse(result)

    @app.post("/query")
    async def http_query(request: Request):
        body = await request.json()
        q = body.get("question") or body.get("q") or ""
        semantic = body.get("semantic", False)
        G,_ = load_graph(body.get("graph", graph_path), allowed_root=allowed_root)
        matches = search_nodes(G, q, limit=body.get("limit",12), semantic=semantic)
        return {"question": q, "matches": matches, "subgraph": {"text": format_query_answer(G,q, graph_path=Path(graph_path), semantic=semantic)}}

    @app.post("/task")
    async def http_task(request: Request):
        body = await request.json()
        task = body.get("task","")
        semantic = body.get("semantic", False)
        G,_ = load_graph(body.get("graph", graph_path), allowed_root=allowed_root)
        result = task_compiler(G, task, semantic=semantic)
        return result

    @app.post("/impact")
    async def http_impact(request: Request):
        body = await request.json()
        semantic = body.get("semantic", False)
        G,_ = load_graph(body.get("graph", graph_path), allowed_root=allowed_root)
        result = impact_analysis(G, body.get("node",""), direction=body.get("direction","both"), depth=body.get("depth",3), semantic=semantic)
        return result

    @app.get("/cost")
    def http_cost():
        G,_ = load_graph(graph_path)
        cost_path = _cost_path_for_graph(Path(graph_path))
        return {"text": format_cost_dashboard(cost_path)}

    print(f"[personal-graphify] HTTP MCP serving on http://{host}:{port} — graph {graph_path} SOTA semantic+hooks+cost")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"[personal-graphify] WARNING: binding to {host} exposes the server beyond localhost")
    print(f"Endpoints: GET /mcp/tools, POST /mcp/call, POST /query, POST /task, POST /impact, GET /cost")
    uvicorn.run(app, host=host, port=port)

def main(args=None):
    if args is None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--transport", default="http", choices=["http","stdio"])
        parser.add_argument("--port", type=int, default=8080)
        parser.add_argument("--host", default="127.0.0.1", help="Bind address (default localhost-only; override deliberately to expose)")
        parser.add_argument("--graph", default="graphify-out/graph.json")
        args = parser.parse_args()

    transport = getattr(args, "transport", "http")
    port = getattr(args, "port", 8080)
    host = getattr(args, "host", "127.0.0.1")
    graph = getattr(args, "graph", "graphify-out/graph.json")

    if transport == "stdio":
        run_stdio()
    else:
        run_http(port, graph, host=host)

if __name__ == "__main__":
    main()
