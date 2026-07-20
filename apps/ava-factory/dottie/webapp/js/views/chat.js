// Chat view — the primary surface. POST /assistant (ReAct trace ledger) when
// available, POST /chat as the plain fallback; the active mode is always
// visible before sending. No server-side streaming exists, so the pending
// state is an honest elapsed-time ticker, not a fake typewriter.

import { h, clear, chip, fmtInt } from "../dom.js";
import { live, bus } from "../state.js";
import { getMessages, saveMessages, touchSession, getSettings } from "../store.js";
import { ApiError } from "../api.js";

/**
 * Decide which endpoint a send would use right now.
 * auto: /assistant when the loop is usable (auth off, or a token is set);
 *       otherwise /chat. Explicit prefer settings override.
 */
export function pickEndpoint(settings, assistantStatus) {
  if (settings.prefer === "assistant") return "assistant";
  if (settings.prefer === "chat") return "chat";
  const auth = assistantStatus?.trust?.auth; // "on" | "off" | undefined
  if (auth === "on" && !settings.token) return "chat";
  return "assistant";
}

export function modeChipText(settings, assistantStatus) {
  const ep = pickEndpoint(settings, assistantStatus);
  const auth = assistantStatus?.trust?.auth;
  if (ep === "assistant") {
    const authBit = auth === "on" ? (settings.token ? "auth on · token set" : "auth on · NO token") : "auth off";
    return `POST /assistant · ReAct tool loop · ${authBit}`;
  }
  const why = settings.prefer === "chat" ? "by setting" : auth === "on" ? "no token set (assistant auth is on)" : "fallback";
  return `POST /chat · plain, no tools · ${why}`;
}

export function mountChat(root, ctx) {
  const { client, sessionId, onFirstMessage } = ctx;
  const settings = getSettings();
  let messages = getMessages(sessionId);
  let inflight = false;

  const logInner = h("div", { class: "log-inner" });
  const log = h("div", { class: "log" }, logInner);

  const modeChip = h("span", { class: "chip", role: "status" });
  const brainNote = h("span", { class: "chip" });

  const input = h("textarea", {
    placeholder: "Ask Dottie — she checks with read-only tools and shows every step…",
    rows: 1,
    "aria-label": "Message Dottie",
  });
  const sendBtn = h("button", { class: "btn", type: "button" }, "Send");

  const composer = h("div", { class: "composer" },
    h("div", { class: "composer-inner" },
      h("div", { class: "mode-row" }, modeChip, brainNote),
      h("div", { class: "compose-row" }, input, sendBtn),
    ),
  );

  const view = h("div", { class: "chat" }, log, composer);
  clear(root).append(view);

  function refreshModeChips() {
    const s = getSettings();
    const ast = live.assistant.ok ? live.assistant.data : null;
    modeChip.textContent = modeChipText(s, ast);
    const eng = ast?.engine;
    if (!live.assistant.ok) {
      brainNote.textContent = "engine: unknown (status unreachable)";
    } else if (eng?.available) {
      brainNote.textContent = "engine: loaded — replies come from the factory checkpoint";
    } else {
      brainNote.textContent = `engine: none — ${eng?.reason || "unavailable"} (sends will fail honestly)`;
    }
  }
  const unsub = bus.on("assistant", refreshModeChips);
  refreshModeChips();

  // ------------------------------------------------------------ rendering

  function stepCard(st, i) {
    const gate =
      st.gate === "denied" ? chip("DENIED", "stamp-bad")
      : st.gate === "ok" ? chip("gate ok", "stamp-ok")
      : null; // gate "n/a" — final answer, no tool call
    const rows = [];
    if (st.thought) rows.push(h("div", { class: "row" }, h("span", { class: "lbl" }, "thought"), h("span", { class: "val" }, st.thought)));
    if (st.observation != null) rows.push(h("div", { class: "row" }, h("span", { class: "lbl" }, "observ."), h("span", { class: "val mono" }, st.observation)));
    return h("div", { class: "step-card" },
      h("div", { class: "step-head" },
        h("span", { class: "n" }, String(i + 1).padStart(2, "0")),
        h("span", { class: "act" }, st.action ? st.action.replace(/^Action:\s*/, "") : st.status === "refused" ? "(refusal)" : "(final answer)"),
        gate,
        st.status && st.status !== "final" && st.status !== "ok" ? chip(st.status, st.status === "error" ? "stamp-warn" : "") : null,
      ),
      rows.length ? h("div", { class: "body" }, rows) : null,
    );
  }

  function traceLedger(meta) {
    const steps = meta?.steps || [];
    if (!steps.length) return null;
    const denied = steps.filter((s) => s.gate === "denied").length;
    const tools = steps.filter((s) => s.action).length;
    const summary = `trace · ${steps.length} step${steps.length > 1 ? "s" : ""}`
      + (tools ? ` · ${tools} tool call${tools > 1 ? "s" : ""}` : "")
      + (denied ? ` · ${denied} DENIED` : "");
    return h("details", { class: "trace" },
      h("summary", {}, summary),
      steps.map((s, i) => stepCard(s, i)),
    );
  }

  function metaChips(meta) {
    const out = [];
    if (!meta) return out;
    out.push(chip(meta.endpoint === "chat" ? "/chat" : "/assistant"));
    if (meta.refused) out.push(chip("refused", "stamp-warn"));
    if (typeof meta.tokens === "number") out.push(chip(`${fmtInt(meta.tokens)} tok`));
    if (typeof meta.latency_ms === "number") out.push(chip(`${(meta.latency_ms / 1000).toFixed(1)}s`));
    return out;
  }

  function renderMsg(m) {
    if (m.role === "user") {
      return h("div", { class: "msg user" },
        h("div", { class: "who" }, "you"),
        h("div", { class: "bubble" }, m.content));
    }
    if (m.meta?.error) {
      return h("div", { class: "msg error" },
        h("div", { class: "who" }, "dottie", chip(m.meta.endpoint === "chat" ? "/chat" : "/assistant")),
        h("div", { class: "bubble" }, m.meta.error));
    }
    return h("div", { class: "msg asst" },
      h("div", { class: "who" }, "dottie", ...metaChips(m.meta)),
      h("div", { class: "bubble" }, m.content || "(empty reply)"),
      traceLedger(m.meta));
  }

  function emptyState() {
    return h("div", { class: "empty-state" },
      h("div", { class: "glyph" }, "▙ dottie"),
      h("p", {}, "Grounded, trust-gated, telemetered. Every tool call renders as a numbered trace with its trust-gate stamp; every metric on this console is fetched live or marked unreachable."),
      h("p", {}, "Try: ", h("code", {}, "What is 19 + 23? Use the calculator."), " or ", h("code", {}, "What files are in the repo root?")));
  }

  function renderLog() {
    clear(logInner);
    if (!messages.length) logInner.append(emptyState());
    else logInner.append(...messages.map(renderMsg));
    log.scrollTop = log.scrollHeight;
  }

  // ------------------------------------------------------------ sending

  function apiMessages() {
    // The API is stateless: role/content history only, error turns excluded.
    return messages
      .filter((m) => !(m.role === "assistant" && m.meta?.error))
      .map((m) => ({ role: m.role, content: m.content }));
  }

  async function send() {
    const text = input.value.trim();
    if (!text || inflight) return;
    inflight = true;
    sendBtn.disabled = true;
    input.value = "";
    input.style.height = "";

    const s = getSettings();
    const endpoint = pickEndpoint(s, live.assistant.ok ? live.assistant.data : null);

    messages.push({ role: "user", content: text, t: Date.now() });
    if (messages.filter((m) => m.role === "user").length === 1) {
      touchSession(sessionId, { title: text.slice(0, 60) });
      onFirstMessage?.(text);
    }
    saveMessages(sessionId, messages);
    renderLog();

    // Honest pending state: no streaming server-side, so show what we know —
    // which endpoint, and how long it has actually been.
    const t0 = Date.now();
    const elapsed = h("span", {}, "0.0s");
    const pendingEl = h("div", { class: "msg asst" },
      h("div", { class: "who" }, "dottie"),
      h("div", { class: "pending-line" },
        h("span", { class: "spin", "aria-hidden": "true" }, "▚"),
        `waiting on POST /${endpoint} (no server streaming) — `, elapsed));
    logInner.append(pendingEl);
    log.scrollTop = log.scrollHeight;
    const glyphs = ["▚", "▞", "▙", "▟"];
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const tick = setInterval(() => {
      elapsed.textContent = `${((Date.now() - t0) / 1000).toFixed(1)}s`;
      if (!reduced) {
        const g = pendingEl.querySelector(".spin");
        if (g) g.textContent = glyphs[Math.floor((Date.now() - t0) / 250) % 4];
      }
    }, 100);

    // When /assistant/status already told us there is no engine, a generate
    // cannot succeed — don't make the operator sit through the full 3-minute
    // budget to hear it. (Status refreshes every 15s, so a freshly loaded
    // engine gets the full budget on the next send.)
    const engineKnownDown = live.assistant.ok && live.assistant.data?.engine?.available === false;
    const timeoutMs = engineKnownDown ? 30000 : 180000;

    let turn;
    try {
      if (endpoint === "assistant") {
        const r = await client.assistant(apiMessages(), { timeoutMs });
        turn = {
          role: "assistant", content: r.content, t: Date.now(),
          meta: { endpoint, steps: r.steps || [], tokens: r.tokens, latency_ms: r.latency_ms, refused: !!r.refused },
        };
      } else {
        const r = await client.chat(apiMessages(), { timeoutMs });
        turn = {
          role: "assistant", content: r.content, t: Date.now(),
          meta: { endpoint, tokens: r.tokens, latency_ms: r.latency_ms },
        };
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.describe() : String(e);
      let hint = "";
      if (e instanceof ApiError && e.status === 401) hint = " — set the assistant token in Settings.";
      if (e instanceof ApiError && e.status === 403) hint = " — the configured token was rejected.";
      if (e instanceof ApiError && e.status === 503) hint = " — the trainer owns the GPU right now; plain /chat will fail the same way until a serving checkpoint is loaded.";
      if (e instanceof ApiError && e.kind === "timeout" && engineKnownDown) {
        hint = ` — /assistant/status reports the engine is unavailable (${live.assistant.data?.engine?.reason || "no reason given"}), so the wait was capped at 30s.`;
      }
      turn = { role: "assistant", content: "", t: Date.now(), meta: { endpoint, error: msg + hint } };
    }
    clearInterval(tick);
    pendingEl.remove();
    messages.push(turn);
    saveMessages(sessionId, messages);
    renderLog();
    inflight = false;
    sendBtn.disabled = false;
    input.focus();
  }

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  input.addEventListener("input", () => {
    input.style.height = "";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  });

  renderLog();
  input.focus();
  return () => unsub();
}
