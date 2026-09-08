import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";

const appRoot = path.resolve(import.meta.dirname, "..");
const repoRoot = path.resolve(appRoot, "..", "..");
const bearer = "e2e-jarvis-bearer";
const repo = "e2e-fixed-repo";
const secret = Buffer.alloc(32, 7).toString("base64url");
const work = await mkdtemp(path.join(tmpdir(), "arxiviq-e2e-"));
const children = [];

async function freePort() {
  const server = createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  await new Promise((resolve) => server.close(resolve));
  return port;
}

function start(command, args, options) {
  const child = spawn(command, args, { stdio: "pipe", ...options });
  children.push(child);
  return child;
}

async function waitFor(url) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`timed out waiting for ${url}`);
}

async function json(url, init = {}) {
  const response = await fetch(url, init);
  return { response, body: await response.json().catch(() => ({})) };
}

function chunkedBody(prefix, byteCount, suffix) {
  const chunks = [
    new TextEncoder().encode(prefix),
    new Uint8Array(byteCount).fill(65),
    new TextEncoder().encode(suffix),
  ];
  return new ReadableStream({
    pull(controller) {
      const chunk = chunks.shift();
      if (chunk) controller.enqueue(chunk);
      else controller.close();
    },
  });
}

async function stop(child) {
  if (child.exitCode !== null) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
  } else {
    child.kill();
  }
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 2000)),
  ]);
}

try {
  const jarvisPort = await freePort();
  const nextPort = await freePort();
  const jarvisBase = `http://127.0.0.1:${jarvisPort}`;
  const nextBase = `http://127.0.0.1:${nextPort}`;
  const publicOrigin = nextBase;
  const jarvisDb = path.join(work, "jarvis.db");
  const startJarvis = (agentRate = "100") => start(
    "uv",
    ["run", "--project", "apps/jarvisd", "python", "-m", "jarvisd", "serve", "--host", "127.0.0.1", "--port", String(jarvisPort), "--db", jarvisDb, "--no-sse", "--log-level", "warning"],
    { cwd: repoRoot, env: { ...process.env, JARVIS_BEARER: bearer, JARVIS_RATE_AGENT: agentRate } },
  );
  let jarvisChild = startJarvis("3");
  await waitFor(`${jarvisBase}/api/health`);

  const seedHeaders = {
    authorization: `Bearer ${bearer}`,
    "content-type": "application/json",
    "x-agent-id": "e2e-seed",
  };
  await json(`${jarvisBase}/api/claims`, {
    method: "POST",
    headers: seedHeaders,
    body: JSON.stringify({ repo, area: "apps/arxiviq", note: "real e2e" }),
  });
  await json(`${jarvisBase}/api/goals`, {
    method: "POST",
    headers: seedHeaders,
    body: JSON.stringify({ repo, text: "prove authenticated edge" }),
  });
  const created = await json(`${jarvisBase}/api/pair/create`, {
    method: "POST",
    headers: seedHeaders,
    body: JSON.stringify({ expire_min: 10 }),
  });
  assert.equal(created.response.status, 200);

  start(
    process.execPath,
    [path.join(appRoot, "node_modules", "next", "dist", "bin", "next"), "start", "-p", String(nextPort), "-H", "127.0.0.1"],
    {
      cwd: appRoot,
      env: {
        ...process.env,
        JARVIS_URL: jarvisBase,
        JARVIS_BEARER: bearer,
        ARXIVIQ_SESSION_SECRET: secret,
        ARXIVIQ_JARVIS_REPO: repo,
        ARXIVIQ_PUBLIC_ORIGIN: publicOrigin,
      },
    },
  );
  await waitFor(nextBase);

  const pairHeaders = {
    origin: publicOrigin,
    "sec-fetch-site": "same-origin",
    "content-type": "application/json",
  };
  const oversizedPair = await json(`${nextBase}/api/pair/verify`, {
    method: "POST",
    headers: pairHeaders,
    body: chunkedBody('{"code":"', 2048, '"}'),
    duplex: "half",
  });
  assert.equal(oversizedPair.response.status, 413, JSON.stringify(oversizedPair.body));
  const paired = await json(`${nextBase}/api/pair/verify`, {
    method: "POST",
    headers: pairHeaders,
    body: JSON.stringify({ code: created.body.code }),
  });
  assert.equal(paired.response.status, 200);
  const cookie = paired.response.headers.get("set-cookie")?.split(";", 1)[0];
  assert.match(cookie || "", /^__Host-arxiviq_session=/);

  const replay = await json(`${nextBase}/api/pair/verify`, {
    method: "POST",
    headers: pairHeaders,
    body: JSON.stringify({ code: created.body.code }),
  });
  assert.equal(replay.response.status, 400);

  const third = await json(`${nextBase}/api/pair/verify`, {
    method: "POST",
    headers: pairHeaders,
    body: JSON.stringify({ code: "ZZZZZZ" }),
  });
  assert.equal(third.response.status, 400);
  const limited = await json(`${nextBase}/api/pair/verify`, {
    method: "POST",
    headers: pairHeaders,
    body: JSON.stringify({ code: "YYYYYY" }),
  });
  assert.equal(limited.response.status, 429);

  assert.equal((await json(`${nextBase}/api/jarvis/claims`)).response.status, 401);
  assert.equal((await json(`${nextBase}/api/jarvis/claims`, { headers: { cookie: `${cookie}x` } })).response.status, 401);
  const claims = await json(`${nextBase}/api/jarvis/claims?repo=wrong`, { headers: { cookie } });
  const goals = await json(`${nextBase}/api/jarvis/goals`, { headers: { cookie } });
  assert.equal(claims.body.claims[0].repo, repo);
  assert.equal(goals.body.goals[0].repo, repo);

  await stop(jarvisChild);
  jarvisChild = startJarvis();
  await waitFor(`${jarvisBase}/api/health`);
  const conductorHeaders = { ...pairHeaders, cookie };
  const initialSnapshot = await json(`${nextBase}/api/conductor/snapshot`, {
    headers: { cookie },
  });
  assert.equal(initialSnapshot.response.status, 200);
  assert.equal(initialSnapshot.body.repo, repo);
  assert.equal(initialSnapshot.body.persistence.kind, "sqlite");
  assert.deepEqual(initialSnapshot.body.feedback, []);

  const oversizedRpc = await json(`${nextBase}/api/conductor/rpc`, {
    method: "POST",
    headers: conductorHeaders,
    body: chunkedBody(
      '{"method":"scratchpad.write","params":{"text":"',
      17 * 1024,
      '"}}',
    ),
    duplex: "half",
  });
  assert.equal(oversizedRpc.response.status, 413);
  const afterOversize = await json(`${nextBase}/api/conductor/snapshot`, {
    headers: { cookie },
  });
  assert.deepEqual(afterOversize.body.scratchpad, []);

  const feedback = await json(`${nextBase}/api/conductor/rpc`, {
    method: "POST",
    headers: conductorHeaders,
    body: JSON.stringify({
      method: "feedback.push",
      params: { kind: "note", message: "persist me", strength: 0.5 },
    }),
  });
  const scratch = await json(`${nextBase}/api/conductor/rpc`, {
    method: "POST",
    headers: conductorHeaders,
    body: JSON.stringify({
      method: "scratchpad.write",
      params: { text: "real breadcrumb" },
    }),
  });
  const todo = await json(`${nextBase}/api/conductor/rpc`, {
    method: "POST",
    headers: conductorHeaders,
    body: JSON.stringify({
      method: "todo.create",
      params: { text: "real task", priority: "high" },
    }),
  });
  assert.equal(feedback.response.status, 200);
  assert.equal(scratch.response.status, 200);
  assert.equal(todo.response.status, 200);
  const moved = await json(`${nextBase}/api/conductor/rpc`, {
    method: "POST",
    headers: conductorHeaders,
    body: JSON.stringify({
      method: "todo.move",
      params: { id: todo.body.result.id, status: "in_progress" },
    }),
  });
  assert.equal(moved.body.snapshot.todos[0].status, "in_progress");

  const blocked = await json(`${nextBase}/api/conductor/rpc`, {
    method: "POST",
    headers: conductorHeaders,
    body: JSON.stringify({ method: "command.run", params: { command: "whoami" } }),
  });
  assert.equal(blocked.response.status, 400);

  await stop(jarvisChild);
  jarvisChild = startJarvis();
  await waitFor(`${jarvisBase}/api/health`);
  const persisted = await json(`${nextBase}/api/conductor/snapshot`, {
    headers: { cookie },
  });
  assert.equal(persisted.body.feedback[0].message, "persist me");
  assert.equal(persisted.body.scratchpad[0].text, "real breadcrumb");
  assert.equal(persisted.body.todos[0].status, "in_progress");

  await stop(jarvisChild);
  const outage = await json(`${nextBase}/api/conductor/snapshot`, {
    headers: { cookie },
  });
  assert.equal(outage.response.status, 503);
  const outagePage = await fetch(`${nextBase}/conductor`, { headers: { cookie } });
  const outageHtml = await outagePage.text();
  assert.match(outageHtml, /Authenticated conductor transport is not connected/);
  assert.doesNotMatch(outageHtml, /Send note|What’s next\?/);

  assert.equal((await json(`${nextBase}/api/session`, { method: "DELETE", headers: { cookie } })).response.status, 200);
  console.log("real pair→snapshot→writes→restart→blocked-command→outage E2E passed");
} finally {
  for (const child of children.reverse()) await stop(child);
  await rm(work, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
}
