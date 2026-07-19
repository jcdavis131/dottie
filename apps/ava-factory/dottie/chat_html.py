"""Self-contained live chat UI HTML (no CDN). Talks to the existing POST
/chat JSON API in server.py -- this file only adds the GET /chat page."""

CHAT_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Dottie Chat</title>
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
  display: flex;
  flex-direction: column;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--line);
  background: var(--card);
  flex: none;
}
header h1 { margin: 0; font-size: 1.25rem; font-weight: 600; letter-spacing: -0.02em; }
header .meta { color: var(--muted); font-size: 0.85rem; }
a { color: var(--accent); }
main {
  flex: 1; display: flex; flex-direction: column;
  max-width: 760px; width: 100%; margin: 0 auto; padding: 1rem 1.5rem;
  min-height: 0;
}
.alert {
  padding: 0.6rem 0.75rem; border: 1px solid #d4b56a; background: #f7efd8;
  color: var(--warn); font-size: 0.85rem; margin-bottom: 0.75rem; display: none;
}
.alert.show { display: block; }
.alert.bad { border-color: #c99; background: #f5e8e8; color: var(--bad); }
#thread {
  flex: 1; overflow-y: auto; border: 1px solid var(--line); background: var(--card);
  padding: 1rem; min-height: 0; display: flex; flex-direction: column; gap: 0.7rem;
}
.msg { max-width: 80%; padding: 0.55rem 0.75rem; line-height: 1.5; font-size: 0.92rem; white-space: pre-wrap; word-break: break-word; }
.msg.user { align-self: flex-end; background: var(--accent); color: #fff; }
.msg.assistant { align-self: flex-start; background: var(--bg); border: 1px solid var(--line); }
.msg.error { align-self: flex-start; background: #f5e8e8; border: 1px solid #c99; color: var(--bad); font-size: 0.82rem; }
.msg .meta { display: block; font-size: 0.65rem; opacity: 0.7; margin-top: 0.3rem; }
.empty { color: var(--muted); font-size: 0.88rem; margin: auto; text-align: center; }
.composer { display: flex; gap: 0.5rem; margin-top: 0.75rem; flex: none; }
.composer textarea {
  flex: 1; resize: none; padding: 0.6rem 0.7rem; border: 1px solid var(--line);
  background: var(--card); font: inherit; font-size: 0.92rem; min-height: 2.6rem; max-height: 8rem;
}
.composer button {
  padding: 0 1.1rem; border: 1px solid var(--accent); background: var(--accent);
  color: #fff; font: inherit; cursor: pointer;
}
.composer button:disabled { opacity: 0.5; cursor: not-allowed; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-top: 0.5rem; font-size: 0.78rem; color: var(--muted); }
.toolbar label { display: inline-flex; align-items: center; gap: 0.3rem; }
.toolbar input[type=range] { width: 6rem; }
.toolbar button.linkbtn {
  background: none; border: none; color: var(--accent); text-decoration: underline;
  cursor: pointer; font: inherit; font-size: 0.78rem; padding: 0;
}
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 0.35rem; }
.dot.ok { background: var(--ok); }
.dot.bad { background: var(--bad); }
.dot.warn { background: var(--warn); }
</style>
</head>
<body>
<header>
  <h1>Dottie chat</h1>
  <div class="meta">
    <span id="engineStatus"><span class="dot warn"></span>checking…</span>
    · <a href="/dashboard">dashboard</a>
    · <a href="/evals">evals</a>
  </div>
</header>
<main>
  <div class="alert" id="engineAlert"></div>
  <div id="thread"><div class="empty">No messages yet. This talks directly to the live checkpoint (hot-reloaded from <code>ckpt/latest</code>) — quality depends entirely on how far along training is.</div></div>
  <div class="composer">
    <textarea id="input" placeholder="Say something…" rows="1"></textarea>
    <button id="sendBtn" type="button">Send</button>
  </div>
  <div class="toolbar">
    <label>temperature <input type="range" id="temp" min="0.1" max="1.5" step="0.1" value="0.8"/> <span id="tempVal">0.8</span></label>
    <button class="linkbtn" id="clearBtn" type="button">Clear conversation</button>
  </div>
</main>
<script>
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

let history = [];  // [{role, content}] -- resent in full every turn (stateless API)
const thread = document.getElementById("thread");
const input = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const tempSlider = document.getElementById("temp");
const tempVal = document.getElementById("tempVal");

tempSlider.oninput = () => { tempVal.textContent = tempSlider.value; };

function renderThread() {
  if (!history.length) {
    thread.innerHTML = `<div class="empty">No messages yet. This talks directly to the live checkpoint (hot-reloaded from <code>ckpt/latest</code>) — quality depends entirely on how far along training is.</div>`;
    return;
  }
  thread.innerHTML = history.map(m => {
    const cls = m.role === "user" ? "user" : (m.role === "error" ? "error" : "assistant");
    const label = m.role === "user" ? "you" : (m.role === "error" ? "error" : "ava");
    const meta = m.latency_ms != null ? `<span class="meta">${label} · ${m.tokens ?? "?"} tok · ${Math.round(m.latency_ms)}ms</span>` : `<span class="meta">${label}</span>`;
    return `<div class="msg ${cls}">${escapeHtml(m.content)}${meta}</div>`;
  }).join("");
  thread.scrollTop = thread.scrollHeight;
}

async function checkEngine() {
  const statusEl = document.getElementById("engineStatus");
  const alertEl = document.getElementById("engineAlert");
  try {
    const r = await fetch("/health");
    if (r.ok) {
      statusEl.innerHTML = `<span class="dot ok"></span>engine loaded`;
      alertEl.classList.remove("show");
    } else {
      statusEl.innerHTML = `<span class="dot bad"></span>engine unavailable`;
      alertEl.textContent = `The model engine isn't loaded on this server (HTTP ${r.status}). This is common while a separate process is training — the dashboard server often runs with AVA_SKIP_ENGINE_BOOT=1 on purpose so it doesn't compete with the trainer for the GPU. Chat will fail until that's toggled off (and a checkpoint exists to load).`;
      alertEl.classList.add("show", "bad");
    }
  } catch (e) {
    statusEl.innerHTML = `<span class="dot bad"></span>unreachable`;
  }
}

async function send() {
  const text = input.value.trim();
  if (!text) return;
  history.push({ role: "user", content: text });
  input.value = "";
  input.style.height = "auto";
  renderThread();
  sendBtn.disabled = true;

  try {
    const r = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: history.filter(m => m.role === "user" || m.role === "assistant").map(m => ({ role: m.role, content: m.content })),
        temperature: Number(tempSlider.value),
        max_tokens: 256,
      }),
    });
    if (!r.ok) {
      let detail = "";
      try { detail = JSON.stringify(await r.json()); } catch { detail = await r.text(); }
      history.push({ role: "error", content: `HTTP ${r.status}: ${detail.slice(0, 400)}` });
    } else {
      const j = await r.json();
      history.push({ role: "assistant", content: j.content, tokens: j.tokens, latency_ms: j.latency_ms });
    }
  } catch (e) {
    history.push({ role: "error", content: `Request failed: ${String(e)}` });
  }
  sendBtn.disabled = false;
  renderThread();
  input.focus();
}

sendBtn.onclick = send;
input.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send(); }
});
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(128, input.scrollHeight) + "px";
});
document.getElementById("clearBtn").onclick = () => { history = []; renderThread(); };

checkEngine();
renderThread();
</script>
</body>
</html>
"""
