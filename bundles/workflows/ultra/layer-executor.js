export const meta = {
  name: "layer-executor",
  description: "Layer 3 — executes one DAG node with self-contained workspace, supports parallel groups + stuck-detector v5 Prime + honest lens",
  phases: [
    { name: "stuck-check", title: "v5 Prime stuck detector — loop>3 conf<0.4 latency>thr → 1 lens" },
    { name: "execute-node", title: "Run single DAG node with lateral lens if needed" },
    { name: "checkpoint-save", title: "Triple-write 7-field mandatory per checkpoint-manager" },
    { name: "route-check", title: "Router-2 checks if downstream changed + recovery ladder bounded" }
  ]
};

// args: { node: {id,title,agent,pack,expected_artifact,depends_on,inputs}, prior_outputs, runId, memory_context, dag, history?, attempt? }

import { detectStuck, applyLens, honestLensReport, shouldEarlyExit, getStuckRemediation } from '../../ultra/stuck-detector.js';
import { decideRecovery, classifySideEffect, FailureTaxonomy5 } from '../../ultra/recovery-ladder.js';
import { UltraCheckpointManager } from '../../ultra/checkpoint-manager.js';

const node = args.node;
const prior = args.prior_outputs || {};
const runId = args.runId || "ultra-run";
const history = args.history || args.prior_history || [];
const attempt = args.attempt || 1;

// --- v5 Prime Stuck Detector Check ---
let stuckInfo = null;
let lensPrompt = "";
let honestInfo = null;
let earlyExit = { early:false };

try {
  // Build history for stuck detector from prior timeline or supplied history
  // history shape: [{nodeId, attempt, confidence, latency, errorClass, observationHash, status, runId}, ...]
  const inputHistory = (history.length ? history : Object.values(prior).map(o=>({
    nodeId: o.node_id||o.id||'',
    attempt: o.attempt||1,
    confidence: o.confidence||o.critic_score||1,
    latency: o.latency_ms||o.latency||0,
    errorClass: o.errorClass||o.blocker_reason||null,
    observationHash: o.artifact_path||o.summary||'',
    status: o.status||'',
    runId: o.runId||runId
  }))).filter(h=>h.nodeId);

  if(inputHistory.length){
    // only check recent 10 for this node
    const relevant = inputHistory.filter(h=>h.nodeId===node.id).slice(-6);
    if(relevant.length>=3){
      stuckInfo = detectStuck(relevant.length ? relevant : inputHistory);
      if(stuckInfo?.stuck){
        honestInfo = honestLensReport(stuckInfo, { nodeId: node.id, history: relevant, task: node.title });
        const remediation = getStuckRemediation(stuckInfo, { nodeId: node.id, nodeIds: relevant.map(r=>r.nodeId) });
        earlyExit = shouldEarlyExit(relevant);
        if(remediation.lens){
          lensPrompt = applyLens(remediation.lens, { nodeId: node.id, goal: node.title, trigger: stuckInfo.trigger });
        }
      }
    }
  }
} catch(e){ /* detector non-blocking */ stuckInfo=null; }

// Specific node remediation for 3 known stuck loops (deep.list, langchain.list, eval_hoops)
const knownRemediation = {
  "deep.list": {
    failureClass: "CONTEXT_STARVATION",
    reason: "Deep adapter discovery listing 4x over 7d each ok — healthy repetition but missing ACNE 5-layer cache causes re-list each run. Fix: cache registry, honest lens.",
    lens: "concept-fan",
    fix: "Return cached deep agent list from manifest.json + ACNE local src/acne if present, zero-deps. Avoid pip torch. Early exit after 2 attempts with empty list fallback. Honest visibleAbandonments noFake7of7."
  },
  "langchain.list": {
    failureClass: "TOOL_FAILURE",
    reason: "LangChain adapter list 4x over 7d each 45ms ok — LangChain not needed pip heavy, should use ACNE pattern. Fix: scamper lens.",
    lens: "scamper",
    fix: "Substitute LangChain with ACNE adapters (get_langchain_tools()->get_hatch_tools), Combine with local src/acne, Adapt from ACNE 5-layer. Return cached list from bundles/manifest.json. Zero-deps true."
  },
  "eval_hoops": {
    failureClass: "OUTPUT_CORRUPTION", // actually healthy but repeated eval wasteful
    reason: "eval_hoops 5x over 7d each 350ms ok — repeated eval without caching wastes tokens. Gate G1-G4 passes but no memoization. Fix: inversion lens.",
    lens: "inversion",
    fix: "Invert: worsen metric deliberately to test gate brittleness then invert back. Use cached eval_scoreboard.json from assets/ if mtime <24h, provenance 7/7/0. Triple-write checkpoint mandatory 7-field even no-change. Early exit after gate PASS, zero-deps."
  }
};

const thisNodeFix = knownRemediation[node.id] || null;
if(thisNodeFix && !lensPrompt){
  lensPrompt = applyLens(thisNodeFix.lens, { nodeId: node.id, goal: node.title, trigger: thisNodeFix.failureClass });
}

// --- Execute Node with Lens ---
const agentPrompt = `You are ${node.agent} executing Scout Ultra Layer 3.
NODE: ${JSON.stringify(node)}
TASK: ${node.title}
EXPECTED ARTIFACT: ${node.expected_artifact}
MEMORY: ${(args.memory_context||"").slice(0,1200)}
PRIOR NODE OUTPUTS: ${JSON.stringify(prior).slice(0,3000)}
RUN ID: ${runId}
ATTEMPT: ${attempt}
${stuckInfo?.stuck ? `STUCK DETECTED v5 Prime: trigger=${stuckInfo.trigger} meta=${stuckInfo.metaPattern} reasons=${(stuckInfo.reasons||[]).join('|')} confidence=${stuckInfo.confidence} lens=${stuckInfo.lens} earlyExit=${earlyExit.early||false} honest=${JSON.stringify(honestInfo?.remediation||{}).slice(0,500)}` : `STUCK: none — healthy`}
${lensPrompt ? `LATERAL LENS TRIGGER (1 lens per v5 Prime): ${lensPrompt} — apply exactly one lens, do not ignore. If you cannot apply, state honest abandonment visible. No fake 7/7.` : ''}
${thisNodeFix ? `KNOWN FIX for ${node.id}: failureClass=${thisNodeFix.failureClass} reason=${thisNodeFix.reason} fix=${thisNodeFix.fix} — implement.` : ''}
${earlyExit.early ? `EARLY EXIT TRIGGER: ${earlyExit.reason} — do NOT retry same approach, switch lens or fallback honest empty result. Zero-deps true, no torch pip, no network egress.` : ''}

Rules from ~/workspace/bundles/agents/executor.md:
- Use ${node.pack}
- Write artifact to correct spot (your_files/<slug>/ for final, bundles/research/ for research, exports/ for temp, bundles/ultra/runs/${runId}/ for working)
- Triple-write 7-field mandatory: bundles/ultra/runs/<runId>/timeline.jsonl + dottie/pipeline/runs/<runId>/ + dottie/bundles/ultra/runs/<runId>/ etc (handled by checkpoint-manager but acknowledge)
- If blocked, say blocked precisely with failureClass=${Object.keys(FailureTaxonomy5).join('|')} — choose one
- Return JSON: { node_id, status, artifact_path, summary, critic_score?, blocked?, blocker_reason?, new_dependency?, attempt, latency_ms, tokens_est, errorClass, confidence, observationHash }

Scout rules v5 Prime:
- Zero-deps true (bundles/zero_deps.json allow acne:./src) — no pip installs, no cloud, ACNE optional local. LanceDB/onnx optional fallback.
- Honest lens: visibleAbandonments true, noFake7of7 true — never claim 7/7 if missing 6 spots repaired.
- 1 clarifying question max already done — do NOT ask more. Execute best guess if ambiguous.
- If this is deep.list / langchain.list / eval_hoops — apply known fix above, use cached assets, early exit after 2, honest report.`;

const result = await agent(
  agentPrompt,
  { key:`exec-${node.id}-${runId}`, label:`exec ${node.id} ${stuckInfo?.stuck?'(lens:'+stuckInfo.lens+')':''}`, schema:{
    type:"object", required:["node_id","status","summary"],
    properties:{
      node_id:{type:"string"},
      status:{type:"string", enum:["completed","blocked","failed"]},
      artifact_path:{type:"string"},
      summary:{type:"string"},
      critic_score:{type:"number"},
      blocked:{type:"boolean"},
      blocker_reason:{type:"string"},
      new_dependency:{type:"object"},
      attempt:{type:"number"},
      latency_ms:{type:"number"},
      tokens_est:{type:"number"},
      errorClass:{type:"string"},
      confidence:{type:"number"},
      observationHash:{type:"string"}
    }
  }}
);

// --- Checkpoint Triple-Write 7-field mandatory ---
let checkpointSaved=false;
try{
  const mgr = new UltraCheckpointManager(runId);
  await mgr.ensureDir();
  const entry = {
    nodeId: result.node_id||node.id,
    agentId: node.agent||'executor',
    attempt: result.attempt||attempt||1,
    latency_ms: result.latency_ms||0,
    latency: result.latency_ms||0,
    tokens_est: result.tokens_est||200,
    tokens: result.tokens_est||200,
    status: result.status,
    errorClass: result.errorClass||null,
    confidence: result.confidence||0.9,
    observationHash: result.observationHash||result.artifact_path||'',
    runId,
    layer:3,
    stuck_detected: !!stuckInfo?.stuck,
    lens_used: stuckInfo?.lens||null,
    honest_lens: honestInfo ? { visibleAbandonments:true, noFake7of7:true } : null,
    early_exit: earlyExit.early||false,
    known_fix_applied: !!thisNodeFix,
    tempo: ':13'
  };
  await mgr.logNode(entry);
  // ensure triple-write handled by mgr (now patched to 7 dirs) — attempt extra saves for safety via legacy tripleWrite if method exists
  if(typeof mgr.save==='function'){
    await mgr.save({ dag_version:1, nodes:[{ id: entry.nodeId, status: entry.status, agent: entry.agentId }], last_node: entry.nodeId });
  }
  checkpointSaved=true;
}catch(e){ /* non-blocking */ }

// --- Router-2 + Recovery Ladder bounded ---
let routeDecision = { action:"continue" };
const sideEffect = classifySideEffect(node.title+' '+ (node.expected_artifact||''));
let recoveryAction=null;

if (result.status==="blocked" || result.blocked || result.status==="failed" || (result.critic_score!==undefined && result.critic_score<5)) {
  const fClass = result.errorClass|| (knownRemediation[node.id]?.failureClass) || 'TOOL_FAILURE';
  const replanCount = args.replanCount||0;
  recoveryAction = decideRecovery({
    nodeId: node.id,
    attempt: result.attempt||attempt||1,
    failureClass: fClass,
    sideEffectLevel: sideEffect.level,
    replanCount
  });

  // Honest lens for known nodes — do NOT infinite retry
  if(thisNodeFix && (result.attempt||attempt)>=2){
    recoveryAction = { action:'escalate', to:'human', reason:`honest early exit after 2 attempts for ${node.id}: ${thisNodeFix.reason} — fallback ${thisNodeFix.fix}`, step:5, honest:true, side_effect_guard: sideEffect.level>=2 };
  } else if(stuckInfo?.stuck){
    const remediation = getStuckRemediation(stuckInfo,{ nodeId: node.id });
    if(remediation.early_exit_after && (result.attempt||attempt)>=remediation.early_exit_after){
      routeDecision = { action:"escalate", reason:`early exit after ${remediation.early_exit_after} attempts lens=${remediation.lens} trigger=${stuckInfo.trigger} honest visible`, slice_from: node.id, lens: remediation.lens, honest_lens: remediation.honest_lens };
    } else {
      routeDecision = { action: recoveryAction.action==='retry'?'repair':'replan', reason: `stuck ${stuckInfo.trigger} -> 1 lens ${remediation.lens} ${remediation.suggestion.slice(0,300)}`, slice_from: node.id, lens: remediation.lens, failure_class: fClass, recovery_step: recoveryAction.step };
    }
  } else {
    routeDecision = recoveryAction.action==='escalate' ?
      { action:"escalate", reason: recoveryAction.reason, slice_from: node.id, failure_class: fClass, recovery_step: recoveryAction.step } :
      { action: recoveryAction.action==='retry' ? 'repair' : recoveryAction.action, reason: result.blocker_reason || result.summary, slice_from: node.id, failure_class: fClass, recovery_step: recoveryAction.step };
  }
}
if (result.new_dependency) routeDecision = { action:"inject", new_node: result.new_dependency };

return {
  node_result: { ...result, checkpoint_saved: checkpointSaved, stuck_info: stuckInfo||null, honest_lens: honestInfo||null, known_fix: thisNodeFix||null, early_exit: earlyExit },
  route_decision: routeDecision,
  recovery: recoveryAction,
  side_effect,
  stuck: stuckInfo,
  message: `Node ${node.id} ${result.status} — ${result.summary.slice(0,120)} ${stuckInfo?.stuck?`[stuck:${stuckInfo.trigger} lens:${stuckInfo.lens} honest]`:`[healthy]`} ${checkpointSaved?'✓triple':'!ckpt'}`
};
