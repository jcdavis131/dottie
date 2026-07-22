// BLUEHENRE dev server — static files + the HONEST NPC-chat proxy.
// Zero dependencies (node >= 18). Run: node server.mjs   (PORT, DOTTIE_CHAT_URL env)
//
// Provenance doctrine (same as the Dottie console webapp): an NPC reply either
// comes from the real Dottie engine (source:"dottie") or the server says plainly
// that no engine is reachable (source:"offline"). Nothing here fabricates a
// model reply, and the client displays the source tag with every line.
import { createServer } from "node:http";
import { readFile, appendFile, mkdir } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { toShards } from "./public/js/extract.mjs";

const ROOT = join(fileURLToPath(new URL(".", import.meta.url)), "public");
const DATA_DIR = join(fileURLToPath(new URL(".", import.meta.url)), "data");
const SHARD_FILE = join(DATA_DIR, "workflows.jsonl");
const PORT = Number(process.env.PORT || 8321);
const DOTTIE_CHAT_URL = process.env.DOTTIE_CHAT_URL || ""; // e.g. http://localhost:8100/app/api/chat

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
    // P4: run-end extraction. VALIDATED runs become curriculum shards banked to a
    // LOCAL jsonl the operator can inspect and feed to the factory by hand —
    // nothing auto-ingests (SPEC "OUT of autonomous scope"). Discarded runs get an
    // honest refusal, never a silent 200-that-stored-nothing.
    if (req.method === "POST" && req.url === "/api/extract-run") {
      const chunks = [];
      for await (const c of req) chunks.push(c);
      let body = null;
      try {
        body = JSON.parse(Buffer.concat(chunks).toString("utf-8"));
      } catch {
        return send(400, MIME[".json"], JSON.stringify({ stored: 0, detail: "bad JSON" }));
      }
      if (body?.validated !== true)
        return send(200, MIME[".json"], JSON.stringify({
          stored: 0,
          detail: `discarded (${body?.reason ?? "unvalidated"}) — wiped with the session`,
        }));
      try {
        const shards = toShards(body);
        await mkdir(DATA_DIR, { recursive: true });
        await appendFile(SHARD_FILE, shards.map((s) => JSON.stringify(s)).join("\n") + "\n");
        return send(200, MIME[".json"], JSON.stringify({
          stored: shards.length,
          detail: `${shards.length} curriculum shard(s) banked to data/workflows.jsonl — ` +
            "operator feeds these to the factory explicitly; nothing auto-ingests",
        }));
      } catch (e) {
        return send(200, MIME[".json"], JSON.stringify({
          stored: 0, detail: `extraction refused: ${e.message}`,
        }));
      }
    }
    // static: normalize + confine to ROOT
    const rel = normalize(decodeURIComponent((req.url || "/").split("?")[0])).replace(/^([/\\])+/, "");
    const path = join(ROOT, rel === "" ? "index.html" : rel);
    if (!path.startsWith(ROOT)) return send(403, "text/plain", "forbidden");
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
