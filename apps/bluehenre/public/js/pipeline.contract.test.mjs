// Contract: the org builds the model ITSELF; the consultant only clears blockers.
import { createPipeline, tickPipeline, resolveBlocker, statusLine, STAGES, RETAINER } from "./pipeline.mjs";

let pass = 0, fail = 0;
const check = (name, ok, extra = "") => {
  ok ? pass++ : fail++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

// stage order is the doc's pipeline with a dept owner each
check("five owned stages in order",
  STAGES.map((s) => s.id).join(",") === "data,curate,train,eval,ship" &&
  STAGES.every((s) => s.dept && s.work > 0));

// no workers, no progress — the org does the work, not wall-clock
const idle = createPipeline(7);
tickPipeline(idle, 10, []);
check("no progress without the owning dept at post", idle.progress === 0);

// the owning dept at post drives progress; a WRONG dept does not
const p = createPipeline(7);
tickPipeline(p, 1, ["labs"]); // stage 0 is owned by servers
check("wrong dept working does nothing", p.progress === 0);
tickPipeline(p, 1, ["servers"]);
check("owning dept at post progresses", p.progress > 0);

// run until the first blocker raises; progress must then FREEZE
let events = [];
for (let i = 0; i < 500 && !p.blocker; i++) events.push(...tickPipeline(p, 0.5, ["servers", "archives", "labs", "proving", "design"]));
check("a seeded blocker raises", p.blocker !== null && events.some((e) => e.type === "blocked"));
const frozen = p.progress;
tickPipeline(p, 5, ["servers", "archives", "labs", "proving", "design"]);
check("blocked pipeline freezes", p.progress === frozen);

// resolution demands the right hat + fix + department, with honest reasons
const b = p.blocker;
const wrongDept = resolveBlocker(p, { persona: b.persona, action: b.action, dept: "hall" });
check("wrong department refused", !wrongDept.ok && wrongDept.reason.includes(b.dept));
const wrongHat = resolveBlocker(p, { persona: b.persona === "cipher" ? "auditor" : "cipher",
                                     action: "interview", dept: b.dept });
check("wrong hat refused", !wrongHat.ok);
const right = resolveBlocker(p, { persona: b.persona, action: b.action, dept: b.dept });
check("right consultant clears it + retainer", right.ok && right.retainer === RETAINER && p.blocker === null);

// full engagement: clearing every blocker ships the model
const full = createPipeline(3);
let shipped = false, stagesDone = 0;
for (let i = 0; i < 5000 && !shipped; i++) {
  const evs = tickPipeline(full, 0.5, ["servers", "archives", "labs", "proving", "design"]);
  for (const e of evs) {
    if (e.type === "blocked") {
      const r = resolveBlocker(full, { persona: e.persona, action: e.action, dept: e.dept });
      if (!r.ok) break;
    }
    if (e.type === "stage_done") stagesDone++;
    if (e.type === "shipped") shipped = true;
  }
}
check("cleared engagement ships the model", shipped && full.shipped && stagesDone === STAGES.length,
  `stages done ${stagesDone}`);

// determinism: same seed, same blocker schedule
const a1 = createPipeline(42), a2 = createPipeline(42);
check("same seed, same engagement",
  JSON.stringify(a1.stages.map((s) => s.blockers)) === JSON.stringify(a2.stages.map((s) => s.blockers)));

// status line is honest about the blocker
const st = createPipeline(7);
check("status names model + stage", statusLine(st).includes("DUMBMODEL-1"));
let threw = false;
try { createPipeline(NaN); } catch { threw = true; }
check("bad seed throws", threw);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
