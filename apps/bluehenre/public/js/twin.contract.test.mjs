// Contract: the twin never fabricates the real model's state.
import { parseMetricsTail, safeParseJson, parseEvalSummary, twinLine } from "./twin.mjs";

let pass = 0, fail = 0;
const check = (name, ok, extra = "") => {
  ok ? pass++ : fail++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

// metrics tail: last step wins, other events + garbage skipped
const jsonl = [
  '{"event":"boot","pid":1}',
  '{"event":"step","step":100,"lm":0.5,"tokens":1000}',
  "not json at all",
  '{"event":"checkpoint","step":110}',
  '{"event":"step","step":120,"lm":0.42,"tokens":2000}',
].join("\n");
const tail = parseMetricsTail(jsonl);
check("last step event wins", tail?.step === 120 && tail?.lm === 0.42 && tail?.tokens === 2000);
check("empty text -> null", parseMetricsTail("") === null && parseMetricsTail(null) === null);
check("checkpoint-only text -> null", parseMetricsTail('{"event":"checkpoint","step":9}') === null);

// Python NaN literals survive parsing as null
const evalJson = safeParseJson('{"base":{"perplexity":{"0":{"ppl":100.0,"tokens":100},"3":{"ppl":NaN,"tokens":0}}}}');
check("NaN literals parse to null", evalJson !== null && evalJson.base.perplexity["3"].ppl === null);
check("broken json -> null, no throw", safeParseJson("{nope") === null);

// weighted ppl: only measured phases count; math is token-weighted geometric mean
const sum = parseEvalSummary({ base: { perplexity: {
  a: { ppl: 100, tokens: 100 }, b: { ppl: 400, tokens: 100 }, c: { ppl: null, tokens: 0 },
} } });
check("weighted ppl is geometric mean", Math.abs(sum.weightedPpl - 200) < 1e-9, `got ${sum?.weightedPpl}`);
check("nothing measured -> null", parseEvalSummary({ base: { perplexity: { a: { ppl: null, tokens: 0 } } } }) === null);

// rendering: numbers ONLY for source:"local"
check("offline renders honestly", twinLine({ source: "offline" }).includes("offline"));
check("missing status renders honestly", twinLine(null).includes("offline"));
const line = twinLine({ source: "local", model: "ava-mini/tool", step: 1487, lm: 0.1508, weightedPpl: 275.95 });
check("local renders step+loss+ppl", line.includes("1487") && line.includes("0.1508") && line.includes("276.0") === false && line.includes("275.9"));
check("hosted status with numbers but wrong source stays offline",
  twinLine({ source: "proxy?", step: 999 }).includes("offline"));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
