# Ava — Continuous Gather → Clean → Train → Serve

Collection, curation, and training run **concurrently** as five Docker services coordinated by a
SQLite manifest. Training on the local RTX 4080; everything else in containers.

Live tracker: [`TODOS.md`](TODOS.md) · Agent protocol: [`ORCHESTRATION.md`](ORCHESTRATION.md) · Contracts: [`specs/`](specs/)

*(Supersedes the previous plan, which assumed no GPU and a firewalled HuggingFace. Both premises are
false on this machine.)*

---

## Why this exists

The v6.4 repo was a blueprint, not a system. The audit found, and this project fixed or is fixing:

| Blueprint claim | Reality |
|---|---|
| "1B model, trains with `torchrun`" | Training loop was 5 steps of `loss=torch.tensor(1.0)`; checkpoints were **text files** |
| Transformer | **No causal mask** — attention saw the future. Not a language model. |
| Global Workspace | Mean-pooled the **whole sequence** and broadcast it to every position — leaked the future even after the mask was added |
| "AutoInit std=0.02" | Dead code. nano started at cross-entropy **196** where ln(8192)=9.01 |
| `verbalizable_mass` | The literal constant **0.06** (a `hasattr` guard that was always False) |
| 5 canonical eval tests | Every score **hardcoded**; the "intervention engine" edited a `torch.randn` matrix indexed by `sha256(concept) % vocab` |
| "ava-tokenizer" | Does not exist anywhere |
| `server.py` | `NameError` on import (`Optional` never imported) |

## Measured environment (not assumed)

| Fact | Value | Consequence |
|---|---|---|
| GPU | RTX 4080 Laptop, 12.2GB | ~11.6GB usable |
| GPU in Docker | `--gpus all` **works** | train in a container |
| HF from Windows host | **connection reset** | unusable |
| HF from Docker | **reliable** | *Docker is the network fix, not just packaging* |
| HF streaming | needs `datasets==2.20.0` + `pyarrow==16.1.0` | unpinned → `NoneType.ArrowInvalid` |
| Disk | 28.5GB free, single drive | **the binding constraint** |
| RAM / CPU | 15.7GB (Docker 8.1GB) / 32 cores | curation is CPU-parallel |

> ⚠️ **Never run `docker system prune --volumes`.** The 29 volumes are other projects' live data
> (`p0_postgres_data`, `p0_neo4j_data`, `p1_minio_data`, `p2_pgdata`, `infra_synthaembed_pg`, …).
> `docker builder prune -a` is safe and reclaimed **25GB**.

## Architecture

```
 collector ×4 (CPU)        curator ×6 (CPU)          trainer ×1 (GPU)      server (GPU)
 ─────────────────         ─────────────────         ─────────────────     ────────────
 HF streaming    ─┐                                                        hot-reloads
 synthetic gens  ─┼─▶ raw/*.jsonl.zst ─▶ clean·dedup·decon·split· ─▶ packed/{phase}/ ─▶ ckpt/latest
 (resumable       │      [RAW]           tokenize·pack              {split}/*.bin         ▲
  cursors)        │                          [PACKED]                    │                │
                  └──────── backpressure ◀── janitor: watermarks, ───────┴────────────────┘
                                             delete CONSUMED, rotate ckpts
```

**Shard lifecycle** (`ava/pipeline/manifest.py`, enforced):
`RAW → CLAIMED_CURATE → PACKED → CLAIMED_TRAIN → CONSUMED → DELETED` (+`FAILED`), leases requeued on
worker death. Claims are `SELECT`+`UPDATE` inside one `BEGIN IMMEDIATE` — proven by a negative
control: weakening it to `BEGIN DEFERRED` makes the 12-claimer test fail immediately.

**Flow control** (`ava/pipeline/flow.py`) keeps the system *training-bound*:
- collector pauses on `free_disk < 12GB` **or** `raw > 4GB` **or** `packed_runway > 3B tokens`
- trainer emits `DATA_STARVED` (never crashes) and collectors re-prioritize that phase
- collector prefetches `phase_current` **and** `phase_next` so transitions don't stall the GPU
- **delete-after-consume** is safe because training is single-pass; `val`/`test` shards are
  structurally protected (the trainer cannot claim them; the janitor refuses to delete them)

## Data

Hybrid. Real corpora for breadth; synthetic for the logic-first phases and for the `task_type` /
`concept` tags the J-Space routing and Critic losses need (nothing on the Hub carries them).

| Phase | Real (streamed) | Synthetic |
|---|---|---|
| P0 logic | — | truth tables, natural-deduction proofs valid *by construction*, syllogisms, FOL |
| P1 math | open-web-math | staged arithmetic→probability, answers computed not templated |
| P2 foundation | fineweb-edu (`score≥2`), github-code, cosmopedia | canonical fact corpus |
| P3 reasoning | proof-pile-2, open-web-math | CoT traces, temporal workflow logs |
| P4 long | fineweb-edu long docs | needle-in-haystack |
| P5 anneal | fineweb-edu (`score≥4.5`), proof-pile-2 | safety dialogues + benign twins |

**Splits:** doc-level, hash-stable — `bucket(sha1(doc_id))` → train 98 / val 1 / test 1. Reruns and
reordering reproduce identical assignments.

**Decontamination** (13-gram) is the gate on every published number. The subtlety: `encyclopedia.py`
deliberately teaches "a spider has eight legs" — the model *must* learn the fact. We decontaminate
against the eval **prompt strings**, not the underlying facts. Too lax poisons the evals; too strict
lobotomizes the model.

## Scale ladder

| Rung | Params | Tokens | Wall-clock | Purpose |
|---|---|---|---|---|
| nano | **13.8M** ✅ | ~50M | ~10 min | proves the loop; not a capability claim |
| mini | **171.3M** ✅ | ~2.5B | 3–5 days | the real validation; GO/NO-GO for base1b |
| base1b | **1409M** ⚠️ | M1 2B → M2 10B → M3 30B+ | ~100M tok/day | the target |

Param counts are **measured**, and the specs undercounted: each of the 4 workspaces carries
`10·d_model²` (two MHA + gate + broadcast proj), plus 4 cross-attentions at `4·d_model²`.
At d=2048 the J-Space alone is ~235M. base1b lands at 1409M, not the spec'd 1.17B — VRAM is tight
(8.4GB before activations); trim decision at the Stage 9 gate.

Chinchilla-optimal for base1b (~20B tokens) is ~6 months on this GPU. Hence milestones with WSD
stable checkpoints at every phase boundary, making it **stop-anytime** and fork-anytime (code/math/chat
branches per `BRANCH_CONFIGS`).

## Verification

```bash
docker builder prune -a          # safe. NEVER: docker system prune --volumes
make test                        # manifest concurrency, causality, dedup, decon, splits, resume
docker compose up -d             # collector RAW↑ → curator PACKED↑ → trainer step↑ → janitor DELETED↑
make ps                          # shard counts by state
bash scripts/smoke_live.sh       # health, generate, inspect, intervene-403, hot-reload
pytest tests/test_no_mock.py     # no hardcoded eval literals may survive
```

**Steady state = success:** GPU utilization stays high, `DATA_STARVED` never fires for more than a
few seconds at phase transitions, disk stays under the high watermark indefinitely, val PPL falls,
and `curl localhost:8000/jspace/inspect` returns input-dependent workspace data from the checkpoint
being trained *right now*.
