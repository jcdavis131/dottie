// Hub Artifact Registry exporter (the Dottie site — Pillar 2 "HUB").
// Read-only: scans tasks/artifacts/corpus_proposals/<name>/ for HF-standard
// dataset cards (README.md frontmatter) + audit sidecars, computes each data
// file's sha256, and emits public/hub_registry.json — the static feed the Hub
// card renders. Deterministic, no network. Provenance doctrine: every field is
// lifted from the card/sidecar/file; nothing is invented. A card missing its
// provenance_classification is emitted with classification=null (rendered
// "unclassified"), never guessed.
//
// Run: node apps/bluehenre/scripts/build_hub_registry.mjs
//   (from repo root; or set DOTTIE_ROOT). Re-run whenever a card changes.

import { readFileSync, writeFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { join, dirname, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = process.env.DOTTIE_ROOT ? resolve(process.env.DOTTIE_ROOT) : resolve(HERE, "..", "..", "..");
const PROPOSALS = join(ROOT, "tasks", "artifacts", "corpus_proposals");
const MODELS = join(ROOT, "tasks", "artifacts", "model_cards");
const RESEARCH_MANIFEST = join(ROOT, "tasks", "artifacts", "research_reports.json");
const OUT = join(HERE, "..", "public", "hub_registry.json");

const CLASSES = new Set(["REAL", "HONEST-SYNTHETIC", "PLACEHOLDER"]);

/** The `---`-delimited YAML frontmatter block of a markdown card, or "". */
function frontmatter(md) {
  // tolerate a closing `---` with no trailing newline (last line of the file)
  const m = String(md).match(/^---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/);
  return m ? m[1] : "";
}

/** First `key: value` scalar in a block, trimmed, or null. Tolerates the
 * leading indentation of a nested key (e.g. provenance_classification under
 * dataset_info). */
function scalar(block, key) {
  const m = block.match(new RegExp(`^[ \\t]*${key}:[ \\t]*(.+?)[ \\t]*$`, "m"));
  return m ? m[1].trim() : null;
}

/** The list under `key:` — block style (`- item` lines) or flow style
 * (`key: [a, b]`). Quotes are stripped. Returns [] when absent. */
function list(block, key) {
  const lines = block.split(/\r?\n/);
  const at = lines.findIndex((l) => new RegExp(`^[ \\t]*${key}:`).test(l));
  if (at < 0) return [];
  const unquote = (s) => s.trim().replace(/^['"]|['"]$/g, "");
  const flow = lines[at].match(new RegExp(`^[ \\t]*${key}:[ \\t]*\\[(.*)\\][ \\t]*$`));
  if (flow) return flow[1].split(",").map(unquote).filter(Boolean);
  const out = [];
  for (let i = at + 1; i < lines.length; i++) {
    const m = lines[i].match(/^[ \t]*-[ \t]+(.+?)[ \t]*$/);
    if (m) out.push(unquote(m[1]));
    else if (lines[i].trim() === "") continue;
    else break; // next key at this level
  }
  return out;
}

/** The `dataset_info:` sub-block (to end of frontmatter). */
function datasetInfoBlock(fm) {
  const m = fm.match(/^dataset_info:[ \t]*\r?\n([\s\S]*)$/m);
  return m ? m[1] : "";
}

/** The indented sub-block under `key:` within a block (lines more-indented than
 * the `key:` line, stopping at the next same-or-shallower key). For splits: /
 * features:. */
function subBlock(block, key) {
  const lines = block.split(/\r?\n/);
  const at = lines.findIndex((l) => new RegExp(`^[ \\t]*${key}:[ \\t]*$`).test(l));
  if (at < 0) return "";
  const base = lines[at].match(/^[ \t]*/)[0].length;
  const out = [];
  for (let i = at + 1; i < lines.length; i++) {
    const l = lines[i];
    if (l.trim() === "") { out.push(l); continue; }
    const ind = l.match(/^[ \t]*/)[0].length;
    // a block-sequence may sit at the SAME indent as its key (valid YAML), so
    // keep same-indent list items; stop only at a non-list key at base or shallower
    if (ind > base || (ind === base && /^[ \t]*-/.test(l))) { out.push(l); continue; }
    break;
  }
  return out.join("\n");
}

/** Splits under dataset_info: one {name, num_examples} per `- name:` entry,
 * tolerant of an intervening `num_bytes:` (the HF-standard push_to_hub shape).
 * Scoped to the splits: sub-block so feature `- name:` lines never leak in. */
function splits(diBlock) {
  const block = subBlock(diBlock, "splits");
  const out = [];
  for (const entry of block.split(/\r?\n(?=[ \t]*-[ \t]*name:)/).filter((e) => /-[ \t]*name:/.test(e))) {
    const name = entry.match(/-[ \t]*name:[ \t]*(.+?)[ \t]*(?:\r?\n|$)/)?.[1];
    const ne = entry.match(/num_examples:[ \t]*(\d+)/)?.[1];
    if (name && ne !== undefined) out.push({ name: name.trim(), num_examples: Number(ne) });
  }
  return out;
}

/** Count TOP-LEVEL features under dataset_info. Nested struct/sequence
 * sub-fields (their own deeper `- name:`) do NOT inflate the count. */
function countTopLevelFeatures(diBlock) {
  const nameLines = subBlock(diBlock, "features").split(/\r?\n/)
    .filter((l) => /-[ \t]*name:[ \t]*\S/.test(l));
  if (!nameLines.length) return 0;
  const min = Math.min(...nameLines.map((l) => l.match(/^[ \t]*/)[0].length));
  return nameLines.filter((l) => l.match(/^[ \t]*/)[0].length === min).length;
}

/** The first paragraph under `## Dataset Summary`, whitespace-collapsed. */
function summary(md) {
  const m = String(md).match(/##[ \t]*Dataset Summary[ \t]*\r?\n+([\s\S]*?)(\r?\n\r?\n|\r?\n##)/);
  if (!m) return null;
  const p = m[1].replace(/\s+/g, " ").trim();
  return p.length > 320 ? p.slice(0, 319) + "…" : p;
}

/** From <name>_audit.md: generation date + the input source sha256s. */
function auditFacts(dir, name) {
  const path = join(dir, `${name}_audit.md`);
  if (!existsSync(path)) return { generated: null, source_sha256: [], sidecar_path: null };
  const md = readFileSync(path, "utf-8");
  const gen = md.match(/Generated[ \t]+(\d{4}-\d{2}-\d{2})/)?.[1] ?? null;
  const shas = [...md.matchAll(/sha256=([0-9a-f]{64})/g)].map((x) => x[1]);
  return { generated: gen, source_sha256: [...new Set(shas)], sidecar_path: rel(path) };
}

const rel = (p) => relative(ROOT, p).split("\\").join("/");
const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");

/** Data files a card declares via `configs: … data_files: … path:`. */
function dataFiles(fm, dir) {
  const paths = [...fm.matchAll(/path:[ \t]*(.+?)[ \t]*$/gm)].map((m) => m[1].trim());
  const out = [];
  for (const p of [...new Set(paths)]) {
    const full = join(dir, p);
    if (!existsSync(full)) { out.push({ name: p, bytes: null, sha256: null, missing: true }); continue; }
    const buf = readFileSync(full);
    out.push({ name: p, bytes: buf.length, sha256: sha256(buf) });
  }
  return out;
}

function buildRecord(dir, name) {
  const cardPath = join(dir, "README.md");
  if (!existsSync(cardPath)) return null;
  const md = readFileSync(cardPath, "utf-8");
  const fm = frontmatter(md);
  if (!fm) return null;
  const di = datasetInfoBlock(fm);
  const clsRaw = scalar(di, "provenance_classification") || scalar(fm, "provenance_classification");
  const cls = clsRaw ? clsRaw.toUpperCase() : null; // normalize case; still never a guess
  const classification = cls && CLASSES.has(cls) ? cls : null;
  const sp = splits(di);
  const nFields = countTopLevelFeatures(di); // top-level only; nested structs don't inflate
  return {
    name,
    kind: "dataset",
    pretty_name: scalar(fm, "pretty_name") || name,
    classification,               // null => "unclassified", never guessed
    license: scalar(fm, "license"),
    task_categories: list(fm, "task_categories"),
    tags: list(fm, "tags"),
    size_category: list(fm, "size_categories")[0] || null,
    rows: sp.reduce((a, s) => a + s.num_examples, 0) || null,
    splits: sp,
    n_fields: nFields > 0 ? nFields : null,
    summary: summary(md),
    card_path: rel(cardPath),
    data_files: dataFiles(fm, dir),
    audit: auditFacts(dir, name),
  };
}

/** A model card (model_cards/<name>/README.md) -> registry record, or null.
 * Same provenance doctrine as datasets: the honest eval renders, a retracted
 * number is carried EXPLICITLY (never dropped), classification is never guessed. */
function buildModelRecord(dir, name) {
  const cardPath = join(dir, "README.md");
  if (!existsSync(cardPath)) return null;
  const md = readFileSync(cardPath, "utf-8");
  const fm = frontmatter(md);
  if (!fm) return null;
  const mi = (fm.match(/^model_info:[ \t]*\r?\n([\s\S]*)$/m) || [, ""])[1];
  const clsRaw = scalar(mi, "provenance_classification") || scalar(fm, "provenance_classification");
  const cls = clsRaw ? clsRaw.toUpperCase() : null;
  const numOrNull = (s) => { const n = Number(s); return s != null && Number.isFinite(n) ? n : null; };
  return {
    name,
    kind: "model",
    pretty_name: scalar(fm, "pretty_name") || name,
    classification: cls && CLASSES.has(cls) ? cls : null,
    license: scalar(fm, "license"),
    tags: list(fm, "tags"),
    arch: {
      preset: scalar(mi, "base_preset"),
      dModel: numOrNull(scalar(mi, "d_model")),
      nLayers: numOrNull(scalar(mi, "n_layers")),
      nHeads: numOrNull(scalar(mi, "n_heads")),
      mlp: scalar(mi, "mlp"),
      jspaceSplit: scalar(mi, "jspace_split"),
      vocab: numOrNull(scalar(mi, "vocab_size")),
      maxContext: numOrNull(scalar(mi, "max_context")),
      paramsNote: scalar(mi, "params_note"),
    },
    eval: {
      metric: scalar(mi, "eval_metric"),
      value: numOrNull(scalar(mi, "eval_value")),
      tokens: numOrNull(scalar(mi, "eval_tokens")),
      method: scalar(mi, "eval_method"),
      retracted: scalar(mi, "eval_retracted"), // named, never silently dropped
    },
    summary: summary(md),
    card_path: rel(cardPath),
    audit: auditFacts(dir, name),
  };
}

/** Curated research reports (research_reports.json) -> registry records. Each
 * report's file is verified present and sha256-pinned; a report whose file is
 * missing is skipped (no phantom reports). Title/summary are the manifest's
 * editorial text — the provenance is the real committed file. */
function scanResearch() {
  if (!existsSync(RESEARCH_MANIFEST)) return [];
  let manifest;
  try { manifest = JSON.parse(readFileSync(RESEARCH_MANIFEST, "utf-8")); }
  catch { return []; }
  const reports = Array.isArray(manifest?.reports) ? manifest.reports : [];
  const out = [];
  for (const r of reports) {
    const p = typeof r?.path === "string" ? r.path : null;
    if (!p) continue;
    const full = join(ROOT, p);
    if (!existsSync(full)) continue; // must be a real committed file
    const buf = readFileSync(full);
    const base = p.split("/").pop();
    out.push({
      name: base.replace(/\.md$/, ""),
      kind: "research",
      title: typeof r.title === "string" ? r.title : base,
      report_type: typeof r.type === "string" ? r.type : "report",
      summary: typeof r.summary === "string" ? r.summary : null,
      card_path: p,
      integrity: { bytes: buf.length, sha256: sha256(buf) },
    });
  }
  return out;
}

/** Scan a dir of `<name>/README.md` cards, building each with `build`. */
function scanCards(baseDir, build) {
  if (!existsSync(baseDir)) return [];
  const out = [];
  for (const entry of readdirSync(baseDir).sort()) {
    const dir = join(baseDir, entry);
    if (!statSync(dir).isDirectory()) continue;
    const rec = build(dir, entry);
    if (rec) out.push(rec);
  }
  return out;
}

/** Build the registry doc from the current cards + manifest (no I/O beyond
 * reads). Deterministic — the same inputs always produce the same bytes. */
function buildDoc() {
  const datasets = scanCards(PROPOSALS, buildRecord);
  const models = scanCards(MODELS, buildModelRecord);
  const research = scanResearch();
  return {
    generated_by: "build_hub_registry.mjs",
    count: datasets.length + models.length + research.length,
    datasets, models, research,
  };
}

const serialize = (doc) => JSON.stringify(doc, null, 2) + "\n";

function main() {
  if (!existsSync(PROPOSALS)) {
    console.error(`no corpus_proposals dir at ${PROPOSALS}`);
    process.exit(1);
  }
  const doc = buildDoc();
  const fresh = serialize(doc);
  const summary = `${doc.datasets.length} datasets, ${doc.models.length} models, ${doc.research.length} research`;

  // --check: verify the committed registry is FRESH (matches the cards) without
  // writing. A stale registry would make the Hub render data that no longer
  // matches its source — a provenance-honesty violation. Use before deploy / CI.
  if (process.argv.includes("--check")) {
    if (!existsSync(OUT)) {
      console.error(`STALE: ${rel(OUT)} does not exist — run without --check to build it`);
      process.exit(1);
    }
    // normalize line endings: a Windows autocrlf checkout may store the committed
    // file as CRLF in the working tree while the exporter emits LF — compare content
    const committed = readFileSync(OUT, "utf-8").replace(/\r\n/g, "\n");
    if (committed === fresh) {
      console.log(`fresh: ${rel(OUT)} matches the cards (${summary})`);
      process.exit(0);
    }
    console.error(`STALE: ${rel(OUT)} does not match the current cards (${summary}) — ` +
      "re-run build_hub_registry.mjs and commit before deploying");
    process.exit(1);
  }

  writeFileSync(OUT, fresh);
  console.log(`wrote ${rel(OUT)}: ${summary}`);
}

// pure parser helpers, exported for the regression test (bare-node)
export { frontmatter, scalar, list, datasetInfoBlock, subBlock, splits, countTopLevelFeatures };

// run main() only when executed directly, never on import (the test imports the
// helpers and must NOT trigger a real registry write)
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
