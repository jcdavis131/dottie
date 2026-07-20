/* Contract test for store.js — persistence must REPORT failure, never hide it.
   Runs outside a browser with a minimal localStorage shim: node js/store.contract.test.mjs */
let pass = 0, fail = 0;
const check = (name, ok, extra = "") => {
  (ok ? pass++ : fail++);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

function installStorage({ full = false } = {}) {
  const map = new Map();
  globalThis.localStorage = {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => {
      if (full) {
        const e = new Error("QuotaExceededError");
        e.name = "QuotaExceededError";
        throw e;
      }
      map.set(k, v);
    },
    removeItem: (k) => map.delete(k),
  };
  return map;
}
globalThis.location = { protocol: "http:" };

installStorage();
const store = await import(
  "file:///C:/Users/jcdav/dottie/apps/ava-factory/dottie/webapp/js/store.js");

// 1) Healthy storage: saveMessages reports success and the transcript round-trips.
const msgs = [{ role: "user", content: "hi" }];
check("saveMessages -> true when storage works", store.saveMessages("s1", msgs) === true);
check("  …and the transcript round-trips", JSON.stringify(store.getMessages("s1")) === JSON.stringify(msgs));

// 2) Full storage: the write is refused and REPORTED (this is the whole point).
installStorage({ full: true });
const ok = store.saveMessages("s1", msgs);
check("saveMessages -> false when storage is full", ok === false, `got ${ok}`);

// 3) A refused write must not throw — the chat keeps working from memory.
let threw = null;
try { store.saveSettings({ theme: "dark" }); } catch (e) { threw = e; }
check("a refused write never throws", threw === null, threw ? String(threw) : "");

// 4) Reads degrade to the fallback rather than throwing.
check("getMessages falls back to [] when nothing is stored",
  Array.isArray(store.getMessages("never-written")) && store.getMessages("never-written").length === 0);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
