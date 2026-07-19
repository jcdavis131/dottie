"""
wandb_dashboard.py — adds J-space live charts
Solo personal project, no connection to employer, built with public/free-tier only
"""
import math

def define_charts():
    charts=[
        "half_life/S1_decay, S1_hl_est, S1_target=8",
        "half_life/S2_decay, S2 target 300",
        "half_life/Critic target 30",
        "half_life/Planner target 150",
        "half_life_curve/S1 token_offset vs retention exp(-ln2*t/hl)",
        "capacity/k vs accuracy S1 knee 6 S2 knee 10 combined 9",
        "routing/S1,S2,Critic,Planner + routing/S2_veto",
        "jspace/S1/broadcast, S2/verbalizable_mass, Critic/early_warning",
        "safety AUC, veto accuracy, inter_space/mi_loss",
        "rope/base, rope/scale, context YaRN 10k->1M",
    ]
    print("W&B charts defined:", charts)
    return charts

if __name__=="__main__":
    define_charts()
