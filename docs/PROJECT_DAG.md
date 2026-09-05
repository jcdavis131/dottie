# The unified project DAG — what to work on, in what order

**Source of truth:** [`project_dag.json`](project_dag.json) (machine-readable). This page
is generated commentary; when the two disagree, the JSON is right and `scripts/dag_next.py
--mermaid` regenerates the picture below. **Updated 2026-09-05.**

## How to use it

```bash
python scripts/dag_next.py            # READY (in priority order), IN PROGRESS, BLOCKED, tally
python scripts/dag_next.py --repo vector-hub
python scripts/dag_next.py --check    # CI gate: unique ids, deps resolve, no cycles
python scripts/dag_next.py --mermaid  # regenerate the graph source
python -m factory start <node>        # ready -> in_progress, prints the repo and its validate gate
python -m factory done <node> --evidence "..."   # in_progress -> done; docs/FACTORY.md
```

Every Claude Code session in this repo opens with the frontier line (the SessionStart
hook reads this file), so the first question of a session is already answered: the
lowest-priority-number READY node in your repo. Work that, mark it `done` in the JSON,
open a PR. A node is READY when it is not done and every `depends_on` is done; READY and
BLOCKED are recomputed, never hand-set. `parked` nodes never enter the frontier.

## The shape of the graph

Five layers, read left to right. Product nodes sit on top of shared-infra nodes, and the
GPU-bound retrains sit behind one node (`gpu-box-dedicated`) because they all wait on the
same machine getting a schedule.

1. **Roots (this week).** `ci-green` and `jarvisd` are done. `merge-pr23` and
   `enable-analytics` are the two operator clicks that unblock the most. Analytics is
   first because every product has it off: there is no usage signal in the account, so
   "opportunistic" is still a guess until 30 days of data exist.
2. **Opportunistic products, no dependencies.** `jcamd-lab-links` (the only lead
   mechanism in the portfolio is that site's mail link; its Lab section misses the hub),
   `alamost-open-shop` (a finished product waiting on operator steps),
   `hub-nav-restore` (dumbmodel.com's served page links to none of its games).
3. **Shared infra the family builds on.** `vector-ci-green` (five red default branches),
   then `shared-map-canonical` (13 copies of the map engine in 3 lineages),
   `pwa-shell-template`, `unified-caches-restore` (CPU-only file copies), and
   `retire-coordination-boards` once the daemon is hosted.
4. **The 5-game hub.** `unified-5th-game` needs the caches and the hub nav;
   `hub-5-games` needs the 5th game and the canonical map. This is where
   `GOAL_AND_SHIP.md`'s "5-game hub at hoops-level parity" actually lands.
5. **GPU-bound research.** `hoops-v6-retrain`, `gridiron-real-train`,
   `unified-g2-retrain`, and the parked `ava-factory`, all behind `gpu-box-dedicated`,
   which itself follows `host-jarvis` because the same box hosts the daemon.

Cross-cutting ops that fix real confusion: `repoint-arxiviq` (arxiviq.com is served from
the archived bluehen repo today), `bluehen-vercel-cleanup` (nine Vercel projects still
build from bluehen, four with live domains), `slasso-domain` (slasso.com is served by a
project linked to a repo called yubipet).

## What deliberately is not in the graph

vector-arcade, vector-fusion-demo, component-books, the two Cursor skill packs, the
profile README. None of them consume shared infra or have users to serve, and adding
nodes for "leave alone" is how a graph turns back into a list.

## The picture

```mermaid
flowchart LR
  ci-green["ci-green<br/>dottie CI green on main"]
  jarvisd["jarvisd<br/>Jarvis daemon: MCP + JSON API + SQLite + auth + free Ollama brain"]
  factory["factory<br/>The factory: software, MLOps and data lines over this DAG (python -m factory; docs/FACTORY.md)"]
  enable-analytics["enable-analytics<br/>Turn on Vercel Web Analytics for the 14 custom-domain projects"]
  merge-pr23["merge-pr23<br/>Merge dottie PR #23 (harness build) into main"]
  archive-mirrors["archive-mirrors<br/>Merge the six deprecation PRs and click Archive (scout-cli, ava-skills, ava-open-harness, personal-graphify, bluehen, agent-lasso)"]
  jcamd-lab-links["jcamd-lab-links<br/>jcamd.com: Lab links to dumbmodel.com hub + unified, footer off hoops.jcamd.com, refresh /graphify export, add a smoke test"]
  alamost-open-shop["alamost-open-shop<br/>alamost.com: run the shop-opening order of operations (PR #6), set ANTHROPIC_API_KEY for photo listing"]
  hub-nav-restore["hub-nav-restore<br/>dumbmodel.com: restore real game navigation and real vectors.json on the served index (it currently links no games and self-describes as synthetic)"]
  vector-ci-green["vector-ci-green<br/>Get hoops, gridiron, pitch, unified and equities default-branch CI green; add lint+tests to hoops (it has none)"]
  host-jarvis["host-jarvis<br/>Run jarvisd on the home box behind a Cloudflare Tunnel (free), nightly SQLite backup, smoke jarvis.ask on Ollama"]
  connect-clients["connect-clients<br/>Point Claude Code, Cursor and OpenCode at the hosted daemon; two-client remember/recall test passes"]
  vercel-arxiviq-rootdir["vercel-arxiviq-rootdir<br/>Set the dottie arxiviq Vercel project's Root Directory to apps/arxiviq; delete or configure the orphan dottie Vercel project"]
  repoint-arxiviq["repoint-arxiviq<br/>Move arxiviq.com from bluehen's arxiv-exam-app project to the dottie arxiviq project; retire the standalone arxiviq repo to data scripts"]
  arxiviq-real-data["arxiviq-real-data<br/>arxiviq: replace the synthetic papers.json fallback with fetch_topics.py output on a schedule"]
  bluehen-vercel-cleanup["bluehen-vercel-cleanup<br/>Re-point or drop arcade.dumbmodel.com, training.jcamd.com, signals/data.bhenre.com; then delete the nine bluehen-linked Vercel projects"]
  slasso-domain["slasso-domain<br/>slasso.com is served by a Vercel project linked to the yubipet repo; point it at apps/dottie-harness-api or drop the domain"]
  retire-coordination-boards["retire-coordination-boards<br/>Replace the eight duplicated COORDINATION.md / CLAIM_BOARD_PROMPT.md / bundles/ copies with jarvis.claim; delete the file boards"]
  shared-map-canonical["shared-map-canonical<br/>One canonical shared-map.js in vector-hub/packages/vector-tokens, published to the five game repos (today: 13 copies, 3 lineages)"]
  pwa-shell-template["pwa-shell-template<br/>Template the PWA shell (sw.js, manifest.json, offline.html, 404.html, vercel.json) once and stamp it into the six sites"]
  unified-caches-restore["unified-caches-restore<br/>vector-unified: restore the input caches (factory data restore unified-pitch-cache / unified-gridiron-matrix work from sibling checkouts; unified_matrix.npz is gitignored and exists only on the box); CPU only"]
  unified-5th-game["unified-5th-game<br/>unified.dumbmodel.com: daily chimera at hoops-level parity (the 5th game), promoted to a real subdomain"]
  hub-5-games["hub-5-games<br/>dumbmodel.com as the 5-game hub (GOAL_AND_SHIP.md): one nav, one design system, hub chimera over the 20,719-row joint embedding"]
  equities-forward-ic["equities-forward-ic<br/>vector-equities: reconcile forward-IC eval with README claims (TODO #8)"]
  equities-peer-drift["equities-peer-drift<br/>vector-equities: peer-drift model zoo cross-validation (CPU pipeline)"]
  gridiron-nflverse-fetch["gridiron-nflverse-fetch<br/>vector-gridiron: pipeline/fetch_nflverse.py exists (566 lines); run it for real seasons and record which train_matrix.npz is real vs --synthetic (factory data refresh gridiron-train-matrix)"]
  gpu-box-dedicated["gpu-box-dedicated<br/>Alienware box: install the nightly training window (scripts/train_window.ps1 -Install), disk headroom; factory/train_queue.json is the one queue; Ollama and jarvisd share the box"]
  hoops-v6-retrain["hoops-v6-retrain<br/>vector-hoops: v6 transformer 150-epoch hill-climb (composite 0.79 to 0.85), promote only if the gate passes"]
  gridiron-real-train["gridiron-real-train<br/>vector-gridiron: retrain the 32-d MTNN on real nflverse data"]
  unified-g2-retrain["unified-g2-retrain<br/>vector-unified: Stage-2 sport-blindness retrain (G2 0.685 to 0.64), 60 epochs on the box"]
  vector-realty-pr4["vector-realty-pr4<br/>Review vector-realty PR #4 (data-integrity fix); merge or close, which unblocks vector-unified PR #5"]
  harness-api-proxy["harness-api-proxy<br/>slasso harness API proxies jarvisd (goals, inbox, claims, timeline) so the dashboard shows the live daemon"]
  who-e-branding["who-e-branding<br/>Untangle WHO-E branding leaks in vector-hub and dottie-harness-api; decide who-e.com's home"]
  flywheel-gate["flywheel-gate<br/>Router promotion gate passes once on real daemon traces (Phase 4: let it learn)"]
  ava-factory["ava-factory<br/>Ava factory mini/base1b training track"]
  ci-green --> jarvisd
  ci-green --> factory
  jarvisd --> merge-pr23
  merge-pr23 --> host-jarvis
  host-jarvis --> connect-clients
  merge-pr23 --> vercel-arxiviq-rootdir
  vercel-arxiviq-rootdir --> repoint-arxiviq
  repoint-arxiviq --> arxiviq-real-data
  repoint-arxiviq --> bluehen-vercel-cleanup
  archive-mirrors --> bluehen-vercel-cleanup
  connect-clients --> retire-coordination-boards
  vector-ci-green --> shared-map-canonical
  shared-map-canonical --> pwa-shell-template
  unified-caches-restore --> unified-5th-game
  hub-nav-restore --> unified-5th-game
  unified-5th-game --> hub-5-games
  shared-map-canonical --> hub-5-games
  equities-forward-ic --> equities-peer-drift
  vector-ci-green --> equities-peer-drift
  vector-ci-green --> gridiron-nflverse-fetch
  factory --> gpu-box-dedicated
  host-jarvis --> gpu-box-dedicated
  gpu-box-dedicated --> hoops-v6-retrain
  vector-ci-green --> hoops-v6-retrain
  gridiron-nflverse-fetch --> gridiron-real-train
  gpu-box-dedicated --> gridiron-real-train
  unified-5th-game --> unified-g2-retrain
  gpu-box-dedicated --> unified-g2-retrain
  connect-clients --> harness-api-proxy
  slasso-domain --> harness-api-proxy
  retire-coordination-boards --> flywheel-gate
  harness-api-proxy --> flywheel-gate
  gpu-box-dedicated --> ava-factory
  classDef done fill:#dcefe2,stroke:#2c7a4b,color:#1a2330;
  classDef ready fill:#d9ecea,stroke:#0e6b6b,color:#1a2330;
  classDef in_progress fill:#f6e8cf,stroke:#a6701c,color:#1a2330;
  classDef blocked fill:#e9eef1,stroke:#75808c,color:#1a2330;
  classDef parked fill:#f5dcdc,stroke:#b23b3b,color:#1a2330;
  class ci-green,jarvisd,factory done;
  class alamost-open-shop,enable-analytics,jcamd-lab-links,merge-pr23,hub-nav-restore,unified-caches-restore,vector-ci-green,equities-forward-ic,slasso-domain,vector-realty-pr4,who-e-branding ready;
  class archive-mirrors in_progress;
  class connect-clients,host-jarvis,vercel-arxiviq-rootdir,hub-5-games,repoint-arxiviq,retire-coordination-boards,shared-map-canonical,unified-5th-game,arxiviq-real-data,bluehen-vercel-cleanup,pwa-shell-template,equities-peer-drift,gpu-box-dedicated,gridiron-nflverse-fetch,gridiron-real-train,hoops-v6-retrain,harness-api-proxy,unified-g2-retrain,flywheel-gate blocked;
  class ava-factory parked;
```
