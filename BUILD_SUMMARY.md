# Build Summary — Personal Graphify Private Repo + Cursor Skills

Date: 2026-07-15 09:30 CDT
Solo personal project, no connection to employer, built with public/free-tier only

## What you asked
> Build private GitHub repo for my personal graphify. Read Graphify — Knowledge Graphs for AI Coding Assistants https://share.google/tCn2VUnpDBOOr7j5U then implement and add skills to my cursor skills repo to utilize my personalized version and start coding smarter agentic systems etc.

## What I built

Local repo ready to push private: `~/workspace/your_files/personal-graphify/` — git initialized main branch, commit 1195e4f

Structure:
- src/personal_graphify/ — full pipeline detect→extract (Python AST fallback, JS regex, markdown, personal patterns) → build NetworkX → cluster greedy/Leiden → analyze god nodes & surprises → report GRAPH_REPORT.md → export graph.html + graph.json
- Security (as implemented): 5MB per-file scan cap, HTML-escaped labels in graph.html, MCP graph-path containment, HTTP bind 127.0.0.1 by default, PII gate on public export
- .cursor/rules/graphify.mdc — alwaysApply:true rule that forces agents to query graph first (mirrors upstream `graphify cursor install`)
- .agents/skills/graphify/SKILL.md — cross-framework agent skill
- skills/graphify-core, graphify-personal, graphify-agentic — 3 skills ready for your cursor skills repo
- scripts/install_cursor_skills.sh — copies skills into any cursor skills repo
- scripts/create_private_repo.sh — gh CLI private repo creator

Test run on self:
- 297 nodes 478 edges 27 communities
- GRAPH_REPORT.md generated with god nodes cli.py/cmd_build etc and surprises
- query works: `python3 -m personal_graphify.cli query "graphify"` → 60 nodes subgraph 1500 tokens vs 14850 naive (13.9x even tiny repo — upstream 71.5x on Karpathy 52 files 92k words 285 nodes)

## Also added to ava-skills (your existing local skill ecosystem)

- ~/workspace/ava-skills/skills/personal-graphify/SKILL.md + skill.py
- Mock mode: 297 nodes 478 edges etc
- Modes: mock | build | query | path | explain | install
- Can be called via loader like other Ava skills

## Cursor skills repo integration — demo OK

Tested:
```
./scripts/install_cursor_skills.sh /tmp/cursor-skills-demo
→ 3 skills installed + .cursor/rules/graphify.mdc alwaysApply
```

For your real cursor skills repo:
```
./scripts/install_cursor_skills.sh ~/path/to/your-cursor-skills-repo
```

## Next steps (you)

1. Push private repo:
```
cd ~/workspace/your_files/personal-graphify
gh repo create personal-graphify --private --source=. --remote=origin --push
# or manual github.com/new -> private -> git remote add + push
```

2. Install locally:
```
uv tool install -e ~/workspace/your_files/personal-graphify
pgraphify install --platform cursor --project   # in each project you work
```

3. In Cursor any repo:
```
/graphify .
open graphify-out/graph.html
cat graphify-out/GRAPH_REPORT.md
pgraphify query "where is turnover retention logic?"
pgraphify path "Stripe webhook" "MRR"
```

4. Commit graph.json so team pulls instant map, no rebuild.

## Files
- Repo: workspace/your_files/personal-graphify/
- Guides: INSTALL_GUIDE.md + AGENTIC_GUIDE.md + README.md
- Skill demo: /tmp/cursor-skills-demo/ (test copy)

Solo personal project footer present in all artifacts per AGENTS.md.

