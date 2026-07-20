// Shared live snapshots + a tiny event bus. app.js runs the pollers and
// writes here; views subscribe. Each slot records what was fetched, when,
// and — when it failed — exactly why, so the UI can always tell the truth.

export const live = {
  pipeline: { ok: false, data: null, error: null, at: 0 },
  assistant: { ok: false, data: null, error: null, at: 0 },
  research: { ok: false, data: null, error: null, at: 0, source: null, sourceUrl: null },
};

const listeners = new Map(); // topic -> Set<fn>

export const bus = {
  on(topic, fn) {
    if (!listeners.has(topic)) listeners.set(topic, new Set());
    listeners.get(topic).add(fn);
    return () => listeners.get(topic)?.delete(fn);
  },
  emit(topic, payload) {
    for (const fn of listeners.get(topic) || []) {
      try {
        fn(payload);
      } catch (e) {
        console.error(`[bus:${topic}]`, e);
      }
    }
  },
};

export function setSlot(name, patch) {
  Object.assign(live[name], patch, { at: Date.now() });
  bus.emit(name, live[name]);
}
