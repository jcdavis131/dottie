import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = (file) => readFile(path.join(root, file), "utf8");

test("pair verification is same-origin POST and issues a hardened host cookie", async () => {
  const route = await source("app/api/pair/verify/route.ts");
  assert.match(route, /ARXIVIQ_PUBLIC_ORIGIN/);
  assert.match(route, /sec-fetch-site/);
  assert.match(route, /SESSION_COOKIE/);
  assert.match(route, /httpOnly:\s*true/);
  assert.match(route, /secure:\s*true/);
  assert.match(route, /sameSite:\s*"strict"/);
  assert.match(route, /maxAge:\s*session\.maxAge/);
  assert.doesNotMatch(route, /export async function GET/);
  assert.doesNotMatch(route, /\.\.\.proxied\.data/);
});

test("pair traffic uses trusted pseudonymous centralized identities", async () => {
  const limiter = await source("lib/pair-rate.ts");
  const verify = await source("app/api/pair/verify/route.ts");
  const status = await source("app/api/pair/status/route.ts");
  assert.match(limiter, /createHmac\("sha256", secret\)/);
  assert.match(limiter, /x-vercel-forwarded-for/);
  assert.match(limiter, /ARXIVIQ_TRUSTED_CLIENT_IP_HEADER/);
  assert.doesNotMatch(limiter, /req\.headers\.get\("x-forwarded-for"\)/);
  assert.match(verify, /resolvePairClient\(req,\s*"verify"\)/);
  assert.match(verify, /agentId:\s*pairClient\.agentId/);
  assert.match(status, /resolvePairClient\(req,\s*"status"\)/);
});

test("claims and goals are GET-only, session-gated, and fixed-repo", async () => {
  for (const board of ["claims", "goals"]) {
    const route = await source(`app/api/jarvis/${board}/route.ts`);
    assert.match(route, /readSession/);
    assert.match(route, /session\.repo/);
    assert.match(route, /new URLSearchParams\(\{\s*repo:\s*session\.repo/s);
    assert.doesNotMatch(route, /searchParams\.get\(["']repo["']\)/);
    assert.match(route, /arxiviq-session-\$\{session\.sid\}/);
    assert.match(route, /ephemeralAuth:\s*true/);
    assert.doesNotMatch(route, /export async function (POST|PUT|PATCH|DELETE)/);
  }
});

test("remote jarvis requires an explicit exact HTTPS operator origin", async () => {
  const client = await source("lib/jarvis.ts");
  assert.match(client, /JARVIS_ALLOWED_ORIGINS/);
  assert.match(client, /parsed\.protocol !== "https:"/);
  assert.match(client, /allowedOrigins\.has\(url\.origin\)/);
  assert.match(client, /169\.254\.169\.254/);
});

test("session signatures use length-checked timing-safe comparison", async () => {
  const session = await source("lib/session.mjs");
  assert.match(session, /actual\.length !== expected\.length/);
  assert.match(session, /timingSafeEqual\(actual,\s*expected\)/);
});

test("resolveJarvisBase accepts only configured remote HTTPS origins", async () => {
  const previous = {
    JARVIS_URL: process.env.JARVIS_URL,
    JARVIS_ALLOWED_ORIGINS: process.env.JARVIS_ALLOWED_ORIGINS,
  };
  const { resolveJarvisBase } = await import("../lib/jarvis.ts");
  try {
    process.env.JARVIS_URL = "https://jarvis.example.test/api";
    process.env.JARVIS_ALLOWED_ORIGINS = "https://jarvis.example.test";
    assert.equal(resolveJarvisBase().base, "https://jarvis.example.test/api");

    process.env.JARVIS_ALLOWED_ORIGINS = "https://other.example.test";
    assert.equal(resolveJarvisBase().base, null);

    process.env.JARVIS_URL = "https://169.254.169.254/latest/meta-data";
    process.env.JARVIS_ALLOWED_ORIGINS = "https://169.254.169.254";
    assert.equal(resolveJarvisBase().base, null);

    process.env.JARVIS_URL = "https://jarvis.example.test.evil/api";
    process.env.JARVIS_ALLOWED_ORIGINS = "https://jarvis.example.test";
    assert.equal(resolveJarvisBase().base, null);

    process.env.JARVIS_URL = "http://jarvis.example.test/api";
    process.env.JARVIS_ALLOWED_ORIGINS = "https://jarvis.example.test";
    assert.equal(resolveJarvisBase().base, null);

    process.env.JARVIS_URL = "https://jarvis.example.test/api";
    process.env.JARVIS_ALLOWED_ORIGINS = "https://jarvis.example.test/path";
    assert.equal(resolveJarvisBase().base, null);

    process.env.JARVIS_URL = "https://user:pass@jarvis.example.test/api";
    process.env.JARVIS_ALLOWED_ORIGINS = "https://jarvis.example.test";
    assert.equal(resolveJarvisBase().base, null);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
});

test("jarvisFetch preserves business errors and redacts server error payloads", async (t) => {
  const requests = [];
  const server = createServer((req, res) => {
    requests.push({
      authorization: req.headers.authorization,
      agent: req.headers["x-agent-id"],
    });
    res.setHeader("Content-Type", "application/json");
    if (req.url === "/business") {
      res.writeHead(400);
      res.end(JSON.stringify({ ok: false, error: "already paired" }));
      return;
    }
    res.writeHead(500);
    res.end(JSON.stringify({ error: "upstream failed", code: "SECRET", agent: "private-agent" }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const address = server.address();
  assert.notEqual(address, null);
  assert.equal(typeof address, "object");
  const previous = {
    JARVIS_URL: process.env.JARVIS_URL,
    JARVIS_ALLOWED_ORIGINS: process.env.JARVIS_ALLOWED_ORIGINS,
    JARVIS_BEARER: process.env.JARVIS_BEARER,
  };
  const { jarvisFetch } = await import("../lib/jarvis.ts");
  try {
    process.env.JARVIS_URL = `http://127.0.0.1:${address.port}`;
    delete process.env.JARVIS_ALLOWED_ORIGINS;
    process.env.JARVIS_BEARER = "operator-bearer";

    const business = await jarvisFetch("/business", {
      method: "POST",
      agentId: "arxiviq-session-pseudonymous",
      ephemeralAuth: true,
    });
    assert.equal(business.status, 400);
    assert.equal(business.error, "already paired");
    assert.deepEqual(business.data, { ok: false, error: "already paired" });

    const serverError = await jarvisFetch("/server-error", {
      agentId: "arxiviq-session-pseudonymous",
      ephemeralAuth: true,
    });
    assert.equal(serverError.status, 503);
    assert.equal(serverError.error, "jarvisd unavailable");
    assert.equal(Object.hasOwn(serverError, "data"), false);

    assert.equal(requests.length, 2);
    assert.equal(requests.every((request) => request.agent === "arxiviq-session-pseudonymous"), true);
    assert.equal(requests.every((request) => request.authorization !== "Bearer operator-bearer"), true);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
});

test("public health uses stable redacted configuration errors", async () => {
  const health = await source("app/api/jarvis/health/route.ts");
  assert.doesNotMatch(health, /resolveJarvisBase/);
  assert.doesNotMatch(health, /\breason\b/);
  assert.match(health, /error:\s*proxied\.error/);
  assert.match(health, /provenance:\s*proxied\.provenance/);

  const previous = {
    JARVIS_URL: process.env.JARVIS_URL,
    JARVIS_ALLOWED_ORIGINS: process.env.JARVIS_ALLOWED_ORIGINS,
  };
  const { jarvisFetch } = await import("../lib/jarvis.ts");
  try {
    process.env.JARVIS_URL = "https://operator:top-secret@jarvis.example.test/api";
    process.env.JARVIS_ALLOWED_ORIGINS = "https://jarvis.example.test";
    const result = await jarvisFetch("/api/health");
    assert.equal(result.status, 503);
    assert.equal(result.provenance, "configuration_error");
    assert.equal(result.error, "jarvisd configuration is invalid");
    assert.doesNotMatch(JSON.stringify(result), /operator|top-secret/);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
});

test("pair codes are neither put in URLs nor retained after success", async () => {
  const dottie = await source("app/dottie/page.tsx");
  const conductor = await source("app/components/AgentConductorPanel.tsx");
  const status = await source("app/api/pair/status/route.ts");
  assert.match(dottie, /setPairCode\(""\)/);
  assert.doesNotMatch(conductor, /encodeURIComponent\(pairCode\)/);
  assert.match(status, /pair codes are accepted only in the POST body/);
});

test("Dottie pairing state comes only from the session endpoint", async () => {
  const dottie = await source("app/dottie/page.tsx");
  assert.match(dottie, /fetch\("\/api\/session"/);
  assert.doesNotMatch(dottie, /pairedCount/);
  assert.doesNotMatch(dottie, /paired_count/);
});

test("conductor BFF is session-gated, fixed-scope, and ephemeral", async () => {
  const snapshot = await source("app/api/conductor/snapshot/route.ts");
  const rpc = await source("app/api/conductor/rpc/route.ts");
  for (const route of [snapshot, rpc]) {
    assert.match(route, /readSession/);
    assert.match(route, /session\.repo/);
    assert.match(route, /arxiviq-session-\$\{session\.sid\}/);
    assert.match(route, /ephemeralAuth:\s*true/);
    assert.match(route, /cache-control["'],\s*["']no-store/i);
    assert.doesNotMatch(route, /searchParams\.get\(["']repo["']\)/);
    assert.doesNotMatch(route, /authorization/i);
  }
  assert.match(rpc, /ARXIVIQ_PUBLIC_ORIGIN/);
  assert.doesNotMatch(snapshot, /export async function POST/);
});

test("conductor adapter uses only the supported authenticated transport", async () => {
  const adapter = await source("lib/conductor.ts");
  const panel = await source("app/components/AgentConductorPanel.tsx");
  assert.match(adapter, /fetch\("\/api\/conductor\/snapshot"/);
  assert.match(adapter, /fetch\("\/api\/conductor\/rpc"/);
  assert.match(panel, /getConductorSnapshot/);
  assert.match(panel, /sendConductorRpc/);
  assert.match(panel, /capabilities\.write/);
  for (const sourceText of [adapter, panel]) {
    assert.doesNotMatch(sourceText, /safeGetDaemon|app\/acd/);
    assert.doesNotMatch(
      sourceText,
      /command\.|pty\.|tunnel\.|guardrail\.toggle|feedback\.compact/,
    );
  }
  assert.doesNotMatch(panel, /One touch|new session|Tidy up/);
});

test("conductor UI clears transported state when snapshot polling fails", async () => {
  const panel = await source("app/components/AgentConductorPanel.tsx");
  assert.match(panel, /catch\s*\{[\s\S]*?setSnap\(null\)/);
  assert.match(panel, /!snap\s*\?/);
  assert.match(panel, /Authenticated conductor transport is not connected/);
});

test("pair and conductor mutations share streaming bounded JSON parsing", async () => {
  const pair = await source("app/api/pair/verify/route.ts");
  const rpc = await source("app/api/conductor/rpc/route.ts");
  for (const route of [pair, rpc]) {
    assert.match(route, /readBoundedJson/);
    assert.doesNotMatch(route, /req\.(json|arrayBuffer)\(/);
  }
});

test("hydrated conductor exposes typed accessible controls only when live", async () => {
  const panel = await source("app/components/AgentConductorPanel.tsx");
  assert.doesNotMatch(panel, /@ts-nocheck|\bany\b/);
  assert.match(panel, /role=["']tablist["']/);
  assert.match(panel, /role=["']tab["']/);
  assert.match(panel, /role=["']tabpanel["']/);
  assert.match(panel, /aria-label=/);
  assert.match(panel, /Fixed mission/);
  assert.doesNotMatch(panel, /Saved automatically when a session exits|Conflicts keep/);
});

test("conductor write buttons expose capability-gated disabled states", async () => {
  const panel = await source("app/components/AgentConductorPanel.tsx");
  assert.match(
    panel,
    /disabled=\{!canWrite\("feedback\.push"\)\}[\s\S]*?>\s*Good/,
  );
  assert.match(
    panel,
    /disabled=\{!canWrite\("scratchpad\.write"\)\}[\s\S]*?>\s*Add note/,
  );
  assert.match(
    panel,
    /disabled=\{!canWrite\("todo\.create"\)\}[\s\S]*?>\s*Add task/,
  );
});
