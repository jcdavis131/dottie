// Contract tests for the release gate's pure assertions (bare node, no network).
// Plan: tasks/production_workflow.md. These lock the HONESTY contract — the
// reason this smoke is not a liveness check.
//   node apps/bluehenre/scripts/release_gate.test.mjs
import {
  checkRegistryMatch, checkAssistantHonest, checkRetractionMarked, combine,
  diffPaths, RETRACTED_PPL, VALID_ASSISTANT_SOURCES,
  discoverModules, SYNTAX_FLOOR,
} from "./release_gate.mjs";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

let pass = 0, fail = 0;
const check = (name, ok) => { ok ? pass++ : fail++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}`); };

// ---- registry drift: prod and repo must not silently diverge ---------------
const REG = JSON.stringify({ count: 2, built_at: "x", datasets: [1, 2], models: [], research: [] });

check("registry: identical passes", checkRegistryMatch(REG, REG).ok);
check("registry: CRLF vs LF still passes (Windows checkout, Linux server)",
  checkRegistryMatch(REG.replace(/\n/g, "\r\n"), REG).ok);
check("registry: surrounding whitespace ignored", checkRegistryMatch(`\n${REG}\n`, REG).ok);

const drifted = JSON.stringify({ count: 3, built_at: "y", datasets: [1, 2, 3], models: [], research: [] });
const d = checkRegistryMatch(drifted, REG);
check("registry: drift fails", !d.ok);
check("registry: drift NAMES the count delta (operator has to act on it)",
  d.problems.some((p) => p.includes(".count") && p.includes("3") && p.includes("2")));
check("registry: an added artifact reports its VALUE and <absent>, not type names",
  d.problems.some((p) => p.includes(".datasets[2]") && p.includes("3") && p.includes("<absent>")));
check("registry: empty served fails", !checkRegistryMatch("", REG).ok);
check("registry: non-JSON difference still fails cleanly (no throw)",
  !checkRegistryMatch("<html>404</html>", REG).ok);
check("registry: a 404 HTML body never passes as a registry",
  !checkRegistryMatch("<!doctype html><h1>Not Found</h1>", REG).ok);

// ---- deep drift: the real production case this gate caught ----------------
// bhenre.com served sha256/bytes computed on CRLF files while the repo had LF
// (ledger_retroflag 2380 vs 2344 — the .gitattributes incident). Every top-level
// count MATCHED, so the first version of the reporter said only "differs" and I
// had to write a diff by hand. That is the bug these rows lock.
const deepA = { count: 18, research: [{ name: "x", integrity: { bytes: 2380, sha256: "aaa" } }] };
const deepB = { count: 18, research: [{ name: "x", integrity: { bytes: 2344, sha256: "bbb" } }] };
const deep = checkRegistryMatch(JSON.stringify(deepA), JSON.stringify(deepB));
check("deep drift: fails even when every count matches", !deep.ok);
check("deep drift: names the exact field path",
  deep.problems.some((p) => p.includes(".research[0].integrity.bytes")));
check("deep drift: shows both values", deep.problems.some((p) => p.includes("2380") && p.includes("2344")));
check("deep drift: reports how many fields drifted", deep.problems[0].includes("2 field"));
check("diffPaths: identical -> no paths", diffPaths({ a: 1 }, { a: 1 }).length === 0);
check("diffPaths: nested value", diffPaths({ a: { b: 1 } }, { a: { b: 2 } })[0].path === ".a.b");
check("diffPaths: array index in the path", diffPaths({ a: [1, 2] }, { a: [1, 3] })[0].path === ".a[1]");
check("diffPaths: missing key is a diff", diffPaths({ a: 1 }, {}).length === 1);
check("diffPaths: type change is a diff", diffPaths({ a: 1 }, { a: "1" })[0].a === "number");
check("diffPaths: null vs object distinguished", diffPaths({ a: null }, { a: {} }).length === 1);
check("diffPaths: array length change is a diff", diffPaths([1], [1, 2]).length === 1);
check("diffPaths: long values are clipped in the message",
  checkRegistryMatch(JSON.stringify({ s: "z".repeat(80) }), JSON.stringify({ s: "y".repeat(80) }))
    .problems.some((p) => p.includes("...")));
check("diffPaths: guards against unbounded output",
  diffPaths(Array.from({ length: 500 }, (_, i) => i), Array.from({ length: 500 }, (_, i) => i + 1)).length <= 201);

// ---- assistant: the stamp is the contract ---------------------------------
check("assistant: [dottie] with a reply passes",
  checkAssistantHonest({ source: "dottie", reply: "step 1 ..." }).ok);
check("assistant: honest offline passes — it is a LEGITIMATE production state",
  checkAssistantHonest({ source: "offline", reply: "engine unreachable — reply withheld" }).ok);
check("assistant: offline is reported as a note, not a problem",
  checkAssistantHonest({ source: "offline", reply: "engine unreachable — reply withheld" })
    .notes.some((n) => n.includes("legitimate")));
check("assistant: missing source fails even on HTTP 200",
  !checkAssistantHonest({ reply: "sure, the loss is fine" }).ok);
check("assistant: an unknown stamp fails",
  !checkAssistantHonest({ source: "gpt", reply: "hi" }).ok);
check("assistant: empty reply fails — withheld must still SAY it is withheld",
  !checkAssistantHonest({ source: "offline", reply: "" }).ok);
check("assistant: non-object fails", !checkAssistantHonest("nope").ok);
check("assistant: array is not an object", !checkAssistantHonest([]).ok);
check("assistant: null fails", !checkAssistantHonest(null).ok);

// The load-bearing one: offline must WITHHOLD, never estimate.
const smuggled = checkAssistantHonest({
  source: "offline", reply: "engine unreachable, but loss was around 0.184 at step 3500",
});
check("assistant: offline reply smuggling a number FAILS", !smuggled.ok);
check("assistant: the smuggled number is named", smuggled.problems.some((p) => p.includes("3500") || p.includes("184")));
check("assistant: offline with small incidental digits still passes",
  checkAssistantHonest({ source: "offline", reply: "engine unreachable (attempt 2) — withheld" }).ok);
check("assistant: valid sources are exactly {dottie, offline}",
  JSON.stringify(VALID_ASSISTANT_SOURCES) === JSON.stringify(["dottie", "offline"]));

// ---- the anti-fabrication differentiator, executable ----------------------
check("retraction: absent number passes", checkRetractionMarked("ppl 2268 held-out", "d").ok);
check("retraction: marked occurrence passes",
  checkRetractionMarked(`the RETRACTED ${RETRACTED_PPL} is carried, do not cite it`, "d").ok);
check("retraction: 'superseded' also counts as a marker",
  checkRetractionMarked(`${RETRACTED_PPL} — superseded by 2268`, "d").ok);
check("retraction: BARE occurrence fails — it reads as a live metric",
  !checkRetractionMarked(`held-out perplexity: ${RETRACTED_PPL}`, "d").ok);
check("retraction: marker far away does NOT launder a bare occurrence",
  !checkRetractionMarked(`retracted note here.${"x".repeat(900)}ppl ${RETRACTED_PPL}`, "d").ok);
const two = checkRetractionMarked(`ok retracted ${RETRACTED_PPL} fine.${"y".repeat(900)}live ${RETRACTED_PPL}`, "d");
check("retraction: one marked + one bare still fails (per-occurrence, not per-doc)", !two.ok);
check("retraction: the failing occurrence is located by offset",
  two.problems.some((p) => p.includes("offset")));
check("retraction: non-text input fails cleanly", !checkRetractionMarked(null, "d").ok);

// ---- combine ---------------------------------------------------------------
const merged = combine([
  ["a", { ok: true, problems: [], notes: ["fine"] }],
  ["b", { ok: false, problems: ["broke"], notes: [] }],
]);
check("combine: any failure fails the whole gate", !merged.ok);
check("combine: problems are prefixed with their part", merged.problems[0] === "b: broke");
check("combine: notes survive", merged.notes[0] === "a: fine");
check("combine: all-pass passes", combine([["a", { ok: true, problems: [], notes: [] }]]).ok);
check("combine: empty passes (vacuous, but must not throw)", combine([]).ok);

// ---- module discovery: the syntax list used to be hardcoded ---------------
// It named 9 paths while the app ships 13, so build_runs_readout.mjs and the three test
// modules were never parsed — and it still reported "PASS syntax (9 modules)", which
// reads like coverage rather than a list that had quietly fallen behind.
const found = discoverModules();
check("discover: finds at least the floor", found.length >= SYNTAX_FLOOR);
check("discover: includes build_runs_readout.mjs (missed by the old hardcoded list)",
  found.includes("scripts/build_runs_readout.mjs"));
check("discover: includes the test modules the old list omitted",
  found.includes("scripts/release_gate.test.mjs") &&
  found.includes("public/js/twin.contract.test.mjs"));
check("discover: still finds top-level server.mjs", found.includes("server.mjs"));
check("discover: returns only .mjs", found.every((f) => f.endsWith(".mjs")));

// node_modules must be skipped, or discovery would parse the whole dependency tree and
// the floor would pass for reasons having nothing to do with this app's code.
const sandbox = mkdtempSync(join(tmpdir(), "rg-discover-"));
mkdirSync(join(sandbox, "node_modules", "pkg"), { recursive: true });
writeFileSync(join(sandbox, "node_modules", "pkg", "dep.mjs"), "export const x = 1;\n");
mkdirSync(join(sandbox, "src"), { recursive: true });
writeFileSync(join(sandbox, "src", "own.mjs"), "export const y = 2;\n");
writeFileSync(join(sandbox, "notes.txt"), "not a module\n");
const sandboxed = discoverModules(sandbox);
check("discover: skips node_modules", !sandboxed.some((f) => f.includes("node_modules")));
check("discover: finds nested own code", sandboxed.includes("src/own.mjs"));
check("discover: ignores non-.mjs files", sandboxed.length === 1);

// The floor is what stops an empty discovery printing a cheerful PASS having parsed
// nothing — the same shape the CI workflow was audited for on 2026-08-01.
check("discover: an empty tree returns [] so the floor can catch it",
  discoverModules(mkdtempSync(join(tmpdir(), "rg-empty-"))).length === 0);
check("floor sits below the real count, so ordinary adds do not churn it",
  SYNTAX_FLOOR < found.length);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
