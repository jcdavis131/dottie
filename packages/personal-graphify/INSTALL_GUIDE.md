# Private GitHub Repo Setup + Cursor Skills Integration

Solo personal project, no connection to employer, built with public/free-tier only.

This guide takes you from zero to personal Graphify in Cursor coding smarter agentic systems.

## 1. Create Private GitHub Repo

You already have local repo at `~/workspace/your_files/personal-graphify/`

### Option A — with gh CLI (recommended)

```bash
cd ~/workspace/your_files/personal-graphify
gh auth login
./scripts/create_private_repo.sh personal-graphify private
# Creates private repo github.com/YOURUSER/personal-graphify + pushes
```

### Option B — manual (github.com/new)

1. Go to https://github.com/new
2. Name: `personal-graphify` , Visibility: Private, do NOT init with README
3. Then:

```bash
cd ~/workspace/your_files/personal-graphify
git init
git add .
git commit -m "feat: personal-graphify v0.1.0 — Ollama-first Graphify fork with Cursor skills (solo, free-tier only)"
git branch -M main
git remote add origin git@github.com:YOURUSER/personal-graphify.git
git push -u origin main
```

## 2. Install Personal Graphify Locally (free-tier)

```bash
# isolated (recommended)
uv tool install -e ~/workspace/your_files/personal-graphify
# or
pipx install -e ~/workspace/your_files/personal-graphify
# dev mode
pip install -e ~/workspace/your_files/personal-graphify --break-system-packages

# optional: also install upstream for full MCP server fallback
uv tool install graphifyy
```

Verify:

```bash
pgraphify --help
python -m personal_graphify.cli build . --out /tmp/test --max-files 200
```

## 3. Install Cursor Skills (your cursor skills repo)

Your source repo for Cursor rules (maybe `~/code/cursor-skills` or `~/cursor-skills-repo` — replace path):

```bash
# copy 3 skills + .cursor/rules/graphify.mdc into your cursor skills repo
~/workspace/your_files/personal-graphify/scripts/install_cursor_skills.sh ~/path/to/your-cursor-skills-repo

cd ~/path/to/your-cursor-skills-repo
git add skills/graphify-core skills/graphify-personal skills/graphify-agentic .cursor/rules/graphify.mdc .agents/skills/graphify
git commit -m "feat: personal-graphify skills — 71.5x token reduction, Ollama-first, Davis ecosystem"
git push
```

Then in **any project** you work on (Vector Hoops, Ava, Family Brain, Turnover Shield):

```bash
# one-time per project
pgraphify install --platform cursor --project
# writes .cursor/rules/graphify.mdc with alwaysApply:true and .agents/skills/graphify/SKILL.md
git add .cursor/rules/graphify.mdc .agents/skills/graphify
git commit -m "chore: enable personal-graphify graph-first"
```

## 4. Use In Cursor — Code Smarter Agentic Systems

In Cursor Chat (Cmd+K / Cmd+L), the rule `graphify.mdc` is auto-included.

### Build once
```
/graphify .
→ creates graphify-out/graph.html (open in browser), GRAPH_REPORT.md, graph.json (commit this)
```

### Query-first workflow (instead of grep)
```
/graphify query "what connects Stripe webhook to MRR?"
/graphify path "Turnover Shield Stripe" "Supabase MRR"
/graphify explain "MTNN"
/graphify explain "Ava S2 Slow"
open graphify-out/graph.html
```

Upstream pattern: Karpathy mixed corpus 285 nodes 340 edges 53 communities ~1.7k tokens vs ~123k naive = 71.5x. Same holds locally — your 297 nodes 27 communities was 13.9x even on tiny repo.

### Agentic system prompt

Paste this when you want agent to act senior:

> Before editing, run `pgraphify query "how does turnover churn calc flow?"` + `pgraphify explain "Turnover Shield"` and `graphify-out/GRAPH_REPORT.md` god nodes. Use only that subgraph + EXTRACTED edges. If need Stripe connection, run `pgraphify path "Stripe webhook" "MRR"`. Never brute-grep before query.

### Commit graph

```bash
git add graphify-out/graph.json graphify-out/GRAPH_REPORT.md
# .gitignore already has graphify-out/cache + cost.json — keep repo small, but graph.json committed so team pulls instant map, no rebuild needed
graphify hook install  # auto-rebuild AST on commit + merge driver for graph.json
```

## 5. Ollama (optional, query-time only)

Extraction never calls an LLM — it is AST + regex + Markdown parsing + ecosystem patterns.
Ollama is used ONLY when you pass `--semantic` to `pgraphify query`/`task`, to rerank the
top lexical matches with local embeddings. No cloud fallback exists; if Ollama isn't
running, queries silently stay lexical.

```bash
pip install "personal-graphify[ollama]"   # the ollama python client
ollama pull mxbai-embed-large             # embedding model used by --semantic
ollama serve
pgraphify query "Turnover Shield" --semantic
```

## 6. Integrate with Ava Skills (you already have ava-skills/)

```bash
# Already created: ~/workspace/ava-skills/skills/personal-graphify/
ls ~/workspace/ava-skills/skills/personal-graphify/
# SKILL.md + skill.py

# test runner
python -m ava_skills.skills.loader --skill personal-graphify --mode mock
python -m ava_skills.skills.personal-graphify.skill --mode build --path ~/workspace/your_files/personal-graphify
```

This lets Ava AGI Factory auto-discover personal-graphify as a skill — `jspace-inspector` + `family-brain-wiki` + `personal-graphify` compose.

## 7. Daily Use Examples — Your Ecosystem

```bash
# Family Brain
cd ~/workspace/your_files/davis-family-brain
pgraphify . ; pgraphify query "Betterment Joint 5594 $201,954 vs Emergency"

# Turnover Shield (goal $1k MRR = 7-13 customers @ $79-149)
cd ~/workspace/your_files/passive-lab/turnover-shield
pgraphify . ; pgraphify query "where is retention playbook defined?"
pgraphify path "Stripe checkout" "paid_users"

# Ava v6.4
cd ~/workspace/ava-agi-factory-v6-4
pgraphify . --max-files 500 ; pgraphify query "S1 Fast hl8 vs Planner hl150 broadcast"

# Vector Hoops 12,966 seasons
cd ~/workspace/vector-hoops
pgraphify . ; pgraphify query "MTNN 120 feats 17 families cat([x·m,m])"
```

## 8. Security & Isolation (Home-only)

- Solo personal project, no connection to employer, built with public/free-tier only
- Free/public pip only, no work connectors, manual CSV/upload
- Zero references to work internal systems — passes path check `01_Finance / 02_Passive_Lab / 04_Tennis_DINOv3` vs `03_Meta_Work_ISOLATED`
- Security (as implemented): 5MB per-file scan cap, HTML-escaped labels in graph.html, MCP graph-path containment, HTTP server binds 127.0.0.1 by default, PII gate on public export

## Footer

Footer disclaimer included per AGENTS.md: Solo personal project footer in README + all skills + all templates.

Enjoy smarter agentic coding — query graph, not grep.
