// Local persistence: settings + chat sessions. Everything lives in this
// browser's localStorage; the backend API is stateless (the full message
// history is sent on every turn — POST /assistant and POST /chat accept no
// session id, so none is invented client-side).
//
// The assistant token is stored here and used ONLY as an Authorization header
// on POST /assistant. It is never logged and never sent to :8100.

const SETTINGS_KEY = "dottie.settings.v1";
const SESSIONS_KEY = "dottie.sessions.v1";
const MSGS_PREFIX = "dottie.msgs.";

function sameOriginIsApi() {
  // When the app is served by the API itself (the normal case: :8000/app),
  // relative URLs are the most robust default.
  return typeof location !== "undefined" && /^https?:$/.test(location.protocol);
}

export const DEFAULTS = Object.freeze({
  base: sameOriginIsApi() ? "" : "http://localhost:8000", // "" = same origin
  researchBase: "http://localhost:8100",
  token: "",
  prefer: "auto", // auto | assistant | chat
  theme: "auto", // auto | light | dark
});

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

/** Persist a value. Returns false when storage refused it (quota/private mode).
 *  The app keeps working from memory either way — but the caller is told, so the
 *  UI can say so. Silent loss is the one degradation this console never marks:
 *  on reload the session would quietly revert to the last write that fit. */
function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function getSettings() {
  return { ...DEFAULTS, ...read(SETTINGS_KEY, {}) };
}

export function saveSettings(patch) {
  const next = { ...getSettings(), ...patch };
  write(SETTINGS_KEY, next);
  return next;
}

// ---------------------------------------------------------------- sessions

export function listSessions() {
  return read(SESSIONS_KEY, []);
}

export function createSession() {
  const s = {
    id: `s_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
    title: "new session",
    created: Date.now(),
    updated: Date.now(),
  };
  write(SESSIONS_KEY, [s, ...listSessions()]);
  write(MSGS_PREFIX + s.id, []);
  return s;
}

export function deleteSession(id) {
  write(SESSIONS_KEY, listSessions().filter((s) => s.id !== id));
  try {
    localStorage.removeItem(MSGS_PREFIX + id);
  } catch { /* ignore */ }
}

export function touchSession(id, patch = {}) {
  const all = listSessions();
  const i = all.findIndex((s) => s.id === id);
  if (i === -1) return;
  all[i] = { ...all[i], ...patch, updated: Date.now() };
  write(SESSIONS_KEY, all);
}

export function getMessages(id) {
  return read(MSGS_PREFIX + id, []);
}

/** Returns false when the transcript could not be persisted (see write()). */
export function saveMessages(id, messages) {
  const ok = write(MSGS_PREFIX + id, messages);
  touchSession(id);
  return ok;
}

export function clearAll() {
  try {
    for (const s of listSessions()) localStorage.removeItem(MSGS_PREFIX + s.id);
    localStorage.removeItem(SESSIONS_KEY);
    localStorage.removeItem(SETTINGS_KEY);
  } catch { /* ignore */ }
}
