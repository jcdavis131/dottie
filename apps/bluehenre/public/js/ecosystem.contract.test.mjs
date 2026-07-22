/* Contract test for ecosystem.mjs — circuits move NPCs, near pairs exchange memos,
   one memo per leg. Run: node public/js/ecosystem.contract.test.mjs */
import { createEcosystem, tickEcosystem, CIRCUIT_STOPS } from "./ecosystem.mjs";

let pass = 0, fail = 0;
const realCheck = (name, ok, extra = "") => {
  (ok ? pass++ : fail++);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

const depts = ["labs", "design", "finance", "archives", "servers", "hall", "gardens", "proving"];
const eco = createEcosystem(depts);
realCheck("one npc per location", eco.npcs.length === 8);
realCheck("npc ids carry their location", eco.npcs.every((n) => n.id === `${n.dept}-1`));
realCheck("every circuit has the fixed stop count",
  eco.npcs.every((n) => n.stops.length === CIRCUIT_STOPS));

const before = eco.npcs.map((n) => n.pos.slice());
tickEcosystem(eco, 0.5);
const moved = eco.npcs.filter((n, i) =>
  Math.hypot(n.pos[0] - before[i][0], n.pos[1] - before[i][1]) > 0.01);
realCheck("ticking moves npcs along their circuit", moved.length >= 6, `${moved.length}/8 moved`);

// run the sim long enough that everyone converges on the hub leg → memos flow
let exchanges = [];
for (let t = 0; t < 4000; t++) exchanges = exchanges.concat(tickEcosystem(eco, 0.05));
realCheck("inter-npc memos happen", exchanges.length > 0, `${exchanges.length} memos`);
realCheck("memo names both parties",
  exchanges.every((x) => x.a && x.b && x.memo.includes("sync")));
realCheck("no self-memos", exchanges.every((x) => x.a !== x.b));
// one memo per pair per leg: no immediate duplicate of the same pair in one tick
const firstTickPairs = tickEcosystem(eco, 0.05).map((x) => `${x.a}|${x.b}`);
realCheck("no duplicate pair in a single tick",
  new Set(firstTickPairsKey(firstTickPairs)).size === firstTickPairs.length);
function firstTickPairsKey(ps) { return ps; }

let threw = false;
try { createEcosystem(["solo"]); } catch { threw = true; }
realCheck("refuses a one-location campus", threw);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
