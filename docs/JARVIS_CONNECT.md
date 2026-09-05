# Connect an agent to Jarvis

How Claude Code, Cursor and OpenCode reach the `jarvisd` daemon
(`docs/JARVISD_SPEC.md`; plan `docs/JARVIS_HARNESS_PLAN.md` §5 Phase 3).
All three clients talk MCP streamable-HTTP to `<JARVIS_URL>/mcp` with a static
bearer. One daemon, one SQLite file, one claim board.

## Environment

| Var | Meaning | Default |
|---|---|---|
| `JARVIS_URL` | Daemon base URL, no path | `http://127.0.0.1:8790` |
| `JARVIS_BEARER` | Static bearer (spec §2). Required unless the daemon runs on loopback with auth disabled. | unset |

Put `JARVIS_BEARER` in `deploy/.env` (`cp deploy/.env.example deploy/.env`,
chmod 600; git-ignored) — the same file `docker-compose.jarvisd.yml` reads. The
Claude Code hook reads `deploy/.env` and `~/.config/dottie/.env` itself, but the
MCP clients only see your process environment, so also export both variables in
the shell that launches `claude`, Cursor or `opencode`. The committed configs
reference the variables; **never commit a real token**.

To use the tunnel instead of the local daemon, set
`JARVIS_URL=https://jarvis.<your-domain>` (Claude Code picks it up through
`${JARVIS_URL:-…}`) and edit the literal URL in `.cursor/mcp.json` and
`opencode.json`, whose formats have no default-value expansion.

## Claude Code

| Item | Where |
|---|---|
| Server | `.mcp.json` (project scope) — `type: http`, `url: ${JARVIS_URL:-http://127.0.0.1:8790}/mcp`, header `Authorization: Bearer ${JARVIS_BEARER}` |
| SessionStart hook | `.claude/hooks/jarvis_session_start.py`, registered in `.claude/settings.json` under `hooks.SessionStart` (matcher `startup|resume|clear|compact`, 5 s timeout) |
| Skill | `.claude/skills/jarvis/SKILL.md` — when to `context` / `claim` / `remember` / `recall` / `send` / `harness.*` / `ask` |

Verify:

```bash
claude mcp list            # jarvis: …/mcp (HTTP) — first run shows "Pending approval"
claude                     # approve the project server when prompted, then /mcp
python3 .claude/hooks/jarvis_session_start.py   # prints one JSON line if the daemon is up, nothing if down
```

Shapes confirmed against https://code.claude.com/docs/en/mcp (`${VAR}` and
`${VAR:-default}` expand in `url` and `headers`) and
https://code.claude.com/docs/en/hooks (`hookSpecificOutput.additionalContext`).

## Cursor

| Item | Where |
|---|---|
| Server | `.cursor/mcp.json` — `mcpServers.jarvis.url` (streamable HTTP) + `headers.Authorization: Bearer ${env:JARVIS_BEARER}` |
| Rule | `.cursor/rules/jarvis.mdc` (`alwaysApply: false`, globbed to source and docs) |

Verify: Cursor Settings → MCP (or Tools & Integrations → MCP) lists `jarvis`
with a green dot and the tool list (`jarvis.context`, `jarvis.remember`, …).
If the dot is red, launch Cursor from a shell where `JARVIS_BEARER` is exported;
Cursor reads the variable from its own process environment, not from `.env`.

Note: `.gitignore` ignores `.cursor/` wholesale in this repo, so these two
files are untracked until the operator adds `!.cursor/mcp.json` and
`!.cursor/rules/` (not changed in this pass). The `${env:…}` header syntax is
the Cursor documented form; the docs host was unreachable from the build
environment, so if Cursor shows the header unexpanded, paste the token into the
(already git-ignored) `.cursor/mcp.json` locally and do not track the file.

## OpenCode

| Item | Where |
|---|---|
| Server | `opencode.json` — `mcp.jarvis`: `type: remote`, `url: http://127.0.0.1:8790/mcp`, `enabled: true`, header `Authorization: Bearer {env:JARVIS_BEARER}` |

Verify:

```bash
opencode mcp list          # jarvis and its auth status
opencode mcp debug jarvis  # if it does not connect
```

Shape confirmed against the OpenCode docs source
(`packages/web/src/content/docs/mcp-servers.mdx` and `config.mdx` in
`sst/opencode`): `{env:VAR}` substitutes an environment variable and expands to
an empty string when unset, hence the literal URL.

## Acceptance: two clients, one memory (spec §8 item 2)

- [ ] Daemon up: `curl -s $JARVIS_URL/api/health` → `{"ok": true, …}`
- [ ] Claude Code: `claude mcp list` shows `jarvis` connected
- [ ] Cursor: Settings → MCP shows `jarvis` green
- [ ] In Claude Code: `jarvis.remember(text="connect-test <today> from claude", scope="repo:dottie", tags=["test"])` → `ok: true`
- [ ] In Cursor, within seconds: `jarvis.recall(query="connect-test")` returns that memory with `agent: claude`
- [ ] Reverse direction: `remember` from Cursor, `recall` from Claude Code
- [ ] In Cursor: `jarvis.claim(repo="dottie", area="docs", note="test")`; in Claude Code `jarvis.claims` shows it within 5 s (plan §5 Phase 3 acceptance); `jarvis.release` from Cursor
- [ ] Optional: `opencode mcp list` shows `jarvis`; `jarvis.recall` from OpenCode returns the same memory
- [ ] New Claude Code session in this repo shows the `Jarvis (…)` line from the SessionStart hook

## Other repos

Copy into each active `vector-*` repo (and any other repo the fleet works in):

```bash
cp .mcp.json .cursor/mcp.json ../vector-<name>/          # mkdir -p ../vector-<name>/.cursor first
cp -r .claude/skills/jarvis .claude/hooks/jarvis_session_start.py ../vector-<name>/.claude/...
cp .cursor/rules/jarvis.mdc ../vector-<name>/.cursor/rules/
```

Then merge the `hooks.SessionStart` entry from `.claude/settings.json` into that
repo's settings (do not overwrite other keys). The hook derives the repo name
from the directory basename, so no per-repo edits are needed.

The per-repo `COORDINATION.md` claim boards are superseded by `jarvis.claim`
(plan §5 Phase 3: one board, no sync commits). They are left in place in this
pass; stop adding rows to them once the daemon is reachable from every client.
