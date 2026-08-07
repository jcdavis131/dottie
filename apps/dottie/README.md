# dottie — SOTA Edition of Prime Agent

Dottie is the personally built, **SOTA edition of [PrimeIntellect's prime-agent](https://github.com/PrimeIntellect-ai/prime-agent)** — taking its two great ideas (Recursive Language Model + Continual Harness) and shipping them with a real training factory, Scout v5 Prime missions, and a single CLI that can extend itself.

> Solo personal project, no connection to employer, built with public/free-tier only, MIT. This is the production OS you actually live in; prime-agent is the research prototype that inspired it.

**If you know prime-agent:** Dottie is the same REPL-first, programmatic, daemon-backed, `rlm(...)` world — but every trace trains a small model (14M → 1.4B J-Space), every number carries provenance, every habit is refineable with rollback, and the forge lets the agent *write its own tools* mid-task.

See [`DOTTIE_PRIME_SOTA.md`](./DOTTIE_PRIME_SOTA.md) for the full prime → Dottie mapping and why this beats vanilla.

## How Dottie improves prime-agent (honest)

| Prime gives you | Dottie SOTA adds |
|---|---|
| RLM — prompt-as-variable, `rlm(...)` subagents in persistent IPython | Same, plus typed `MissionLog` at `workspace/.scout/missions/<id>/timeline.jsonl` — pause Monday, resume Thursday, receipts. Stuck Detector (2× same query / 2 fails / conf<0.4) → ONE lateral lens (SCAMPER/Six Hats/Inversion/etc) not spam. Verifier budget that ships (score 1-10, fix biggest gap once if <8, max 2 loops). |
| Continual Harness — durable supplemental prompts/memories/skills/subagents, `/refine` small evidence-backed updates, snapshots | Same guarantees at `workspace/.dottie/harness/<session>/`, plus People Resolver Write-Back (memory_search → ask once → MEMORY.md <50ms forever after), GARNet graph memory (G_workflow DAG + G_history patterns), confidence <0.4 = hint only, source tracked (`manual|calendar|memory_heuristic|enriched|extraction|ingest`), explicit rollback. Local by default — no push unless you ask. |
| Everything programmatic | Identical, plus Dottie Single-CLI doctrine: LLM gets exactly ONE tool `scout --json ...`. Capability `network/filesystem/secrets` default-deny in manifest. |
| Skills as importable packages | Same, plus `scout forge new|edit|test|install` — generate skill from OpenAPI/MCP in one line. Zero pip unless opted, token-cache optimizer (~80% savings). |
| Daemon sessions survive terminal close, reattachable, agent-to-agent messaging | Same, plus MissionLog, `HEARTBEAT.md` checklist, `dottie daemon status|doctor|shutdown`, `dottie comms inbox`, climb gates with measured promotion. |
| — | **Factory loop Dottie-only:** `tasks → traces.jsonl → RFT export + memory mint → eval gate (ava-open-harness) → GRPO step → better ckpt → serve`. Provenance every metric, honest 503 when backend missing, never faked. Proves closed-loop MLOps solo, on public/free-tier only. |
| — | **Local-first contacts Dottie-only:** ACNE fuzzy trigger phrases, same-name disambiguation, confidence scoring, writes to MEMORY.md. Says "Don't connect contacts" — no OAuth, no cloud. |

## Honest capability statement (read first)

- **Ollama is the working brain today.** Only backend that does useful work is `ollama` (default `qwen3:32b`) served locally.
- **Ava is the trainee.** `ava` backend decodes from real smoke-scale checkpoint (~14M nano). Zero task capability today, emits noise — honestly. Exists so flywheel has a trainee and serving path is built for day a capable ckpt exists.
- **Echo is plumbing.** Deterministic CI harness (`plumbing_only=True`).
- **Anti-fabrication everywhere.** Unreachable Ollama, missing ckpt, missing torch → Dottie refuses with true reason (`DottiePolicyUnavailable` / 503). Every metric computed from real inputs; `r_task` for free-form is `null` (no verifier), never invented. Verified tasks (`compute`, `extract`, `tool_chain`, `file_ops`, `constraint`) have deterministic verifier from same values rendered into prompt — automated no-leakage check enforces it.
- **RLM + Harness are real code now.** `dottie/rlm.py` (MissionLog, StuckDetector, VerifierWithBudget, `make_rlm_environment` → `rlm(...)`), `dottie/harness_continual.py` (versioned, snapshot, rollback, evidence-required refine, <0.4 = hint), `dottie/sessions.py` (registry, daemon status, inbox messaging), `dottie/goals.py` (persistent `/goal` that lives across turns).

## Architecture — RLM Inside Factory

```
                 ┌────────────────── Dottie SOTA (prime-agent + factory) ──────────────────┐
                 │                                                                         │
                 │  RLM v2 (prime's idea, Dottie's ship):                                  │
                 │    persistent IPython REPL — context = variables — rlm(...) spawns       │
                 │    child agents programmatically, MissionLog timeline.jsonl pause/resume │
                 │                                          │                              │
  POST /tasks ──▶│  FastAPI api.py ──▶ thread pool ──▶ DottieEngine (engine.py)            │
  rlm("...") ──▶│  + RLM Runner (rlm.py) ──▶ Harness v2 (harness_continual.py)           │
                 │       │ ContinualHarness refined via evidence, snapshots, rollback      │
                 │       │ Sessions daemon Registry + inbox messaging + goals + heartbeat  │
                 │       ├─ OllamaPolicy (qwen3:32b) ─ brain                              │
                 │       ├─ AvaPolicy (TorchModelPolicy+ckpt) ─ trainee                   │
                 │       └─ EchoPolicy (deterministic CI)                                 │
                 │                        │                                                │
                 │        ava.rl CodeAct ⇄ Sandbox (real Python exec, real observations)  │
                 │                        │                                                │
                 │            traces.jsonl → flywheel → ckpt → serve                       │
                 └─────────────────────────┬───────────────────────────────────────────────┘
                                          │ flywheel.py
        ┌─────────────────┬───────────────┼──────────────────┬──────────────────┐
        ▼                 ▼               ▼                  ▼                  │
  export_rft_dataset  mint_memories   evaluate          train_step              │
  (scout-cli ETL)     (ava-skills)    (ava-open-harness)(ava-factory GRPO)     │
        └─────────────────┴───────────────┴──────────────────┴──► better ava ckpt ─► AvaPolicy
```

## Quickstart — SOTA Edition

```bash
# 1. Ollama brain
ollama serve &
ollama pull qwen3:32b

# 2. Install Dottie SOTA
pip install -e apps/dottie   # provides dottie CLI
pip install -e apps/scout-cli # provides scout CLI

# 3. RLM session — prime's pattern, Dottie's log
python3 -c "from dottie.rlm import MissionLog, make_rlm_environment; ml=MissionLog('demo'); env=make_rlm_environment(ml); print(env['rlm']('research stripe vs lemonsqueezy aug 2026', model_tier='deep_research', require=['min 5 sources graded A/B/C','contradiction matrix']))"

# Or interactive REPL (persistent)
dottie repl                      # coming: wraps IPython with rlm(...) built-in
dottie repl --resume <mission-id>

# 4. Harness v2
python3 -c "
from dottie.harness_continual import ContinualHarness
h=ContinualHarness('my-session')
print(h.refine(evidence='found 3 pricing sources all agree stripe cheaper >$100k volume', updates={'prompt:stripe-scale':'when volume >100k emphasize stripe enterprise'}, provenance='extraction', confidence=0.9))
print(h.get_context_for_prompt())
"

# 5. Goals / Sessions
python3 -c "
from dottie.goals import GoalStore
from dottie.sessions import SessionRegistry, SessionRecord, send_message
import time
gs=GoalStore(); g=gs.set('close factory loop unattended'); print(g)
reg=SessionRegistry(); rec=SessionRecord(session_id='s1',created_ts=time.time(),last_seen_ts=time.time(),status='running',mission_id=g.goal_id); reg.register(rec); print(reg.list())
"

# 6. Factory tasks (honest refusal if no ollama)
curl -s http://localhost:8100/status | python3 -m json.tool
dottie run "How many words in this? Use word_count" --backend echo  # echo is plumbing
```

Docker path still works: `docker compose -f apps/dottie/docker-compose.dottie.yml up --build -d`

## The RLM Programming Model (prime-compatible, Dottie-extended)

```python
# From prime-agent docs pattern, now using Dottie
query = "find contradictions in stripe vs lemonsqueezy pricing"
# context as variables
sources = ["stripe.com/pricing", "lemonsqueezy docs", "forum threads"]
# programmatic subagent calling
results = rlm(
  "research stripe vs lemonsqueezy aug 2026",
  sources=sources,
  require=["min 5 sources graded A/B/C", "freshness aug 2026", "contradiction matrix"],
  model_tier="deep_research"  # 9K heavy tier
)
# Dottie: verifier that actually ships
from dottie.rlm import VerifierWithBudget
v = VerifierWithBudget(threshold=8.0, max_loops=2)
scored = v.score(results)
if v.should_fix(scored):
    results = v.fix_once(results, scored)

# Continual Harness refinement (never rewrites base prompt)
harness.refine(
  evidence="results contain 5 graded sources all showing same contradiction at >$100k",
  updates={"prompt:pricing-heuristic": "when volume >$100k emphasize stripe enterprise vs lmsq simplicity"},
  provenance="extraction",
  confidence=0.85
)
```

## Sessions as OS (prime → Dottie)

```
# prime-agent style
prime-agent agents
prime-agent attach <agent>
prime-agent status

# Dottie SOTA style (same capabilities, local registry)
dottie agent list
dottie agent attach <id>
dottie agent --resume <path|id>
dottie daemon status|doctor|shutdown
dottie goal set "ship arxiviq starter by friday"
dottie heartbeat enable --interval 15m
dottie schedule add "every monday 9am" --task "scan vector-hub"
dottie autonomous --turns 20 --tokens 9K --time 30m --gate "pytest passes"
dottie comms send --to agent:researcher-2 --msg "found contradiction"
dottie comms inbox
```

Agents discover each other via `workspace/.dottie/registry.json` (`DOTTIE_REGISTRY` env override).

## Flywheel Loop (Dottie-only, why SOTA needs it)

1. **Run tasks** (`POST /tasks` or `rlm(...)`): CodeAct loop drives model, actions execute in subprocess sandbox, FINAL captured.
2. **Traces → training data**: `POST /flywheel/export-rft` — real RFT ETL (redaction, episode segmentation, reward components, versioned schema).
3. **Traces → memory**: `POST /flywheel/mint` — real memory-mint over shard store, recallable.
4. **Eval gate**: `POST /flywheel/evaluate` — real ava-open-harness (mock or real ckpt), J-Space behavioral tests, 11-category rubric, anti-mock guard.
5. **Train step**: `POST /flywheel/train-step` — real GRPO update (`scripts/rl_smoke_update.py`), mechanical-health gate, manifest append.
6. **Better ckpt → AvaPolicy** — loop repeats. Today mechanics proven (capability_claim=none); capability comes from scale.

The climb: `python -m dottie climb --families mixed --n 20 --backend ollama --iterations 1` — measured, gated by per-family no-regression.

## Relation to prime-agent codebase

We re-implement prime-agent's core contracts (RLM, Continual Harness, daemon sessions, `/refine`, agent messaging) in pure Python under `dottie/` with no vendor lock:
- `dottie/rlm.py` ≈ prime's `rlm()` + MissionLog (adds Scout v5 Prime stuck/lens/verifier)
- `dottie/harness_continual.py` ≈ prime's harness (adds versioning, snapshots, provenance, confidence, People Write-Back hook)
- `dottie/sessions.py` ≈ prime's daemon layer (adds registry.json local, inbox.jsonl, heartbeat.md)
- `dottie/goals.py` ≈ prime's `/goal` (adds climb integration)

Prime is MIT; Dottie SOTA is MIT, same license, no pi dependency required (we thank pi authors implicitly as prime does). Dottie thanks Prime Intellect authors for RLM/Harness formulation and builds on it with honest factory loop.

## Tests

```bash
cd apps/dottie && python3 -m pytest tests -q -k "not test_engine"  # most pass without AVA_FACTORY_ROOT
# new modules smoke
python3 - << 'PY'
from dottie.rlm import MissionLog
from dottie.harness_continual import ContinualHarness
from dottie.sessions import SessionRegistry
from dottie.goals import GoalStore
print("SOTA modules importable ✓")
PY
```

See `DOTTIE_PRIME_SOTA.md` for full comparison, Scout v5 Prime fixes, lateral lenses, verification economics, and single-CLI doctrine.

