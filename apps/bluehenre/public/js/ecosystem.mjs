// P2 — closed-loop NPC ecosystem (BLUEHENRE SPEC phase 2).
// Pure logic: schedules + inter-NPC traffic. No THREE, no DOM, no wall-clock —
// the caller supplies dt ticks and (for tests) a deterministic rand. The 3D layer
// only reads `pos` to place meshes.
//
// Each NPC walks a fixed daily circuit: home location → the Great Hall (the social
// hub) → a peer location → home. When two NPCs stand near each other they exchange a
// memo, which the caller banks into BOTH memory buckets via the router — that is the
// "closed loop": NPC knowledge spreads through simulated org traffic, not authorial fiat.

export const CIRCUIT_STOPS = 3; // home → hub → peer (then wraps)

export function createEcosystem(depts, { spacing = 24 } = {}) {
  if (!Array.isArray(depts) || depts.length < 2) throw new RangeError("need >=2 departments");
  const hubIdx = Math.max(0, depts.findIndex((d) => d === "hall"));
  const npcs = depts.map((dept, i) => {
    const a = (i / depts.length) * Math.PI * 2;
    const home = [Math.cos(a) * spacing, Math.sin(a) * spacing];
    const peerIdx = (i + 1) % depts.length; // deterministic peer: next dept on the ring
    const pa = (peerIdx / depts.length) * Math.PI * 2;
    const ha = (hubIdx / depts.length) * Math.PI * 2;
    return {
      id: `${dept}-1`,
      dept,
      pos: home.slice(),
      stops: [home, [Math.cos(ha) * spacing * 0.4, Math.sin(ha) * spacing * 0.4],
              [Math.cos(pa) * spacing, Math.sin(pa) * spacing]],
      stop: 1,          // index of the stop currently walked toward (spawns AT home=0)
      speed: 2.0,
      met: new Set(),   // npc ids exchanged with at the CURRENT stop leg (reset on arrive)
    };
  });
  return { npcs, memos: 0 };
}

const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

/** Advance every NPC toward its current stop; on arrival move to the next stop.
 * Returns the list of {a, b, memo} exchanges that happened this tick — the caller
 * decides what to do with them (bank into router buckets, surface in-world, …). */
export function tickEcosystem(eco, dt) {
  const exchanges = [];
  for (const n of eco.npcs) {
    const target = n.stops[n.stop % CIRCUIT_STOPS];
    const d = dist(n.pos, target);
    if (d < 0.5) {
      n.stop = (n.stop + 1) % CIRCUIT_STOPS;
      n.met.clear(); // a new leg allows fresh exchanges
      continue;
    }
    n.pos[0] += ((target[0] - n.pos[0]) / d) * n.speed * dt;
    n.pos[1] += ((target[1] - n.pos[1]) / d) * n.speed * dt;
  }
  // inter-NPC traffic: near pairs exchange one memo per leg
  for (let i = 0; i < eco.npcs.length; i++) {
    for (let j = i + 1; j < eco.npcs.length; j++) {
      const a = eco.npcs[i], b = eco.npcs[j];
      if (dist(a.pos, b.pos) < 2.5 && !a.met.has(b.id) && !b.met.has(a.id)) {
        a.met.add(b.id);
        b.met.add(a.id);
        eco.memos += 1;
        exchanges.push({
          a: a.id, b: b.id,
          memo: `${a.dept} sync with ${b.dept}: status exchanged (memo #${eco.memos})`,
        });
      }
    }
  }
  return exchanges;
}
