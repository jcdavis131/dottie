// Scout Bounded Recovery Ladder + Side-Effect Classification
// Prevents infinite retries or premature replan — explicit trigger, bounded scope, strict escalation
// v5 Prime — includes node-specific remediation for stuck-loop fix deep.list / langchain.list / eval_hoops + honest lens + early exit
// recovery-ladder.js — 4-Stage Self-Healing + Bio-Inspired Mapping

export const FailureTaxonomy5 = {
  INPUT_CORRUPTION: { id: 'input_corruption', retry: false, action: 're-fetch input + validate schema', layer: 'Observe'},
  CONTEXT_STARVATION: { id: 'context_starvation', retry: false, action: 'expand context window + memory lattice 1-2 hops + add 2 sources', layer: 'Orient'},
  TOOL_FAILURE: { id: 'tool_failure', retry: true, action: 'retry with alt tool or sandbox 30s×2', layer: 'Act'},
  REASONING_COLLAPSE: { id: 'reasoning_collapse', retry: false, action: 'patch prompt + reduce scope to single-resp', layer: 'Decide'},
  OUTPUT_CORRUPTION: { id: 'output_corruption', retry: true, action: 're-generate with tighter schema', layer: 'Act'},
};

export const SideEffectClasses = {
  READ: { level: 0, label: 'read-only', examples: ['browser.search','memory_search','reads sheets'], retry: 'safe unlimited (bounded 1×)', parallel: 'yes', human_gate: false},
  WRITE_IDEMPOTENT: { level: 1, label: 'write idempotent', examples: ['write file same path','upsert row with id'], retry: 'safe 1× with check', parallel: 'with idempotency key', human_gate: false},
  WRITE_DESTRUCTIVE: { level: 2, label: 'write destructive', examples: ['delete','overwrite no backup','drop table'], retry: 'never auto, require human confirm', parallel: 'no', human_gate: true},
  EXTERNAL_NOTIFY: { level: 3, label: 'external notify irreversible', examples: ['send email','post social','ticket purchase','pay invoice'], retry: 'never auto on failure, classify', parallel: 'no speculative parallel', human_gate: true},
};

export const RecoveryLadder = [
  { step: 1, name: 'Validation Check', trigger: 'any node output', action: 'schema validate vs expected artifact type, not "is good?"', max_attempts: 1, cost: 'low', on_fail: '→ step2'},
  { step: 2, name: 'Transient Retry', trigger: 'TOOL_FAILURE or OUTPUT_CORRUPTION transient', action: 'retry 1× same agent same prompt', max_attempts: 1, cost: 'tokens', on_fail: '→ step3', bio: 'Hemostasis/Containment — isolate reroute'},
  { step: 3, name: 'Patch Prompt', trigger: 'REASONING_COLLAPSE or CONTEXT_STARVATION', action: 'new prompt = old prompt + failure context + narrowed scope single-resp', max_attempts: 1, cost: 'medium', on_fail: '→ step4', bio: 'Inflammation/Diagnosis — collect analyze scope'},
  { step: 4, name: 'Replan Node', trigger: 'same node fails 2× or failure class = INPUT_CORRUPTION', action: 'replan protocol: version DAG++ never mutate in place slice_from node_id, alternative agent from pool', max_attempts: 2, cost: 'high', on_fail: '→ step5', bio: 'Proliferation/MetaCognitive — microagent new pathways'},
  { step: 5, name: 'Escalate Human', trigger: '≥2 replans fail OR side_effect.level>=2 OR BLOCKED', action: 'precise ask to Cameron: blocker_reason + alternatives + missing info', max_attempts: 1, cost: 'human time', on_fail: 'halt', bio: 'Remodeling/Knowledge — propagate via rendezvous'},
];

export function decideRecovery({ nodeId, attempt, failureClass, sideEffectLevel, replanCount}){
  if (replanCount >=2) return { action: 'escalate', to: 'human', reason: `repeated replan ${nodeId} ${failureClass}`, step: 5};
  if (sideEffectLevel >=2 && attempt>=1) return { action: 'escalate', to: 'human', reason: `destructive side-effect ${sideEffectLevel} requires confirm`, step: 5};
  if (failureClass === 'TOOL_FAILURE' && attempt===1) return { action: 'retry', target: nodeId, step: 2};
  if (failureClass === 'OUTPUT_CORRUPTION' && attempt===1) return { action: 'retry', target: nodeId, step: 2};
  if (failureClass === 'REASONING_COLLAPSE' || failureClass === 'CONTEXT_STARVATION') return { action: 'patch', target: nodeId, step: 3, newPromptHint: `fix ${failureClass} narrow scope`};
  if (attempt>=2) return { action: 'replan', slice_from: nodeId, step: 4, dag_version_increment: true};
  return { action: 'repair', target: nodeId, step: 2};
}

export function getNodeSpecificRecovery(nodeId){
  const map={
    'deep.list': { failureClass:'CONTEXT_STARVATION', retries:false, lateralLens:'concept-fan', earlyExitAfter:2, action:'return cached list manifest.json + ACNE src/acne fallback 5-layer, zero-deps true no torch', honest:{ visibleAbandonments:true, noFake7of7:true, early_exit_after:2, triple_write_7field:true, zero_deps:true, reason:'Deep adapter discovery repeating 4x healthy — healthyRepetition skip, but if sameRun retry, cache registry to avoid pip', docs:'bundles/manifest.json v3.3-OODA-Agentic-MoMA-Graph-Checkpoint 13 agents / 11 packs' } },
    'langchain.list': { failureClass:'TOOL_FAILURE', retries:false, lateralLens:'scamper', earlyExitAfter:2, action:'Substitute LangChain with ACNE hatch tools get_hatch_tools(), Combine with local src/acne, return cached adapter list, no pip heavy deps', honest:{ visibleAbandonments:true, noFake7of7:true, early_exit_after:2, zero_deps:true, reason:'LangChain heavy pip blocked zero_deps flag true — scamper to ACNE pattern, healthy repetition elsewhere ok', docs:'zero_deps.json allow acne:./src no pip heavy' } },
    'eval_hoops': { failureClass:'OUTPUT_CORRUPTION', retries:false, lateralLens:'inversion', earlyExitAfter:2, action:'Use cached eval_scoreboard.json assets/ mtime<24h, provenance 7/7/0, inversion lens worsen metric then invert back, triple-write 7-field mandatory, early exit after PASS', honest:{ visibleAbandonments:true, noFake7of7:true, early_exit_after:2, triple_write_7field:true, zero_deps:true, reason:'eval_hoops 5x healthy ok but 5× re-eval wasteful — memoize, gate G1-G4 player-split leak-free not season-split, DM_PROVENANCE 7/7/0 live', docs:'mlops-operator.md layer3 MLOps end-to-end Gate G1-G4' } },
    'analytics-phase0': { failureClass:'TOOL_FAILURE', retries:false, lateralLens:'six-hats', earlyExitAfter:2, action:'cached analytics store bundles/analytics/store.jsonl OR safe no-op shard bundles/analytics/events/.gitkeep + heartbeat :13 no-torch zero-deps true — candidate.json first honest triple-write 7-field mandatory visibleAbandonment noFake7of7 early_exit 2', honest:{ visibleAbandonments:true, noFake7of7:true, early_exit_after:2, triple_write_7field:true, zero_deps:true, no_torch:true, candidate_first:true, fallback:'cached analytics store OR safe no-op shard', reason:'analytics Phase0 TOOL_FAILURE loop>3 distinctRuns=2 failures=2 — deterministic cheap MoMA-lite no-torch DAU1 WAU1 missing cached shard. Real failure not healthy repetition per pattern_detector. Apply six-hats honest lens blue-hat process control + green-hat cache fallback early exit 2 visibleAbandonment noFake7of7', docs:'bundles/analytics/store.jsonl + events/.gitkeep shard + cli5 + zero_deps.json' } },
    'auth-phase0': { failureClass:'TOOL_FAILURE', retries:false, lateralLens:'analogy', earlyExitAfter:2, action:'cached flags bundles/auth/flags.jsonl 4 lines is_on 0.9 OR 0.9 cached verified <2h no-torch 3-user users.jsonl zero_deps true candidate.json first honest triple-write 7-field mandatory visibleAbandonment noFake7of7 early_exit 2', honest:{ visibleAbandonments:true, noFake7of7:true, early_exit_after:2, triple_write_7field:true, zero_deps:true, no_torch:true, candidate_first:true, fallback:'cached flags 0.9 OR 0.9 cached verified <2h no-torch 3-user', reason:'auth Phase0 TOOL_FAILURE loop>3 distinctRuns=2 failures=2 — 3-user flags 0.9 cached <2h no-torch missing cached flags. Real failure not healthy repetition. Analogy traffic: flags=is_on cached as signal timing. Honest lens analogy early exit 2 visibleAbandonment noFake7of7', docs:'bundles/auth/users.jsonl 3 lines + flags.jsonl 4 flags is_on 0.9 + zero_deps.json' } },
  };
  return map[nodeId]||null;
}

export function classifyNodeFailure(nodeId, error){
  const specific=getNodeSpecificRecovery(nodeId);
  if(specific) return specific.failureClass;
  if(error?.includes('input')||error?.includes('schema')) return 'INPUT_CORRUPTION';
  if(error?.includes('context')||error?.includes('memory')) return 'CONTEXT_STARVATION';
  if(error?.includes('tool')||error?.includes('timeout')) return 'TOOL_FAILURE';
  if(error?.includes('reason')||error?.includes('logic')) return 'REASONING_COLLAPSE';
  if(error?.includes('output')||error?.includes('json')||error?.includes('artifact')) return 'OUTPUT_CORRUPTION';
  return 'TOOL_FAILURE';
}

export function classifySideEffect(toolName) {
  if (/search|read|get|list|fetch/.test(toolName)) return SideEffectClasses.READ;
  if (/write|edit|upsert/.test(toolName) &&!/delete/.test(toolName)) return SideEffectClasses.WRITE_IDEMPOTENT;
  if (/delete|drop|overwrite.*no.backup/.test(toolName)) return SideEffectClasses.WRITE_DESTRUCTIVE;
  if (/send|post|notify|email|purchase|pay|ticket/.test(toolName)) return SideEffectClasses.EXTERNAL_NOTIFY;
  return SideEffectClasses.READ;
}

export default { FailureTaxonomy5, SideEffectClasses, RecoveryLadder, decideRecovery, getNodeSpecificRecovery, classifyNodeFailure, classifySideEffect };
