"""Self-contained live eval-review page HTML (no CDN)."""

EVALS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Ava Evals</title>
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
main { max-width: 980px; margin: 0 auto; padding: 1rem 1.5rem 2.5rem; }
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 2px;
  padding: 1rem 1.1rem;
  margin-bottom: 1rem;
}
.card h2 {
  margin: 0 0 0.75rem;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  font-weight: 600;
}
.row { display: flex; gap: 0.75rem; flex-wrap: wrap; }
.stat {
  flex: 1 1 7rem;
  min-width: 6.5rem;
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--line);
  background: var(--bg);
}
.stat .k { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.stat .v { font-size: 1.2rem; font-variant-numeric: tabular-nums; font-weight: 600; margin-top: 0.15rem; }
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
.alert {
  margin: 0 0 0.75rem;
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--line);
  background: var(--bg);
  color: var(--muted);
  font-size: 0.88rem;
}
.tip {
  display: inline-flex; align-items: center; justify-content: center;
  width: 13px; height: 13px; margin-left: 0.3em; border-radius: 50%;
  border: 1px solid var(--muted); color: var(--muted); font-size: 0.62rem;
  font-weight: 600; cursor: help; position: relative; vertical-align: middle; flex: none;
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
.md-body h2 { font-size: 1.05rem; margin: 1.1rem 0 0.5rem; }
.md-body h3 { font-size: 0.92rem; margin: 0.9rem 0 0.4rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.md-body h4 { font-size: 0.85rem; margin: 0.7rem 0 0.3rem; }
.md-body p { font-size: 0.88rem; line-height: 1.6; margin: 0.4rem 0; }
.md-table-wrap { overflow-x: auto; margin: 0.5rem 0 1rem; border: 1px solid var(--line); }
table.md-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
table.md-table th, table.md-table td { text-align: left; padding: 0.4rem 0.55rem; border-bottom: 1px solid var(--line); vertical-align: top; }
table.md-table th { background: var(--bg); color: var(--muted); font-weight: 600; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em; }
table.md-table td { font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 0.76rem; word-break: break-word; max-width: 26rem; }
.muted { color: var(--muted); font-size: 0.85rem; }
a { color: var(--accent); }
.branch-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 0.6rem; margin-top: 0.5rem; }
.branch-cell { border: 1px solid var(--line); background: var(--bg); padding: 0.55rem 0.65rem; }
.branch-cell .name { font-weight: 600; font-size: 0.9rem; }
.branch-cell .ckpt { font-size: 0.72rem; color: var(--muted); margin-top: 0.15rem; font-family: ui-monospace, monospace; }
</style>
</head>
<body>
<header>
  <h1>Ava evals</h1>
  <div class="meta">
    <a href="/dashboard">dashboard</a>
    · <a href="/chat">chat</a>
    · <a href="/jspace/eval_branch">raw json</a>
    · <a href="/jspace/viewer">viewer</a>
  </div>
</header>
<main>
  <section class="card" id="metaCard">
    <h2>Run meta</h2>
    <div class="row" id="metaStats"><p class="muted">Loading…</p></div>
  </section>

  <section class="card" id="branchCard" style="display:none">
    <h2>Branches evaluated</h2>
    <div class="branch-grid" id="branchGrid"></div>
  </section>

  <section class="card" id="reportCard">
    <h2>Report — pretraining quality</h2>
    <p class="muted" style="margin:0 0 0.5rem">Perplexity, probes, J-Space routing — raw model quality, no tool use.</p>
    <div id="reportBody" class="md-body"><p class="muted">Loading…</p></div>
  </section>

  <section class="card" id="agentEvalCard">
    <h2>Agentic hill-climb — Ava-claw / AgenticOS</h2>
    <p class="muted" style="margin:0 0 0.5rem">A different axis: can this checkpoint act as the brain behind a real ReAct tool-calling agent? See <code>agent-eval/scripts/ava_claw_run.py</code>.</p>
    <div id="agentEvalBody" class="md-body"><p class="muted">Loading…</p></div>
  </section>
</main>
<script>
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

// Small, safe, purpose-built renderer for scripts/make_report.py's output
// (headers, one-line paragraphs, GFM pipe tables) -- not a general markdown
// engine, and deliberately not pulling in a CDN dependency for one report.
function renderMarkdown(md) {
  const lines = md.split(/\r?\n/);
  let html = "";
  let i = 0;
  const isSep = (line) => /^\|?[\s:|-]+\|?$/.test(line) && line.includes("-");
  const splitRow = (line) => {
    const cells = line.split("|").map(c => c.trim());
    if (cells.length && cells[0] === "") cells.shift();
    if (cells.length && cells[cells.length - 1] === "") cells.pop();
    return cells;
  };
  while (i < lines.length) {
    const line = lines[i];
    if (/^#\s+/.test(line)) { html += `<h2>${escapeHtml(line.replace(/^#\s+/, ""))}</h2>`; i++; continue; }
    if (/^##\s+/.test(line)) { html += `<h3>${escapeHtml(line.replace(/^##\s+/, ""))}</h3>`; i++; continue; }
    if (/^###\s+/.test(line)) { html += `<h4>${escapeHtml(line.replace(/^###\s+/, ""))}</h4>`; i++; continue; }
    if (/^\|/.test(line) && i + 1 < lines.length && isSep(lines[i + 1])) {
      const headerCells = splitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\|/.test(lines[i])) { rows.push(splitRow(lines[i])); i++; }
      const COL_TIPS = {
        Test: "The name of a specific automated check — usually formatted as branch/test-name.",
        Bar: "The pass/fail threshold this test is checking against — what result would count as a genuine capability, not chance.",
        Measured: "The raw measured value(s) for this test, as logged by the eval harness — the evidence behind the PASS/FAIL verdict.",
        Verdict: "Whether the measured value cleared the bar. FAIL on an untrained/random-init checkpoint is expected — these tests are only meaningful once the model has actually learned something.",
        Metric: "Which quantity is being compared between the base and chat branches.",
        Base: "The value for the base (non-chat-tuned) branch.",
        Chat: "The value for the chat branch (fine-tuned for conversation on top of base).",
        "Δ%": "Percent change from Base to Chat — how much fine-tuning moved this metric.",
      };
      html += `<div class="md-table-wrap"><table class="md-table"><thead><tr>${
        headerCells.map(c => `<th>${escapeHtml(c)}${COL_TIPS[c] ? `<span class="tip" tabindex="0" data-tip="${COL_TIPS[c].replace(/"/g,"&quot;")}"></span>` : ""}</th>`).join("")
      }</tr></thead><tbody>`;
      rows.forEach(r => {
        html += "<tr>" + r.map(c => {
          const t = c.trim();
          if (t === "PASS") return `<td><span class="pill ok">PASS</span></td>`;
          if (t === "FAIL") return `<td><span class="pill bad">FAIL</span></td>`;
          return `<td>${escapeHtml(c)}</td>`;
        }).join("") + "</tr>";
      });
      html += `</tbody></table></div>`;
      continue;
    }
    if (line.trim() === "") { i++; continue; }
    html += `<p>${escapeHtml(line)}</p>`;
    i++;
  }
  return html || `<p class="muted">Empty report.</p>`;
}

const META_TIPS = {
  Preset: "Which model size/config was evaluated (nano/mini/base1b) — see configs/*.yaml.",
  Device: "Hardware the eval ran on (cpu/cuda). Results can differ slightly by device due to floating-point non-determinism.",
  Wall: "How long the whole eval run took, in real seconds.",
  "Probe n": "How many probe examples were used per test category (arithmetic, facts, etc).",
  "Git sha": "Which commit of the code produced this eval — for reproducing or comparing results across changes.",
  Torch: "PyTorch version used — relevant since numerics can shift slightly between versions.",
};

function renderMeta(meta) {
  if (!meta) { document.getElementById("metaStats").innerHTML = `<p class="muted">No meta.</p>`; return; }
  const rows = [
    ["Preset", meta.preset], ["Device", meta.device], ["Wall", meta.wall_s != null ? meta.wall_s.toFixed(1) + "s" : "—"],
    ["Probe n", meta.probe_n], ["Git sha", meta.git_sha], ["Torch", meta.torch],
  ];
  document.getElementById("metaStats").innerHTML = rows.map(([k, v]) =>
    `<div class="stat"><div class="k">${escapeHtml(k)}${META_TIPS[k] ? `<span class="tip" tabindex="0" data-tip="${META_TIPS[k].replace(/"/g,"&quot;")}"></span>` : ""}</div><div class="v" style="font-size:0.95rem">${v != null ? escapeHtml(String(v)) : "—"}</div></div>`
  ).join("");
}

function renderBranches(data) {
  const card = document.getElementById("branchCard");
  const branches = Object.keys(data).filter(k => k !== "meta");
  if (!branches.length) { card.style.display = "none"; return; }
  card.style.display = "";
  document.getElementById("branchGrid").innerHTML = branches.map(name => {
    const b = data[name] || {};
    const ckpt = b.ckpt || "—";
    const probeKeys = b.probes ? Object.keys(b.probes) : [];
    return `<div class="branch-cell">
      <div class="name">${escapeHtml(name)}</div>
      <div class="ckpt">ckpt: ${escapeHtml(String(ckpt))}</div>
      <div class="muted" style="margin-top:0.3rem">${probeKeys.length} probe set${probeKeys.length === 1 ? "" : "s"}${b.jspace ? " · jspace tests present" : ""}</div>
    </div>`;
  }).join("");
}

async function load() {
  try {
    const r = await fetch("/jspace/eval_branch");
    if (r.ok) {
      const data = await r.json();
      renderMeta(data.meta);
      renderBranches(data);
    } else {
      document.getElementById("metaStats").innerHTML =
        `<p class="muted">No eval JSON yet (HTTP ${r.status}). Run <code>make eval</code>.</p>`;
      document.getElementById("branchCard").style.display = "none";
    }
  } catch (e) {
    document.getElementById("metaStats").innerHTML = `<p class="muted">Fetch failed: ${escapeHtml(String(e))}</p>`;
  }

  try {
    const r = await fetch("/jspace/eval_report");
    if (r.ok) {
      const j = await r.json();
      document.getElementById("reportBody").innerHTML = renderMarkdown(j.report_markdown || "");
    } else {
      document.getElementById("reportBody").innerHTML =
        `<div class="alert">No eval report yet — run <code>make eval</code> (or <code>python scripts/make_report.py</code>) to generate one.</div>`;
    }
  } catch (e) {
    document.getElementById("reportBody").innerHTML = `<div class="alert">Fetch failed: ${escapeHtml(String(e))}</div>`;
  }

  try {
    const r = await fetch("/agent_eval/scoreboard");
    if (r.ok) {
      const j = await r.json();
      document.getElementById("agentEvalBody").innerHTML = renderMarkdown(j.scoreboard_markdown || "");
    } else {
      document.getElementById("agentEvalBody").innerHTML =
        `<div class="alert">No agent-eval scoreboard yet — run <code>python scripts/ava_claw_run.py --tag &lt;name&gt;</code> from the agent-eval repo once there's RAM headroom (HTTP ${r.status}).</div>`;
    }
  } catch (e) {
    document.getElementById("agentEvalBody").innerHTML = `<div class="alert">Fetch failed: ${escapeHtml(String(e))}</div>`;
  }
}

load();
</script>
</body>
</html>
"""
