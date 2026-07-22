// Twin telemetry (BLUEHENRE SPEC "the Dottie digital twin").
// Pure logic shared by the local server and the game: parse the REAL factory's
// metrics/eval artifacts into the display model. Provenance doctrine applies:
// only a `source:"local"` status may show numbers; anything else is offline and
// says so — the twin never fabricates the state of the real model.

/** Last {"event":"step"} record of a metrics_*.jsonl text -> {step, lm, tokens}
 * or null. Garbage lines are skipped (the file interleaves many event types). */
export function parseMetricsTail(text) {
  let out = null;
  for (const line of String(text ?? "").split("\n")) {
    const l = line.trim();
    if (!l) continue;
    try {
      const d = JSON.parse(l);
      if (d.event === "step" && Number.isFinite(d.step))
        out = { step: d.step, lm: Number.isFinite(d.lm) ? d.lm : null,
                tokens: Number.isFinite(d.tokens) ? d.tokens : null };
    } catch { /* non-JSON or partial line — skip */ }
  }
  return out;
}

/** JSON.parse that survives Python-written NaN literals (the eval report has
 * them for unmeasured phases). NaN -> null, honestly absent. */
export function safeParseJson(text) {
  try {
    return JSON.parse(String(text).replace(/\bNaN\b/g, "null"));
  } catch {
    return null;
  }
}

/** Token-weighted held-out perplexity from branch_eval_results_real.json.
 * Only finite, measured phases count; nothing measured -> null. */
export function parseEvalSummary(report) {
  const ppl = report?.base?.perplexity;
  if (!ppl || typeof ppl !== "object") return null;
  let tokens = 0;
  let ws = 0;
  for (const v of Object.values(ppl)) {
    if (v && Number.isFinite(v.ppl) && v.ppl > 0 && Number.isFinite(v.tokens) && v.tokens > 0) {
      tokens += v.tokens;
      ws += Math.log(v.ppl) * v.tokens;
    }
  }
  return tokens ? { weightedPpl: Math.exp(ws / tokens), tokens } : null;
}

/** One-line board rendering of a twin status. Numbers ONLY when source is
 * "local"; every other source renders as an honest offline line. */
export function twinLine(status) {
  if (!status || status.source !== "local")
    return "REAL TWIN: offline — this build cannot see the training box";
  const bits = [];
  if (Number.isFinite(status.step)) bits.push(`step ${status.step}`);
  if (Number.isFinite(status.lm)) bits.push(`loss ${status.lm.toFixed(4)}`);
  if (Number.isFinite(status.weightedPpl)) bits.push(`heldout ppl ${status.weightedPpl.toFixed(1)}`);
  return `REAL TWIN (${status.model ?? "ava-mini"}): ${bits.length ? bits.join(" · ") : "no numbers yet"} [local]`;
}
