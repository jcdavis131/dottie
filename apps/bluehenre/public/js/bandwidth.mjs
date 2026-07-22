// Bandwidth — the per-run action budget (BLUEHENRE SPEC "Core mechanics").
// Pure logic: no DOM, no clock — the caller supplies ticks. Testable in bare node.

export const ACTION_COSTS = {
  // action: { defaultCost, cheapFor: persona that does it at half cost }
  interview: { cost: 8, cheapFor: "auditor" },
  decode: { cost: 12, cheapFor: "cipher" },
  replan: { cost: 12, cheapFor: "architect" },
  move_fast: { cost: 1, cheapFor: null }, // sprint tick
  hot_swap: { cost: 5, cheapFor: null },
};

export const REGEN_PER_TICK = 0.5;

export function createBandwidth(max = 100) {
  if (!(Number.isFinite(max) && max > 0)) throw new RangeError(`bad max ${max}`);
  return { max, value: max, spentTotal: 0, runOver: false };
}

export function costOf(action, persona) {
  const spec = ACTION_COSTS[action];
  if (!spec) throw new RangeError(`unknown action ${action}`);
  return spec.cheapFor === persona ? spec.cost / 2 : spec.cost;
}

/** Spend for an action. Returns {ok, cost} — ok:false (and no spend) if it
 * would cross zero; crossing to exactly 0 is allowed and ends the run. */
export function spend(bw, action, persona) {
  if (bw.runOver) return { ok: false, cost: 0, reason: "run over" };
  const cost = costOf(action, persona);
  if (cost > bw.value) return { ok: false, cost, reason: "insufficient bandwidth" };
  bw.value -= cost;
  bw.spentTotal += cost;
  if (bw.value === 0) bw.runOver = true;
  return { ok: true, cost };
}

/** Slow regen, capped at max. No-op once the run is over — resets are wipes, not refills. */
export function tick(bw, n = 1) {
  if (bw.runOver) return bw.value;
  bw.value = Math.min(bw.max, bw.value + REGEN_PER_TICK * n);
  return bw.value;
}

/** GTA-style reset: fresh budget, session wiped; only totals survive as run stats. */
export function resetRun(bw) {
  const stats = { spentTotal: bw.spentTotal };
  bw.value = bw.max;
  bw.spentTotal = 0;
  bw.runOver = false;
  return stats;
}
