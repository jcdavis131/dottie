#!/usr/bin/env python3
"""
Graphify Research Builder — Daily 07:00 UTC / Interval 4h
Solo personal project, no connection to employer, built with public/free-tier only

Purpose: Build personal-graphify knowledge base over latest research corpus + existing Ava/BigBang docs
Inspired by Karpathy autoresearch: build on top of harvest, token-efficient graph for LLMs (35.2x reduction)

Steps:
1. Source: ~/workspace/ava-research-engine/graphify_source/*.md (from arxiv_harvester) + ~/workspace/dottie/apps/ava-factory/docs + ~/workspace/dottie/apps/scout-cli/docs/llm-wiki
2. Run: pgraphify build graphify_source --out graphify-out-research (or via python -m personal_graphify)
   Actually uses CLI pgraphify if available, else fallback to building via python lib
3. Outputs: graphify-out-research/{graph.json, graph.html, GRAPH_REPORT.md, cost.json}
4. Copy to: ~/workspace/your_files/personal-graphify/references/spaces/research-graph.json + REPORT
5. Also copy to ~/workspace/dottie/apps/ava-factory/graphify_out for BigBang visibility
6. Update LLM wiki: bigbang-cli/docs/llm-wiki/research-latest.md with latest queries + graph stats + top papers
7. Log to results/graphify_{date}.json

Security: no secrets, FS write only to allowed paths, sanitizes NO_PROXY
"""
import os, sys, re, json, shutil, subprocess
from pathlib import Path
from datetime import datetime, timezone

def sanitize_no_proxy():
    import os, re
    for var in ["NO_PROXY","no_proxy","HTTP_PROXY","http_proxy","HTTPS_PROXY","https_proxy"]:
        val = os.environ.get(var,"")
        if not val: continue
        parts = re.split(r"[, \s]+", val)
        cleaned = [p for p in parts if p and p not in ["::","::/0"] and not p.startswith("[") and "::" not in p and "fd8b" not in p]
        os.environ[var] = ",".join(cleaned)

sanitize_no_proxy()

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "topics.yaml"
import yaml
cfg = yaml.safe_load(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
harvest_cfg = cfg.get("harvest",{})
graphify_cfg = cfg.get("graphify",{})

def expand(p):
    return Path(os.path.expanduser(str(p)))

src_dir = expand(harvest_cfg.get("graphify_source_dir", "~/workspace/dottie/apps/ava-factory/graphify_source"))
# Also include additional source dirs for context
ava_docs = expand("~/workspace/dottie/apps/ava-factory/docs")
bigbang_wiki = expand("~/workspace/dottie/apps/scout-cli/docs/llm-wiki")

out_dir = expand(graphify_cfg.get("out_dir", "~/workspace/dottie/apps/ava-factory/graphify_out"))
out_dir.mkdir(parents=True, exist_ok=True)

# Secondary out for Ava engine itself
local_out = ROOT / "graphify_out"
local_out.mkdir(parents=True, exist_ok=True)

personal_ref = expand(graphify_cfg.get("personal_ref", "~/workspace/your_files/personal-graphify/references/spaces/research-graph.json"))
personal_ref.parent.mkdir(parents=True, exist_ok=True)

today = datetime.now(timezone.utc).date().isoformat()

print(f"[graphify-builder] src={src_dir} exists={src_dir.exists()} count={len(list(src_dir.glob('*.md'))) if src_dir.exists() else 0}")
print(f"  out={out_dir}")
print(f"  personal_ref={personal_ref}")

if not src_dir.exists() or len(list(src_dir.glob("*.md"))) == 0:
    print("[warn] no graphify source md yet — run arxiv_harvester first, creating placeholder")
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "_placeholder.md").write_text("# Research corpus placeholder\nNo papers yet, run harvester.\n")

# Try pgraphify CLI
def run_pgraphify(source, out):
    # Find pgraphify binary
    try:
        # try python -m personal_graphify fallback is pgraphify command
        result = subprocess.run(["pgraphify", "build", str(source), "--out", str(out)], capture_output=True, text=True, timeout=120)
        print(result.stdout[-2000:])
        if result.stderr:
            print("stderr:", result.stderr[-2000:])
        return result.returncode == 0
    except Exception as e:
        print(f"[error] pgraphify build failed: {e}")
        return False

# Build over research source only
success = run_pgraphify(src_dir, out_dir)
# Also build local copy
run_pgraphify(src_dir, local_out)

# If build succeeded, stats
graph_json = out_dir / "graph.json"
report_md = out_dir / "GRAPH_REPORT.md"
cost_json = out_dir / "cost.json"

if graph_json.exists():
    size_kb = graph_json.stat().st_size / 1024
    print(f"[ok] graph.json {size_kb:.1f} KB")
    # copy to personal ref
    shutil.copy2(graph_json, personal_ref)
    print(f"  copied to {personal_ref}")
    # also copy report
    if report_md.exists():
        shutil.copy2(report_md, personal_ref.parent / "research-GRAPH_REPORT.md")
    # also copy cost
    if cost_json.exists():
        shutil.copy2(cost_json, personal_ref.parent / "research-cost.json")
    # copy local
    # shutil.copy2(graph_json, ROOT / "graphify_source-graph.json")

    # Try some queries to validate
    for q in ["Muon optimizer training", "GraphRAG knowledge graph", "MCP tool routing", "Jacobian regularization"]:
        try:
            result = subprocess.run(["pgraphify", "query", q, "--graph", str(graph_json)], capture_output=True, text=True, timeout=30)
            print(f"\n[query] {q} -> {result.stdout[:500]}")
        except Exception as e:
            print(f"query {q} failed {e}")
else:
    print("[error] graph.json not found after build")

# Build combined graph over research + bigbang wiki + ava docs for richer context (optional, if enough files)
combined_src = ROOT / "graphify_source_combined"
combined_src.mkdir(exist_ok=True)
# copy few key docs into combined for context (limit 30 files to keep build fast)
# symlink or copy markdowns
for md_file in list(src_dir.glob("*.md"))[:50]:
    dest = combined_src / md_file.name
    if not dest.exists():
        try:
            dest.write_text(md_file.read_text(errors="ignore")[:10000])
        except:
            pass
# add top 5 wiki files
if bigbang_wiki.exists():
    for md_file in list(bigbang_wiki.glob("*.md"))[:5]:
        dest = combined_src / f"bbwiki_{md_file.name}"
        try:
            dest.write_text(md_file.read_text(errors="ignore")[:5000])
        except:
            pass

# Build combined
combined_out = expand("~/workspace/dottie/apps/ava-factory/graphify_out-combined")
combined_out.mkdir(parents=True, exist_ok=True)
run_pgraphify(combined_src, combined_out)

# Update LLM wiki research-latest.md
wiki_path = expand("~/workspace/dottie/apps/scout-cli/docs/llm-wiki/research-latest.md")
wiki_path.parent.mkdir(parents=True, exist_ok=True)
# Gather latest harvest report
harvest_reports = sorted((ROOT / "docs").glob("harvest_report_*.md"))
latest_harvest = harvest_reports[-1].read_text() if harvest_reports else "No harvest yet"

# Read graph report
graph_report_text = report_md.read_text()[:5000] if report_md.exists() else "No report"

# Count papers
rolling = expand("~/workspace/your_files/research/arxiv/rolling_index.json")
paper_count = 0
latest_papers = []
if rolling.exists():
    try:
        data = json.loads(rolling.read_text())
        paper_count = len(data.get("papers",{}))
        # last 5
        for pid, paper in list(data.get("papers",{}).items())[-5:]:
            latest_papers.append(paper)
    except Exception as e:
        print(f"rolling parse error {e}")

wiki_md = f"""# Research Latest — Graphify Knowledge Base (Auto-Updated {today})

**Solo personal project, no connection to employer, built with public/free-tier only**

This file is auto-generated by `ava-research-engine/scripts/graphify_research.py` (cron: daily 07:00 UTC, interval 4h).

## Overview
- Source corpus: `{src_dir}` — {len(list(src_dir.glob('*.md')))} markdown papers
- Rolling index: `{rolling}` — {paper_count} total deduped papers (14d lookback)
- Graphify out: `{out_dir}`
- Personal ref: `{personal_ref}`
- Token reduction: 35.2× (1500 vs 52750 naive) per earlier build, upstream 71.5×
- Graph files: graph.json ~{graph_json.stat().st_size/1024:.0f}KB if exists, graph.html, GRAPH_REPORT.md

## Latest Harvest Summary
{latest_harvest}

## Graphify Report (truncated)
{graph_report_text}

## Latest 5 Papers (from rolling_index)
"""
for p in latest_papers:
    wiki_md += f"- **{p.get('title','')}** [{p.get('arxiv_id','')}] {p.get('arxiv_url','')} — topics {','.join(p.get('topics',[]))}\n  Abstract: {p.get('abstract','')[:200]}...\n"

wiki_md += f"""
## How to Query
```bash
cd ~/workspace/bigbang-cli
pgraphify query "Muon optimizer for S1 Fast" --graph graphify-out-research/graph.json
pgraphify query "GraphRAG for code knowledge graph" --graph graphify-out-research/graph.json
pgraphify path "model_1b.py" "YaRN" --graph graphify-out-research/graph.json
pgraphify explain "_run_gws" --graph graphify-out-research/graph.json

# Combined context
pgraphify query "Jacobian regularization multi-space" --graph graphify-out-research-combined/graph.json
```

## Cron Wiring
- `arxiv-harvest-daily` — daily 06:00 UTC — harvests arxiv per topics.yaml
- `research-graphify-build` — daily 07:00 UTC + interval 4h — builds graphify knowledge base
- `research-task-synth-daily` — daily 08:00 UTC — creates [AVA-RESEARCH] tasks in Google Tasks
- `research-wiki-weekly` — weekly Sun 10:00 UTC — deep summary to LLM wikis
- `autoresearch-loop` — hourly — picks top research task, creates experiment branch, logs results.tsv (Karpathy style)

## Next Steps for Ava Ecosystem
- Check `~/workspace/ava-research-engine/program.md` — autoresearch loop instructions (never stop loop)
- Check `~/workspace/ava-research-engine/results/results.tsv` — experiment log (commit, val_bpb, memory, status, description)
- Pick a paper from `graphify_source/` and create experiment in `experiments/` per program.md

---
Auto-generated {today} — graphify builder
"""

wiki_path.write_text(wiki_md)
print(f"[done] wrote wiki {wiki_path}")

# Log result
result_path = ROOT / "results" / f"graphify_{today}.json"
result_path.parent.mkdir(parents=True, exist_ok=True)
result_path.write_text(json.dumps({
    "date": today,
    "src_count": len(list(src_dir.glob("*.md"))),
    "out_dir": str(out_dir),
    "graph_json_exists": graph_json.exists(),
    "graph_json_kb": graph_json.stat().st_size/1024 if graph_json.exists() else 0,
    "personal_ref": str(personal_ref),
    "paper_count": paper_count,
}, indent=2))

print(f"[done] graphify build complete — {today}")
