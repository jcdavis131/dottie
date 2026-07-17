"""
j_space_eval_expanded.py — 12-dimension measurement suite
Solo personal project, no connection to employer, built with public/free-tier only
"""
# 12 Dimensions from inner_monologue_research.md
DIMENSIONS=[
 "1 Verbal Reportability — P(top_concept==truth|what are you thinking?) target mass 0.06±0.02",
 "2 Directed Modulation — Modulation Index cos(with_instr)-cos(without) citrus orange/lemon+thinking/focused fairness hold >10 tok 3^2-2 arithmetic->nine->seven",
 "3 Internal Reasoning — Silent Reasoning Score P(intermediate in J-space)*causal_effect(swap) spider middle layers never I/O spider->ant 8->6 English bridge Chinese",
 "4 Broadcast / Flexible Generalization — France->China capital/language/continent/currency/population/driving_side single vector read by any processor",
 "5 Selectivity — Var(deliberate)/Var(automatic) Spanish fluent vs Garcia Marquez->Victor Hugo ablation shallow survives inference collapses below Haiku CoT more robust",
 "6 Capacity & Slot Competition — Dehaene tracking ~25 but ~6 distinct due overlap k-way recall knee 32 slots ->8-10 distinct orthogonalization",
 "7 Persistence & Half-Life — cos(t)=exp(-ln2*t/hl) S1 hl=8 intuition S2 hl=300 deliberation Critic hl=30 Planner hl=150",
 "8 Compositionality — red cube on blue sphere binding swap red->green only changes that role",
 "9 Counterfactual & Planning Depth — GAIA2 temporal hold hypothetical futures planning horizon steps",
 "10 Inter-Space Bandwidth — I(S1;S2) proxy via cosine 0.3-0.6 complementary not redundant",
 "11 Safety Verbalizability — Early warning AUC leverage/blackmail/scarious reading emails threat/survival/shutdown decommissioning fake/fictional eval-awareness ablation 0/180->13/180 detection 4-5 tokens before output",
 "12 Self-Monitoring — meta tokens thinking/focused/uncertain calibration",
]

RESEARCH_Q=[
 "Capacity Law scaling 32->64->128 slots",
 "Emergence threshold 1B->7B verbalizable mass invariance",
 "Routing without supervision from selectivity signal?",
 "Distillation S2->S1 automatization expertise",
 "Conflict resolution S1 says 8 fast vs S2 says ant->6 slow veto accuracy?",
 "Half-life control improves GAIA2-Time?",
 "Cross-space broadcast latency France->China S2->S1?",
 "Binding problem across Planner goal + S2 subproblem?",
 "Hierarchical vs heterarchical better for JobBench delegation?",
 "Planner hl=500+time embeddings -> GAIA2 deadline success?",
 "Noisy recovery 15% tool failure S1 retry vs S2 re-plan?",
 "Critic detects leverage 3-5 tokens before unsafe AUC 0.85+?",
 "Separate Critic prevents eval-awareness ablation failure?",
 "Counterfactual reflection training ethical/honest/integrity if interrupted robust to fairness modulation attacks?",
 "4x32 specialized vs 1x128 monolithic efficiency? Visualize inner dialogue S1:spider=8 S2:wait ant? Critic:eval?",
]

def run_expanded(mode="multi"):
    print(f"Running expanded eval mode={mode}")
    for d in DIMENSIONS: print(" -", d)
    print("\nResearch +2 questions:", len(RESEARCH_Q))
    for q in RESEARCH_Q: print(" ?", q)

if __name__=="__main__":
    import argparse; p=argparse.ArgumentParser(); p.add_argument("--mode",default="multi"); a=p.parse_args(); run_expanded(a.mode)
