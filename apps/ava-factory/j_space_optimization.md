# J-Space Optimization — full expansion roadmap from paper to explicit training
- Reportability loss: CE(verbalizer(workspace.mean), target_concept) — makes 6% variance load-bearing
- Modulation loss: sim_with - sim_without >0.5 for instruction following
- Broadcast loss: target broadcast = 20% of token norm — preserves selectivity
- Selectivity loss: automatic tasks → low variance, deliberate → high variance
Curriculum to expand J-space:
Phase 0-1 Logic/Math: train reportability — force model to report spider before answering 8
Phase 2-3: train modulation — "concentrate on citrus" reward
Phase 4 Long: train broadcast — 128k needle must be held in workspace for all processors
Phase 5 Anneal: train selectivity — mix automatic vs deliberate
Scaling path: 32 slots (Claude baseline) → 64 slots (hold 2-hop + instruction) → 128 slots (human 7±2 but superhuman). With YaRN 1M base, J-space can hold 128k summary that broadcasts to all 131k tokens.
Safety dashboard: show live top concepts, flag leverage/blackmail/threat before output, detect fake/secretly/trick for reward-hacking, unsafe/dangerous for Tylenol case.
