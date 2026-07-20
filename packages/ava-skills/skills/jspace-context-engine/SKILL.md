---
name: jspace-context-engine
description: Build the single-CLI context payload — empty tool registry, scout-only text manifest, forge as the sole expansion path
triggers:
- context
- manifest
- system prompt
- tools
- forge
- single cli
j_space_target: Planner
half_life: 150
broadcast_target: 0.22
reportability_target: 0.065
dependencies: []
connectors: []
provider: none
---

# jspace-context-engine

Assembles the context block handed to a local engine (qwen3:32b and similar) so that the
**`scout` CLI is the only executable surface**.

## Why `tools: []` is deliberate

Local models invent tool schemas. Given a registry of fifty functions they will confidently
call a fifty-first that does not exist, and the failure is silent — a well-formed JSON call
that nothing consumes. So the payload ships an **empty tool array** and describes the
interface in **text** instead. One verb (`scout`) is enforceable; a registry is not.

## Why the inventory is fetched, not hardcoded

Subcommands come from `scout --json forge list` at build time, so a tool forged five minutes
ago appears in the next prompt with no edit here.

If that call fails, the manifest says **"inventory unavailable"** rather than listing
nothing. Those are different claims: a model told *"you have no tools"* when the truth is
*"we could not ask"* will forge duplicates of things that already work.

## Expansion

A missing capability has exactly one sanctioned response:

```
scout forge new <name> --description '<what it does>'
```

`missing_tool_guidance()` returns those words verbatim, so the same instruction reaches the
model whether the gap is spotted while building context or at call time.

## Use

```python
from skills.loader import SkillLoader
ctx = SkillLoader().get("jspace-context-engine").run()      # live inventory
ctx["tools"]    # [] — always
ctx["system"]   # the text manifest

run(mode="mock", want="weather")   # deterministic, no CLI needed
```

Solo personal project, no connection to employer, built with public/free-tier only.
