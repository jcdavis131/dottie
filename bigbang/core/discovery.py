"""Discovery — turn any internet thing into bb tool"""
import httpx

def fetch_openapi(url: str) -> dict:
    r = httpx.get(url, timeout=10, follow_redirects=True)
    r.raise_for_status()
    return r.json() if "json" in r.headers.get("content-type","") else {}

def discover_mcp_tools(server_url: str):
    # Placeholder for MCP client discovery — will POST list_tools
    # For now returns mock capability
    return [{"name": "example_tool", "description": "discovered via MCP"}]
