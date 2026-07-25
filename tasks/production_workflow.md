# The Dottie site — workflow to production (2026-07-25)

Spec: `apps/bluehenre/SPEC.md`. Phased feature plan: `tasks/dottie_site_plan.md`.
Live board: `tasks/todo.md`. This file is the **release workflow**, not a feature
list — how a change gets from the working tree to www.bhenre.com without anyone
having to remember anything.

## The thesis

**The site is deployed. It is not productionised.** Those are different claims and
the board currently conflates them.

Deployment is a fact that happened once: `bluehenre-campus-peejfd91y-…` is aliased
to www.bhenre.com and answers (`/org.html` 200 in 0.14 s, `/hub_registry.json` 200,
`/` → 307 as configured — measured 2026-07-25). Production is a *property*: it keeps
working, it breaks loudly, and someone who did not build it can ship a change
safely.

Measured gaps between the two:

| | today | needed |
|---|---|---|
| pre-deploy | 3 commands a human must remember (README:64) | one command, exit-coded |
| post-deploy | **nothing** | smoke before the alias moves |
| alias-guard pin | hand-edited text file | written by the gate, only on success |
| "does it render" | *"pixels unconfirmed (Chrome extension down)"* — repeated 4× on the board | asserted from the served bytes |
| regression | CI covers parsers | CI covers parsers **and** the deployed contract |

The board's own words are the evidence: Phase 1 shipped with *"live visual render
not yet confirmed"*, and Phase 2 shipped with *"visual render unconfirmed"*. Two
features are in production that nobody has verified render. That is not a criticism
of the work — it is exactly what happens when verification is manual and the tool
for it is flaky.

## The one idea that makes this app's smoke different

A generic smoke test asserts liveness: 200s, latency, no 5xx. **That would be wrong
here**, and would have to be disabled within a week.

This app's core promise is provenance-honesty: numbers render only from
`source:"local"`, unreachable blocks render as offline lines, `[dottie]`/`[offline]`
is stamped, withheld beats fabricated. So on bhenre.com the assistant answering
`{source:"offline", reply:"engine unreachable — reply withheld"}` is **correct
production behaviour**, not an outage. A liveness smoke fails on it; a naive fix
would be to stop smoking the assistant at all.

So the gate asserts the **honesty contract**, not liveness:

1. the served `hub_registry.json` is byte-identical to the committed one — prod and
   repo cannot silently diverge (a stale prod registry renders data that does not
   match its source, which is the exact violation `--check` exists to prevent
   locally);
2. every assistant reply carries a source stamp from the closed set
   `{dottie, offline}` — an unstamped or absent stamp is a failure even when the
   HTTP call succeeded;
3. the retracted **275.95** ppl appears **only** adjacent to a retraction marker,
   never as a live metric. This is the anti-fabrication differentiator made
   executable against production bytes;
4. offline is asserted as *honest*, not as *broken* — an offline reply must still
   be well-formed and must not contain a fabricated number.

Liveness is still checked, but it is the cheap half.

## The pipeline — five gates, each exit-coded

```
G0 SOURCE   tree clean · CI green on HEAD
G1 PRE      contract suite · exporter test · registry freshness · JS syntax
G2 BUILD    vercel deploy --prod  →  capture the DEPLOYMENT url
G3 SMOKE    assert the honesty contract against THE DEPLOYMENT URL
G4 PROMOTE  alias → www.bhenre.com · re-smoke the alias · write the pin
G5 WATCH    periodic liveness + freshness; stale is "history, not telemetry"
```

**G3 before G4 is the load-bearing inversion.** Today the order is deploy → alias →
hope, so a broken build becomes www.bhenre.com and the operator finds out by
looking. Smoking the deployment URL *before* the alias moves means a bad release
never reaches the domain, and rollback is "don't move the alias" rather than "deploy
again under pressure".

**The pin is an output, not an input.** `data/last_good_deployment.txt` is currently
hand-edited, so it records what someone *intended*. Written by G4 only after G3+G4
pass, it records what was actually verified — which is what an alias-guard is for.

## What makes it *dynamic* rather than a checklist

Each gate branches on measured state instead of asserting a fixed expectation:

- **registry STALE → rebuild, re-check, and report the diff** rather than failing a
  human who then runs the rebuild by hand. Fail only if it is still stale after the
  rebuild (that means the exporter is broken, which is a real failure).
- **engine unreachable → assert the honest-offline contract** and pass; engine
  reachable → additionally assert the `[dottie]` stamp and a non-empty reply. The
  gate adapts to which production state it is in, because both are legitimate.
- **telemetry stale → warn, do not fail.** Stale is a documented, honest state
  ("history, not telemetry"). Failing on it would train everyone to ignore the gate
  — the same failure mode that made `lint.yml` a permanently-red required check.
- **new artifact classes appear → the count assertion reads the committed registry**
  rather than a hardcoded 14, so adding a dataset does not break the gate.

The rule behind all four: **a gate that fires on a legitimate state gets disabled,
and a disabled gate protects nothing.** Only assert things whose violation is
genuinely a defect.

## Sequencing

| stage | what | blocked on |
|---|---|---|
| **S1** | `release_gate.mjs --pre` — the README's three commands as one exit-coded command | nothing — **doing now** |
| **S2** | `release_gate.mjs --post <url>` — the honesty-contract smoke | nothing — **doing now** |
| **S3** | wire `--pre` into the existing `bluehenre-checks` CI job | S1 |
| **S4** | G4 writes the pin; document the deploy runbook as gate-driven | S2, operator deploys |
| **S5** | Phase 3 MONITOR (runtrack readout) — the last unbuilt pillar | nothing |
| **S6** | assistant brain in prod — see the fork below | **operator decision** |
| **S7** | G5 watch loop (scheduled liveness + freshness probe) | S2 |

## The one real fork — operator's call, not mine

**On bhenre.com the assistant has no brain, and cannot get one by shipping code.**
`api/assistant-chat.mjs` returns `source:"offline"` unless `DOTTIE_CHAT_URL` is set,
and it is not set in prod because the box is deliberately unexposed. So the flagship
pillar is permanently honest-but-inert in production. The deterministic
`nextActions` digest already ships real guidance without an engine — that was the
right call and it works — but *conversation* does not exist for a visitor.

Three ways out, and they are genuinely different products:

1. **Tunnel to the box.** Cheapest to reach `[dottie]`, but puts a 16 GB laptop with
   a live trainer, intermittent Docker and documented memory pressure on the
   critical path of a public site. Rejected on those measurements unless the
   operator wants it.
2. **Hosted model API as a second tier**, grounded in the published telemetry gist:
   `[dottie]` when the box is reachable → `[claude]` when it is not → `[offline]`
   when neither. Always-on, box stays unexposed, honesty preserved by extending the
   stamp set rather than weakening it. Costs a key and a per-call spend, and it
   means the assistant is not the org's own model.
3. **Serve the org's own trained checkpoint** behind the site. Most faithful to
   "own the application layer" and to the mission, and the largest build.

I have not chosen. Option 2 is the fastest to a working production assistant and
option 3 is the one that matches the stated mission; they are not exclusive — 2 can
be the fallback tier for 3. Whichever is chosen, it ships **dormant and honest**
until the operator supplies the credential, exactly as the HF mirror does
("awaiting token rotation") — entering credentials is explicitly the operator's own
action per `SPEC.md`.

## Definition of done for "production"

1. One command gates a release; nobody remembers three.
2. No build reaches www.bhenre.com without passing the honesty smoke first.
3. The alias-guard pin records what was verified, not what was intended.
4. The anti-fabrication promise is asserted against production bytes on every
   release, not audited by hand once.
5. A visitor who is not the operator can use the assistant, or is told honestly why
   they cannot — currently the second, by design, pending the fork above.
