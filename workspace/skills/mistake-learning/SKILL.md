---
name: "mistake-learning"
description: "Learns from every mistake — pairs each failure, correction, or stuck loop with a concrete lesson and applies it to your harness and personalized setup. Always on. Use when something fails, feels slow, or you say 'learn from this'."
---

# Mistake Learning — Every Mistake Paired With a Lesson

## Purpose
Turn every error, retry, user correction, low verifier score, or stuck-loop into a durable improvement. No mistake is logged alone — it's always paired with why it happened and how we prevent it next time. Then auto-improve the harness, prompts, and your Scout setup.

## When To Trigger
- Any tool error, test fail, build fail, timeout, 503, or loop>3
- User says no / wrong / actually / fix / again
- Verifier score <8, latency spike, conf <0.4
- You explicitly say "learn from this" or "every mistake is a lesson"
- Hourly sweep even when quiet (always-on)

## Workflow

1. **Capture Mistake (30s)**
   ```json
   {
     "when": "ISO timestamp",
     "what": "short what failed",
     "where": "agent/node/tool",
     "context": "prompt or task id",
     "errorClass": "timeout|auth|import|logic|UX|etc",
     "signal": "user correction | stuck-detector | verifier 6/10 | exception"
   }
   ```

2. **Pair With Lesson (1 lens)**
   - Root cause: 1 sentence honest
   - Lesson: what to do differently
   - Fix now: patch applied
   - Prevention: harness/prompt/check that stops it forever
   - Confidence: 0-1 for auto-apply

3. **Store**
   - Append to `workspace/lessons/ledger.jsonl` (machine)
   - Append to `docs/LESSONS.md` (human readable)
   - If people-related: queue for `people_writeback.jsonl` → MEMORY.md

4. **Apply (always-on)**
   - conf >=0.7: auto-patch (AGENTS.md convention, manifest.json rule, ultra module guard, prompt in bundles/)
   - conf 0.4-0.69: draft patch + flag for review
   - conf <0.4: note as hint only, never block
   - Never fake success. If unavailable, log 503/unavailable.

5. **Close Loop**
   - Log to `bundles/ultra/runs/<id>/timeline.jsonl` with fields: nodeId, agentId, attempt, latency, tokens, status, errorClass
   - Update `AGENTS.md` Conventions if new pattern emerges 3x
   - Prune lessons >90d that never recurred

## Tooling
- `bin/learn.py` — CLI to capture and apply
  - `learn.py capture '{"what":"..."}' --lesson '{"cause":"...","fix":"..."}'`
  - `learn.py sweep --hours 24`  — scans timeline.jsonl for failures
  - `learn.py apply --min-conf 0.7`
- References: heavy examples and schema live in `references/`

## Output Contract
Every capture returns:
```
lesson_id: lsn_<ts>
paired: true|false (must be true to save)
applied: auto|draft|hint|skipped + file paths
next: 1 sentence on what this prevents next time
```

## Operating Rules
1. Every mistake MUST be paired. Lone error logs are rejected.
2. Always-on: hourly cron + stuck/verify hooks. Even "no change" gets logged to timeline.jsonl.
3. Local-first, zero-deps. No vector DB, no embeddings API, no cloud. Pure traversal.
4. Honest: label EXTRACTED vs INFERRED, never hallucinate metrics.
5. Tech-debt friendly: if fix removes 10 lines and adds 2, prefer removal. Cleaner systems > more files.
6. Single enforcement for quality: Verifier With Budget still owns ship gate. This skill only improves, never bypasses it.
7. One clarifying Q max, then act.

## Integration Points
- `stuck-detector.js`: loop>3 or conf<0.4 → calls this skill with 1 lens
- `verifier-with-budget.js`: score<8 → capture why + fix once
- `checkpoint-manager.js`: every timeline.jsonl errorClass becomes input
- `people_writeback.py`: people mistakes → MEMORY.md
- Cron: `bundles/cron.d/mistake_learning_hourly.json` owner=operator 60m
