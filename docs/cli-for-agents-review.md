# Scout CLI × cli-for-agents — hyper-detail review

**Date:** 2026-07-17  
**Scope:** `scout-cli` v0.6.1 (`bigbang/` package, primary binary `scout`)  
**Lens:** [cli-for-agents](https://github.com/) skill — headless, layered help, examples, pipelines, actionable errors, idempotency, dry-run, confirmation bypass, consistent structure, machine-useful success output.

Solo personal project, no connection to employer, built with public/free-tier only.

---

## Executive scorecard

| Criterion | Score (pre → post this PR) | Notes |
|---|---|---|
| Non-interactive first | **C → B+** | `--json` + many flags existed; auth/secrets still prompted and could hang agents. Fixed for secrets/auth/tools core paths. |
| Discoverability (layered help) | **A−** | `no_args_is_help=True` everywhere; root lists plugins. Good. |
| `--help` with Examples | **D → B** | Almost no Examples before. Root + secrets/auth/tools/write/agent now ship copy-pasteable Examples. Remaining plugins still thin. |
| stdin / pipelines | **C+ → B** | `write` already accepted stdin. secrets/auth now `--stdin`; still uneven elsewhere. |
| Fail-fast actionable errors | **C → B** | Typer “Missing argument” was bare. Core paths now emit `{error, example, discover}`. |
| Idempotency | **B** | `tools add` overwrites; `secrets rm` / `tools rm` report `existed`/`ok`. |
| Destructive dry-run / `--force` | **D → C+** | Added `--dry-run`/`--force` on secrets/tools rm. Most other mutators still lack dry-run. |
| Predictable structure | **B+** | `resource verb` mostly (`tools list`, `auth login`). Outliers: `rtx releases` action positional, `tasks delete` vs `secrets rm`, stale `bb` in some docs. |
| Success output for agents | **A−** | Global `--json` + `emit()` is excellent. Audit redaction is real. |

**Overall agentability (pre):** ~**C+** — marketed agent-native, but several default paths were human-prompt-first.  
**Overall after this pass:** ~**B** — core vault/auth/tools paths are agent-safe; rest of surface still needs the same treatment.

---

## What already worked well

1. **Global `--json` with position-independent hoist** (`ScoutTyper`) — agents can write `scout tools list --json` or `scout --json tools list`.
2. **Layered discovery** — root → plugin → leaf; no dump of the entire manual on every run.
3. **`emit()` dual mode** — Rich/JSON + audited, with secret redaction in `core/output.py`.
4. **`agent run` default is plan-only**; `--execute` is opt-in (good destructive default).
5. **`ava train`/`eval` have `--yes`**; `tasks delete` has `--force`.
6. **`write` stdin story** — `--text` / `--file` / pipe.
7. **MCP serve** — real stdio/SSE server (`scout mcp serve`) for Cursor/Claude.
8. **Capability manifests** per plugin — right shape for policy-gated agent execution.

---

## Findings (severity-ranked)

### P0 — Agent blockers (fixed in this PR where marked)

| ID | Finding | Skill rule | Status |
|---|---|---|---|
| P0.1 | `scout auth set-token <svc>` with no token **prompted and hung** under `timeout`/pipes | Non-interactive first | **Fixed** — fail-fast + `--token`/`--stdin` |
| P0.2 | `scout auth login --method pat` had no `--token`; always prompted | Flags over prompts | **Fixed** — `--token` |
| P0.3 | `scout secrets set KEY VALUE` required positional secret (shell history + no stdin) | stdin/flags | **Fixed** — `--value` / `--stdin` |
| P0.4 | Missing-required Typer errors gave no example invocation | Fail-fast with example | **Partial** — custom `fail_agent` on logical errors; Typer missing-arg still generic |

### P1 — High-value agent UX gaps

| ID | Finding | Recommendation |
|---|---|---|
| P1.1 | Leaf `--help` had **zero Examples** on nearly every command | Adopt `examples_epilog()` on every mutator + top 20 read commands (pattern in `core/cli_ux.py`) |
| P1.2 | Hints still said `bb …` in many emit payloads | Sweep remaining plugins (`ava`, `system`, README snippets) to `scout` |
| P1.3 | `tools rm` / `secrets rm` had no `--dry-run`; agents can't preview | **Fixed** for secrets/tools; extend to `tasks delete`, `auth logout`, `mcp` rm |
| P1.4 | `tools get` / `secrets get` missing → exit 0 with error JSON (or soft emit) | **Fixed** — exit 1 via `fail_agent` |
| P1.5 | `rtx releases` uses positional `list\|sync` instead of subcommands | Split to `releases list` / `releases sync` for consistency with `tools list` |
| P1.6 | No global `--yes` / `--dry-run` | Optional root flags that plugins can read (env `SCOUT_YES=1` also helps agents) |

### P2 — Structure & honesty

| ID | Finding | Recommendation |
|---|---|---|
| P2.1 | `family` / `vector` / `tennis` are bookmarks; help text still reads like live tools | Keep bookmark status in **command help first line** (tennis already does); promote pattern |
| P2.2 | `agent run --execute` is real now, but README still oversells Ava “plans + runs” without emphasizing plan-default | Document plan-default + `--execute` in root epilog (done) and README What’s New |
| P2.3 | Inconsistent delete verbs: `rm` vs `delete` vs `logout` | Alias both (`rm`/`delete`) on secrets/tools/tasks |
| P2.4 | `lab` has `--json-out` alias that does nothing useful vs root `--json` | Remove or wire; document “always use `scout --json`” |
| P2.5 | Policy engine supports fs/secret enforce; zero call sites (ecosystem audit) | Wire `enforce_or_raise` before writes — security × agent trust |
| P2.6 | Success payloads vary shape (`message` vs `status` vs bare dict) | Standard envelope: `{ok, command, data, example?}` for `--json` |

### P3 — Polish

| ID | Finding | Recommendation |
|---|---|---|
| P3.1 | Emoji-heavy help burns tokens for agents | Keep human help; add `scout --help --plain` or `SCOUT_HELP_PLAIN=1` |
| P3.2 | `doctor` duplicated at root and `system doctor` | Fine for UX; document canonical `scout system doctor` |
| P3.3 | No `scout completion` examples in root help | Add to epilog (shell install already exists via Typer) |
| P3.4 | Version not on `--version` | Add `@app.callback` version option from `pyproject`/`importlib.metadata` |

---

## Command-surface audit (live)

Probed on this machine after install:

| Surface | Help layered? | Examples? | Non-interactive? | Dry-run / force? |
|---|---|---|---|---|
| `scout` | yes | **yes (new)** | n/a | n/a |
| `secrets *` | yes | **yes (new)** | **yes (new)** | **yes (new)** |
| `auth login/set-token` | yes | **yes (new)** | **yes (new)** | n/a |
| `tools *` | yes | **yes (new)** | yes | **rm dry-run/force (new)** |
| `write scan` | yes | **yes (new)** | yes (stdin) | n/a |
| `agent run` | yes | **yes (new)** | yes | plan-default / `--execute` |
| `ava train/eval` | yes | no | `--yes` | no dry-run |
| `tasks delete` | yes | no | `--force` | no dry-run |
| `graphify *` | yes | prose only | yes | n/a |
| `mcp serve` | yes | no | yes | n/a |
| `rtx releases` | yes | no | yes | no |
| `family/vector/tennis` | yes | n/a | yes (bookmark emit) | n/a |

---

## Recommended backlog (priority order)

### Wave 1 — finish agent-safe core (this PR starts it)

1. ✅ `core/cli_ux.py` helpers (`examples_epilog`, `fail_agent`, `require_secret_value`, `is_interactive`)
2. ✅ secrets / auth / tools / root / write scan / agent run Examples + non-interactive paths
3. ⬜ Apply same pattern to: `mcp add/rm`, `tasks delete`, `auth logout`, `rtx releases sync`, `system scaffold`
4. ⬜ Root `--version`
5. ⬜ Sweep remaining `bb ` strings in emit payloads + docs quickstart

### Wave 2 — consistency

1. Subcommand-ize `rtx releases {list,sync}`
2. Standard JSON envelope for all `emit()` calls
3. Global `SCOUT_YES` / `SCOUT_DRY_RUN` env honored by confirm gates
4. Alias `delete`↔`rm` across plugins

### Wave 3 — trust & execution

1. Wire fs/secret policy enforcement at write sites
2. `--dry-run` on `agent run --execute` (print argv only)
3. Bookmark plugins: single `status: bookmark` schema + README section “Bookmarks vs live”
4. `scout doctor --json` machine checklist for agent boot probes

---

## Concrete “good” patterns to copy inside this repo

**Non-interactive secret ingest**

```bash
scout secrets set GITHUB_TOKEN --value "$TOKEN"
printf '%s' "$TOKEN" | scout secrets set GITHUB_TOKEN --stdin
scout auth set-token github --token "$TOKEN"
```

**Fail-fast shape** (`fail_agent`)

```json
{
  "error": "GITHUB_TOKEN not found",
  "example": "scout secrets set GITHUB_TOKEN --value <secret>",
  "discover": "scout secrets list"
}
```

**Destructive preview**

```bash
scout tools rm old-tool --dry-run
scout tools rm old-tool --force
```

**Discovery ladder**

```bash
scout --help
scout tools --help
scout tools add --help
```

---

## Verification commands

```bash
pip install -e ".[dev]"
pytest tests/test_cli_for_agents.py tests/test_cli.py -q
scout --help | grep -A20 Examples
scout secrets set --help | grep -A10 Examples
printf 'x' | scout auth set-token _agent_probe --stdin
scout auth set-token _agent_probe 2>&1 | head -5   # must exit fast, not hang
scout tools rm __missing__ --force --dry-run
```
