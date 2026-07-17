#!/usr/bin/env python3
"""
Generate LLM wikis for BigBang CLI
- Parses bigbang/plugins/*/manifest.yaml + cli.py for @app.command
- Emits docs/llm-wiki/plugins.md and quickstart.md and tasks export sample
Solo personal project, no connection to employer, built with public/free-tier only
"""
from pathlib import Path
import re, yaml, json

ROOT = Path(__file__).parent.parent
PLUGINS_DIR = ROOT / "bigbang" / "plugins"
WIKI_DIR = ROOT / "docs" / "llm-wiki"
WIKI_DIR.mkdir(parents=True, exist_ok=True)

def parse_commands(cli_path: Path):
    text = cli_path.read_text(errors="ignore")
    # find @app.command("name") + def name(
    cmds = []
    pattern = re.compile(r'@app\.command\(["\']([^"\']+)["\']\)\s*\n def (\w+)', re.MULTILINE)
    # also handle without name param?
    for m in re.finditer(r'@app\.command\(.*?\)\s*\ndef (\w+)\s*\(.*?\)\s*:', text, re.DOTALL):
        # fallback: function name is command if no explicit string
        func = m.group(1)
        # look backwards for explicit name
        snippet = text[max(0,m.start()-200):m.start()]
        name_match = re.search(r'@app\.command\(["\']([^"\']+)["\']\)', snippet)
        name = name_match.group(1) if name_match else func.replace("_","-")
        cmds.append(name)
    # dedup
    seen=set()
    uniq=[]
    for c in cmds:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq

def load_manifest(mf_path: Path):
    if not mf_path.exists():
        return {}
    try:
        return yaml.safe_load(mf_path.read_text()) or {}
    except Exception as e:
        return {"error": str(e)}

plugins = []
for p in sorted(PLUGINS_DIR.iterdir()):
    if not p.is_dir() or p.name.startswith("__"):
        continue
    cli = p / "cli.py"
    mf = p / "manifest.yaml"
    if not cli.exists():
        continue
    cmds = parse_commands(cli)
    manifest = load_manifest(mf)
    plugins.append({
        "name": p.name,
        "manifest": manifest,
        "commands": cmds,
        "cli_path": str(cli.relative_to(ROOT)),
    })

# Emit plugins.md
out_plugins = WIKI_DIR / "plugins.md"
md_lines = []
md_lines.append("# Plugins Catalog — LLM Wiki")
md_lines.append("")
md_lines.append("**Solo personal project, no connection to employer, built with public/free-tier only**")
md_lines.append("")
md_lines.append(f"Total plugins: {len(plugins)}")
md_lines.append("")
md_lines.append("| Plugin | Version | Commands | Capabilities | Description |")
md_lines.append("|--------|---------|----------|--------------|-------------|")
for pl in plugins:
    mf = pl["manifest"]
    ver = mf.get("version","?")
    desc = (mf.get("description") or "")[:60].replace("|"," ").replace("\n"," ")
    caps = mf.get("capabilities",{})
    net = caps.get("network",{})
    domains = ",".join(net.get("domains",[])[:2]) if isinstance(net,dict) else ""
    if len(domains)>40: domains=domains[:37]+"..."
    cmds = ", ".join(pl["commands"][:5])
    if len(pl["commands"])>5:
        cmds += f" +{len(pl['commands'])-5}"
    md_lines.append(f"| {pl['name']} | {ver} | {cmds} | net:{net.get('enabled',False)} {domains} | {desc} |")
md_lines.append("")
md_lines.append("## Per-Plugin Details")
md_lines.append("")
for pl in plugins:
    mf = pl["manifest"]
    md_lines.append(f"### {pl['name']} ({mf.get('version','?')})")
    md_lines.append(f"- **Path**: `{pl['cli_path']}`")
    md_lines.append(f"- **Description**: {mf.get('description','')[:200]}")
    md_lines.append(f"- **Commands**: `{'`, `'.join(pl['commands'])}`")
    md_lines.append(f"- **Capabilities**: ```json\n{json.dumps(mf.get('capabilities',{}), indent=2)[:800]}\n```")
    md_lines.append(f"- **Tags**: {mf.get('tags',[])}")
    md_lines.append("")
out_plugins.write_text("\n".join(md_lines))
print(f"Wrote {out_plugins} with {len(plugins)} plugins")

# Emit quickstart.md
out_quick = WIKI_DIR / "quickstart.md"
qs = []
qs.append("# BigBang CLI Quickstart — LLM Wiki")
qs.append("")
qs.append("**Solo personal project, no connection to employer, built with public/free-tier only**")
qs.append("")
qs.append("## Install & Doctor")
qs.append("```bash")
qs.append("git clone ~/workspace/bigbang-cli")
qs.append("cd bigbang-cli")
qs.append("pip3 install -e .")
qs.append(f"bb --help  # {len(plugins)} plugins discovered automatically")
qs.append("bb system doctor")
qs.append("bb system policy")
qs.append("```")
qs.append("")
qs.append("## Google Tasks Wiring (new v0.4.1)")
qs.append("```bash")
qs.append("bb tasks status --json  # connected? 2 lists: Lina's Morning/Afternoon")
qs.append("bb tasks lists --json | jq .tasklists[].title")
qs.append("bb tasks list --tasklist @default --json")
qs.append("bb tasks add \"Ship Turnover Shield $79/mo\" --notes \"bb tools generate + Stripe webhook\" --json")
qs.append("bb tasks complete <task_id> --tasklist @default")
qs.append("bb tasks sync-bb --tasklist @default  # audit.jsonl -> Google Tasks")
qs.append("bb tasks export --tasklist @default  # -> docs/llm-wiki/tasks-@default.json")
qs.append("```")
qs.append("")
qs.append("## Universal Tool Registry")
qs.append("```bash")
qs.append("bb tools list")
qs.append("bb tools add petstore --type openapi --url https://petstore.swagger.io/v2/swagger.json")
qs.append("bb tools generate petstore  # -> bb petstore --help with 20 ops")
qs.append("bb petstore findPetsByStatus --status available --json | jq .data[0].name")
qs.append("bb tools call petstore findPetsByStatus '{\"status\":\"available\"}' --json")
qs.append("```")
qs.append("")
qs.append("## MCP")
qs.append("```bash")
qs.append(f"bb mcp manifest --json  # {len(plugins)} bb_* tools")
qs.append("bb mcp add myserver https://mcp.example.com/sse")
qs.append("bb mcp list-tools myserver --json")
qs.append("bb mcp call myserver some_tool --args '{\"q\":\"test\"}' --json")
qs.append("# Serve bb as a real MCP server (stdio default; --sse --port 8787 for SSE):")
qs.append("# bb mcp serve")
qs.append("# Claude Desktop config (stdio): {\"mcpServers\": {\"scout\": {\"command\": \"scout\", \"args\": [\"mcp\", \"serve\"]}}}")
qs.append("```")
qs.append("")
qs.append("## Ava & Agent")
qs.append("```bash")
qs.append("bb ava status --json  # Ollama detection localhost:11434 + host.docker.internal:11434")
qs.append("bb ava route \"list my Lina morning tasks\" --json  # -> tasks 0.92")
qs.append("bb ava route \"summarize petstore pets\" --json")
qs.append("bb agent run \"list my todos and export them\" --json  # plan: [bb tasks list, bb tasks export]")
qs.append("bb agent run \"ship Turnover Shield fix\" --json")
qs.append("```")
qs.append("")
qs.append("## Graphify (Knowledge Graph for LLMs)")
qs.append("```bash")
qs.append("pip install -e ~/workspace/your_files/personal-graphify  # provides pgraphify")
qs.append("cd ~/workspace/bigbang-cli")
qs.append("pgraphify build . --out graphify-out")
qs.append("ls graphify-out/  # graph.json, graph.html, GRAPH_REPORT.md, cost.json")
qs.append("pgraphify query \"how does bb tasks sync-bb work?\"")
qs.append("pgraphify query \"what connects ava router to tasks?\"")
qs.append("pgraphify path \"tasks/cli.py\" \"audit.py\"")
qs.append("pgraphify explain \"_run_gws\"")
qs.append("# Token savings: ~71.5x (graph.json ~2k tokens vs 123k naive)")
qs.append("```")
qs.append("")
qs.append("## LLM Wiki Docs Built")
qs.append("Located in docs/llm-wiki/:")
qs.append("- index.md (entry)")
qs.append("- architecture.md (v0.4.1 flow)")
qs.append("- tasks-plugin.md (wiring details)")
qs.append("- security-model.md (caps, vault, proxy fix)")
qs.append("- graphify-integration.md (build/query/save to personal graphify)")
qs.append(f"- plugins.md (auto-generated catalog of {len(plugins)} plugins)")
qs.append("- quickstart.md (this file)")
qs.append("- tasks-*.json (exported Google Tasks for ingestion)")
qs.append("")
qs.append("# Solo personal project, no connection to employer, built with public/free-tier only")
out_quick.write_text("\n".join(qs))
print(f"Wrote {out_quick}")

# Also ensure tasks export placeholder if no real tasks
export_sample = WIKI_DIR / "tasks-@default.json"
if not export_sample.exists():
    export_sample.write_text(json.dumps({"items": [], "hint": "Run bb tasks export --tasklist @default to populate"}, indent=2))
    print(f"Wrote placeholder {export_sample}")
