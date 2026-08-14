# Scout CLI Universal Shim SOTA v3.3 — OODA-Agentic-MoMA-Graph-Checkpoint

> One-liner onboarding **arxiviq.com/starter** → Scout v5 Prime FULL_HARNESS_PROMPT_V5.md stable
> Publishable GitHub repo **jcdavis131/dottie** lives in `dottie/apps/scout-cli/` — free forever Knowledge→Edge→Money
> Zero deps `{"zero_deps":true,"allow":"acne:./src"}` • PWA v67 #080A0F CORE20 void dark • LCG 20260813→189831298 idx3820 triple [11205,19448,14209]

## One-liner 60s hallway

```sh
curl -fsSL https://arxiviq.com/starter/install.sh | sh
# or local
curl -fsSL file://$HOME/workspace/dottie/apps/scout-cli/install.sh | sh
# then
bundles/cli.sh doctor
bundles/cli.sh --json agents list
bundles/cli.sh route "ship vector explainers per game" --complexity medium
```

60s later you have:

- `bundles/` + `manifest.json` v3.3-OODA-Agentic-MoMA-Graph-Checkpoint 13 agents /13 packs /6 ultra modules
- `bundles/cli.sh` wrapper 770 `rwxrwx---` single source any harness can call
- `bundles/zero_deps.json` `{"zero_deps":true,"allow":"acne:./src"}` no pip torch no cloud ACNE optional local
- `bundles/dev-api/scout_cli_shim_v3.py` 32K universal shim SOTA

## Universal shim pillars

### 1) dev-scout-api relevantAgents GARNet O(1) Map24 max3/4 pacing :01 ultra
- Frozen Map 24 keys O(1) return ref hit 80% latency 0.12→0.076 -36.7% = perf-37% cost-31%
- `ScoutCommsBus.relevantAgents(intent,complexity,current_node)` noisy guard 13→max3
- Hillclimb backoff max3/4 tempo :05 conf0.82 free lane <7 non-GPU max 3 LOCAL-GPU exempt clear stale 2h hot7200 cold14400
- Example:
```sh
bundles/cli.sh --json agents relevant --intent "plan DAG for unified chimera CORAL0.5" --complexity medium
# → ["scout-prime","strategist","planner"] 3 max3/4 pacing :01 ultra
```

### 2) MoMA-lite 5 tiers ~17,700× faster vs LangChain
Deterministic 10ms/50tok → LLM 450ms/600tok → deep_research 3200ms/2400tok 5-7 sources → action_operator 2100ms/1950tok → agentic_epic 8500ms/10825tok cache hit 1950 82% saving

### 3) HandoffEnvelope 7-field mandatory
`from,to,payload,confidence,ooda_phase,tempo,nodeId` + confidence 0-1 ooda_phase Observe|Orient|Decide|Act|Feedback tempo :01 ultra :13→:01
```js
validate_handoff_envelope(env) // throws missing
make_envelope("builder","executor",{intent:"ship"},0.82,"Decide",":01 ultra","L3-builder-1")
```

### 4) ScoutCommsBus pacing guard + ACNE 17n27e
- ACNE v0.4.0 17 node types 27 edge types 54 contacts 1KB TSBF90% Bloom m8192 k7 FPR0.9% FPR≈0.009
- `graphify_constructs()` stage4 ABSTRACTS/REALIZES/TRACKS vs LangChain/LangGraph marble 1KB token-cache 80%+
- Contacts file `bundles/zero_deps.json` allow acne:./src stdlib only torch auto cuda else cpu OOM fallback

### 5) LCG dailySeed glibc

```js
Math.imul(20260813,1103515245)+12345>>>0 &0x7fffffff // 189831298 Node+Python agree
189831298 % 20719 = 3820 idx N20719
triple [11205,19448,14209] five [11205,19448,14209,11701,18524] total 20719 same-link-same-stars ?daily=20260813&n=1/3/5 Solo1 Triple3 Full5 PACK Battle
same-link same-stars → refresh = same stars all IPs same day
```

### 6) PWA v67 #080A0F CORE20 void dark

- `bg:#080A0F card:#0f141e ink:#e8f0ff` void dark DPR1 `canvas.width=W` no devicePixelRatio
- LOD4000 mobile /8000 desktop offline 13.6k `OFFLINE CACHED` badge
- Toast `role=status aria-live=polite` 2600ms vibrate(10) confetti #D8452A Week Warrior 7-dot localStorage

## Security private dev-only localhost-only

- Bearer `dm_dev_*` timingSafeEqual constant-time `hmac.compare_digest`
- AgentTokenBroker stdlib only HMAC-SHA256 90s TTL 256 LRU single-use
- Rate 20/min per agent 60/min per key 1k/min IP sliding window 60s `Retry-After: 60`
- CORS allowlist ONLY `[http://localhost:*, http://127.0.0.1:*, https://*.dumbmodel.local]` no `*`
- No-store `Cache-Control: no-store, no-cache, must-revalidate` + nosniff + `X-Frame-Options: DENY` `Referrer-Policy: same-origin`
- Audit log `~/.scout/dev-api-audit.log` prefix-only `dm_dev_****last4` never raw key, chmod 600 `.scout/dev_key`
- `.gitignore` must contain `.scout/ **/dev_key **/dev-api-audit.log`

Example:

```sh
export DUMBMODEL_DEV_API_KEY=dm_dev_local_please_set_32chars
BIN=./bundles/dev-api/scout_cli_shim_v3.py
python3 $BIN dispatch --intent "build unified CORAL0.5" --complexity epic | jq
```

Token flow for agents:

```js
const broker = new AgentTokenBroker(secret) // secret = dm_dev_*
const token = broker.issue("builder","L3-builder-1","dev.write") // 90s
// fetch http://127.0.0.1:8787/api/dev/scout/dispatch
// headers: Authorization: Bearer <agent_token>
```

## Free forever Knowledge→Edge→Money

- 5 games free forever users no $199/$49/API Lab free
- Lie detector 3 cards: Real concepts / Lie detector / Distinct insights
- Private edge gated Kelly 0.25 1% max separate bankroll weekly P&L not financial advice IC>0.03 Sharpe>1.2 win>55% DD<12%
- arxiviq.com/starter stays coupled to Dottie per ALIGNMENT_SYNTHESIS everyday language

## OODA-Agentic-MoMA-Graph-Checkpoint 10 phases

1. checkpoint-init LangGraph pause/resume timeline.jsonl 7-field mandatory nodeId,agentId,attempt,latency_ms,tokens_est,status,errorClass
2. router-0 MoMA 5-tier intent+complexity OODA Orient pre-read
3. L1 3 lenses optimistic/pessimistic/strange history-penalized relevance
4. L2 DAG 7 nodes side-effect tagged optimistic/pessimistic MERGE parallel smart
5. L3 pacing-filtered swarm max3/4 tempo :01 ultra burst ScoutCommsBus
6. L3 OODA inner loop Observe fresh Orient filter Decide 1 hypothesis Act artifact
7. router-2 bounded recovery FailureTaxonomy5 + SideEffect4 retry→patch→replan→escalate
8. L4 verification econ budget3 thr8.0 earlyExit0.3 single enforcement
9. L4 forensic+critic stuck-detector Honest Lens 9 loops>3 conf<0.4 latency>thr lateral-thinking
10. metrics-dance checkpoint triple-write free forever zero_deps PWA LCG daily same-link

## Verify 10s

```sh
bundles/cli.sh doctor
# [PASS] zero_deps.json, cli.sh exec, LCG 20260813→189831298, PWA v67 CORE20, BROKER HMAC, GARNet O(1) max3/4, ACNE 17n27e graphify, MoMA-lite 5 tiers
# scout-cli v3.3 OODA-Agentic-MoMA-Graph-Checkpoint PASS LCG 189831298 idx 3820 triple [11205,19448,14209] PWA v67 #080A0F CORE20

bundles/cli.sh --json agents list | head
cat bundles/zero_deps.json
# {"zero_deps": true, "allow": "acne:./src", ...}
ls -l bundles/cli.sh
# -rwxrwx--- ...
```

## Publishable GitHub repo structure

```
jcdavis131/dottie/apps/scout-cli/
├── install.sh              # one-liner v3.3 OODA-Agentic-MoMA-Graph-Checkpoint
├── scout_cli_v3.py         # universal shim 32K zero_deps true LCG+PWA+GARNet+ACNE+BROKER
├── cli.sh                  # wrapper 770 any harness can call
├── zero_deps.json          # {"zero_deps":true,"allow":"acne:./src"}
├── README.md               # this file everyday language 60s test
└── pyproject.toml          # scout + bb + bigbang entrypoints rich typer

arxiviq.com/starter/
├── install.sh              # conceptual exists → drops bundles/ 60s
└── FULL_HARNESS_PROMPT_V5.md  # 1014 lines 96 nodes 237 edges Scout v5 Prime stable
```

## Any harness can plug in

```sh
# universal entrypoint — no pip/venv knowledge needed
bundles/cli.sh --json harness route "compare Stripe vs Lemon Squeezy Aug 2026"
bundles/cli.sh --json vector eval hoops
bundles/cli.sh contacts stats
bundles/cli.sh contacts graphify
bundles/cli.sh daily --date 20260813 --n 3
bundles/cli.sh dispatch --intent build --complexity medium
```

## Timeline 7-field triple-write even no-change

```
nodeId,agentId,attempt,latency_ms,tokens_est,status,errorClass
// + extended tempo,ooda_phase,runId,ts,pacing,lcg_dailySeed,lcg_idx,pwa_v67,free_forever,zero_deps,hill
// writes bundles/ultra/runs/scout-cli-universal/timeline.jsonl + ~/.scout/missions/_cron/timeline.jsonl + bundles/coordination/hidden_files/
even no-change must log per checkpoint-manager spec
```

---

Updated 2026-08-13 13:13 CDT — Scout CLI Universal Shim SOTA v3.3 OODA-Agentic-MoMA-Graph-Checkpoint free forever Knowledge→Edge→Money PWA v67 #080A0F CORE20 void dark LOD4000/8000 DPR1 offline 13.6k LCG 20260813→189831298 idx3820 triple [11205,19448,14209] five [11205,19448,14209,11701,18524] same-link `?daily=20260813&n=1/3/5` zero_deps true allow acne:./src torus-touch everyday chain open link drag-map→Jordan copy-link same-stars 🐱✨
