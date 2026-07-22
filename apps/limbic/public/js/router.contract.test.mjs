/* Contract test for router.mjs — the memory stub must self-identify and wipe clean.
   Run: node public/js/router.contract.test.mjs */
import { createRouter, remember, route, wipe } from "./router.mjs";

let pass = 0, fail = 0;
const realCheck = (name, ok, extra = "") => {
  (ok ? pass++ : fail++);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

const r = createRouter(["archive-1", "safety-1"]);
realCheck("stub self-identifies", r.kind === "keyword-stub");

remember(r, "archive-1", "the cipher key lives in the cold archive vault");
remember(r, "safety-1", "safety review gates every hardware heist");

const hits = route(r, "where is the archive cipher key?");
realCheck("routes to the right npc", hits.length >= 1 && hits[0].npcId === "archive-1");
realCheck("hit carries stub provenance", hits.every((h) => h.kind === "keyword-stub"));
realCheck("irrelevant npc filtered", !hits.some((h) => h.npcId === "safety-1" && h.score === 0));

const none = route(r, "zzz qqq xxx");
realCheck("no-overlap query returns empty", none.length === 0);

let threw = false;
try { remember(r, "ghost-9", "boo"); } catch { threw = true; }
realCheck("unknown npc refuses", threw);

const w = wipe(r);
realCheck("wipe counts and clears", w.wiped === 2 && route(r, "archive cipher").length === 0);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
