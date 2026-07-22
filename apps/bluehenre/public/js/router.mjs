// Memory-router STUB (BLUEHENRE SPEC "Memory architecture").
// Honest placeholder for the target global-router + per-NPC vector stores:
// plain keyword overlap scoring into per-NPC memory buckets. It never claims
// to be semantic — `kind:"keyword-stub"` is stamped on every result so a later
// vector implementation is a visible upgrade, not a silent swap.

export function createRouter(npcIds) {
  const buckets = new Map();
  for (const id of npcIds) buckets.set(id, []);
  return { kind: "keyword-stub", buckets };
}

const tokenize = (s) =>
  String(s)
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length > 2);

/** Store an utterance in one NPC's bucket. */
export function remember(router, npcId, text) {
  const b = router.buckets.get(npcId);
  if (!b) throw new RangeError(`unknown npc ${npcId}`);
  b.push({ text: String(text), tokens: new Set(tokenize(text)) });
}

/** Score a query against every NPC's memories: token overlap, best-first.
 * Returns [{npcId, score, best}] with score 0 rows filtered out. */
export function route(router, query) {
  const q = new Set(tokenize(query));
  const out = [];
  for (const [npcId, mems] of router.buckets) {
    let score = 0;
    let best = null;
    for (const m of mems) {
      let s = 0;
      for (const t of q) if (m.tokens.has(t)) s++;
      if (s > score) ({ score, best } = { score: s, best: m.text });
    }
    if (score > 0) out.push({ npcId, score, best, kind: router.kind });
  }
  return out.sort((a, b) => b.score - a.score);
}

/** Run-end wipe: session memories are ephemeral (SPEC "reset loop"). */
export function wipe(router) {
  let n = 0;
  for (const b of router.buckets.values()) {
    n += b.length;
    b.length = 0;
  }
  return { wiped: n };
}
