# LIMBIC — Dottie campus game (Phase-1 vertical slice)

Cel-shaded 3D browser slice of the LIMBIC campus (see [SPEC.md](./SPEC.md) — distilled from
the operator's design doc). Zero npm dependencies: three.js loads via import map at runtime,
the server is bare node.

## Run

```bash
node server.mjs                        # http://localhost:8321, NPCs offline-honest
DOTTIE_CHAT_URL=http://localhost:8100/app/api/chat node server.mjs   # NPCs answer via Dottie
```

Controls: **WASD** move · **Shift** sprint (spends bandwidth) · **E** persona ability at the
nearest NPC · **1/2/3** hot-swap persona *on a terminal pad* · **R** reset after run-over.

## Honesty doctrine

Same as the Dottie console webapp: every NPC line is tagged `[dottie]` (real engine reply)
or `[offline]` (no engine — the reply is withheld and says so). The memory router stamps
`keyword-stub` on every result — it never claims to be a vector store.

## Tests (bare node, like the webapp)

```bash
node public/js/bandwidth.contract.test.mjs
node public/js/persona.contract.test.mjs
node public/js/router.contract.test.mjs
```
