# Revenue instrumentation proposal — privacy-light visitor analytics for the org's revenue surfaces

**Status: PROPOSAL ONLY.** Standing order is propose-first for revenue surfaces; nothing in this
document has been applied or deployed. Every diff below is ready-to-apply by the operator (or a
steer-gated agent) but has NOT been applied. 2026-07-23, L5 light build.

**The gap in one sentence:** the org probes its sites for uptime/latency/TTFB every 10 minutes
(`_probe_sites` in `apps/ava-factory/scripts/publish_live_status.py`, lines 44–71) but has **zero
visitor analytics anywhere** — it cannot say whether ANY insight, game, or page has earned a single
pageview.

**The first measurable number** (lands at rollout step 1, before any code beyond one script tag):
**"dumbmodel.com pageviews + unique visitors, last 24 h"** in the Vercel Web Analytics dashboard —
visible within minutes of the first visit after the enable + deploy.

---

## 1. Current state (evidence-cited; confirm-why per claim)

**Claim: site *probes* exist.**
`apps/ava-factory/scripts/publish_live_status.py`:
- lines 44–53: `SITES` list — `hub` (dumbmodel.com), `hoops`, `grid`, `pitch`, `equi`, `arcad`,
  `arxiv`, `bhenre`.
- lines 56–71: `_probe_sites()` — server-side HEAD request per site; emits
  `{"name", "url", "http", "ms", "up"}`.
- lines 120–132: `_site_history()` — rolling 24 h of probe rows per site.
- lines 168–201: `_site_perf()` — weekly TTFB/page-weight with >20 % regression flags.
- lines 252–264: `compose()` puts them under `hub.sites` / `hub.site_history` / `hub.site_perf`
  in the gist snapshot (`dottie_live_status/v2`, additive schema).

**Claim: visitor analytics do NOT exist.** Verified 2026-07-23:

```
$ grep -rniE "gtag|plausible|umami|goatcounter|analytics|beacon" \
    C:/Users/jcdav/vector-hub C:/Users/jcdav/dottie/apps/bluehenre/public \
    --include="*.html" --include="*.mjs" --include="*.js" --include="*.json" -l
(no matches)
$ grep -rniE "gtag|plausible|umami|goatcounter|analytics" \
    vector-hoops/index.html vector-pitch/index.html vector-equities/index.html
(no matches)
```

**Claim: a consented first-party beacon pattern already exists in the org — but is dormant.**
`C:/Users/jcdav/vector-hoops/api/telemetry.js` is a same-origin Vercel function: event-name
allowlist (`vh-start` … `vh-share`), payload truncation, `consent: true`, server-side
`SYNTH_API_KEY`, forwards to the Blue Hen exhaust pipeline
(`https://api-production-3dea.up.railway.app/v1/exhaust`). **Nothing calls it**:

```
$ grep -rn "api/telemetry|vh-start|sendBeacon" vector-hoops --include="*.js" --include="*.html" -l
C:/Users/jcdav/vector-hoops/api/telemetry.js        # the endpoint itself is the only match
```

**Claim: the sites feed already has exactly one consumer chain**, so a visits field has one
well-defined landing spot:

```
publish_live_status.py  →  gist (schema dottie_live_status/v2, hub.sites)
  →  apps/bluehenre/api/twin-status.mjs (hosted)  /  server.mjs /api/twin-status (local)
       (both attach the gist's `hub` block to the status object verbatim:
        twin-status.mjs line 50 `if (live.hub) status.hub = live.hub;`
        server.mjs line 159 `if (lf.hub) status.hub = lf.hub;`)
  →  public/js/twin.mjs  parseHub()  — sites mapping at lines 204–215
  →  public/js/org.mjs   renderSites() — lines 444–463 (SITES table on bhenre.com)
```

## 2. Revenue surface inventory

| Surface | Domain | Repo | Deploy | Feed key |
|---|---|---|---|---|
| Vector arcade hub | dumbmodel.com | `C:/Users/jcdav/vector-hub` (static, no build) | Vercel, scope `cams-projects-c5c4c5f6` | `hub` |
| Blue Hen RE org console | www.bhenre.com → `/org.html` | `C:/Users/jcdav/dottie/apps/bluehenre` | Vercel project `bluehenre-campus`; **every deploy must re-alias www.bhenre.com** (memory: bluehenre deploy) | `bhenre` |
| Vector Hoops | hoops.dumbmodel.com (hoops.jcamd.com 301s in) | `C:/Users/jcdav/vector-hoops` | Vercel | `hoops` |
| Vector Pitch | pitch.dumbmodel.com (pitch.jcamd.com 301s in) | `C:/Users/jcdav/vector-pitch` | Vercel | `pitch` |
| Vector Equities | equities.dumbmodel.com (equities.jcamd.com 301s in) | `C:/Users/jcdav/vector-equities` | Vercel | `equi` |
| Vector Gridiron | gridiron.dumbmodel.com | `C:/Users/jcdav/vector-gridiron` (head not inspected — verify anchors before applying) | Vercel | `grid` |
| Arcade / ArXivIQ | arcade.dumbmodel.com, arxiviq.com | later wave | Vercel | `arcad`, `arxiv` |

Note: the probe list keys hoops/pitch/equi to the jcamd.com hosts; probes follow the 301 (urllib
auto-follows), so the feed keys stay stable and the join in Phase C uses them as-is.

---

## 3. Phase A — platform analytics enable (Vercel Web Analytics)

Why first: zero infrastructure, cookieless by design (Vercel identifies visits with an anonymized,
daily-rotating server-side hash — no cookies, no persistent identifier, no PII stored), and it
produces the org's **first-ever pageview number** the same day. Free Hobby tier includes Web
Analytics with an event cap and short retention (confirm the current cap/retention numbers in the
dashboard at enable time — they change; do not quote stale limits in copy).

**Known limitation (drives Phases B/C):** the free tier has no supported read API — numbers live in
the dashboard only, so this phase cannot feed the twin's SITES table. That is acceptable: the goal
of Phase A is that a human can finally answer "did anyone visit?".

### A.1 Operator step (per Vercel project, dashboard, no code)

Vercel dashboard → project → **Analytics** tab → **Enable**. Projects, in rollout order:
vector-hub, bluehenre-campus, vector-pitch, vector-equities, vector-hoops, vector-gridiron.

### A.2 Ready-to-apply diffs — one `<script>` tag per static site

These sites are plain static HTML (no framework package), so the documented static-site include is
the bare script tag. It 404s harmlessly anywhere analytics isn't enabled (e.g. the local
`server.mjs` dev server on :8321 — a deferred 404 script is a no-op).

`C:/Users/jcdav/vector-hub/index.html`:

```diff
 <link rel="stylesheet" href="/assets/hub.css">
+<script defer src="/_vercel/insights/script.js"></script>
 </head>
```

`C:/Users/jcdav/dottie/apps/bluehenre/public/org.html` (bhenre apex console):

```diff
 <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=DM+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap" />
+<script defer src="/_vercel/insights/script.js"></script>
 <style>
```

`C:/Users/jcdav/dottie/apps/bluehenre/public/index.html` (mobile command console):

```diff
 <link rel="icon" href="./icon.svg" type="image/svg+xml" />
+<script defer src="/_vercel/insights/script.js"></script>
 <style>
```

`C:/Users/jcdav/vector-pitch/index.html`:

```diff
 <link rel="stylesheet" href="assets/responsive.css">
+<script defer src="/_vercel/insights/script.js"></script>
 </head>
```

`C:/Users/jcdav/vector-equities/index.html`:

```diff
 <title>Vector Equities — Company Embedding Explorer</title>
+<script defer src="/_vercel/insights/script.js"></script>
 <style>
```

vector-hoops and vector-gridiron have multiple HTML pages (`index`, `play`, `players`, `model`,
`leaderboard`, …) — add the identical tag to each page's `<head>`; anchors vary per page, verify
each before applying.

**Redirect note:** the hub's `/hoops`, `/pitch`, `/gridiron` shortcuts and the jcamd.com hosts are
server-side 301s — no HTML is served, no script runs, so redirects cannot double-count.

---

## 4. Phase B — first-party beacon (org-owned, feed-able counts)

Phase A numbers are dashboard-only. To ever put a visits number into the twin feed (Phase C), the
org needs a counter it can *read programmatically*. The org already owns a write path — the Blue
Hen exhaust pipeline that `vector-hoops/api/telemetry.js` was built for. Phase B reuses that exact
pattern (event-name-only, key server-side, never breaks a page) for pageviews.

### B.1 New file: `C:/Users/jcdav/dottie/apps/bluehenre/api/beacon.mjs`

Central endpoint on the bluehenre-campus project; all non-hoops sites beacon here cross-origin.
`navigator.sendBeacon` with a plain string sends `text/plain` — a CORS "simple request", delivered
without preflight (the caller never reads the response, so no ACAO header is needed for counting) —
hence the string-body parse branch.

```js
// First-party pageview beacon (revenue instrumentation, Phase B). Same
// doctrine as vector-hoops/api/telemetry.js: event-name-only, no cookies,
// no IP/UA storage; the exhaust key stays server-side. A beacon must never
// break a page: every failure path returns 2xx-or-4xx JSON and swallows.
const SITES = new Set(["hub", "bhenre", "hoops", "grid", "pitch", "equi", "arcad", "arxiv"]);
const EVENTS = new Set(["pv", "engaged"]);

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  const key = process.env.SYNTH_API_KEY;
  if (!key) return res.status(200).json({ ok: false, note: "beacon not configured" });
  let body = req.body;
  // sendBeacon(string) arrives as text/plain — Vercel leaves it a string
  if (typeof body === "string") { try { body = JSON.parse(body); } catch { body = null; } }
  const { site, event, path } = body || {};
  if (!SITES.has(site) || !EVENTS.has(event))
    return res.status(400).json({ error: "unknown site/event" });
  try {
    await fetch("https://api-production-3dea.up.railway.app/v1/exhaust", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        source: `site-${site}`, kind: "pageview", consent: true,
        payload: { event, path: String(path || "/").slice(0, 80) },
      }),
    });
  } catch { /* exhaust down — the visit still succeeded for the visitor */ }
  return res.status(200).json({ ok: true });
}
```

### B.2 Client snippet — per-site diffs (body end)

Engagement definition (fixed, so the number means one thing): **engaged = first pointerdown OR
15 s dwell, whichever first, at most once per pageview.** DNT is honored; a hostname guard keeps
localhost/preview/alias traffic out of the count.

`C:/Users/jcdav/vector-hub/index.html`:

```diff
 <script src="/assets/hub.js" defer></script>
+<script>
+/* first-party beacon — no cookies, no PII (tasks/artifacts/revenue_instrumentation_proposal.md) */
+(() => { if (navigator.doNotTrack === "1" || location.hostname !== "dumbmodel.com") return;
+  const send = (event) => navigator.sendBeacon("https://www.bhenre.com/api/beacon",
+    JSON.stringify({ site: "hub", event, path: location.pathname }));
+  send("pv");
+  let done = false;
+  const engaged = () => { if (!done) { done = true; send("engaged"); } };
+  addEventListener("pointerdown", engaged, { once: true, passive: true });
+  setTimeout(engaged, 15000);
+})();
+</script>
 </body>
```

`C:/Users/jcdav/dottie/apps/bluehenre/public/org.html` (same-origin — relative URL):

```diff
 <script type="module" src="./js/org.mjs"></script>
+<script>
+(() => { if (navigator.doNotTrack === "1" || !location.hostname.endsWith("bhenre.com")) return;
+  const send = (event) => navigator.sendBeacon("/api/beacon",
+    JSON.stringify({ site: "bhenre", event, path: location.pathname }));
+  send("pv");
+  let done = false;
+  const engaged = () => { if (!done) { done = true; send("engaged"); } };
+  addEventListener("pointerdown", engaged, { once: true, passive: true });
+  setTimeout(engaged, 15000);
+})();
+</script>
 </body>
```

`C:/Users/jcdav/vector-pitch/index.html` — same snippet with
`site: "pitch"`, guard `location.hostname !== "pitch.dumbmodel.com"`, anchored after
`<script src="assets/game.js" defer></script>`.

`C:/Users/jcdav/vector-equities/index.html` — same snippet with `site: "equi"`, guard
`location.hostname !== "equities.dumbmodel.com"`, anchored after the closing `</script>` of the
inline `load();` block.

**vector-hoops variant** — hoops already has a same-origin endpoint; extend it instead of
cross-origin. `C:/Users/jcdav/vector-hoops/api/telemetry.js`:

```diff
   const ALLOWED = new Set(["vh-start", "vh-guess", "vh-win", "vh-loss",
-    "vh-deadline-round", "vh-deadline-done", "vh-share"]);
+    "vh-deadline-round", "vh-deadline-done", "vh-share", "vh-pv", "vh-engaged"]);
```

and a page snippet using same-origin `fetch` with JSON content-type (that handler expects parsed
JSON bodies, unlike beacon.mjs):

```html
<script>
(() => { if (navigator.doNotTrack === "1" || location.hostname !== "hoops.dumbmodel.com") return;
  const send = (event) => fetch("/api/telemetry", { method: "POST", keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event, detail: location.pathname.slice(0, 40) }) }).catch(() => {});
  send("vh-pv");
  let done = false;
  const engaged = () => { if (!done) { done = true; send("vh-engaged"); } };
  addEventListener("pointerdown", engaged, { once: true, passive: true });
  setTimeout(engaged, 15000);
})();
</script>
```

(Hoops events land in exhaust as `source: "vector-hoops"`; the Phase C aggregator must map
`vector-hoops → hoops` when joining to the feed key.)

### B.3 Pre-flight checks before enabling Phase B (all currently UNVERIFIED)

1. Is `SYNTH_API_KEY` set in the bluehenre-campus (and vector-hoops) Vercel project env? If not,
   the endpoints honestly no-op (`ok:false, note:"…not configured"`) — safe, but counts nothing.
2. Does the exhaust API accept `kind: "pageview"`? Hoops uses `kind: "interaction"`. If the schema
   is closed, ship `kind: "interaction"` with `payload.event: "pv"` instead — one-line change.
3. Exhaust retention/quota on the Railway free tier — confirm pageview volume won't evict the
   interaction events hoops was built to send.

---

## 5. Phase C — visits in the sites feed (the twin renders real engagement)

### 5.1 Exact JSON shape change (gist schema `dottie_live_status/v2`, additive — v2 consumers unaffected)

A `hub.sites` row today (produced by `_probe_sites`, publish_live_status.py lines 68–70):

```json
{ "name": "hub", "url": "https://dumbmodel.com", "http": 200, "ms": 142, "up": true }
```

After Phase C — an **optional** `visits` object appears on rows the counter source measured, plus
one new carried block:

```json
{ "name": "hub", "url": "https://dumbmodel.com", "http": 200, "ms": 142, "up": true,
  "visits": { "d1": 42, "d7": 310, "engaged_d1": 16, "as_of": 1769212345, "via": "exhaust-api" } }
```

```json
"site_visits": {
  "as_of": 1769212345,
  "via": "exhaust-api",
  "sites": { "hub": { "d1": 42, "d7": 310, "engaged_d1": 16 },
             "bhenre": { "d1": 7, "d7": 31, "engaged_d1": 4 } }
}
```

Field meanings: `d1`/`d7` = pageview beacons in the trailing 1/7 days; `engaged_d1` = engaged
beacons trailing day; `as_of` = epoch-seconds of the poll; `via` = provenance stamp. **A site with
no measured count carries NO `visits` key** — absence, never zero, per provenance doctrine.

### 5.2 Publisher diff — `apps/ava-factory/scripts/publish_live_status.py`

> **OPERATOR-APPLIED ONLY.** The scheduled task "Dottie Status publisher" executes this file every
> 10 minutes; standing rule: agents never edit it in place. The task launches Python fresh each
> tick, so an operator edit is picked up on the next run — no restart, no task change needed.

```diff
 def _site_history(existing_hub, probes: list) -> dict:
     ...


+def _site_visits(existing_hub) -> dict:
+    """Per-site visitor counts from the org's counter API (Phase C). Absent
+    env -> {} so probe rows stay visit-less (the console renders an honest
+    em-dash, never zero). Polled hourly; carried between polls like site_perf."""
+    api = os.environ.get("DOTTIE_VISITS_API", "")
+    token = os.environ.get("DOTTIE_VISITS_TOKEN", "")
+    prev = existing_hub.get("site_visits", {}) if isinstance(existing_hub, dict) else {}
+    now = time.time()
+    if not api:
+        return {}
+    if isinstance(prev.get("as_of"), (int, float)) and now - prev["as_of"] < 3600:
+        return prev
+    try:
+        headers = {"Authorization": f"Bearer {token}"} if token else {}
+        req = urllib.request.Request(api, headers=headers)
+        with urllib.request.urlopen(req, timeout=10) as r:
+            data = json.loads(r.read().decode("utf-8"))
+        # expected: {"sites": {"hub": {"d1": 42, "d7": 310, "engaged_d1": 16}, ...}}
+        if isinstance(data.get("sites"), dict):
+            return {"as_of": round(now), "via": "exhaust-api", "sites": data["sites"]}
+    except Exception:  # noqa: BLE001 - publisher must never crash on a probe
+        pass  # honest absence beats a stale or invented number
+    return prev
```

and in `compose()`, directly after `hub["site_perf"] = _site_perf(existing.get("hub", {}))`
(line 264):

```diff
     hub["site_perf"] = _site_perf(existing.get("hub", {}))
+    visits = _site_visits(existing.get("hub", {}))
+    if visits:
+        hub["site_visits"] = visits
+        for row in hub["sites"]:
+            v = (visits.get("sites") or {}).get(row["name"])
+            if isinstance(v, dict) and isinstance(v.get("d1"), (int, float)):
+                row["visits"] = {**v, "as_of": visits["as_of"], "via": visits["via"]}
```

`DOTTIE_VISITS_API` points at whatever aggregate endpoint materializes from Phase B pre-flight
check 2/3: preferred = an aggregate-read endpoint on the org-owned exhaust service (add one if it
lacks it — it's the org's own Railway app); fallback if exhaust can't serve reads = GoatCounter
free tier (cookieless, no-PII, documented read API) with the beacon URL swapped in Phase B.
Until the env var is set, `_site_visits` returns `{}` and nothing changes anywhere — the diff is
safe to apply ahead of the counter source.

### 5.3 Consumer diff — `apps/bluehenre/public/js/twin.mjs`, `parseHub()` sites mapping (lines 204–215)

This is **the** parser that consumes the field (single consumer chain, section 1). Tests first —
see 5.4; apply the test diff, watch it FAIL, then apply this and watch it pass.

```diff
   const sites = Array.isArray(hub?.sites)
     ? hub.sites.map((s) => {
         const h = Array.isArray(histAll?.[s.name]) ? histAll[s.name] : [];
         const ups = h.filter((r) => r?.up === true).length;
+        const v = s.visits;
         return { name: String(s.name ?? "?"), up: s.up === true,
                  ms: Number.isFinite(s.ms) ? s.ms : null,
                  // link only when the probe URL is a real http(s) URL
                  url: /^https?:\/\//.test(s.url ?? "") ? String(s.url) : null,
                  up24: h.length ? Math.round((ups / h.length) * 100) : null,
-                 strip: h.slice(-36).map((r) => r?.up === true) };
+                 strip: h.slice(-36).map((r) => r?.up === true),
+                 // visits render ONLY when the feed carries a measured count;
+                 // unmeasured stays null and draws as "—", never 0 (doctrine)
+                 visits: v && Number.isFinite(v.d1)
+                   ? { d1: v.d1, d7: Number.isFinite(v.d7) ? v.d7 : null,
+                       engagedD1: Number.isFinite(v.engaged_d1) ? v.engaged_d1 : null,
+                       via: String(v.via ?? "?") }
+                   : null };
       })
     : null;
```

### 5.4 Contract-test diff (FIRST) — `apps/bluehenre/public/js/twin.contract.test.mjs`

Insert after the existing `siteHub` checks (line 178):

```diff
 check("site urls pass through only when real http(s)",
   siteHub.sites[0].url === "https://dumbmodel.com" &&
   parseHub({ hub: { sites: [{ name: "x", up: true, ms: 1, url: "javascript:alert(1)" }] } })
     .sites[0].url === null);
+const visitHub = parseHub({ hub: { sites: [
+  { name: "hub", url: "https://dumbmodel.com", up: true, ms: 1,
+    visits: { d1: 42, d7: 310, engaged_d1: 16, via: "exhaust-api" } },
+  { name: "pitch", url: "https://pitch.jcamd.com", up: true, ms: 1 },
+  { name: "equi", up: true, ms: 1, visits: { d1: "many" } },
+] } });
+check("site visits parse only when measured; absence stays null, never 0",
+  visitHub.sites[0].visits.d1 === 42 && visitHub.sites[0].visits.d7 === 310 &&
+  visitHub.sites[0].visits.engagedD1 === 16 && visitHub.sites[0].visits.via === "exhaust-api" &&
+  visitHub.sites[1].visits === null && visitHub.sites[2].visits === null);
```

Gate (README.md line 46): `cd C:\Users\jcdav\dottie\apps\bluehenre` then
`node public/js/twin.contract.test.mjs` — bare node, no deps.

### 5.5 Render diff — `apps/bluehenre/public/js/org.mjs`, `renderSites()` (lines 444–463)

```diff
-  el.append(table(["site", "status", "24h|r", "latency|r"],
+  el.append(table(["site", "status", "24h|r", "latency|r", "visits/d|r"],
     h.sites.map((s) => {
       let nameCell = s.name;
       if (s.url) {
         nameCell = document.createElement("a");
         nameCell.href = s.url;
         nameCell.target = "_blank";
         nameCell.rel = "noopener";
         nameCell.textContent = s.name;
       }
       return [nameCell, withLed(s.up, s.up ? " up" : " down"),
         Number.isFinite(s.up24) ? `${s.up24}%` : "—",
-        Number.isFinite(s.ms) ? `${s.ms}ms` : "—"];
+        Number.isFinite(s.ms) ? `${s.ms}ms` : "—",
+        s.visits ? String(s.visits.d1) : "—"];
     })));
-  el.append(P("24h = share of real probes up over the rolling day (10-min cadence)", "note"));
+  el.append(P("24h = share of real probes up over the rolling day (10-min cadence); " +
+    "visits/d = measured pageview beacons, trailing 24h — '—' until a counter source is wired", "note"));
```

---

## 6. Privacy notes (the whole point of "privacy-light")

- **No cookies, no localStorage, no fingerprinting** — neither Vercel Web Analytics (cookieless,
  anonymized daily-rotating hash, per its published model) nor the beacon (stateless POST).
- **No PII** — beacon payload is exactly `{site, event, path}`; event and site are allowlisted
  enums; path is truncated (80 chars central / 40 chars hoops). No IP, no user agent, no referrer,
  no user identifier is stored by org code; the exhaust key never reaches the browser.
- **DNT honored** — every snippet exits on `navigator.doNotTrack === "1"` before sending anything.
- **No consent banner needed under this design** (no cookies/persistent identifiers, aggregate
  counts only) — if the org later wants per-user anything, that's a different proposal with a
  consent flow.
- **Deliberately not collected:** sessions, funnels, referrers, geo, device. First get "did anyone
  come at all"; resist scope creep until that number is nonzero.
- Bot traffic: Vercel WA filters known bots; the raw beacon does not — label the feed column
  "pageview beacons", not "humans".

## 7. Rollout order (each step independently valuable; stop anywhere and keep the gains)

1. **vector-hub / dumbmodel.com — Phase A.** Enable Analytics on the project, apply the one-tag
   diff, `vercel deploy --prod --yes` from the repo. → **First measurable number ever.**
2. **bluehenre-campus / bhenre apex — Phase A.** Same, from `apps/bluehenre`. **Then re-alias:**
   `vercel alias set <new-deployment-url> www.bhenre.com` (domain still lives on the `frontend`
   project and does not auto-advance — memory: bluehenre deploy).
3. **vector-pitch, vector-equities, vector-hoops, vector-gridiron — Phase A.**
4. **Phase B**: pre-flight checks B.3; add `api/beacon.mjs` + client snippets (second deploy wave,
   same repos). Hoops uses its own extended `/api/telemetry`.
5. **Phase C**: verify/build the exhaust aggregate-read endpoint → operator applies the publisher
   diff + sets `DOTTIE_VISITS_API`/`_TOKEN` → apply the twin.mjs test-then-parser diffs and the
   org.mjs column → run the contract gate → deploy bluehenre-campus (+ re-alias). The SITES table
   on bhenre.com now shows real visits next to real uptime.

## 8. What the org can say afterwards

- After step 1 (day one): "dumbmodel.com had N pageviews and M visitors yesterday" — currently
  unanswerable at any price.
- After step 4: per-site pageview + engagement events accumulate in an org-owned store.
- After step 5: the public org console renders visits/day per site from the same provenance-honest
  feed as everything else — absence renders as "—", never as a fabricated zero.

## 9. Open questions / risks

| # | Question | Owner | Blocks |
|---|---|---|---|
| 1 | `SYNTH_API_KEY` present in bluehenre-campus + vector-hoops Vercel env? | operator | Phase B |
| 2 | Exhaust API: accepts `kind:"pageview"`? has/needs an aggregate read endpoint? retention? | operator (org-owned Railway app) | Phase B/C |
| 3 | Vercel Hobby analytics caps (events/mo, retention) at enable time | operator, dashboard | none (informational) |
| 4 | GoatCounter fallback acceptable if exhaust can't serve reads? (third-party script, but cookieless/no-PII, documented read API) | operator | Phase C fallback only |
| 5 | vector-gridiron + hoops multi-page anchors — verify each page head/body before applying | applier | steps 3–4 |
