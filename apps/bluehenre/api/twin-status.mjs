// Vercel twin of /api/twin-status. Priority:
//   1. TWIN_STATUS_URL (an operator-exposed live endpoint) — proxied untouched.
//   2. The operator's OWN published live-status gist (publish_live_status.py on
//      the 4080 box pushes real telemetry there) — parsed with the same pure
//      twin.mjs functions the local server uses, freshness-capped so history is
//      never dressed up as telemetry. via:"gist-feed" stamps the channel.
//   3. Honest offline.
// Nothing here invents numbers; every value traces to a feed the training box
// itself published.
import { safeParseJson, parseTrainerTail, parseDashboard, parseLiveEvents, liveAgeS }
  from "../public/js/twin.mjs";

const GIST_URL = process.env.TWIN_GIST_URL ||
  "https://gist.githubusercontent.com/jcdavis131/929c3c0b8ad38457f0a19f4f6605085c/raw/dottie_live_status.json";
// The box's "Dottie Status publisher" task pushes the gist HOURLY — cap at
// 75 min so a healthy cadence never flickers offline, while genuinely stale
// history still refuses to render as live telemetry (ageS ships regardless).
const TWIN_MAX_AGE_S = 4500;

export default async function handler(req, res) {
  const url = process.env.TWIN_STATUS_URL || "";
  if (url) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(10_000) });
      if (!r.ok) return res.status(200).json({ source: "offline", detail: `twin feed HTTP ${r.status}` });
      return res.status(200).json(await r.json());
    } catch (e) {
      return res.status(200).json({ source: "offline", detail: `twin feed unreachable (${e.name})` });
    }
  }
  try {
    const r = await fetch(GIST_URL, { signal: AbortSignal.timeout(8_000) });
    if (!r.ok) return res.status(200).json({ source: "offline", detail: `gist feed HTTP ${r.status}` });
    const live = safeParseJson(await r.text());
    const age = liveAgeS(live, Date.now());
    if (age !== null && age > TWIN_MAX_AGE_S)
      return res.status(200).json({
        source: "offline", model: "ava-mini/tool",
        detail: `published feed is ${Math.round(age / 60)} min old — history, not telemetry`,
      });
    const status = { source: "offline", model: "ava-mini/tool" };
    const tail = parseTrainerTail(live);
    if (tail) Object.assign(status, tail, { source: "local" });
    const dash = parseDashboard(live);
    if (dash) Object.assign(status, { dashboard: dash, source: "local" });
    if (status.source === "local") {
      Object.assign(status, { via: "gist-feed", ageS: age, events: parseLiveEvents(live) });
      // the published gist also carries the full :8000 hub + research loop
      if (live.hub) status.hub = live.hub;
      if (live.research) status.research = live.research;
      status.hubPublishedUtc = live.published_utc ?? null;
    } else {
      status.detail = "published feed had no readable telemetry";
    }
    return res.status(200).json(status);
  } catch (e) {
    return res.status(200).json({ source: "offline", detail: `gist feed unreachable (${e.name})` });
  }
}
