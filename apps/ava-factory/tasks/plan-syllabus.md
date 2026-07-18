# LLM pretrain syllabus — gaps vs frontier + Ava levers

Date: 2026-07-11  
Sources: live mini climb, `configs/mini.yaml` / `sources.yaml`, FineWeb + Llama-3 anneal notes,
canvas `llm-pretrain-syllabus`, other-agent docs on `origin/master`
(`docs/CONTINUOUS_PIPELINES.md`, `docs/DISTILLATION_INTEGRATION.md`, `CURRICULUM_LOOP_PLAN.md`,
`inner_monologue_research.md`).

## Ava syllabus (already shipped)

| Phase | Role | Mix highlights |
|-------|------|----------------|
| P0 logic | Cold start | synth logic 100% |
| P1 math | Symbolic | math + logic |
| P2 foundation | Web + code bulk | FineWeb-Edu, GitHub, Cosmopedia, synth code |
| P3 reasoning | Longer CoT | proof-pile, OWM, temporal |
| P4 long | Ctx extend | long docs + needle |
| P5 anneal | HQ upsample | proofs / math_reason / chat / safety |

Closed-loop **demand** (expand / curate / examples) is ahead of most open recipes.

## Gaps vs frontier syllabi

| Gap | Frontier practice | Ava status | When |
|-----|-------------------|------------|------|
| G1 Polyak / EMA | Average anneal ckpts (Llama 3) | Not implemented | P5 / end of mini |
| G2 Code volume | Stack-v2 scale, 5–15% code | Modest until P2 (~25% mix + GitHub) | P2+ |
| G3 Mid-train mixture ablations | Small-scale response-surface sweeps | Not automated | After P0–P1 stable |
| G4 Branch FT | Code/math/chat experts then unify | T9.5 post-pretrain; MOPD on master is later | After mini eval |
| G5 Coding probe | HumanEval-scale number | None while on P0 | Gate when entering P2 |
| G6 Hang reliability | Checkpoint + watchdog | Observed hangs ~50–100 steps post-ckpt | **Now** |

## Practical levers (corrected live evidence 2026-07-11)

1. **Exclusive GPU** — keep host `train_mtnn` / other CUDA jobs off the 4080.
2. **Resume from latest hard ckpt** — currently **`step_400.pt`** (not step_200; stale).
3. **Stay on P0** until P1 runway + math sources are ready; do not skip phases.
4. **Hang watchdog** — if no `step` log ≥15m while trainer Up + GPU mem ≥8GB → stop + resume `--resume` from `/ckpt/latest`.
5. **When P2 starts** — add a tiny coding probe to eval harness so “can it code?” is a number.
6. **Syllabus upgrades (defer)** — P5 Polyak/EMA; loss-by-source demand; mid-train mixture sweeps; T9.5 branch FT (+ optional MOPD from master research).

## Other-agent research to absorb (without merging conflicting train paths)

Compatible with this Docker mini closed-loop now:
- Continuous expansion / discovery *ideas* → feed **collector demand `expand`** + future discovery script.
- Inner-monologue / JobBench–GAIA2 workflow mixes → **P3–P5** mixture weights later.
- Hang / resume discipline (above).

Park until GO (different entrypoints on `origin/master`):
- `train_1b_deepspeed.py` / Prefect Hatch crons / 4h 10M expansion on 4090.
- MOPD multi-teacher distill (`on_policy_distill.py`) — after T9.5 experts exist.
- GDrive upload (work Drive blocked; personal/R2 only).

## Stop hard

base1b GO/NO-GO, secrets, irreversible volume prune, killing unrelated GPU jobs.
