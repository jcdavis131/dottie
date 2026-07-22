/* Contract test for quests.mjs — steps gate on persona+action+location, in order,
   and completion is exact. Run: node public/js/quests.contract.test.mjs */
import { QUESTS, createQuestLog, advance, briefs, ORG } from "./quests.mjs";

let pass = 0, fail = 0;
const realCheck = (name, ok, extra = "") => {
  (ok ? pass++ : fail++);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

realCheck("all four doc pillars exist",
  ["archival_cipher", "performance_division", "design_sabotage", "hardware_heist"]
    .every((id) => QUESTS.some((q) => q.id === id)));
realCheck("every step is persona+action+location gated",
  QUESTS.every((q) => q.steps.every((s) => s.persona && s.action && s.dept && s.brief)));

const log = createQuestLog();
realCheck("fresh log has all briefs", briefs(log).length === QUESTS.length);

// wrong persona: nothing advances
const wrong = advance(log, { persona: "cipher", action: "interview", dept: "archives" });
realCheck("wrong persona does not advance", wrong.advanced.length === 0);

// out-of-order step 2 first: nothing advances
const early = advance(log, { persona: "cipher", action: "decode", dept: "archives" });
realCheck("later steps refuse to fire early", early.advanced.length === 0);

// correct sequence completes archival_cipher
const s1 = advance(log, { persona: "auditor", action: "interview", dept: "archives" });
realCheck("step 1 advances", s1.advanced.some((a) => a.quest === "archival_cipher"));
const s2 = advance(log, { persona: "cipher", action: "decode", dept: "archives" });
realCheck("step 2 completes the quest", s2.completed.includes("archival_cipher"));
realCheck("completed quest leaves the brief list",
  !briefs(log).some((b) => b.quest === "The Archival Cipher"));
realCheck("completion recorded once", log.completed.filter((q) => q === "archival_cipher").length === 1);

// a completed quest cannot re-fire
const again = advance(log, { persona: "cipher", action: "decode", dept: "archives" });
realCheck("completed quest is inert", again.advanced.length === 0 && again.completed.length === 0);

realCheck("org identity is bluehenre", ORG.name === "bluehenre" && ORG.values.length >= 3);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
