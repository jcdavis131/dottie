// Contract: the pure joystick math behind the mobile-first default input.
import { stickState, SPRINT_AT } from "./touch.mjs";

let pass = 0, fail = 0;
const check = (name, ok, extra = "") => {
  ok ? pass++ : fail++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

// deadzone: tiny drags do not move (thumb jitter must not walk the player)
const dz = stickState(4, 4, 56);
check("deadzone swallows jitter", dz.x === 0 && dz.z === 0 && dz.mag === 0 && !dz.sprint);

// at the deadzone EDGE movement starts from zero (no jump)
const edge = stickState(56 * 0.16, 0, 56);
check("deadzone edge starts smooth", edge.mag > 0 && edge.mag < 0.03, `mag=${edge.mag.toFixed(4)}`);

// direction preserved: pure up-screen drag = forward (-z), no x bleed
const up = stickState(0, -40, 56);
check("up-screen drag is forward", up.z < 0 && Math.abs(up.x) < 1e-9);

// clamped at the rim: dragging past the radius never exceeds unit magnitude
const far = stickState(500, 0, 56);
check("over-rim clamps to 1", Math.abs(far.mag - 1) < 1e-9 && Math.abs(far.x - 1) < 1e-9);

// sprint: full-ish deflection sprints, mid deflection walks
check("full deflection sprints", stickState(56, 0, 56).sprint === true);
const mid = stickState(28, 0, 56);
check("half deflection walks", mid.sprint === false, `mag=${mid.mag.toFixed(2)} < ${SPRINT_AT}`);

// diagonal magnitude equals axis magnitude at the same deflection (no diagonal boost)
const ax = stickState(40, 0, 56).mag;
const di = stickState(40 / Math.SQRT2, 40 / Math.SQRT2, 56).mag;
check("no diagonal speed boost", Math.abs(ax - di) < 1e-9);

// bad radius refuses loudly
let threw = false;
try { stickState(1, 1, 0); } catch { threw = true; }
check("bad radius throws", threw);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
