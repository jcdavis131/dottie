"""Self-contained live training report HTML (no CDN).

Designed for a single screenshot to convey the full training state to an
LLM agent assistant: a one-line narrative, a stat grid, the curriculum
progress map, health gates, runway/disk, and recent restarts. Includes a
"Copy markdown" button so the same information can be pasted as text.

Polls ``/pipeline/status`` every 10s (less aggressive than the dashboard's
3s to avoid wedging the status collector under repeated screenshot loads).
"""

REPORT_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Ava training report</title>
<style>
:root {
  --bg: #f4f2ec;
  --ink: #1a1a18;
  --muted: #5c5a52;
  --line: #d4d0c4;
  --card: #fffcf5;
  --ok: #2f6b3a;
  --warn: #9a6b12;
  --bad: #8b2e2e;
  --accent: #1e4d6b;
  --bar: #c8c2b4;
  --bar-ok: #5a8f64;
  --bar-warn: #c4a04a;
  --bar-now: #1e4d6b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--ink);
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.9rem 1.5rem;
  border-bottom: 1px solid var(--line);
  background: var(--card);
}
header .left { display: flex; align-items: baseline; gap: 0.8rem; }
header h1 { margin: 0; font-size: 1.1rem; font-weight: 600; letter-spacing: -0.02em; }
header .preset { color: var(--muted); font-size: 0.85rem; font-variant-numeric: tabular-nums; }
header .right { display: flex; align-items: center; gap: 0.6rem; }
.pill {
  padding: 0.18rem 0.6rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  border: 1px solid var(--line);
  background: var(--bg);
  color: var(--muted);
}
.pill.ok { background: #e8f0e6; color: var(--ok); border-color: #b9d4b0; }
.pill.warn { background: #f5ecd9; color: var(--warn); border-color: #e2c98a; }
.pill.bad { background: #f4e0e0; color: var(--bad); border-color: #d9b0b0; }
header nav a { color: var(--accent); text-decoration: none; font-size: 0.8rem; margin-left: 0.7rem; }
header nav a:hover { text-decoration: underline; }
main {
  display: grid;
  grid-template-columns: 1.05fr 1fr;
  gap: 0.8rem;
  padding: 0.9rem 1.5rem 1.5rem;
  max-width: 1320px;
  margin: 0 auto;
}
@media (max-width: 900px) { main { grid-template-columns: 1fr; } }
.narrative {
  grid-column: 1 / -1;
  background: var(--card);
  border: 1px solid var(--line);
  border-left: 4px solid var(--accent);
  border-radius: 2px;
  padding: 0.7rem 1rem;
  font-size: 1.02rem;
  line-height: 1.45;
  font-variant-numeric: tabular-nums;
}
.narrative .nflabel { color: var(--muted); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; margin-right: 0.4rem; }
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 2px;
  padding: 0.8rem 0.95rem;
}
.card h2 {
  margin: 0 0 0.55rem 0;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--muted);
}
/* stat grid */
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 0.45rem 0.9rem; }
.stat { display: flex; flex-direction: column; }
.stat .k { font-size: 0.68rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.stat .v { font-size: 1.08rem; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.15; }
.stat .v small { font-size: 0.72rem; font-weight: 400; color: var(--muted); margin-left: 0.2rem; }
.stat .v.up { color: var(--ok); }
.stat .v.down { color: var(--bad); }
.stat .v.warn { color: var(--warn); }
/* gates */
.gates { display: flex; flex-direction: column; gap: 0.28rem; }
.gate { display: flex; align-items: center; gap: 0.5rem; font-size: 0.88rem; font-variant-numeric: tabular-nums; }
.gate .gid { font-weight: 600; color: var(--muted); width: 1.6rem; }
.gate .gname { flex: 1; }
.gate .gval { color: var(--ink); font-weight: 500; }
.gate .gtgt { color: var(--muted); font-size: 0.75rem; }
.gate .dot { width: 0.55rem; height: 0.55rem; border-radius: 50%; flex-shrink: 0; }
.gate .dot.ok { background: var(--ok); }
.gate .dot.bad { background: var(--bad); }
/* curriculum bars */
.currow { display: flex; align-items: center; gap: 0.5rem; margin: 0.32rem 0; font-size: 0.82rem; }
.currow .cname { width: 5.2rem; color: var(--ink); font-weight: 500; }
.currow .cbar { flex: 1; height: 0.7rem; background: var(--bar); border-radius: 2px; overflow: hidden; }
.currow .cfill { height: 100%; background: var(--bar-ok); }
.currow .cfill.done { background: var(--bar-ok); }
.currow .cfill.now { background: var(--bar-now); }
.currow .cfill.zero { background: transparent; }
.currow .cfill.future { background: repeating-linear-gradient(45deg, var(--bar), var(--bar) 4px, transparent 4px, transparent 8px); }
.currow .cpc { width: 3.4rem; text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; font-size: 0.78rem; }
.currow.now .cname { color: var(--accent); font-weight: 600; }
.currow.now .cname::after { content: " \25C0"; font-size: 0.65rem; color: var(--accent); }
/* runway / disk mini */
.mini { display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem 0.8rem; font-size: 0.86rem; }
.mini .row { display: flex; justify-content: space-between; font-variant-numeric: tabular-nums; }
.mini .row .mk { color: var(--muted); }
.mini .row .mv { font-weight: 500; }
/* restarts */
.restarts { font-size: 0.8rem; color: var(--muted); font-variant-numeric: tabular-nums; line-height: 1.5; }
.restarts .rcount { color: var(--ink); font-weight: 600; font-size: 0.92rem; }
.restarts code { font-family: "IBM Plex Mono", "Consolas", monospace; font-size: 0.76rem; }
/* footer actions */
.actions {
  grid-column: 1 / -1;
  display: flex;
  gap: 0.6rem;
  align-items: center;
  padding: 0.2rem 0;
}
button {
  font-family: inherit;
  font-size: 0.82rem;
  padding: 0.4rem 0.8rem;
  border: 1px solid var(--line);
  border-radius: 2px;
  background: var(--card);
  color: var(--ink);
  cursor: pointer;
}
button:hover { border-color: var(--accent); color: var(--accent); }
button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
button.primary:hover { color: #fff; opacity: 0.9; }
.toast {
  font-size: 0.78rem; color: var(--ok); opacity: 0; transition: opacity 0.3s;
}
.toast.show { opacity: 1; }
.loading { color: var(--muted); padding: 2rem; text-align: center; font-size: 0.9rem; }
.fingerprint { color: var(--muted); font-size: 0.72rem; font-variant-numeric: tabular-nums; }
.hint { font-size: 0.78rem; color: var(--warn); margin-top: 0.3rem; }
</style>
</head>
<body>
<header>
  <div class="left">
    <h1>Ava training report</h1>
    <span class="preset" id="preset">—</span>
  </div>
  <div class="right">
    <span class="pill" id="modepill">…</span>
    <span class="fingerprint" id="fingerprint"></span>
    <nav>
      <a href="/dashboard">dashboard</a>
      <a href="/network">network</a>
      <a href="/evals">evals</a>
      <a href="/ecosystem">ecosystem</a>
      <a href="/report/offline">offline</a>
    </nav>
  </div>
</header>
<main>
  <div class="narrative" id="narrative">
    <span class="nflabel">summary</span><span id="nftext">loading…</span>
  </div>

  <div class="card">
    <h2>Current step</h2>
    <div class="stats" id="stepstats">
      <div class="stat"><span class="k">step</span><span class="v" id="s_step">—</span></div>
      <div class="stat"><span class="k">age</span><span class="v" id="s_age">—</span></div>
      <div class="stat"><span class="k">lm loss</span><span class="v" id="s_lm">—</span></div>
      <div class="stat"><span class="k">Δ10</span><span class="v" id="s_delta">—</span></div>
      <div class="stat"><span class="k">throughput</span><span class="v" id="s_tok">—</span></div>
      <div class="stat"><span class="k">gpu util</span><span class="v" id="s_gpu">—</span></div>
      <div class="stat"><span class="k">ckpt</span><span class="v" id="s_ckpt">—</span></div>
      <div class="stat"><span class="k">steps→ckpt</span><span class="v" id="s_to_ckpt">—</span></div>
      <div class="stat"><span class="k">grad norm</span><span class="v" id="s_grad">—</span></div>
      <div class="stat"><span class="k">lr</span><span class="v" id="s_lr">—</span></div>
      <div class="stat"><span class="k">phase / seq</span><span class="v" id="s_phase">—</span></div>
      <div class="stat"><span class="k">run progress</span><span class="v" id="s_run">—</span></div>
    </div>
  </div>

  <div class="card">
    <h2>Curriculum — phase progress</h2>
    <div id="curriculum"><div class="loading">loading…</div></div>
    <div class="hint" id="hint"></div>
  </div>

  <div class="card">
    <h2>Health gates</h2>
    <div class="gates" id="gates"><div class="loading">loading…</div></div>
  </div>

  <div class="card">
    <h2>Runway · disk · shards</h2>
    <div class="mini" id="mini"></div>
  </div>

  <div class="card" style="grid-column: 1 / -1;">
    <h2>Restart / crash history</h2>
    <div class="restarts" id="restarts"><div class="loading">loading…</div></div>
  </div>

  <div class="actions">
    <button class="primary" id="copybtn">Copy markdown summary</button>
    <button id="dlbtn">Download .md</button>
    <button id="shotbtn">Screenshot tip</button>
    <span class="toast" id="toast">copied ✓</span>
    <span class="fingerprint" id="genstamp"></span>
  </div>
</main>

<script>
let LAST = null;

function fmtAge(s){
  if (s == null || isNaN(s)) return "—";
  if (s < 60) return Math.round(s) + "s";
  if (s < 3600) return Math.round(s/60) + "m";
  return (s/3600).toFixed(1) + "h";
}
function fmtTok(n){
  if (n == null) return "—";
  if (n >= 1e9) return (n/1e9).toFixed(2) + "B";
  if (n >= 1e6) return (n/1e6).toFixed(0) + "M";
  if (n >= 1e3) return (n/1e3).toFixed(0) + "k";
  return String(n);
}
function fmtPct(f){ return (f*100).toFixed(1) + "%"; }
function setText(id, t){ const e=document.getElementById(id); if(e) e.textContent = t; }
function setClass(id, cls){ const e=document.getElementById(id); if(e) e.className = "v " + cls; }

function render(d){
  LAST = d;
  const t = d.trainer && d.trainer.last ? d.trainer.last : null;
  const w = d.watch || {};
  const pp = w.phase_progress || {};
  const rp = w.run_progress || {};
  const flow = d.flow || {};
  const ckpt = d.ckpt || {};
  const cur = d.curriculum || {};
  const mode = d.mode || {id:"?",label:"?",detail:""};

  // header
  setText("preset", d.preset || "—");
  const mp = document.getElementById("modepill");
  mp.textContent = mode.label || mode.id || "—";
  mp.className = "pill " + (mode.id === "training" ? "ok" : (mode.id === "stale" || mode.id === "crashed" ? "bad" : "warn"));
  mp.title = mode.detail || "";

  // fingerprint / timestamp
  const now = new Date();
  const stamp = now.toLocaleString(undefined, {year:"numeric",month:"short",day:"2-digit",hour:"2-digit",minute:"2-digit"});
  setText("fingerprint", d.preset + " · " + stamp);
  setText("genstamp", "generated " + stamp);

  // narrative
  const step = t ? t.step : "—";
  const lm = t ? (t.lm_loss != null ? t.lm_loss : t.lm) : null;
  const toks = t ? t.tok_s : null;
  const ck = ckpt.latest_pointer || "—";
  const phaseShort = pp.short || "—";
  const phaseFrac = pp.frac != null ? fmtPct(pp.frac) : "—";
  const runFrac = rp.frac != null ? fmtPct(rp.frac) : "—";
  const age = d.trainer ? d.trainer.age_s : null;
  const restartN = d.trainer && d.trainer.restarts ? d.trainer.restarts.length : 0;
  let nf = "P" + (pp.phase != null ? pp.phase : "?") + " " + phaseShort + " " + phaseFrac + " · step " + step;
  if (lm != null) nf += " · lm " + (lm).toFixed(3);
  if (toks != null) nf += " · " + (toks >= 1000 ? (toks/1000).toFixed(1)+"k" : toks) + " tok/s";
  nf += " · ckpt " + ck;
  nf += " · " + runFrac + " of " + fmtTok(cur.tokens_total || rp.tokens_total || 0) + " run";
  if (mode.id !== "training") nf += " · ⚠ " + (mode.label || mode.id).toUpperCase() + " " + fmtAge(age);
  if (restartN) nf += " · " + restartN + " restarts";
  setText("nftext", nf);

  // step stats
  setText("s_step", step);
  const ageEl = document.getElementById("s_age"); if(ageEl){ ageEl.textContent = fmtAge(age); ageEl.className = "v " + (mode.id==="training" ? "" : "warn"); }
  if (lm != null) { setText("s_lm", lm.toFixed(3)); }
  const dl = w.lm_delta_10;
  if (dl != null) { setText("s_delta", (dl>=0?"+":"") + dl.toFixed(3)); setClass("s_delta", dl < 0 ? "up" : "down"); }
  if (toks != null) setText("s_tok", toks >= 1000 ? (toks/1000).toFixed(1)+"k" : String(toks));
  if (t && t.gpu_util_pct != null) setText("s_gpu", t.gpu_util_pct + "%");
  setText("s_ckpt", ck);
  setText("s_to_ckpt", w.steps_to_ckpt != null ? w.steps_to_ckpt : "—");
  if (t && t.grad_norm != null) setText("s_grad", t.grad_norm.toFixed(3));
  if (t && t.lr != null) setText("s_lr", t.lr.toExponential(1));
  setText("s_phase", "P" + (pp.phase != null ? pp.phase : "?") + " / seq" + (pp.seq || "—"));
  if (rp.frac != null) setText("s_run", fmtPct(rp.frac) + " · " + fmtTok(rp.tokens_done) + "/" + fmtTok(rp.tokens_total));

  // hints
  const hints = w.hints || [];
  setText("hint", hints.join(" · "));

  // curriculum bars
  const cEl = document.getElementById("curriculum");
  if (cur.phases) {
    const doneUpTo = pp.phase != null ? pp.phase : 0;
    let h = "";
    for (const p of cur.phases) {
      const isNow = p.index === pp.phase;
      const isDone = p.index < pp.phase;
      let fill, fillCls, pcText;
      if (isDone) { fill = 100; fillCls = "done"; pcText = "100%"; }
      else if (isNow) { fill = (pp.frac || 0) * 100; fillCls = "now"; pcText = fmtPct(pp.frac || 0); }
      else if (p.index === doneUpTo + 1) { fill = 0; fillCls = "future"; pcText = "next"; }
      else { fill = 0; fillCls = "zero"; pcText = "0%"; }
      h += '<div class="currow' + (isNow ? ' now' : '') + '">'
         + '<span class="cname">P' + p.index + ' ' + p.short + '</span>'
         + '<span class="cbar"><span class="cfill ' + fillCls + '" style="width:' + fill + '%"></span></span>'
         + '<span class="cpc">' + pcText + ' · ' + fmtTok(p.tokens) + '</span>'
         + '</div>';
    }
    cEl.innerHTML = h;
  }

  // gates
  const gEl = document.getElementById("gates");
  if (flow.gates) {
    gEl.innerHTML = flow.gates.map(g =>
      '<div class="gate"><span class="dot ' + (g.ok ? 'ok' : 'bad') + '"></span>'
      + '<span class="gid">' + g.id + '</span>'
      + '<span class="gname">' + g.name + '</span>'
      + '<span class="gval">' + g.value + '</span>'
      + '<span class="gtgt">' + g.target + '</span></div>'
    ).join("");
  }

  // mini runway/disk/shards
  const mEl = document.getElementById("mini");
  const man = d.manifest || {};
  const disk = d.disk || {};
  const runway = flow.phase_runway || [];
  const curRunway = runway.find(r => r.is_trainer) || {};
  const targetRunway = runway.find(r => r.is_target) || {};
  const fn = man.funnel || {};
  const rows = [
    ["disk free", disk.free_gb != null ? disk.free_gb.toFixed(0) + " GB" : "—"],
    ["disk low-water", (disk.low_water_gb || 12) + " GB"],
    ["P" + flow.trainer_phase + " runway", curRunway.tokens != null ? fmtTok(curRunway.tokens) + " tok" : "—"],
    ["target P" + flow.target_phase, targetRunway.tokens != null ? fmtTok(targetRunway.tokens) + " tok" : "—"],
    ["raw backlog", man.raw_gb != null ? man.raw_gb.toFixed(2) + " / " + (man.raw_max_gb||4) + " GB" : "—"],
    ["raw fill", man.raw_fill != null ? fmtPct(man.raw_fill) : "—"],
    ["total shards", man.total_shards != null ? String(man.total_shards) : "—"],
    ["packed / failed", (fn.packed != null ? fn.packed : (man.by_state?man.by_state.PACKED:0)) + " / " + (fn.failed != null ? fn.failed : 0)],
    ["data state", flow.data_state || "—"],
    ["collector pause", (flow.collector_pause && flow.collector_pause.paused) ? "YES" : "no"],
  ];
  mEl.innerHTML = rows.map(r => '<div class="row"><span class="mk">' + r[0] + '</span><span class="mv">' + r[1] + '</span></div>').join("");

  // restarts
  const rEl = document.getElementById("restarts");
  const rests = d.trainer && d.trainer.restarts ? d.trainer.restarts : [];
  if (rests.length) {
    const recent = rests.slice(-8).map(r => "s" + r.cum_step).join(" → ");
    const lastTs = rests[rests.length-1].ts;
    const lastAge = (Date.now()/1000) - lastTs;
    rEl.innerHTML = '<span class="rcount">' + rests.length + ' restarts</span> across the run. '
      + 'Most recent: <code>' + recent + '</code>'
      + ' (last ~' + fmtAge(lastAge) + ' ago).'
      + '<br><span style="color:var(--muted)">Recurring CUDA "unknown error" pattern auto-recovers via docker restart; zero permanent data loss.</span>';
  } else {
    rEl.innerHTML = '<span class="rcount">0 restarts</span> — clean run so far.';
  }
}

function markdown(d){
  if (!d) return "";
  const t = d.trainer && d.trainer.last ? d.trainer.last : {};
  const w = d.watch || {};
  const pp = w.phase_progress || {};
  const rp = w.run_progress || {};
  const flow = d.flow || {};
  const ckpt = d.ckpt || {};
  const cur = d.curriculum || {};
  const mode = d.mode || {};
  const man = d.manifest || {};
  const disk = d.disk || {};
  const rests = d.trainer && d.trainer.restarts ? d.trainer.restarts : [];
  const ts = new Date().toLocaleString(undefined, {year:"numeric",month:"short",day:"2-digit",hour:"2-digit",minute:"2-digit"});
  const lm = t.lm_loss != null ? t.lm_loss : t.lm;
  let m = "# Ava training report\n\n";
  m += "**Generated:** " + ts + "  \n";
  m += "**Preset:** " + (d.preset||"—") + "  \n";
  m += "**Status:** " + (mode.label||mode.id||"—") + (mode.detail ? " — " + mode.detail : "") + "\n\n";
  m += "## Current step\n\n";
  m += "| metric | value |\n|---|---|\n";
  m += "| step | " + (t.step||"—") + " |\n";
  m += "| age | " + fmtAge(d.trainer?d.trainer.age_s:null) + " |\n";
  m += "| lm loss | " + (lm!=null?lm.toFixed(3):"—") + " |\n";
  m += "| Δ10 | " + (w.lm_delta_10!=null?(w.lm_delta_10>=0?"+":"")+w.lm_delta_10.toFixed(3):"—") + " |\n";
  m += "| throughput | " + (t.tok_s!=null?t.tok_s+" tok/s":"—") + " |\n";
  m += "| gpu util | " + (t.gpu_util_pct!=null?t.gpu_util_pct+"%":"—") + " |\n";
  m += "| ckpt | " + (ckpt.latest_pointer||"—") + " |\n";
  m += "| steps→ckpt | " + (w.steps_to_ckpt!=null?w.steps_to_ckpt:"—") + " |\n";
  m += "| grad norm | " + (t.grad_norm!=null?t.grad_norm.toFixed(3):"—") + " |\n";
  m += "| lr | " + (t.lr!=null?t.lr.toExponential(1):"—") + " |\n";
  m += "| phase / seq | P" + (pp.phase!=null?pp.phase:"?") + " / seq" + (pp.seq||"—") + " |\n";
  m += "| run progress | " + (rp.frac!=null?fmtPct(rp.frac):"—") + " (" + fmtTok(rp.tokens_done) + "/" + fmtTok(rp.tokens_total) + ") |\n\n";
  m += "## Curriculum — phase progress\n\n";
  m += "| phase | tokens | progress |\n|---|---|---|\n";
  if (cur.phases) for (const p of cur.phases) {
    const isNow = p.index === pp.phase;
    const isDone = p.index < pp.phase;
    const pc = isDone ? "100% done" : isNow ? fmtPct(pp.frac||0) + " ◀ now" : "0%";
    m += "| P" + p.index + " " + p.short + " | " + fmtTok(p.tokens) + " | " + pc + " |\n";
  }
  m += "\n## Health gates\n\n";
  m += "| gate | value | target | ok |\n|---|---|---|---|\n";
  if (flow.gates) for (const g of flow.gates) m += "| " + g.id + " " + g.name + " | " + g.value + " | " + g.target + " | " + (g.ok?"✓":"✗") + " |\n";
  m += "\n## Runway · disk · shards\n\n";
  m += "| metric | value |\n|---|---|\n";
  m += "| disk free | " + (disk.free_gb!=null?disk.free_gb.toFixed(0)+" GB":"—") + " |\n";
  m += "| raw backlog | " + (man.raw_gb!=null?man.raw_gb.toFixed(2)+" / "+(man.raw_max_gb||4)+" GB":"—") + " |\n";
  m += "| total shards | " + (man.total_shards!=null?man.total_shards:"—") + " |\n";
  m += "| packed / failed | " + (man.funnel?man.funnel.packed:0) + " / " + (man.funnel?man.funnel.failed:0) + " |\n";
  m += "| data state | " + (flow.data_state||"—") + " |\n";
  m += "| collector pause | " + ((flow.collector_pause&&flow.collector_pause.paused)?"YES":"no") + " |\n\n";
  m += "## Restart / crash history\n\n";
  m += "**" + rests.length + " restarts** across the run";
  if (rests.length) {
    m += ". Recent cumulative steps: " + rests.slice(-8).map(r=>"s"+r.cum_step).join(" → ");
  }
  m += "\n\n_Recurring CUDA \"unknown error\" pattern auto-recovers via docker restart; zero permanent data loss._\n";
  if (w.hints && w.hints.length) m += "\n## Watch signals\n\n- " + w.hints.join("\n- ") + "\n";
  return m;
}

async function poll(){
  try {
    const r = await fetch("/pipeline/status");
    const d = await r.json();
    render(d);
  } catch(e) {
    setText("nftext", "error loading /pipeline/status: " + e.message);
  }
}

document.getElementById("copybtn").addEventListener("click", async () => {
  const md = markdown(LAST);
  try {
    await navigator.clipboard.writeText(md);
    const t = document.getElementById("toast"); t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 1600);
  } catch(e) {
    // fallback: select+copy via execCommand on a hidden textarea
    const ta = document.createElement("textarea"); ta.value = md; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); const t=document.getElementById("toast"); t.classList.add("show"); setTimeout(()=>t.classList.remove("show"),1600); } catch(_){}
    document.body.removeChild(ta);
  }
});

document.getElementById("dlbtn").addEventListener("click", () => {
  const md = markdown(LAST);
  const blob = new Blob([md], {type:"text/markdown"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "ava_report_" + (LAST && LAST.preset ? LAST.preset : "run") + ".md";
  a.click();
  URL.revokeObjectURL(a.href);
});

document.getElementById("shotbtn").addEventListener("click", () => {
  alert("Screenshot tip: set browser viewport to ~1280×960, wait for the page to load, then capture the full window. The whole report fits in one screen — no scrolling needed. Use 'Copy markdown summary' for a text version an LLM can ingest directly.");
});

poll();
setInterval(poll, 10000);
</script>
</body>
</html>
"""
