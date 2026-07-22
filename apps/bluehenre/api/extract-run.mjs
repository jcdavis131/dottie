// Vercel serverless twin of /api/extract-run. A hosted deployment has no durable
// local disk and no factory — so it HONESTLY refuses to bank shards rather than
// pretending storage happened. Training-signal extraction is a local-run feature.
export default function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ stored: 0, detail: "POST only" });
  const body = req.body ?? {};
  if (body.validated !== true)
    return res.status(200).json({
      stored: 0,
      detail: `discarded (${body.reason ?? "unvalidated"}) — wiped with the session`,
    });
  return res.status(200).json({
    stored: 0,
    detail: "hosted build — validated run acknowledged but NOT banked (no durable disk, " +
      "no factory here). Run the game locally (node server.mjs) to bank curriculum shards.",
  });
}
