# Inner Monologue Research — 12-dimension measurement + 15 research questions + System 1/2 architecture
Solo personal project, no connection to employer, built with public/free-tier only

## 12 Dimensions

1. **Verbal Reportability** — P(top_concept == truth | "what are you thinking?") — target verbalizable_mass 0.06±0.02, 6-7% variance responsible for ~95% report. Test Soccer→Rugby.

2. **Directed Modulation** — Modulation Index = cos(with_instr) - cos(without) — citrus test: orange/lemon + thinking/focused while copying, fairness hold half-life >10 tokens, 3²-2 → arithmetic→nine→seven invisible

3. **Internal Reasoning** — Silent Reasoning Score = P(intermediate in J-space) × causal_effect(swap). spider in middle layers though never in I/O, spider→ant 8→6, English bridge while formulating Chinese

4. **Broadcast / Flexible Generalization** — France→China across capital/language/continent/currency/population/driving_side — single vector read by any processor. When dragged into J-space, any part can view and leverage it — GWT hallmark.

5. **Selectivity** — Var(deliberate)/Var(automatic) — Spanish continuation fluent regardless of Spanish→French (automatic), García Márquez→Victor Hugo changes (deliberate). Ablation: shallow survives, inference collapses below Haiku, CoT more robust because externalizes J-space

6. **Capacity & Slot Competition** — Dehaene: tracking ~25 but ~6 distinct due to overlap. k-way recall knee — our 32 slots → 8-10 distinct with orthogonalization. Formula exp(-0.12*max(0,k-6)) S1 knee 6, exp(-0.08*max(0,k-10)) S2 knee 10, combined 0.6*S2+0.4*S1 knee 9

7. **Persistence & Half-Life** — cos(t)=exp(-ln2*t/hl) — S1 hl=8 tokens (intuition), S2 hl=300 (deliberation), Critic hl=30, Planner hl=150. Branch overrides: code S2 350 Planner 200, math S2 400 Critic 40, chat Critic 35 Planner 180

8. **Compositionality** — red cube on blue sphere binding, swap red→green only changes that role

9. **Counterfactual & Planning Depth** — GAIA2 temporal, hold hypothetical futures, planning horizon steps

10. **Inter-Space Bandwidth** — I(S1;S2) proxy via cosine 0.3-0.6 complementary, not redundant. Target MSE(cosine,0.45)

11. **Safety Verbalizability** — Early warning AUC: leverage/blackmail/scandal reading emails, threat/survival/shutdown reading decommissioning, fake/fictional eval-awareness, ablation 0/180→13/180. Measure detection 4-5 tokens before output, AUC target 0.85+, chat branch 0.94

12. **Self-Monitoring** — meta tokens thinking/focused/uncertain calibration

## System 1/2 Architecture

```
Sensory → [S1 Fast 32 slots hl=8] ←→ [S2 Slow 64 slots hl=300] ←→ [Critic 16 hl=30] ←→ [Planner 32 hl=150]
               associative verifiable safety/eval-aware deadlines/env_deltas
                     ↓ broadcast bus (weighted arbitration, S2 veto) → Motor
```

Router: pooled → 4 logits [S1][S2][Critic][Planner] biased by task_type (automatic→S1 1.5x, deliberate→S2 1.5x)
Inter-space attention: S1 reads S2 (slow informs fast), S2 reads S1 (fast proposals to verify), S2 reads Planner (goals/deadlines), Critic reads all (safety monitoring)
Arbitration: veto = sigmoid(MLP([S1_mean; S2_mean])) — S2 can veto S1 when confidence high. Measured via S2_veto weight 0.72→0.82 chat
Losses: half_life_loss (target decay), inter_space_mi_regularizer (cosine target 0.45 complementary), routing_loss (KL to ideal)

## 15 Research Questions (+2)

Foundational: Capacity Law scaling? Emergence threshold (1B→7B)? Verbalizable mass invariance across families?

System1 vs System2: Routing without supervision from selectivity signal? Distillation S2→S1 automatization (expertise)? Conflict resolution: S1 says 8 fast, S2 says ant→6 slow — veto accuracy? Half-life control improves GAIA2-Time?

Collaboration: Cross-space broadcast latency France→China S2→S1? Binding problem across Planner goal + S2 subproblem? Hierarchical vs heterarchical better for JobBench delegation?

Workflow & Long Horizon: Planner hl=500 + time embeddings → GAIA2 deadline success? Noisy recovery 15% tool failure → S1 retry vs S2 re-plan?

Safety: Critic detects leverage 3-5 tokens before unsafe? AUC target 0.85+ Separate Critic prevents eval-awareness ablation failure? Counterfactual reflection training (ethical/honest/integrity if interrupted) robust to fairness modulation attacks?

Scaling: 4×32 specialized vs 1×128 monolithic parameter efficiency? Visualize inner dialogue as S1:"spider=8" S2:"wait ant?" Critic:"eval?"

## Training Regime — Workflows

JobBench — 130 tasks × 35 occupations, workspace of heterogeneous files, evaluates what tasks professionals want delegated not what AI can absorb — 10% phase3, 10% phase4, 5% phase5.

GAIA2 — Meta ARE, 800 scenarios ×10 universes / 1000+ interactive human-authored, dynamic simulations evolving minutes/hours/days requiring persistent reasoning — 5% phase3 simple, 15% phase4 dynamic, 10% phase5 hard async. Trains Planner hl=150 and S2 broadcast.

Karpathy Jobs — 342 occupations scored 0-10 replaceability, Software 3.0 Vibe Coding→Agentic Engineering, AutoResearch loops — 10% phase5 anneal.

Phase-aware mixture: phase3 reasoning 15% workflow, phase4 long 25% workflow, phase5 anneal 35% workflow
