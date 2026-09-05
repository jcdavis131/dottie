---
name: jarvis
description: Use the shared Jarvis daemon (jarvisd MCP server) for cross-agent context, memory, claims, handoffs and harness runs. Load at the start of any work session in a repo that has .mcp.json pointing at jarvis, and before editing shared areas, grepping for known facts, or handing work to Cursor/OpenCode.
---

# Jarvis — shared context for the agent fleet

Jarvis is one always-on daemon (`apps/jarvisd`, spec: `docs/JARVISD_SPEC.md`).
Claude Code, Cursor and OpenCode all connect to the same SQLite-backed state
over MCP, so a memory written here is recalled there. The tools below are
exposed by the `jarvis` MCP server configured in `.mcp.json`. The client agent
is the brain; Jarvis is the ledger. If a tool is missing, run `claude mcp list`
and check `docs/JARVIS_CONNECT.md` before working around it.

## When to call what

| Moment | Tool | Notes |
|---|---|---|
| Start of work in a repo | `jarvis.context(repo)` | Open claims, open goals, last memories and timeline rows, unread inbox count. The SessionStart hook injects a one-line summary; call this for detail. |
| Before editing a repo area | `jarvis.claim(repo, area, note)` | Fails if another agent holds the same `repo+area`; do not edit until it succeeds. `jarvis.release` when done. `jarvis.claims` to see the board. |
| A decision, a gotcha, a command that worked | `jarvis.remember(text, scope, tags)` | Scope `repo:<name>` for repo facts, `global` for fleet-wide, `person:<name>` for people. One fact per call; include the evidence (file path, command, number). |
| Before grepping for something you might already know | `jarvis.recall(query, scope)` | FTS over memories. Cheaper than a codebase search and captures what other agents learned. If it returns nothing, grep, then `remember` the answer. |
| Handing work to Cursor or OpenCode, or reading theirs | `jarvis.send(to, body)` / `jarvis.inbox(mark_read)` | Agent ids: `claude`, `cursor`, `opencode`. Body: what, where, what is verified, what is not. |
| Recording or closing a goal | `jarvis.goal` / `jarvis.goals` / `jarvis.goal_done` | Goals are per repo; `goal_done` takes `result` json. |
| Deciding how to run a goal | `harness.route(goal)` | Scout's heuristic router; records a timeline row. Use before `harness.run` for anything non-trivial. |
| Running a goal through the harness | `harness.run(goal, mcp_namespace)` | Records run id and critic score to the timeline. |
| Asking Jarvis itself | `jarvis.ask(question, repo)` | Only when the operator has set `ANTHROPIC_API_KEY` on the daemon. Otherwise it returns `brain unavailable`; say "brain is off" and answer from context yourself. Never present a fabricated answer as Jarvis's. |
| Checking health | `jarvis.status()` | Version, uptime, db path, counts, brain availability. |

Every tool returns JSON with `ok`; on failure, `error` and `example`. Read the
`example` before retrying.

## Session shape

1. Read the SessionStart summary, then `jarvis.context(repo)` if it mentions
   open claims or goals that touch your task.
2. `jarvis.recall` for the area you are about to work in.
3. `jarvis.claim` the area. If it fails, `jarvis.send` the holder or pick
   another area; do not edit a claimed area.
4. Work. As you go, `jarvis.remember` decisions, gotchas and commands that
   worked, with the evidence attached.
5. Before ending: `jarvis.release`, `jarvis.goal_done` if applicable, and
   `jarvis.send` a handoff to whoever picks it up next.

## Claim boards

`jarvis.claim` supersedes the per-repo `COORDINATION.md` claim boards (plan
§5 Phase 3). Do not delete those files in this pass; do not add new rows to
them either. One board, no sync commits.

## Voice

The operator's house voice applies to anything you write into Jarvis or send
to another agent: measured, evidence-backed, honest about what is unmeasured.
State the number, the file, or the command; no sports metaphors, no hype.
A memory that says "X works" without saying how it was verified is not useful.

## Setup and verification

`docs/JARVIS_CONNECT.md` — per-client config, `claude mcp list`, the two-client
acceptance test, and how to copy this setup into other repos.
