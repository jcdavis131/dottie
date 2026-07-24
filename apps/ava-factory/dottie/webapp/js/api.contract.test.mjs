/* Contract test for the webapp's api.js — it documents itself as importable and
   testable outside a browser, so test it there. Asserts the module's own promise:
   EVERY failure leaves as a typed ApiError. */
const mod = await import(
  "file:///C:/Users/jcdav/dottie/apps/ava-factory/dottie/webapp/js/api.js");
const { makeClient, ApiError } = mod;

let pass = 0, fail = 0;
const check = (name, ok, extra = "") => {
  (ok ? pass++ : fail++);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

const client = () => makeClient({ base: "http://x", researchBase: "http://y", token: "" });

// 1) 200 with a NON-JSON body (the gap): must be a typed ApiError, not SyntaxError.
globalThis.fetch = async () => ({
  ok: true, status: 200,
  json: async () => { throw new SyntaxError("Unexpected token '<', \"<html>\"... is not valid JSON"); },
});
try {
  await client().pipelineStatus();
  check("200 non-JSON body throws", false, "no error thrown at all");
} catch (e) {
  check("200 non-JSON body -> ApiError", e instanceof ApiError, e && e.constructor && e.constructor.name);
  check("  …carries status 200", e.status === 200, `status=${e.status}`);
  check("  …describe() is operator-facing", /HTTP 200/.test(e.describe()) && !/Unexpected token/.test(e.describe().split("—")[0]),
    JSON.stringify(e.describe()).slice(0, 90));
}

// 2) Non-2xx with a JSON detail: unchanged behaviour.
globalThis.fetch = async () => ({
  ok: false, status: 503, json: async () => ({ detail: "trainer owns the GPU" }),
});
try {
  await client().chat([]);
  check("503 throws", false);
} catch (e) {
  check("503 -> ApiError with server detail",
    e instanceof ApiError && e.status === 503 && /trainer owns the GPU/.test(e.describe()), e.describe());
}

// 3) Happy path still returns parsed JSON.
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ mode: "Training" }) });
const okBody = await client().pipelineStatus();
check("200 JSON body returns parsed payload", okBody && okBody.mode === "Training");

// 4) Network failure stays typed.
globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
try {
  await client().chat([]);
  check("network error throws", false);
} catch (e) {
  check("network -> ApiError(kind=network)", e instanceof ApiError && e.kind === "network", e.describe());
}


// 5) A proxy 200 with a drifted shape must NOT become an empty-but-successful read.
//    Verified contract: server.py returns {ok, source, status} on 200 and 502 on failure,
//    so `status` is present today. But `wrapped.status` on a drifted 200 would hand the UI
//    `undefined` as data -- a research panel that renders empty while reporting success,
//    which is exactly what the doctrine at the top of api.js forbids. Direct call fails
//    first (research base http://y is stubbed unreachable), so this exercises the proxy branch.
globalThis.fetch = async (url) => {
  if (String(url).startsWith("http://y")) throw new TypeError("Failed to fetch"); // direct research base
  return { ok: true, status: 200, json: async () => ({ ok: true, source: "x" }) }; // no `status`
};
try {
  await client().researchStatus();
  check("proxy 200 without `status` throws", false);
} catch (e) {
  check("proxy 200 without `status` -> ApiError naming the shape",
    e instanceof ApiError && /unexpected shape|status/.test(e.describe()), e.describe());
}

// 6) And the well-formed proxy response still works.
globalThis.fetch = async (url) => {
  if (String(url).startsWith("http://y")) throw new TypeError("Failed to fetch"); // direct research base
  return { ok: true, status: 200, json: async () => ({ ok: true, source: "u", status: { counts: { total: 3 } } }) };
};
const viaProxy = await client().researchStatus();
check("well-formed proxy response returns its payload",
  viaProxy.source === "proxy" && viaProxy.data.counts.total === 3);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
