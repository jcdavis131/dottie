// Vercel twin of /api/twin-status. The hosted build has NO access to the
// training box, so by default it says exactly that (source:"offline") instead
// of inventing telemetry. If the operator exposes a status endpoint and sets
// TWIN_STATUS_URL, we proxy it and pass its source through untouched.
export default async function handler(req, res) {
  const url = process.env.TWIN_STATUS_URL || "";
  if (!url) {
    return res.status(200).json({
      source: "offline", model: "ava-mini/tool",
      detail: "hosted build cannot see the training box — the REAL twin numbers only render when the game runs on (or can reach) the machine training the model",
    });
  }
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(10_000) });
    if (!r.ok) return res.status(200).json({ source: "offline", detail: `twin feed HTTP ${r.status}` });
    return res.status(200).json(await r.json());
  } catch (e) {
    return res.status(200).json({ source: "offline", detail: `twin feed unreachable (${e.name})` });
  }
}
