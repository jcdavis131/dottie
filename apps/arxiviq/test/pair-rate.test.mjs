import assert from "node:assert/strict";
import test from "node:test";

import { resolvePairClient } from "../lib/pair-rate.ts";

function request(url, headers = {}) {
  return { headers: new Headers(headers), nextUrl: new URL(url) };
}

const BASE_ENV = {
  ARXIVIQ_PUBLIC_ORIGIN: "https://arxiviq.example",
  JARVIS_BEARER: "server-only-pair-hmac-key",
};

test("Vercel identity trusts only validated platform client metadata", () => {
  const env = { ...BASE_ENV, VERCEL: "1" };
  const first = resolvePairClient(
    request("https://arxiviq.example/api/pair/verify", {
      "x-vercel-forwarded-for": "198.51.100.8",
      "x-forwarded-for": "203.0.113.99",
    }),
    "verify",
    env,
  );
  const same = resolvePairClient(
    request("https://arxiviq.example/api/pair/verify", {
      "x-vercel-forwarded-for": "198.51.100.8",
      "x-forwarded-for": "192.0.2.4",
    }),
    "verify",
    env,
  );
  assert.equal(first.ok, true);
  assert.equal(same.ok, true);
  assert.equal(first.agentId, same.agentId);
  assert.doesNotMatch(JSON.stringify(first), /198\.51\.100\.8/);
  const different = resolvePairClient(
    request("https://arxiviq.example/api/pair/verify", {
      "x-vercel-forwarded-for": "198.51.100.9",
    }),
    "verify",
    env,
  );
  assert.equal(different.ok, true);
  assert.notEqual(first.agentId, different.agentId);
  assert.equal(
    resolvePairClient(request("https://arxiviq.example/api/pair/verify"), "verify", env).ok,
    false,
  );
  assert.equal(
    resolvePairClient(
      request("https://arxiviq.example/api/pair/verify", {
        "x-vercel-forwarded-for": "not-an-ip",
      }),
      "verify",
      env,
    ).ok,
    false,
  );
});

test("non-Vercel public identity requires an explicit trusted IP header", () => {
  const req = request("https://arxiviq.example/api/pair/verify", {
    "x-forwarded-for": "198.51.100.1",
    "x-real-client-ip": "203.0.113.7",
  });
  assert.equal(resolvePairClient(req, "verify", BASE_ENV).ok, false);
  assert.equal(
    resolvePairClient(req, "verify", {
      ...BASE_ENV,
      ARXIVIQ_TRUSTED_CLIENT_IP_HEADER: "x-missing-client-ip",
    }).ok,
    false,
  );
  assert.equal(
    resolvePairClient(
      request("https://arxiviq.example/api/pair/verify", {
        "x-real-client-ip": "203.0.113.7, 192.0.2.1",
      }),
      "verify",
      {
        ...BASE_ENV,
        ARXIVIQ_TRUSTED_CLIENT_IP_HEADER: "x-real-client-ip",
      },
    ).ok,
    false,
  );
  const trusted = resolvePairClient(req, "verify", {
    ...BASE_ENV,
    ARXIVIQ_TRUSTED_CLIENT_IP_HEADER: "x-real-client-ip",
  });
  assert.equal(trusted.ok, true);
  assert.match(trusted.agentId, /^arxiviq-pair-verify-[a-f0-9]{32}$/);
});

test("exact local loopback operation uses one fixed pseudonymous identity", () => {
  const env = {
    ...BASE_ENV,
    ARXIVIQ_PUBLIC_ORIGIN: "http://127.0.0.1:3000",
  };
  const a = resolvePairClient(
    request("http://127.0.0.1:3000/api/pair/verify", {
      host: "127.0.0.1:3000",
      "x-forwarded-for": "198.51.100.1",
    }),
    "verify",
    env,
  );
  const b = resolvePairClient(
    request("http://127.0.0.1:3000/api/pair/verify", {
      host: "127.0.0.1:3000",
      "x-forwarded-for": "203.0.113.2",
    }),
    "verify",
    env,
  );
  assert.equal(a.ok, true);
  assert.equal(a.agentId, b.agentId);
  assert.doesNotMatch(a.agentId, /127\.0\.0\.1/);
});
