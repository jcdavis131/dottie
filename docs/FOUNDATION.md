# Scout Foundation Plan

**North star:** Scout is a clean, extensible **judgment plane** for personal agents — not a PTY multiplexer, not a chat UI, not Herdr.

**Thesis:** Most agent managers are multiplexers. **Scout is a judgment plane.**  
(Full differentiation vs Herdr screenshots/site: [`docs/DIFFERENTIATION.md`](DIFFERENTIATION.md).)

**Primary student:** Dottie-claw (and any claw/Cursor/Claude agent we teach via skills + MCP).

Solo personal project, no connection to employer, built with public/free-tier only.

---

## 1. What Scout is (and is not)

| Scout **is** | Scout **is not** |
|---|---|
| Local-first CLI + JSON + MCP surface | Electron / browser dashboard |
| Tool registry, vault, policy, audit | A replacement for Herdr panes |
| Ava routing + herd session ledger | A hosted multi-tenant SaaS |
| Extensible plugin packs with manifests | A dumping ground of half-wired stubs |
| Something we **teach agents** to drive | Something agents must reverse-engineer |

**Herdr** owns real PTYs. **Scout** owns *what to run, with which secrets, under which policy, with which wait/read/report loop*.

```text
Dottie-claw / Cursor / Claude
        │  skill + MCP + shell
        ▼
   scout --json …
        │
        ├── secrets / auth / policy / audit
        ├── tools / mcp  (internet adapters)
        ├── herd         (session ledger + wait)
        ├── ava / agent  (route + plan)
        └── domain plugins (write, lab, brain, rtx, graphify, …)
```

---

## 2. Design principles (non-negotiable)

1. **Agent-first, human-capable** — every input is a flag; prompts only on TTY fallback.
2. **Layered discovery** — `scout --help` → plugin → command; Examples on every mutator.
3. **One plugin shape** — `cli.py` + `manifest.yaml` + optional tests; capability default-deny.
4. **Stable JSON** — prefer `{ok, command, data|error, example?}` for new surfaces.
5. **Idempotent mutators** — retries are safe; destructive ops need `--force` / `--dry-run`.
6. **Teach, don't dump** — ship skills (`bigbang/skills/`) installable for Dottie-claw.
7. **Honest stubs** — bookmarks say `status: bookmark`; never invent live measurements.

---

## 3. Execution waves

### Wave F0 — Foundation contract *(done)*

- [x] This document (`docs/FOUNDATION.md`)
- [x] `bigbang/core/contract.py` — `ok`/`err` helpers + `make_plugin_app`
- [x] `scout skill` — list / show / install for Dottie-claw, Claude, Cursor, OpenClaw
- [x] Master skill `bigbang/skills/scout/SKILL.md` (Dottie-claw curriculum)
- [x] MCP tools as `scout_<plugin>` (+ `bb_` compat)
- [x] Scaffold emits foundation-shaped plugins (Examples + contract emit)

### Wave F0.5 — Differentiation cockpit *(done)*

- [x] `docs/DIFFERENTIATION.md` — refuse the Herdr-trap; five planes thesis
- [x] `scout planes status|compare|loop|thesis` — agent-readable proof

### Wave F1 — Core hardening

- [ ] Migrate high-traffic plugins (`herd`, `secrets`, `tools`, `system`) to `ok`/`err` envelope
- [ ] Finish cli-for-agents Examples/dry-run on `mcp`, `tasks`, `rtx`, `auth logout`
- [ ] Wire fs/secret `enforce_or_raise` at write sites
- [ ] Root `--version` from package metadata

### Wave F2 — Orchestration depth (Herdr-steal, not Herdr-clone)

- [ ] `herd send` / stdin append for long jobs
- [ ] `herd watch` event poll (JSONL events file)
- [ ] Import Cursor cloud-agent runs into herd ledger
- [ ] Keep Herdr pairing via `scout herd herdr` only — never embed a TUI

### Wave F3 — Extensibility marketplace

- [ ] `scout plugin search` over GitHub topic `scout-plugin`
- [ ] `scout plugin install org/repo` → `~/.local/share/bigbang/plugins/`
- [ ] External plugin path on `PYTHONPATH` / share dir (documented)

### Wave F4 — Dottie-claw loops

- [ ] Heartbeat recipe: Dottie calls `scout --json herd status` + `agent bus` on a schedule
- [ ] RFT path: Dottie workflows → `audit.jsonl` → `scout rft export` → Ava training
- [ ] WebGPU dottie-claw serving stays *planned* until a capability checkpoint exists (arxiviq)

---

## 4. How we teach Dottie-claw

| Artifact | Role |
|---|---|
| `bigbang/skills/scout/SKILL.md` | Primary curriculum — discovery ladder, herd, vault, MCP |
| `bigbang/skills/scout-herd.md` | Deep dive on session orchestration |
| `scout skill install --target dottie` | Copies skills into Dottie-claw's skill dir |
| `scout mcp serve` | Live tool surface (`scout_herd`, `scout_tools`, …) |
| `docs/FOUNDATION.md` | Human/architect north star |

Install for Dottie-claw:

```bash
scout skill install scout --target dottie
scout skill install scout-herd --target dottie
# or
scout skill install --all --target dottie
```

Default Dottie path: `~/.dottie-claw/skills/<name>/SKILL.md`  
(also supports `--target openclaw|claude|cursor`).

---

## 5. Plugin author checklist

```bash
scout system scaffold mytool
# edit manifest.yaml capabilities
# implement commands with emit(ok(...)) / fail_agent(...)
pytest tests/ -q
scout --json mytool hello
scout skill show scout   # ensure docs still match
```

Every new plugin must:

1. Ship `manifest.yaml` with explicit caps  
2. Set `no_args_is_help=True` + Examples epilog  
3. Accept `--json` via root (no local `--json-out` forks)  
4. Fail with `{error, example}` — never hang  
5. Be reachable as `scout_<name>` MCP tool  

---

## 6. Success metrics

- Cold agent (Dottie) can run `scout skill show scout` and complete a herd create→start→wait loop without human help  
- `pytest tests/` green; MCP lists `scout_*` tools  
- New plugin via scaffold is agent-safe by default  
- Zero new prompt-first commands on the foundation surface  

---

## 7. Related docs

- `docs/herdr-inspired.md` — why we steal orchestration, not panes  
- `docs/cli-for-agents-review.md` — agentability scorecard  
- `docs/EXTENDING.md` — plugin how-to (update toward this foundation)  
- `docs/SECURITY.md` — vault / policy / audit  
