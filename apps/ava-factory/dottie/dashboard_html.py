"""Self-contained live pipeline dashboard HTML (no CDN)."""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Dottie Pipeline</title>
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
header h1 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  letter-spacing: -0.02em;
}
header .meta { color: var(--muted); font-size: 0.85rem; font-variant-numeric: tabular-nums; }
main {
  display: grid;
  grid-template-columns: 1.15fr 1fr;
  gap: 1rem;
  padding: 1rem 1.5rem 2rem;
}
@media (max-width: 960px) { main { grid-template-columns: 1fr; } }
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 2px;
  padding: 1rem 1.1rem;
}
.card h2 {
  margin: 0 0 0.75rem;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  font-weight: 600;
}
.span2 { grid-column: 1 / -1; }
.row { display: flex; gap: 0.75rem; flex-wrap: wrap; }
.stat {
  flex: 1 1 7rem;
  min-width: 6.5rem;
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--line);
  background: var(--bg);
}
.stat .k { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.stat .v { font-size: 1.35rem; font-variant-numeric: tabular-nums; font-weight: 600; margin-top: 0.15rem; }
.stat .v.sm { font-size: 1rem; }
.stat .sub { font-size: 0.7rem; color: var(--muted); margin-top: 0.2rem; }
.pill {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  font-size: 0.75rem;
  border: 1px solid var(--line);
  font-variant-numeric: tabular-nums;
}
.pill.ok { color: var(--ok); border-color: #9cbc9f; background: #e8f0e9; }
.pill.warn { color: var(--warn); border-color: #d4b56a; background: #f7efd8; }
.pill.bad { color: var(--bad); border-color: #c99; background: #f5e8e8; }
.narrative-card { border-left: 3px solid var(--accent); }
.narrative-body {
  margin: 0; font-size: 0.98rem; line-height: 1.65; color: var(--ink);
}
.narrative-body b { font-variant-numeric: tabular-nums; }
.narrative-body .warn-inline { color: var(--warn); font-weight: 600; }
.narrative-body .bad-inline { color: var(--bad); font-weight: 600; }
.mode {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
  padding: 0.85rem 1rem;
  border: 1px solid var(--line);
  background: var(--bg);
  margin-bottom: 0.85rem;
}
.mode .title { font-weight: 600; font-size: 1.05rem; }
.mode .detail { color: var(--muted); font-size: 0.85rem; margin-top: 0.2rem; }
.gates { display: grid; grid-template-columns: repeat(5, 1fr); gap: 0.45rem; }
@media (max-width: 960px) { .gates { grid-template-columns: repeat(2, 1fr); } }
.gate {
  border: 1px solid var(--line);
  padding: 0.55rem 0.6rem;
  background: var(--bg);
}
.gate.ok { border-color: #9cbc9f; }
.gate.bad { border-color: #c99; background: #faf2f2; }
.gate .id { font-size: 0.65rem; color: var(--muted); letter-spacing: 0.06em; text-transform: uppercase; }
.gate .name { font-size: 0.8rem; font-weight: 600; margin: 0.15rem 0; }
.gate .val { font-size: 0.85rem; font-variant-numeric: tabular-nums; }
.gate .tgt { font-size: 0.7rem; color: var(--muted); margin-top: 0.15rem; }
.bar-row { display: grid; grid-template-columns: 7.5rem 1fr 3.5rem; gap: 0.5rem; align-items: center; margin: 0.35rem 0; font-size: 0.85rem; font-variant-numeric: tabular-nums; }
.bar-track { height: 10px; background: var(--bar); position: relative; }
.bar-fill { height: 100%; background: var(--accent); }
.funnel { display: grid; grid-template-columns: repeat(6, 1fr); gap: 0.4rem; margin-bottom: 0.75rem; }
@media (max-width: 960px) { .funnel { grid-template-columns: repeat(3, 1fr); } }
.funnel .cell {
  border: 1px solid var(--line);
  padding: 0.45rem;
  text-align: center;
  background: var(--bg);
}
.funnel .lab { font-size: 0.65rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.funnel .num { font-size: 1.05rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.glossary { margin-top: 0.75rem; display: grid; gap: 0.35rem; }
.glossary .g-row {
  display: grid;
  grid-template-columns: 8.5rem 3rem 1fr;
  gap: 0.5rem;
  align-items: start;
  font-size: 0.8rem;
  padding: 0.35rem 0.4rem;
  border-bottom: 1px solid var(--line);
}
.glossary .g-state { font-weight: 600; font-variant-numeric: tabular-nums; }
.glossary .g-n { font-variant-numeric: tabular-nums; color: var(--muted); }
.glossary .g-help { color: var(--muted); }
.curric {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 0.4rem;
  margin-top: 0.5rem;
}
@media (max-width: 960px) { .curric { grid-template-columns: repeat(2, 1fr); } }
.curric .cphase {
  border: 1px solid var(--line);
  padding: 0.55rem 0.5rem;
  background: var(--bg);
  min-height: 5.5rem;
}
.curric .cphase.active {
  border-color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--accent);
  background: #eef4f8;
}
.curric .cphase.done { opacity: 0.55; }
.curric .cname { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.curric .ctitle { font-weight: 600; font-size: 0.9rem; margin: 0.15rem 0; }
.curric .cmeta { font-size: 0.72rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.curric .cmix { font-size: 0.68rem; color: var(--muted); margin-top: 0.35rem; line-height: 1.35; }
.curric .cfill { margin-top: 0.4rem; height: 6px; background: var(--bar); }
.curric .cfill > span { display: block; height: 100%; background: var(--accent); }
.hints { margin: 0.6rem 0 0; padding: 0; list-style: none; }
.hints li {
  font-size: 0.82rem;
  padding: 0.35rem 0.5rem;
  border-left: 3px solid var(--accent);
  background: var(--bg);
  margin: 0.25rem 0;
  color: var(--ink);
}
.hints li.warn { border-left-color: var(--warn); }
.phase-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 0.4rem; }
.phase {
  border: 1px solid var(--line);
  padding: 0.5rem;
  text-align: center;
  background: var(--bg);
  position: relative;
}
.phase.trainer { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
.phase.target:not(.trainer) { border-color: var(--warn); }
.phase .p { font-size: 0.7rem; color: var(--muted); }
.phase .n { font-size: 0.95rem; font-variant-numeric: tabular-nums; font-weight: 600; }
.phase .fill {
  margin-top: 0.35rem;
  height: 6px;
  background: var(--bar);
}
.phase .fill > span { display: block; height: 100%; background: var(--bar-ok); }
.phase.thin .fill > span { background: var(--bar-warn); }
.phase .tag {
  font-size: 0.6rem;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-top: 0.25rem;
  min-height: 0.85rem;
}
svg.chart { width: 100%; height: 180px; display: block; background: var(--bg); border: 1px solid var(--line); }
.legend { display: flex; gap: 1rem; font-size: 0.75rem; color: var(--muted); margin-top: 0.4rem; flex-wrap: wrap; }
.legend i { display: inline-block; width: 12px; height: 3px; vertical-align: middle; margin-right: 4px; }
.muted { color: var(--muted); font-size: 0.85rem; }
.alert {
  margin: 0 0 0.75rem;
  padding: 0.55rem 0.7rem;
  border: 1px solid #d4b56a;
  background: #f7efd8;
  color: var(--warn);
  font-size: 0.85rem;
}
.alert.bad { border-color: #c99; background: #f5e8e8; color: var(--bad); }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; font-variant-numeric: tabular-nums; }
td, th { text-align: left; padding: 0.35rem 0.4rem; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 500; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }
.probe { display: flex; gap: 0.5rem; margin-top: 0.5rem; }
.probe input {
  flex: 1;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--line);
  background: var(--bg);
  font: inherit;
}
.probe button {
  padding: 0.5rem 0.9rem;
  border: 1px solid var(--accent);
  background: var(--accent);
  color: #fff;
  font: inherit;
  cursor: pointer;
}
pre.out {
  margin: 0.6rem 0 0;
  padding: 0.6rem;
  background: var(--bg);
  border: 1px solid var(--line);
  font-size: 0.75rem;
  max-height: 180px;
  overflow: auto;
  white-space: pre-wrap;
}
.kv { display: grid; grid-template-columns: 7.5rem 1fr; gap: 0.25rem 0.6rem; font-size: 0.85rem; font-variant-numeric: tabular-nums; }
.kv .k { color: var(--muted); }
a { color: var(--accent); }

/* -- ELI5 tooltips: a small "?" badge next to any label; hover or focus to
   read a plain-language explainer. CSS-only (no JS listeners per element)
   and keyboard-reachable (tabindex + :focus), unlike the native `title`
   attribute it replaces. */
.tip {
  display: inline-flex; align-items: center; justify-content: center;
  width: 13px; height: 13px; margin-left: 0.3em; border-radius: 50%;
  border: 1px solid var(--muted); color: var(--muted); font-size: 0.62rem;
  font-weight: 600; font-style: normal; text-transform: none; letter-spacing: 0;
  cursor: help; position: relative; vertical-align: middle; flex: none;
}
.tip::before { content: "?"; }
.tip::after {
  content: attr(data-tip);
  position: absolute; bottom: calc(100% + 6px); left: 50%; transform: translateX(-50%);
  width: max-content; max-width: 15rem; background: var(--ink); color: var(--card);
  font-size: 0.72rem; font-weight: 400; line-height: 1.4; padding: 0.4rem 0.55rem;
  border-radius: 2px; box-shadow: 0 2px 8px rgba(20,18,10,0.25);
  opacity: 0; pointer-events: none; transition: opacity 0.1s ease; z-index: 10;
}
.tip:hover::after, .tip:focus::after { opacity: 1; }
.tip:focus { outline: 2px solid var(--accent); outline-offset: 1px; }

/* -- Manim-inspired chart grid: smooth curves, precise axes, traced dots -- */
.chart-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.7rem; margin-top: 0.6rem; }
@media (max-width: 720px) { .chart-grid { grid-template-columns: 1fr; } }
.chart-card { border: 1px solid var(--line); background: var(--bg); padding: 0.55rem 0.65rem 0.4rem; }
.chart-card h3 {
  margin: 0 0 0.3rem; font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--muted); display: flex; justify-content: space-between; align-items: baseline;
}
.chart-card h3 .cv { font-variant-numeric: tabular-nums; color: var(--ink); font-weight: 600; font-size: 0.82rem; text-transform: none; letter-spacing: 0; }
.mchart-wrap { position: relative; }
svg.mchart { width: 100%; height: 120px; display: block; overflow: visible; }
svg.mchart text { font-family: "IBM Plex Sans", "Segoe UI", sans-serif; }
.mchart-tooltip {
  position: absolute; top: 2px; pointer-events: none; background: var(--card); border: 1px solid var(--line);
  padding: 0.3rem 0.5rem; font-size: 0.7rem; box-shadow: 0 2px 8px rgba(20,18,10,0.14); z-index: 5;
  white-space: nowrap; line-height: 1.5;
}
.mchart-tooltip b { font-variant-numeric: tabular-nums; }
.mchart-tooltip span.k { border-bottom: 2px solid; padding-bottom: 1px; margin-right: 0.3rem; }
.tracer-dot { animation: tracer-pulse 1.8s ease-in-out infinite; }
@keyframes tracer-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.routebar { display: flex; height: 14px; overflow: hidden; border: 1px solid var(--line); background: var(--bar); }
.routebar > div { height: 100%; }
.eqn-card {
  border: 1px solid var(--line); background: var(--bg); padding: 0.7rem 0.85rem; margin-top: 0.5rem;
}
.eqn-line {
  font-family: "Iowan Old Style", "Palatino Linotype", Georgia, "Times New Roman", serif;
  font-style: italic; font-size: 0.98rem; line-height: 1.7; color: var(--ink);
}
.eqn-line b { font-style: normal; }
.eqn-line sub { font-style: normal; font-size: 0.7em; }
.eqn-sub { margin-top: 0.4rem; font-family: "IBM Plex Sans", "Segoe UI", sans-serif; font-style: normal; }
.aux-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(148px, 1fr)); gap: 0.5rem; margin-top: 0.6rem; }
.aux-cell { border: 1px solid var(--line); background: var(--bg); padding: 0.4rem 0.5rem 0.3rem; }
.aux-cell .lab { font-size: 0.65rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.03em; display: flex; align-items: center; gap: 0.35rem; }
.aux-cell .lab i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: none; }
.aux-cell .val { font-size: 0.92rem; font-weight: 600; font-variant-numeric: tabular-nums; margin: 0.15rem 0 0.25rem; }
svg.spark { width: 100%; height: 26px; display: block; }
.linkbtn {
  background: none; border: none; padding: 0; margin-top: 0.6rem; color: var(--accent);
  text-decoration: underline; cursor: pointer; font: inherit; font-size: 0.8rem;
}
.table-wrap { max-height: 260px; overflow: auto; margin-top: 0.5rem; display: none; border: 1px solid var(--line); }
.table-wrap.show { display: block; }
.table-wrap table { font-size: 0.72rem; }
.table-wrap th, .table-wrap td { white-space: nowrap; padding: 0.25rem 0.5rem; }
</style>
</head>
<body>
<header>
  <h1>Dottie pipeline</h1>
  <div class="meta">
    <span id="preset">—</span>
    · <span id="clock">—</span>
    · poll 3s
    · <a href="/evals">evals</a>
    · <a href="/chat">chat</a>
    · <a href="/ecosystem">ecosystem</a>
    · <a href="/pipeline/status">json</a>
    · <a href="/health">/health</a>
    · <a href="/jspace/viewer">viewer</a>
    · <a href="/report">report</a>
  </div>
</header>
<main>
  <section class="card span2 narrative-card">
    <h2>Current state<span class="tip" tabindex="0" data-tip="A plain-English paragraph, rewritten from live data every few seconds, answering &quot;what is the pipeline doing right now?&quot; so you don't have to cross-reference six panels."></span></h2>
    <p class="narrative-body" id="narrative">Loading…</p>
  </section>

  <section class="card span2">
    <h2>Operator view<span class="tip" tabindex="0" data-tip="The 30-second view: what mode the pipeline is in, plus five pass/fail gates (D1–D5). Green everywhere = nothing needs you."></span></h2>
    <div id="modeBanner"></div>
    <div class="gates" id="gates"></div>
    <div class="row" id="topStats" style="margin-top:0.85rem"></div>
  </section>

  <section class="card span2">
    <h2>Curriculum — where we are<span class="tip" tabindex="0" data-tip="The model learns in six lessons (phases), like school: logic first, then math, general knowledge, reasoning, long documents, and a final high-quality polish. Each card shows that lesson's token budget and data diet."></span></h2>
    <div id="curriculumHero"></div>
    <div class="curric" id="curriculum"></div>
    <p class="muted" id="curriculumCaption" style="margin:0.75rem 0 0">Six-phase logic-first curriculum. Active phase is outlined.</p>
  </section>

  <section class="card span2">
    <h2>Closed-loop demand (train → miners)<span class="tip" tabindex="0" data-tip="The feedback loop: the trainer regularly tells the data-gatherers what it's hungry for ('more examples', 'expand this phase'), and they re-weight their sources to match."></span></h2>
    <div id="demandPanel"></div>
    <p class="muted" style="margin:0.75rem 0 0">Only collectors fetch outside data. Trainer publishes expand / curate / examples; miners reweight sources.</p>
  </section>

  <section class="card">
    <h2>Shard lifecycle<span class="tip" tabindex="0" data-tip="Every chunk of text (a 'shard') moves through these stages: gathered raw → being cleaned → packed (ready to train on) → being read → consumed (safe to delete when disk is tight)."></span></h2>
    <div id="prepAlerts"></div>
    <div class="funnel" id="funnel"></div>
    <div class="glossary" id="lifecycleGlossary"></div>
  </section>

  <section class="card">
    <h2>Packed runway by phase<span class="tip" tabindex="0" data-tip="Fuel gauges, one per lesson: prepped tokens stacked up vs the minimum needed so the trainer never runs out mid-lesson."></span></h2>
    <div class="phase-grid" id="phases"></div>
    <p class="muted" id="runwayCaption" style="margin:0.75rem 0 0">Fill = tokens vs packed_min. Outlined = trainer phase; amber = collector target.</p>
  </section>

  <section class="card span2">
    <h2>Training — current run<span class="tip" tabindex="0" data-tip="Live vital signs of the model actually learning: how wrong its guesses are, how fast it reads, and how hard it's adjusting itself."></span></h2>
    <div id="trainAlerts"></div>
    <div class="row" id="trainStats"></div>

    <h2 style="margin-top:1rem">Loss landscape<span class="tip" tabindex="0" data-tip="Six live charts of the run. All share the same X axis: cumulative training step across the whole run (restarts don't reset it; amber ticks mark them). Hover any chart for exact values."></span></h2>
    <div class="chart-grid">
      <div class="chart-card"><h3><span>Loss — lm vs total<span class="tip" tabindex="0" data-tip="Y-axis: the loss value (lower = model is less surprised by the data = better). X-axis: cumulative training step across the WHOLE run (keeps counting up across restarts instead of resetting), not just since the last restart — amber ticks mark where the trainer crashed and resumed. Two lines: lm_loss (core prediction loss) and total (lm_loss plus all the auxiliary regularizers)."></span></span><span class="cv" id="lossCv">—</span></h3>
        <div class="mchart-wrap"><svg class="mchart" id="chartLoss"></svg></div></div>
      <div class="chart-card"><h3><span>Learning rate<span class="tip" tabindex="0" data-tip="Y-axis: the learning rate the optimizer is currently using. X-axis: cumulative training step. Follows a warmup (ramps up) then decay (ramps down) schedule."></span></span><span class="cv" id="lrCv">—</span></h3>
        <div class="mchart-wrap"><svg class="mchart" id="chartLr"></svg></div></div>
      <div class="chart-card"><h3><span>Gradient norm<span class="tip" tabindex="0" data-tip="Y-axis: gradient norm (how big a weight update the optimizer wants to make). X-axis: cumulative training step. The dashed red line is the clip threshold — values are capped there to stop the model taking a destructively large step."></span></span><span class="cv" id="gradCv">—</span></h3>
        <div class="mchart-wrap"><svg class="mchart" id="chartGrad"></svg></div></div>
      <div class="chart-card"><h3><span>Throughput<span class="tip" tabindex="0" data-tip="Y-axis: training throughput in tokens per second. X-axis: cumulative training step. Dips often line up with restarts, checkpoint writes, or the GPU being shared with something else."></span></span><span class="cv" id="tokCv">—</span></h3>
        <div class="mchart-wrap"><svg class="mchart" id="chartTok"></svg></div></div>
      <div class="chart-card"><h3><span>Workspace mass &amp; broadcast<span class="tip" tabindex="0" data-tip="Y-axis: two workspace health signals, 0 to 1. verbalizable_mass = how much of the workspace content could be put into words; broadcast_strength = how strongly it's being shared with the rest of the model. X-axis: cumulative training step."></span></span><span class="cv" id="jsCv">—</span></h3>
        <div class="mchart-wrap"><svg class="mchart" id="chartJspace"></svg></div></div>
      <div class="chart-card"><h3><span>Route mix (this step)<span class="tip" tabindex="0" data-tip="What fraction of the most recent batch's attention was routed to each of the four reasoning spaces: S1 (fast/automatic), S2 (slow/deliberate), Critic (safety), Planner (long-horizon)."></span></span><span class="cv" id="routeCv">—</span></h3>
        <div id="routeMix"></div></div>
    </div>
    <p class="muted" style="margin:0.5rem 0 0">Smoothed (Catmull–Rom) · x-axis is cumulative training step, spans the whole run (not just since the last restart — the trainer's own step counter resets each time, this keeps counting up) · hover any chart for exact values, including raw step and wall-clock time · amber ticks mark trainer restarts.</p>

    <h2 style="margin-top:1.1rem">Loss function — J-space auxiliary terms<span class="tip" tabindex="0" data-tip="The actual formula being minimized during training: the core language-modeling loss (lm) plus several auxiliary regularizer terms, each color-matched to its sparkline below."></span></h2>
    <div class="eqn-card">
      <div class="eqn-line">
        <b>loss</b> = lm
        + ( <span style="color:#2a78d6">report</span>·1.0
          + <span style="color:#1baf7a">broadcast</span>·0.5
          + <span style="color:#eda100">selectivity</span>·0.3
          + <span style="color:#008300">modulation</span>·0.5 ) · j<sub>w</sub>
        + Σ <span style="color:#4a3aa7">half_life</span>·hl<sub>w</sub>
        + <span style="color:#e34948">inter_mi</span>(cos, 0.45)·0.3
        + <span style="color:#e87ba4">routing_KL</span>·0.4
      </div>
      <div class="eqn-sub muted" id="eqnSub"></div>
    </div>
    <div class="aux-grid" id="auxGrid"></div>

    <div class="kv" id="trainDetail" style="margin-top:0.9rem"></div>
    <button type="button" class="linkbtn" id="tableToggle">Show data table ▾</button>
    <div class="table-wrap" id="tableWrap"><table><thead id="seriesThead"></thead><tbody id="seriesTbody"></tbody></table></div>

    <h2 style="margin-top:1rem">Watch signals<span class="tip" tabindex="0" data-tip="Auto-generated 'things worth a glance' — with warnings when a number looks off."></span></h2>
    <div class="row" id="watchStats"></div>
    <ul class="hints" id="watchHints"></ul>
    <p class="muted" id="trainCaption">Source: metrics jsonl</p>
  </section>

  <section class="card">
    <h2>Checkpoints<span class="tip" tabindex="0" data-tip="Saved snapshots of the model's brain. After a crash, training resumes from the newest one — you only ever lose the steps since it was written."></span></h2>
    <table>
      <thead><tr><th title="Snapshot filename — step_N.pt was saved at training step N">File</th><th title="Snapshot size on disk in megabytes">MB</th><th title="How long ago this snapshot was written">Age</th></tr></thead>
      <tbody id="ckpts"></tbody>
    </table>
  </section>

  <section class="card">
    <h2>Live inspect<span class="tip" tabindex="0" data-tip="Type a sentence and peek inside the live model: which inner workspaces light up and where attention routes. Needs the engine booted (off during training so it doesn't fight the trainer for the GPU)."></span></h2>
    <p class="muted">Forward pass on the hot-reloaded checkpoint (needs engine boot). Mass / route should change with input.</p>
    <div class="probe">
      <input id="probeText" value="The number of legs on the animal that spins webs is"/>
      <button id="probeBtn" type="button">Inspect</button>
    </div>
    <pre class="out" id="probeOut">—</pre>
  </section>
</main>
<script>
const STATES = ["RAW","CLAIMED_CURATE","PACKED","CLAIMED_TRAIN","CONSUMED","FAILED","DELETED"];
let lastPayload = null;

// ELI5 explainers, one per metric/axis/label across this page. Plain
// language on purpose -- assume the reader doesn't already know what "j_aux
// share" means. Keyed by a short id, looked up via tip(id).
const TIP = {
  d1_host_free: "How much free disk space the machine has. If this runs out, everything stops — data collection, training, checkpoints. Needs to stay above the red line (the low-water mark).",
  d2_runway: "How much cleaned, ready-to-train-on data is queued up for the phase currently being trained. Like a fuel gauge — if it hits empty, the trainer has nothing to chew on.",
  d3_collectors: "Whether the workers fetching raw training text from the outside world are actively running, or paused (usually because disk is too full).",
  d4_raw_headroom: "How much unprocessed raw text is sitting on disk, out of the max allowed before collectors pause themselves to avoid filling the disk.",
  d5_fail_rate: "Percent of data shards that a worker gave up on (bad data, crash, etc.) instead of successfully processing. High numbers mean something's wrong upstream.",
  loop_health: "One-word verdict on the whole pipeline: healthy and stepping, stale (stuck), or data-starved (trainer ready but nothing to train on).",
  host_free: "Free disk space on the actual host machine (not the container's virtual disk, which can lie about how much room is really left).",
  collectors_status: "Whether the pipeline is currently pausing data collection (usually a disk-space precaution) or letting it run.",
  trainer_phase: "Which stage of the curriculum the model is currently being trained on (see the Curriculum panel below) — the topic mix and context length change per phase.",
  step: "One optimizer update = one step. The model's weights change a tiny bit after every step, based on a batch of training data.",
  lm_loss: "How surprised the model is by the actual next word, on average — lower is better. This is the main number that should trend down as training works.",
  raw_backlog: "Unprocessed text collected from the internet but not yet cleaned/tokenized, waiting for a curator worker to get to it.",
  ckpt: "The most recent saved snapshot of the model's weights — what you'd load to actually use or resume training from.",
  phase_progress: "How far through the CURRENT curriculum phase training has gotten, measured in tokens (words/sub-words) processed vs. that phase's budget.",
  run_progress: "How far through the ENTIRE planned training run this is, across all curriculum phases combined.",
  next_ckpt: "How many more optimizer steps until the next checkpoint (saved snapshot) gets written to disk.",
  demand_step: "The training step number as of the last time the trainer told the data-collection side what it needs more/less of.",
  curate_stricter: "Whether the trainer is asking curators to be pickier about data quality right now (e.g. because loss is rising and it suspects noisy data).",
  task_boosts: "Which categories of training examples (math, code, chat, ...) the trainer is asking miners to prioritize collecting more of.",
  tokens_seen: "Total words/sub-words the model has been trained on so far in this run, summed across all steps.",
  lm_total: "Two numbers: the core language-modeling loss (predict-the-next-word), and the total loss including all the auxiliary J-space regularizers added on top. See the loss formula below.",
  tok_s: "Training throughput: how many tokens (words/sub-words) per second the GPU is processing. Higher = faster training, all else equal.",
  lr: "Learning rate — how big a step the optimizer takes when updating weights. Follows a warmup-then-decay schedule (see the Learning rate chart).",
  grad: "Gradient norm — roughly, how hard the optimizer is trying to push the weights this step. Spikes can mean instability; it's clipped at a max value (dashed line on the chart) to prevent the model from blowing up.",
  broadcast_kv: "How strongly information is being shared ('broadcast') between the model's different reasoning workspaces (S1/S2/Critic/Planner) on this batch.",
  report_kv: "One of the auxiliary loss terms — encourages a workspace to be able to accurately 'report' (verbalize) what it's holding.",
  routing_kv: "How much the model's internal router disagrees with the expected routing pattern for this task type (e.g. 'automatic' tasks should route mostly to S1). Lower is better alignment.",
  mass_kv: "Verbalizable mass — roughly, what fraction of a workspace's content could plausibly be put into words. Very low means it's not holding much meaningful info yet; very high can mean it's saturated.",
  routes_kv: "The last batch's routing split across the four reasoning spaces (R0=S1 automatic, R1=S2 deliberate, R2=Critic, R3=Planner) — should shift depending on task type.",
  phase_name: "Which curriculum phase (P0-P5) the most recently logged training step belongs to.",
  loss_chart: "Y-axis: the loss value (lower = model is less surprised by the data = better). X-axis: cumulative training step across the WHOLE run (keeps counting up across restarts instead of resetting), not just since the last restart — amber ticks mark where the trainer crashed and resumed. Two lines: lm_loss (core prediction loss) and total (lm_loss plus all the auxiliary regularizers).",
  lr_chart: "Y-axis: the learning rate the optimizer is currently using. X-axis: cumulative training step. Follows a warmup (ramps up) then decay (ramps down) schedule — see WSD in the curriculum caption.",
  grad_chart: "Y-axis: gradient norm (how big a weight update the optimizer wants to make). X-axis: cumulative training step. The dashed red line is the clip threshold — values are capped there to stop the model from taking a destructively large step.",
  tok_chart: "Y-axis: training throughput in tokens per second. X-axis: cumulative training step. Dips often line up with restarts, checkpoint writes, or the GPU being shared with something else.",
  jspace_chart: "Y-axis: two workspace health signals, 0 to 1. verbalizable_mass = how much of the workspace content could be put into words; broadcast_strength = how strongly it's being shared with the rest of the model. X-axis: cumulative training step.",
  route_mix_chart: "What fraction of the most recent batch's attention was routed to each of the four reasoning spaces: S1 (fast/automatic), S2 (slow/deliberate), Critic (safety), Planner (long-horizon). Different task types are expected to route differently.",
  dominant_route: "Whichever of S1/S2/Critic/Planner got the largest share of routing on the last batch, and what percent it got.",
  route_entropy: "How spread out the routing is across the four spaces, in bits. Near 0 = all traffic goes to one space (route 'collapsed'); higher = more evenly spread.",
  j_aux_share: "What fraction of the TOTAL loss comes from the auxiliary J-space terms rather than the core language-modeling loss. If this gets too high, the aux terms may be drowning out actual language learning.",
  lm_delta: "How much the lm_loss changed versus the previous logged step — a quick 'is it currently improving or getting worse' signal.",
  grad_vs_clip: "The most recent gradient norm, for comparison against the clip target (usually ~1.0) shown alongside it.",
  half_lives: "How many tokens of 'memory' each reasoning space holds before old information decays to half strength. S1 forgets fast (short-term), S2/Critic/Planner hold on longer — by design, not a bug.",
  eqn_card: "The actual formula being minimized during training: the core language-modeling loss (lm) plus several auxiliary regularizer terms, each color-matched to its sparkline below.",
  aux_report: "Report loss — penalizes a workspace when it can't accurately verbalize/report what it's holding.",
  aux_broadcast: "Broadcast loss — encourages the right amount of information sharing between workspaces (not too little, not so much it floods everything).",
  aux_selectivity: "Selectivity loss — encourages 'automatic' tasks to use low variance (routine, on-rails) and 'deliberate' tasks to use high variance (more exploratory) internal representations.",
  aux_modulation: "Modulation loss — checks that the model's internal state actually changes in a task-appropriate way, not just a fixed default pattern.",
  aux_half_life: "Half-life loss — pulls each workspace's memory decay rate toward its target half-life (see the Half-lives stat).",
  aux_inter_mi: "Inter-space mutual-information loss — keeps different reasoning spaces from just copying each other; they're supposed to specialize.",
  aux_routing: "Routing KL loss — penalizes the router when its space-selection distribution drifts from the expected pattern for the current task type.",
  data_table: "The raw numbers behind the charts above — every logged point (not smoothed), most recent first, with the wall-clock time each was logged.",
  cur_hero: "seq = how long each practice text is, in tokens. rope = the position-encoding dial that lets the model handle longer texts. mix = this lesson's diet of data types (tool_use = agentic tool-and-skill transcripts).",
  demand_reasons: "The trainer's own words for why it's asking: phase deficits, loss trends, or 'runway healthy — maintain mixture'.",
  eval_meta: "Basic context for the eval run: which preset/checkpoint was tested, what hardware, how long it took.",
  eval_test: "The name of a specific automated check — usually formatted as branch/test-name.",
  eval_bar: "The pass/fail threshold this test is checking against — what result would count as a genuine capability, not chance.",
  eval_measured: "The raw measured value(s) for this test, as logged by the eval harness — the evidence behind the PASS/FAIL verdict.",
  eval_verdict: "Whether the measured value cleared the bar. FAIL on an untrained/random-init checkpoint is expected — these tests are only meaningful once the model has actually learned something.",
};

function tipEl(key) {
  const t = TIP[key];
  if (!t) return "";
  return `<span class="tip" tabindex="0" data-tip="${t.replace(/&/g,"&amp;").replace(/"/g,"&quot;")}"></span>`;
}

function fmt(n) {
  if (n == null || Number.isNaN(n)) return "—";
  if (Math.abs(n) >= 1e9) return (n/1e9).toFixed(2) + "B";
  if (Math.abs(n) >= 1e6) return (n/1e6).toFixed(2) + "M";
  if (Math.abs(n) >= 1e3) return (n/1e3).toFixed(1) + "k";
  return String(n);
}
function fmtTs(t) {
  try { return new Date(t * 1000).toLocaleTimeString(); } catch { return "—"; }
}
function fmtAge(s) {
  if (s == null) return "—";
  if (s < 60) return Math.round(s) + "s";
  if (s < 3600) return Math.round(s/60) + "m";
  return (s/3600).toFixed(1) + "h";
}
function pillClass(ok, warn) {
  if (ok === false) return "bad";
  if (warn) return "warn";
  return "ok";
}

function fmtDuration(s) {
  if (s == null || !isFinite(s) || s < 0) return "—";
  if (s < 90) return Math.round(s) + "s";
  if (s < 3600) return Math.round(s / 60) + "m";
  if (s < 86400) return (s / 3600).toFixed(1) + "h";
  return (s / 86400).toFixed(1) + "d";
}

// One paragraph, plain language, regenerated from the live payload every
// poll -- this is meant to answer "what's going on right now" without
// making the reader cross-reference six panels themselves.
function composeNarrative(d) {
  const mode = d.mode || {};
  const preset = d.preset || "?";
  const last = (d.trainer && d.trainer.last) || {};
  const watch = d.watch || {};
  const restarts = (d.trainer && d.trainer.restarts) || [];
  const fs = (d.trainer && d.trainer.full_series) || {};
  const disk = d.disk || {};
  const pause = (d.flow && d.flow.collector_pause) || {};
  const parts = [];

  // 1. What is it doing right now.
  if (mode.id === "training") {
    parts.push(`Training the <b>${preset}</b> preset.`);
  } else if (mode.id === "data_prep") {
    parts.push(`Building data runway for the <b>${preset}</b> preset — not training yet.`);
  } else if (mode.id === "stale") {
    parts.push(`<span class="warn-inline">Trainer stale</span> on the <b>${preset}</b> preset — no step logged in ${fmtAge(d.trainer && d.trainer.age_s)}.`);
  } else if (mode.id === "blocked") {
    parts.push(`<span class="bad-inline">Blocked</span> — ${mode.detail || "see gates below"}.`);
  } else {
    parts.push(`Preset <b>${preset}</b>.`);
  }

  // 2. Where in the curriculum.
  const pp = watch.phase_progress, rp = watch.run_progress;
  if (pp && rp) {
    parts.push(`Currently phase P${pp.phase} (${pp.short || pp.name}), <b>${(pp.frac*100).toFixed(0)}%</b> through this phase and <b>${(rp.frac*100).toFixed(1)}%</b> through the full ${fmt(rp.tokens_total)}-token run.`);
  }

  // 3. Loss trend + throughput, in plain words rather than just a number.
  if (last.step != null && last.lm_loss != null) {
    const delta = watch.lm_delta_10;
    let trend = "holding steady";
    if (delta != null) {
      if (delta < -0.01) trend = "falling";
      else if (delta > 0.02) trend = "<span class=\"warn-inline\">rising</span>";
    }
    parts.push(`Loss is ${trend} (lm <b>${Number(last.lm_loss).toFixed(3)}</b>) at step <b>${fmt(last.step)}</b>, ~${last.tok_s != null ? fmt(Math.round(last.tok_s)) : "—"} tok/s.`);
  }

  // 4. Restart/stability history — the thing that's easy to miss by only
  // looking at "current run" charts.
  if (restarts.length > 0) {
    const sinceLast = Date.now() / 1000 - restarts[restarts.length - 1];
    const totalSpan = (fs.ts && fs.ts.length >= 2) ? (fs.ts[fs.ts.length - 1] - fs.ts[0]) : null;
    parts.push(`This run has hit <b>${restarts.length}</b> restart${restarts.length === 1 ? "" : "s"}${totalSpan != null ? ` over its ~${fmtDuration(totalSpan)} history` : ""}, but has been stable for the last ${fmtDuration(sinceLast)}.`);
  } else if (fs.ts && fs.ts.length >= 2) {
    parts.push(`No restarts in the visible history (~${fmtDuration(fs.ts[fs.ts.length - 1] - fs.ts[0])}) — running smoothly.`);
  }

  // 5. Infra health, only called out when it needs attention (don't restate
  // "everything's fine" six different ways).
  const issues = [];
  if (disk.below_low_water) issues.push(`<span class="warn-inline">host disk low</span> (${disk.free_gb} GB)`);
  if (pause.paused) issues.push(`<span class="warn-inline">collectors paused</span> (${pause.reason || "unknown"})`);
  if (d.trainer && d.trainer.data_starved) issues.push(`<span class="bad-inline">data starved</span>`);
  parts.push(issues.length ? `Watch: ${issues.join(", ")}.` : `Disk and collectors are healthy.`);

  // 6. Evals.
  if (d.eval && d.eval.json_exists) {
    parts.push(`Eval results are available — see the <a href="/evals">evals page</a>.`);
  } else {
    parts.push(`No eval run yet.`);
  }

  return parts.join(" ");
}

function renderNarrative(d) {
  document.getElementById("narrative").innerHTML = composeNarrative(d);
}

function renderMode(d) {
  const m = d.mode || {};
  const id = m.id || "unknown";
  const cls = id === "training" ? "ok" : (id === "data_prep" ? "warn" : "bad");
  document.getElementById("modeBanner").innerHTML = `
    <div class="mode">
      <div>
        <div class="title"><span class="pill ${cls}">${m.label || id}</span></div>
        <div class="detail">${m.detail || ""}</div>
      </div>
    </div>`;
}

const GATE_TIPS = { D1: "d1_host_free", D2: "d2_runway", D3: "d3_collectors", D4: "d4_raw_headroom", D5: "d5_fail_rate" };

function renderGates(d) {
  const gates = (d.flow && d.flow.gates) || [];
  document.getElementById("gates").innerHTML = gates.map(g => `
    <div class="gate ${g.ok ? "ok" : "bad"}">
      <div class="id">${g.id}${tipEl(GATE_TIPS[g.id])}</div>
      <div class="name">${g.name}</div>
      <div class="val">${g.value || "—"}</div>
      <div class="tgt">${g.target || ""}</div>
    </div>`).join("");
}

function renderTop(d) {
  const m = d.manifest || {};
  const tr = d.trainer || {};
  const last = tr.last || {};
  const flow = d.flow || {};
  const disk = d.disk || {};
  const starved = !!tr.data_starved;
  const pause = flow.collector_pause || {};
  const health = starved ? "bad" : (tr.stale ? "warn" : (m.ok ? "ok" : "warn"));
  const healthLabel = starved ? "DATA_STARVED" : (tr.stale ? "STALE" : (m.ok ? "healthy" : "manifest?"));
  const step = last.step != null ? last.step : "—";
  const loss = last.lm_loss != null ? Number(last.lm_loss).toFixed(3) : "—";
  const toks = last.tok_s != null ? Math.round(last.tok_s) : "—";
  const free = disk.free_gb != null ? disk.free_gb : d.disk_free_gb;
  const freeCls = disk.below_low_water ? "bad" : "ok";
  document.getElementById("preset").textContent = d.preset || "—";
  document.getElementById("clock").textContent = fmtTs(d.ts);
  document.getElementById("topStats").innerHTML = `
    <div class="stat"><div class="k">Loop${tipEl('loop_health')}</div><div class="v sm"><span class="pill ${health}">${healthLabel}</span></div>
      <div class="sub">${flow.data_detail || ""}</div></div>
    <div class="stat"><div class="k">Host free${tipEl('host_free')}</div><div class="v sm"><span class="pill ${freeCls}">${free != null ? free + " GB" : "—"}</span></div>
      <div class="sub">probe ${disk.probe || "—"} · low ${disk.low_water_gb ?? "—"}</div></div>
    <div class="stat"><div class="k">Collectors${tipEl('collectors_status')}</div><div class="v sm"><span class="pill ${pause.paused ? "warn" : "ok"}">${pause.paused ? "paused" : "running"}</span></div>
      <div class="sub">${pause.reason || "feeding target phase"}</div></div>
    <div class="stat"><div class="k">Trainer phase${tipEl('trainer_phase')}</div><div class="v">${flow.trainer_phase != null ? flow.trainer_phase : "—"}</div>
      <div class="sub">${(d.watch && d.watch.phase_progress && d.watch.phase_progress.short) || "target P"+(flow.target_phase != null ? flow.target_phase : "—")}</div></div>
    <div class="stat"><div class="k">Step${tipEl('step')}</div><div class="v">${step}</div>
      <div class="sub">age ${fmtAge(tr.age_s)}</div></div>
    <div class="stat"><div class="k">lm loss${tipEl('lm_loss')}</div><div class="v sm">${loss}</div>
      <div class="sub">${toks} tok/s</div></div>
    <div class="stat"><div class="k">Raw backlog${tipEl('raw_backlog')}</div><div class="v sm">${m.raw_gb != null ? m.raw_gb + " GB" : "—"}</div>
      <div class="sub">${Math.round((m.raw_fill || 0)*100)}% of max ${m.raw_max_gb ?? "—"} GB</div></div>
    <div class="stat"><div class="k">Ckpt${tipEl('ckpt')}</div><div class="v sm">${(d.ckpt && d.ckpt.latest_pointer) || "—"}</div>
      <div class="sub">tok ${m.tokenizer_sha || "—"}</div></div>
  `;
}

function mixStr(mix) {
  if (!mix) return "—";
  return Object.entries(mix).sort((a,b) => b[1]-a[1])
    .map(([k,v]) => `${k} ${(v*100).toFixed(0)}%`).join(" · ");
}

function renderCurriculum(d) {
  const cur = d.curriculum;
  const flow = d.flow || {};
  const watch = d.watch || {};
  const hero = document.getElementById("curriculumHero");
  const grid = document.getElementById("curriculum");
  if (!cur || !cur.phases) {
    hero.innerHTML = `<p class="muted">Curriculum preset not loaded.</p>`;
    grid.innerHTML = "";
    return;
  }
  const pp = watch.phase_progress || {};
  const rp = watch.run_progress || {};
  const active = flow.trainer_phase != null ? flow.trainer_phase : pp.phase;
  const activePh = cur.phases.find(p => p.index === active) || cur.phases[0];
  const pctPhase = pp.frac != null ? (pp.frac * 100).toFixed(1) : "—";
  const pctRun = rp.frac != null ? (rp.frac * 100).toFixed(2) : "—";
  hero.innerHTML = `
    <div class="mode">
      <div>
        <div class="title">Now training:
          <span class="pill ok">P${active} · ${activePh.short || activePh.name}</span>
        </div>
        <div class="detail">
          seq ${activePh.seq} · rope ${activePh.rope_base} · mix ${mixStr(activePh.mix)}${tipEl('cur_hero')}
          · phase progress${tipEl('phase_progress')} ${pctPhase}% (${fmt(pp.tokens_in_phase)} / ${fmt(pp.phase_tokens)})
          · run${tipEl('run_progress')} ${pctRun}% of ${fmt(cur.tokens_total)} tokens
          · next ckpt${tipEl('next_ckpt')} in ${watch.steps_to_ckpt != null ? watch.steps_to_ckpt : "—"} steps
        </div>
      </div>
    </div>`;
  grid.innerHTML = cur.phases.map(p => {
    const isActive = p.index === active;
    const isDone = active != null && p.index < active;
    const frac = (isActive && pp.frac != null) ? pp.frac
      : (isDone ? 1 : 0);
    const cls = ["cphase", isActive ? "active" : "", isDone ? "done" : ""].filter(Boolean).join(" ");
    return `<div class="${cls}">
      <div class="cname">P${p.index}</div>
      <div class="ctitle">${p.short || p.name}</div>
      <div class="cmeta">${fmt(p.tokens)} tok · seq ${p.seq}</div>
      <div class="cfill"><span style="width:${Math.round(frac*100)}%"></span></div>
      <div class="cmix">${mixStr(p.mix)}</div>
    </div>`;
  }).join("");
  document.getElementById("curriculumCaption").textContent =
    `Preset ${d.preset} · ${fmt(cur.tokens_per_step)} tok/step · ckpt every ${cur.checkpoint_every_steps} · lr ${cur.lr_max}→${cur.lr_min}`;
}

function renderPrep(d) {
  const flow = d.flow || {};
  const pause = flow.collector_pause || {};
  const m = d.manifest || {};
  const funnel = m.funnel || {};
  const life = d.lifecycle || {};
  const help = life.help || {};
  const order = life.order || ["RAW","CLAIMED_CURATE","PACKED","CLAIMED_TRAIN","CONSUMED","FAILED","DELETED"];
  const by = m.by_state || {};
  const alerts = [];
  if (pause.paused) alerts.push(`<div class="alert">Collectors paused: ${pause.reason || "unknown"}</div>`);
  if (d.disk && d.disk.below_low_water) alerts.push(`<div class="alert bad">Host disk below low-water (${d.disk.free_gb} GB &lt; ${d.disk.low_water_gb} GB)</div>`);
  if ((funnel.failed || 0) > 0) alerts.push(`<div class="alert">FAILED shards: ${funnel.failed} — check curator logs</div>`);
  document.getElementById("prepAlerts").innerHTML = alerts.join("");

  const cells = [
    ["RAW", funnel.raw],
    ["Curating", funnel.curating],
    ["Packed", funnel.packed],
    ["Training", funnel.training],
    ["Consumed", funnel.consumed],
    ["Failed", funnel.failed],
  ];
  document.getElementById("funnel").innerHTML = cells.map(([lab, n]) =>
    `<div class="cell"><div class="lab">${lab}</div><div class="num">${fmt(n || 0)}</div></div>`
  ).join("");

  document.getElementById("lifecycleGlossary").innerHTML = order.map(s => {
    const n = by[s] || 0;
    return `<div class="g-row"><div class="g-state">${s}</div><div class="g-n">${n}</div><div class="g-help">${help[s] || ""}</div></div>`;
  }).join("");
}

function renderPhases(d) {
  const flow = d.flow || {};
  const runway = flow.phase_runway || [];
  const cur = d.curriculum;
  const minTok = flow.packed_min_tokens || 0;
  const nameOf = (p) => {
    if (!cur || !cur.phases) return `P${p}`;
    const ph = cur.phases.find(x => x.index === p);
    return ph ? `P${p} ${ph.short}` : `P${p}`;
  };
  if (!runway.length) {
    const t = (d.manifest && d.manifest.tokens_ready_by_phase) || {};
    document.getElementById("phases").innerHTML = [0,1,2,3,4,5].map(p => {
      const n = t[String(p)] || 0;
      return `<div class="phase"><div class="p">${nameOf(p)}</div><div class="n">${fmt(n)}</div></div>`;
    }).join("");
    return;
  }
  document.getElementById("phases").innerHTML = runway.map(r => {
    const cls = [
      "phase",
      r.ok ? "" : "thin",
      r.is_trainer ? "trainer" : "",
      r.is_target ? "target" : "",
    ].filter(Boolean).join(" ");
    const tag = r.is_trainer ? "trainer" : (r.is_target ? "collect" : "");
    const pct = Math.round((r.fill || 0) * 100);
    return `<div class="${cls}">
      <div class="p">${nameOf(r.phase)}</div>
      <div class="n">${fmt(r.tokens)}</div>
      <div class="fill"><span style="width:${pct}%"></span></div>
      <div class="tag">${tag}</div>
    </div>`;
  }).join("");
  document.getElementById("runwayCaption").textContent =
    `Fill = tokens / packed_min (${fmt(minTok)}). Outlined = trainer phase; amber = collector target.`;
}

function renderWatch(d) {
  const w = d.watch || {};
  const last = (d.trainer && d.trainer.last) || {};
  const hl = last.hl_est || {};
  const dom = w.dominant_route || {};
  document.getElementById("watchStats").innerHTML = `
    <div class="stat"><div class="k">Dominant route${tipEl('dominant_route')}</div><div class="v sm">${dom.name || "—"} ${dom.p != null ? (dom.p*100).toFixed(0)+"%" : ""}</div>
      <div class="sub">entropy ${w.route_entropy != null ? w.route_entropy : "—"} bits ${tipEl('route_entropy')}</div></div>
    <div class="stat"><div class="k">J-aux share${tipEl('j_aux_share')}</div><div class="v sm">${w.j_aux_share != null ? (w.j_aux_share*100).toFixed(0)+"%" : "—"}</div>
      <div class="sub">of total loss</div></div>
    <div class="stat"><div class="k">Δ lm (log)${tipEl('lm_delta')}</div><div class="v sm">${w.lm_delta_10 != null ? (w.lm_delta_10 > 0 ? "+" : "")+w.lm_delta_10 : "—"}</div>
      <div class="sub">vs prior step log</div></div>
    <div class="stat"><div class="k">grad${tipEl('grad_vs_clip')}</div><div class="v sm">${w.grad_vs_clip != null ? w.grad_vs_clip : "—"}</div>
      <div class="sub">clip target ~1.0</div></div>
    <div class="stat"><div class="k">mass</div><div class="v sm">${last.verbalizable_mass != null ? Number(last.verbalizable_mass).toFixed(3) : "—"}</div>
      <div class="sub">broadcast ${last.broadcast_strength != null ? Number(last.broadcast_strength).toFixed(3) : "—"}</div></div>
    <div class="stat"><div class="k">half-lives${tipEl('half_lives')}</div><div class="v sm">${hl.system1 != null ? Math.round(hl.system1)+"/"+Math.round(hl.system2||0) : "—"}</div>
      <div class="sub">S1/S2 · C ${hl.critic != null ? Math.round(hl.critic) : "—"} · P ${hl.planner != null ? Math.round(hl.planner) : "—"}</div></div>
  `;
  const hints = w.hints || [];
  document.getElementById("watchHints").innerHTML = hints.map(h => {
    const warn = /rising|collapsed|high|low|diluted|FAILED|starv/i.test(h);
    return `<li class="${warn ? "warn" : ""}">${h}</li>`;
  }).join("");
}

// -- Manim-inspired chart engine --------------------------------------------
// Smooth Catmull-Rom curves (not raw polylines), a precise gridded axis, a
// pulsing tracer dot at the latest value (a nod to Manim's `always_redraw`
// dot-on-graph updaters), a "Create()"-style draw-in the first time a chart
// gets data, and a crosshair + tooltip readout on hover.
const MCOLORS = {
  blue: "#2a78d6", aqua: "#1baf7a", gold: "#eda100", green: "#008300",
  violet: "#4a3aa7", red: "#e34948", magenta: "#e87ba4", orange: "#eb6834",
};
const _chartSeen = new Set();

function catmullRomPath(pts) {
  if (pts.length < 2) return "";
  if (pts.length === 2) {
    return `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)} L${pts[1][0].toFixed(1)},${pts[1][1].toFixed(1)}`;
  }
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

function niceTicks(min, max, n) {
  if (min === max) { min -= 1; max += 1; }
  const out = [];
  for (let i = 0; i <= n; i++) out.push(min + (max - min) * i / n);
  return out;
}

function lastNonNull(arr) {
  if (!arr) return null;
  for (let i = arr.length - 1; i >= 0; i--) if (arr[i] != null) return arr[i];
  return null;
}

function sparkline(ys, color) {
  const w = 100, h = 26, pad = 2;
  const pts = [];
  for (let i = 0; i < ys.length; i++) if (ys[i] != null) pts.push(i);
  if (pts.length < 2) return `<svg viewBox="0 0 ${w} ${h}" class="spark"></svg>`;
  const vals = pts.map(i => ys[i]);
  let ymin = Math.min(...vals), ymax = Math.max(...vals);
  if (ymin === ymax) { ymin -= Math.abs(ymin) * 0.1 || 1; ymax += Math.abs(ymax) * 0.1 || 1; }
  const xmax = ys.length - 1 || 1;
  const coords = pts.map(i => [
    pad + (w - 2*pad) * (i / xmax),
    h - pad - (h - 2*pad) * ((ys[i] - ymin) / (ymax - ymin)),
  ]);
  const d = catmullRomPath(coords);
  const last = coords[coords.length - 1];
  return `<svg viewBox="0 0 ${w} ${h}" class="spark" preserveAspectRatio="none">
    <path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
    <circle class="tracer-dot" cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2" fill="${color}"/>
  </svg>`;
}

function drawChart(svg, { chartId, xs, lines, refLines, xTickFmt, yTickFmt, restarts, steps, times, xLabel }) {
  const w = 320, h = 120, padL = 40, padR = 10, padT = 8, padB = 18;
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  const wrap = svg.parentElement;
  const goodXs = (xs || []).filter(v => v != null);
  const anyY = lines.some(l => (l.ys || []).some(v => v != null));
  if (goodXs.length < 2 || !anyY) {
    svg.innerHTML = `<text x="8" y="${h/2}" font-size="10" fill="#898781">waiting for steps…</text>`;
    svg.onpointermove = null; svg.onpointerleave = null;
    const tip = wrap.querySelector(".mchart-tooltip");
    if (tip) tip.style.display = "none";
    return;
  }
  const xmin = Math.min(...goodXs), xmax = Math.max(...goodXs);
  let allY = [];
  lines.forEach(l => { allY = allY.concat((l.ys || []).filter(v => v != null)); });
  (refLines || []).forEach(r => allY.push(r.value));
  let ymin = Math.min(...allY), ymax = Math.max(...allY);
  if (ymin === ymax) { ymin -= Math.abs(ymin) * 0.1 || 1; ymax += Math.abs(ymax) * 0.1 || 1; }
  const span = ymax - ymin;
  ymin -= span * 0.08; ymax += span * 0.08;

  const X = x => padL + (w - padL - padR) * ((x - xmin) / Math.max(1e-9, xmax - xmin));
  const Y = y => (h - padB) - (h - padT - padB) * ((y - ymin) / Math.max(1e-9, ymax - ymin));

  let out = "";
  const yTicks = niceTicks(ymin, ymax, 3);
  yTicks.forEach(t => {
    const y = Y(t);
    out += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${w-padR}" y2="${y.toFixed(1)}" stroke="#e1e0d9" stroke-width="1"/>`;
    out += `<text x="${padL-5}" y="${(y+3).toFixed(1)}" text-anchor="end" font-size="8.5" fill="#898781">${yTickFmt ? yTickFmt(t) : t.toFixed(2)}</text>`;
  });
  const xMid = xmin + (xmax - xmin) / 2;
  out += `<line x1="${X(xMid).toFixed(1)}" y1="${padT}" x2="${X(xMid).toFixed(1)}" y2="${h-padB}" stroke="#e1e0d9" stroke-width="1"/>`;
  [xmin, xMid, xmax].forEach(t => {
    out += `<text x="${X(t).toFixed(1)}" y="${h-4}" text-anchor="middle" font-size="8.5" fill="#898781">${xTickFmt ? xTickFmt(t) : Math.round(t)}</text>`;
  });
  out += `<line x1="${padL}" y1="${padT}" x2="${padL}" y2="${h-padB}" stroke="#c3c2b7" stroke-width="1"/>`;
  out += `<line x1="${padL}" y1="${h-padB}" x2="${w-padR}" y2="${h-padB}" stroke="#c3c2b7" stroke-width="1"/>`;

  (refLines || []).forEach(r => {
    const y = Y(r.value);
    out += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${w-padR}" y2="${y.toFixed(1)}" stroke="${r.color || '#898781'}" stroke-width="1" stroke-dasharray="3 3"/>`;
    if (r.label) out += `<text x="${w-padR}" y="${(y-3).toFixed(1)}" text-anchor="end" font-size="8" fill="${r.color || '#898781'}">${r.label}</text>`;
  });

  // Restart markers: short muted ticks at the top edge only (not full-height
  // lines) -- a run with many restarts would otherwise turn the chart into a
  // picket fence. Hover reveals which one via the crosshair tooltip.
  (restarts || []).forEach(rt => {
    if (rt < xmin || rt > xmax) return;
    const x = X(rt).toFixed(1);
    out += `<line x1="${x}" y1="${padT}" x2="${x}" y2="${padT + 5}" stroke="${MCOLORS.orange}" stroke-width="1.5" opacity="0.85"/>`;
  });

  const firstDraw = !_chartSeen.has(chartId);
  lines.forEach((l, li) => {
    const pts = [];
    for (let i = 0; i < xs.length; i++) if (l.ys[i] != null) pts.push([X(xs[i]), Y(l.ys[i])]);
    if (pts.length < 2) return;
    const d = catmullRomPath(pts);
    out += `<path id="${chartId}-p${li}" d="${d}" fill="none" stroke="${l.color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
    const last = pts[pts.length - 1];
    out += `<circle class="tracer-dot" cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.6" fill="${l.color}"/>`;
  });
  out += `<line class="mchart-cross" x1="0" y1="${padT}" x2="0" y2="${h-padB}" stroke="#898781" stroke-width="1" opacity="0"/>`;
  svg.innerHTML = out;

  if (firstDraw) {
    _chartSeen.add(chartId);
    lines.forEach((l, li) => {
      const p = svg.querySelector(`#${chartId}-p${li}`);
      if (!p) return;
      const len = p.getTotalLength();
      p.style.strokeDasharray = `${len}`;
      p.style.strokeDashoffset = `${len}`;
      p.getBoundingClientRect();
      p.style.transition = `stroke-dashoffset ${700 + li * 150}ms cubic-bezier(.22,.7,.2,1)`;
      requestAnimationFrame(() => { p.style.strokeDashoffset = "0"; });
    });
  }

  let tip = wrap.querySelector(".mchart-tooltip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "mchart-tooltip";
    tip.style.display = "none";
    wrap.appendChild(tip);
  }
  const cross = svg.querySelector(".mchart-cross");
  svg.onpointermove = (ev) => {
    const rect = svg.getBoundingClientRect();
    const px = ((ev.clientX - rect.left) / rect.width) * w;
    let bestI = 0, bestD = Infinity;
    for (let i = 0; i < xs.length; i++) {
      if (xs[i] == null) continue;
      const dd = Math.abs(X(xs[i]) - px);
      if (dd < bestD) { bestD = dd; bestI = i; }
    }
    const cx = X(xs[bestI]);
    cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("opacity", "1");
    const rows = lines.filter(l => l.ys[bestI] != null).map(l =>
      `<div><span class="k" style="border-color:${l.color}">${l.label}</span><b>${yTickFmt ? yTickFmt(l.ys[bestI]) : l.ys[bestI]}</b></div>`
    ).join("");
    const xHead = xTickFmt ? xTickFmt(xs[bestI]) : xs[bestI];
    // Raw logged step only shown when it actually differs from the
    // cumulative x position (i.e. after a restart) — otherwise it's the
    // same number twice.
    const rawStep = steps && steps[bestI] != null ? Math.round(steps[bestI]) : null;
    const stepHead = rawStep != null && rawStep !== Math.round(xs[bestI]) ? ` (raw step ${rawStep})` : "";
    const timeHead = times && times[bestI] != null ? ` · ${fmtClockTime(times[bestI])}` : "";
    const nearRestart = (restarts || []).some(rt => Math.abs(rt - xs[bestI]) < (xmax - xmin) / w * 6);
    const restartNote = nearRestart ? `<div style="color:${MCOLORS.orange};font-size:0.65rem">↻ trainer restart</div>` : "";
    tip.innerHTML = `<div class="muted" style="font-size:0.65rem">${xLabel || ""}${xHead}${stepHead}${timeHead}</div>${restartNote}${rows}`;
    tip.style.display = "block";
    const leftPct = (cx / w) * 100;
    if (leftPct > 55) { tip.style.right = `calc(${100 - leftPct}% + 4px)`; tip.style.left = "auto"; }
    else { tip.style.left = `calc(${leftPct}% + 4px)`; tip.style.right = "auto"; }
  };
  svg.onpointerleave = () => { tip.style.display = "none"; cross.setAttribute("opacity", "0"); };
}

const fmtLoss = v => v == null ? "—" : Number(v).toFixed(3);
const fmtLr = v => v == null ? "—" : Number(v).toExponential(1);
const fmtGrad = v => v == null ? "—" : Number(v).toFixed(2);
const fmtTokS = v => v == null ? "—" : fmt(Math.round(v));
const fmtFrac = v => v == null ? "—" : Number(v).toFixed(3);
const fmtStep = v => v == null ? "—" : Math.round(v);

// Full local timestamp, used in tooltips/captions where wall-clock time is
// supplementary context alongside the step-based x-axis.
function fmtClockTime(tsSec) {
  if (tsSec == null) return "—";
  try { return new Date(tsSec * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
  catch { return "—"; }
}

const AUX_TERMS = [
  ["report", "Report", MCOLORS.blue, "aux_report"],
  ["broadcast", "Broadcast", MCOLORS.aqua, "aux_broadcast"],
  ["selectivity", "Selectivity", MCOLORS.gold, "aux_selectivity"],
  ["modulation", "Modulation", MCOLORS.green, "aux_modulation"],
  ["half_life", "Half-life", MCOLORS.violet, "aux_half_life"],
  ["inter_mi", "Inter-MI", MCOLORS.red, "aux_inter_mi"],
  ["routing", "Routing KL", MCOLORS.magenta, "aux_routing"],
];
const ROUTE_NAMES = ["S1 automatic", "S2 deliberate", "Critic", "Planner"];
const ROUTE_COLORS = [MCOLORS.blue, MCOLORS.aqua, MCOLORS.gold, MCOLORS.green];
const TABLE_COLS = ["step", "lm_loss", "total", "grad_norm", "lr", "tok_s",
  "report", "broadcast", "selectivity", "modulation", "half_life", "inter_mi",
  "routing", "verbalizable_mass", "broadcast_strength"];

function renderTrain(d) {
  const tr = d.trainer || {};
  const last = tr.last || {};
  const alerts = [];
  if (tr.data_starved) alerts.push(`<div class="alert bad">DATA_STARVED — no packed tokens for trainer phase</div>`);
  if (tr.stale) alerts.push(`<div class="alert">Trainer stale (${fmtAge(tr.age_s)} since last step)</div>`);
  document.getElementById("trainAlerts").innerHTML = alerts.join("");

  const route = last.route_probs || [];
  const routeStr = route.length
    ? route.map((p,i) => `R${i}:${(Number(p)*100).toFixed(0)}%`).join(" ")
    : "—";
  document.getElementById("trainStats").innerHTML = `
    <div class="stat"><div class="k">Step${tipEl('step')}</div><div class="v">${last.step ?? "—"}</div></div>
    <div class="stat"><div class="k">Tokens seen${tipEl('tokens_seen')}</div><div class="v sm">${fmt(last.tokens)}</div></div>
    <div class="stat"><div class="k">lm / total${tipEl('lm_total')}</div><div class="v sm">${last.lm_loss != null ? Number(last.lm_loss).toFixed(3) : "—"} / ${last.total != null ? Number(last.total).toFixed(3) : "—"}</div></div>
    <div class="stat"><div class="k">tok/s${tipEl('tok_s')}</div><div class="v sm">${last.tok_s != null ? Math.round(last.tok_s) : "—"}</div></div>
    <div class="stat"><div class="k">lr${tipEl('lr')}</div><div class="v sm">${last.lr != null ? Number(last.lr).toExponential(1) : "—"}</div></div>
    <div class="stat"><div class="k">grad${tipEl('grad')}</div><div class="v sm">${last.grad_norm != null ? Number(last.grad_norm).toFixed(2) : "—"}</div></div>
  `;
  document.getElementById("trainDetail").innerHTML = `
    <div class="k">broadcast${tipEl('broadcast_kv')}</div><div>${last.broadcast != null ? Number(last.broadcast).toFixed(4) : "—"}</div>
    <div class="k">report${tipEl('report_kv')}</div><div>${last.report != null ? Number(last.report).toFixed(3) : "—"}</div>
    <div class="k">routing${tipEl('routing_kv')}</div><div>${last.routing != null ? Number(last.routing).toFixed(4) : "—"}</div>
    <div class="k">mass${tipEl('mass_kv')}</div><div>${last.verbalizable_mass != null ? Number(last.verbalizable_mass).toFixed(3) : "—"}</div>
    <div class="k">routes${tipEl('routes_kv')}</div><div>${routeStr}</div>
    <div class="k">phase name${tipEl('phase_name')}</div><div>${last.phase != null ? "P"+last.phase : "—"}</div>
  `;

  const s = tr.series || {};                    // current run only (exact, for stat cards/table)
  const fs = tr.full_series || {};               // whole history, downsampled, restarts included
  // cum_step, not raw step: the trainer's own counter resets/rolls back on
  // every restart, so it isn't monotonic across the full history the way it
  // is within one run — cum_step keeps counting up instead of jumping
  // backward. steps/times ride along for the tooltip (exact raw step + when).
  const xs = fs.cum_step || [];
  const restarts = (tr.restarts || []).map(r => r.cum_step);
  const chartOpts = { xTickFmt: fmtStep, restarts, steps: fs.step, times: fs.ts, xLabel: "step " };

  document.getElementById("lossCv").textContent = fmtLoss(lastNonNull(s.lm_loss));
  drawChart(document.getElementById("chartLoss"), {
    chartId: "loss", xs, ...chartOpts,
    lines: [
      { label: "lm_loss", color: MCOLORS.blue, ys: fs.lm_loss || [] },
      { label: "total", color: MCOLORS.aqua, ys: fs.total || [] },
    ],
    yTickFmt: fmtLoss,
  });

  document.getElementById("lrCv").textContent = fmtLr(lastNonNull(s.lr));
  drawChart(document.getElementById("chartLr"), {
    chartId: "lr", xs, ...chartOpts,
    lines: [{ label: "lr", color: MCOLORS.gold, ys: fs.lr || [] }],
    yTickFmt: fmtLr,
  });

  const clip = (d.objective && d.objective.grad_clip) || 1.0;
  document.getElementById("gradCv").textContent = fmtGrad(lastNonNull(s.grad_norm));
  drawChart(document.getElementById("chartGrad"), {
    chartId: "grad", xs, ...chartOpts,
    lines: [{ label: "grad_norm", color: MCOLORS.violet, ys: fs.grad_norm || [] }],
    refLines: [{ value: clip, color: MCOLORS.red, label: `clip ${clip}` }],
    yTickFmt: fmtGrad,
  });

  document.getElementById("tokCv").textContent = fmtTokS(lastNonNull(s.tok_s));
  drawChart(document.getElementById("chartTok"), {
    chartId: "tok", xs, ...chartOpts,
    lines: [{ label: "tok/s", color: MCOLORS.green, ys: fs.tok_s || [] }],
    yTickFmt: fmtTokS,
  });

  document.getElementById("jsCv").textContent = fmtFrac(lastNonNull(s.verbalizable_mass));
  drawChart(document.getElementById("chartJspace"), {
    chartId: "jspace", xs, ...chartOpts,
    lines: [
      { label: "verbalizable_mass", color: MCOLORS.blue, ys: fs.verbalizable_mass || [] },
      { label: "broadcast_strength", color: MCOLORS.orange, ys: fs.broadcast_strength || [] },
    ],
    yTickFmt: fmtFrac,
  });

  renderRouteMix(d);
  renderEqn(d);
  renderAux(d);
  renderTable(d);

  const stepSpan = xs.length >= 2 ? `step ${fmtStep(xs[0])} → ${fmtStep(xs[xs.length - 1])}` : "—";
  const times = fs.ts || [];
  const timeSpan = times.length >= 2 && times[0] != null && times[times.length - 1] != null
    ? ` (${fmtClockTime(times[0])} → ${fmtClockTime(times[times.length - 1])})` : "";
  document.getElementById("trainCaption").textContent =
    `Source: ${tr.metrics_path || "metrics"} · ${xs.length} points, ${stepSpan}${timeSpan} · ${restarts.length} restart${restarts.length === 1 ? "" : "s"} (amber tick marks) · ${tr.n_points || 0} recent jsonl lines read`;
}

function renderRouteMix(d) {
  const last = (d.trainer && d.trainer.last) || {};
  const probs = last.route_probs || [];
  const el = document.getElementById("routeMix");
  const cv = document.getElementById("routeCv");
  if (!probs.length) {
    el.innerHTML = `<p class="muted" style="margin:0.3rem 0 0">No route data yet.</p>`;
    cv.textContent = "—";
    return;
  }
  const domI = probs.reduce((best, p, i) => (p > probs[best] ? i : best), 0);
  cv.textContent = `${ROUTE_NAMES[domI] || "r"+domI} ${(probs[domI]*100).toFixed(0)}%`;
  const segs = probs.map((p, i) =>
    `<div title="${ROUTE_NAMES[i] || 'r'+i} ${(p*100).toFixed(0)}%" style="width:${Math.max(0,p*100).toFixed(1)}%;background:${ROUTE_COLORS[i] || '#898781'}"></div>`
  ).join("");
  const legend = probs.map((p, i) =>
    `<span><i style="background:${ROUTE_COLORS[i] || '#898781'}"></i>${ROUTE_NAMES[i] || 'r'+i} ${(p*100).toFixed(0)}%</span>`
  ).join("");
  el.innerHTML = `<div class="routebar" style="margin-top:0.35rem">${segs}</div><div class="legend" style="margin-top:0.4rem">${legend}</div>`;
}

function renderEqn(d) {
  const o = d.objective;
  const el = document.getElementById("eqnSub");
  if (!o) { el.textContent = ""; return; }
  const phase = (d.flow && d.flow.trainer_phase) || 0;
  const jw = phase <= 2 ? o.j_weight.early : o.j_weight.late;
  const hl = o.half_life_target || {};
  el.textContent =
    `j_w = ${o.j_weight.early} (P0–P2) / ${o.j_weight.late} (P3–P5) — active ${jw} at P${phase} · ` +
    `grad clip ${o.grad_clip} (dashed line, right) · ` +
    `hl targets S1 ${hl.system1} · S2 ${hl.system2} · Critic ${hl.critic} · Planner ${hl.planner} tok`;
}

function renderAux(d) {
  const fs = (d.trainer && d.trainer.full_series) || {};
  document.getElementById("auxGrid").innerHTML = AUX_TERMS.map(([key, label, color, tipKey]) => {
    const ys = fs[key] || [];
    const last = lastNonNull(ys);
    return `<div class="aux-cell">
      <div class="lab"><i style="background:${color}"></i>${label}${tipEl(tipKey)}</div>
      <div class="val">${last != null ? Number(last).toFixed(4) : "—"}</div>
      ${sparkline(ys, color)}
    </div>`;
  }).join("");
}

function renderTable(d) {
  const fs = (d.trainer && d.trainer.full_series) || {};
  const n = (fs.step || []).length;
  document.getElementById("seriesThead").innerHTML =
    `<tr><th>time</th>${TABLE_COLS.map(c => `<th>${c}</th>`).join("")}</tr>`;
  const start = Math.max(0, n - 30);
  let rows = "";
  for (let i = n - 1; i >= start; i--) {
    const cells = TABLE_COLS.map(c => {
      const v = (fs[c] || [])[i];
      if (v == null) return "<td>—</td>";
      return `<td>${typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(4)) : v}</td>`;
    }).join("");
    rows += `<tr><td>${fmtClockTime(fs.ts && fs.ts[i])}</td>${cells}</tr>`;
  }
  document.getElementById("seriesTbody").innerHTML = rows;
}

function renderCkpts(d) {
  const files = (d.ckpt && d.ckpt.files) || [];
  const latest = d.ckpt && d.ckpt.latest_pointer;
  document.getElementById("ckpts").innerHTML = files.length
    ? files.map(f => {
        const mark = f.name === latest ? " ← latest" : "";
        return `<tr><td>${f.name}${mark}</td><td>${f.mb}</td><td>${fmtAge(f.age_s)}</td></tr>`;
      }).join("")
    : `<tr><td colspan="3" class="muted">No .pt files</td></tr>`;
}

function renderDemand(d) {
  const dem = d.demand;
  const el = document.getElementById("demandPanel");
  if (!dem) {
    el.innerHTML = `<div class="alert">No demand.json yet — waiting for trainer heartbeat to publish.</div>`;
    return;
  }
  const phases = dem.phases || [];
  const boost = dem.boost_task_types || {};
  const boostStr = Object.keys(boost).length
    ? Object.entries(boost).map(([k,v]) => `${k}×${v}`).join(", ")
    : "—";
  const reasonStr = (dem.reasons || []).join(" · ") || "—";
  el.innerHTML = `
    <div class="row">
      <div class="stat"><div class="k">Demand step${tipEl('demand_step')}</div><div class="v">${dem.step ?? "—"}</div>
        <div class="sub">age ${fmtAge(dem.age_s)} · phase P${dem.trainer_phase ?? "—"}</div></div>
      <div class="stat"><div class="k">Curate stricter${tipEl('curate_stricter')}</div><div class="v sm"><span class="pill ${dem.curate_stricter ? "warn" : "ok"}">${dem.curate_stricter ? "yes" : "no"}</span></div></div>
      <div class="stat"><div class="k">Task boosts${tipEl('task_boosts')}</div><div class="v sm">${boostStr}</div></div>
      <div class="stat"><div class="k">Reasons${tipEl('demand_reasons')}</div><div class="v sm">${reasonStr}</div></div>
    </div>
    <div class="phase-grid" style="margin-top:0.75rem">
      ${[0,1,2,3,4,5].map(p => {
        const row = phases.find(x => x.phase === p) || {};
        const acts = (row.actions || []).join(",") || "—";
        const eff = row.effort != null ? (row.effort*100).toFixed(0)+"%" : "0%";
        return `<div class="phase ${p === dem.trainer_phase ? "trainer" : ""}">
          <div class="p">P${p}</div>
          <div class="n">${eff}</div>
          <div class="tag">${acts}</div>
        </div>`;
      }).join("")}
    </div>`;
}

async function refresh() {
  try {
    const r = await fetch("/pipeline/status");
    const d = await r.json();
    lastPayload = d;
    renderNarrative(d);
    renderMode(d);
    renderGates(d);
    renderTop(d);
    renderCurriculum(d);
    renderDemand(d);
    renderPrep(d);
    renderPhases(d);
    renderTrain(d);
    renderWatch(d);
    renderCkpts(d);
  } catch (e) {
    document.getElementById("clock").textContent = "fetch failed";
  }
}

document.getElementById("probeBtn").onclick = async () => {
  const text = document.getElementById("probeText").value;
  document.getElementById("probeOut").textContent = "…";
  try {
    const r = await fetch("/jspace/inspect", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text}),
    });
    if (!r.ok) {
      const err = await r.text();
      document.getElementById("probeOut").textContent = `HTTP ${r.status}: ${err.slice(0, 400)}\n(Engine may be skipped during training — AVA_SKIP_ENGINE_BOOT=1)`;
      return;
    }
    const j = await r.json();
    const spaces = j.spaces || j.per_space || {};
    const route = j.route_probs || j.routing || {};
    const mass = j.verbalizable_mass ?? j.mass;
    document.getElementById("probeOut").textContent = JSON.stringify({
      verbalizable_mass: mass,
      route_probs: route,
      spaces: Object.fromEntries(Object.entries(spaces).map(([k,v]) => [k, {
        mass: v.verbalizable_mass ?? v.mass,
        top: (v.top_concepts || v.top || []).slice?.(0,5) || v.top,
      }])),
    }, null, 2);
  } catch (e) {
    document.getElementById("probeOut").textContent = String(e);
  }
};

document.getElementById("tableToggle").onclick = () => {
  const w = document.getElementById("tableWrap");
  const showing = w.classList.toggle("show");
  document.getElementById("tableToggle").textContent = showing ? "Hide data table ▴" : "Show data table ▾";
};

refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""
