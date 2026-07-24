// BLUEHENRE mobile command console (operator directive 2026-07-22): check the
// org from a phone — run status, fleet, alerts, Dottie chat, sites. Same data
// spine and provenance doctrine as everything else: numbers render only from
// source:"local" feeds; everything else says offline, honestly.
import { twinLine, parseHub, nextActions, parseHubRegistry } from "./twin.mjs";

const $ = (id) => document.getElementById(id);
const esc = (el, text) => { el.textContent = text; return el; };
const line = (k, v, cls = "") => {
  const d = document.createElement("div");
  d.className = "rowline";
  const ks = document.createElement("span"); ks.className = "k"; ks.textContent = k;
  const vs = document.createElement("span"); vs.className = "v" + (cls ? " " + cls : "");
  vs.textContent = v;
  d.append(ks, vs);
  return d;
};
const fmtDur = (s) => {
  if (!Number.isFinite(s)) return "?";
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  return `${Math.floor(s / 3600)}h${String(Math.round((s % 3600) / 60)).padStart(2, "0")}m`;
};
const bar = (frac, label, phase = false) => {
  const d = document.createElement("div");
  d.className = "bar" + (phase ? " phase" : "");
  const i = document.createElement("i");
  i.style.width = `${Math.max(0, Math.min(100, (frac ?? 0) * 100)).toFixed(1)}%`;
  const b = document.createElement("b"); b.textContent = label;
  d.append(i, b);
  return d;
};

let twin = null;

function renderRun() {
  const el = $("run");
  el.replaceChildren();
  if (twin?.source !== "local") {
    el.append(esc(document.createElement("p"),
      twin?.detail ?? "feed offline — this build cannot see the training box"));
    return;
  }
  const dash = twin.dashboard ?? {};
  if (dash.mode) {
    const m = document.createElement("div");
    m.className = `mode ${dash.mode.id}`;
    m.textContent = `● ${dash.mode.label.toUpperCase()}`;
    m.title = dash.mode.detail ?? "";
    el.append(m);
  }
  el.append(
    line("step · loss", `${twin.step ?? "?"} · ${Number.isFinite(twin.lm) ? twin.lm.toFixed(4) : "?"}`),
    line("heldout ppl", Number.isFinite(twin.weightedPpl) ? twin.weightedPpl.toFixed(1) : "—"),
  );
  if (dash.timing)
    el.append(line("throughput · eta",
      `${Number.isFinite(dash.timing.tokS) ? Math.round(dash.timing.tokS).toLocaleString() : "?"} tok/s · ${fmtDur(dash.timing.etaS)}`));
  if (Number.isFinite(dash.ckptAgeS)) el.append(line("checkpoint", `${fmtDur(dash.ckptAgeS)} ago`));
  if (Number.isFinite(dash.run?.frac))
    el.append(bar(dash.run.frac,
      `RUN ${(dash.run.frac * 100).toFixed(1)}%${Number.isFinite(dash.run.total) ? ` of ${(dash.run.total / 1e9).toFixed(1)}B tok` : ""}`));
  if (Number.isFinite(dash.phase?.frac))
    el.append(bar(dash.phase.frac,
      `${dash.phase.name.toUpperCase()} ${(dash.phase.frac * 100).toFixed(0)}% · SEQ ${dash.phase.seq ?? "?"}`, true));
  if (Array.isArray(dash.gates) && dash.gates.length) {
    const g = document.createElement("div");
    for (const gt of dash.gates) {
      const s = document.createElement("span");
      s.style.marginRight = "12px";
      const led = document.createElement("i");
      led.className = `led ${gt.ok ? "up" : "down"}`;
      s.append(led, document.createTextNode(gt.id));
      s.title = `${gt.name}: ${gt.value}`;
      g.append(s);
    }
    el.append(g);
  }
  if (dash.funnel) {
    const f = dash.funnel;
    el.append(line("shard funnel",
      `raw ${f.raw ?? 0} · packed ${f.packed ?? 0} · used ${f.consumed ?? 0} · fail ${f.failed ?? 0}`));
  }
  if (dash.spark?.lm?.length >= 2) {
    const c = document.createElement("canvas");
    c.id = "spark";
    el.append(c);
    requestAnimationFrame(() => drawSpark(c, dash.spark));
  }
}

function drawSpark(c, spark) {
  const W = c.clientWidth * 2, H = c.clientHeight * 2;
  c.width = W; c.height = H;
  const g = c.getContext("2d");
  const lo = Math.min(...spark.lm), hi = Math.max(...spark.lm), span = hi - lo || 1;
  spark.lm.forEach((v, i) => {
    const x = Math.floor((i / Math.max(1, spark.lm.length - 1)) * (W - 6));
    const y = 6 + Math.floor((1 - (v - lo) / span) * (H - 24));
    g.fillStyle = "#0f6f80"; g.fillRect(x, y + 4, 4, Math.max(0, H - 4 - y));
    g.fillStyle = "#28e6ff"; g.fillRect(x, y, 4, 4);
  });
  g.font = "20px monospace"; g.fillStyle = "#5a7284"; g.textBaseline = "top";
  g.fillText(`LM ${hi.toFixed(3)}→${lo.toFixed(3)}  steps ${spark.steps[0]}–${spark.steps[spark.steps.length - 1]}`, 8, 4);
}

function renderBatch() {
  const el = $("batch");
  el.replaceChildren();
  const s = twin?.source === "local" ? parseHub(twin)?.sample : null;
  if (!s) { el.append(esc(document.createElement("p"), "feed offline — no batch sample")); return; }
  el.append(
    line("shard (claimed)", `${s.source} · p${s.phase ?? "?"} · ${s.state}`),
    line("doc", `${s.taskType} · ${s.docTokens ?? "?"} tok (showing ${s.shownTokens ?? "?"})`),
  );
  const t = document.createElement("div");
  t.className = "sampletext";
  t.textContent = s.text; // verbatim feed text — textContent only, never markup
  el.append(t);
  el.append(esc(Object.assign(document.createElement("p"), { className: "dimtxt" }),
    `real tokens the trainer is consuming, decoded from ${s.shard} (${s.docsInShard ?? "?"} docs); rotates each publish`));
}

function renderAlerts() {
  const el = $("alerts");
  el.replaceChildren();
  if (twin?.source !== "local") { el.append(esc(document.createElement("p"), "feed offline")); return; }
  const evs = Array.isArray(twin.events) ? twin.events : [];
  // weekly site-perf regressions surface here too (steer: flag as ALERT)
  const regressions = parseHub(twin)?.sitePerf?.regressions ?? [];
  if (!evs.length && !regressions.length) {
    const p = document.createElement("p");
    p.className = "ok-line";
    p.textContent = "● no active alerts — the org is unblocked";
    el.append(p);
    return;
  }
  for (const label of regressions) {
    const a = document.createElement("div");
    a.className = "alert";
    const who = document.createElement("div");
    who.className = "who";
    who.textContent = "site-perf regression (weekly probe)";
    const what = document.createElement("div");
    what.textContent = label;
    a.append(who, what);
    el.append(a);
  }
  for (const ev of evs) {
    const a = document.createElement("div");
    a.className = "alert";
    const who = document.createElement("div");
    who.className = "who";
    who.textContent = `${ev.kind} @ ${ev.dept} team`;
    const what = document.createElement("div");
    what.textContent = ev.label;
    a.append(who, what);
    el.append(a);
  }
}

// Fleet control (operator 2026-07-22): tap a container -> action bar -> the
// `fleet: <verb> <name>` command is copied and the STEER gist opens. The
// LOGIN IS GITHUB: only owner comments are executed by the box (closed
// verb/target allowlist there too) — visitors can tap all they like.
const STEER_URL = "https://gist.github.com/jcdavis131/c899ef776dcb81e99319239efa0f92ba";
let fleetSel = null;
let lastFleet = null;
async function fleetAct(verb) {
  const cmd = `fleet: ${verb} ${fleetSel}`;
  try { await navigator.clipboard.writeText(cmd); } catch { /* clipboard denied — gist still opens */ }
  open(STEER_URL, "_blank", "noopener");
}
function renderFleet(f) {
  lastFleet = f;
  const el = $("fleet");
  el.replaceChildren();
  if (f?.source !== "local" || !Array.isArray(f.containers)) {
    el.append(esc(document.createElement("p"), f?.detail ?? "docker feed offline"));
    return;
  }
  const t = document.createElement("table");
  t.className = "fleet";
  for (const c of [...f.containers].sort((a, b) => (b.cpuPct ?? 0) - (a.cpuPct ?? 0))) {
    const tr = document.createElement("tr");
    if (c.short === fleetSel) tr.className = "sel";
    tr.addEventListener("click", () => {
      fleetSel = fleetSel === c.short ? null : c.short;
      renderFleet(lastFleet);
    });
    const name = document.createElement("td");
    const led = document.createElement("i");
    led.className = `led ${(c.cpuPct ?? 0) >= 1 ? "up" : "idle"}`;
    name.append(led, document.createTextNode(c.short));
    const cpu = document.createElement("td");
    cpu.className = "cpu";
    const cb = document.createElement("div");
    cb.className = "cpubar" + ((c.cpuPct ?? 0) > 80 ? " hot" : "");
    const ci = document.createElement("i");
    ci.style.width = `${Math.min(100, c.cpuPct ?? 0).toFixed(0)}%`;
    cb.append(ci);
    cpu.append(cb);
    const num = document.createElement("td");
    num.style.textAlign = "right";
    num.textContent = `${c.cpuPct ?? "?"}% · ${c.mem ?? "?"}`;
    tr.append(name, cpu, num);
    t.append(tr);
  }
  el.append(t);
  if (fleetSel) {
    const bar2 = document.createElement("div");
    bar2.className = "fleetact";
    const label = document.createElement("span");
    label.textContent = `${fleetSel} →`;
    bar2.append(label);
    for (const verb of ["restart", "stop", "start"]) {
      const b = document.createElement("button");
      b.textContent = verb;
      b.addEventListener("click", () => fleetAct(verb));
      bar2.append(b);
    }
    el.append(bar2);
    el.append(esc(Object.assign(document.createElement("p"), { className: "dimtxt" }),
      "copies the command + opens STEER — operator-gated by GitHub login; " +
      "the box only executes owner comments (allowlisted verbs/targets)"));
  }
  if (f.via === "gist-feed")
    el.append(esc(Object.assign(document.createElement("p"), { className: "dimtxt" }),
      `snapshot from the box's published feed (${fmtDur(f.ageS)} old)`));
}

function renderHub() {
  const el = $("hub");
  el.replaceChildren();
  const h = twin?.source === "local" ? parseHub(twin) : null;
  if (!h) { el.append(esc(document.createElement("p"), "feed offline")); return; }
  if (h.network)
    el.append(line("model", `${h.network.preset} · ${(h.network.params / 1e6).toFixed(1)}M · ${h.network.layers}L (${h.network.split ?? "?"})`));
  if (h.ecosystem)
    el.append(line("skills ecosystem", `tools ${h.ecosystem.toolsBuilt}/${h.ecosystem.toolsTotal} · skills ${h.ecosystem.skillsTotal}`));
  if (h.evals)
    el.append(line("evals", `${h.evals.pass} PASS / ${h.evals.fail} FAIL`, h.evals.fail ? "" : "ok-line"));
  if (h.research) {
    // honesty: the research loop parks while the trainer owns the GPU — flag
    // how old its status actually is instead of presenting it as current
    const ageH = Number.isFinite(h.research.ts) ? (Date.now() / 1000 - h.research.ts) / 3600 : null;
    const stale = ageH !== null && ageH > 1 ? ` · ${ageH.toFixed(0)}h old` : "";
    el.append(line("research baseline",
      `${h.research.value?.toFixed(4) ?? "?"} ±${h.research.sem?.toFixed(3) ?? "?"} (${h.research.provenance}${stale})`));
    el.append(line("research queue",
      `pending ${h.research.pending ?? "?"} · sota ${h.research.sota ?? "?"} · rejected ${h.research.rejected ?? "?"}`));
  }
}

function renderSites() {
  const el = $("sites");
  el.replaceChildren();
  const h = twin?.source === "local" ? parseHub(twin) : null;
  if (!h?.sites) { el.append(esc(document.createElement("p"), "feed offline")); return; }
  const wrap = document.createElement("div");
  wrap.className = "sites";
  for (const s of h.sites) {
    // each site links out when the probe URL is real (parseHub validates http(s))
    const sp = document.createElement(s.url ? "a" : "span");
    if (s.url) { sp.href = s.url; sp.target = "_blank"; sp.rel = "noopener"; }
    const led = document.createElement("i");
    led.className = `led ${s.up ? "up" : "down"}`;
    sp.append(led, document.createTextNode(
      `${s.name}${Number.isFinite(s.ms) ? ` ${s.ms}ms` : ""}` +
      (Number.isFinite(s.up24) ? ` · ${s.up24}%/24h` : "")));
    // 24h trend strip: one tick per real probe (steer directive: trends)
    if (s.strip?.length) {
      const strip = document.createElement("span");
      strip.className = "upstrip";
      for (const ok of s.strip) {
        const t = document.createElement("i");
        t.className = ok ? "up" : "down";
        strip.append(t);
      }
      sp.append(strip);
    }
    wrap.append(sp);
  }
  el.append(wrap);
}

// Guide — "what should I do next" on the phone: the deterministic digest
// (nextActions) that ranks the org's REAL open items (alerts + research queue +
// fleet health), each with its team and, where unambiguous, a steer command
// (copy + open STEER — the same owner-gated write path as fleet control). This
// is the assistant's guidance surface for the operator steering from anywhere.
function renderGuide() {
  const el = $("guide");
  if (!el) return;
  el.replaceChildren();
  const na = nextActions(twin, Array.isArray(lastFleet?.containers) ? lastFleet.containers : null);
  el.append(line("what to do next", na.count ? `${na.count} open` : "org unblocked"));
  if (!na.count) {
    el.append(esc(Object.assign(document.createElement("p"), { className: "ok-line" }),
      "● nothing queued — no real alerts, no pending reviews"));
    return;
  }
  for (const a of na.actions) {
    const row = document.createElement("div");
    row.className = "alert";
    const who = document.createElement("div");
    who.className = "who";
    who.textContent = `${a.severity.toUpperCase()} · ${a.team} team`;
    row.append(who, esc(document.createElement("div"), a.label));
    if (a.steerCmd) {
      const bar2 = document.createElement("div");
      bar2.className = "fleetact";
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = "copy + STEER";
      b.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(a.steerCmd); } catch { /* gist still opens */ }
        open(STEER_URL, "_blank", "noopener");
      });
      bar2.append(esc(document.createElement("span"), `${a.steerCmd} →`), b);
      row.append(bar2);
    }
    el.append(row);
  }
}

async function refreshTwin() {
  try {
    const r = await fetch("/api/twin-status");
    twin = await r.json();
  } catch { twin = { source: "offline", detail: "console cannot reach its own API" }; }
  $("feedsub").textContent = twin.source === "local"
    ? `LIVE · ${twin.via ?? "local"}${Number.isFinite(twin.ageS) ? ` · ${fmtDur(twin.ageS)} old` : ""}`
    : "OFFLINE";
  $("prov").textContent = `provenance: ${twinLine(twin)}`;
  $("chathint").textContent = twin.source === "local" && twin.via === "pipeline-endpoint"
    ? "wired to the local Dottie engine when configured — replies are source-stamped"
    : "replies are source-stamped [dottie] or [offline] — never fabricated";
  renderRun(); renderBatch(); renderAlerts(); renderHub(); renderSites(); renderGuide();
}
async function refreshFleet() {
  let f = null;
  try { f = await (await fetch("/api/fleet")).json(); } catch { f = { source: "offline" }; }
  renderFleet(f);
  renderGuide(); // fleet health feeds the digest
}

$("askform").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("askq");
  const text = q.value.trim();
  if (!text) return;
  q.value = "";
  const log = $("chatlog");
  const you = document.createElement("p");
  you.textContent = `you: ${text}`;
  log.prepend(you);
  try {
    const r = await fetch("/api/assistant-chat", { method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt: text }) });
    const d = await r.json();
    const re = document.createElement("p");
    const src = document.createElement("span");
    src.className = "src";
    src.textContent = `dottie [${d.source}]: `;
    re.append(src, document.createTextNode(d.reply));
    log.prepend(re);
  } catch {
    log.prepend(esc(document.createElement("p"), "dottie [offline]: unreachable"));
  }
});

// Hub — the org's OWN datasets + models, each provenance-badged (the Dottie-site
// differentiator, on the phone too). Static committed artifacts from the same
// /hub_registry.json the org console uses; loaded once (not polled).
const ART_REPO = "https://github.com/jcdavis131/dottie/blob/main/";
let artifacts = null;
function artRow(prettyName, cardPath, badge) {
  const row = document.createElement("div");
  row.className = "artline";
  const nm = document.createElement("span");
  if (cardPath) {
    const a = document.createElement("a");
    a.href = ART_REPO + cardPath; a.target = "_blank"; a.rel = "noopener";
    a.textContent = prettyName;
    nm.append(a);
  } else nm.textContent = prettyName;
  const b = document.createElement("span");
  b.className = `badge ${badge.cls}`; b.textContent = badge.label;
  row.append(nm, b);
  return row;
}
function sec(text) {
  const d = document.createElement("div");
  d.className = "hubsec"; d.textContent = text;
  return d;
}
function renderArtifacts() {
  const el = $("artifacts");
  if (!el) return;
  el.replaceChildren();
  if (!artifacts || !artifacts.count) {
    el.append(esc(document.createElement("p"), "no artifacts in the registry yet"));
    return;
  }
  if (artifacts.datasets.length) {
    el.append(sec("datasets"));
    for (const d of artifacts.datasets) {
      el.append(artRow(d.prettyName, d.cardPath, d.badge));
      const bits = [];
      if (Number.isFinite(d.rows)) bits.push(`${d.rows.toLocaleString()} rows`);
      if (Number.isFinite(d.nFields)) bits.push(`${d.nFields} fields`);
      if (bits.length) el.append(line(d.taskCategories?.[0] ?? "", bits.join(" · ")));
    }
  }
  if (artifacts.models.length) {
    el.append(sec("models"));
    for (const m of artifacts.models) {
      el.append(artRow(m.prettyName, m.cardPath, m.badge));
      if (Number.isFinite(m.eval.value)) el.append(line(m.eval.metric ?? "eval", m.eval.value.toLocaleString()));
      // the differentiator, on mobile too: a retracted number is named, not dropped
      if (m.eval.retracted) el.append(esc(Object.assign(document.createElement("p"),
        { className: "retracted" }), `⚠ retracted: ${m.eval.retracted}`));
    }
  }
  el.append(esc(Object.assign(document.createElement("p"), { className: "dimtxt" }),
    `${artifacts.count} artifacts · provenance-badged (REAL / HONEST-SYNTHETIC / PLACEHOLDER)`));
}
async function loadArtifacts() {
  const el = $("artifacts");
  try { artifacts = parseHubRegistry(await (await fetch("/hub_registry.json", { cache: "no-cache" })).json()); }
  catch { if (el) el.replaceChildren(esc(document.createElement("p"), "hub registry not built")); return; }
  renderArtifacts();
}

refreshTwin(); refreshFleet(); loadArtifacts();
setInterval(refreshTwin, 15_000);
setInterval(refreshFleet, 10_000);
// hub artifacts are static committed cards — load once, no poll.
