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

// ---- live pipeline feed (hill-climb rung 3 + the dashboard board) ----------
// Two REAL sources share one shape: the factory hub's live `/pipeline/status`
// endpoint returns the pipeline object bare; the exported dottie_live_status
// gist wraps the same object under `pipeline` (plus published_utc). Every
// parser here accepts either. Labels/numbers come from the feed verbatim —
// the twin never invents telemetry.

const pipelineOf = (live) =>
  (live?.pipeline && typeof live.pipeline === "object" ? live.pipeline : live) ?? null;

/** Seconds since the feed was published, or null if unparseable. Uses the
 * gist's published_utc when present, else the endpoint's epoch-seconds ts. */
export function liveAgeS(live, nowMs) {
  if (!Number.isFinite(nowMs)) return null;
  const utc = Date.parse(live?.published_utc ?? "");
  if (Number.isFinite(utc)) return (nowMs - utc) / 1000;
  const ts = pipelineOf(live)?.ts;
  return Number.isFinite(ts) ? nowMs / 1000 - ts : null;
}

/** Trainer tail from the live feed: {step, lm, tokens} or null. Same shape as
 * parseMetricsTail, sourced from trainer.last instead of a jsonl. */
export function parseTrainerTail(live) {
  const d = pipelineOf(live)?.trainer?.last;
  if (!d || d.event !== "step" || !Number.isFinite(d.step)) return null;
  return { step: d.step, lm: Number.isFinite(d.lm) ? d.lm : null,
           tokens: Number.isFinite(d.tokens) ? d.tokens : null };
}

/** The dashboard board model: everything the in-game command console renders
 * of the REAL run (operator directive 2026-07-22: bring the :8000 dashboard
 * to life in the game). Missing pieces come back null — drawn as absent. */
export function parseDashboard(live) {
  const p = pipelineOf(live);
  if (!p || typeof p !== "object") return null;
  const num = (v) => (Number.isFinite(v) ? v : null);
  const w = p.watch ?? {};
  const mode = p.mode?.id
    ? { id: String(p.mode.id), label: String(p.mode.label ?? p.mode.id),
        detail: String(p.mode.detail ?? "") }
    : null;
  const run = w.run_progress
    ? { frac: num(w.run_progress.frac), done: num(w.run_progress.tokens_done),
        total: num(w.run_progress.tokens_total) }
    : null;
  const phase = w.phase_progress
    ? { name: String(w.phase_progress.name ?? "?"), short: String(w.phase_progress.short ?? "?"),
        frac: num(w.phase_progress.frac), seq: num(w.phase_progress.seq) }
    : null;
  const timing = w.timing
    ? { tokS: num(w.timing.tok_s), etaS: num(w.timing.eta_remaining_s) }
    : null;
  const gates = Array.isArray(p.flow?.gates)
    ? p.flow.gates.map((g) => ({ id: String(g.id ?? "?"), name: String(g.name ?? "?"),
                                 ok: g.ok === true, value: String(g.value ?? "") }))
    : [];
  const funnel = p.manifest?.funnel && typeof p.manifest.funnel === "object"
    ? Object.fromEntries(Object.entries(p.manifest.funnel)
        .filter(([, v]) => Number.isFinite(v)).map(([k, v]) => [k, v]))
    : null;
  const ckptAgeS = num(p.ckpt?.files?.[0]?.age_s);
  // loss sparkline: the last 40 (step, lm_loss) pairs of the recent series
  const s = p.trainer?.series;
  let spark = null;
  if (Array.isArray(s?.step) && Array.isArray(s?.lm_loss) && s.step.length === s.lm_loss.length) {
    const pairs = s.step.map((st, i) => [st, s.lm_loss[i]])
      .filter(([st, lm]) => Number.isFinite(st) && Number.isFinite(lm))
      .slice(-40);
    if (pairs.length >= 2) spark = { steps: pairs.map((x) => x[0]), lm: pairs.map((x) => x[1]) };
  }
  if (!mode && !run && !phase && !timing && !gates.length && !funnel && spark === null) return null;
  return { mode, run, phase, timing, gates, funnel, ckptAgeS, spark };
}

/** Hub panels (operator 2026-07-22: ALL of the :8000 hub, in-world). Input is
 * a status/feed object carrying `hub` (+ `research`) as published by
 * publish_live_status.py. Returns per-department display models, null when a
 * block is missing or {"unreachable"} — panels render an honest offline line.
 * Every number is lifted from the feed; nothing is computed beyond counting. */
export function parseHub(feed) {
  const hub = feed?.hub;
  const research = feed?.research;
  if (!hub && !research) return null;
  const ok = (b) => b && typeof b === "object" && !b.unreachable;

  let network = null;
  const arch = ok(hub?.network) ? hub.network.architecture : null;
  if (arch && typeof arch === "object") {
    network = {
      preset: String(arch.preset ?? "?"), params: Number.isFinite(arch.params_analytic) ? arch.params_analytic : null,
      dModel: arch.d_model ?? null, layers: arch.n_layers ?? null, heads: arch.n_heads ?? null,
      mlp: String(arch.mlp ?? "?"),
      split: [arch.n_text, arch.n_fusion, arch.n_reasoning].every(Number.isFinite)
        ? `${arch.n_text}T/${arch.n_fusion}F/${arch.n_reasoning}R` : null,
    };
  }

  let ecosystem = null;
  if (ok(hub?.ecosystem)) {
    const e = hub.ecosystem;
    ecosystem = {
      toolsBuilt: e.agenticos?.built ?? null, toolsTotal: e.agenticos?.total ?? null,
      skillsTotal: e.skills?.total ?? null, skillsOwn: e.skills?.agenticos_own ?? null,
      agentEval: Array.isArray(e.agent_eval?.results)
        ? e.agent_eval.results.slice(0, 3).map((r) => ({
            model: String(r.model ?? "?"), tasks: r.tasks ?? 0, success: r.success ?? 0 }))
        : [],
    };
  }

  let evals = null;
  if (ok(hub?.eval_report) && typeof hub.eval_report.report_markdown === "string") {
    const md = hub.eval_report.report_markdown;
    evals = {
      pass: (md.match(/PASS/g) ?? []).length,
      fail: (md.match(/FAIL/g) ?? []).length,
      wallS: Number(md.match(/Wall:\s*([\d.]+)s/)?.[1]) || null,
      preset: md.match(/Preset:\s*(\w+)/)?.[1] ?? null,
    };
  }

  let researchOut = null;
  if (ok(research) && research.baseline) {
    const b = research.baseline;
    const c = research.counts ?? {};
    researchOut = {
      metric: String(b.metric_name ?? "?"),
      value: Number.isFinite(b.metric_value) ? b.metric_value : null,
      sem: Number.isFinite(b.metric_sem) ? b.metric_sem : null,
      provenance: String(b.provenance ?? "?"),
      pending: c.pending ?? null, sota: c.sota ?? null, rejected: c.rejected ?? null,
      ts: Number.isFinite(research.ts) ? research.ts : null, // caller renders staleness
    };
  }

  // a REAL example from the shard the trainer has claimed (decoded in-container
  // from the packed tokens; rotates each publish). Text is the feed's verbatim.
  let sample = null;
  if (ok(hub?.batch_sample) && typeof hub.batch_sample.text === "string") {
    const b = hub.batch_sample;
    sample = {
      shard: String(b.shard ?? "?"), source: String(b.source ?? "?"),
      phase: Number.isFinite(b.phase) ? b.phase : null,
      state: String(b.state ?? "?"), taskType: String(b.task_type ?? "?"),
      docId: String(b.doc_id ?? "?"),
      docTokens: Number.isFinite(b.doc_tokens) ? b.doc_tokens : null,
      shownTokens: Number.isFinite(b.shown_tokens) ? b.shown_tokens : null,
      docsInShard: Number.isFinite(b.docs_in_shard) ? b.docs_in_shard : null,
      text: b.text.slice(0, 700),
    };
  }

  // rung 6: the org's real deployed sites, probed by the publisher
  const sites = Array.isArray(hub?.sites)
    ? hub.sites.map((s) => ({ name: String(s.name ?? "?"), up: s.up === true,
                              ms: Number.isFinite(s.ms) ? s.ms : null,
                              // link only when the probe URL is a real http(s) URL
                              url: /^https?:\/\//.test(s.url ?? "") ? String(s.url) : null }))
    : null;

  if (!network && !ecosystem && !evals && !researchOut && !sites && !sample) return null;
  return { network, ecosystem, evals, research: researchOut, sites, sample };
}

// ---- fleet (operator 2026-07-22: NPCs ARE the docker containers) -----------
// Parse `docker stats --no-stream --format "{{json .}}"` line output into the
// game's fleet model. Every number is docker's own; nothing is invented.

/** Which campus department a container reports to, by its role in the org. */
export function fleetRole(name) {
  const n = String(name).toLowerCase();
  const short = n.replace(/^dottie-factory-/, "").replace(/^dottie-/, "");
  const pick = (role, dept) => ({ role, dept, short });
  if (n.includes("trainer")) return pick("foundation trainer", "labs");
  if (n.includes("collector")) return pick("data collector", "servers");
  if (n.includes("curator")) return pick("data curator", "archives");
  if (n.includes("janitor")) return pick("fleet janitor", "finance");
  if (n.includes("server")) return pick("hub server", "hall");
  if (n.includes("dottie")) return pick("research daemon", "proving");
  return pick("service", "gardens");
}

/** docker-stats JSONL -> [{name, short, role, dept, cpuPct, mem, memPct}].
 * Garbage lines skipped; no containers -> []. */
export function parseFleet(text) {
  const out = [];
  for (const line of String(text ?? "").split("\n")) {
    const l = line.trim();
    if (!l) continue;
    try {
      const d = JSON.parse(l);
      const name = d.Name ?? d.Container;
      if (!name) continue;
      const cpu = parseFloat(String(d.CPUPerc ?? "").replace("%", ""));
      const memPct = parseFloat(String(d.MemPerc ?? "").replace("%", ""));
      const mem = String(d.MemUsage ?? "").split("/")[0].trim();
      out.push({ name: String(name), ...fleetRole(name),
                 cpuPct: Number.isFinite(cpu) ? cpu : null,
                 memPct: Number.isFinite(memPct) ? memPct : null,
                 mem: mem || null });
    } catch { /* partial line — skip */ }
  }
  return out;
}

/** The COMPREHENSIVE org model (bhenre.com console): every little aspect the
 * feed truthfully carries — curriculum, data flow, manifest, checkpoints,
 * compute, routing watch, demand, research detail, eval catalog. Missing or
 * unreachable pieces come back null; nothing is invented. */
export function parseOrg(live) {
  const p = pipelineOf(live);
  if (!p || typeof p !== "object") return null;
  const num = (v) => (Number.isFinite(v) ? v : null);
  const w = p.watch ?? {};
  const cur = p.curriculum;
  const curriculum = Array.isArray(cur?.phases)
    ? {
        tokensTotal: num(cur.tokens_total), tokensPerStep: num(cur.tokens_per_step),
        current: num(w.phase_progress?.phase),
        phases: cur.phases.map((ph) => ({
          index: ph.index, name: String(ph.name ?? "?"), seq: num(ph.seq),
          tokens: num(ph.tokens), start: num(ph.token_start), end: num(ph.token_end),
          mix: ph.mix && typeof ph.mix === "object" ? ph.mix : {},
        })),
      }
    : null;
  const flow = p.flow
    ? {
        dataState: String(p.flow.data_state ?? "?"), dataDetail: String(p.flow.data_detail ?? ""),
        collectorPaused: p.flow.collector_pause?.paused === true,
        collectorReason: String(p.flow.collector_pause?.reason ?? ""),
        runway: Array.isArray(p.flow.phase_runway)
          ? p.flow.phase_runway.map((r) => ({ phase: r.phase, tokens: num(r.tokens),
              fill: num(r.fill), ok: r.ok === true, isTrainer: r.is_trainer === true }))
          : [],
        gates: Array.isArray(p.flow.gates)
          ? p.flow.gates.map((g) => ({ id: String(g.id ?? "?"), name: String(g.name ?? "?"),
              ok: g.ok === true, value: String(g.value ?? ""), target: String(g.target ?? "") }))
          : [],
      }
    : null;
  const manifest = p.manifest
    ? { total: num(p.manifest.total_shards), byState: p.manifest.by_state ?? {},
        rawGb: num(p.manifest.raw_gb), rawMaxGb: num(p.manifest.raw_max_gb),
        rawFill: num(p.manifest.raw_fill) }
    : null;
  const disk = p.disk
    ? { freeGb: num(p.disk.free_gb), lowGb: num(p.disk.low_water_gb),
        critGb: num(p.disk.critical_gb), belowLow: p.disk.below_low_water === true,
        belowCrit: p.disk.below_critical === true }
    : null;
  const ckpts = Array.isArray(p.ckpt?.files)
    ? { latest: String(p.ckpt.latest_pointer ?? "?"),
        files: p.ckpt.files.slice(0, 8).map((f) => ({ name: String(f.name ?? "?"),
          mb: num(f.mb), ageS: num(f.age_s) })) }
    : null;
  const t = w.timing;
  const timing = t
    ? { tokS: num(t.tok_s), etaS: num(t.eta_remaining_s), stepsDone: num(t.steps_done),
        stepsTotal: num(t.steps_total), tokensDone: num(t.tokens_done),
        tokensTotal: num(t.tokens_total) }
    : null;
  const tpp = w.tokens_per_param
    ? { tpp: num(w.tokens_per_param.tpp), regime: String(w.tokens_per_param.regime ?? "?"),
        target: num(w.tokens_per_param.t2t_target) }
    : null;
  const last = p.trainer?.last;
  const gpu = last && Number.isFinite(last.gpu_util_pct)
    ? { utilPct: num(last.gpu_util_pct), memMb: num(last.gpu_mem_mb),
        memTotalMb: num(last.gpu_mem_total_mb), tempC: num(last.gpu_temp_c),
        powerW: num(last.gpu_power_w), lr: num(last.lr), gradNorm: num(last.grad_norm) }
    : null;
  const watch = {
    dominantRoute: w.dominant_route
      ? { name: String(w.dominant_route.name ?? "?"), p: num(w.dominant_route.p) } : null,
    routeEntropy: num(w.route_entropy),
    hints: Array.isArray(w.hints) ? w.hints.map(String).slice(0, 4) : [],
  };
  const demand = p.demand
    ? { step: num(p.demand.step),
        reasons: Array.isArray(p.demand.reasons) ? p.demand.reasons.map(String).slice(0, 3) : [] }
    : null;
  const r = live?.research && !live.research.unreachable ? live.research : null;
  const research = r
    ? { counts: r.counts ?? {}, note: String(r.note ?? ""),
        sotaRows: Array.isArray(r.sota_history) ? r.sota_history.length : null,
        ts: num(r.ts) }
    : null;
  const cat = live?.hub?.eval_catalog && !live.hub.eval_catalog.unreachable ? live.hub.eval_catalog : null;
  const evalCatalog = cat
    ? { active: String(cat.active_name ?? "?"),
        artifacts: Array.isArray(cat.artifacts)
          ? cat.artifacts.slice(0, 6).map((a) => ({ name: String(a.name ?? "?"),
              preset: String(a.preset ?? "?"), ckpt: String(a.base_ckpt ?? "?") }))
          : [] }
    : null;
  // ---- dashboard visuals (operator: "add more from :8000/dashboard") -------
  // Recent training signals (tok/s, grad norm, lr) from the rolling series.
  const ser = p.trainer?.series;
  let signals = null;
  if (Array.isArray(ser?.step) && ser.step.length >= 2) {
    const pick = (key) => Array.isArray(ser[key])
      ? ser.step.map((st, i) => [st, ser[key][i]])
          .filter(([st, v]) => Number.isFinite(st) && Number.isFinite(v))
      : [];
    const tokS = pick("tok_s"), gradNorm = pick("grad_norm"), lr = pick("lr");
    if (tokS.length >= 2 || gradNorm.length >= 2 || lr.length >= 2)
      signals = { tokS, gradNorm, lr };
  }
  // Full-run loss curve from full_series (cum_step keeps restarts monotonic),
  // downsampled to <=240 points — the whole story, 10.6 -> now.
  const fs = p.trainer?.full_series;
  let fullCurve = null;
  if (Array.isArray(fs?.cum_step) && Array.isArray(fs?.lm_loss)) {
    let pairs = fs.cum_step.map((st, i) => [st, fs.lm_loss[i]])
      .filter(([st, v]) => Number.isFinite(st) && Number.isFinite(v) && v > 0);
    if (pairs.length >= 8) {
      const stride = Math.max(1, Math.ceil(pairs.length / 240));
      pairs = pairs.filter((_, i) => i % stride === 0 || i === pairs.length - 1);
      fullCurve = { steps: pairs.map((x) => x[0]), lm: pairs.map((x) => x[1]) };
    }
  }
  // J-Space internals: route probabilities align with the hl_est key order
  // (verified: watch.dominant_route matches route_probs by position).
  const JSPACES = ["system1", "system2", "critic", "planner"];
  const hlT = p.objective?.half_life_target ?? {};
  let jspace = null;
  if (last && Array.isArray(last.route_probs) && last.route_probs.length === JSPACES.length) {
    jspace = {
      routes: JSPACES.map((name, i) => ({ name, p: num(last.route_probs[i]) })),
      halfLife: JSPACES.map((name) => ({ name, est: num(last.hl_est?.[name]),
                                         target: num(hlT[name]) })),
      verbalizableMass: num(last.verbalizable_mass),
      broadcastStrength: num(last.broadcast_strength),
    };
  }
  return { curriculum, flow, manifest, disk, ckpts, timing, tpp, gpu, watch, demand,
           research, evalCatalog, signals, fullCurve, jspace };
}

// which department (and consultant hat) owns each REAL problem kind
const MODE_EVENTS = {
  stale: { dept: "labs", persona: "cipher", action: "decode" },
  error: { dept: "labs", persona: "cipher", action: "decode" },
  starved: { dept: "servers", persona: "auditor", action: "interview" },
};
const GATE_EVENTS = {
  D1: { dept: "finance", persona: "architect", action: "replan" },  // host disk
  D2: { dept: "archives", persona: "architect", action: "replan" }, // token runway
  D3: { dept: "servers", persona: "auditor", action: "interview" }, // collectors
  D4: { dept: "servers", persona: "auditor", action: "interview" }, // raw headroom
  D5: { dept: "archives", persona: "cipher", action: "decode" },    // fail rate
};
const clip = (s, n = 140) => (String(s).length > n ? String(s).slice(0, n - 1) + "…" : String(s));

/** Extract REAL problem events from a parsed live-status feed. Healthy feeds
 * return []. Unknown problem shapes are skipped, not guessed at. */
export function parseLiveEvents(live) {
  const p = pipelineOf(live);
  if (!p || typeof p !== "object") return [];
  const out = [];
  const mode = p.mode;
  if (mode?.id && MODE_EVENTS[mode.id])
    out.push({ kind: `mode_${mode.id}`, ...MODE_EVENTS[mode.id],
               label: clip(`${mode.label ?? mode.id}: ${mode.detail ?? ""}`) });
  const flow = p.flow;
  if (typeof flow?.data_state === "string" && flow.data_state !== "READY")
    out.push({ kind: "data_starved", ...MODE_EVENTS.starved,
               label: clip(`data ${flow.data_state}: ${flow.data_detail ?? ""}`) });
  const disk = p.disk;
  if (disk?.below_critical === true)
    out.push({ kind: "disk_critical", ...GATE_EVENTS.D1,
               label: clip(`disk critical: ${disk.free_gb} GB free (< ${disk.critical_gb} GB)`) });
  else if (disk?.below_low_water === true)
    out.push({ kind: "disk_low", ...GATE_EVENTS.D1,
               label: clip(`disk low: ${disk.free_gb} GB free (< ${disk.low_water_gb} GB)`) });
  const benignPause = /runway/.test(flow?.collector_pause?.reason ?? "");
  for (const gate of Array.isArray(flow?.gates) ? flow.gates : []) {
    if (gate?.ok !== false || !GATE_EVENTS[gate.id]) continue;
    if (gate.id === "D3" && benignPause) continue; // full-runway pause is healthy backpressure
    out.push({ kind: `gate_${gate.id}`, ...GATE_EVENTS[gate.id],
               label: clip(`${gate.name}: ${gate.value} (want ${gate.target})`) });
  }
  return out;
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
