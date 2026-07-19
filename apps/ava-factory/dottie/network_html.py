"""Live neural-network visualizer HTML (no CDN). Polls ``/network/status``."""

NETWORK_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Ava network</title>
<style>
:root {
  --bg: #0f1419;
  --ink: #e7ecef;
  --muted: #8b9aab;
  --line: #2a3542;
  --card: #161d26;
  --ok: #3d9a6a;
  --warn: #c4a04a;
  --bad: #c45a5a;
  --accent: #4a9fd8;
  --text: #5a8f9a;
  --fusion: #6b7fd7;
  --jspace: #c97b4a;
  --reason: #7a9e5a;
  --io: #8a8a9a;
  --router: #b56bc7;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
  background:
    radial-gradient(1200px 600px at 10% -10%, #1a2838 0%, transparent 55%),
    radial-gradient(900px 500px at 100% 0%, #1e2230 0%, transparent 50%),
    var(--bg);
  color: var(--ink);
  min-height: 100vh;
}
header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.85rem 1.4rem; border-bottom: 1px solid var(--line);
  background: rgba(22,29,38,0.92); backdrop-filter: blur(8px);
  position: sticky; top: 0; z-index: 5;
}
header h1 { margin: 0; font-size: 1.05rem; font-weight: 600; letter-spacing: -0.02em; }
header .meta { color: var(--muted); font-size: 0.8rem; }
header a { color: var(--accent); text-decoration: none; margin-left: 0.75rem; }
header a:hover { text-decoration: underline; }
.pill {
  display: inline-block; padding: 0.12rem 0.55rem; border-radius: 999px;
  font-size: 0.72rem; font-weight: 600; border: 1px solid var(--line);
  background: var(--card); color: var(--muted); margin-left: 0.5rem;
}
.pill.ok { color: var(--ok); border-color: #2d5a42; }
.pill.warn { color: var(--warn); border-color: #6a5530; }
main {
  display: grid;
  grid-template-columns: 1.35fr 0.85fr;
  gap: 0.85rem;
  padding: 0.95rem 1.4rem 1.6rem;
  max-width: 1400px;
  margin: 0 auto;
}
@media (max-width: 980px) { main { grid-template-columns: 1fr; } }
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: 4px;
  padding: 0.85rem 1rem;
}
.card h2 {
  margin: 0 0 0.6rem 0; font-size: 0.7rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
}
.narrative {
  grid-column: 1 / -1;
  border-left: 3px solid var(--accent);
  font-size: 0.98rem; line-height: 1.45;
}
.narrative b { color: #fff; }
#graphWrap {
  position: relative; overflow: auto; min-height: 420px;
  background:
    linear-gradient(var(--line) 1px, transparent 1px) 0 0 / 24px 24px,
    linear-gradient(90deg, var(--line) 1px, transparent 1px) 0 0 / 24px 24px,
    #121820;
  border-radius: 3px; border: 1px solid var(--line);
}
svg#net { display: block; width: 100%; min-width: 720px; height: 480px; }
.node-rect { stroke-width: 1.5; rx: 6; }
.node-rect.io { fill: #1c222c; stroke: var(--io); }
.node-rect.text { fill: #15262b; stroke: var(--text); }
.node-rect.fusion { fill: #1a1f38; stroke: var(--fusion); }
.node-rect.jspace { fill: #2a1e14; stroke: var(--jspace); }
.node-rect.workspace { fill: #241a12; stroke: #a86a3a; }
.node-rect.router { fill: #261828; stroke: var(--router); }
.node-rect.reasoning { fill: #1a2618; stroke: var(--reason); }
.node-rect.hot { filter: drop-shadow(0 0 6px rgba(74,159,216,0.55)); }
.node-label {
  fill: var(--ink); font-size: 11px; font-family: "IBM Plex Sans", sans-serif;
  text-anchor: middle; dominant-baseline: middle; pointer-events: none;
}
.node-sub {
  fill: var(--muted); font-size: 9px; font-family: "IBM Plex Sans", sans-serif;
  text-anchor: middle; pointer-events: none;
}
.edge { stroke: #3a4a5a; stroke-width: 1.4; fill: none; opacity: 0.85; }
.edge.live { stroke: var(--accent); stroke-width: 2; opacity: 1; }
.legend { display: flex; flex-wrap: wrap; gap: 0.55rem; margin-top: 0.55rem; font-size: 0.72rem; color: var(--muted); }
.legend span::before {
  content: ""; display: inline-block; width: 0.55rem; height: 0.55rem;
  border-radius: 2px; margin-right: 0.28rem; vertical-align: -0.05rem;
  background: currentColor;
}
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 0.45rem 0.7rem; }
.stat .k { font-size: 0.65rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.stat .v { font-size: 1.05rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.bar-row { display: flex; align-items: center; gap: 0.45rem; margin: 0.28rem 0; font-size: 0.8rem; }
.bar-row .lab { width: 5.2rem; color: var(--muted); }
.bar-track { flex: 1; height: 0.55rem; background: #0d1218; border-radius: 99px; overflow: hidden; }
.bar-fill { height: 100%; background: linear-gradient(90deg, #2a6a90, var(--accent)); border-radius: 99px; transition: width 0.4s ease; }
.bar-row .num { width: 2.6rem; text-align: right; font-variant-numeric: tabular-nums; font-size: 0.75rem; }
.hl-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem; margin-top: 0.35rem; }
.hl-card {
  background: #121820; border: 1px solid var(--line); border-radius: 3px;
  padding: 0.4rem 0.5rem; font-size: 0.78rem;
}
.hl-card .nm { color: var(--muted); font-size: 0.65rem; text-transform: uppercase; }
.hl-card .vl { font-weight: 600; font-variant-numeric: tabular-nums; font-size: 1rem; }
.norm-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; margin-top: 0.35rem; }
.norm-table th, .norm-table td {
  text-align: left; padding: 0.28rem 0.35rem; border-bottom: 1px solid var(--line);
  font-variant-numeric: tabular-nums;
}
.norm-table th { color: var(--muted); font-weight: 500; font-size: 0.65rem; text-transform: uppercase; }
.muted { color: var(--muted); font-size: 0.8rem; }
.hint { margin-top: 0.55rem; font-size: 0.72rem; color: var(--muted); line-height: 1.4; }
</style>
</head>
<body>
<header>
  <div>
    <h1>Ava network</h1>
    <span class="pill" id="modePill">—</span>
  </div>
  <div class="meta">
    <span id="preset">—</span>
    · <span id="clock">—</span>
    · poll 4s
    <a href="/dashboard">dashboard</a>
    <a href="/report">report</a>
    <a href="/network/status">json</a>
    <a href="/jspace/viewer">j-lens</a>
  </div>
</header>
<main>
  <section class="card narrative" id="narrative">Loading network…</section>

  <section class="card">
    <h2>Architecture · live flow</h2>
    <div id="graphWrap"><svg id="net" viewBox="0 0 900 480" preserveAspectRatio="xMidYMid meet"></svg></div>
    <div class="legend">
      <span style="color:var(--text)">text</span>
      <span style="color:var(--fusion)">fusion</span>
      <span style="color:var(--jspace)">j-space</span>
      <span style="color:var(--reason)">reasoning</span>
      <span style="color:var(--router)">router</span>
      <span style="color:var(--io)">io</span>
    </div>
    <p class="hint" id="archHint">—</p>
  </section>

  <section class="card">
    <h2>Live peel · trainer metrics</h2>
    <div class="stats" id="liveStats"></div>
    <h2 style="margin-top:0.9rem">Route mass</h2>
    <div id="routes"></div>
    <h2 style="margin-top:0.9rem">Half-lives (est.)</h2>
    <div class="hl-grid" id="hls"></div>
    <h2 style="margin-top:0.9rem">Checkpoint weight RMS
      <button id="peekBtn" type="button" style="margin-left:0.5rem;font-size:0.65rem;padding:0.15rem 0.45rem;cursor:pointer;background:#1e2a38;color:var(--accent);border:1px solid var(--line);border-radius:3px;">Peek</button>
    </h2>
    <div id="norms" class="muted">Click Peek to load CPU weight-group norms (cached; ~1× per ckpt).</div>
    <p class="hint">CPU-only peek of latest ``.pt`` — never shares the trainer GPU. J-lens forward probes need engine boot (post-train).</p>
  </section>
</main>
<script>
const POLL_MS = 4000;
let lastNorms = null;
let peeking = false;

const KIND_W = { io: 88, text: 78, fusion: 78, jspace: 120, workspace: 100, router: 78, reasoning: 78 };
const KIND_H = { io: 44, text: 44, fusion: 44, jspace: 56, workspace: 48, router: 44, reasoning: 44 };

function fmt(n) {
  if (n == null || Number.isNaN(n)) return "—";
  if (Math.abs(n) >= 1e6) return (n/1e6).toFixed(2) + "M";
  if (Math.abs(n) >= 1e3) return (n/1e3).toFixed(1) + "k";
  return Number(n).toFixed(Number.isInteger(n) ? 0 : 3);
}
function fmtTs(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString();
}

function layout(arch) {
  // Column layouts by regime — left-to-right training dataflow.
  const cols = {
    embed: 40,
    text: 140,
    fusion: 280,
    jspace: 430,
    workspace: 560,
    router: 560,
    reason: 700,
    lm: 820,
  };
  const pos = {};
  const texts = arch.nodes.filter(n => n.kind === "text");
  const fusions = arch.nodes.filter(n => n.kind === "fusion");
  const reasons = arch.nodes.filter(n => n.kind === "reasoning");
  const workspaces = arch.nodes.filter(n => n.kind === "workspace");

  for (const n of arch.nodes) {
    if (n.id === "embed") pos[n.id] = { x: cols.embed, y: 210 };
    else if (n.id === "jspace") pos[n.id] = { x: cols.jspace, y: 200 };
    else if (n.id === "router") pos[n.id] = { x: cols.router, y: 380 };
    else if (n.id === "lm_head") pos[n.id] = { x: cols.lm, y: 210 };
  }
  texts.forEach((n, i) => {
    const span = Math.max(texts.length - 1, 1);
    pos[n.id] = { x: cols.text, y: 60 + i * (360 / span) };
  });
  fusions.forEach((n, i) => {
    const span = Math.max(fusions.length - 1, 1);
    pos[n.id] = { x: cols.fusion, y: 60 + i * (360 / span) };
  });
  workspaces.forEach((n, i) => {
    pos[n.id] = { x: cols.workspace, y: 40 + i * 72 };
  });
  reasons.forEach((n, i) => {
    const span = Math.max(reasons.length - 1, 1);
    pos[n.id] = { x: cols.reason, y: 80 + i * (320 / span) };
  });
  return pos;
}

function drawGraph(arch, live) {
  const svg = document.getElementById("net");
  const pos = layout(arch);
  const ns = "http://www.w3.org/2000/svg";
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  // Defs for arrowheads
  const defs = document.createElementNS(ns, "defs");
  defs.innerHTML = `<marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#3a4a5a"/></marker>`;
  svg.appendChild(defs);

  const hotIds = new Set(["jspace", "router"]);
  if (live && live.available) {
    hotIds.add("jspace");
    for (const s of (arch.spaces || [])) hotIds.add("ws_" + s);
  }

  for (const e of arch.edges) {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) continue;
    const line = document.createElementNS(ns, "path");
    const ax = a.x + (KIND_W[arch.nodes.find(n=>n.id===e.from)?.kind] || 80) / 2;
    const ay = a.y;
    const bx = b.x - (KIND_W[arch.nodes.find(n=>n.id===e.to)?.kind] || 80) / 2;
    const by = b.y;
    const mx = (ax + bx) / 2;
    line.setAttribute("d", `M${ax},${ay} C${mx},${ay} ${mx},${by} ${bx},${by}`);
    line.setAttribute("class", "edge" + (hotIds.has(e.from) || hotIds.has(e.to) ? " live" : ""));
    line.setAttribute("marker-end", "url(#arrow)");
    svg.appendChild(line);
  }

  for (const n of arch.nodes) {
    const p = pos[n.id];
    if (!p) continue;
    const w = KIND_W[n.kind] || 80;
    const h = KIND_H[n.kind] || 44;
    const g = document.createElementNS(ns, "g");
    const rect = document.createElementNS(ns, "rect");
    rect.setAttribute("x", p.x - w/2);
    rect.setAttribute("y", p.y - h/2);
    rect.setAttribute("width", w);
    rect.setAttribute("height", h);
    rect.setAttribute("class", "node-rect " + n.kind + (hotIds.has(n.id) ? " hot" : ""));
    g.appendChild(rect);

    const lines = (n.label || n.id).split("\n");
    lines.forEach((t, i) => {
      const text = document.createElementNS(ns, "text");
      text.setAttribute("x", p.x);
      text.setAttribute("y", p.y + (i - (lines.length-1)/2) * 12);
      text.setAttribute("class", i === 0 ? "node-label" : "node-sub");
      text.textContent = t;
      g.appendChild(text);
    });

    // Live badge on workspaces: hl estimate
    if (n.kind === "workspace" && live && live.hl_est && n.space != null) {
      const hl = live.hl_est[n.space];
      if (hl != null) {
        const badge = document.createElementNS(ns, "text");
        badge.setAttribute("x", p.x);
        badge.setAttribute("y", p.y + h/2 + 12);
        badge.setAttribute("class", "node-sub");
        badge.setAttribute("fill", "#4a9fd8");
        badge.textContent = "hl " + Math.round(hl);
        g.appendChild(badge);
      }
    }
    svg.appendChild(g);
  }
}

function renderLive(d) {
  const live = d.live || {};
  const arch = d.architecture || {};
  document.getElementById("preset").textContent = d.preset || "—";
  document.getElementById("clock").textContent = fmtTs(d.ts);
  const mode = (d.mode && d.mode.label) || (d.mode && d.mode.id) || "—";
  const pill = document.getElementById("modePill");
  pill.textContent = mode;
  pill.className = "pill " + ((d.mode && d.mode.id === "training") ? "ok" : "warn");

  const tpp = d.tokens_per_param;
  const parts = [];
  if (live.available) {
    parts.push(`Watching <b>${d.preset}</b> at step <b>${fmt(live.step)}</b> (phase P${live.phase ?? "—"}).`);
    parts.push(`lm <b>${live.lm_loss != null ? Number(live.lm_loss).toFixed(3) : "—"}</b> · ~${live.tok_s != null ? fmt(Math.round(live.tok_s)) : "—"} tok/s · grad ${live.grad_norm != null ? Number(live.grad_norm).toFixed(2) : "—"}.`);
  } else {
    parts.push(`Architecture for <b>${d.preset}</b> is ready; waiting for trainer metrics.`);
  }
  if (tpp && tpp.tpp != null) {
    parts.push(`Scale <b>${Number(tpp.tpp).toFixed(1)} TPP</b> (${tpp.regime}).`);
  }
  parts.push(`${fmt(arch.params_analytic)} analytic params · d=${arch.d_model} · ${arch.n_layers} layers (${arch.n_text}/${arch.n_fusion}/${arch.n_reasoning}).`);
  document.getElementById("narrative").innerHTML = parts.join(" ");

  document.getElementById("archHint").textContent =
    `${arch.mlp} MLP · ${arch.n_heads} heads (kv ${arch.kv_heads}) · ` + (d.hint || "");

  drawGraph(arch, live);

  const stats = [
    ["step", live.step],
    ["lm loss", live.lm_loss != null ? Number(live.lm_loss).toFixed(3) : "—"],
    ["tok/s", live.tok_s != null ? Math.round(live.tok_s) : "—"],
    ["grad", live.grad_norm != null ? Number(live.grad_norm).toFixed(3) : "—"],
    ["mass", live.verbalizable_mass != null ? Number(live.verbalizable_mass).toFixed(3) : "—"],
    ["broadcast", live.broadcast_strength != null ? Number(live.broadcast_strength).toFixed(3) : "—"],
  ];
  document.getElementById("liveStats").innerHTML = stats.map(([k,v]) =>
    `<div class="stat"><div class="k">${k}</div><div class="v">${v ?? "—"}</div></div>`
  ).join("");

  const routes = live.route_probs || {};
  const rnames = arch.route_names || Object.keys(routes);
  document.getElementById("routes").innerHTML = rnames.map(name => {
    const p = routes[name];
    const pct = p != null ? Math.round(p * 100) : 0;
    return `<div class="bar-row"><div class="lab">${name}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      <div class="num">${p != null ? (p*100).toFixed(0)+"%" : "—"}</div></div>`;
  }).join("") || `<p class="muted">No route_probs yet</p>`;

  const hl = live.hl_est || {};
  const spaces = arch.spaces || Object.keys(hl);
  document.getElementById("hls").innerHTML = spaces.map(s => {
    const tgt = (arch.nodes.find(n => n.space === s) || {}).hl_target;
    return `<div class="hl-card"><div class="nm">${s}</div>
      <div class="vl">${hl[s] != null ? Math.round(hl[s]) : "—"}</div>
      <div class="muted">tgt ${tgt ?? "—"}</div></div>`;
  }).join("");

  const norms = (d.ckpt && d.ckpt.norms) || lastNorms;
  const el = document.getElementById("norms");
  if (!norms) {
    el.innerHTML = `<span class="muted">No checkpoint on disk yet (or peek skipped).</span>`;
  } else if (norms.skipped) {
    el.innerHTML = `<span class="muted">Skipped: ${norms.reason || "too large"}</span>`;
  } else if (norms.error) {
    el.innerHTML = `<span class="muted">Error: ${norms.error}</span>`;
  } else {
    const groups = norms.groups || {};
    const rows = Object.keys(groups).sort().map(g => {
      const x = groups[g];
      return `<tr><td>${g}</td><td>${x.rms_mean.toFixed(4)}</td><td>${x.rms_max.toFixed(4)}</td><td>${x.n}</td></tr>`;
    }).join("");
    el.innerHTML = `<table class="norm-table"><thead><tr><th>group</th><th>rms mean</th><th>rms max</th><th>tensors</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <div class="muted" style="margin-top:0.35rem">${norms.n_params ? fmt(norms.n_params)+" params · " : ""}${norms.elapsed_s || "—"}s · ${norms.path || ""}</div>`;
  }
}

async function tick() {
  try {
    const r = await fetch("/network/status");
    const d = await r.json();
    if (lastNorms && d.ckpt) d.ckpt.norms = lastNorms;
    renderLive(d);
  } catch (e) {
    document.getElementById("narrative").textContent = "network status unreachable: " + e;
  }
}
async function peekNorms() {
  if (peeking) return;
  peeking = true;
  const btn = document.getElementById("peekBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Loading…"; }
  document.getElementById("norms").innerHTML = `<span class="muted">Peeking checkpoint on CPU (may take ~1 min first time)…</span>`;
  try {
    const r = await fetch("/network/status?norms=1");
    const d = await r.json();
    if (d.ckpt && d.ckpt.norms) lastNorms = d.ckpt.norms;
    if (lastNorms) {
      d.ckpt = d.ckpt || {};
      d.ckpt.norms = lastNorms;
      renderLive(d);
    }
  } catch (e) {
    document.getElementById("norms").innerHTML = `<span class="muted">Peek failed: ${e}</span>`;
  } finally {
    peeking = false;
    if (btn) { btn.disabled = false; btn.textContent = "Peek"; }
  }
}
document.getElementById("peekBtn").addEventListener("click", peekNorms);
tick();
setInterval(tick, POLL_MS);
</script>
</body>
</html>
"""
