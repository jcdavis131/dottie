// Blue Hen RE org console (www.bhenre.com): every little aspect of the org,
// rendered from real telemetry only. Same provenance doctrine as everything
// else: source:"local" or it says offline; absences render as absences.
import { twinLine, parseHub } from "./twin.mjs";

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
  if (!evs.length) {
    const p = P("● no active alerts — the org is unblocked");
    p.style.color = "var(--bh-ok)";
    el.append(p);
    return;
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

function renderSites(h) {
  const el = $("sites");
  el.replaceChildren();
  if (!h?.sites) return offline(el);
  el.append(table(["site", "status", "latency|r"],
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
        Number.isFinite(s.ms) ? `${s.ms}ms` : "—"];
    })));
}

function renderDemand() {
  const el = $("demand");
  el.replaceChildren();
  const d = twin?.org?.demand;
  if (twin?.source !== "local" || !d) return offline(el);
  el.append(line("trainer step seen", String(d.step ?? "?")));
  for (const r of d.reasons) el.append(P(`◦ ${r}`, "note"));
}

function renderFleet(f) {
  const el = $("fleet");
  el.replaceChildren();
  if (f?.source !== "local" || !Array.isArray(f.containers)) return offline(el, f?.detail);
  el.append(table(["container", "team", "cpu|r", "memory|r"],
    [...f.containers].sort((a, b) => (b.cpuPct ?? 0) - (a.cpuPct ?? 0))
      .map((c) => [withLed((c.cpuPct ?? 0) >= 1 ? true : null, ` ${c.short}`),
        c.dept, `${c.cpuPct ?? "?"}%`, c.mem ?? "?"])));
  if (f.via === "gist-feed") el.append(P(`snapshot from the box's published feed (${fmtDur(f.ageS)} old)`, "note"));
}

async function refreshTwin() {
  try { twin = await (await fetch("/api/twin-status")).json(); }
  catch { twin = { source: "offline", detail: "console cannot reach its own API" }; }
  $("feedsub").textContent = twin.source === "local"
    ? `live · ${twin.via ?? "local"}${Number.isFinite(twin.ageS) ? ` · ${fmtDur(twin.ageS)} old` : ""}`
    : "offline";
  $("prov").textContent = `provenance: ${twinLine(twin)}`;
  const h = twin.source === "local" ? parseHub(twin) : null;
  renderRun(); renderAlerts(); renderCurriculum(); renderFlow(); renderManifest();
  renderCkpts(); renderCompute(); renderNetwork(h); renderWatch(); renderResearch(h);
  renderEvals(h); renderEco(h); renderSites(h); renderDemand();
}
async function refreshFleet() {
  let f = null;
  try { f = await (await fetch("/api/fleet")).json(); } catch { f = { source: "offline" }; }
  renderFleet(f);
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
    const r = await fetch("/api/npc-chat", { method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ npc: "dottie:app", dept: "org", prompt: text }) });
    const d = await r.json();
    const re = document.createElement("p");
    const src = document.createElement("span");
    src.className = "src";
    src.textContent = `dottie [${d.source}] `;
    re.append(src, document.createTextNode(d.reply));
    log.prepend(re);
  } catch { log.prepend(P("dottie [offline]: unreachable")); }
});

refreshTwin(); refreshFleet();
setInterval(refreshTwin, 15_000);
setInterval(refreshFleet, 10_000);
