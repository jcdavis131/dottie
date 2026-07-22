/* Contract test for extract.mjs — shards mirror the factory doc contract and
   unvalidated runs are refused. Run: node public/js/extract.contract.test.mjs */
import { toShards } from "./extract.mjs";
import { createRun, record, recordQuestComplete, extractRun } from "./workflow.mjs";

let pass = 0, fail = 0;
const realCheck = (name, ok, extra = "") => {
  (ok ? pass++ : fail++);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

const run = createRun(3);
record(run, { action: "interview", persona: "auditor", dept: "finance", ok: true, cost: 4 });
record(run, { action: "replan", persona: "architect", dept: "finance", ok: true, cost: 6 });
recordQuestComplete(run, "performance_division");
const shards = toShards(extractRun(run));

realCheck("one shard per completed quest", shards.length === 1);
const s = shards[0];
realCheck("shard matches the factory doc contract",
  typeof s.text === "string" && s.task_type === "tool_selection" &&
  typeof s.concept === "string" && s.phase === "p3" && s.source === "bluehenre/workflow");
realCheck("concept maps the pillar", s.concept === "workflow_optimization");
realCheck("text carries the real steps", s.text.includes("[auditor] interview @ finance") &&
  s.text.includes("[architect] replan @ finance"));
realCheck("text states provenance", s.text.includes("real recorded play"));

// refusal: an unvalidated extraction must throw, not silently emit training data
const bad = createRun(4);
record(bad, { action: "decode", persona: "cipher", dept: "servers", ok: false, cost: 6 });
let threw = false;
let msg = "";
try { toShards(extractRun(bad)); } catch (e) { threw = true; msg = e.message; }
realCheck("unvalidated run refused with the reason", threw && msg.includes("no quest"));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
