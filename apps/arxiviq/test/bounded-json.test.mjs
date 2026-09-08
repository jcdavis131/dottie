import assert from "node:assert/strict";
import test from "node:test";

import { readBoundedJson } from "../lib/bounded-json.ts";

test("bounded JSON rejects declared oversize before reading the stream", async () => {
  const request = {
    headers: new Headers({ "content-length": "2048" }),
    get body() {
      throw new Error("body must not be accessed");
    },
  };

  const result = await readBoundedJson(request, 1024);

  assert.deepEqual(result, {
    ok: false,
    status: 413,
    error: "request body too large",
  });
});

test("bounded JSON stops a chunked body as soon as it exceeds the limit", async () => {
  let cancelled = false;
  const chunks = [
    new TextEncoder().encode('{"text":"'),
    new Uint8Array(1024),
    new Uint8Array(1024),
  ];
  const body = new ReadableStream({
    pull(controller) {
      const chunk = chunks.shift();
      if (chunk) controller.enqueue(chunk);
      else controller.close();
    },
    cancel() {
      cancelled = true;
    },
  });
  const request = new Request("http://localhost", {
    method: "POST",
    body,
    duplex: "half",
  });

  const result = await readBoundedJson(request, 1024);

  assert.equal(result.ok, false);
  assert.equal(result.status, 413);
  assert.equal(cancelled, true);
});

test("bounded JSON parses a valid object", async () => {
  const request = new Request("http://localhost", {
    method: "POST",
    body: JSON.stringify({ code: "ABCDEF" }),
  });

  assert.deepEqual(await readBoundedJson(request, 1024), {
    ok: true,
    value: { code: "ABCDEF" },
  });
});
