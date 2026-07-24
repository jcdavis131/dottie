// Settings view: backend base URLs, assistant token (localStorage only, sent
// solely as a Bearer header to POST /assistant, never logged), endpoint
// preference, theme, and local-data reset.

import { h, clear } from "../dom.js";
import { getSettings, saveSettings, clearAll, DEFAULTS } from "../store.js";

export function mountSettings(root, ctx) {
  const s = getSettings();

  const baseIn = h("input", { type: "text", value: s.base, placeholder: DEFAULTS.base || "(same origin)", id: "set-base" });
  const researchIn = h("input", { type: "text", value: s.researchBase, placeholder: "http://localhost:8100", id: "set-research" });
  const tokenIn = h("input", { type: "password", value: s.token, autocomplete: "off", id: "set-token", placeholder: "(none — auth may be off server-side)" });
  const showBtn = h("button", { class: "icon-btn", type: "button" }, "show");
  showBtn.addEventListener("click", () => {
    const hidden = tokenIn.type === "password";
    tokenIn.type = hidden ? "text" : "password";
    showBtn.textContent = hidden ? "hide" : "show";
  });

  const preferSel = h("select", { id: "set-prefer" },
    h("option", { value: "auto", selected: s.prefer === "auto" }, "auto — /assistant when usable, else /chat"),
    h("option", { value: "assistant", selected: s.prefer === "assistant" }, "always POST /assistant (ReAct tools)"),
    h("option", { value: "chat", selected: s.prefer === "chat" }, "always POST /chat (plain)"));

  const themeSel = h("select", { id: "set-theme" },
    h("option", { value: "auto", selected: s.theme === "auto" }, "auto — follow the OS"),
    h("option", { value: "light", selected: s.theme === "light" }, "light (paper)"),
    h("option", { value: "dark", selected: s.theme === "dark" }, "dark (night shift)"));

  const savedNote = h("span", { class: "save-note", role: "status" });
  const saveBtn = h("button", { class: "btn", type: "button" }, "Save settings");
  saveBtn.addEventListener("click", () => {
    const { persisted } = saveSettings({
      base: baseIn.value.trim(),
      researchBase: researchIn.value.trim(),
      token: tokenIn.value, // deliberately not trimmed-and-logged anywhere
      prefer: preferSel.value,
      theme: themeSel.value,
    });
    // Do not claim a save this browser refused. On quota/private-mode the settings --
    // including the token -- revert on reload, and an unconditional "saved" is how the
    // operator finds out the hard way (TODOS 5.3.R68).
    savedNote.textContent = persisted
      ? "saved — clients and pollers restarted"
      : "applied for this session ONLY — the browser refused to store it (private mode or quota), so it will be lost on reload";
    ctx.onSettingsChanged?.();
    setTimeout(() => { savedNote.textContent = ""; }, 4000);
  });

  const resetBtn = h("button", { class: "icon-btn danger", type: "button" }, "erase all local data");
  resetBtn.addEventListener("click", () => {
    if (!confirm("Erase all local sessions, messages, and settings (including the token) from this browser?")) return;
    clearAll();
    location.hash = "#/chat";
    location.reload();
  });

  const field = (label, control, hint) => h("div", { class: "field" },
    h("label", { for: control.id || null }, label), control,
    hint ? h("div", { class: "hint" }, hint) : null);

  clear(root).append(h("div", { class: "settings" }, h("div", { class: "settings-inner" },
    h("h2", {}, "Backends"),
    field("factory server (:8000)", baseIn,
      "Base URL for /assistant, /chat, /assistant/status, /pipeline/status. Empty = same origin as this page."),
    field("research server (:8100)", researchIn,
      "Optional. Fetched directly first; when CORS blocks that, the console falls back to the :8000 server-side proxy and labels the source."),
    h("h2", {}, "Assistant auth"),
    field("assistant token", h("div", { class: "row" }, tokenIn, showBtn),
      "Stored only in this browser's localStorage. Sent only as \"Authorization: Bearer …\" on POST /assistant. Never logged, never sent to :8100. Leave empty when the server runs with auth off."),
    field("endpoint preference", preferSel,
      "Sessions are local to this browser; both endpoints are stateless and receive the full message history each turn."),
    h("h2", {}, "Appearance"),
    field("theme", themeSel),
    h("div", { class: "save-row" }, saveBtn, savedNote),
    h("h2", {}, "Local data"),
    h("div", { class: "save-row" }, resetBtn),
  )));
  return () => {};
}
