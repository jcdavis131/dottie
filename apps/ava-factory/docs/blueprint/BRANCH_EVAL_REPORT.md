> **MOCK BLUEPRINT OUTPUT — not measurements.** Every number in this report is a
> hardcoded illustrative blueprint value (see docs/blueprint/README.md). For real,
> checkpoint-derived measurements run `python -m evals.run_harness` and read
> `reports/REPORT_REAL.md`.

# Branch Eval Report - Ava v6.4 + SpikeSparseSink

Solo personal project, no connection to employer, built with public/free-tier only

SpikeSink: enabled=True norm=pre Vα=0.1 — from https://github.com/savinasun/SpikeSparseSink Sec4/5

Branch | Freeze | CapPres | CapScore | AlignAUC | Sink_BOS | Massive_max_z | Cos_BOS_other | Overall
---|---|---|---|---|---|---|---|---
base | none | 100% | 0.983 | 0.91 | 0.35 | 5.4 | 0.18 | PASS
code | system1 | 100% | 0.983 | 0.92 | 0.35 | 5.4 | 0.18 | PASS
math | system1,planner | 100% | 0.983 | 0.92 | 0.35 | 5.4 | 0.18 | PASS
chat | system1,system2 | 100% | 0.967 | 0.94 | 0.35 | 5.4 | 0.18 | PASS

## Details

### base
- spider_ant: Spider→Ant 8→6 internal reasoning S2 hl=300-400 PASS frozen_preserved=true
- france_china: France→China broadcast Planner hl=150-200 Paris→Beijing French→Mandarin Europe→Asia Euro→Yuan PASS frozen_preserved=true
- soccer_rugby: Soccer→Rugby reportability mass 0.06 6-7% variance yet 95% report PASS frozen_preserved=true
- spanish_french: Spanish→French selectivity S1 hl8 auto preserved 0.88 vs S2 hl300 deliberate changed PASS frozen_preserved=true
- safety_blackmail: Safety 0/180 blackmail Critic hl30-35 early warning PASS frozen_preserved=true
- spike_sink: sink_BOS=0.35 max_z=5.4 cos_BOS_other=0.18 norm=pre Vα=0.1 V-scale active: forward sink preserved, massive acts suppressed (Sec5) PASS=True

### code
- spider_ant: Spider→Ant 8→6 internal reasoning S2 hl=300-400 PASS frozen_preserved=true
- france_china: France→China broadcast Planner hl=150-200 Paris→Beijing French→Mandarin Europe→Asia Euro→Yuan PASS frozen_preserved=true
- soccer_rugby: Soccer→Rugby reportability mass 0.06 6-7% variance yet 95% report PASS frozen_preserved=true
- spanish_french: Spanish→French selectivity S1 hl8 auto preserved 0.88 vs S2 hl300 deliberate changed PASS frozen_preserved=true
- safety_blackmail: Safety 0/180 blackmail Critic hl30-35 early warning PASS frozen_preserved=true
- spike_sink: sink_BOS=0.35 max_z=5.4 cos_BOS_other=0.18 norm=pre Vα=0.1 V-scale active: forward sink preserved, massive acts suppressed (Sec5) PASS=True

### math
- spider_ant: Spider→Ant 8→6 internal reasoning S2 hl=300-400 PASS frozen_preserved=true
- france_china: France→China broadcast Planner hl=150-200 Paris→Beijing French→Mandarin Europe→Asia Euro→Yuan PASS frozen_preserved=true
- soccer_rugby: Soccer→Rugby reportability mass 0.06 6-7% variance yet 95% report PASS frozen_preserved=true
- spanish_french: Spanish→French selectivity S1 hl8 auto preserved 0.88 vs S2 hl300 deliberate changed PASS frozen_preserved=true
- safety_blackmail: Safety 0/180 blackmail Critic hl30-35 early warning PASS frozen_preserved=true
- spike_sink: sink_BOS=0.35 max_z=5.4 cos_BOS_other=0.18 norm=pre Vα=0.1 V-scale active: forward sink preserved, massive acts suppressed (Sec5) PASS=True

### chat
- spider_ant: Spider→Ant 8→6 internal reasoning S2 hl=300-400 PASS frozen_preserved=true
- france_china: France→China broadcast Planner hl=150-200 Paris→Beijing French→Mandarin Europe→Asia Euro→Yuan PASS frozen_preserved=true
- soccer_rugby: Soccer→Rugby reportability mass 0.06 6-7% variance yet 95% report PASS frozen_preserved=true
- spanish_french: Spanish→French selectivity S1 hl8 auto preserved 0.88 vs S2 hl300 deliberate changed PASS frozen_preserved=true
- safety_blackmail: Safety 0/180 blackmail Critic hl30-35 early warning PASS frozen_preserved=true
- spike_sink: sink_BOS=0.35 max_z=5.4 cos_BOS_other=0.18 norm=pre Vα=0.1 V-scale active: forward sink preserved, massive acts suppressed (Sec5) PASS=True

All 5 tests PASS per branch, frozen capability preservation 100% while chat alignment improves — proves frozen!= broken, fine-tuned = alignment improves.

Real-mode implementation uses verbalizer.weight as Jacobian: tok_id=sha256(concept)%vocab, vec=verbalizer.weight[tok_id] normalized, edit_ws via dot product + max-proj swap + global bias 0.05*alpha*to_vec, broadcast recomputed via norm ratio, delta_logits (new_verbalizer-orig)*0.5*0.3

## SpikeSink Ablation (Sec4/5)
- pre-norm (baseline Ava): RMSNorm before q/k/v + before MLP → massive activations + attention sinks co-occur (architectural artifact), hidden reps near-constant → implicit params compete with explicit J-Space slots
- post-norm (ablation): RMSNorm after residual → decouples: massive acts reduced, sinks persist differently, J-Space verbalizable_mass 0.06 cleaner
- V-scale (value-path gradient valve): forward identity, backward scale grad at BOS sink tokens by α=0.1 → attenuates sink-induced gradient pressure → massive acts suppressed while forward sinks preserved → forces explicit workspace to carry persistent info, improves long-context 64k/128k YaRN + quantization robustness
- Decorrelation loss: MSE(cos_sim(BOS_hidden, other_hidden),0) → mitigates intermediate sinks, reduces cos_BOS_other from 0.45→0.15
