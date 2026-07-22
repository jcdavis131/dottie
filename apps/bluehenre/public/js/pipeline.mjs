// The Project — the org's model-build pipeline (BLUEHENRE SPEC "The Project").
// Pure logic: no THREE, no DOM, no wall-clock. The org BUILDS THE MODEL itself —
// a stage progresses only while its owning department's NPC is at their post —
// and the consultant's job is clearing the seeded blockers that stall it.

export const MODEL = "DUMBMODEL-1";

export const STAGES = [
  { id: "data", label: "Collect data", dept: "servers", work: 30 },
  { id: "curate", label: "Curate corpus", dept: "archives", work: 30 },
  { id: "train", label: "Train", dept: "labs", work: 45 },
  { id: "eval", label: "Evaluate", dept: "proving", work: 30 },
  { id: "ship", label: "Ship", dept: "design", work: 20 },
];

// consultant hats (persona keys/abilities are the game's existing ones)
const HATS = [
  { persona: "auditor", action: "interview" },
  { persona: "cipher", action: "decode" },
  { persona: "architect", action: "replan" },
];

const BLOCKER_FLAVOR = {
  data: ["collector stalled on a rate limit", "raw shard checksum mismatch"],
  curate: ["data drift in the dedupe pass", "license flag on a source batch"],
  train: ["loss spike at the curriculum switch", "OOM on the long-context phase"],
  eval: ["eval harness flake — probes disagree", "held-out set contamination scare"],
  ship: ["release gate red: provenance doc missing", "rollback plan unsigned"],
};

// deterministic PRNG (mulberry32) — same seed, same engagement
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Work rate in units/sec while the owning dept's NPC is at their post. */
export const WORK_RATE = 1.6;
/** Bandwidth refund for clearing a blocker — the consulting retainer. */
export const RETAINER = 15;

export function createPipeline(seed = 1) {
  if (!Number.isFinite(seed)) throw new RangeError(`bad seed ${seed}`);
  const r = rng(seed);
  const stages = STAGES.map((s) => {
    const flavors = BLOCKER_FLAVOR[s.id];
    const n = 1 + (r() < 0.5 ? 1 : 0); // 1-2 blockers per stage
    const blockers = [];
    for (let i = 0; i < n; i++) {
      const hat = HATS[Math.floor(r() * HATS.length)];
      blockers.push({
        at: n === 1 ? 0.55 : 0.35 + i * 0.35, // progress fraction that raises it
        dept: s.dept,
        persona: hat.persona,
        action: hat.action,
        label: flavors[i % flavors.length],
        resolved: false,
      });
    }
    return { ...s, blockers };
  });
  return { model: MODEL, seed, stage: 0, progress: 0, stages, blocker: null, shipped: false };
}

/** Advance the pipeline. workingDepts = dept ids whose NPC is at their post this
 * tick (the caller derives this from the ecosystem). Returns events:
 * {type:"blocked"|"stage_done"|"shipped", ...}. No progress while blocked or shipped
 * — the org waits on its consultant. */
export function tickPipeline(pl, dt, workingDepts) {
  if (pl.shipped || pl.blocker) return [];
  const events = [];
  const s = pl.stages[pl.stage];
  const working = Array.isArray(workingDepts)
    ? workingDepts.includes(s.dept)
    : workingDepts?.has?.(s.dept) ?? false;
  if (!working) return events;

  pl.progress += WORK_RATE * dt;

  // does this progress cross an unresolved blocker threshold?
  const next = s.blockers.find((b) => !b.resolved && pl.progress / s.work >= b.at);
  if (next) {
    pl.blocker = next;
    events.push({ type: "blocked", stage: s.id, dept: next.dept,
                  persona: next.persona, action: next.action, label: next.label });
    return events;
  }

  if (pl.progress >= s.work) {
    events.push({ type: "stage_done", stage: s.id });
    pl.stage += 1;
    pl.progress = 0;
    if (pl.stage >= pl.stages.length) {
      pl.shipped = true;
      events.push({ type: "shipped", model: pl.model });
    }
  }
  return events;
}

/** The consultant attempts to clear the active blocker with {persona, action, dept}.
 * All three must match — right hat, right fix, right department. Honest reasons. */
export function resolveBlocker(pl, { persona, action, dept }) {
  const b = pl.blocker;
  if (!b) return { ok: false, reason: "no active blocker" };
  if (dept !== b.dept) return { ok: false, reason: `wrong department — this blocker lives in ${b.dept}` };
  if (persona !== b.persona || action !== b.action)
    return { ok: false, reason: `needs the ${b.persona}'s ${b.action}, not ${persona}/${action}` };
  b.resolved = true;
  pl.blocker = null;
  return { ok: true, retainer: RETAINER };
}

/** Compact HUD line: stage, %, blocker if any. */
export function statusLine(pl) {
  if (pl.shipped) return `${pl.model} SHIPPED`;
  const s = pl.stages[pl.stage];
  const pct = Math.min(99, Math.floor((pl.progress / s.work) * 100));
  return pl.blocker
    ? `${pl.model} ${s.label} ${pct}% BLOCKED: ${pl.blocker.label} → ${pl.blocker.persona}/${pl.blocker.action} @ ${pl.blocker.dept}`
    : `${pl.model} ${s.label} ${pct}%`;
}
