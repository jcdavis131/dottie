# Claim Board Prompt — for any helper (Hatch or local)

Copy this into your other agent as its SYSTEM / task preamble. It works both ways (Hatch ↔ outside).

---

**You are working in a shared monorepo setup with other agents.**

Repos: `dottie`, `vector-hoops`, `vector-pitch`, `vector-gridiron`, `vector-equities`, `vector-unified`, `vector-hub`, `scout-cli`

**Source of truth for who is doing what:**

1. `bundles/coordination/active-tasks.md` — master inside Hatch
2. `COORDINATION.md` at root of each repo — mirrored for outside agents (pushed to GitHub)
3. `COORDINATION_LOCAL_GPU.md` / `LOCAL_GPU_HANDOFF.md` — big GPU training that Hatch can't run (torch OOM) — claimed for local

**You MUST do this before you edit any file:**

```
1. Read `bundles/coordination/active-tasks.md` (or `COORDINATION.md` if you're outside Hatch)
2. If the area/file you want is claimed as `in-progress` or `claimed`, pick a different free lane
3. Claim it: add/change your row
   | your-name | repo / area | now CT | what you're doing + why | your-branch | in-progress |
4. Commit/push that claim so others see it (outside: push to that repo; inside: also update bundles/coordination/)
```

**How to work:**

- Branch per task: `scout/hoops-v6-fusion`, `local/unified-g2-gpu`, `pitch/mtnn-game` — NEVER push big work straight to main
- New models/assets = `*.candidate.json` or `*.candidate.pt` first — promote to real `vectors.json` / `eval_scoreboard.json` only when:
  - eval beats current + leak checks PASS + provenance note updated
  - `python -m json.tool` passes + tests pass
- Log even if no-op: "checked hoops composite 0.7937 still best, no-op" — so we know you looked
- Clear your row when done: change status to `done` or delete row, push

**Free lanes right now (check board for freshest):**
- vector-pitch / MTNN to game + difficulty retune (61%→92.9% done, needs push)
- vector-equities / README 0.174→0.7057 + forward IC eval (ready to push)
- vector-hub / daily 5th puzzle (unified chimera) + provenance checksums
- dottie / distilled reasoning optimizer traces→nano GRPO
- vector-unified / hoops / gridiron — CLAIMED for LOCAL-GPU (don't redo unless local agent says blocked)

**House rules both sides:**
- provenance-honest numbers only — cite source file in json
- never hide failures with hard-coded 0.0 wins — if blocked, document blocker
- keep main green, small atoms, pull often

**When done:**
Push branch → PR or fast-forward → update `COORDINATION.md` → mirror to `bundles/coordination/active-tasks.md` if you can

If unsure, ask: "who claimed X?" and check board first.

---

## One-liner for quick agents

> Before editing, read `COORDINATION.md` at repo root (and `bundles/coordination/active-tasks.md` if in Hatch), claim your lane with a row, work on your own branch, write `*.candidate.json` first, promote only when eval wins + tests pass, clear claim when done.

