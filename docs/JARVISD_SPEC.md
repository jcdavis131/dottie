# jarvisd — the Jarvis daemon (spec)

**Status:** Implementing 2026-09-05 (Phase 1 of `JARVIS_HARNESS_PLAN.md`)
**Package:** `apps/jarvisd` (Python 3.11, uv workspace member, stdlib + `mcp` SDK + `uvicorn`)
**Role:** the one always-on process other agents connect to. Claude Code, Cursor and
OpenCode speak MCP to it; humans and scripts speak JSON over HTTP to it. It owns the
shared state (memory, claims, inbox, goals, timeline index) in one SQLite file.

The client agent is the brain in v1 (plan §6 decision 1). jarvisd is the shared
context, tools and routing server. `jarvis.ask` gives it a voice of its own at $0 by
default: the home-box Ollama (§6), with Anthropic only when the operator sets
`ANTHROPIC_API_KEY`. When neither can serve it returns a structured "brain
unavailable" error, never a fabricated answer. Everything here runs free: SQLite,
stdlib, a Cloudflare Tunnel or a Hugging Face Space.

## 1. Process shape

```
python -m jarvisd serve --host 0.0.0.0 --port 8790 --db /data/jarvis.db
```

One `uvicorn` process serving one Starlette app:

| Mount | What |
|---|---|
| `/mcp` | MCP streamable-HTTP (FastMCP `streamable_http_app()`), stateless mode so a proxy or sleep/wake host cannot strand a session |
| `/sse` | MCP SSE (legacy transport, same tool set) |
| `/api/*` | JSON API (below) |
| `/` | one-page text status (no auth): name, version, uptime, tool count |

Port 8790, not 8787: `docker-compose.dottie.yml` already binds 8787 for the old dev API.

## 2. Auth (all of `/mcp`, `/sse`, and every `/api/*` except `/api/health`)

Ported from the inline server in `docker-compose.dottie.yml`, implemented once as a
Starlette middleware in `jarvisd/auth.py`:

- Static bearer: `Authorization: Bearer <JARVIS_BEARER>`, `hmac.compare_digest`.
- Ephemeral token: `<sig16>:<unix_ts>:<nonce>` where `sig16 = HMAC-SHA256(JARVIS_BEARER, f"{ts}:{nonce}")[:16]`, valid ±90 s, single-use (256-entry LRU).
- Rate limits per minute: 1000 per IP, 60 per key (last 4 chars), 20 per `X-Agent-Id`.
- Fail closed: if `JARVIS_BEARER` is unset and host is not loopback, refuse to start.
  On loopback with no bearer, start with auth disabled and say so in the status page.
- Responses carry `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`.
- Audit: append `{ts, agent, path, status, key_last4}` to `<db dir>/audit.jsonl`. Never the raw key.

## 3. State (`jarvisd/state.py`, SQLite, WAL mode)

| Table | Columns |
|---|---|
| `memories` | id, ts, agent, scope (`repo:<name>` / `global` / `person:<name>`), text, tags (json), source |
| `claims` | id, ts, agent, repo, area, note, released_ts (null = active) |
| `messages` | id, ts, from_agent, to_agent, body, read_ts |
| `goals` | id, ts, agent, repo, text, status (`open`/`done`/`dropped`), result (json) |
| `timeline` | id, ts, agent, repo, kind, payload (json) — index of harness runs and notable events |
| `sessions` | id, ts, agent, repo, last_seen |

`recall` is FTS5 over `memories.text` with a LIKE fallback if FTS5 is unavailable.
Every write records `agent` from `X-Agent-Id` (default `anon`). JSONL export of any
table via `/api/export/<table>` for the flywheel; the DB is the store, JSONL is a view.

## 4. MCP tools (`jarvisd/tools.py`)

Names use dots as the plan wrote them; FastMCP accepts them. Every tool returns a JSON
string with `ok`, and on failure `error` + `example`.

| Tool | Args | Does |
|---|---|---|
| `jarvis.context` | repo | open claims, open goals, last 10 memories in scope, last 10 timeline rows, unread inbox count for the caller |
| `jarvis.remember` | text, scope="global", tags=[] | insert memory |
| `jarvis.recall` | query, scope=None, limit=10 | FTS search |
| `jarvis.claim` / `jarvis.release` / `jarvis.claims` | repo, area, note | claim board; claim fails if another agent holds the same repo+area |
| `jarvis.send` / `jarvis.inbox` | to, body / mark_read | agent-to-agent messages |
| `jarvis.goal` / `jarvis.goals` / `jarvis.goal_done` | repo, text / id, result | goals |
| `harness.route` | goal | calls scout's heuristic router in-process (`bigbang.plugins.harness.cli` scoring functions); records a timeline row |
| `harness.run` | goal, mcp_namespace=None | calls `bigbang.plugins.harness.runner.run_goal`; records a timeline row with the run id and critic score |
| `contacts.resolve` | phrase | acne `ContactsHub().resolve` if `acne` is importable, else `ok:false, error:"acne not installed"` |
| `graph.query` | query, graph_path=None | personal-graphify `graph.json` query if importable, else structured error |
| `jarvis.ask` | question, repo=None | optional Anthropic brain (§6) |
| `jarvis.status` | | version, uptime, db path, counts, brain availability |

`scout_<plugin>` tools are NOT re-exported by default (64 subprocess tools is noise for
a pair programmer). `--expose-scout` adds them via `bigbang.plugins.mcp.server.build_server`.

## 5. JSON API (`jarvisd/app.py`)

`GET /api/health` (no auth) → `{ok, version, uptime_s, db, brain}`
`POST /api/route {goal}` · `POST /api/run {goal}` · `POST /api/plan {goal}` (same shape as `apps/dottie-harness-api`)
`GET|POST /api/memories` · `GET /api/recall?q=` · `GET|POST|DELETE /api/claims` ·
`GET|POST /api/inbox` · `GET|POST|PATCH /api/goals` · `GET /api/timeline` · `GET /api/export/<table>`

## 6. Brain (`jarvisd/brain.py`, optional)

- Two providers behind one tool loop, picked by `JARVIS_BRAIN`:
  - `ollama` — the operator's home-box Ollama over plain HTTP (`POST {OLLAMA_HOST}/api/chat`,
    `stream:false`, tools in Ollama's `{"type":"function","function":{...}}` shape). Stdlib
    `urllib` only, no extra dependency, $0 to run. Model `JARVIS_MODEL` → `OLLAMA_MODEL` →
    `qwen3:32b` (what the rest of the repo runs). 120 s per call (`JARVIS_BRAIN_TIMEOUT`).
  - `anthropic` — the `anthropic` SDK (optional extra `jarvisd[brain]`); model `claude-opus-5`,
    adaptive thinking, `output_config.effort` from `JARVIS_EFFORT` (default `high`), streaming.
    The only paid path.
- `JARVIS_BRAIN=auto` (default): Anthropic when `ANTHROPIC_API_KEY` is set (a set key commits
  to Anthropic; a missing SDK is then reported, not swapped), else Ollama when
  `GET {OLLAMA_HOST}/api/tags` answers within 1 s, else unavailable. `off` disables the tool.
- Manual tool loop over the daemon's own tools (context, recall, remember, claims, route);
  max 8 turns; every tool call and result is appended to `timeline` as `kind="brain"` on
  both providers. Ollama tool arguments may arrive as a dict or a JSON string; each call is
  answered with one `{"role":"tool"}` message. Result shape is the same for both:
  `ok, answer, turns, tool_calls, usage{input_tokens,output_tokens,cache_read_input_tokens},
  model, provider, stop_reason` (`end_turn` | `tool_use` | `max_turns`; Anthropic may also
  report `refusal`).
- System prompt: the operator's house voice (measured, evidence-backed, honest about
  what is unmeasured), the repo name, and the `jarvis.context` result for that repo.
- No provider can serve → `{ok:false, error:"brain unavailable: <reason>"}` (e.g.
  `ANTHROPIC_API_KEY unset; ollama unreachable at http://127.0.0.1:11434: ...`). An Ollama
  host that goes down mid-call → `{ok:false, error:"ollama unreachable at <host>: ..."}`,
  never a raise. `jarvis.status().brain` reports `provider`, `model`, `available`, `reason`.
- Tests use a fake Anthropic client and a fake `urllib.request.urlopen`; no network in tests.

## 7. Config (env, all optional except as noted)

| Var | Default | Meaning |
|---|---|---|
| `JARVIS_BEARER` | — | static bearer; **required** when host is not loopback |
| `JARVIS_DB` | `~/.local/share/jarvisd/jarvis.db` | SQLite path |
| `JARVIS_HOST` / `JARVIS_PORT` | `127.0.0.1` / `8790` | bind |
| `JARVIS_PUBLIC_HOST` | — | hostname for DNS-rebinding allowlist when public (e.g. `jarvis.example.com`) |
| `JARVIS_WORKSPACE` | `~/workspace` | root the harness may read/write under |
| `JARVIS_BRAIN` | `auto` | brain provider: `auto` \| `anthropic` \| `ollama` \| `off` (§6) |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama base URL for the `ollama` provider (compose: `http://host.docker.internal:11434`) |
| `OLLAMA_MODEL` | `qwen3:32b` | Ollama model when `JARVIS_MODEL` is unset |
| `JARVIS_BRAIN_TIMEOUT` | `120` | seconds per Ollama `/api/chat` call (the 1 s `/api/tags` probe is fixed) |
| `ANTHROPIC_API_KEY`, `JARVIS_MODEL`, `JARVIS_EFFORT` | — / `claude-opus-5` / `high` | Anthropic brain (paid); `JARVIS_MODEL` also overrides the Ollama model |
| `BIGBANG_POLICY_FILE` | scout default | URL allowlist for downstream MCP |

## 8. Acceptance (plan §5 Phase 1)

1. `claude mcp add --transport http jarvis https://<host>/mcp --header "Authorization: Bearer …"` lists the tools.
2. A memory written from one client is recalled from another within seconds.
3. `docker compose -f docker-compose.jarvisd.yml up` brings the daemon up with no heredoc.
4. `uv run pytest apps/jarvisd -q` green; scout-cli and ava-factory suites unaffected.
5. Unauthenticated `/mcp` → 401; bad ephemeral token → 401; reused ephemeral token → 401.
