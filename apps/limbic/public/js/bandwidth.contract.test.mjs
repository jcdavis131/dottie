/* Contract test for bandwidth.mjs — the budget must gate actions honestly.
   Run: node public/js/bandwidth.contract.test.mjs */
import { createBandwidth, costOf, spend, tick, resetRun, REGEN_PER_TICK } from "./bandwidth.mjs";

let pass = 0, fail = 0;
const check = (name, ok, extra = "") => {
  (ok ? pass++ : fail++);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

// specialist discount applies only to the matching persona
check("interview costs auditor half", costOf("interview", "auditor") === 4);
check("interview costs cipher full", costOf("interview", "cipher") === 8);
check("decode costs cipher half", costOf("decode", "cipher") === 6);

// spending gates on remaining budget and never goes negative
const bw = createBandwidth(10);
check("spend within budget ok", spend(bw, "interview", "cipher").ok && bw.value === 2);
const denied = spend(bw, "decode", "auditor");
check("overdraft denied, no spend", !denied.ok && bw.value === 2, denied.reason);

// crossing to exactly 0 ends the run; further spends refuse
const bw2 = createBandwidth(8);
check("exact-zero spend ends run", spend(bw2, "interview", "cipher").ok && bw2.runOver);
check("post-run spend refused", !spend(bw2, "move_fast", "auditor").ok);

// regen is slow, capped, and dead after run end
const bw3 = createBandwidth(10);
spend(bw3, "interview", "auditor"); // -4 → 6
tick(bw3, 2);
check("regen adds per tick", Math.abs(bw3.value - (6 + 2 * REGEN_PER_TICK)) < 1e-9);
tick(bw3, 1000);
check("regen caps at max", bw3.value === 10);
check("no regen after run over", (tick(bw2, 100), bw2.value === 0));

// reset wipes the session but reports run stats
const stats = resetRun(bw2);
check("reset restores budget", bw2.value === bw2.max && !bw2.runOver);
check("reset reports spentTotal", stats.spentTotal === 8);

// bad inputs are refusals, not silence
let threw = 0;
try { costOf("juggle", "auditor"); } catch { threw++; }
try { createBandwidth(-5); } catch { threw++; }
check("unknown action + bad max throw", threw === 2);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
