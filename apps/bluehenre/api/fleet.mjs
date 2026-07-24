// Vercel twin of /api/fleet. The hosted build cannot run docker on the
// training box; it serves the fleet snapshot the box itself published to the
// gist (hub.fleet, hourly cadence, ageS included) — or says offline honestly.
import { safeParseJson, liveAgeS, parseFleet } from "../public/js/twin.mjs";

const GIST_URL = process.env.TWIN_GIST_URL ||
  "https://gist.githubusercontent.com/jcdavis131/929c3c0b8ad38457f0a19f4f6605085c/raw/dottie_live_status.json";
const TWIN_MAX_AGE_S = 1800; // publisher runs every 10 min (operator, 2026-07-22)

export default async function handler(req, res) {
  try {
    const r = await fetch(GIST_URL, { signal: AbortSignal.timeout(8_000) });
    if (!r.ok) return res.status(200).json({ source: "offline", detail: `gist feed HTTP ${r.status}` });
    const live = safeParseJson(await r.text());
    const age = liveAgeS(live, Date.now());
    const fleet = live?.hub?.fleet;
    if (!Array.isArray(fleet?.containers) || (age !== null && age > TWIN_MAX_AGE_S))
      return res.status(200).json({
        source: "offline",
        detail: age !== null && age > TWIN_MAX_AGE_S
          ? `published fleet snapshot is ${Math.round(age / 60)} min old — history, not telemetry`
          : "published feed carries no fleet snapshot",
      });
    // same parsed shape the local server serves (raw rows -> JSONL -> parseFleet)
    const containers = parseFleet(fleet.containers.map((r) => JSON.stringify(r)).join("\n"));
    return res.status(200).json({ source: "local", via: "gist-feed", ageS: age, containers });
  } catch (e) {
    return res.status(200).json({ source: "offline", detail: `gist feed unreachable (${e.name})` });
  }
}
