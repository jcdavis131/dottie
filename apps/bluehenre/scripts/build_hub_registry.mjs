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
const OUT = join(HERE, "..", "public", "hub_registry.json");

const CLASSES = new Set(["REAL", "HONEST-SYNTHETIC", "PLACEHOLDER"]);

/** The `---`-delimited YAML frontmatter block of a markdown card, or "". */
function frontmatter(md) {
  const m = String(md).match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
  return m ? m[1] : "";
}

/** First `key: value` scalar in a block, trimmed, or null. Tolerates the
 * leading indentation of a nested key (e.g. provenance_classification under
 * dataset_info). */
function scalar(block, key) {
  const m = block.match(new RegExp(`^[ \\t]*${key}:[ \\t]*(.+?)[ \\t]*$`, "m"));
  return m ? m[1].trim() : null;
}

/** The `- item` list immediately under `key:` (until a non-list, non-blank
 * line at the same or lower indent). Returns [] when absent. */
function list(block, key) {
  const lines = block.split(/\r?\n/);
  const at = lines.findIndex((l) => new RegExp(`^${key}:[ \\t]*$`).test(l));
  if (at < 0) return [];
  const out = [];
  for (let i = at + 1; i < lines.length; i++) {
    const m = lines[i].match(/^[ \t]*-[ \t]+(.+?)[ \t]*$/);
    if (m) out.push(m[1].trim());
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

/** Sum of `num_examples:` under splits, plus the per-split rows. */
function splits(diBlock) {
  const out = [];
  const re = /-[ \t]*name:[ \t]*(.+?)[ \t]*\r?\n[ \t]*num_examples:[ \t]*(\d+)/g;
  let m;
  while ((m = re.exec(diBlock))) out.push({ name: m[1].trim(), num_examples: Number(m[2]) });
  return out;
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
  const cls = scalar(di, "provenance_classification") || scalar(fm, "provenance_classification");
  const classification = cls && CLASSES.has(cls) ? cls : null;
  const sp = splits(di);
  const nFields = (di.match(/-[ \t]*name:[ \t]*\S/g) ?? []).length - sp.length; // features minus splits
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

function main() {
  if (!existsSync(PROPOSALS)) {
    console.error(`no corpus_proposals dir at ${PROPOSALS}`);
    process.exit(1);
  }
  const records = [];
  for (const entry of readdirSync(PROPOSALS).sort()) {
    const dir = join(PROPOSALS, entry);
    if (!statSync(dir).isDirectory()) continue;
    const rec = buildRecord(dir, entry);
    if (rec) records.push(rec);
  }
  // Sorted by name for deterministic output; built_at stamped at run time.
  const doc = { generated_by: "build_hub_registry.mjs", count: records.length, datasets: records };
  writeFileSync(OUT, JSON.stringify(doc, null, 2) + "\n");
  console.log(`wrote ${rel(OUT)}: ${records.length} datasets ` +
    `(${records.map((r) => `${r.name}=${r.classification ?? "unclassified"}`).join(", ")})`);
}

main();
