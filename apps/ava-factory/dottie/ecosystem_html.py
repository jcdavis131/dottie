"""Self-contained ecosystem-status page HTML (no CDN).

Sibling to dottie/dashboard_html.py: that page is training-focused (loss,
curriculum, checkpoints); this one answers "what's the state of everything
*around* the model" -- the coding-agent harness, the merged skills
libraries, the agent-eval scoreboard, and curriculum-stage (TODOS.md)
progress. Same visual language (CSS variables, .card/.stat/.pill classes)
so the two pages read as one system, reachable from each other's header.
"""

ECOSYSTEM_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Dottie ecosystem</title>
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
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--ink);
  min-height: 100vh;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--line);
  background: var(--card);
}
header h1 { margin: 0; font-size: 1.25rem; font-weight: 600; letter-spacing: -0.02em; }
header .meta { color: var(--muted); font-size: 0.85rem; font-variant-numeric: tabular-nums; }
main {
  display: grid;
  grid-template-columns: 1.1fr 1fr;
  gap: 1rem;
  padding: 1rem 1.5rem 2rem;
}
@media (max-width: 960px) { main { grid-template-columns: 1fr; } }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 2px; padding: 1rem 1.1rem; }
.card h2 {
  margin: 0 0 0.75rem; font-size: 0.75rem; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--muted); font-weight: 600;
}
.span2 { grid-column: 1 / -1; }
.row { display: flex; gap: 0.75rem; flex-wrap: wrap; }
.stat {
  flex: 1 1 7rem; min-width: 6.5rem; padding: 0.6rem 0.7rem;
  border: 1px solid var(--line); background: var(--bg);
}
.stat .k { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.stat .v { font-size: 1.35rem; font-variant-numeric: tabular-nums; font-weight: 600; margin-top: 0.15rem; }
.stat .v.sm { font-size: 1rem; }
.stat .sub { font-size: 0.7rem; color: var(--muted); margin-top: 0.2rem; }
.pill {
  display: inline-block; padding: 0.15rem 0.5rem; font-size: 0.75rem;
  border: 1px solid var(--line); font-variant-numeric: tabular-nums;
}
.pill.ok { color: var(--ok); border-color: #9cbc9f; background: #e8f0e9; }
.pill.warn { color: var(--warn); border-color: #d4b56a; background: #f7efd8; }
.pill.bad { color: var(--bad); border-color: #c99; background: #f5e8e8; }
.filelist { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.3rem 0.6rem; margin-top: 0.5rem; }
.filelist .f { font-size: 0.8rem; display: flex; align-items: center; gap: 0.4rem; }
.filelist .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.filelist .dot.yes { background: var(--ok); }
.filelist .dot.no { background: var(--bad); }
.stage-list { display: grid; gap: 0.3rem; margin-top: 0.5rem; }
.stage-row {
  display: grid; grid-template-columns: 1fr 7rem 3rem; gap: 0.5rem; align-items: center;
  font-size: 0.8rem; padding: 0.3rem 0.4rem; border-bottom: 1px solid var(--line);
}
.stage-row .name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stage-bar { height: 8px; background: var(--bar); position: relative; }
.stage-bar > span { display: block; height: 100%; background: var(--bar-ok); }
.stage-bar.done > span { background: var(--ok); }
.stage-n { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; font-variant-numeric: tabular-nums; }
td, th { text-align: left; padding: 0.35rem 0.4rem; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 500; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }
.tail { margin: 0.5rem 0 0; padding: 0; list-style: none; font-size: 0.78rem; }
.tail li {
  padding: 0.35rem 0.5rem; border-left: 3px solid var(--accent);
  background: var(--bg); margin: 0.25rem 0; color: var(--ink);
  overflow-wrap: anywhere;
}
.alert {
  margin: 0 0 0.75rem; padding: 0.55rem 0.7rem; border: 1px solid #d4b56a;
  background: #f7efd8; color: var(--warn); font-size: 0.85rem;
}
.alert.bad { border-color: #c99; background: #f5e8e8; color: var(--bad); }
.muted { color: var(--muted); font-size: 0.85rem; }
a { color: var(--accent); }
</style>
</head>
<body>
<header>
  <h1>Dottie ecosystem</h1>
  <div class="meta">
    <span id="clock">—</span>
    · poll 15s
    · <a href="/ecosystem/status">json</a>
    · <a href="/dashboard">training dashboard</a>
    · <a href="/health">/health</a>
    · <a href="/report">report</a>
  </div>
</header>
<main>
  <section class="card">
    <h2>Coding-agent harness (AgenticOS)</h2>
    <div id="harnessBanner"></div>
    <div class="filelist" id="harnessFiles"></div>
  </section>

  <section class="card">
    <h2>Skills libraries</h2>
    <div id="skillsBody"></div>
  </section>

  <section class="card span2">
    <h2>Agent-eval scoreboard</h2>
    <div id="evalBody"></div>
  </section>

  <section class="card">
    <h2>Curriculum stage progress (TODOS.md)</h2>
    <div id="stagesBody" class="stage-list"></div>
  </section>

  <section class="card">
    <h2>Agentic hill-climb — recent cycles</h2>
    <ul class="tail" id="agentHillTail"></ul>
  </section>

  <section class="card span2">
    <h2>Pretraining hill-climb — recent ticks</h2>
    <ul class="tail" id="trainHillTail"></ul>
  </section>
</main>
<script>
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function renderHarness(d) {
  const banner = document.getElementById("harnessBanner");
  const files = document.getElementById("harnessFiles");
  const h = d.agenticos || {};
  if (!h.found) {
    banner.innerHTML = `<div class="alert bad">AgenticOS checkout not found under the host-disk mount.</div>`;
    files.innerHTML = "";
    return;
  }
  banner.innerHTML = `<div class="row">
    <div class="stat"><div class="k">Tool modules built</div><div class="v">${h.built}/${h.total}</div></div>
  </div>`;
  files.innerHTML = Object.entries(h.files || {}).map(([f, present]) =>
    `<div class="f"><span class="dot ${present ? "yes" : "no"}"></span>${esc(f)}</div>`
  ).join("");
}

function renderSkills(d) {
  const s = d.skills || {};
  const el = document.getElementById("skillsBody");
  if (!s.found) {
    el.innerHTML = `<div class="alert bad">No skills libraries found.</div>`;
    return;
  }
  el.innerHTML = `<div class="row">
    <div class="stat"><div class="k">Total merged</div><div class="v">${s.total}</div></div>
    <div class="stat"><div class="k">AgenticOS own</div><div class="v sm">${s.agenticos_own}</div></div>
    <div class="stat"><div class="k">cursor-agent-skills</div><div class="v sm">${s.cursor_agent_skills}</div></div>
    <div class="stat"><div class="k">addyosmani lifecycle</div><div class="v sm">${s.addyosmani_lifecycle}</div></div>
  </div>`;
}

function renderEval(d) {
  const ev = d.agent_eval || {};
  const el = document.getElementById("evalBody");
  if (!ev.found) {
    el.innerHTML = `<div class="alert bad">agent-eval checkout not found under the host-disk mount.</div>`;
    return;
  }
  const results = ev.results || [];
  const rows = results.length
    ? results.map(r => `<tr><td>${esc(r.model)}</td><td>${r.success}/${r.tasks}</td></tr>`).join("")
    : `<tr><td colspan="2" class="muted">No results/*.json yet — run scripts/run_eval.py.</td></tr>`;
  el.innerHTML = `<table><thead><tr><th>model</th><th>success</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderStages(d) {
  const t = d.todos || {};
  const el = document.getElementById("stagesBody");
  if (!t.found) {
    el.innerHTML = `<div class="alert bad">TODOS.md not found.</div>`;
    return;
  }
  el.innerHTML = (t.stages || []).map(s => {
    const pct = s.total ? Math.round(100 * s.done / s.total) : 0;
    const done = s.total > 0 && s.done === s.total;
    return `<div class="stage-row">
      <div class="name" title="${esc(s.name)}">${esc(s.name)}</div>
      <div class="stage-bar ${done ? "done" : ""}"><span style="width:${pct}%"></span></div>
      <div class="stage-n">${s.done}/${s.total}</div>
    </div>`;
  }).join("");
}

function renderTail(elId, lines) {
  const el = document.getElementById(elId);
  if (!lines || !lines.length) {
    el.innerHTML = `<li class="muted">No log yet.</li>`;
    return;
  }
  el.innerHTML = lines.slice(-6).map(l => `<li>${esc(l).slice(0, 500)}</li>`).join("");
}

async function refresh() {
  document.getElementById("clock").textContent = new Date().toLocaleTimeString();
  try {
    const r = await fetch("/ecosystem/status");
    const d = await r.json();
    renderHarness(d);
    renderSkills(d);
    renderEval(d);
    renderStages(d);
    renderTail("agentHillTail", (d.agent_eval || {}).hillclimb_tail);
    renderTail("trainHillTail", d.hillclimb_tail);
  } catch (e) {
    document.getElementById("clock").textContent = "fetch failed";
  }
}

refresh();
setInterval(refresh, 15000);
</script>
</body>
</html>
"""
