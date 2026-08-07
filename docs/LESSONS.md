# Lessons Learned — Every Mistake Paired

Every entry: what / cause / lesson / fixed / prevents

## 2026-08-07 — ava.rl shim broke submodule imports, 10 engine tests failed
- **Where**: apps/ava-factory/ava/rl/__init__.py
- **Cause**: sys.modules replacement in ava.rl/__init__.py
- **Lesson**: shims must re-export not replace namespace
- **Fixed**: made dottie/rl canonical package, ava shims clean, engine fallback chain
- **Prevents**: AGENTS.md rule: no sys.modules swap; real package mirror
- **Confidence**: 0.92

## 2026-08-07 — dual lockfiles bun.lock + package-lock caused Vercel patch timeout
- **Where**: apps/arxiviq
- **Cause**: mixed package managers
- **Lesson**: one PM per app, npm for arxiviq
- **Fixed**: removed bun.lock, kept npm
- **Prevents**: .gitignore guard + vercel.json build uses npm
- **Confidence**: 0.85

## 2026-08-07 — duplicate bundles and old pipeline runs cluttered repo 115 runs
- **Where**: bundles/ultra/runs
- **Cause**: checkpoint-manager mirrors not pruned, pipeline/ not ignored
- **Lesson**: one canonical runs location, mirrors auto, prune monthly
- **Fixed**: deleted dupes, pruned to 100, .gitignore guards
- **Prevents**: monthly_clean cron + .gitignore pipeline/ + bundles/ultra/runs/
- **Confidence**: 0.88
