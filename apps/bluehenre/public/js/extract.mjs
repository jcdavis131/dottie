// P4 — validated workflow → curriculum shard (BLUEHENRE SPEC phase 4).
// Pure logic, shared by the server endpoint. Mirrors the factory datagen doc
// contract ({text, task_type, concept, phase, source}) so an operator can feed
// the output straight to the collector — but NOTHING here auto-ingests: shards
// are returned/written locally and the wiring into training is the operator's
// explicit act (SPEC "OUT of autonomous scope").

const QUEST_CONCEPTS = {
  archival_cipher: "archival_cipher",
  performance_division: "workflow_optimization",
  design_sabotage: "social_deduction",
  hardware_heist: "adversarial_testing",
};

/** Render one VALIDATED extraction (from workflow.extractRun) into curriculum-
 * shard docs — one per completed quest. Refuses unvalidated input loudly:
 * discarded transcripts must never leak into training data. */
export function toShards(extraction) {
  if (!extraction || extraction.validated !== true)
    throw new RangeError(
      `refusing to shard an unvalidated run (${extraction?.reason ?? "no extraction"})`);
  return extraction.quests.map((questId) => {
    const steps = extraction.events
      .map((e, i) => `  ${i + 1}. [${e.persona}] ${e.action}` +
        `${e.dept ? " @ " + e.dept : ""} -> ${e.ok ? "ok" : "FAILED"}` +
        `${e.note ? " (" + e.note + ")" : ""}`)
      .join("\n");
    const text =
      `### Task: complete the "${questId}" workflow on the bluehenre campus.\n\n` +
      `A player run (run #${extraction.runId}) demonstrated this workflow end to end ` +
      `(${extraction.stats.okCount}/${extraction.stats.total} actions succeeded):\n\n` +
      `${steps}\n\n` +
      `Validation: ${extraction.reason}.\n` +
      `Source: bluehenre/workflow — real recorded play, not synthetic narration.\n`;
    return {
      text,
      task_type: "tool_selection",
      concept: QUEST_CONCEPTS[questId] ?? questId,
      phase: "p3",
      source: "bluehenre/workflow",
    };
  });
}
