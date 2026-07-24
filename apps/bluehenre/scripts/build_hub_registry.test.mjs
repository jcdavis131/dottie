// Regression test for build_hub_registry's frontmatter parser (bare node).
// Locks the fixes for the latent bugs found in adversarial review 2026-07-24:
// num_bytes between name/num_examples, nested-feature n_fields inflation,
// same-indent block sequences, flow-style lists, trailing-newline frontmatter.
//   node apps/bluehenre/scripts/build_hub_registry.test.mjs
import { frontmatter, list, splits, countTopLevelFeatures } from "./build_hub_registry.mjs";

let pass = 0, fail = 0;
const check = (name, ok) => { ok ? pass++ : fail++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}`); };

// dataset_info body (2-space indent, as the real cards and `datasets` emit).
// Splits carry num_bytes BEFORE num_examples; `answers` is a nested struct.
const di = [
  "  features:",
  "  - name: id",
  "    dtype: string",
  "  - name: answers",
  "    sequence:",
  "    - name: text",
  "      dtype: string",
  "    - name: start",
  "      dtype: int32",
  "  splits:",
  "  - name: train",
  "    num_bytes: 5000",
  "    num_examples: 100",
  "  - name: test",
  "    num_bytes: 500",
  "    num_examples: 20",
  "  provenance_classification: REAL",
].join("\n");

const sp = splits(di);
check("splits tolerate num_bytes between name and num_examples",
  sp.length === 2 && sp[0].num_examples === 100 && sp[1].num_examples === 20);
check("rows sum across multiple splits", sp.reduce((a, s) => a + s.num_examples, 0) === 120);
check("feature `- name:` lines never leak into splits", sp.every((s) => s.name === "train" || s.name === "test"));
check("nested struct sub-fields do NOT inflate n_fields (2 top-level, not 4)",
  countTopLevelFeatures(di) === 2);

// same-indent block sequence WITHOUT num_bytes (the current committed cards)
const diPlain = [
  "  features:",
  "  - name: a",
  "    dtype: int64",
  "  - name: b",
  "    dtype: string",
  "  splits:",
  "  - name: train",
  "    num_examples: 42",
  "  provenance_classification: HONEST-SYNTHETIC",
].join("\n");
check("plain same-indent card: 2 fields, 42 rows",
  countTopLevelFeatures(diPlain) === 2 && splits(diPlain)[0].num_examples === 42);

// flow-style list + quotes
const fmFlow = 'tags: [code, "dottie", nlp]\nlicense: mit\n';
check("flow-style list parses + strips quotes",
  JSON.stringify(list(fmFlow, "tags")) === JSON.stringify(["code", "dottie", "nlp"]));
check("block-style list still works", (() => {
  const b = "tags:\n- code\n- dottie\n";
  return JSON.stringify(list(b, "tags")) === JSON.stringify(["code", "dottie"]);
})());

// frontmatter with the closing --- as the last line (no trailing newline)
const cardNoNL = "---\npretty_name: X\nlicense: mit\n---";
check("frontmatter extracts even with no trailing newline after closing ---",
  frontmatter(cardNoNL).includes("pretty_name: X"));
check("frontmatter still extracts the normal (trailing-newline) form",
  frontmatter("---\na: 1\n---\n# body").trim() === "a: 1");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
