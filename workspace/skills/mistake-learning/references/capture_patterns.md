# Capture Template — Every Mistake Paired

## Minimal Pair (required fields)
```json
{
  "id": "lsn_20260807T130500Z_a1b2",
  "when": "2026-08-07T13:05:00Z",
  "what": "dottie.rl import broke engine tests — ModuleNotFoundError",
  "where": "apps/dottie/dottie/engine.py:135",
  "context": "test_engine.py echo backend",
  "signal": "ModuleNotFoundError exception, 10 tests failed",
  "errorClass": "import-shim",

  "cause": "ava.rl __init__.py replaced sys.modules with dottie.rl module, breaking submodule imports like ava.rl.codeact_loop",
  "lesson": "Package shims must not replace sys.modules — re-export instead, keep namespace intact",
  "fix_now": "Rewrote ava.rl/__init__.py to re-export without sys.modules replacement, made dottie/rl a real package, copied all codeact_* files canonical",
  "prevention": "Added rule to AGENTS.md: shim packages never replace sys.modules; always mirror as real package; engine tries ava -> dottie -> honest error",
  "confidence": 0.92,
  "paired": true,
  "applied_to": ["apps/ava-factory/ava/rl/__init__.py", "apps/dottie/dottie/rl/", "apps/dottie/dottie/engine.py", ".gitignore"]
}
```

## Patterns Library

### 1. Import / Path Debt
- Symptom: ModuleNotFoundError after move
- Lesson: One canonical source, others shim via re-export, never via sys.modules swap
- Prevention: `__init__.py` only does `from canonical import *`, no magic

### 2. Dual Lockfiles
- Symptom: bun.lock + package-lock.json, Vercel timeout on patch fetch
- Lesson: One package manager per app. Pick npm for arxiviq (Vercel), remove bun.lock
- Prevention: .gitignore guard + check in CI

### 3. Untracked Dupes
- Symptom: apps/ava-factory/bundles/, pipeline/dottie-* lying around, 115 runs
- Lesson: One canonical bundles/ultra/runs, others are mirrors built by checkpoint-manager. Old runs prune monthly.
- Prevention: .gitignore pattern pipeline/, bundles/ultra/runs/ mirrors, cron monthly_clean

### 4. Verifier Low Score <8
- Symptom: score 6-7, fix not applied, loop continues
- Lesson: Fix once max 2 loops total, single enforcement. Don't pile fixes.
- Prevention: verifier-with-budget.js owns gate, others just capture lesson

### 5. User Correction ("no, actually...")
- Symptom: User says everyday language, no machinery
- Lesson: Rewrite reply in plain words, keep deep work hidden
- Prevention: SOUL.md already says everyday language — trigger re-read

### 6. Stuck Loop >3
- Symptom: executor retries same query, same prompt
- Lesson: Rotate 1 lens from lateral-thinking-pack, confess + pivot
- Prevention: stuck-detector.js auto lens + handoff to planner/escalate

## Schema (ledger.jsonl)
Each line is a JSON object with fields above plus:
- `recurrence`: int how many times seen
- `last_seen`: iso ts
- `status`: open|applied|watching|retired
- `source`: timeline|stuck|verifier|user|manual

## Docs/LESSONS.md Format
```md
## 2026-08-07 — Import Shim Breaking Submodules
- **What**: ava.rl shim killed ava.rl.codeact_loop import
- **Cause**: sys.modules replacement
- **Lesson**: Keep namespace intact, re-export only
- **Fixed**: Made dottie/rl canonical package, ava shims to it, engine fallback chain
- **Prevents**: Future factory moves won't break tests
```
