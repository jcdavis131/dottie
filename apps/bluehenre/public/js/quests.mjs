// P3 — the doc's four gameplay pillars as quest lines (BLUEHENRE SPEC phase 3).
// Pure logic: each quest is an ordered list of steps gated by persona + location.
// A step completes when the player performs the required ability as the required
// persona near an NPC of the required location. No skips, no partial credit.

export const QUESTS = [
  {
    id: "archival_cipher",
    label: "The Archival Cipher",
    steps: [
      { persona: "auditor", action: "interview", dept: "archives",
        brief: "interview the Legal Archives keeper about the sealed index" },
      { persona: "cipher", action: "decode", dept: "archives",
        brief: "decode the sealed index in the Legal Archives" },
    ],
  },
  {
    id: "performance_division",
    label: "The Performance Division",
    steps: [
      { persona: "auditor", action: "interview", dept: "finance",
        brief: "audit the Finance Towers' resource ledger" },
      { persona: "architect", action: "replan", dept: "finance",
        brief: "re-plan the compute allocation the audit exposed" },
    ],
  },
  {
    id: "design_sabotage",
    label: "The Design Sabotage",
    steps: [
      { persona: "auditor", action: "interview", dept: "design",
        brief: "probe the Design Studio for the planted brief" },
      { persona: "auditor", action: "interview", dept: "hall",
        brief: "cross-check the story in the Great Hall" },
    ],
  },
  {
    id: "hardware_heist",
    label: "The Hardware Heist",
    steps: [
      { persona: "cipher", action: "decode", dept: "servers",
        brief: "bypass the Server Farm badge logic" },
      { persona: "architect", action: "replan", dept: "servers",
        brief: "re-route the rack plan to expose the flaw" },
    ],
  },
];

export function createQuestLog() {
  return { progress: Object.fromEntries(QUESTS.map((q) => [q.id, 0])), completed: [] };
}

/** Feed one player event {persona, action, dept}. Returns what advanced:
 * {advanced:[{quest, step}], completed:[questId]} — both possibly empty. */
export function advance(log, event) {
  const advanced = [];
  const completed = [];
  for (const q of QUESTS) {
    const at = log.progress[q.id];
    if (at >= q.steps.length) continue; // already done
    const need = q.steps[at];
    if (need.persona === event.persona && need.action === event.action && need.dept === event.dept) {
      log.progress[q.id] = at + 1;
      advanced.push({ quest: q.id, step: at });
      if (log.progress[q.id] === q.steps.length) {
        log.completed.push(q.id);
        completed.push(q.id);
      }
    }
  }
  return { advanced, completed };
}

/** The next actionable brief per quest — the HUD's quest tracker. */
export function briefs(log) {
  return QUESTS.filter((q) => log.progress[q.id] < q.steps.length)
    .map((q) => ({ quest: q.label, next: q.steps[log.progress[q.id]].brief }));
}

/** bluehenre org identity, surfaced in-world (SPEC "org identity"). */
export const ORG = {
  name: "bluehenre",
  hq: "Austin, TX",
  mission: "ship autonomous organizations that audit themselves",
  vision: "every workflow a training signal; every campus a curriculum",
  values: ["provenance over polish", "refuse to fabricate", "ephemeral play, persistent signal"],
  platform: "dumbmodels.com (fictional public platform)",
};
