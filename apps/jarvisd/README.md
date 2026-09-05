# jarvisd — the Jarvis daemon

The one always-on process the operator's agents connect to. Claude Code, Cursor and
OpenCode speak **MCP** to it (`/mcp` streamable-HTTP, `/sse` legacy); humans and scripts
speak **JSON over HTTP** (`/api/*`). It owns the shared state — memories, claims, inbox,
goals, timeline, sessions — in one SQLite file. Spec: `docs/JARVISD_SPEC.md`.

The client agent is the brain in v1. An optional `jarvis.ask` runs a tool loop against
either the home-box Ollama (`$0`, stdlib HTTP, default `qwen3:32b`) or Anthropic (paid,
`jarvisd[brain]`), picked by `JARVIS_BRAIN` (`auto` = Anthropic if `ANTHROPIC_API_KEY` is
set, else Ollama if `OLLAMA_HOST` answers). When neither can serve, the tool returns a
structured `brain unavailable` error, never a fabricated answer.

## Quickstart

```bash
uv sync --all-groups                       # workspace member; stdlib + mcp + starlette + uvicorn
export JARVIS_BEARER="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run python -m jarvisd serve             # 127.0.0.1:8790, db ~/.local/share/jarvisd/jarvis.db
```

```bash
uv run python -m jarvisd serve --host 0.0.0.0 --port 8790 --db /data/jarvis.db   # public: JARVIS_BEARER required
uv run python -m jarvisd serve --expose-scout --no-sse                            # add scout_<plugin> tools, drop /sse
uv run python -m jarvisd export memories > memories.jsonl                         # JSONL view of any table
uv run python -m jarvisd token                                                    # ephemeral single-use token
```

Without `JARVIS_BEARER` the daemon starts only on a loopback host, with auth disabled,
and says so on the `/` status page. A non-loopback bind without a bearer refuses to start.

## Connect an agent

```bash
claude mcp add --transport http jarvis http://127.0.0.1:8790/mcp \
  --header "Authorization: Bearer $JARVIS_BEARER" --header "X-Agent-Id: claude-code"
```

Send `X-Agent-Id` so memories, claims and messages carry your agent's name; without it
you are `anon`. Every tool also accepts an explicit `agent` argument.

Tools: `jarvis.context` · `jarvis.remember` · `jarvis.recall` · `jarvis.claim` ·
`jarvis.release` · `jarvis.claims` · `jarvis.send` · `jarvis.inbox` · `jarvis.goal` ·
`jarvis.goals` · `jarvis.goal_done` · `harness.route` · `harness.run` ·
`contacts.resolve` · `graph.query` · `jarvis.ask` · `jarvis.status`.
Each returns a JSON string with `ok`; on failure `error` and `example`.

## Environment

| Var | Default | Meaning |
|---|---|---|
| `JARVIS_BEARER` | — | static bearer; **required** when the host is not loopback |
| `JARVIS_DB` | `~/.local/share/jarvisd/jarvis.db` | SQLite path; `audit.jsonl` lives beside it |
| `JARVIS_HOST` / `JARVIS_PORT` | `127.0.0.1` / `8790` | bind |
| `JARVIS_PUBLIC_HOST` | — | hostname for the DNS-rebinding allowlist when public (e.g. `jarvis.example.com`) |
| `JARVIS_WORKSPACE` | `~/workspace` | root the harness writes runs under (`bundles/ultra/runs`) and where `graph.query` looks for `graphify-out/graph.json` |
| `JARVIS_BRAIN` | `auto` | brain provider: `auto` \| `anthropic` \| `ollama` \| `off`; `auto` = Anthropic when the key is set, else Ollama when `/api/tags` answers within 1 s |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama base URL (bare `host:port` gets `http://`); compose sets `http://host.docker.internal:11434`. Plain `urllib`, so `no_proxy` applies if you export a proxy |
| `OLLAMA_MODEL` | `qwen3:32b` | Ollama model when `JARVIS_MODEL` is unset |
| `JARVIS_BRAIN_TIMEOUT` | `120` | seconds per Ollama `/api/chat` call |
| `ANTHROPIC_API_KEY`, `JARVIS_MODEL`, `JARVIS_EFFORT` | — / `claude-opus-5` / `high` | Anthropic brain, paid (`pip install 'jarvisd[brain]'`); `JARVIS_MODEL` also overrides the Ollama model |
| `JARVIS_RATE_IP` / `JARVIS_RATE_KEY` / `JARVIS_RATE_AGENT` | `1000` / `60` / `20` | requests per minute per IP / key / `X-Agent-Id` |
| `BIGBANG_POLICY_FILE` | scout default | URL allowlist for downstream MCP (read by scout) |

`contacts.resolve` needs `acne`, which is not on any package index: install the sibling
checkout (`pip install -e ~/workspace/acne`); jarvisd also looks for `~/workspace/acne/src`.

## Auth

- `Authorization: Bearer <JARVIS_BEARER>` — constant-time compare.
- Ephemeral: `<sig16>:<unix_ts>:<nonce>` with `sig16 = HMAC-SHA256(JARVIS_BEARER, "ts:nonce")[:16]`,
  valid ±90 s, single-use (256-entry LRU). `python -m jarvisd token` mints one.
- Rate limits per minute: 1000/IP, 60/key (last 4 chars), 20/`X-Agent-Id`.
- `/` and `/api/health` need no auth. Every response carries `Cache-Control: no-store`,
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`.
- Audit: `<db dir>/audit.jsonl`, one `{ts, agent, path, status, key_last4}` per request. Never the key.

## curl

```bash
H=(-H "Authorization: Bearer $JARVIS_BEARER" -H "X-Agent-Id: shell")
curl -s localhost:8790/api/health
curl -s "${H[@]}" -X POST localhost:8790/api/memories -d '{"text":"port is 8790","scope":"repo:dottie","tags":["ports"]}'
curl -s "${H[@]}" "localhost:8790/api/recall?q=8790"
curl -s "${H[@]}" -X POST localhost:8790/api/claims -d '{"repo":"dottie","area":"apps/jarvisd","note":"building"}'
curl -s "${H[@]}" localhost:8790/api/claims
curl -s "${H[@]}" -X DELETE localhost:8790/api/claims -d '{"repo":"dottie","area":"apps/jarvisd"}'
curl -s "${H[@]}" -X POST localhost:8790/api/inbox -d '{"to":"cursor","body":"take the README"}'
curl -s -H "Authorization: Bearer $JARVIS_BEARER" -H "X-Agent-Id: cursor" "localhost:8790/api/inbox?mark_read=1"
curl -s "${H[@]}" -X POST localhost:8790/api/goals -d '{"repo":"dottie","text":"green CI"}'
curl -s "${H[@]}" -X PATCH localhost:8790/api/goals -d '{"id":1,"result":{"sha":"abc"}}'
curl -s "${H[@]}" -X POST localhost:8790/api/route -d '{"goal":"compare Stripe vs Lemon Squeezy Aug 2026"}'
curl -s "${H[@]}" -X POST localhost:8790/api/plan  -d '{"goal":"ship the daemon"}'
curl -s "${H[@]}" "localhost:8790/api/timeline?repo=dottie"
curl -s "${H[@]}" localhost:8790/api/export/memories        # JSONL

# one-shot token instead of the bearer (single use, 90 s)
T=$(uv run python -m jarvisd token)
curl -s -H "Authorization: Bearer $T" localhost:8790/api/claims
```

## Layout

| File | Role |
|---|---|
| `jarvisd/config.py` | env → `Config`, loopback detection, fail-closed rule |
| `jarvisd/state.py` | SQLite (WAL, FTS5 with LIKE fallback), thread-safe `State` |
| `jarvisd/auth.py` | pure-ASGI `AuthMiddleware`, `mint_token`, rate limiter, audit |
| `jarvisd/tools.py` | `Jarvis` service + FastMCP tool registration |
| `jarvisd/app.py` | `build_app(config)` → Starlette; `serve()` under uvicorn |
| `jarvisd/brain.py` | optional brain: Ollama (stdlib, `$0`) or Anthropic (`jarvisd[brain]`), one shared tool loop |
| `jarvisd/cli.py` | `serve` / `export` / `token` |

```bash
uv run pytest apps/jarvisd -q
uvx ruff@0.15.22 check apps/jarvisd
```
