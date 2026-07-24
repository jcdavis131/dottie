// Blue Hen RE org console (www.bhenre.com): every little aspect of the org,
// rendered from real telemetry only. Same provenance doctrine as everything
// else: source:"local" or it says offline; absences render as absences.
import { twinLine, parseHub, parseHubRegistry, nextActions } from "./twin.mjs";

const $ = (id) => document.getElementById(id);
const P = (text, cls = "") => {
  const p = document.createElement("p");
  if (cls) p.className = cls;
  p.textContent = text;
  return p;
};
const line = (k, v) => {
  const d = document.createElement("div");
  d.className = "rowline";
  const ks = document.createElement("span"); ks.className = "k"; ks.textContent = k;
  const vs = document.createElement("span"); vs.className = "v"; vs.textContent = v;
  d.append(ks, vs);
  return d;
};
const bar = (frac, label, accVar) => {
  const d = document.createElement("div");
  d.className = "bar";
  if (accVar) d.style.setProperty("--acc", `var(${accVar})`);
  const i = document.createElement("i");
  i.style.width = `${Math.max(0, Math.min(100, (frac ?? 0) * 100)).toFixed(1)}%`;
  i.style.opacity = "0.45";
  const b = document.createElement("b"); b.textContent = label;
  d.append(i, b);
  return d;
};
const table = (heads, rows) => {
  const t = document.createElement("table");
  const tr = document.createElement("tr");
  for (const h of heads) {
    const th = document.createElement("th");
    if (h.endsWith("|r")) { th.className = "r"; th.textContent = h.slice(0, -2); }
    else th.textContent = h;
    tr.append(th);
  }
  t.append(tr);
  for (const row of rows) {
    const r = document.createElement("tr");
    row.forEach((cell, i) => {
      const td = document.createElement("td");
      if (heads[i]?.endsWith("|r")) td.className = "r";
      if (cell instanceof Node) td.append(cell); else td.textContent = cell;
      r.append(td);
    });
    t.append(r);
  }
  return t;
};
const led = (ok) => {
  const i = document.createElement("i");
  i.className = `led ${ok === true ? "ok" : ok === false ? "bad" : "idle"}`;
  return i;
};
const withLed = (ok, text) => {
  const s = document.createElement("span");
  s.append(led(ok), document.createTextNode(text));
  return s;
};
const fmtDur = (s) => {
  if (!Number.isFinite(s)) return "?";
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  if (s < 172800) return `${Math.floor(s / 3600)}h${String(Math.round((s % 3600) / 60)).padStart(2, "0")}m`;
  return `${(s / 86400).toFixed(1)}d`;
};
const gb = (n) => (Number.isFinite(n) ? `${(n / 1e9).toFixed(2)}B` : "?");
const offline = (el, detail) => { el.replaceChildren(P(detail ?? "feed offline — no fabricated numbers", "note")); };

let twin = null;
let fleet = null; // last /api/fleet response (shared with the Guide digest)

// Shared series renderer (the :8000 dashboard's visual idiom): supersampled
// hard-pixel marks in a brand hue, x mapped by real step value (restart gaps
// stay honest), optional log y, muted-ink direct label — title carries
// identity, so single-series charts need no legend.
function seriesCanvas(xs, ys, { label, accVar = "--bh-hen-blue", logY = false, tall = false } = {}) {
  const c = document.createElement("canvas");
  c.className = "seriescv" + (tall ? " tall" : "");
  requestAnimationFrame(() => {
    const W = c.clientWidth * 2, H = c.clientHeight * 2;
    if (!W) return;
    c.width = W; c.height = H;
    const g = c.getContext("2d");
    const cs = getComputedStyle(document.documentElement);
    const acc = cs.getPropertyValue(accVar).trim() || "#3d6b89";
    const mut = cs.getPropertyValue("--bh-muted").trim() || "#6f655a";
    const ty = logY ? ys.map((v) => Math.log10(v)) : ys;
    const lo = Math.min(...ty), hi = Math.max(...ty), span = hi - lo || 1;
    const x0 = Math.min(...xs), xr = (Math.max(...xs) - x0) || 1;
    ys.forEach((_, i) => {
      const x = Math.floor(((xs[i] - x0) / xr) * (W - 6));
      const y = 8 + Math.floor((1 - (ty[i] - lo) / span) * (H - 30));
      g.fillStyle = acc;
      g.globalAlpha = 0.3; g.fillRect(x, y + 4, 3, Math.max(0, H - 4 - y));
      g.globalAlpha = 1; g.fillRect(x, y, 3, 3);
    });
    g.font = "600 19px IBM Plex Mono, monospace"; g.fillStyle = mut; g.textBaseline = "top";
    g.fillText(label, 8, 4);
  });
  return c;
}

function renderCurve() {
  const el = $("curve");
  el.replaceChildren();
  const fc = twin?.org?.fullCurve;
  if (twin?.source !== "local" || !fc) return offline(el);
  el.append(seriesCanvas(fc.steps, fc.lm, {
    label: `lm loss ${fc.lm[0].toFixed(2)} → ${fc.lm.at(-1).toFixed(3)} · ${fc.steps.at(-1).toLocaleString()} cumulative steps · log scale`,
    accVar: "--bh-hen-blue", logY: true, tall: true,
  }));
  el.append(P("every metrics event since step 1, cumulative across restarts, downsampled — the whole climb in one line", "note"));
}

function renderSignals() {
  const el = $("signals");
  el.replaceChildren();
  const s = twin?.org?.signals;
  if (twin?.source !== "local" || !s) return offline(el);
  const grid = document.createElement("div");
  grid.style.cssText = "display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px";
  const put = (pairs, label, accVar, logY = false) => {
    if (!Array.isArray(pairs) || pairs.length < 2) return;
    grid.append(seriesCanvas(pairs.map((x) => x[0]), pairs.map((x) => x[1]), { label, accVar, logY }));
  };
  put(s.tokS, `tok/s · now ${Math.round(s.tokS.at(-1)?.[1] ?? 0).toLocaleString()}`, "--bh-moss");
  put(s.gradNorm, `grad norm · now ${(s.gradNorm.at(-1)?.[1] ?? 0).toFixed(3)} · log`, "--bh-rust", true);
  put(s.lr, `lr · now ${(s.lr.at(-1)?.[1] ?? 0).toExponential(1)}`, "--bh-copper");
  el.append(grid);
  el.append(P("recent metrics window — throughput, gradient norm, learning rate", "note"));
}

function renderJspace() {
  const el = $("jspace");
  el.replaceChildren();
  const j = twin?.org?.jspace;
  if (twin?.source !== "local" || !j) return offline(el);
  // fixed space order + fixed brand hues; the bar label carries identity
  const ACC = { system1: "--bh-slate", system2: "--bh-hen-blue",
                critic: "--bh-rust", planner: "--bh-copper" };
  for (const r of j.routes)
    if (Number.isFinite(r.p))
      el.append(bar(r.p, `route ${r.name} · ${(r.p * 100).toFixed(1)}%`, ACC[r.name]));
  el.append(table(["space", "half-life est|r", "target|r"],
    j.halfLife.map((hl) => [hl.name, hl.est ?? "?", hl.target ?? "?"])));
  if (Number.isFinite(j.verbalizableMass))
    el.append(line("verbalizable mass", j.verbalizableMass.toFixed(4)));
  if (Number.isFinite(j.broadcastStrength))
    el.append(line("broadcast strength", j.broadcastStrength.toFixed(3)));
}

function renderRun() {
  const el = $("run");
  el.replaceChildren();
  if (twin?.source !== "local") return offline(el, twin?.detail);
  const dash = twin.dashboard ?? {};
  const o = twin.org ?? {};
  const grid = document.createElement("div");
  grid.style.cssText = "display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:4px 22px";
  const left = document.createElement("div");
  if (dash.mode) {
    const m = P(`● ${dash.mode.label}`, "mono");
    m.style.color = ["training", "running"].includes(dash.mode.id) ? "var(--bh-ok)"
      : dash.mode.id === "recovering" ? "var(--bh-copper)" : "var(--bh-bad)";
    m.style.fontWeight = "600"; m.style.margin = "0 0 4px";
    m.title = dash.mode.detail ?? "";
    left.append(m);
  }
  left.append(
    line("step · loss", `${twin.step ?? "?"} · ${Number.isFinite(twin.lm) ? twin.lm.toFixed(4) : "?"}`),
    line("held-out ppl", Number.isFinite(twin.weightedPpl) ? twin.weightedPpl.toFixed(1) : "—"),
  );
  if (dash.timing) left.append(line("throughput · eta",
    `${Number.isFinite(dash.timing.tokS) ? Math.round(dash.timing.tokS).toLocaleString() : "?"} tok/s · ${fmtDur(dash.timing.etaS)}`));
  if (o.timing) left.append(line("steps", `${o.timing.stepsDone ?? "?"} of ${o.timing.stepsTotal ?? "?"}`));
  if (Number.isFinite(dash.ckptAgeS)) left.append(line("checkpoint", `${fmtDur(dash.ckptAgeS)} ago`));
  if (o.tpp) left.append(line("tokens/param", `${o.tpp.tpp ?? "?"} (${o.tpp.regime}, target ${o.tpp.target ?? "?"})`));
  const right = document.createElement("div");
  if (Number.isFinite(dash.run?.frac))
    right.append(bar(dash.run.frac, `run ${(dash.run.frac * 100).toFixed(1)}% of ${gb(dash.run.total)} tok`, "--bh-hen-blue"));
  if (Number.isFinite(dash.phase?.frac))
    right.append(bar(dash.phase.frac, `${dash.phase.name} ${(dash.phase.frac * 100).toFixed(0)}% · seq ${dash.phase.seq ?? "?"}`, "--bh-copper"));
  if (Array.isArray(dash.gates) && dash.gates.length) {
    const g = document.createElement("div");
    g.style.margin = "4px 0";
    for (const gt of dash.gates) {
      const c = document.createElement("span");
      c.className = "chip";
      c.title = `${gt.name}: ${gt.value}`;
      c.append(led(gt.ok), document.createTextNode(gt.id));
      g.append(c);
    }
    right.append(g);
  }
  if (dash.spark?.lm?.length >= 2) {
    const c = document.createElement("canvas");
    c.id = "spark";
    right.append(c);
    requestAnimationFrame(() => {
      const W = c.clientWidth * 2, H = c.clientHeight * 2;
      c.width = W; c.height = H;
      const g2 = c.getContext("2d");
      const cs = getComputedStyle(document.documentElement);
      const acc = cs.getPropertyValue("--bh-hen-blue").trim() || "#3d6b89";
      const mut = cs.getPropertyValue("--bh-muted").trim() || "#6f655a";
      const lo = Math.min(...dash.spark.lm), hi = Math.max(...dash.spark.lm), span = hi - lo || 1;
      dash.spark.lm.forEach((v, i) => {
        const x = Math.floor((i / Math.max(1, dash.spark.lm.length - 1)) * (W - 6));
        const y = 8 + Math.floor((1 - (v - lo) / span) * (H - 28));
        g2.fillStyle = acc; g2.globalAlpha = 0.35; g2.fillRect(x, y + 4, 4, Math.max(0, H - 4 - y));
        g2.globalAlpha = 1; g2.fillRect(x, y, 4, 4);
      });
      g2.font = "600 19px IBM Plex Mono, monospace"; g2.fillStyle = mut;
      g2.textBaseline = "top";
      g2.fillText(`lm ${hi.toFixed(3)} → ${lo.toFixed(3)} · steps ${dash.spark.steps[0]}–${dash.spark.steps.at(-1)}`, 8, 4);
    });
  }
  grid.append(left, right);
  el.append(grid);
}

function renderAlerts() {
  const el = $("alerts");
  el.replaceChildren();
  if (twin?.source !== "local") return offline(el);
  const evs = Array.isArray(twin.events) ? twin.events : [];
  // weekly site-perf regressions surface here too (steer: flag as ALERT)
  const regressions = parseHub(twin)?.sitePerf?.regressions ?? [];
  if (!evs.length && !regressions.length) {
    const p = P("● no active alerts — the org is unblocked");
    p.style.color = "var(--bh-ok)";
    el.append(p);
    return;
  }
  for (const label of regressions) {
    const a = document.createElement("div");
    a.className = "alert";
    const who = document.createElement("div");
    who.className = "who";
    who.textContent = "site-perf regression (weekly probe)";
    a.append(who, P(label));
    el.append(a);
  }
  for (const ev of evs) {
    const a = document.createElement("div");
    a.className = "alert";
    const who = document.createElement("div");
    who.className = "who";
    who.textContent = `${ev.kind} @ ${ev.dept} team`;
    a.append(who, P(ev.label));
    el.append(a);
  }
}

function renderCurriculum() {
  const el = $("curriculum");
  el.replaceChildren();
  const cur = twin?.org?.curriculum;
  if (twin?.source !== "local" || !cur) return offline(el);
  const done = twin.tokens ?? null;
  el.append(line("budget", `${gb(cur.tokensTotal)} tokens · ${Number.isFinite(cur.tokensPerStep) ? cur.tokensPerStep.toLocaleString() : "?"} tok/step`));
  for (const ph of cur.phases) {
    const frac = Number.isFinite(done) && Number.isFinite(ph.start) && Number.isFinite(ph.end)
      ? Math.max(0, Math.min(1, (done - ph.start) / (ph.end - ph.start))) : 0;
    const isCur = ph.index === cur.current;
    const b = bar(frac, `p${ph.index} ${ph.name.replace(/^p\d_/, "")} · seq ${ph.seq ?? "?"} · ${gb(ph.tokens)} · ${(frac * 100).toFixed(0)}%`,
      isCur ? "--bh-copper" : "--bh-slate");
    if (isCur) b.style.borderColor = "var(--bh-copper)";
    el.append(b);
    if (isCur) {
      const mix = document.createElement("div");
      for (const [k, v] of Object.entries(ph.mix)) {
        const c = document.createElement("span");
        c.className = "chip";
        c.textContent = `${k} ${(v * 100).toFixed(0)}%`;
        mix.append(c);
      }
      el.append(mix);
    }
  }
}

function renderFlow() {
  const el = $("flow");
  el.replaceChildren();
  const f = twin?.org?.flow;
  if (twin?.source !== "local" || !f) return offline(el);
  el.append(line("data state", f.dataState), P(f.dataDetail, "note"));
  el.append(line("collectors", f.collectorPaused ? `paused — ${f.collectorReason}` : "running"));
  for (const r of f.runway)
    el.append(bar(Math.min(1, r.fill ?? 0),
      `p${r.phase}${r.isTrainer ? " ◂ trainer" : ""} · ${gb(r.tokens)} ready`, r.ok ? "--bh-moss" : "--bh-rust"));
}

function renderManifest() {
  const el = $("manifest");
  el.replaceChildren();
  const m = twin?.org?.manifest;
  if (twin?.source !== "local" || !m) return offline(el);
  el.append(line("total shards", String(m.total ?? "?")));
  const chips = document.createElement("div");
  for (const [k, v] of Object.entries(m.byState)) {
    const c = document.createElement("span");
    c.className = "chip";
    c.textContent = `${k} ${v}`;
    if (k === "FAILED" && v > 0) c.style.borderColor = "var(--bh-rust)";
    chips.append(c);
  }
  el.append(chips);
  if (Number.isFinite(m.rawFill))
    el.append(bar(m.rawFill, `raw buffer ${m.rawGb ?? "?"} / ${m.rawMaxGb ?? "?"} GB`, "--bh-moss"));
}

function renderCkpts() {
  const el = $("ckpts");
  el.replaceChildren();
  const c = twin?.org?.ckpts;
  if (twin?.source !== "local" || !c) return offline(el);
  el.append(line("latest pointer", c.latest));
  el.append(table(["file", "size|r", "age|r"],
    c.files.map((f) => [f.name, Number.isFinite(f.mb) ? `${(f.mb / 1024).toFixed(1)}G` : "?", fmtDur(f.ageS)])));
}

function renderCompute() {
  const el = $("compute");
  el.replaceChildren();
  const o = twin?.org ?? {};
  if (twin?.source !== "local" || (!o.gpu && !o.disk)) return offline(el);
  if (o.gpu) {
    el.append(
      line("gpu util", `${o.gpu.utilPct ?? "?"}% · ${o.gpu.tempC ?? "?"}°C · ${o.gpu.powerW ?? "?"}W`),
      line("gpu memory", `${o.gpu.memMb ?? "?"} / ${o.gpu.memTotalMb ?? "?"} MB`),
      line("lr · grad norm", `${o.gpu.lr?.toExponential(2) ?? "?"} · ${o.gpu.gradNorm?.toFixed(3) ?? "?"}`),
    );
    if (Number.isFinite(o.gpu.memMb) && Number.isFinite(o.gpu.memTotalMb))
      el.append(bar(o.gpu.memMb / o.gpu.memTotalMb, `vram ${(o.gpu.memMb / o.gpu.memTotalMb * 100).toFixed(0)}%`, "--bh-slate"));
  }
  if (o.disk) {
    el.append(line("host disk", `${o.disk.freeGb ?? "?"} GB free (low ${o.disk.lowGb} · crit ${o.disk.critGb})`));
    el.append(bar(Math.min(1, (o.disk.freeGb ?? 0) / 100),
      `free ${o.disk.freeGb ?? "?"} GB`, o.disk.belowLow ? "--bh-rust" : "--bh-moss"));
  }
}

function renderBatch(h) {
  const el = $("batch");
  el.replaceChildren();
  const s = h?.sample;
  if (twin?.source !== "local" || !s) return offline(el);
  el.append(
    line("shard (claimed by trainer)", `${s.source} · p${s.phase ?? "?"} · ${s.state}`),
    line("document", `${s.taskType} · ${s.docTokens ?? "?"} tokens (showing ${s.shownTokens ?? "?"})`),
  );
  const t = document.createElement("div");
  t.className = "sampletext";
  t.textContent = s.text; // verbatim feed text — textContent only
  el.append(t);
  const n = document.createElement("p");
  n.className = "note";
  n.textContent = `decoded from ${s.shard} (${s.docsInShard ?? "?"} docs in shard); a fresh example each publish`;
  el.append(n);
}

function renderNetwork(h) {
  const el = $("network");
  el.replaceChildren();
  if (!h?.network) return offline(el);
  const n = h.network;
  el.append(
    line("preset · mlp", `${n.preset} · ${n.mlp}`),
    line("params", n.params ? `${(n.params / 1e6).toFixed(1)}M` : "?"),
    line("d_model · heads", `${n.dModel ?? "?"} · ${n.heads ?? "?"}`),
    line("layers", `${n.layers ?? "?"}${n.split ? ` (${n.split})` : ""}`),
  );
}

function renderWatch() {
  const el = $("watch");
  el.replaceChildren();
  const w = twin?.org?.watch;
  if (twin?.source !== "local" || !w) return offline(el);
  if (w.dominantRoute)
    el.append(line("dominant route", `${w.dominantRoute.name} @ ${(w.dominantRoute.p * 100).toFixed(1)}%`));
  if (Number.isFinite(w.routeEntropy)) el.append(line("route entropy", w.routeEntropy.toFixed(3)));
  for (const h of w.hints) el.append(P(`◦ ${h}`, "note"));
}

function renderResearch(h) {
  const el = $("research");
  el.replaceChildren();
  const r = twin?.org?.research;
  const hr = h?.research;
  if (twin?.source !== "local" || (!r && !hr)) return offline(el);
  if (hr) {
    const ageH = Number.isFinite(hr.ts) ? (Date.now() / 1000 - hr.ts) / 3600 : null;
    el.append(line("baseline", `${hr.value?.toFixed(4) ?? "?"} ±${hr.sem?.toFixed(3) ?? "?"} (${hr.provenance}${ageH > 1 ? ` · ${ageH.toFixed(0)}h old` : ""})`));
  }
  if (r?.counts) {
    const chips = document.createElement("div");
    for (const [k, v] of Object.entries(r.counts)) {
      const c = document.createElement("span");
      c.className = "chip";
      c.textContent = `${k} ${v}`;
      chips.append(c);
    }
    el.append(chips);
  }
  if (r?.note) el.append(P(r.note, "note"));
}

function renderEvals(h) {
  const el = $("evals");
  el.replaceChildren();
  const cat = twin?.org?.evalCatalog;
  if (twin?.source !== "local" || (!h?.evals && !cat)) return offline(el);
  if (h?.evals) {
    const v = line("verdicts", `${h.evals.pass} PASS / ${h.evals.fail} FAIL`);
    el.append(v);
    if (h.evals.wallS) el.append(line("wall · preset", `${Math.round(h.evals.wallS)}s · ${h.evals.preset ?? "?"}`));
  }
  if (cat) {
    el.append(line("active report", cat.active));
    el.append(table(["artifact", "preset|r"], cat.artifacts.map((a) => [a.name, a.preset])));
  }
}

function renderEco(h) {
  const el = $("eco");
  el.replaceChildren();
  if (!h?.ecosystem) return offline(el);
  const e = h.ecosystem;
  el.append(
    line("agentic tools", `${e.toolsBuilt ?? "?"} / ${e.toolsTotal ?? "?"} built`),
    line("skills", `${e.skillsTotal ?? "?"} total (${e.skillsOwn ?? "?"} own)`),
  );
  for (const r of e.agentEval)
    el.append(line(r.model, `${r.success}/${r.tasks} tasks ok`));
}

// Hub — the org's OWN datasets, each stamped with its provenance class (the
// Dottie-site differentiator). Fed by the static /hub_registry.json (built by
// scripts/build_hub_registry.mjs from the corpus_proposals cards); these are
// committed, sha-verified artifacts, so the card renders independent of the
// live-telemetry gate. Card links go to the public repo blob (real URL).
const REPO_BASE = "https://github.com/jcdavis131/dottie/blob/main/";
let hubReg = null;
async function loadHubRegistry() {
  const el = $("hubreg");
  let doc = null;
  try { doc = await (await fetch("/hub_registry.json", { cache: "no-cache" })).json(); }
  catch { return offline(el, "hub registry not built — run scripts/build_hub_registry.mjs"); }
  hubReg = parseHubRegistry(doc);
  renderHubRegistry();
}
// shared hub-card bits (datasets + models both carry a provenance badge)
const hubBadge = (b) => {
  const s = document.createElement("span");
  s.className = `badge ${b.cls}`; s.textContent = b.label;
  return s;
};
const hubHead = (prettyName, cardPath, badge) => {
  const h = document.createElement("div");
  h.className = "dshead";
  const nm = document.createElement("span");
  nm.className = "nm";
  if (cardPath) {
    const a = document.createElement("a");
    a.href = REPO_BASE + cardPath; a.target = "_blank"; a.rel = "noopener";
    a.textContent = prettyName;
    nm.append(a);
  } else nm.textContent = prettyName;
  h.append(nm, hubBadge(badge));
  return h;
};
const hubChips = (tags) => {
  const tg = document.createElement("div");
  for (const t of tags) {
    const c = document.createElement("span");
    c.className = "chip"; c.textContent = t;
    tg.append(c);
  }
  return tg;
};
function renderHubRegistry() {
  const el = $("hubreg");
  el.replaceChildren();
  if (!hubReg || !hubReg.count) return offline(el, "no artifacts in the registry yet");

  if (hubReg.datasets.length) {
    el.append(P("Datasets", "hubsec"));
    for (const d of hubReg.datasets) {
      const block = document.createElement("div");
      block.className = "dsblock";
      block.append(hubHead(d.prettyName, d.cardPath, d.badge));
      const stats = [];
      if (Number.isFinite(d.rows)) stats.push(`${d.rows.toLocaleString()} rows`);
      if (Number.isFinite(d.nFields)) stats.push(`${d.nFields} fields`);
      if (d.sizeCategory) stats.push(d.sizeCategory);
      if (d.license) stats.push(d.license.toUpperCase());
      block.append(line(d.taskCategories[0] ?? d.kind, stats.join(" · ") || "—"));
      if (d.integrity.sha256short) {
        const src = d.integrity.sourceCount ? ` · ${d.integrity.sourceCount} source sha` : "";
        block.append(line("integrity", `sha256 ${d.integrity.sha256short}…${src}`));
      }
      if (d.tags.length) block.append(hubChips(d.tags));
      if (d.summary) block.append(P(d.summary, "note"));
      el.append(block);
    }
  }

  if (hubReg.models.length) {
    el.append(P("Models", "hubsec"));
    for (const m of hubReg.models) {
      const block = document.createElement("div");
      block.className = "dsblock";
      block.append(hubHead(m.prettyName, m.cardPath, m.badge));
      const a = m.arch;
      const ab = [];
      if (Number.isFinite(a.dModel)) ab.push(`${a.dModel}d`);
      if (Number.isFinite(a.nLayers)) ab.push(`${a.nLayers}L`);
      if (a.jspaceSplit) ab.push(`(${a.jspaceSplit})`);
      if (a.mlp) ab.push(a.mlp);
      block.append(line(a.preset ? `arch · ${a.preset}` : "arch", ab.join(" · ") || "—"));
      if (a.paramsNote) block.append(line("params", a.paramsNote));
      if (Number.isFinite(m.eval.value)) {
        const tok = Number.isFinite(m.eval.tokens) ? ` · ${(m.eval.tokens / 1e6).toFixed(2)}M tok` : "";
        block.append(line(m.eval.metric ?? "eval", `${m.eval.value.toLocaleString()}${tok}`));
      }
      // the differentiator: a retracted number is shown, named, never dropped
      if (m.eval.retracted) block.append(P(`⚠ retracted (do not cite): ${m.eval.retracted}`, "retracted"));
      if (m.license) block.append(line("license", m.license.toUpperCase()));
      if (m.tags.length) block.append(hubChips(m.tags));
      if (m.summary) block.append(P(m.summary, "note"));
      el.append(block);
    }
  }

  el.append(P(`${hubReg.count} artifact${hubReg.count === 1 ? "" : "s"} · badge = provenance class ` +
    "per data_provenance_SOP.md (REAL measured · HONEST-SYNTHETIC labelled · PLACEHOLDER " +
    "stand-in); retracted numbers are named, never dropped — no card renders without provenance", "note"));
}

function renderSites(h) {
  const el = $("sites");
  el.replaceChildren();
  if (!h?.sites) return offline(el);
  el.append(table(["site", "status", "24h|r", "latency|r"],
    h.sites.map((s) => {
      let nameCell = s.name;
      if (s.url) {
        nameCell = document.createElement("a");
        nameCell.href = s.url;
        nameCell.target = "_blank";
        nameCell.rel = "noopener";
        nameCell.textContent = s.name;
      }
      return [nameCell, withLed(s.up, s.up ? " up" : " down"),
        Number.isFinite(s.up24) ? `${s.up24}%` : "—",
        Number.isFinite(s.ms) ? `${s.ms}ms` : "—"];
    })));
  el.append(P("24h = share of real probes up over the rolling day (10-min cadence)", "note"));
}

function renderDeploys(h) {
  const el = $("deploys");
  el.replaceChildren();
  if (!h?.deploys) return offline(el);
  el.append(table(["project", "updated|r"],
    h.deploys.map((p) => {
      let nameCell = p.name;
      if (p.url) {
        nameCell = document.createElement("a");
        nameCell.href = p.url;
        nameCell.target = "_blank";
        nameCell.rel = "noopener";
        nameCell.textContent = p.name;
      }
      return [nameCell, p.updated];
    })));
  el.append(P("read-only, from vercel ls at each publish — deploys stay CLI/steer-gated", "note"));
}

function renderDemand() {
  const el = $("demand");
  el.replaceChildren();
  const d = twin?.org?.demand;
  if (twin?.source !== "local" || !d) return offline(el);
  el.append(line("trainer step seen", String(d.step ?? "?")));
  for (const r of d.reasons) el.append(P(`◦ ${r}`, "note"));
}

// Fleet control (operator 2026-07-22): pick a container + verb -> the
// `fleet: <verb> <name>` command is copied and STEER opens. GitHub login
// gates execution (owner comments only; box-side allowlist) — visitors can
// click freely and steer nothing.
const STEER_URL = "https://gist.github.com/jcdavis131/c899ef776dcb81e99319239efa0f92ba";
let fleetSel = null;
function renderFleet(f) {
  const el = $("fleet");
  el.replaceChildren();
  if (f?.source !== "local" || !Array.isArray(f.containers)) return offline(el, f?.detail);
  el.append(table(["container", "team", "cpu|r", "memory|r"],
    [...f.containers].sort((a, b) => (b.cpuPct ?? 0) - (a.cpuPct ?? 0))
      .map((c) => [withLed((c.cpuPct ?? 0) >= 1 ? true : null, ` ${c.short}`),
        c.dept, `${c.cpuPct ?? "?"}%`, c.mem ?? "?"])));
  const bar = document.createElement("div");
  bar.className = "fleetact";
  const sel = document.createElement("select");
  for (const c of [...f.containers].sort((a, b) => a.short.localeCompare(b.short))) {
    const o = document.createElement("option");
    o.value = c.short;
    o.textContent = c.short;
    if (c.short === fleetSel) o.selected = true;
    sel.append(o);
  }
  fleetSel = fleetSel ?? sel.value;
  sel.addEventListener("change", () => { fleetSel = sel.value; });
  bar.append(sel);
  for (const verb of ["restart", "stop", "start"]) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = verb;
    b.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(`fleet: ${verb} ${fleetSel}`); } catch { /* gist still opens */ }
      open(STEER_URL, "_blank", "noopener");
    });
    bar.append(b);
  }
  el.append(bar);
  el.append(P("copies the command + opens STEER — GitHub login gates execution " +
    "(owner-only, allowlisted verbs/targets); visitors are read-only", "note"));
  if (f.via === "gist-feed") el.append(P(`snapshot from the box's published feed (${fmtDur(f.ageS)} old)`, "note"));
}

// Guide — "what should I do next": the deterministic digest (nextActions) that
// ranks the org's REAL open items (alerts + research queue + fleet health) into
// the assistant card, each with its owning team and, where unambiguous, a steer
// command (copy + open STEER, the same owner-gated write path as fleet control).
// Renders from twin + fleet; a healthy org honestly shows "unblocked".
function renderGuide() {
  const el = $("guide");
  if (!el) return;
  el.replaceChildren();
  const na = nextActions(twin, Array.isArray(fleet?.containers) ? fleet.containers : null);
  const head = document.createElement("div");
  head.className = "rowline";
  const k = document.createElement("span"); k.className = "k"; k.textContent = "what to do next";
  const v = document.createElement("span"); v.className = "v";
  v.textContent = na.count ? `${na.count} open` : "org unblocked";
  head.append(k, v);
  el.append(head);
  if (!na.count) return void el.append(P("nothing queued — no real alerts, no pending reviews", "note"));
  for (const a of na.actions) {
    const row = document.createElement("div");
    row.className = "alert";
    const who = document.createElement("div");
    who.className = "who";
    who.append(led(a.severity === "normal" ? null : false),
      document.createTextNode(` ${a.severity.toUpperCase()} · ${a.team} team`));
    row.append(who, P(a.label));
    if (a.steerCmd) {
      const barEl = document.createElement("div");
      barEl.className = "fleetact";
      const code = document.createElement("span");
      code.className = "mono"; code.textContent = a.steerCmd;
      const b = document.createElement("button");
      b.type = "button"; b.textContent = "copy + STEER";
      b.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(a.steerCmd); } catch { /* gist still opens */ }
        open(STEER_URL, "_blank", "noopener");
      });
      barEl.append(code, b);
      row.append(barEl);
    }
    el.append(row);
  }
}

async function refreshTwin() {
  try { twin = await (await fetch("/api/twin-status")).json(); }
  catch { twin = { source: "offline", detail: "console cannot reach its own API" }; }
  $("feedsub").textContent = twin.source === "local"
    ? `live · ${twin.via ?? "local"}${Number.isFinite(twin.ageS) ? ` · ${fmtDur(twin.ageS)} old` : ""}`
    : "offline";
  $("prov").textContent = `provenance: ${twinLine(twin)}`;
  const h = twin.source === "local" ? parseHub(twin) : null;
  renderRun(); renderCurve(); renderSignals(); renderBatch(h); renderAlerts();
  renderCurriculum(); renderFlow(); renderManifest();
  renderCkpts(); renderCompute(); renderNetwork(h); renderWatch(); renderJspace();
  renderResearch(h); renderEvals(h); renderEco(h); renderSites(h); renderDeploys(h); renderDemand();
  renderGuide();
}
async function refreshFleet() {
  try { fleet = await (await fetch("/api/fleet")).json(); } catch { fleet = { source: "offline" }; }
  renderFleet(fleet);
  renderGuide(); // fleet health feeds the digest
}

$("askform").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("askq");
  const text = q.value.trim();
  if (!text) return;
  q.value = "";
  const log = $("chatlog");
  log.prepend(P(`you: ${text}`));
  try {
    const r = await fetch("/api/assistant-chat", { method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt: text }) });
    const d = await r.json();
    const re = document.createElement("p");
    const src = document.createElement("span");
    src.className = "src";
    src.textContent = `dottie [${d.source}] `;
    re.append(src, document.createTextNode(d.reply));
    log.prepend(re);
  } catch { log.prepend(P("dottie [offline]: unreachable")); }
});

refreshTwin(); refreshFleet(); loadHubRegistry();
setInterval(refreshTwin, 15_000);
setInterval(refreshFleet, 10_000);
// hub registry is a static committed artifact — load once, no poll.
