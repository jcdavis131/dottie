# Closed-loop hill-climb: miner ingress + train→data demand

Date: 2026-07-11 (rev)  
Mode: `/auto-mode` + `/loop 2m` (monitor-only status)  
Loop sentinel: `AGENT_LOOP_TICK_closedloop`  
Loop PID: track live shell (currently 44420 / terminal 428347)  
Companion: `tasks/plan-syllabus.md`, `tasks/plan-hillclimb.md`

## Objective

Only **data miners (collectors)** gather outside data. Train → demand → collect/curate → pack → train.

```
Score = runway_health + (−Δlm) + demand_fulfillment − DATA_STARVED_frac − hang_penalty
```

## Live state (correct-assumptions)

- Preset **mini**, phase **P0 logic**, ckpt/50.
- Latest hard ckpt: **`/ckpt/step_400.pt`** (~105M tokens / 2.5B).
- Recurring failure mode: **post-checkpoint hang** (GPU mem held, CPU ~100%, no `step` for hours). Recover by resume from `latest`.
- Syllabus gaps / deferred upgrades: see `tasks/plan-syllabus.md`.

## Invariant

| Role | May fetch external data? | Emits |
|------|--------------------------|--------|
| Collector (miner) | YES (HF / synth) | RAW shards |
| Curator | NO | PACKED shards |
| Trainer | NO | heartbeats + **demand.json** |
| Janitor / server | NO | cleanup / status |

## Demand vocabulary (v1)

| Action | Meaning | Actuator |
|--------|---------|----------|
| `expand` | Need more tokens for phase P | Collector effort ↑ on P |
| `curate` | Quality gate failing / noisy supply | Curator priority; later stricter filters |
| `examples` | Model struggling (lm rising / route collapse) | Boost matching `task_type` sources |

Artifact: `/state/demand.json`.

## Tick contract (every **2m** — monitor only)

**Do not stop trainer or collectors from the loop.** Report status; start trainer only if it is already down and GPU is free (GPU-first recovery). Never kill host GPU jobs; never `compose stop` mid-climb from a routine tick.

1. Read live metrics + `demand.json` + last trainer `step` / lm / tok_s / ckpt + GPU util/VRAM.
2. If trainer not Up and 4080 free → `docker compose up -d trainer` (resume latest) — only start, do not stop.
3. Append one line to `tasks/hillclimb-log.md` (status).
4. Surface a short status report to the user.
5. Stop hard (human decision): irreversible destroy, secrets, base1b GO/NO-GO, budget blowup.

Hang / CUDA recover is **out of band** (explicit user ask or separate incident), not routine tick action.

## GPU policy (RTX 4080 Laptop — local)

**Prefer the 4080 for mini training whenever it is free.** Default is trainer **on**, not idle.

| Situation | Routine tick action |
|-----------|---------------------|
| No host `train_*.py` / other heavy CUDA; trainer stopped or exited | `docker compose up -d trainer` resume from `/ckpt/latest` |
| Host job (`train_mtnn`, etc.) holds the GPU | Report contention only — do **not** stop trainer from the 2m loop |
| Trainer Up but no `step` ≥15m + VRAM ≥8GB | Report hang suspect — hang recover is **out of band** (user ask) |
| CUDA unknown error / restart loop | Report; recover out of band once GPU exclusive |

Do not leave a free 4080 idle while mini has unfinished budget (start trainer if down + free).

## Priority order for levers

1. **GPU-first:** if 4080 free → ensure trainer running  
2. Hang recover / exclusive GPU (pause mini only while host CUDA contends)  
3. Disk D1 / collector pause  
4. Demand actuate (expand/curate/examples)  
5. Syllabus prep (only when gated): coding probe at P2 entry; Polyak design notes at P5  
6. Do **not** merge `origin/master` deepspeed/Prefect train path into this loop without explicit GO

## Board

### Closed-loop v1 (shipped)
- [x] `demand.py` + tests  
- [x] Trainer publishes demand  
- [x] Collectors reweight  
- [x] Dashboard demand panel  
- [x] Live verify while mini trains  

### Active (this loop)
- [ ] Mini climb on exclusive GPU from `step_400+` without hang (watchdog)  
- [ ] Hold P0 until P1 runway green  
- [ ] Keep demand ↔ collectors healthy  

### Syllabus backlog (see plan-syllabus)
- [ ] Coding probe at P2 entry  
- [ ] Polyak/EMA on P5 anneal ckpts  
- [ ] Loss-by-source demand  
- [ ] Mid-train mixture ablations  
- [ ] T9.5 branch FT (+ optional MOPD later)  
