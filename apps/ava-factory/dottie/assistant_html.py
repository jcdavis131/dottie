"""Self-contained Dottie assistant UI (no CDN). Talks to POST /assistant and
GET /assistant/status in server.py. This file only adds the GET /assistant page.

The page foregrounds the two invariants the loop guarantees: every step shows
its Thought / Action / Observation and its **trust gate** (ok / denied), and the
tool catalog + capability boundaries are shown up front from /assistant/status —
Telemetry and Trust made visible, not buried in a log."""

ASSISTANT_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Dottie — tool-use assistant</title>
<style>
:root {
  --bg: #f4f2ec; --ink: #1a1a18; --muted: #5c5a52; --line: #d4d0c4;
  --card: #fffcf5; --ok: #2f6b3a; --warn: #9a6b12; --bad: #8b2e2e; --accent: #1e4d6b;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: "IBM Plex Sans","Segoe UI",sans-serif; background: var(--bg);
  color: var(--ink); min-height: 100vh; display: flex; flex-direction: column; }
header { display: flex; justify-content: space-between; align-items: baseline;
  padding: 1.1rem 1.4rem; border-bottom: 1px solid var(--line); background: var(--card); flex: none; }
header h1 { font-size: 1.1rem; margin: 0; letter-spacing: .02em; }
header .sub { color: var(--muted); font-size: .8rem; }
main { flex: 1; display: grid; grid-template-columns: 1fr 320px; gap: 0; min-height: 0; }
#log { padding: 1.2rem 1.4rem; overflow-y: auto; }
aside { border-left: 1px solid var(--line); background: var(--card); padding: 1rem 1.1rem;
  overflow-y: auto; font-size: .82rem; }
aside h2 { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted);
  margin: 1.1rem 0 .5rem; }
.tool { padding: .3rem 0; border-bottom: 1px dotted var(--line); }
.tool code { color: var(--accent); }
.tool .desc { color: var(--muted); }
.msg { margin-bottom: 1.1rem; max-width: 62ch; }
.msg .who { font-size: .72rem; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); }
.bubble { padding: .6rem .8rem; border: 1px solid var(--line); border-radius: 8px; background: var(--card);
  margin-top: .25rem; white-space: pre-wrap; }
.user .bubble { background: #eef0f2; }
.steps { margin-top: .4rem; border-left: 2px solid var(--line); padding-left: .7rem; }
.step { font-size: .8rem; margin: .35rem 0; }
.step .lbl { font-weight: 600; }
.gate-ok { color: var(--ok); } .gate-denied { color: var(--bad); font-weight: 700; }
.obs { color: var(--muted); font-family: ui-monospace,monospace; }
#alert { display: none; background: #f7ecd0; border-bottom: 1px solid var(--warn); color: #6b4a12;
  padding: .6rem 1.4rem; font-size: .82rem; }
footer { flex: none; border-top: 1px solid var(--line); background: var(--card); padding: .8rem 1.4rem;
  display: flex; gap: .6rem; }
#inp { flex: 1; padding: .55rem .7rem; border: 1px solid var(--line); border-radius: 6px; font: inherit; }
button { padding: .55rem 1rem; border: 1px solid var(--accent); background: var(--accent); color: #fff;
  border-radius: 6px; cursor: pointer; font: inherit; }
button:disabled { opacity: .5; cursor: default; }
.pill { display:inline-block; font-size:.68rem; padding:.05rem .4rem; border-radius: 999px;
  border:1px solid var(--line); color: var(--muted); }
</style>
</head>
<body>
<header>
  <div><h1>Dottie</h1><div class="sub">grounded · trust-gated · telemetered — spec 15</div></div>
  <div class="sub"><a href="/">index</a> · <a href="/assistant/status">status json</a></div>
</header>
<div id="alert"></div>
<main>
  <div id="log"></div>
  <aside>
    <h2>Trust policy</h2>
    <div id="policy" class="sub">loading…</div>
    <h2>Tool catalog</h2>
    <div id="tools" class="sub">loading…</div>
    <h2>Recent telemetry</h2>
    <div id="telemetry" class="sub">—</div>
  </aside>
</main>
<footer>
  <input id="inp" placeholder="Ask Dottie… (she'll call read-only tools and show every step)" />
  <button id="send">Send</button>
</footer>
<script>
const log = document.getElementById("log");
const alertEl = document.getElementById("alert");
const messages = [];

async function loadStatus() {
  try {
    const r = await fetch("/assistant/status");
    const s = await r.json();
    document.getElementById("policy").innerHTML =
      `<span class="pill">${(s.trust && s.trust.enforcement) || "capability-gated"}</span> `
      + (s.trust ? `${s.trust.read_only_tools||0} read-only tools · ${s.trust.sandboxed_tools||0} sandboxed · auth ${s.trust.auth||"off"}` : "");
    const tools = (s.tools || []);
    document.getElementById("tools").innerHTML = tools.map(t =>
      `<div class="tool"><code>${t.signature||t.name}</code><div class="desc">${t.description||""}`
      + (t.sandboxed==="True" ? ' <span class="pill">sandboxed</span>' : "") + `</div></div>`).join("") || "—";
    const tel = (s.telemetry && s.telemetry.recent) || [];
    document.getElementById("telemetry").innerHTML = tel.slice(-6).map(e =>
      `<div>${e.action||""} <span class="obs">${e.target||""}</span> <span class="pill">${e.status||""}</span></div>`).join("") || "no events yet";
  } catch (e) { /* status is best-effort */ }
}

async function checkHealth() {
  try {
    const r = await fetch("/health");
    if (!r.ok) {
      alertEl.style.display = "block";
      alertEl.textContent = `The model engine isn't loaded (HTTP ${r.status}). The dashboard server often runs with AVA_SKIP_ENGINE_BOOT=1 so it doesn't compete with the trainer for the GPU. Live chat will return 503 until that's toggled off and a checkpoint exists — the tool catalog and telemetry above are still live.`;
    }
  } catch (e) {
    alertEl.style.display = "block";
    alertEl.textContent = "Backend unreachable.";
  }
}

function addMsg(who, cls) {
  const d = document.createElement("div");
  d.className = "msg " + cls;
  d.innerHTML = `<div class="who">${who}</div><div class="bubble"></div>`;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}

function renderSteps(container, steps) {
  if (!steps || !steps.length) return;
  const s = document.createElement("div");
  s.className = "steps";
  s.innerHTML = steps.map(st => {
    if (!st.action) return `<div class="step"><span class="lbl">answer</span></div>`;
    const gate = st.gate === "denied"
      ? `<span class="gate-denied">DENIED</span>` : `<span class="gate-ok">ok</span>`;
    return `<div class="step"><span class="lbl">${st.action.replace(/^Action:\s*/,"")}</span> ${gate}`
      + (st.observation ? `<div class="obs">→ ${st.observation}</div>` : "") + `</div>`;
  }).join("");
  container.appendChild(s);
}

async function send() {
  const inp = document.getElementById("inp");
  const btn = document.getElementById("send");
  const text = inp.value.trim();
  if (!text) return;
  inp.value = ""; btn.disabled = true;
  addMsg("you", "user").querySelector(".bubble").textContent = text;
  messages.push({ role: "user", content: text });
  const holder = addMsg("dottie", "asst");
  holder.querySelector(".bubble").textContent = "…";
  try {
    const r = await fetch("/assistant", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, max_steps: 4 }),
    });
    if (!r.ok) {
      const detail = (await r.json().catch(() => ({}))).detail || r.status;
      holder.querySelector(".bubble").textContent = "⚠ " + detail;
    } else {
      const data = await r.json();
      holder.querySelector(".bubble").textContent = data.content || "(no answer)";
      renderSteps(holder, data.steps);
      messages.push({ role: "assistant", content: data.content || "" });
      loadStatus();  // refresh telemetry after the turn
    }
  } catch (e) {
    holder.querySelector(".bubble").textContent = "⚠ " + e;
  }
  btn.disabled = false; log.scrollTop = log.scrollHeight;
}

document.getElementById("send").addEventListener("click", send);
document.getElementById("inp").addEventListener("keydown", e => { if (e.key === "Enter") send(); });
loadStatus(); checkHealth();
setInterval(loadStatus, 15000);
</script>
</body>
</html>"""
