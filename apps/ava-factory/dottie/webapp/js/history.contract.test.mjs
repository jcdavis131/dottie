/* Contract test for chat.js's apiMessages() — the history filter.

   The backend is stateless: the FULL history is re-sent on every turn. So what this
   function includes is what the model sees, every time. Two properties matter and neither
   was covered (TODOS 5.3.R70):

     1. Error turns are excluded. A failed turn is stored with `content: ""` and the error
        text in `meta.error`, so replaying it would inject a BLANK assistant message into
        the conversation on every subsequent turn — silently degrading context in a way
        that looks like the model getting worse, not like a client bug.
     2. Only role/content are sent. `meta` carries the endpoint, timings and raw error
        strings; none of that belongs in a prompt.

   apiMessages() is a closure inside a DOM-importing module, so the logic is verified here
   and the source is asserted to still contain it — a silent removal fails this file. */

let pass = 0, fail = 0;
const check = (name, ok, extra = "") => {
  (ok ? pass++ : fail++);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`);
};

const fs = await import("node:fs");
const src = fs.readFileSync(
  "C:/Users/jcdav/dottie/apps/ava-factory/dottie/webapp/js/views/chat.js", "utf-8");

// The filter must still be wired.
check("apiMessages exists", /function apiMessages\(/.test(src));
check("error turns are still filtered out",
  /filter\(\(m\) => !\(m\.role === "assistant" && m\.meta\?\.error\)\)/.test(src));
check("only role/content are mapped",
  /map\(\(m\) => \(\{ role: m\.role, content: m\.content \}\)\)/.test(src));

// Behaviour, mirroring the implementation.
const apiMessages = (messages) => messages
  .filter((m) => !(m.role === "assistant" && m.meta?.error))
  .map((m) => ({ role: m.role, content: m.content }));

const history = [
  { role: "user", content: "hi", t: 1 },
  { role: "assistant", content: "hello", t: 2, meta: { endpoint: "/chat" } },
  { role: "user", content: "again", t: 3 },
  // a failed turn: empty content, error in meta
  { role: "assistant", content: "", t: 4, meta: { endpoint: "/assistant", error: "HTTP 503 — trainer owns the GPU" } },
  { role: "user", content: "retry", t: 5 },
];
const sent = apiMessages(history);

check("failed assistant turn is dropped", sent.length === 4, `sent=${sent.length}`);
check("no blank assistant content survives",
  !sent.some((m) => m.role === "assistant" && m.content === ""));
check("no error text reaches the API",
  !JSON.stringify(sent).includes("503"));
check("meta never leaks",
  sent.every((m) => Object.keys(m).length === 2 && "role" in m && "content" in m),
  JSON.stringify(sent[1]));
check("a successful assistant turn IS kept",
  sent.some((m) => m.role === "assistant" && m.content === "hello"));
check("user turns are untouched",
  sent.filter((m) => m.role === "user").map((m) => m.content).join(",") === "hi,again,retry");

// A user turn carrying a meta.error must NOT be dropped — the filter is scoped to
// assistant turns on purpose, and widening it would silently delete the operator's input.
const userWithMeta = apiMessages([{ role: "user", content: "keep me", meta: { error: "x" } }]);
check("a user turn with meta.error is kept", userWithMeta.length === 1);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
