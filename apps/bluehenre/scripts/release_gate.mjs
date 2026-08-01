// Release gate for the Dottie site — G1 PRE and G3 SMOKE.
// Plan of record: tasks/production_workflow.md.
//
// Why a bespoke smoke instead of a liveness check: this app's promise is
// provenance-honesty, so on bhenre.com an assistant answering
// {source:"offline", reply:"...withheld"} is CORRECT production behaviour, not an
// outage. A liveness smoke fails on it, someone disables the smoke, and a
// disabled gate protects nothing (the permanently-red lint.yml lesson). So this
// asserts the HONESTY CONTRACT — the thing whose violation is genuinely a defect:
//
//   1. the served hub_registry.json is byte-identical to the committed one
//      (prod and repo silently diverging = rendering data that does not match its
//      source, the exact violation `build_hub_registry.mjs --check` prevents
//      locally, but checked against what production actually serves);
//   2. every assistant reply carries a source stamp from the closed set
//      {dottie, offline} — unstamped is a failure even on HTTP 200;
//   3. the retracted 275.95 ppl appears ONLY beside a retraction marker, never as
//      a live metric — the anti-fabrication differentiator, executable;
//   4. an offline reply is well-formed and carries no fabricated number.
//
// Dynamic, not a checklist: the assistant assertion branches on whether the
// engine is reachable, because BOTH states are legitimate production states.
//
// Run: node apps/bluehenre/scripts/release_gate.mjs --pre
//      node apps/bluehenre/scripts/release_gate.mjs --post https://www.bhenre.com
//      node apps/bluehenre/scripts/release_gate.mjs --all  https://www.bhenre.com
// Exit 0 = gate passed. Exit 1 = do not promote.

import { readFileSync, existsSync, readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = resolve(HERE, "..");

// The retracted held-out perplexity. It is allowed to APPEAR — carrying it
// explicitly is the differentiator — but only next to a marker saying so.
export const RETRACTED_PPL = "275.95";
export const RETRACTION_MARKERS = ["retract", "do not cite", "do-not-cite", "superseded"];
export const VALID_ASSISTANT_SOURCES = ["dottie", "offline"];

// ---------------------------------------------------------------------------
// Pure assertions — no network, no fs. Each returns {ok, problems[], notes[]}.
// ---------------------------------------------------------------------------

const res = (problems = [], notes = []) => ({ ok: problems.length === 0, problems, notes });

/** Served registry must match the committed one byte-for-byte (after newline
 * normalisation — a Windows checkout must not fail a Linux-served file). */
export function checkRegistryMatch(servedText, committedText) {
  if (typeof servedText !== "string" || !servedText.trim())
    return res(["served registry is empty or not text"]);
  if (typeof committedText !== "string" || !committedText.trim())
    return res(["committed registry is empty or not text"]);
  const norm = (s) => s.replace(/\r\n/g, "\n").trim();
  if (norm(servedText) === norm(committedText))
    return res([], [`registry matches (${norm(committedText).length} bytes)`]);
  let served, committed;
  try {
    served = JSON.parse(servedText);
    committed = JSON.parse(committedText);
  } catch {
    return res(["served registry differs from committed and one of them is not valid JSON"]);
  }
  // Name WHERE it drifted. The first version only compared top-level counts and
  // array lengths, so the first real drift it caught in production reported
  // nothing but "differs" — every count matched and the divergence was four
  // fields deep (sha256/bytes on two artifacts). A diff that cannot point at the
  // field makes the operator go write the diff tool by hand, which is what
  // happened. Walk the whole structure and name the paths.
  const paths = diffPaths(served, committed);
  const problems = [
    `served registry differs from the committed hub_registry.json (${paths.length} field${paths.length === 1 ? "" : "s"})`,
  ];
  for (const { path, a, b } of paths.slice(0, 8))
    problems.push(`  ${path}: served=${clipVal(a)} committed=${clipVal(b)}`);
  if (paths.length > 8) problems.push(`  ...and ${paths.length - 8} more`);
  return res(problems);
}

const clipVal = (v) => {
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s === undefined ? "undefined" : s.length > 40 ? `${s.slice(0, 37)}...` : s;
};

/** Recursive field-level diff -> [{path, a, b}]. Order-sensitive on arrays,
 * which is correct here: the exporter emits deterministically, so a reordering
 * IS drift. */
export function diffPaths(a, b, path = "", out = []) {
  if (out.length > 200) return out; // pathological-input guard, not a silent cap
  const ta = Array.isArray(a) ? "array" : a === null ? "null" : typeof a;
  const tb = Array.isArray(b) ? "array" : b === null ? "null" : typeof b;
  if (ta !== tb) {
    // An added/removed artifact is the most likely real drift, so report the
    // VALUE that is present and mark the other side absent. Reporting type names
    // ("served=number committed=undefined") names the shape and hides the fact.
    if (ta === "undefined" || tb === "undefined")
      out.push({ path: path || ".", a: ta === "undefined" ? "<absent>" : a, b: tb === "undefined" ? "<absent>" : b });
    else out.push({ path: path || ".", a: ta, b: tb });
    return out;
  }
  if (ta === "object") {
    for (const k of [...new Set([...Object.keys(a), ...Object.keys(b)])].sort())
      diffPaths(a[k], b[k], `${path}.${k}`, out);
  } else if (ta === "array") {
    for (let i = 0; i < Math.max(a.length, b.length); i++)
      diffPaths(a[i], b[i], `${path}[${i}]`, out);
  } else if (a !== b) out.push({ path: path || ".", a, b });
  return out;
}

/** The assistant must stamp its source. Branches on which legitimate production
 * state it is in rather than demanding the engine be up. */
export function checkAssistantHonest(body) {
  if (body === null || typeof body !== "object" || Array.isArray(body))
    return res(["assistant response is not a JSON object"]);
  const { source, reply } = body;
  const problems = [], notes = [];
  if (!VALID_ASSISTANT_SOURCES.includes(source))
    problems.push(`source ${JSON.stringify(source)} is not one of ${VALID_ASSISTANT_SOURCES.join("|")} — an unstamped reply is a fabrication risk`);
  if (typeof reply !== "string" || !reply.trim())
    problems.push("reply is empty — withheld must still SAY it is withheld");
  if (source === "offline" && typeof reply === "string") {
    // An offline reply must not smuggle a number: withheld beats fabricated.
    const digits = reply.match(/\d[\d,.]*/g) || [];
    const suspicious = digits.filter((d) => d.replace(/\D/g, "").length >= 3);
    if (suspicious.length)
      problems.push(`offline reply contains number-like tokens ${JSON.stringify(suspicious)} — offline must withhold, not estimate`);
    notes.push("engine unreachable — honest-offline contract asserted (this is a legitimate production state)");
  }
  if (source === "dottie") notes.push("engine reachable — [dottie] stamp present");
  return res(problems, notes);
}

/** The retracted number may appear, but only beside a marker naming it retracted. */
export function checkRetractionMarked(text, label = "document") {
  if (typeof text !== "string") return res([`${label}: not text`]);
  const problems = [], notes = [];
  let idx = text.indexOf(RETRACTED_PPL), hits = 0;
  while (idx !== -1) {
    hits++;
    // Look in a window around the occurrence, not the whole document: a marker
    // 40 KB away does not make THIS occurrence honest.
    const window = text.slice(Math.max(0, idx - 400), idx + 400).toLowerCase();
    if (!RETRACTION_MARKERS.some((m) => window.includes(m)))
      problems.push(`${label}: ${RETRACTED_PPL} at offset ${idx} has no retraction marker within 400 chars — it reads as a live metric`);
    idx = text.indexOf(RETRACTED_PPL, idx + 1);
  }
  if (hits && !problems.length) notes.push(`${label}: ${RETRACTED_PPL} present ${hits}×, every occurrence marked retracted`);
  return res(problems, notes);
}

/** Merge results; the gate fails if any part failed. */
export function combine(named) {
  const problems = [], notes = [];
  for (const [name, r] of named) {
    for (const p of r.problems) problems.push(`${name}: ${p}`);
    for (const n of r.notes) notes.push(`${name}: ${n}`);
  }
  return res(problems, notes);
}

// ---------------------------------------------------------------------------
// G1 PRE — the README's three commands, plus syntax, as one exit-coded command.
// ---------------------------------------------------------------------------

// WAS a hardcoded list of nine paths while the app ships thirteen .mjs, so
// build_runs_readout.mjs and the three test modules were never parsed here. A hardcoded
// list does not fail when it falls behind — it silently checks less, and reports
// "PASS syntax (9 modules)", which reads like coverage. Discovered from disk instead so a
// new module is covered the day it lands.
//
// readdir rather than `git ls-files`: this gate must work from a deploy tarball or any
// checkout without git, and an unavailable git would otherwise turn into an empty list.
export const SYNTAX_FLOOR = 10;

export function discoverModules(root = APP) {
  const skip = new Set(["node_modules", ".git", ".vercel", "dist", "build"]);
  const out = [];
  (function walk(dir, rel) {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      if (skip.has(e.name)) continue;
      const abs = join(dir, e.name);
      const r = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) walk(abs, r);
      else if (e.name.endsWith(".mjs")) out.push(r);
    }
  })(root, "");
  return out.sort();
}

function run(label, args) {
  const r = spawnSync(process.execPath, args, { cwd: APP, encoding: "utf8" });
  const ok = r.status === 0;
  const tail = ((r.stdout || "") + (r.stderr || "")).trim().split("\n").slice(-2).join(" | ");
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${tail ? `  — ${tail}` : ""}`);
  return ok;
}

export function preGate() {
  console.log("G1 PRE\n------");
  let ok = true;
  ok = run("contract suite", ["public/js/twin.contract.test.mjs"]) && ok;
  ok = run("exporter parser test", ["scripts/build_hub_registry.test.mjs"]) && ok;

  // Dynamic: a STALE registry is recoverable, so rebuild and re-check before
  // failing a human who would just run the rebuild by hand. Still stale after a
  // rebuild means the exporter is broken — that IS a failure.
  let fresh = spawnSync(process.execPath, ["scripts/build_hub_registry.mjs", "--check"], { cwd: APP, encoding: "utf8" });
  if (fresh.status !== 0) {
    console.log("WARN  registry stale — rebuilding once, then re-checking");
    spawnSync(process.execPath, ["scripts/build_hub_registry.mjs"], { cwd: APP, encoding: "utf8" });
    fresh = spawnSync(process.execPath, ["scripts/build_hub_registry.mjs", "--check"], { cwd: APP, encoding: "utf8" });
    if (fresh.status === 0)
      console.log("PASS  registry freshness (REBUILT — commit public/hub_registry.json before deploying)");
    else { console.log("FAIL  registry still stale after rebuild — the exporter is broken"); ok = false; }
  } else console.log("PASS  registry freshness");

  // The Monitor readout, which CI checks and this gate did NOT — so `--pre` could print
  // "safe to promote" over a readout that no longer matched the eval reports it renders.
  // That is the one thing this app promises not to do, and `--pre` exists precisely so a
  // deploy needs no remembered sequence; a step only CI knew about defeats that.
  const readout = spawnSync(process.execPath, ["scripts/build_runs_readout.mjs", "--check"],
    { cwd: APP, encoding: "utf8" });
  if (readout.status === 0) console.log("PASS  runs readout freshness");
  else {
    const tail = ((readout.stdout || "") + (readout.stderr || "")).trim().split("\n").slice(-2).join(" | ");
    console.log(`FAIL  runs readout stale — rendered numbers disagree with the reports  — ${tail}`);
    ok = false;
  }

  const files = discoverModules();
  // A zero-length discovery would make every filter below vacuous and print a cheerful
  // PASS having parsed nothing — the exact shape this repo audited its CI for on
  // 2026-08-01. Floor sits below the current 13 so ordinary adds/removals do not churn it.
  if (files.length < SYNTAX_FLOOR) {
    console.log(`FAIL  syntax: discovered only ${files.length} modules (floor ${SYNTAX_FLOOR}) — discovery is broken`);
    ok = false;
  }
  const missing = files.filter((f) => !existsSync(join(APP, f)));
  if (missing.length) { console.log(`FAIL  syntax: missing ${missing.join(", ")}`); ok = false; }
  const bad = files.filter((f) => existsSync(join(APP, f)) &&
    spawnSync(process.execPath, ["--check", f], { cwd: APP, encoding: "utf8" }).status !== 0);
  if (bad.length) { console.log(`FAIL  syntax: ${bad.join(", ")}`); ok = false; }
  else if (!missing.length && files.length >= SYNTAX_FLOOR)
    console.log(`PASS  syntax (${files.length} modules, discovered)`);

  return ok;
}

// ---------------------------------------------------------------------------
// G3 SMOKE — assert the honesty contract against a deployed URL.
// ---------------------------------------------------------------------------

async function get(url, timeoutMs = 20_000) {
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(timeoutMs), redirect: "follow" });
    return { ok: true, status: r.status, text: await r.text() };
  } catch (e) { return { ok: false, status: 0, text: "", error: e.name }; }
}

export async function postGate(base) {
  const root = String(base).replace(/\/+$/, "");
  console.log(`\nG3 SMOKE  ${root}\n------`);
  const parts = [];
  let ok = true;

  const org = await get(`${root}/org.html`);
  if (org.status !== 200) { console.log(`FAIL  org.html HTTP ${org.status}${org.error ? ` (${org.error})` : ""}`); ok = false; }
  else {
    console.log(`PASS  org.html 200 (${org.text.length} bytes)`);
    parts.push(["org.html", checkRetractionMarked(org.text, "org.html")]);
  }

  const reg = await get(`${root}/hub_registry.json`);
  if (reg.status !== 200) { console.log(`FAIL  hub_registry.json HTTP ${reg.status}`); ok = false; }
  else {
    const committedPath = join(APP, "public", "hub_registry.json");
    parts.push(["registry", existsSync(committedPath)
      ? checkRegistryMatch(reg.text, readFileSync(committedPath, "utf8"))
      : res(["committed hub_registry.json not found — cannot compare"])]);
    parts.push(["registry-body", checkRetractionMarked(reg.text, "hub_registry.json")]);
  }

  // The assistant: POST and assert the stamp. A non-200 here IS a failure (the
  // honest-offline path returns 200 with source:"offline" by design), so a 5xx
  // means the function itself broke.
  try {
    const r = await fetch(`${root}/api/assistant-chat`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt: "release-gate smoke: report your source" }),
      signal: AbortSignal.timeout(25_000),
    });
    if (r.status !== 200) { console.log(`FAIL  /api/assistant-chat HTTP ${r.status} — the honest-offline path should still be 200`); ok = false; }
    else {
      let body = null;
      try { body = JSON.parse(await r.text()); } catch { /* handled below */ }
      parts.push(["assistant", body === null ? res(["response was not JSON"]) : checkAssistantHonest(body)]);
    }
  } catch (e) { console.log(`FAIL  /api/assistant-chat unreachable (${e.name})`); ok = false; }

  const merged = combine(parts);
  for (const n of merged.notes) console.log(`PASS  ${n}`);
  for (const p of merged.problems) console.log(`FAIL  ${p}`);
  return ok && merged.ok;
}

// ---------------------------------------------------------------------------

async function main() {
  const argv = process.argv.slice(2);
  const url = argv.find((a) => /^https?:\/\//.test(a));
  const wantPre = argv.includes("--pre") || argv.includes("--all");
  const wantPost = argv.includes("--post") || argv.includes("--all");
  if (!wantPre && !wantPost) {
    console.log("usage: release_gate.mjs --pre | --post <url> | --all <url>");
    process.exit(2);
  }
  let ok = true;
  if (wantPre) ok = preGate() && ok;
  if (wantPost) {
    if (!url) { console.log("FAIL  --post needs a URL"); process.exit(2); }
    ok = (await postGate(url)) && ok;
  }
  console.log(`\n${ok ? "GATE PASSED — safe to promote" : "GATE FAILED — do not move the alias"}`);
  process.exit(ok ? 0 : 1);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
