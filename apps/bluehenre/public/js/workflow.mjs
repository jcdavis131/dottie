// P2/P4 — run workflow recorder + honest extraction (BLUEHENRE SPEC phases 2+4).
// Pure logic. Records what the player actually DID during a run; at run end,
// extraction decides validated vs discarded and says WHY. Only validated
// workflows become training-signal candidates — and even then they are written
// locally for the operator, never auto-ingested (SPEC "OUT of autonomous scope").

export function createRun(runId = 1) {
  return { runId, events: [], startedAtTick: 0, questsCompleted: [] };
}

/** Record one player action. outcome is the spend/quest result — recorded as-is,
 * failures included: a workflow that hides its failed steps is fabricated data. */
export function record(run, { action, persona, dept = null, ok, cost = 0, note = "" }) {
  if (!action || !persona || typeof ok !== "boolean")
    throw new RangeError("record needs action, persona, ok:boolean");
  run.events.push({ action, persona, dept, ok, cost, note });
}

export function recordQuestComplete(run, questId) {
  run.questsCompleted.push(questId);
}

/** Run-end extraction. A workflow is VALIDATED only when the run demonstrated a
 * complete capability: at least one quest line finished AND a majority of its
 * actions succeeded. Everything else is discarded WITH the reason — the reset
 * loop wipes it and nothing pretends otherwise. */
export function extractRun(run) {
  const total = run.events.length;
  const okCount = run.events.filter((e) => e.ok).length;
  const majorityOk = total > 0 && okCount / total > 0.5;
  const validated = run.questsCompleted.length > 0 && majorityOk;
  const reason = validated
    ? `quest(s) ${run.questsCompleted.join("+")} completed with ${okCount}/${total} actions ok`
    : run.questsCompleted.length === 0
      ? "no quest line completed — nothing proven, transcript discarded"
      : `only ${okCount}/${total} actions succeeded — too noisy to be signal`;
  return {
    runId: run.runId,
    validated,
    reason,
    quests: [...run.questsCompleted],
    events: [...run.events],
    stats: { total, okCount },
  };
}
