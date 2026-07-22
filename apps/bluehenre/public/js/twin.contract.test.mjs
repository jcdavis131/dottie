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
check("shard bank count renders when attached (rung 5)",
  twinLine({ source: "local", step: 1, shardsBanked: 1 }).includes("player shards banked 1"));
check("no shard claim when the bank is unseen (hosted)",
  !twinLine({ source: "local", step: 1 }).includes("shards"));

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
  research: { baseline: { metric_name: "factory_lm_loss", metric_value: 5.73733,
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
check("hub research panel lifts baseline + counts",
  hb?.research?.value === 5.73733 && hb.research.provenance === "calibrated" && hb.research.sota === 3);
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

// freshness: published_utc wins; bare ts works; garbage -> null
const t0 = Date.parse("2026-07-22T14:30:02Z");
check("age from published_utc", Math.abs(liveAgeS(wrapped, t0) - 600) < 1);
check("age from bare ts", Math.abs(liveAgeS({ ts: 500 }, 1000_000) - 500) < 1);
check("age of garbage -> null", liveAgeS({}, t0) === null && liveAgeS(wrapped, NaN) === null);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
