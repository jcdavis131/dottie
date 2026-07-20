// Dottie console — app shell. Owns the header instruments (brain badge,
// server mode, connection state), the session rail, the hash router, and the
// pollers that feed js/state.js. Views live in js/views/*.
//
// The brain badge extends the house doctrine to the whole page: name the
// checkpoint that answers, or say plainly that there is none and why.

import { h, clear } from "./dom.js";
import { makeClient } from "./api.js";
import { bus, setSlot } from "./state.js";
import { getSettings, saveSettings, listSessions, createSession, deleteSession, getMessages } from "./store.js";
import { mountChat } from "./views/chat.js";
import { mountOps } from "./views/ops.js";
import { mountSettings } from "./views/settings.js";

let client = makeClient(getSettings());
let timers = [];

// ---------------------------------------------------------------- polling

const INTERVALS = { pipeline: 5000, assistant: 15000, research: 20000 };

async function pollPipeline() {
  try {
    const data = await client.pipelineStatus();
    setSlot("pipeline", { ok: true, data, error: null });
  } catch (e) {
    setSlot("pipeline", { ok: false, error: e.describe ? e.describe() : String(e) });
  }
}
async function pollAssistant() {
  try {
    const data = await client.assistantStatus();
    setSlot("assistant", { ok: true, data, error: null });
  } catch (e) {
    setSlot("assistant", { ok: false, error: e.describe ? e.describe() : String(e) });
  }
}
async function pollResearch() {
  try {
    const { data, source, sourceUrl } = await client.researchStatus();
    setSlot("research", { ok: true, data, source, sourceUrl, error: null });
  } catch (e) {
    setSlot("research", { ok: false, source: null, sourceUrl: null, error: e.describe ? e.describe() : String(e) });
  }
}

function startPolling() {
  stopPolling();
  pollPipeline(); pollAssistant(); pollResearch();
  timers = [
    setInterval(pollPipeline, INTERVALS.pipeline),
    setInterval(pollAssistant, INTERVALS.assistant),
    setInterval(pollResearch, INTERVALS.research),
  ];
}
function stopPolling() {
  timers.forEach(clearInterval);
  timers = [];
}

// ---------------------------------------------------------------- theme

function applyTheme() {
  const t = getSettings().theme;
  const rootEl = document.documentElement;
  if (t === "light" || t === "dark") rootEl.dataset.theme = t;
  else delete rootEl.dataset.theme;
}

// ---------------------------------------------------------------- header

function header() {
  const brain = h("span", { class: "chip", id: "brain", role: "status", title: "which model answers here — honesty in the UI" },
    h("span", { class: "dot" }), "brain: checking…");
  const modeChip = h("span", { class: "chip", id: "srv-mode" }, h("span", { class: "dot" }), "mode: checking…");
  const conn8000 = h("span", { class: "chip", id: "conn-8000" }, h("span", { class: "dot" }), ":8000");
  const conn8100 = h("span", { class: "chip", id: "conn-8100" }, h("span", { class: "dot" }), ":8100");

  bus.on("assistant", (slot) => {
    const el = clear(brain);
    el.className = "chip";
    if (slot.ok && slot.data?.engine?.available) {
      const eng = slot.data.engine;
      const ck = String(eng.ckpt || "checkpoint").split(/[\\/]/).pop();
      const params = typeof eng.params === "number" ? ` · ${(eng.params / 1e6).toFixed(0)}M` : "";
      el.classList.add("live");
      el.append(h("span", { class: "dot" }), "brain: ", h("b", {}, ck), params + " (factory)");
    } else if (slot.ok) {
      el.classList.add("warn-c");
      el.append(h("span", { class: "dot" }), "brain: none — ", slot.data?.engine?.reason || "engine unavailable");
    } else {
      el.classList.add("down");
      el.append(h("span", { class: "dot" }), "brain: unknown — status unreachable");
    }
  });

  bus.on("pipeline", (slot) => {
    const m = clear(modeChip);
    m.className = "chip";
    if (slot.ok) {
      const mode = slot.data?.mode || {};
      const cls = { training: "live", recovering: "warn-c", throttled: "warn-c", data_prep: "warn-c", stale: "down", blocked: "down" }[mode.id] || "";
      if (cls) m.classList.add(cls);
      m.title = mode.detail || "";
      m.append(h("span", { class: "dot" }), "factory: ", h("b", {}, mode.label || "unknown"));
    } else {
      m.classList.add("down");
      m.append(h("span", { class: "dot" }), "factory: unreachable");
    }
    const c = clear(conn8000);
    c.className = `chip ${slot.ok ? "live" : "down"}`;
    c.title = slot.ok ? "GET /pipeline/status ok" : slot.error || "";
    c.append(h("span", { class: "dot" }), ":8000");
  });

  bus.on("research", (slot) => {
    const c = clear(conn8100);
    c.className = `chip ${slot.ok ? "live" : "down"}`;
    c.title = slot.ok ? `research reachable via ${slot.source}` : slot.error || "unreachable (optional service)";
    c.append(h("span", { class: "dot" }), ":8100", slot.ok && slot.source === "proxy" ? " (proxy)" : "");
  });

  const themeBtn = h("button", { class: "icon-btn", type: "button", title: "cycle theme (auto → light → dark)" }, "◐");
  themeBtn.addEventListener("click", () => {
    const order = ["auto", "light", "dark"];
    const cur = getSettings().theme;
    const next = order[(order.indexOf(cur) + 1) % order.length];
    saveSettings({ theme: next });
    applyTheme();
    themeBtn.title = `theme: ${next}`;
  });

  return h("header", { class: "top" },
    h("div", { class: "brand" }, "dottie", h("span", { class: "cursor", "aria-hidden": "true" })),
    h("div", { class: "strip" }, brain, modeChip, conn8000, conn8100),
    h("div", { class: "controls" },
      h("a", { class: "icon-btn", href: "/assistant", title: "the original single-file page" }, "spec-15 page"),
      themeBtn));
}

// ---------------------------------------------------------------- rail

function sessionRail(state) {
  const listEl = h("div", { class: "sessions", role: "list" });

  function renderList() {
    clear(listEl);
    const sessions = listSessions();
    if (!sessions.length) {
      listEl.append(h("div", { class: "rail-foot", style: "border:none;padding:.3rem .55rem" }, "no sessions yet"));
      return;
    }
    for (const s of sessions) {
      const del = h("button", { class: "del", title: "delete session", "aria-label": `delete session ${s.title}` }, "×");
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        if (!confirm(`Delete session "${s.title}"? Local only — nothing server-side to remove.`)) return;
        deleteSession(s.id);
        if (state.sessionId === s.id) {
          state.sessionId = listSessions()[0]?.id || null;
        }
        renderList();
        state.rerender();
      });
      const row = h("div", {
        class: `sess${s.id === state.sessionId ? " active" : ""}`,
        role: "listitem", tabindex: "0",
        title: `${s.title} · ${getMessages(s.id).length} turns`,
      }, h("span", { class: "t" }, s.title), del);
      const activate = () => {
        state.sessionId = s.id;
        location.hash = "#/chat";
        renderList();
        state.rerender();
      };
      row.addEventListener("click", activate);
      row.addEventListener("keydown", (e) => { if (e.key === "Enter") activate(); });
      listEl.append(row);
    }
  }

  const newBtn = h("button", { type: "button" }, "+ new");
  newBtn.addEventListener("click", () => {
    const s = createSession();
    state.sessionId = s.id;
    location.hash = "#/chat";
    renderList();
    state.rerender();
  });

  const nav = h("nav", {},
    navLink("#/chat", "chat"),
    navLink("#/ops", "operations"),
    navLink("#/settings", "settings"));

  const rail = h("aside", { class: "rail" },
    nav,
    h("div", { class: "sess-head" }, "sessions", newBtn),
    listEl,
    h("div", { class: "rail-foot" },
      "sessions live in this browser only — the API is stateless and receives the full history each turn"));

  function navLink(href, label) {
    return h("a", { class: "navlink", href, dataset: { route: href } }, h("span", {}, label), h("span", { class: "mark" }, "·"));
  }

  state.renderRail = renderList;
  state.updateNav = () => {
    for (const a of nav.querySelectorAll(".navlink")) {
      a.classList.toggle("active", a.dataset.route === (location.hash || "#/chat"));
    }
  };
  renderList();
  return rail;
}

// ---------------------------------------------------------------- router

const state = {
  sessionId: null,
  rerender: () => {},
  renderRail: () => {},
  updateNav: () => {},
};

function route() {
  const hash = location.hash || "#/chat";
  const main = document.querySelector(".view");
  if (!main) return;
  if (state.cleanup) { try { state.cleanup(); } catch { /* ignore */ } }
  state.updateNav();

  if (hash.startsWith("#/ops")) {
    state.cleanup = mountOps(main);
  } else if (hash.startsWith("#/settings")) {
    state.cleanup = mountSettings(main, {
      onSettingsChanged() {
        client = makeClient(getSettings());
        applyTheme();
        startPolling();
      },
    });
  } else {
    if (!state.sessionId) {
      const sessions = listSessions();
      state.sessionId = sessions[0]?.id || createSession().id;
      state.renderRail();
    }
    state.cleanup = mountChat(main, {
      client,
      sessionId: state.sessionId,
      onFirstMessage: () => state.renderRail(),
    });
  }
}

// ---------------------------------------------------------------- boot

function boot() {
  applyTheme();
  const app = document.getElementById("app");
  clear(app).append(
    header(),
    h("div", { class: "shell" }, sessionRail(state), h("main", { class: "view" })),
  );
  state.rerender = route;
  window.addEventListener("hashchange", route);
  startPolling();
  route();
}

boot();
