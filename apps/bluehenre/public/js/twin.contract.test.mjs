// Contract: the twin never fabricates the real model's state.
import { parseMetricsTail, safeParseJson, parseEvalSummary, twinLine,
         parseTrainerTail, parseDashboard, parseLiveEvents, liveAgeS, parseHub } from "./twin.mjs";

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

// ---- live pipeline feed (rung 3 + dashboard) --------------------------------
// both shapes: the bare /pipeline/status object and the gist's {pipeline:{...}}
const pipelineObj = {
  ts: 1000, preset: "mini",
  mode: { id: "stale", label: "Trainer stale", detail: "No trainer activity for 38906s" },
  watch: {
    run_progress: { frac: 0.8552, tokens_done: 2137973120, tokens_total: 2500000000 },
    phase_progress: { phase: 3, name: "p3_reasoning", short: "reasoning", frac: 0.9699, seq: 2048 },
    timing: { tok_s: 10943.5, eta_remaining_s: 33081.5 },
  },
  flow: {
    data_state: "READY", data_detail: "phase 3: 3163M tokens ready",
    collector_pause: { paused: true, reason: "packed runway 3.16B tokens >= max 3.00B" },
    gates: [
      { id: "D1", name: "host free", ok: true, value: "48.2 GB", target: ">= 12 GB" },
      { id: "D3", name: "collectors", ok: false, value: "paused", target: "not disk-paused" },
    ],
  },
  disk: { free_gb: 48.19, low_water_gb: 12, critical_gb: 6, below_low_water: false, below_critical: false },
  manifest: { funnel: { raw: 1, curating: 0, packed: 1002, training: 0, consumed: 37, failed: 1 } },
  ckpt: { files: [{ name: "base_final.pt", age_s: 330561 }] },
  trainer: {
    last: { event: "step", step: 1480, lm: 0.1508, tokens: 2137973120 },
    series: { step: [1460, 1470, 1480], lm_loss: [0.1512, 0.1509, 0.1508] },
  },
};
const wrapped = { schema: "dottie_live_status/v2", published_utc: "2026-07-22T14:20:02Z", pipeline: pipelineObj };

const tailLive = parseTrainerTail(pipelineObj);
check("trainer tail from bare endpoint shape", tailLive?.step === 1480 && tailLive?.tokens === 2137973120);
check("trainer tail from wrapped gist shape", parseTrainerTail(wrapped)?.step === 1480);
check("trainer tail of nothing -> null", parseTrainerTail(null) === null && parseTrainerTail({}) === null);

const dash = parseDashboard(wrapped);
check("dashboard carries mode + run + phase + timing",
  dash?.mode?.id === "stale" && Math.abs(dash?.run?.frac - 0.8552) < 1e-9 &&
  dash?.phase?.short === "reasoning" && dash?.timing?.tokS === 10943.5);
check("dashboard gates + funnel + ckpt age survive",
  dash?.gates?.length === 2 && dash?.funnel?.packed === 1002 && dash?.ckptAgeS === 330561);
check("dashboard sparkline pairs steps with losses",
  dash?.spark?.steps.join(",") === "1460,1470,1480" && dash?.spark?.lm[2] === 0.1508);
check("dashboard of nothing -> null", parseDashboard(null) === null && parseDashboard({}) === null);

// REAL events: a stale trainer is an event; a benign full-runway pause is not
const events = parseLiveEvents(wrapped);
check("stale trainer raises a labs event with the feed's own words",
  events.some((e) => e.kind === "mode_stale" && e.dept === "labs" &&
    e.persona === "cipher" && e.label.includes("38906s")));
check("full-runway collector pause is NOT an event (healthy backpressure)",
  !events.some((e) => e.kind === "gate_D3"));
const angry = JSON.parse(JSON.stringify(pipelineObj));
angry.mode = { id: "training", label: "Training" };
angry.flow.data_state = "STARVED";
angry.flow.collector_pause = { paused: true, reason: "disk pressure" };
angry.disk.below_low_water = true;
const angryEvents = parseLiveEvents(angry);
check("healthy mode raises no mode event", !angryEvents.some((e) => e.kind.startsWith("mode_")));
check("data STARVED -> servers event", angryEvents.some((e) => e.kind === "data_starved" && e.dept === "servers"));
check("disk low -> finance event", angryEvents.some((e) => e.kind === "disk_low" && e.dept === "finance"));
check("non-benign collector pause -> gate event", angryEvents.some((e) => e.kind === "gate_D3"));
check("no feed -> no events, no throw", parseLiveEvents(null).length === 0);

// hub panels: real blocks parse, unreachable blocks vanish, nothing invents
const hubFeed = {
  hub: {
    network: { architecture: { preset: "mini", d_model: 768, n_heads: 12, n_layers: 12,
      n_text: 3, n_fusion: 6, n_reasoning: 3, params_analytic: 171283072, mlp: "swiglu" } },
    ecosystem: { agenticos: { built: 8, total: 8 },
      skills: { total: 76, agenticos_own: 9 },
      agent_eval: { results: [{ model: "ava_nano-chat", tasks: 1, success: 0 }] } },
    eval_report: { report_markdown: "# Report\nPreset: mini | Wall: 421.02s\n| a | PASS |\n| b | FAIL |\n| c | PASS |" },
    agent_eval: { scoreboard_markdown: "| model |" },
    eval_catalog: { unreachable: "TimeoutError", url: "x" },
  },
  research: { ts: 1784598101, baseline: { metric_name: "factory_lm_loss", metric_value: 5.73733,
      metric_sem: 0.099092, provenance: "calibrated" },
    counts: { pending: 2, sota: 3, rejected: 19 } },
};
const hb = parseHub(hubFeed);
check("hub network panel parses arch", hb?.network?.params === 171283072 &&
  hb.network.split === "3T/6F/3R" && hb.network.preset === "mini");
check("hub ecosystem panel parses tools+skills+agent-eval",
  hb?.ecosystem?.toolsBuilt === 8 && hb.ecosystem.skillsTotal === 76 &&
  hb.ecosystem.agentEval[0].model === "ava_nano-chat");
check("hub evals panel counts verdicts from the real report",
  hb?.evals?.pass === 2 && hb.evals.fail === 1 && Math.abs(hb.evals.wallS - 421.02) < 1e-9);
check("hub research panel lifts baseline + counts + ts",
  hb?.research?.value === 5.73733 && hb.research.provenance === "calibrated" &&
  hb.research.sota === 3 && hb.research.ts === 1784598101);
// batch sample: real decoded training text passes through verbatim (clipped);
// unreachable probes and text-less blocks parse to null — never fabricated
const sampleHub = parseHub({ hub: { batch_sample: {
  shard: "synth_gaia2-3082f1f3737325aa", source: "synth_gaia2", phase: 4,
  state: "CLAIMED_TRAIN", docs_in_shard: 36675, doc_id: "synth_gaia2:910",
  task_type: "temporal", doc_tokens: 2153, shown_tokens: 160,
  text: "Universe: Startup Ops. Goal: set up a handoff call with Alex.",
} } });
check("batch sample parses the claimed shard's real doc",
  sampleHub?.sample?.source === "synth_gaia2" && sampleHub.sample.phase === 4 &&
  sampleHub.sample.taskType === "temporal" && sampleHub.sample.docTokens === 2153 &&
  sampleHub.sample.text.startsWith("Universe: Startup Ops."));
check("unreachable or text-less batch sample -> null",
  parseHub({ hub: { batch_sample: { unreachable: "x" } } })?.sample == null &&
  parseHub({ hub: { batch_sample: { shard: "s" } } })?.sample == null);
const siteHub = parseHub({ hub: { sites: [
  { name: "hub", url: "https://dumbmodel.com", http: 200, ms: 120, up: true },
  { name: "pitch", url: "https://pitch.jcamd.com", http: 503, ms: 900, up: false },
], site_history: {
  hub: [{ t: 1, up: true, ms: 100 }, { t: 2, up: false, ms: 0 }, { t: 3, up: true, ms: 120 },
        { t: 4, up: true, ms: 110 }],
} } });
const perfHub = parseHub({ hub: { site_perf: {
  measured_at: 1784750000,
  rows: [{ name: "hub", ttfb_ms: 200, page_bytes: 27000 }],
  regressions: [{ name: "hub", metric: "ttfb_ms", label: "hub TTFB regressed 34% (200 -> 268)" }],
} } });
check("weekly site-perf parses with regression labels",
  perfHub?.sitePerf?.measuredAt === 1784750000 && perfHub.sitePerf.rows.length === 1 &&
  perfHub.sitePerf.regressions[0].includes("34%"));
const depHub = parseHub({ hub: { deploys: { projects: [
  { name: "arxiviq", url: "https://www.arxiviq.com", updated: "49s" },
  { name: "weird", url: "javascript:alert(1)", updated: "1d" },
] } } });
check("deploys card parses rows; non-http urls nulled",
  depHub?.deploys?.length === 2 && depHub.deploys[0].updated === "49s" &&
  depHub.deploys[1].url === null);
check("site 24h history -> uptime pct + strip (steer: trends)",
  siteHub?.sites?.[0].up24 === 75 && siteHub.sites[0].strip.join(",") === "true,false,true,true" &&
  siteHub.sites[1].up24 === null && siteHub.sites[1].strip.length === 0);
check("hub sites parse with honest up/down (rung 6)",
  siteHub?.sites?.length === 2 && siteHub.sites[0].up === true && siteHub.sites[1].up === false);
check("site urls pass through only when real http(s)",
  siteHub.sites[0].url === "https://dumbmodel.com" &&
  parseHub({ hub: { sites: [{ name: "x", up: true, ms: 1, url: "javascript:alert(1)" }] } })
    .sites[0].url === null);
const brokenHub = parseHub({ hub: { network: { unreachable: "x" } },
  research: { unreachable: "y" } });
check("unreachable hub blocks parse to null panels, not fabrications",
  brokenHub === null);
check("no hub at all -> null", parseHub({}) === null && parseHub(null) === null);

// fleet: docker's own rows parse; roles map to depts; garbage skipped
import { parseFleet, fleetRole } from "./twin.mjs";
const fleetText = [
  '{"Name":"dottie-factory-trainer-1","CPUPerc":"100.16%","MemPerc":"25.2%","MemUsage":"2.39GiB / 9.485GiB"}',
  '{"Name":"dottie-factory-collector-3","CPUPerc":"74.66%","MemPerc":"6.03%","MemUsage":"585.6MiB / 9.485GiB"}',
  '{"Name":"dottie-dottie-1","CPUPerc":"0.02%","MemPerc":"0.9%","MemUsage":"87.15MiB / 9.485GiB"}',
  "not json",
].join("\n");
const fl = parseFleet(fleetText);
check("fleet parses docker rows, skips garbage", fl.length === 3);
check("trainer maps to labs with real numbers",
  fl[0].dept === "labs" && fl[0].short === "trainer-1" && fl[0].cpuPct === 100.16 && fl[0].mem === "2.39GiB");
check("collector maps to servers", fl[1].dept === "servers" && fl[1].role === "data collector");
check("research daemon maps to proving", fl[2].dept === "proving" && fl[2].short === "dottie-1");
check("unknown role lands in gardens", fleetRole("mystery-svc-1").dept === "gardens");
check("empty fleet -> []", parseFleet("").length === 0 && parseFleet(null).length === 0);

// comprehensive org model (bhenre console): lifts every feed aspect honestly
import { parseOrg } from "./twin.mjs";
const orgFeed = { pipeline: {
  curriculum: { tokens_total: 2500000000, tokens_per_step: 262144,
    phases: [{ index: 0, name: "p0_logic", seq: 512, tokens: 400000000,
               token_start: 0, token_end: 400000000, mix: { logic: 1 } }] },
  watch: { phase_progress: { phase: 0 }, timing: { steps_done: 10, steps_total: 100 },
           tokens_per_param: { tpp: 12.4, regime: "undertrain", t2t_target: 40 },
           dominant_route: { name: "planner", p: 0.5 }, route_entropy: 1.68, hints: ["h1"] },
  flow: { data_state: "READY", phase_runway: [{ phase: 0, tokens: 1e9, fill: 1, ok: true, is_trainer: true }],
          gates: [{ id: "D1", name: "host free", ok: true, value: "48 GB", target: ">= 12" }],
          collector_pause: { paused: true, reason: "runway full" } },
  manifest: { total_shards: 1300, by_state: { PACKED: 1002 }, raw_gb: 0.25, raw_max_gb: 4, raw_fill: 0.06 },
  disk: { free_gb: 48, low_water_gb: 12, critical_gb: 6, below_low_water: false },
  ckpt: { latest_pointer: "x.pt", files: [{ name: "x.pt", mb: 1960, age_s: 60 }] },
  trainer: { last: { event: "step", step: 1, gpu_util_pct: 84, gpu_mem_mb: 10038,
                     gpu_mem_total_mb: 12282, gpu_temp_c: 70, gpu_power_w: 110, lr: 6e-4, grad_norm: 0.03 } },
  demand: { step: 1, reasons: ["runway healthy"] },
}, research: { ts: 1, counts: { sota: 3 }, note: "caveat", sota_history: [1, 2, 3] },
   hub: { eval_catalog: { active_name: "r.json", artifacts: [{ name: "r.json", preset: "mini", base_ckpt: "/ckpt/x" }] } } };
const org = parseOrg(orgFeed);
check("org curriculum + current phase", org?.curriculum?.phases.length === 1 && org.curriculum.current === 0);
check("org flow runway + gates + collector", org?.flow?.runway[0].isTrainer === true &&
  org.flow.gates[0].ok === true && org.flow.collectorPaused === true);
check("org manifest + disk + ckpts", org?.manifest?.total === 1300 && org.disk.freeGb === 48 &&
  org.ckpts.files[0].name === "x.pt");
check("org gpu + watch + demand", org?.gpu?.utilPct === 84 && org.watch.dominantRoute.name === "planner" &&
  org.demand.reasons.length === 1);
check("org research note verbatim + catalog", org?.research?.note === "caveat" &&
  org.research.sotaRows === 3 && org.evalCatalog.active === "r.json");
check("org of nothing -> null", parseOrg(null) === null);

// dashboard visuals: signals + full-run curve + j-space internals
const vizOrg = parseOrg({ pipeline: {
  objective: { half_life_target: { system1: 8, system2: 300, critic: 30, planner: 150 } },
  trainer: {
    last: { event: "step", step: 1750, gpu_util_pct: 50,
      route_probs: [0.1, 0.3, 0.1, 0.5],
      hl_est: { system1: 8.0, system2: 299.9, critic: 30.0, planner: 149.8 },
      verbalizable_mass: 0.995, broadcast_strength: 0.717 },
    series: { step: [1730, 1740, 1750], tok_s: [7000, null, 7100],
              grad_norm: [0.05, 0.04, 0.06], lr: [6e-4, 6e-4, 5.9e-4], lm_loss: [1, 1, 1] },
    full_series: { cum_step: Array.from({ length: 500 }, (_, i) => i + 1),
                   lm_loss: Array.from({ length: 500 }, (_, i) => (i === 3 ? -1 : 10 / (i + 1))) },
  },
} });
check("signals pair steps with finite values only (null tok_s dropped)",
  vizOrg?.signals?.tokS.length === 2 && vizOrg.signals.gradNorm.length === 3 &&
  vizOrg.signals.tokS[1][1] === 7100);
check("full curve downsampled <=240, non-positive losses dropped, endpoint kept",
  vizOrg?.fullCurve?.steps.length <= 240 && vizOrg.fullCurve.steps.at(-1) === 500 &&
  vizOrg.fullCurve.lm.every((v) => v > 0));
check("jspace routes keep fixed space order aligned to route_probs",
  vizOrg?.jspace?.routes.map((r) => r.name).join(",") === "system1,system2,critic,planner" &&
  vizOrg.jspace.routes[3].p === 0.5);
check("jspace half-life carries est and target per space",
  vizOrg?.jspace?.halfLife[1].est === 299.9 && vizOrg.jspace.halfLife[1].target === 300);
check("jspace mass + strength lifted", vizOrg?.jspace?.verbalizableMass === 0.995 &&
  vizOrg.jspace.broadcastStrength === 0.717);
check("no series -> null signals/curve, no throw",
  parseOrg({ pipeline: { mode: { id: "training" } } })?.signals === null ||
  parseOrg({ pipeline: { mode: { id: "training" } } })?.signals === undefined ||
  (parseOrg({ pipeline: { mode: { id: "training" } } })?.signals ?? null) === null);

// freshness: published_utc wins; bare ts works; garbage -> null
const t0 = Date.parse("2026-07-22T14:30:02Z");
check("age from published_utc", Math.abs(liveAgeS(wrapped, t0) - 600) < 1);
check("age from bare ts", Math.abs(liveAgeS({ ts: 500 }, 1000_000) - 500) < 1);
check("age of garbage -> null", liveAgeS({}, t0) === null && liveAgeS(wrapped, NaN) === null);

// ---- S6 gap coverage: contract-critical branches inside covered exports ----

// evals wall time: a 0.00s wall is a REAL measurement, not an absent one
const zeroWall = parseHub({ hub: { eval_report: {
  report_markdown: "# Report\nPreset: mini | Wall: 0.00s\n| a | PASS |" } } });
check("Wall: 0.00s -> wallS is 0, not null", zeroWall?.evals?.wallS === 0);
const bareReport = parseHub({ hub: { eval_report: { report_markdown: "# Report\nno verdicts here" } } });
check("report without Wall/Preset lines -> nulls",
  bareReport?.evals?.wallS === null && bareReport.evals.preset === null &&
  bareReport.evals.pass === 0 && bareReport.evals.fail === 0);

// jspace arity guard: wrong route_probs length must never misalign labels
const badArity = parseOrg({ pipeline: { trainer: { last: { event: "step", step: 1,
  route_probs: [0.2, 0.8], hl_est: { system1: 8 } } } } });
check("route_probs of wrong arity -> jspace null, labels never misaligned",
  badArity !== null && badArity.jspace === null);

// disk critical outranks disk low (else-if precedence)
const critEvents = parseLiveEvents({ pipeline: { disk: { free_gb: 4.2, low_water_gb: 12,
  critical_gb: 6, below_low_water: true, below_critical: true } } });
check("disk critical -> finance event and suppresses disk_low",
  critEvents.some((e) => e.kind === "disk_critical" && e.dept === "finance" && e.label.includes("4.2")) &&
  !critEvents.some((e) => e.kind === "disk_low"));

// every failing gate maps to its OWN department (only D3 was covered)
const gateEvents = (id) => parseLiveEvents({ pipeline: { flow: { gates: [
  { id, name: "g", ok: false, value: "v", target: "t" }] } } });
check("gates D1/D2/D4/D5 map to their departments",
  gateEvents("D1")[0]?.dept === "finance" && gateEvents("D2")[0]?.dept === "archives" &&
  gateEvents("D4")[0]?.dept === "servers" && gateEvents("D5")[0]?.dept === "archives");
check("mode error raises labs cipher event",
  parseLiveEvents({ pipeline: { mode: { id: "error", label: "Trainer error", detail: "boom" } } })
    .some((e) => e.kind === "mode_error" && e.dept === "labs" && e.persona === "cipher"));

// clipping: batch text at 700 verbatim chars, event labels at 140 with ellipsis
const clippedHub = parseHub({ hub: { batch_sample: { text: "x".repeat(900) } } });
check("batch sample text clipped at 700", clippedHub?.sample?.text.length === 700);
const longEvent = parseLiveEvents({ pipeline: {
  mode: { id: "stale", label: "Stale", detail: "d".repeat(300) } } })[0];
check("event labels clipped to 140 with ellipsis",
  longEvent?.label.length === 140 && longEvent.label.endsWith("…"));

// freshness: fallback within the wrapped feed + clock-skew sign
check("garbage published_utc falls back to pipeline.ts",
  Math.abs(liveAgeS({ published_utc: "not a date", pipeline: { ts: 500 } }, 1000_000) - 500) < 1);
check("future published_utc -> negative age",
  liveAgeS({ published_utc: "2026-07-22T15:00:02Z", pipeline: pipelineObj }, t0) < 0);

// parseOrg absence branches: absent numbers stay null, never invented
const bareOrg = parseOrg({ pipeline: { trainer: { last: { event: "step", step: 5 } } },
  research: { unreachable: "y" }, hub: { eval_catalog: { unreachable: "x" } } });
check("trainer.last without gpu_util_pct -> gpu null", bareOrg?.gpu === null);
check("unreachable research/eval_catalog -> null panels",
  bareOrg?.research === null && bareOrg?.evalCatalog === null);
const noSpark = parseDashboard({ pipeline: {
  trainer: { series: { step: [1, 2, 3], lm_loss: [0.5, 0.4] } },
  manifest: { funnel: { raw: 1, packed: NaN, consumed: 2, weird: "x" } } } });
check("mismatched step/lm_loss lengths -> no spark", noSpark?.spark === null);
check("funnel drops non-finite counts",
  noSpark?.funnel?.raw === 1 && noSpark.funnel.consumed === 2 &&
  !("packed" in noSpark.funnel) && !("weird" in noSpark.funnel));

// small honesty branches: default model line, non-finite fields, empty reports
const bareLine = twinLine({ source: "local" });
check("local with no numbers -> 'no numbers yet' + ava-mini default",
  bareLine.includes("no numbers yet") && bareLine.includes("ava-mini") && bareLine.includes("[local]"));
const nfTail = parseMetricsTail('{"event":"step","step":7,"lm":"fast","tokens":null}');
check("step kept, non-finite lm/tokens nulled",
  nfTail?.step === 7 && nfTail.lm === null && nfTail.tokens === null);
check("missing base/perplexity -> null",
  parseEvalSummary({}) === null && parseEvalSummary({ base: {} }) === null &&
  parseEvalSummary(null) === null);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
