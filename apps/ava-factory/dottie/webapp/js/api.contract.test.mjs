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

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
