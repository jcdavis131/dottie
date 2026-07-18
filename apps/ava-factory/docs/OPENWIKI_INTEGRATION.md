# OpenWiki Integration for Ava AGI Factory v6.4

> Solo personal project, no connection to employer, built with public/free-tier only

## Why OpenWiki?

OpenWiki is a CLI that writes and maintains agent documentation for your codebase. It has two modes:
- **Personal mode** builds a local personal brain wiki in `~/.openwiki/wiki` from configured sources like local repositories, Gmail, Notion, Web Search, Hacker News, and X/Twitter
- **Code mode** builds repository documentation in `openwiki/` for the current codebase

For Ava, this maps directly to our J-Space architecture:

| OpenWiki Concept | Ava Mapping | Implementation |
|---|---|---|
| Personal wiki `~/.openwiki/wiki` | S2 Slow Workspace (hl=300 deliberate long-term memory) | `research/memory/openwiki_adapter.py` |
| Code wiki `openwiki/` | S1 Fast + Planner (codebase awareness + temporal planning) | `openwiki/` + AGENTS.md block |
| Connectors (git-repo, gmail, notion, web-search, hackernews) | Data ingestion connectors (git, gmail receipts, web edu) | `ava/connectors/openwiki_connectors.py` |
| Deterministic connector tools write raw data and manifests under `~/.openwiki/connectors/<connector>/raw/`, then agent synthesizes wiki | Ava streaming_data.py dual-track (raw dolma + curated logic) | Same pattern |
| AGENTS.md + CLAUDE.md maintained with `<!-- OPENWIKI:START -->` block | Foreman + worker protocol | We preserve existing AGENTS.md, only rewrite our block |

## Installation

```bash
npm install -g openwiki
# or
bun add -g openwiki
# Windows needs VS Build Tools for better-sqlite3
```

## Quick Start for Ava

```bash
# Code brain mode - repo docs
openwiki code --init
# Personal brain mode - Ava's long-term memory
openwiki personal --init
```

Then to keep docs up-to-date, add the CI workflow:
- GitHub Actions: copy `openwiki-update.yml` into `.github/workflows/openwiki-update.yml`
- GitLab CI: copy `openwiki-update.gitlab-ci.yml`

For repo docs in CI, use `openwiki code --update --print` - no need for --init in CI

## Connectors for Ava

OpenWiki onboarding offers connector setup for local Git repos, Notion, Gmail, X/Twitter, Web Search, Hacker News. You can configure same connector multiple times as separate instances like `web-search-1` and `web-search-2`.

For Ava we configure:
- `git-repo` → reads local paths, writes compact manifests
- `google` → Gmail API with OAuth user credentials (reuse existing Gmail hookup for receipts)
- `notion` → targets hosted Notion MCP server via Notion OAuth
- `x` → X API directly with OAuth user-context for home timeline etc
- `web-search` → Tavily through LangChain requires TAVILY_API_KEY
- `hackernews` → public HN feed, no credentials

Auth: `openwiki auth gmail` runs local browser OAuth flow, saves tokens into `~/.openwiki/.env`. After that, Google connector can ingest Gmail directly with no MCP setup.

Config and secrets saved to `~/.openwiki/.env` on local machine. Connector secrets referenced by env var name and stored in `.env`; config files should never contain raw secret values.

## Ava-Specific Extensions

### 1. OpenWiki → J-Space Bridge

Create `research/memory/openwiki_adapter.py`:

- Watches `~/.openwiki/wiki/` markdown files
- Embeds them into S2 Slow slots (hl=300) as verbalizable concepts
- On eval, top_concepts mass should correlate with wiki pages about that concept
- Implements France→China generalization test via wiki: one vector from wiki about France -> generalizes to capital/language/continent/currency

### 2. Wiki-aware Evaluations

Add evals:
- `evals/openwiki_knowledge.py` — does Ava's S2 recall facts from personal wiki?
- Measures reportability mass (should be 0.06+) after wiki ingestion

### 3. Family Brain Port

Family Brain OS is client-only offline-first (no `~/.openwiki`), so we build an inspired version:

- New tab `WikiTab` that mimics `~/.openwiki/wiki` but stores in encrypted localStorage
- Connectors: `csvConnector`, `plaidConnector`, `gmailConnector` (mock local) → same raw/manifest pattern: `connectors/<name>/raw/` → in-memory, then local heuristic LLM synthesizes wiki pages
- No API keys required: uses `llmConnector` with local heuristic fallback (already exists)
- Export/Import JSON includes wiki pages

See `~/workspace/family-brain-os/src/components/WikiTab.tsx` and `docs/OPENWIKI_FAMILY_BRAIN.md`

## CI Workflow

`openwiki` maintains both AGENTS.md and CLAUDE.md at repo root, adding prompting that instructs coding agent to reference wiki when searching. Each file is created if not exists. If present, OpenWiki only rewrites its own `<!-- OPENWIKI:START -->…<!-- OPENWIKI:END -->` block and leaves rest untouched.

We keep our existing AGENTS.md (Home/Work separation) outside the block, and let OpenWiki manage its block.

## Usage in this repo

```bash
# dev: generate docs
openwiki code --init "Document Ava AGI Factory v6.4 architecture, training phases, J-Space losses, eval harness"

# update
openwiki code --update
openwiki --update "Refresh from configured connectors"

# personal brain ingest
openwiki ingest all
openwiki ingest git-repo
openwiki ingest web-search-2

# auth
openwiki auth gmail
openwiki auth notion
openwiki auth x
openwiki auth slack

# ngrok for Slack OAuth
openwiki ngrok start
# prints callback URL, reads ngrok inspection API, saves OPENWIKI_HTTPS_OAUTH_REDIRECT_URI automatically
```

## Custom Providers

Supports OpenAI (API key or ChatGPT login), OpenRouter, Fireworks, Baseten, NVIDIA NIM, OpenAI-compatible, Anthropic. Default is OpenAI with gpt-5.6-terra.

- Alternative base URLs: set ANTHROPIC_BASE_URL alongside key
- OpenAI-compatible: set OPENAI_COMPATIBLE_BASE_URL + MODEL_ID
- ChatGPT login provider `openai-chatgpt` calls Codex backend using ChatGPT subscription, stores access_token, refresh_token etc in ~/.openwiki/.env
- Retry override: OPENWIKI_PROVIDER_RETRY_ATTEMPTS=3

## Next Steps

- [] Install openwiki CLI
- [] Run `openwiki code --init` in this repo -> creates openwiki/ + updates AGENTS.md block
- [] Copy workflow `.github/workflows/openwiki-update.yml`
- [] Implement `research/memory/openwiki_adapter.py` bridge
- [] Family Brain: ship WikiTab + wikiConnector
