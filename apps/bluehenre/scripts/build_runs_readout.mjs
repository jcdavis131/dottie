// Monitor readout exporter (the Dottie site — Pillar 3 "MONITOR").
// Read-only: reads the factory's committed eval reports and emits the static
// public/runs_readout.json the Monitor card renders — a W&B-style eval-RUN
// COMPARISON built from measured artifacts, not from the live feed.
//
// Provenance doctrine: every number here is recomputed from a committed report
// (token-weighted geometric mean of the per-phase held-out perplexities — the
// same math as twin.mjs parseEvalSummary). Each run carries its bin provenance:
//   DISJOINT    — held-out built with HELDOUT_SEED, disjoint from training (honest)
//   CONTAMINATED— held-out overlapped training (the retracted 275.95 / 4,103 era)
// A run whose report is unreadable or has no measured phase is SKIPPED, never
// filled in. The live current-run telemetry stays on the feed; this is history.
//
// Run: node apps/bluehenre/scripts/build_runs_readout.mjs [--check]

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = process.env.DOTTIE_ROOT ? resolve(process.env.DOTTIE_ROOT) : resolve(HERE, "..", "..", "..");
const REPORTS = join(ROOT, "apps", "ava-factory", "reports");
const OUT = join(HERE, "..", "public", "runs_readout.json");

// The curated run set, oldest checkpoint first. `bins` is the recorded provenance
// of the held-out set each run scored against — the whole point of the comparison.
const RUNS = [
  { file: "branch_eval_results_ext1_baseline.json", name: "step-1487 (tool_final_ext1)",
    bins: "CONTAMINATED", note: "the retracted 275.95 — tiny bins that overlapped training" },
  { file: "branch_eval_results_final2861_CONTAMINATED.json", name: "step-2861 (contaminated bins)",
    bins: "CONTAMINATED", note: "the retracted 4,103 — same contaminated 30k-token bins" },
  { file: "branch_eval_results_final2861_DISJOINT.json", name: "step-2861 (disjoint bins)",
    bins: "DISJOINT", note: "the first reliable number: 6.36M disjoint tokens, all 6 phases" },
];

const num = (v) => (Number.isFinite(v) ? v : null);

/** Parse a Python-written report (NaN literals for unmeasured phases). */
function readReport(path) {
  try {
    return JSON.parse(readFileSync(path, "utf-8").replace(/\bNaN\b/g, "null"));
  } catch {
    return null;
  }
}

/** Token-weighted geometric mean of per-phase ppl + the per-phase breakdown.
 * Only finite, measured phases count; nothing measured -> null (never faked). */
function summarize(report) {
  const ppl = report?.base?.perplexity;
  if (!ppl || typeof ppl !== "object") return null;
  let tokens = 0, ws = 0;
  const phases = [];
  for (const [phase, v] of Object.entries(ppl)) {
    if (!v || !Number.isFinite(v.ppl) || v.ppl <= 0 || !Number.isFinite(v.tokens) || v.tokens <= 0) continue;
    tokens += v.tokens;
    ws += Math.log(v.ppl) * v.tokens;
    phases.push({ phase: String(phase), ppl: v.ppl, tokens: v.tokens });
  }
  if (!tokens) return null;
  phases.sort((a, b) => a.phase.localeCompare(b.phase, undefined, { numeric: true }));
  return { weightedPpl: Math.exp(ws / tokens), tokens, phaseCount: phases.length, phases };
}

const rel = (p) => relative(ROOT, p).split("\\").join("/");
const sha12 = (buf) => createHash("sha256").update(buf).digest("hex").slice(0, 12);

function buildDoc() {
  const runs = [];
  for (const spec of RUNS) {
    const path = join(REPORTS, spec.file);
    if (!existsSync(path)) continue;           // absent report -> no phantom run
    const summary = summarize(readReport(path));
    if (!summary) continue;                     // unmeasured -> skipped, never filled in
    runs.push({
      name: spec.name, bins: spec.bins, note: spec.note,
      weighted_ppl: Number(summary.weightedPpl.toFixed(1)),
      tokens: summary.tokens, phase_count: summary.phaseCount,
      phases: summary.phases.map((p) => ({ phase: p.phase, ppl: Number(p.ppl.toFixed(1)), tokens: p.tokens })),
      source_path: rel(path), source_sha256short: sha12(readFileSync(path)),
    });
  }
  const honest = runs.filter((r) => r.bins === "DISJOINT");
  return {
    generated_by: "build_runs_readout.mjs",
    metric: "weighted held-out perplexity (token-weighted geometric mean over measured phases)",
    count: runs.length,
    // the headline: the only trustworthy number, and what it replaced
    headline: honest.length
      ? { weighted_ppl: honest.at(-1).weighted_ppl, tokens: honest.at(-1).tokens,
          run: honest.at(-1).name,
          retracted: runs.filter((r) => r.bins === "CONTAMINATED").map((r) => r.weighted_ppl) }
      : null,
    runs,
  };
}

const serialize = (doc) => JSON.stringify(doc, null, 2) + "\n";

function main() {
  const doc = buildDoc();
  const fresh = serialize(doc);
  const summary = `${doc.count} eval runs` + (doc.headline ? ` · honest ${doc.headline.weighted_ppl}` : "");
  if (process.argv.includes("--check")) {
    if (!existsSync(OUT)) {
      console.error(`STALE: ${rel(OUT)} missing — run without --check to build it`);
      process.exit(1);
    }
    if (readFileSync(OUT, "utf-8").replace(/\r\n/g, "\n") === fresh) {
      console.log(`fresh: ${rel(OUT)} matches the reports (${summary})`);
      process.exit(0);
    }
    console.error(`STALE: ${rel(OUT)} does not match the eval reports (${summary}) — rebuild and commit`);
    process.exit(1);
  }
  writeFileSync(OUT, fresh);
  console.log(`wrote ${rel(OUT)}: ${summary}`);
}

export { summarize };

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
