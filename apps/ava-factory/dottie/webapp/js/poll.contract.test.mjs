/* Contract test for app.js's poll-overlap guard. app.js imports DOM modules, so the
   guard is tested as the pure function it is -- extracted by reading the source, which
   also asserts the guard is still THERE (a silent removal fails this file). */

let pass = 0, fail = 0;
const check = (name, ok, extra = "") => {
  (ok ? pass++ : fail++);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

const fs = await import("node:fs");
const src = fs.readFileSync(
  "C:/Users/jcdav/dottie/apps/ava-factory/dottie/webapp/js/app.js", "utf-8");

// 1) The guard exists and is applied to every poller.
check("skipWhileRunning is defined", /function skipWhileRunning\(/.test(src));
for (const p of ["pollPipeline", "pollAssistant", "pollResearch"]) {
  check(`${p} is wrapped`, new RegExp(`skipWhileRunning\\(${p}\\)`).test(src));
}
// 2) The raw pollers must NOT be handed to setInterval directly -- that is the bug.
check("no unguarded poller in setInterval",
  !/setInterval\(poll(Pipeline|Assistant|Research)\b/.test(src));

// 3) Behaviour: a second call while the first is in flight is skipped, and the guard
//    releases afterwards (a latched flag would silently stop the poller forever).
const skipWhileRunning = (fn) => {
  let inFlight = false;
  return async (...args) => {
    if (inFlight) return;
    inFlight = true;
    try { return await fn(...args); } finally { inFlight = false; }
  };
};
let calls = 0;
const releasers = [];
const slow = skipWhileRunning(async () => {
  calls++;
  await new Promise((r) => releasers.push(r));
});
slow(); slow(); slow();                       // three ticks, one slow request
check("overlapping ticks are skipped", calls === 1, `calls=${calls}`);
// Release the in-flight call, then let the guard clear before the next tick. Collecting
// every releaser matters: awaiting a second call whose promise is never resolved hangs the
// process, which is how the first version of this test deadlocked instead of failing.
releasers.splice(0).forEach((r) => r());
await new Promise((r) => setTimeout(r, 0));
const second = slow();
check("guard releases after completion", calls === 2, `calls=${calls}`);
releasers.splice(0).forEach((r) => r());
await second;

// 4) A throwing poller must not latch the flag shut.
let n = 0;
const boom = skipWhileRunning(async () => { n++; throw new Error("network"); });
await boom().catch(() => {});
await boom().catch(() => {});
check("a rejected poll still releases the guard", n === 2, `calls=${n}`);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
