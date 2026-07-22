// BLUEHENRE org console server — static console + honest data APIs.
// Zero dependencies (node >= 18). Run: node server.mjs   (PORT, DOTTIE_CHAT_URL env)
//
// Provenance doctrine: a chat reply either comes from the real Dottie engine
// (source:"dottie") or the server says plainly that no engine is reachable
// (source:"offline"). Telemetry renders only from source:"local" feeds.
// Nothing here fabricates a model reply or a number.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { parseMetricsTail, safeParseJson, parseEvalSummary, parseTrainerTail,
         parseDashboard, parseLiveEvents, liveAgeS, parseFleet } from "./public/js/twin.mjs";

const execFileP = promisify(execFile);

const ROOT = join(fileURLToPath(new URL(".", import.meta.url)), "public");
const PORT = Number(process.env.PORT || 8321);
const DOTTIE_CHAT_URL = process.env.DOTTIE_CHAT_URL || ""; // e.g. http://localhost:8100/app/api/chat
// Twin telemetry sources — the REAL factory artifacts on this machine (SPEC
// "the Dottie digital twin"). Overridable so the operator can point at live
// exports; absent files degrade honestly to source:"offline".
const APP_DIR = fileURLToPath(new URL(".", import.meta.url));
const TWIN_METRICS = process.env.DOTTIE_TWIN_METRICS ||
  join(APP_DIR, "..", "ava-factory", "reports", "metrics_mini.jsonl");
const TWIN_EVAL = process.env.DOTTIE_TWIN_EVAL ||
  join(APP_DIR, "..", "ava-factory", "reports", "branch_eval_results_real.json");
// Primary twin source (operator 2026-07-22 "bring the dashboard to life"):
// the factory hub's live /pipeline/status endpoint — the same JSON the :8000
// dashboard renders, fetched fresh. Fallback: the exported live-status gist
// file, then the raw metrics/eval artifacts. All degrade honestly to offline.
const TWIN_PIPELINE_URL = process.env.DOTTIE_TWIN_PIPELINE ??
  "http://localhost:8000/pipeline/status";
const TWIN_LIVE_FILE = process.env.DOTTIE_TWIN_LIVE ||
  join(APP_DIR, "..", "ava-factory", "reports", "dottie_live_status.json");
const TWIN_MAX_AGE_S = 3600; // a feed older than this is history, not telemetry

const fleetCache = { at: 0, value: null };

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

async function npcChat(body) {
  const { npc = "?", dept = "?", prompt = "" } = body ?? {};
  if (!DOTTIE_CHAT_URL) {
    return {
      source: "offline",
      reply: `(${npc}/${dept}) no Dottie engine configured — set DOTTIE_CHAT_URL. ` +
        "This NPC will not pretend to think.",
    };
  }
  try {
    const r = await fetch(DOTTIE_CHAT_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message: `[BLUEHENRE npc=${npc} dept=${dept}] ${prompt}` }),
      signal: AbortSignal.timeout(20_000),
    });
    if (!r.ok) return { source: "offline", reply: `engine HTTP ${r.status} — reply withheld` };
    const d = await r.json();
    const text = d.reply ?? d.response ?? d.message;
    if (typeof text !== "string" || !text)
      return { source: "offline", reply: "engine returned no text — reply withheld" };
    return { source: "dottie", reply: text };
  } catch (e) {
    return { source: "offline", reply: `engine unreachable (${e.name}) — reply withheld` };
  }
}

const server = createServer(async (req, res) => {
  const send = (code, type, data) => {
    res.writeHead(code, { "content-type": type });
    res.end(data);
  };
  try {
    if (req.method === "POST" && req.url === "/api/npc-chat") {
      const chunks = [];
      for await (const c of req) chunks.push(c);
      let body = null;
      try {
        body = JSON.parse(Buffer.concat(chunks).toString("utf-8"));
      } catch {
        return send(400, MIME[".json"], JSON.stringify({ source: "error", reply: "bad JSON" }));
      }
      return send(200, MIME[".json"], JSON.stringify(await npcChat(body)));
    }
    if (req.method === "GET" && (req.url || "").split("?")[0] === "/api/fleet") {
      // The REAL docker fleet (operator 2026-07-22: NPCs are the containers).
      // docker's own numbers via the CLI, cached 10s; honest offline on error.
      const now = Date.now();
      if (!fleetCache.at || now - fleetCache.at > 10_000) {
        try {
          const { stdout } = await execFileP(
            "docker", ["stats", "--no-stream", "--format", "{{json .}}"],
            { timeout: 15_000 });
          fleetCache.value = { source: "local", ts: now, containers: parseFleet(stdout) };
        } catch (e) {
          fleetCache.value = { source: "offline", detail: `docker unreachable (${e.code ?? e.message})` };
        }
        fleetCache.at = now;
      }
      return send(200, MIME[".json"], JSON.stringify(fleetCache.value));
    }
    if (req.method === "GET" && (req.url || "").split("?")[0] === "/api/twin-status") {
      // REAL telemetry from this machine — the digital twin's whole point.
      // Numbers only when a genuine feed is readable AND fresh; else offline.
      const status = { source: "offline", model: "ava-mini/tool" };
      let live = null;
      let liveVia = null;
      if (TWIN_PIPELINE_URL) {
        try {
          const r = await fetch(TWIN_PIPELINE_URL, { signal: AbortSignal.timeout(2500) });
          if (r.ok) { live = await r.json(); liveVia = "pipeline-endpoint"; }
        } catch { /* hub down — fall through to the exported file */ }
      }
      if (!live) {
        try {
          live = safeParseJson(await readFile(TWIN_LIVE_FILE, "utf-8"));
          liveVia = "live-status-file";
        } catch { /* no export either — raw artifacts below */ }
      }
      if (live) {
        const age = liveAgeS(live, Date.now());
        if (age !== null && age > TWIN_MAX_AGE_S) {
          status.detail = `live feed is ${Math.round(age / 60)} min old — history, not telemetry`;
          live = null;
        }
      }
      if (live) {
        const tail = parseTrainerTail(live);
        if (tail) Object.assign(status, tail, { source: "local" });
        const dash = parseDashboard(live);
        if (dash) Object.assign(status, { dashboard: dash, source: "local", via: liveVia });
        status.events = parseLiveEvents(live);
      }
      if (status.source !== "local") {
        try {
          const tail = parseMetricsTail(await readFile(TWIN_METRICS, "utf-8"));
          if (tail) Object.assign(status, tail, { source: "local" });
        } catch { /* metrics not exported to host — eval alone may still light it */ }
      }
      // hub panels + research ride the published live-status FILE regardless of
      // which primary source won (the /pipeline/status endpoint doesn't carry
      // them). Hourly publisher cadence; a stale file (>2h) attaches nothing.
      try {
        const lf = safeParseJson(await readFile(TWIN_LIVE_FILE, "utf-8"));
        const lfAge = liveAgeS(lf, Date.now());
        if (lf && (lfAge === null || lfAge < 7200)) {
          if (lf.hub) status.hub = lf.hub;
          if (lf.research) status.research = lf.research;
          status.hubPublishedUtc = lf.published_utc ?? null;
        }
      } catch { /* no export — panels stay offline */ }
      try {
        const summary = parseEvalSummary(safeParseJson(await readFile(TWIN_EVAL, "utf-8")));
        // evalTokens, NOT tokens: the trainer's cumulative token count must not
        // be overwritten by the (tiny) held-out eval token count.
        if (summary) Object.assign(status,
          { weightedPpl: summary.weightedPpl, evalTokens: summary.tokens, source: "local" });
      } catch { /* no eval report — fine */ }
      if (status.source !== "local")
        status.detail ??= "no factory feed readable here — set DOTTIE_TWIN_PIPELINE / DOTTIE_TWIN_LIVE / DOTTIE_TWIN_METRICS";
      return send(200, MIME[".json"], JSON.stringify(status));
    }
    // static: normalize + confine to ROOT
    const rel = normalize(decodeURIComponent((req.url || "/").split("?")[0])).replace(/^([/\\])+/, "");
    const path = join(ROOT, rel === "" ? "index.html" : rel);
    // Prefix check WITH the separator: bare startsWith(ROOT) would also admit a
    // sibling directory whose name extends ROOT's ("public_backup"), the classic
    // latent traversal footgun. No such sibling exists today; keep it that way.
    if (path !== ROOT && !path.startsWith(ROOT + sep)) return send(403, "text/plain", "forbidden");
    const data = await readFile(path.endsWith(ROOT) ? join(ROOT, "index.html") : path);
    return send(200, MIME[extname(path)] || "application/octet-stream", data);
  } catch (e) {
    if (e.code === "ENOENT" || e.code === "EISDIR") {
      // SPA-less fallback: only "/" maps to index.html; everything else is a real 404
      if ((req.url || "/").split("?")[0] === "/")
        return send(200, MIME[".html"], await readFile(join(ROOT, "index.html")));
      return send(404, "text/plain", "not found");
    }
    return send(500, "text/plain", `server error: ${e.message}`);
  }
});

server.listen(PORT, () => {
  console.log(`BLUEHENRE slice on http://localhost:${PORT}  (dottie engine: ${DOTTIE_CHAT_URL || "none — offline-honest"})`);
});
