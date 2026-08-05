# How Hatch & Outside Agents Sync

This repo is the bridge.

## Source of truth (outside Hatch)
- `COORDINATION.md` at repo root = shared claim board
- Every outside agent MUST read this before editing
- Claim first, then edit on your own branch

## Source of truth (inside Hatch)
- Hatch agents also read/write `bundles/coordination/active-tasks.md` locally
- On sync, Hatch pushes its view to `COORDINATION.md` in each vector-* repo + dottie

## Rule for both
1. Claim before edit
2. Branch per task, no direct main pushes for big work
3. New models/assets as `*.candidate.json` — promote only when eval beats current + tests pass
4. Update eval tables honestly (no hardcoded wins)
5. Clear claim when done

See `COORDINATION.md` for current lanes.
