/* Contract test for workflow.mjs — extraction validates only proven runs and always
   says why. Run: node public/js/workflow.contract.test.mjs */
import { createRun, record, recordQuestComplete, extractRun } from "./workflow.mjs";

let pass = 0, fail = 0;
const realCheck = (name, ok, extra = "") => {
  (ok ? pass++ : fail++);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

// a good run: quest completed, most actions ok
const good = createRun(7);
record(good, { action: "interview", persona: "auditor", dept: "archives", ok: true, cost: 4 });
record(good, { action: "decode", persona: "cipher", dept: "archives", ok: true, cost: 6 });
record(good, { action: "decode", persona: "cipher", dept: "servers", ok: false, cost: 6, note: "denied" });
recordQuestComplete(good, "archival_cipher");
const g = extractRun(good);
realCheck("proven run validates", g.validated === true);
realCheck("validation reason is specific", g.reason.includes("archival_cipher") && g.reason.includes("2/3"));
realCheck("failures are kept in the transcript", g.events.some((e) => !e.ok));

// no quest completed → discarded, with the reason
const idle = createRun(8);
record(idle, { action: "interview", persona: "auditor", dept: "hall", ok: true, cost: 4 });
const i = extractRun(idle);
realCheck("questless run is discarded", i.validated === false && i.reason.includes("no quest"));

// quest completed but mostly failures → too noisy
const noisy = createRun(9);
record(noisy, { action: "decode", persona: "cipher", dept: "servers", ok: false, cost: 6 });
record(noisy, { action: "decode", persona: "cipher", dept: "servers", ok: false, cost: 6 });
record(noisy, { action: "decode", persona: "cipher", dept: "servers", ok: true, cost: 6 });
recordQuestComplete(noisy, "hardware_heist");
const n = extractRun(noisy);
realCheck("noisy run is discarded with the count", n.validated === false && n.reason.includes("1/3"));

let threw = false;
try { record(createRun(1), { action: "interview", persona: "auditor" }); } catch { threw = true; }
realCheck("record refuses missing ok flag", threw);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
