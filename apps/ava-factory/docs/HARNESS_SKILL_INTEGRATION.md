# Harness + Skill System + OpenWiki Integration

> Solo personal project, no connection to employer, built with public/free-tier only

This doc ties three pieces together for Ava v6.4.

## Repos

- **ava-agi-factory-v6-4** — main model factory (this repo)
- **ava-open-harness** — open eval harness (standalone, pip installable) at `../ava-open-harness`
- `harness/registry.py` — @register_eval
- `harness/runner.py` — CLI `python -m harness run --eval all --mode mock`
- `harness/evals/jspace_tests.py` — 5 canonical tests real measurements: Spider→Ant S2 hl300-400, France→China Planner hl150-200 generalization over capital/language/continent/currency, Soccer→Rugby verbal reportability mass 0.06, Spanish→French selectivity S1 hl8 vs S2 hl300, Safety 0/180 Blackmail Critic hl30-35 early warning 4-5 tok
- `harness/evals/frontier_rubric.py` — 11-category weighted rubric (reportability, broadcast 20% norm, selectivity, modulation, routing KL, inter-MI cos 0.45, temporal planning, safety critic AUC, knowledge recall wiki->S2, reasoning depth, process transparency)
- `harness/evals/openwiki_knowledge.py` — does S2 recall facts from `~/.openwiki/wiki`?
- Mock mode no torch needed, real mode loads `ava_stable_736k.pt`
- **ava-skills** — skill system at `../ava-skills`
- 8 starter skills mapping to workspaces: jspace-inspector (Planner hl150), openwiki-sync (S2 hl300), logic-prover (S2 hl300), code-bench (S2 hl350), safety-scanner (Critic hl30), memory-router (Router), eval-harness-runner (Planner), family-brain-wiki (S2)

## OpenWiki CLI

From https://github.com/langchain-ai/openwiki:

Install:
```
npm install -g openwiki
```

Quick start:
```
openwiki personal --init # personal brain wiki in ~/.openwiki/wiki from git, gmail, notion, web-search, hacker-news, x
openwiki code --init # code docs in openwiki/ for current codebase
```

Update keeps docs fresh via CI workflow copy openwiki-update.yml into.github/workflows/openwiki-update.yml and uses `openwiki code --update --print` without init in CI.

Connectors:
- git-repo reads local repository paths and writes compact manifests
- x uses X API directly with OAuth user-context for timeline, posts, mentions, bookmarks, list posts
- notion targets hosted Notion MCP server via Notion OAuth, not paste token
- google uses Gmail API directly with OAuth user credentials to fetch recent mail
- web-search uses Tavily via LangChain requires TAVILY_API_KEY
- hackernews uses public HN feed no creds

Auth saves to `~/.openwiki/.env` via `openwiki auth gmail` flow that saves tokens into.env, creates config when possible, discovers MCP tools, after auth gmail connector can ingest directly no MCP. Secrets referenced by env var name stored in.env, config never raw secrets. `openwiki` maintains AGENTS.md and CLAUDE.md with `<!-- OPENWIKI:START -->...<!-- OPENWIKI:END -->` block, only rewrites its own block.

First-run onboarding lets choose wiki template, customize scope, save ingestion notes and schedules in `~/.openwiki/onboarding.json`, global instructions in `~/.openwiki/INSTRUCTIONS.md`, macOS LaunchAgents for schedules.

Provider support: OpenAI, OpenRouter, Fireworks, Baseten, NVIDIA NIM, OpenAI-compatible, Anthropic default OpenAI gpt-5.6-terra. Alternative base via ANTHROPIC_BASE_URL, OpenAI-compatible via OPENAI_COMPATIBLE_BASE_URL, openai-chatgpt provider via ChatGPT login stores access_token, refresh_token etc.

## Integration flow for Ava

1. Install CLI + init code docs:
```
npm install -g openwiki
cd ava-agi-factory-v6-4
openwiki code --init "Document YaRN RoPE 10k->1M, WSD 736k, 4 J-Spaces S1 hl8 S2 hl300 Critic hl30 Planner hl150, branch biases"
```

2. Init personal brain for long-term memory:
```
openwiki personal --init
openwiki auth gmail # fetch receipts
openwiki auth notion
openwiki ingest all # writes raw under ~/.openwiki/connectors/<connector>/raw/ then synthesizes wiki under ~/.openwiki/wiki/
```

3. Bridge into S2:
```
python -m skills.loader run openwiki-sync --mode mock
# real with ckpt reads ~/.openwiki/wiki/*.md -> embeds -> S2 slots
python -m skills.loader run openwiki-sync --mode real --ckpt ava_stable_736k.pt
```

4. Gate training:
```
cd ava-open-harness
python -m harness run --eval jspace_all,frontier_rubric,openwiki_knowledge --mode mock
python -m harness run --eval all --mode real --ckpt../ava-agi-factory-v6-4/ava_stable_736k.pt
```

## Family Brain port (offline-first)

Family Brain OS cannot use `~/.openwiki/wiki` (client-only). So we built `WikiTab.tsx`:

- Personal mode builds local personal brain wiki in ~/.openwiki/wiki from configured sources -> here `family-brain-wiki-pages:v1` in localStorage from house, finance-auto, git-repo connectors
- Code mode builds repo docs in openwiki/ -> for Ava: openwiki/ + AGENTS.md block
- Deterministic connector tools write raw data and manifests under ~/.openwiki/connectors/<connector>/raw/, then agent synthesizes wiki -> we mimic with `wikiConnector.ts` buildManifests()
- Connector secrets stored in.env, never raw in config -> we use AES-GCM encrypted at rest

UI: More→Wiki📖 — search, list, create/edit markdown, see connector manifests, Sync Auto generates daily snapshot pages from bills/accounts.

Export/Import JSON includes wikiPages.

## Skill execution in training loop

In `ava/train.py`, after stable checkpoint:

```python
from harness.runner import run_harness
from skills.loader import run_skill

# sync wiki into S2 before branching
run_skill("openwiki-sync", ckpt="ava_stable_736k.pt", mode="real")

# gate
results = run_harness(eval_names="jspace_all,frontier_rubric", mode="real", ckpt="ava_stable_736k.pt")
if results["meta"]["passed"] < 3:
raise RuntimeError("Harness gate failed")
```

## Next

- [] Push `ava-open-harness` and `ava-skills` to GitHub as `jcdavis131/ava-open-harness` and `jcdavis131/ava-skills` (repos scaffolded, need `gh repo create` + push)
- [] Run `openwiki code --init` in all three repos
- [] Add Family Brain WikiTab build to production bundle
