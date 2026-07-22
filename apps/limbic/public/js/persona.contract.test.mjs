/* Contract test for persona.mjs — hot-swap is terminal-gated, always explained.
   Run: node public/js/persona.contract.test.mjs */
import { PERSONAS, createPlayer, hotSwap } from "./persona.mjs";

let pass = 0, fail = 0;
const check = (name, ok, extra = "") => {
  (ok ? pass++ : fail++);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

check("three personas exist", Object.keys(PERSONAS).length === 3);
check("each persona names its ability",
  Object.values(PERSONAS).every((p) => typeof p.ability === "string" && p.ability));

const me = createPlayer();
check("default persona is auditor", me.persona === "auditor");

const offPad = hotSwap(me, "cipher", { onTerminal: false });
check("swap off-terminal refused with reason", !offPad.ok && /terminal/.test(offPad.reason));
check("refused swap does not change persona", me.persona === "auditor" && me.swaps === 0);

const onPad = hotSwap(me, "cipher", { onTerminal: true });
check("swap on terminal works", onPad.ok && me.persona === "cipher" && me.swaps === 1);

const same = hotSwap(me, "cipher", { onTerminal: true });
check("same-persona swap refused", !same.ok && me.swaps === 1);

const bogus = hotSwap(me, "wizard", { onTerminal: true });
check("unknown persona refused", !bogus.ok && /unknown/.test(bogus.reason));

let threw = false;
try { createPlayer("wizard"); } catch { threw = true; }
check("bad starting persona throws", threw);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
