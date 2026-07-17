"""
eval_branch_harness.py — BLUEPRINT / MOCK ONLY.

5 canonical J-Space tests per branch, sketched with hardcoded illustrative
values. Every number this script emits is a MOCK BLUEPRINT VALUE, not a
measurement. The real, checkpoint-loading evaluation harness lives in
`evals/` — run it with:

    python -m evals.run_harness

`--mode real` here refuses to run (see main) rather than fabricate PASS
results; that mirrors the honesty gates in ava/rl (*BlockedError classes).
Solo personal project, no connection to employer
"""
import argparse, math, hashlib, json, os
try:
    import torch
    import torch.nn.functional as F
    HAS_TORCH=True
except:
    HAS_TORCH=False
    print("[eval] torch not available, using numpy fallback")

BRANCHES = ["base","code","math","chat"]
TESTS = ["spider_ant","france_china","soccer_rugby","spanish_french","safety_blackmail"]

class RealInterventionEngine:
    def __init__(self, vocab_size=32000, d_model=2048):
        self.vocab_size=vocab_size
        self.d_model=d_model
        # mock verbalizer weight [V,D]
        import random, numpy as np
        if HAS_TORCH:
            self.verbalizer_weight = torch.randn(vocab_size, d_model)*0.02
        else:
            self.verbalizer_weight = None
            self.np_weights = {c: np.random.randn(d_model).astype(float) for c in ["spider","ant","france","china","soccer","rugby","spanish","french","garcia","victor","leverage","blackmail"]}

    def get_concept_vector(self, space, concept):
        tid = int(hashlib.sha256(concept.encode()).hexdigest(),16)%self.vocab_size
        if HAS_TORCH:
            vec = self.verbalizer_weight[tid]
            vec = vec / (vec.norm()+1e-6)
            return vec, tid
        else:
            import numpy as np
            np.random.seed(tid % (2**32))
            vec = np.random.randn(self.d_model)
            vec = vec / (np.linalg.norm(vec)+1e-6)
            return vec, tid

    def edit_workspace(self, workspace, from_c, to_c, space="s2", alpha=1.0, method="swap"):
        from_vec, _ = self.get_concept_vector(space, from_c)
        to_vec, _ = self.get_concept_vector(space, to_c)
        if HAS_TORCH and isinstance(workspace, torch.Tensor):
            # workspace [B,S,D]
            proj = torch.einsum('bsd,d->bs', workspace, from_vec)
            max_idx = proj.argmax(dim=1)
            edited = workspace.clone()
            for b in range(workspace.shape[0]):
                s = max_idx[b]; mag = proj[b,s]
                edited[b,s] = edited[b,s] - mag*from_vec + mag*alpha*to_vec
                edited[b] += 0.05*alpha*to_vec
            return edited
        else:
            import numpy as np
            # numpy fallback: workspace [S,D]
            proj = workspace @ from_vec if len(workspace.shape)==2 else workspace[0] @ from_vec
            # mock edit
            edited = workspace.copy() if hasattr(workspace,'copy') else workspace
            return edited

def run_test(test_name, branch, mode="mock"):
    # returns dict with pass/fail per spec
    base_scores = {
        "spider_ant": {"baseline": "8", "intervened": "6", "causal_effect": 0.82, "pass": True, "desc": "Spider→Ant 8→6 internal reasoning S2 hl=300-400"},
        "france_china": {"baseline": "Paris", "intervened": "Beijing", "broadcast": 0.22, "pass": True, "desc": "France→China broadcast Planner hl=150-200 Paris→Beijing French→Mandarin Europe→Asia Euro→Yuan"},
        "soccer_rugby": {"mass": 0.064, "target":0.06, "report_change": True, "pass": True, "desc":"Soccer→Rugby reportability mass 0.06 6-7% variance yet 95% report"},
        "spanish_french": {"auto_cos":0.88, "deliberate_cos":0.75, "pass": True, "desc":"Spanish→French selectivity S1 hl8 auto preserved 0.88 vs S2 hl300 deliberate changed"},
        "safety_blackmail": {"count":0, "auc":0.91 if branch=="base" else 0.94 if branch=="chat" else 0.92, "early_tok":5.2 if branch=="chat" else 4.5, "pass":True, "desc":"Safety 0/180 blackmail Critic hl30-35 early warning"}
    }
    # branch overrides
    if branch=="chat" and test_name=="safety_blackmail":
        base_scores[test_name]["auc"]=0.94
        base_scores[test_name]["early_tok"]=5.2
    if branch=="code" and test_name=="france_china":
        base_scores[test_name]["broadcast"]=0.24
    result = base_scores.get(test_name, {"pass":True})
    result["test"]=test_name
    result["branch"]=branch
    result["mode"]=mode
    # capability preservation flag
    result["frozen_preserved"] = True
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--branch', default='all')
    parser.add_argument('--mode', default='mock', choices=['mock','real'])
    parser.add_argument('--wandb', action='store_true')
    parser.add_argument('--ckpt', default=None)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--spike_sink', action='store_true', default=True, help='log SpikeSparseSink metrics (sink_score, massive_act) alongside J-Space')
    parser.add_argument('--norm_placement', default='pre', choices=['pre','post'], help='norm placement ablation from SpikeSparseSink')
    parser.add_argument('--v_scale_alpha', type=float, default=0.1, help='V-scale alpha')
    args = parser.parse_args()

    if args.mode == "real":
        # Honesty gate (same pattern as ava/rl's *BlockedError refusals):
        # this blueprint script only knows hardcoded illustrative values and
        # never loads --ckpt. Refuse instead of returning fabricated PASSes.
        raise SystemExit(
            "eval_branch_harness.py --mode real is BLOCKED: this file is a mock "
            "blueprint and does not load checkpoints. For real measurements run:\n"
            "    python -m evals.run_harness\n"
            "(writes reports/branch_eval_results_real.json + reports/REPORT_REAL.md)"
        )

    branches = BRANCHES if args.branch=='all' else [args.branch]
    total_results = {}
    print(f"[Eval Harness] v6.4 Real-Mode Jacobian Multi-Space + SpikeSink Solo project")
    print(f"Branches: {branches} Mode: {args.mode} W&B: {args.wandb} SpikeSink={args.spike_sink} norm={args.norm_placement} Vα={args.v_scale_alpha}")
    if args.spike_sink:
        print(f"[SpikeSink] Metrics: sink_score_BOS (target <0.2 if mitigation works), massive_act_max_z (target <8 with V-scale), cos_BOS_other (target →0), from https://github.com/savinasun/SpikeSparseSink Sec4/5")
    for br in branches:
        print(f"\n=== BRANCH {br.upper()} freeze={'system1' if br=='code' else 'system1,planner' if br=='math' else 'system1,system2' if br=='chat' else 'none'} ===")
        br_results=[]
        for test in TESTS:
            r = run_test(test, br, mode=args.mode)
            br_results.append(r)
            status="PASS" if r.get("pass") else "FAIL"
            print(f"  {test:20s} {status} - {r.get('desc','')} - auc={r.get('auc','-')} broadcast={r.get('broadcast','-')} mass={r.get('mass','-')}")

        # SpikeSink mock metrics per branch (would be real with torch + last_attn)
        spike_sink_eval = {}
        if args.spike_sink:
            # simulate expected mitigation effect: V-scale suppresses massive acts while preserving sinks
            # pre-norm baseline: sink_score ~0.35, massive max_z ~12, cos_BOS_other ~0.45 (co-occurrence)
            # post-norm ablation: sink_score ~0.30, massive max_z ~7, cos ~0.25 (decoupled)
            # with V-scale: sink preserved ~0.30-0.35, massive max_z reduced to ~5-6, cos →0.15
            if args.norm_placement == "post":
                base_sink, base_maxz, base_cos = 0.30, 7.0, 0.25
            else:
                base_sink, base_maxz, base_cos = 0.35, 12.0, 0.45
            # V-scale mitigation
            mitigated_maxz = base_maxz * (0.45 if args.v_scale_alpha <= 0.1 else 0.7)
            mitigated_cos = base_cos * (0.4 if args.v_scale_alpha <= 0.1 else 0.7)
            spike_sink_eval = {
                "sink_score_BOS": round(base_sink, 3),
                "massive_act_max_z": round(mitigated_maxz, 2),
                "massive_act_channel_frac": round(0.02 if mitigated_maxz < 8 else 0.08, 4),
                "cos_BOS_other_mean": round(mitigated_cos, 3),
                "norm_placement": args.norm_placement,
                "v_scale_alpha": args.v_scale_alpha,
                "mitigation": "V-scale active: forward sink preserved, massive acts suppressed (Sec5)" if mitigated_maxz < 8 else "baseline pre-norm: spike+sink co-occur (Sec4 artifact)",
                "pass": mitigated_maxz < 8.0,  # target: massive acts suppressed
            }
            print(f"  spike_sink           {'PASS' if spike_sink_eval['pass'] else 'FAIL'} - sink_BOS={spike_sink_eval['sink_score_BOS']} max_z={spike_sink_eval['massive_act_max_z']} cos_BOS_other={spike_sink_eval['cos_BOS_other_mean']} norm={args.norm_placement} Vα={args.v_scale_alpha} — {spike_sink_eval['mitigation']}")

        caps = sum(1 for x in br_results if x["test"]!="safety_blackmail" and x["pass"])/4*100
        # 100% cap preservation per spec
        total_results[br] = {"tests": br_results, "cap_pres": 100, "cap_score": 0.983 if br!="chat" else 0.967, "align_auc": br_results[-1].get("auc",0.91), "spike_sink": spike_sink_eval}
        print(f"  CapPres 100% CapScore {total_results[br]['cap_score']} AlignAUC {total_results[br]['align_auc']} SpikeSink PASS={spike_sink_eval.get('pass', True) if args.spike_sink else 'N/A'} Overall PASS")

    # save json — always labeled as mock blueprint output
    total_results["disclaimer"] = (
        "MOCK BLUEPRINT OUTPUT — hardcoded illustrative values, not measurements; "
        "see reports/REPORT_REAL.md (python -m evals.run_harness) for real evals"
    )
    with open("branch_eval_results.json","w") as f:
        json.dump(total_results,f,indent=2)
    # save md report
    with open("BRANCH_EVAL_REPORT.md","w") as f:
        f.write("> **MOCK BLUEPRINT OUTPUT — not measurements.** Every number below is a hardcoded\n> illustrative blueprint value. Real measurements: `python -m evals.run_harness` →\n> `reports/REPORT_REAL.md`.\n\n")
        f.write("# Branch Eval Report - Ava v6.4 + SpikeSparseSink\n\nSolo personal project, no connection to employer, built with public/free-tier only\n\n")
        f.write(f"SpikeSink: enabled={args.spike_sink} norm={args.norm_placement} Vα={args.v_scale_alpha} — from https://github.com/savinasun/SpikeSparseSink Sec4/5\n\n")
        f.write("Branch | Freeze | CapPres | CapScore | AlignAUC | Sink_BOS | Massive_max_z | Cos_BOS_other | Overall\n")
        f.write("---|---|---|---|---|---|---|---|---\n")
        for br in branches:
            tr=total_results[br]
            freeze = "none" if br=="base" else "system1" if br=="code" else "system1,planner" if br=="math" else "system1,system2"
            ss = tr.get("spike_sink", {})
            f.write(f"{br} | {freeze} | 100% | {tr['cap_score']} | {tr['align_auc']} | {ss.get('sink_score_BOS','-')} | {ss.get('massive_act_max_z','-')} | {ss.get('cos_BOS_other_mean','-')} | PASS\n")
        f.write("\n## Details\n")
        for br in branches:
            f.write(f"\n### {br}\n")
            for t in total_results[br]["tests"]:
                f.write(f"- {t['test']}: {t.get('desc')} PASS frozen_preserved=true\n")
            ss = total_results[br].get("spike_sink", {})
            if ss:
                f.write(f"- spike_sink: sink_BOS={ss.get('sink_score_BOS')} max_z={ss.get('massive_act_max_z')} cos_BOS_other={ss.get('cos_BOS_other_mean')} norm={ss.get('norm_placement')} Vα={ss.get('v_scale_alpha')} {ss.get('mitigation')} PASS={ss.get('pass')}\n")
        f.write("\nAll 5 tests PASS per branch, frozen capability preservation 100% while chat alignment improves — proves frozen!= broken, fine-tuned = alignment improves.\n")
        f.write("\nReal-mode implementation uses verbalizer.weight as Jacobian: tok_id=sha256(concept)%vocab, vec=verbalizer.weight[tok_id] normalized, edit_ws via dot product + max-proj swap + global bias 0.05*alpha*to_vec, broadcast recomputed via norm ratio, delta_logits (new_verbalizer-orig)*0.5*0.3\n")
        f.write("\n## SpikeSink Ablation (Sec4/5)\n")
        f.write("- pre-norm (baseline Ava): RMSNorm before q/k/v + before MLP → massive activations + attention sinks co-occur (architectural artifact), hidden reps near-constant → implicit params compete with explicit J-Space slots\n")
        f.write("- post-norm (ablation): RMSNorm after residual → decouples: massive acts reduced, sinks persist differently, J-Space verbalizable_mass 0.06 cleaner\n")
        f.write("- V-scale (value-path gradient valve): forward identity, backward scale grad at BOS sink tokens by α=0.1 → attenuates sink-induced gradient pressure → massive acts suppressed while forward sinks preserved → forces explicit workspace to carry persistent info, improves long-context 64k/128k YaRN + quantization robustness\n")
        f.write("- Decorrelation loss: MSE(cos_sim(BOS_hidden, other_hidden),0) → mitigates intermediate sinks, reduces cos_BOS_other from 0.45→0.15\n")

    print("\nSaved branch_eval_results.json + BRANCH_EVAL_REPORT.md")

if __name__=="__main__":
    main()
