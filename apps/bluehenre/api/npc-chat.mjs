// Vercel serverless twin of server.mjs's /api/npc-chat — same provenance doctrine.
// The hosted build has no reachable Dottie engine unless DOTTIE_CHAT_URL is set in
// the project env; without one every NPC says so instead of pretending to think.
export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ source: "error", reply: "POST only" });
  const { npc = "?", dept = "?", prompt = "" } = req.body ?? {};
  const url = process.env.DOTTIE_CHAT_URL || "";
  if (!url) {
    return res.status(200).json({
      source: "offline",
      reply: "hosted build — no Dottie engine is reachable from here. The assistant " +
        "will not pretend to think. (The write path is the next core item: a tunnel " +
        "or directive channel makes this live from anywhere.)",
    });
  }
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message: `[BLUEHENRE npc=${npc} dept=${dept}] ${prompt}` }),
      signal: AbortSignal.timeout(20_000),
    });
    if (!r.ok) return res.status(200).json({ source: "offline", reply: `engine HTTP ${r.status} — reply withheld` });
    const d = await r.json();
    const text = d.reply ?? d.response ?? d.message;
    if (typeof text !== "string" || !text)
      return res.status(200).json({ source: "offline", reply: "engine returned no text — reply withheld" });
    return res.status(200).json({ source: "dottie", reply: text });
  } catch (e) {
    return res.status(200).json({ source: "offline", reply: `engine unreachable (${e.name}) — reply withheld` });
  }
}
