#!/usr/bin/env python3
"""
Research Task Synthesizer — Daily 08:00 UTC
Solo personal project, no connection to employer, built with public/free-tier only
Home-life only — uses Hatch-managed Google Tasks via hatch_gws_cli, no secrets

Purpose: Take latest arxiv papers from rolling_index.json and graphify, create [AVA-RESEARCH] tasks for Ava ecosystem
Bakes research into actionable tasks for Ava-AGI to research, per Karpathy autoresearch: each task → experiment hypothesis

Inputs:
  - ~/workspace/your_files/research/arxiv/rolling_index.json
  - ~/workspace/ava-research-engine/config/topics.yaml
  - ~/workspace/bigbang-cli/graphify-out-research/graph.json (optional for relevance scoring)

Outputs:
  - Creates Google Tasks via hatch_gws_cli tasks insert (target list: Lina's Morning / Ava Research)
  - ava-research-engine/results/tasks_{date}.json log
  - ava-research-engine/docs/tasks_{date}.md report

Security: No secrets, uses Hatch OAuth for tasks, FS write only to allowed paths
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml


def sanitize_no_proxy():
    for var in [
        "NO_PROXY",
        "no_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
    ]:
        val = os.environ.get(var, "")
        if not val:
            continue
        parts = re.split(r"[, \s]+", val)
        cleaned = [
            p
            for p in parts
            if p
            and p not in ["::", "::/0"]
            and not p.startswith("[")
            and "::" not in p
            and "fd8b" not in p
        ]
        os.environ[var] = ",".join(cleaned)


sanitize_no_proxy()

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "topics.yaml"
cfg = yaml.safe_load(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
topics_cfg = {t["id"]: t for t in cfg.get("topics", [])}
tasks_cfg = cfg.get("tasks", {})
max_tasks = tasks_cfg.get("max_tasks_per_day", 5)
prefix = tasks_cfg.get("prefix", "[AVA-RESEARCH]")
target_list = tasks_cfg.get(
    "target_list_id", "MDg4NTEzMTkzNjgwNzI5NDMyMDI6MDow"
)  # Lina's Morning
also_create = tasks_cfg.get("also_create_list", "Ava Research")


def expand(p):
    return Path(os.path.expanduser(str(p)))


rolling_path = expand("~/workspace/your_files/research/arxiv/rolling_index.json")
output_dir = ROOT / "results"
output_dir.mkdir(parents=True, exist_ok=True)
docs_dir = ROOT / "docs"
docs_dir.mkdir(parents=True, exist_ok=True)

today = datetime.now(UTC).date().isoformat()

if not rolling_path.exists():
    print(f"[error] rolling index not found {rolling_path} — run harvester first")
    sys.exit(0)

rolling = json.loads(rolling_path.read_text())
papers = rolling.get("papers", {})
print(f"[task-synth] {today} — rolling has {len(papers)} papers")

# Filter to last 7 days updated
cutoff = datetime.now(UTC) - timedelta(days=7)
recent = []
for pid, paper in papers.items():
    try:
        upd_str = paper.get("updated") or paper.get("published") or ""
        upd = datetime.fromisoformat(upd_str.replace("Z", "+00:00"))
        if upd >= cutoff:
            recent.append(paper)
    except:
        # if no date, include if in last list?
        recent.append(paper)

# Sort by updated desc
recent_sorted = sorted(recent, key=lambda x: x.get("updated", ""), reverse=True)
print(f"  recent (7d): {len(recent_sorted)}")


# Deduplication: check existing tasks to avoid re-creating same arxiv_id
def list_existing_tasks(tasklist_id):
    try:
        cmd = [
            "hatch_gws_cli",
            "tasks",
            "tasks",
            "list",
            "--params",
            json.dumps({"tasklist": tasklist_id, "maxResults": 100}),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            print(f"list tasks failed {result.stderr[:500]}")
            return []
        data = json.loads(result.stdout)
        items = data.get("items", [])
        return items
    except Exception as e:
        print(f"list existing error {e}")
        return []


existing_tasks = list_existing_tasks(target_list)
existing_titles = {t.get("title", "") for t in existing_tasks}
existing_notes = " ".join([t.get("notes", "") for t in existing_tasks])

print(f"  existing tasks in target {target_list}: {len(existing_tasks)}")


def task_already_exists(arxiv_id):
    return arxiv_id in existing_notes or any(arxiv_id in t for t in existing_titles)


# Scoring: prioritize critical importance topics first
importance_order = {"critical": 0, "high": 1, "medium": 2}


def topic_importance(paper):
    # get first topic's importance
    topics = paper.get("topics", [])
    if not topics:
        return 2
    imp = topics_cfg.get(topics[0], {}).get("importance", "medium")
    return importance_order.get(imp, 2)


recent_scored = sorted(
    recent_sorted,
    key=lambda p: (topic_importance(p), p.get("updated", "")),
    reverse=False,
)

selected = []
for paper in recent_scored:
    if len(selected) >= max_tasks:
        break
    if task_already_exists(paper["arxiv_id"]):
        print(f"  skip {paper['arxiv_id']} already exists")
        continue
    selected.append(paper)

print(f"  selected {len(selected)} new tasks to create")

created = []

for paper in selected:
    topic_id = paper.get("topics", ["unknown"])[0] if paper.get("topics") else "unknown"
    topic_info = topics_cfg.get(topic_id, {})
    ecosystem = topic_info.get("ecosystem", "ava-agi-factory-v6-4/")
    importance = topic_info.get("importance", "medium")
    graph_community = topic_info.get("graphify_community", "")

    title = f"{prefix}[{topic_id}][{importance}] {paper['title'][:80]} — {paper['arxiv_id']}"

    # Build notes with rich context for Ava researcher
    notes = f"""Research Task — Auto-generated {today} from arxiv harvest + graphify
Solo personal project, no connection to employer, built with public/free-tier only

Paper: {paper["title"]}
ArXiv ID: {paper["arxiv_id"]}
URL: {paper["arxiv_url"]}
PDF: {paper.get("pdf_url", "")}
Published: {paper.get("published", "")} / Updated: {paper.get("updated", "")}
Authors: {", ".join(paper.get("authors", [])[:6])}
Categories: {", ".join(paper.get("categories", []))}
Topics: {", ".join(paper.get("topics", []))} (ecosystem: {ecosystem})
Graph Community: {graph_community}

Abstract:
{paper.get("abstract", "")[:1200]}

Why relevant:
{topic_info.get("description", "")}

Suggested Experiment (Karpathy autoresearch style):
- Single file to modify: train_1b_deepspeed.py OR model_1b.py OR multi_jspace_module.py (per ecosystem)
- Fixed time budget: 5 minutes wall clock (like program.md)
- Metric: val_bpb lower is better (or cap preservation 0.983 for branch eval)
- Hypothesis for this paper: Apply {paper["title"]} idea to Ava {topic_id}
  Examples:
    - If Muon optimizer: Try Muon for S1 Fast hl=8, keep AdamW for S2 Slow hl=300, compare val_bpb
    - If YaRN: Extend ROPE 10k->1M NTK-aware to 2M, test long context retrieval
    - If GraphRAG: Use graphify query "what connects X to Y" to augment retrieval in ava eval
    - If MCP: Add new tool via bb tools add --type openapi and expose as bb_* for Ava router
- Steps to attempt:
  1. Read paper PDF + graphify_source/{paper["arxiv_id"]}.md
  2. git checkout -b autoresearch/{topic_id}-{paper["arxiv_id"].lower()}
  3. Modify train script (one file only for clean diff)
  4. Commit
  5. Run: uv run train.py or python -m ava.train --preset nano_quick --max-steps 20 smoke
  6. Log to results.tsv: commit val_bpb memory_gb status(description)
  7. If improved, keep branch, update graphify_source, else git reset

Links:
- Graphify source: ~/workspace/ava-research-engine/graphify_source/{paper["arxiv_id"]}.md
- Graphify query: pgraphify query "{paper["title"][:40]}" --graph ~/workspace/bigbang-cli/graphify-out-research/graph.json
- Rolling index: {rolling_path}
- Paper: {paper["arxiv_url"]}

Complexity: importance={importance}
Next: Create experiment in ~/workspace/ava-research-engine/experiments/{paper["arxiv_id"]}/

Auto-wired to Ava ecosystem — will be picked by autoresearch-loop cron (hourly)
"""

    # Create via hatch_gws_cli
    payload = {
        "title": title,
        "notes": notes,
    }
    try:
        cmd = [
            "hatch_gws_cli",
            "tasks",
            "tasks",
            "insert",
            "--params",
            json.dumps({"tasklist": target_list}),
            "--json",
            json.dumps(payload),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode == 0:
            created_task = json.loads(result.stdout)
            print(f"  [created] {paper['arxiv_id']} -> {created_task.get('id')} ")
            created.append({"paper": paper, "task": created_task, "title": title})
        else:
            print(f"  [failed] {paper['arxiv_id']} {result.stderr[:500]}")
            # try fallback to @default
            cmd2 = [
                "hatch_gws_cli",
                "tasks",
                "tasks",
                "insert",
                "--params",
                json.dumps({"tasklist": "@default"}),
                "--json",
                json.dumps(payload),
            ]
            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=20)
            if result2.returncode == 0:
                created_task = json.loads(result2.stdout)
                print(f"  [created fallback @default] {paper['arxiv_id']}")
                created.append({"paper": paper, "task": created_task, "title": title})
    except Exception as e:
        print(f"  exception creating task {paper['arxiv_id']}: {e}")

    time.sleep(1)  # be nice

# Save log
log_path = output_dir / f"tasks_{today}.json"
log_path.write_text(
    json.dumps(
        {
            "date": today,
            "selected": len(selected),
            "created": len(created),
            "papers": [c["paper"] for c in created],
            "tasks": [
                {
                    "id": c["task"].get("id"),
                    "title": c["title"],
                    "arxiv_id": c["paper"]["arxiv_id"],
                }
                for c in created
            ],
        },
        indent=2,
    )
)

# Write docs report
doc_path = docs_dir / f"tasks_{today}.md"
md = f"""# Research Tasks Synthesized — {today}

Solo personal project, no connection to employer.

- Rolling papers: {len(papers)}
- Recent 7d: {len(recent_sorted)}
- Selected for creation: {len(selected)}
- Created: {len(created)}
- Target list: {target_list} (Lina's Morning = @default)
- Prefix: {prefix}
- Max per day: {max_tasks}

## Created Tasks
"""
for c in created:
    md += f"- **{c['paper']['arxiv_id']}** [{c['paper'].get('topics', ['?'])[0]}] {c['title']}\n  - {c['paper']['arxiv_url']}\n  - Task ID {c['task'].get('id')} in list {target_list}\n"

md += f"""
## Existing Tasks in Target (before)
Count: {len(existing_tasks)}

## Next
- Check `bb tasks list --tasklist {target_list}`
- Check `~/workspace/ava-research-engine/program.md` for autoresearch loop instructions
- Experiments will be created in `experiments/` per paper and logged to `results/results.tsv`

---
Generated {today}
"""
doc_path.write_text(md)

print(f"[done] created {len(created)} tasks — log {log_path} doc {doc_path}")

# Also attempt to ensure Ava Research list exists via bb tasks create-list
try:
    cmd = ["hatch_gws_cli", "tasks", "tasklists", "list", "--params", "{}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode == 0:
        data = json.loads(result.stdout)
        titles = [tl.get("title") for tl in data.get("items", [])]
        if also_create not in titles:
            print(f"  creating new tasklist '{also_create}'")
            cmd2 = [
                "hatch_gws_cli",
                "tasks",
                "tasklists",
                "insert",
                "--json",
                json.dumps({"title": also_create}),
            ]
            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=15)
            print(f"    create list result: {result2.stdout[:500]}")
except Exception as e:
    print(f"  ensure list exists failed {e}")
