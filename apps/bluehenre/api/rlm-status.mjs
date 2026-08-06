// Vercel twin of the Dottie RLM console feed. The hosted build cannot see the
// harness running on the training box; it serves the rlm_status.json snapshot
// the box itself published to the gist (`dottie-rlm status --publish` ->
// publisher task, same gist the live-status feed uses) — or says offline
// honestly. Nothing here invents numbers.
//
// Staleness: unlike fleet/twin telemetry (CPU%, trainer step), the RLM feed is
// a sessions table + an append-only refinement ledger — records, not gauges.
// A stale snapshot is therefore not dropped; it ships WITH its age under
// source:"stale" so the page renders it as history, not telemetry. Fresh
// (<= 30 min, same cap as the other feeds) ships as source:"local".
import { safeParseJson } from "../public/js/twin.mjs";

const RLM_GIST_URL = process.env.RLM_GIST_URL ||
  "https://gist.githubusercontent.com/jcdavis131/929c3c0b8ad38457f0a19f4f6605085c/raw/rlm_status.json";
const RLM_MAX_AGE_S = 1800; // freshness cap shared with fleet.mjs / twin-status.mjs

export default async function handler(req, res) {
  try {
    const r = await fetch(RLM_GIST_URL, { signal: AbortSignal.timeout(8_000) });
    // A gist raw URL 404s until the file exists — the harness simply has not
    // published yet. Say exactly that.
    if (r.status === 404)
      return res.status(200).json({ source: "offline", reason: "rlm_status not yet published" });
    if (!r.ok)
      return res.status(200).json({ source: "offline", reason: `gist feed HTTP ${r.status}` });
    const doc = safeParseJson(await r.text());
    if (!doc)
      return res.status(200).json({ source: "offline", reason: "published rlm_status is not parseable JSON" });
    if (!Array.isArray(doc.sessions))
      return res.status(200).json({ source: "offline", reason: "published rlm_status carries no sessions list" });
    const utc = Date.parse(doc.published_utc ?? "");
    const ageS = Number.isFinite(utc) ? (Date.now() - utc) / 1000 : null;
    const stale = ageS === null || ageS > RLM_MAX_AGE_S;
    const body = {
      source: stale ? "stale" : "local",
      via: "gist-feed",
      ageS,
      published_utc: doc.published_utc ?? null,
      // verbatim from the published snapshot — the twin never rewrites rows
      sessions: doc.sessions,
      refinements: Array.isArray(doc.refinements) ? doc.refinements : [],
    };
    if (stale)
      body.reason = ageS === null
        ? "published rlm_status has no parseable published_utc — history, not telemetry"
        : `published rlm_status is ${Math.round(ageS / 60)} min old — history, not telemetry`;
    return res.status(200).json(body);
  } catch (e) {
    return res.status(200).json({ source: "offline", reason: `gist feed unreachable (${e.name})` });
  }
}
