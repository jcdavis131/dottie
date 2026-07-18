# Scout Differentiation — above Herdr, not beside it

**One line:** Most agent managers are multiplexers. **Scout is a judgment plane.**

Herdr ([herdr.dev](https://herdr.dev/)) is excellent at what it is: an agent-aware **PTY multiplexer** — local / SSH / thin-client attach, pane state, agents orchestrating panes. We do **not** compete there. We go somewhere Herdr cannot go without becoming a different product.

Solo personal project, no connection to employer, built with public/free-tier only.

---

## The trap (what the screenshots tempt)

Herdr’s site sells:

1. Run agents where the work is; attach from anywhere  
2. Responsive TUI / mobile-first terminal  
3. “tmux for AI agents” community narrative  
4. Comparison table: terminal ✓ · PTY ✓ · SSH ✓ · semantic state ✓ · attach ✓ · agents orchestrate ✓  

If Scout copies that table, Scout becomes a worse Herdr. **Refuse the trap.**

---

## Scout’s thesis

```text
Herdr  →  WHERE agents live   (panes, detach, reattach)
Scout  →  HOW agents decide   (trust, tools, judgment, memory, learning)
```

Dottie-claw (and any agent) should:

- **Live** in Herdr (or Cursor / Claude Code) when they need a real terminal  
- **Decide and act through Scout** when they need vaulted secrets, policy-gated internet tools, Ava routing, audited workflows, and a personal knowledge graph  

---

## Five planes (Scout-only stack)

| Plane | Question it answers | Scout surface | Herdr? |
|---|---|---|---|
| **Trust** | May this agent do that — and does anything leave without consent? | `secrets` · `auth` · `system policy` · **local** `audit.jsonl` · **no product telemetry** | no telemetry (shared value) |
| **World** | What internet tools exist? | `tools` · `mcp` · OpenAPI/MCP adapters | — |
| **Herd** | What’s running / blocked / done? | `herd` wait/read/report (ledger, not PTY) | panes* |
| **Judgment** | What should we do next? | `ava route` · `agent run` · Frontier-minded bus | — |
| **Memory** | What do we know / learn? | `brain` · `graphify` · `rft` (audit→train) | — |

\*Herdr’s semantic state is about **pane processes**. Scout’s herd is a **JSON control ledger** agents poll — and it feeds the learning loop.

---

## Inverted comparison (honest)

| Capability | tmux/Zellij | Agent apps | Herdr | **Scout** |
|---|---|---|---|---|
| Runs inside your terminal | ✓ | — | ✓ | ✓ (CLI/MCP) |
| Persistent PTY sessions | ✓ | limited | ✓ | — (pair with Herdr) |
| Remote SSH attach | ✓ | limited | ✓ | — (pair) |
| Semantic *pane* state | — | partial | ✓ | ledger only |
| **Capability-gated world tools** | — | partial | — | **✓** |
| **Vault + default-deny policy** | — | varies | — | **✓** |
| **Full audit → RFT training loop** | — | — | — | **✓** |
| **Local brain routing (Ava)** | — | — | — | **✓** |
| **Personal knowledge graph** | — | — | — | **✓** |
| **Installable agent curriculum** | — | partial | skill | **✓ `scout skill teach`** |
| Agents can orchestrate it | scriptable | partial | ✓ | **✓ JSON+MCP** |
| Browser dashboard / account | — | often | — | — |

---

## Decision: audit ∈ Trust · telemetry ∉ Trust

Research (Herdr brand, OpenClaw/claw norms, Codex-CLI governance pressure, local-AI audit practice):

| | **Local audit** (Scout has) | **Product telemetry** (Scout refuses) |
|---|---|---|
| Destination | Your disk (`~/.local/share/bigbang/`) | Vendor / phone-home |
| Purpose | Policy forensics + RFT learning loop | Product analytics / crash funnels |
| Consent | Implicit: you ran the command on your machine | Must be opt-in if it ever exists |
| Peer signal | LocalMode, security CLIs treat audit as evidence | Herdr/OpenClaw market “no telemetry” as trust |

**Decision (locked):**

1. **Audit is part of Trust** — append-only, redacted, local JSONL you own.  
2. **Telemetry is not a Trust feature** — it is a Trust *boundary*: Scout does not phone home.  
3. If Cam ever wants dashboards, that is an **opt-in local export** (you choose the sink), never default Scout-product telemetry. Herdr’s community “telemetry bridge” pattern is the right shape: user-owned, opt-in, not the core binary.

Do not put a `telemetry:` block inside Trust as a capability we ship. Put **`phone_home: false`** as a Trust invariant.

---

## The flywheel Herdr doesn’t have

```text
   act (tools/herd/agent)
        │
        ▼
   audit.jsonl  ──►  scout rft export  ──►  Ava train/eval
        │                                      │
        └──────── brain / graphify ◄───────────┘
                      │
                      ▼
                 better routes next time
```

This is the product: **every Dottie-claw action can make the personal stack smarter**, under policy, with secrets never in the clear.

---

## Product voice (use this, not Herdr’s)

| Don’t say | Say |
|---|---|
| “tmux for AI agents” | “judgment plane for personal agents” |
| “attach from your phone” | “decide from anywhere via MCP/CLI; live in Herdr when you need panes” |
| “mouse-first panes” | “flag-first, JSON-first, skill-taught” |
| “one terminal for the whole herd” | “one control plane for trust, tools, judgment, and memory” |

Tagline options:

1. **Scout — the judgment plane for personal agents.**  
2. **Where agents decide. (Herdr is where they live.)**  
3. **Vaulted. Audited. Teachable. Local.**  

---

## CLI proof (shipped)

```bash
scout --json planes status     # five-plane cockpit
scout --json planes compare    # matrix vs herdr/tmux/apps
scout --json planes loop       # flywheel health
scout planes thesis            # one-liner + taglines
```

Teach Dottie:

```bash
scout skill teach --target dottie
scout skill show scout
```

---

## What we will never build (differentiation by omission)

- A Scout-owned PTY multiplexer / responsive TUI clone of Herdr  
- A hosted control plane or account wall  
- Fake “live” metrics from bookmark plugins  
- Prompt-first flows that hang headless agents  

---

## Success = a stranger gets it in 10 seconds

> “Oh — Herdr is tmux-for-agents. Scout is the secure brain and tool router those agents call — and it learns from what they did.”
