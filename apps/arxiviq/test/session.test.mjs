import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import test from "node:test";

import {
  createSession,
  readSession,
  validatePublicOrigin,
} from "../lib/session.mjs";

const SECRET = "c2Vzc2lvbi1zZWNyZXQtc2Vzc2lvbi1zZWNyZXQtc2Vzc2lvbi1zZWNyZXQ";
const BASE_ENV = {
  ARXIVIQ_SESSION_SECRET: SECRET,
  ARXIVIQ_JARVIS_REPO: "dottie-main",
  JARVIS_BEARER: "different-bearer",
};

function encode(value) {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

function signClaims(claims, header = { alg: "HS256", typ: "JWT" }) {
  const unsigned = `${encode(header)}.${encode(claims)}`;
  const signature = createHmac(
    "sha256",
    Buffer.from(SECRET, "base64url"),
  ).update(unsigned).digest("base64url");
  return `${unsigned}.${signature}`;
}

test("public origin allows universal HTTPS and loopback-only HTTP", () => {
  for (const origin of [
    "https://arxiviq.example",
    "https://10.0.0.8:8443",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://[::1]:3000",
  ]) {
    assert.equal(validatePublicOrigin(origin), origin);
  }

  for (const origin of [
    "http://example.com",
    "http://dev.internal",
    "http://192.168.1.8",
    "http://127.0.0.2",
    "http://0.0.0.0",
    "https://user:pass@example.com",
    "https://example.com/path",
    "https://example.com?query=1",
    "https://example.com#fragment",
    "https://example.com/",
    "not-an-origin",
  ]) {
    assert.equal(validatePublicOrigin(origin), null);
  }
});

test("session rejects missing, weak, and reused configuration", () => {
  assert.throws(() => createSession({ agent: "a", pairExp: 2000, now: 1000 }, {}));
  assert.throws(() =>
    createSession(
      { agent: "a", pairExp: 2000, now: 1000 },
      { ...BASE_ENV, ARXIVIQ_SESSION_SECRET: "d2Vhaw" },
    ),
  );
  assert.throws(() =>
    createSession(
      { agent: "a", pairExp: 2000, now: 1000 },
      { ...BASE_ENV, JARVIS_BEARER: SECRET },
    ),
  );
});

test("session secret length is measured after decoding", () => {
  const thirtyOneBytes = Buffer.alloc(31, 7).toString("base64url");
  const thirtyTwoBytes = Buffer.alloc(32, 7).toString("base64url");

  assert.throws(() =>
    createSession(
      { agent: "a", pairExp: 1100, now: 1000 },
      { ...BASE_ENV, ARXIVIQ_SESSION_SECRET: thirtyOneBytes },
    ),
  );
  assert.doesNotThrow(() =>
    createSession(
      { agent: "a", pairExp: 1100, now: 1000 },
      { ...BASE_ENV, ARXIVIQ_SESSION_SECRET: thirtyTwoBytes },
    ),
  );
});

test("session is pseudonymous, scoped, and bounded by pair expiry", () => {
  const created = createSession({ agent: "private-agent", pairExp: 1300, now: 1000 }, BASE_ENV);
  assert.equal(created.maxAge, 300);
  assert.equal(created.claims.iss, "arxiviq");
  assert.equal(created.claims.aud, "jarvisd");
  assert.equal(created.claims.repo, "dottie-main");
  assert.deepEqual(created.claims.caps, [
    "claims:read",
    "goals:read",
    "conductor:read",
    "conductor:write",
  ]);
  assert.notEqual(created.claims.sub, "private-agent");
  assert.doesNotMatch(created.token, /private-agent|different-bearer/);
  assert.deepEqual(readSession(created.token, { ...BASE_ENV, now: 1000 }), created.claims);
});

test("session lifetime is capped at ten minutes", () => {
  const created = createSession({ agent: "a", pairExp: 10_000, now: 1000 }, BASE_ENV);

  assert.equal(created.maxAge, 600);
  assert.equal(created.claims.exp, 1600);
  assert.notEqual(readSession(created.token, { ...BASE_ENV, now: 1599 }), null);
  assert.equal(readSession(created.token, { ...BASE_ENV, now: 1600 }), null);
});

test("session rejects malformed, tampered, expired, and future tokens", () => {
  const created = createSession({ agent: "a", pairExp: 1600, now: 1000 }, BASE_ENV);
  assert.equal(readSession("malformed", { ...BASE_ENV, now: 1000 }), null);
  assert.equal(readSession(`${created.token}.extra`, { ...BASE_ENV, now: 1000 }), null);
  assert.equal(readSession(created.token.slice(0, -8), { ...BASE_ENV, now: 1000 }), null);
  assert.equal(readSession(`${created.token.slice(0, -1)}x`, { ...BASE_ENV, now: 1000 }), null);
  assert.equal(readSession(created.token, { ...BASE_ENV, now: 1601 }), null);
  assert.equal(readSession(created.token, { ...BASE_ENV, now: 900 }), null);
  assert.equal(
    readSession(created.token, {
      ...BASE_ENV,
      ARXIVIQ_SESSION_SECRET: "b3RoZXItc2VjcmV0LW90aGVyLXNlY3JldC1vdGhlci1zZWNyZXQ",
      now: 1000,
    }),
    null,
  );
});

test("session rejects correctly signed malformed payloads", () => {
  const created = createSession({ agent: "a", pairExp: 1600, now: 1000 }, BASE_ENV);
  const unsigned = `${encode({ alg: "HS256", typ: "JWT" })}.bm90LWpzb24`;
  const malformed = `${unsigned}.${createHmac(
    "sha256",
    Buffer.from(SECRET, "base64url"),
  ).update(unsigned).digest("base64url")}`;

  assert.equal(readSession(malformed, { ...BASE_ENV, now: 1000 }), null);
  assert.equal(
    readSession(
      signClaims({ ...created.claims, repo: "attacker-controlled" }),
      { ...BASE_ENV, now: 1000 },
    ),
    null,
  );
});

test("session rejects signed capability expansion and empty identities", () => {
  const created = createSession({ agent: "a", pairExp: 1600, now: 1000 }, BASE_ENV);

  assert.equal(
    readSession(
      signClaims({ ...created.claims, caps: [...created.claims.caps, "claims:write"] }),
      { ...BASE_ENV, now: 1000 },
    ),
    null,
  );
  assert.equal(
    readSession(signClaims({ ...created.claims, sid: "" }), { ...BASE_ENV, now: 1000 }),
    null,
  );
  assert.equal(
    readSession(signClaims({ ...created.claims, sub: "" }), { ...BASE_ENV, now: 1000 }),
    null,
  );
});
