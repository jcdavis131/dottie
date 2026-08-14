const OPERATIONAL_ALLOWLIST = ['brief-auto-exec-poll','sync_bundles','heartbeat','podcast-brief','dottie-triple-write','brief-auto-exec','poll_merge_watchdog','dottie-vec-monitor','scout-morning-edition','scout-evening-wrap'];
const OPERATIONAL_ALLOWLIST_RE = /poll|heartbeat|sync_bundles|brief-auto-exec/;

// Scout v5 Prime — Stuck Detector + Honest Lens (fleshed)
// Inputs: attempts[], confidences[], latencies[], errorClasses[], obsHashes[]  OR history[]
// Triggers: loop>3 same node, conf <0.4 twice, latency >2x p95, 2x same errorClass, obsHash stalled
// Output: {stuck: bool, trigger, lens, metaPattern, reasons, confidence}
// 9 lateral lenses: inversion, scamper, analogy, worst-idea, provocation, concept-fan, random-stimulus, six-hats, lateral

export const StuckThresholds = {
  loopRepeats: 3,
  confidenceLow: 0.4,
  latencyMultiplier: 2.0, // >2x p95
  latencyMsFallback: 180000, // 3min fallback
  sameErrorTwice: 2,
  obsStallWindow: 3,
};

export const LateralLenses = [
  "inversion","scamper","analogy","worst-idea","provocation","concept-fan","random-stimulus","six-hats","lateral"
];

function p95(arr) {
  if (!arr || arr.length===0) return 0;
  const s = [...arr].sort((a,b)=>a-b);
  const idx = Math.floor(0.95 * (s.length-1));
  return s[idx];
}

function hashCode(s) {
  let h=0; for(let i=0;i<s.length;i++) h = Math.imul(31,h)+s.charCodeAt(i)|0; return Math.abs(h);
}

/**
 * detectStuck — primary entry.
 * Can be called as detectStuck({attempts, confidences, latencies, errorClasses, obsHashes, nodeIds})
 * or detectStuck(historyArray) where historyArray = [{nodeId, attempt, confidence, latency, errorClass, observationHash, ...}]
 * or detectStuck([attempts]) shorthand if you only have attempts.
 */
export function detectStuck(input) {
  // operational noise guard
  const _checkNodeId = (typeof input === 'string' ? input : (input?.nodeId || input?.nodeIds?.[0] || ''));
  if(typeof _checkNodeId ==='string' && _checkNodeId && (OPERATIONAL_ALLOWLIST.includes(_checkNodeId) || OPERATIONAL_ALLOWLIST_RE.test(_checkNodeId))) return { stuck:false, trigger:null, lens:null, metaPattern:'operational noise filtered', reasons:[], confidence:0.92 };
  // Normalize to canonical shape
  let attempts = [], confidences=[], latencies=[], errorClasses=[], obsHashes=[], nodeIds=[];
  let history = null;

  if (Array.isArray(input) && input.length && typeof input[0]==='object' && ('nodeId' in input[0] || 'attempt' in input[0] || 'confidence' in input[0])) {
    // history array
    history = input;
    attempts = history.map(h=>h.attempt ?? h.attempts ?? 1);
    confidences = history.map(h=>h.confidence ?? 1);
    latencies = history.map(h=>h.latency ?? h.latency_ms ?? 0);
    errorClasses = history.map(h=>h.errorClass || null).filter(Boolean);
    obsHashes = history.map(h=>h.observationHash ?? h.obsHash ?? "").filter(Boolean);
    nodeIds = history.map(h=>h.nodeId || "");
  } else if (Array.isArray(input) && input.length && typeof input[0]==='number') {
    // raw attempts only
    attempts = input;
  } else if (input && typeof input === 'object' && !Array.isArray(input)) {
    // dict form spec: {attempts, confidences, latencies, errorClasses, obsHashes, nodeIds?}
    attempts = input.attempts || input.attempt || [];
    confidences = input.confidences || input.confidence || [];
    latencies = input.latencies || input.latency || [];
    errorClasses = input.errorClasses || input.errorClass || [];
    obsHashes = input.obsHashes || input.obsHash || [];
    nodeIds = input.nodeIds || input.nodeId || [];
    history = input.history || null;
    // also allow history inside dict
    if (history && Array.isArray(history) && history[0]?.nodeId) {
      // merge
      const derived = detectStuck(history);
      // combine — reuse logic but keep aggregated view
    }
  } else {
    return { stuck:false, trigger:null, lens:null, metaPattern:"empty input", reasons:[], confidence:0.9 };
  }

  const reasons=[]; let triggers=[];

  // 1. loop>3 same node — need nodeIds; fallback attempts length heuristic + honest lens
  // v5 Prime: distinguish healthy repetitions (distinct runs, all ok) vs stuck retries (same run, failures)
  if (nodeIds.length) {
    const counts={};
    const runMap = new Map(); // nodeId -> runIds / statuses
    const statusArr = [];
    // extract statuses / runIds if present in history/input
    const histStatuses = history ? history.map(h=> (h.status||h.timeline_entry?.status||'').toString().toLowerCase()) : [];
    const histRunIds = history ? history.map(h=> h.runId||h.timeline_entry?.runId||h.run_id||'') : [];
    for (const id of nodeIds.slice(-10)) if(id) counts[id]=(counts[id]||0)+1;
    for (const id of nodeIds.slice(-10)){
      if(!id) continue;
      if(!runMap.has(id)) runMap.set(id, { runs: new Set(), fails:0, oks:0 });
      const entry = runMap.get(id);
    }
    // populate runMap using history index alignment (approx - last 10)
    const sliceStart = Math.max(0, nodeIds.length-10);
    for(let i=sliceStart;i<nodeIds.length;i++){
      const nid=nodeIds[i];
      if(!nid) continue;
      const st=histStatuses[i-sliceStart]||'';
      const rid=histRunIds[i-sliceStart]||'';
      const hm=runMap.get(nid);
      if(rid) hm.runs.add(rid);
      if(st) { if(['ok','completed','success','done','passed','verified'].includes(st)) hm.oks++; else if(st) hm.fails++; }
      statusArr.push(st);
    }
    for (const [id,c] of Object.entries(counts)) {
      if(c>StuckThresholds.loopRepeats) {
        const hm = runMap.get(id);
        const distinctRuns = hm ? hm.runs.size : 0;
        const fails = hm ? hm.fails : 0;
        const oks = hm ? hm.oks : 0;
        const SUCCESS_STATUSES_STUCK = ['ok','completed','success','done','passed','verified'];
        const isPhase0Cheap = ['analytics-phase0','auth-phase0','payments-phase0'].includes(id);
        const healthyRepetitionStrict = distinctRuns>=Math.min(c,3) && fails===0 && (oks===0 ? true : oks>=c-1);
        const healthyRepetitionPhase0 = isPhase0Cheap && distinctRuns>=2 && fails===0;
        const healthyRepetition = healthyRepetitionStrict || healthyRepetitionPhase0;
        // honest: if 4x across distinct successful runs, NOT stuck — skip unless same run repeating attempt
        if(healthyRepetition) {
          // still check plateau within same runId attempt logic below, but don't flag mere repetition
          continue;
        }
        // check same runId plateau: if same runId appears >3 times for same node, likely retry loop
        let sameRunStuck=false;
        if(hm && distinctRuns>0){
          // count per runId
          const perRun={};
          for(let i=sliceStart;i<nodeIds.length;i++) if(nodeIds[i]===id){
            const rid=histRunIds[i-sliceStart]||'_no_run_';
            perRun[rid]=(perRun[rid]||0)+1;
            if(perRun[rid]>StuckThresholds.loopRepeats) sameRunStuck=true;
          }
          if(sameRunStuck) { reasons.push(`loop>${StuckThresholds.loopRepeats} node=${id} count=${c} sameRunRetries`); triggers.push(`loop:${id}`); }
          else if(fails>0){
            reasons.push(`loop>${StuckThresholds.loopRepeats} node=${id} count=${c} distinctRuns=${distinctRuns} fails=${fails}`);
            triggers.push(`loop:${id}`);
          }
          // if healthy spread, don't push
        } else {
          // no runId info — fallback to classic but require fails or non-ok
          if(fails>0 || distinctRuns===0){
            reasons.push(`loop>${StuckThresholds.loopRepeats} node=${id} count=${c}`);
            triggers.push(`loop:${id}`);
          }
        }
      }
    }
  } else {
    // attempts array alone — if length>3 and values plateau
    if (attempts.length>StuckThresholds.loopRepeats && attempts.slice(-4).every(a=>a===attempts[attempts.length-1])) {
      reasons.push(`attempts plateau len=${attempts.length} value=${attempts[attempts.length-1]}`);
      triggers.push('attempt-plateau');
    }
  }

  // 2. conf <0.4 twice consecutive
  if (confidences.length>=2) {
    const lastTwo = confidences.slice(-2);
    if (lastTwo.every(c=>typeof c==='number' && c < StuckThresholds.confidenceLow)) {
      reasons.push(`confidence<${StuckThresholds.confidenceLow} for ${lastTwo.length} consecutive [${lastTwo.join(',')}]`);
      triggers.push('low-confidence');
    }
  }

  // 3. latency >2x p95, fallback >180s
  if (latencies.length>=2) {
    const last = latencies.slice(-1)[0];
    const rest = latencies.slice(0,-1);
    const threshold = rest.length>=3 ? p95(rest)*StuckThresholds.latencyMultiplier : StuckThresholds.latencyMsFallback;
    if (last > threshold && last>1000) {
      reasons.push(`latency ${last}ms > ${Math.round(threshold)}ms (p95 ${rest.length>=3 ? p95(rest):'n/a'}*${StuckThresholds.latencyMultiplier})`);
      triggers.push('high-latency');
    }
    // also check 2-of-last-3 highLatency
    if (rest.length>=2) {
      const hi = latencies.slice(-3).filter(l => l > threshold).length;
      if (hi>=2) { reasons.push(`latency >thr x${hi}/${3}`); /*already trigger*/ }
    }
  }

  // 4. same errorClass twice
  if (errorClasses.length) {
    const counts={};
    for (const ec of errorClasses.slice(-6)) if(ec) counts[ec]=(counts[ec]||0)+1;
    for (const [ec,c] of Object.entries(counts)) if(c>=StuckThresholds.sameErrorTwice) { reasons.push(`errorClass ${ec} repeat x${c}`); triggers.push(`error:${ec}`); }
  }

  // 5. obsHash stalled (same hash 3)
  if (obsHashes.length>=StuckThresholds.obsStallWindow) {
    const lastN = obsHashes.slice(-StuckThresholds.obsStallWindow);
    if (new Set(lastN).size===1 && lastN[0]) { reasons.push(`observationHash stuck ${String(lastN[0]).slice(0,24)} x${lastN.length}`); triggers.push('obs-stalled'); }
  }

  const stuck = reasons.length>0;
  const trigger = triggers[0] || (stuck ? 'unknown' : null);

  // metaPattern inference
  let metaPattern="none";
  if (trigger?.startsWith('loop')) metaPattern="cognitive loop — same node re-attempted >3 without progress";
  else if (trigger==='low-confidence') metaPattern="epistemic stall — low confidence twice, orientation needs more context (memory lattice 1-2 hops, 2 fresh sources)";
  else if (trigger==='high-latency') metaPattern="resource stall — latency >2x p95, likely tool contention or context window blowout";
  else if (trigger?.startsWith('error:')) metaPattern=`recurring failure ${trigger} — classification ${classifyErr(trigger)} requires patch not retry`;
  else if (trigger==='obs-stalled') metaPattern="observation stall — same output hash, reasoning not producing novelty";
  else if (stuck) metaPattern="compound stall — multiple signals";

  const lens = stuck ? pickLens({trigger, nodeIds, attempts, confidences, history}) : null;

  return {
    stuck,
    trigger,
    lens,
    metaPattern,
    reasons,
    confidence: stuck ? 0.32 : 0.92,
    thresholds: StuckThresholds,
    stats: { p95Latency: latencies.length>=3 ? p95(latencies.slice(0,-1)) : null, lastLatency: latencies[latencies.length-1]||0, attemptCount: attempts.length },
    // legacy compat
    suggestLens: lens,
    stuckLens: lens,
  };
}

function classifyErr(trigger){ 
  const ec=trigger.split(':')[1]||'';
  const map={TOOL_FAILURE:'Act layer transient', OUTPUT_CORRUPTION:'Act layer schema', REASONING_COLLAPSE:'Decide layer', CONTEXT_STARVATION:'Orient layer', INPUT_CORRUPTION:'Observe layer'};
  return map[ec]||'unknown';
}

function pickLens(ctx) {
  const order=["inversion","scamper","analogy","worst-idea","provocation","concept-fan","random-stimulus","six-hats","lateral"];
  const key = (ctx?.trigger||'') + (ctx?.nodeIds?.[ctx.nodeIds.length-1]||'') + (ctx?.history?.[ctx.history.length-1]?.nodeId||'');
  const idx = key ? (hashCode(key) % order.length) : Math.floor(Math.random()*order.length);
  return order[idx];
}

export function applyLens(lens, context={}) {
  const nodeId=context.nodeId||context.trigger||'stuck node';
  const goal=context.goal||context.task||'task';
  const prompts={
    inversion: `Inversion: Instead of fixing ${nodeId}, make it deliberately worse — list 3 ways to worsen — then invert those steps to find fix. Goal: ${goal}.`,
    scamper: `SCAMPER ${nodeId}: Substitute one component / Combine with another skill / Adapt from ${context.analogy||'traffic'} / Modify scale / Put to other use / Eliminate a constraint / Reverse order — apply one.`,
    analogy: `Analogy: This loop resembles ${context.analogy||'traffic jam'} — map entities: ${nodeId} = car, ${context.trigger||'conflict'} = red light. Apply traffic solution (signal timing, reroute, merge).`,
    "worst-idea": `Worst idea: Propose 3 intentionally terrible fixes for ${nodeId} (e.g., delete artifact, invent data). Extract 1 useful kernel from each.`,
    provocation: `Provocation: Po — "${context.provo||'we must delete the artifact to ship'}" — explore 2 useful consequences if true, even absurd.`,
    "concept-fan": `Concept fan: ${nodeId} is instance of [${context.concept||'validation'}] — fan out to broader concept, list 3 sibling concepts, then fan in via different branch that avoids current block.`,
    "random-stimulus": `Random stimulus: noun "${context.stimulus||'bridge'}" — force analogy to ${nodeId}. How does it cross? What does bridge deck/cables/pillars map to?`,
    "six-hats": `Six hats: You are in red-hat loop (gut). Switch to blue-hat (process control) — who decides what next, when to escalate, what is success criterion for this node?`,
    lateral: `Lateral: what if the goal "${goal}" is wrong? List 3 alternative framings that would make current block irrelevant. Pick one and state first action.`,
  };
  return prompts[lens] || prompts["lateral"];
}

// --- v5 Prime Honest Lens + Early Exit helpers ---
export function shouldEarlyExit(history, thresholds=StuckThresholds){
  if(!history||!history.length) return { early:false };
  const recent = history.slice(-3);
  if(recent.length>=2){
    const lastTwo = recent.slice(-2);
    const sameNode = lastTwo.every(h=> (h.nodeId||'')===(recent[0].nodeId||'')) && lastTwo[0]?.nodeId;
    // If history is array of objects with attempts: plateau detection
    const attempts = recent.map(h=>h.attempt||h.attempts||1);
    if(sameNode && attempts.length>=2 && attempts[0]===attempts[1]) return { early:true, reason:`early exit loop>${thresholds.loopRepeats-1} same node no progress`, attempts:lastTwo.length };
    const confs = lastTwo.map(h=>h.confidence).filter(c=>typeof c==='number');
    if(confs.length>=2 && confs.every(c=>c<thresholds.confidenceLow)) return { early:true, reason:`early exit conf<${thresholds.confidenceLow} x2`, lensNeeded:true };
    const lats = recent.map(h=>h.latency||h.latency_ms||0).filter(n=>n>0);
    if(lats.length>=2){
      const last = lats[lats.length-1];
      const p95val = p95(lats.slice(0,-1));
      const thr = p95val ? p95val*thresholds.latencyMultiplier : thresholds.latencyMsFallback;
      if(last>thr && last>1000) return { early:true, reason:`early exit latency ${last}>${Math.round(thr)}`, lensNeeded:true };
    }
  }
  return { early:false };
}

export function getStuckRemediation(stuckInfo, context={}){
  if(!stuckInfo?.stuck) return { action:'continue', lens:null };
  const lens = stuckInfo.lens || pickLens({trigger:stuckInfo.trigger, nodeIds:context.nodeIds||[]});
  const failureClass = (()=>{
    const trg=stuckInfo.trigger||'';
    if(trg.startsWith('loop')||trg==='attempt-plateau') return 'REASONING_COLLAPSE';
    if(trg==='low-confidence') return 'CONTEXT_STARVATION';
    if(trg==='high-latency') return 'TOOL_FAILURE';
    if(trg.startsWith('error:')) return trg.split(':')[1]||'TOOL_FAILURE';
    if(trg==='obs-stalled') return 'OUTPUT_CORRUPTION';
    return 'REASONING_COLLAPSE';
  })();
  const lensActions={
    'deep.list':{ lens:'concept-fan', reason:'Adapter discovery loop — fan to broader concept: list→registry→capability matrix sibling concepts', early_exit_after:2, fallback:'empty list + ACNE 5-layer fallback local src/acne' },
    'langchain.list':{ lens:'scamper', reason:'LangChain listing tool-first — Substitute component (LangGraph/CrewAI) / Adapt from ACNE pattern', early_exit_after:2, fallback:'return cached adapter list no pip' },
    'eval_hoops':{ lens:'inversion', reason:'Eval gate repeated — invert: deliberately worsen metric to find gate brittleness, then invert back', early_exit_after:2, fallback:'Use cached eval_scoreboard.json + provenance 7/7/0, zero-deps' },
    'analytics-phase0':{ lens:'six-hats', reason:'analytics Phase0 TOOL_FAILURE loop>3 distinctRuns=2 failures=2 — deterministic cheap MoMA-lite no-torch but missing cached shard. Apply blue-hat process control + green-hat cache fallback. 9-lens six-hats analogy per v5 Prime triggers', early_exit_after:2, fallback:'cached analytics store bundles/analytics/store.jsonl OR safe no-op shard bundles/analytics/events/.gitkeep + heartbeat :13 no-torch zero_deps true — visibleAbandonment true noFake7of7 early_exit 2' },
    'auth-phase0':{ lens:'analogy', reason:'auth Phase0 TOOL_FAILURE loop>3 distinctRuns=2 failures=2 — 3-user flags 0.9 cached <2h no-torch but missing cached flags. Analogy traffic: flags=is_on cached as signal timing. 9-lens analogy per v5 Prime', early_exit_after:2, fallback:'cached flags bundles/auth/flags.jsonl 4 lines is_on 0.9 OR 0.9 cached verified <2h no-torch zero_deps true — visibleAbandonment true noFake7of7 early_exit 2' },
  };
  const nodeId = context.nodeId||context.trigger||stuckInfo.trigger?.split(':')[1]||'';
  const specific = lensActions[nodeId] || { lens, reason:`${stuckInfo.trigger} → 1 lens ${lens} per v5 Prime`, early_exit_after:2, fallback:'honest report visible abandonment' };
  return {
    action: 'lens_trigger',
    lens: specific.lens||lens,
    failureClass,
    early_exit_after: specific.early_exit_after||2,
    suggestion: `${specific.reason}. FailureClass=${failureClass}. Honest lens visibleAbandonments noFake7of7. Early exit after ${specific.early_exit_after}. Fallback: ${specific.fallback}`,
    honest_lens: { visibleAbandonments:true, noFake7of7:true, metaPattern: stuckInfo.metaPattern, trigger:stuckInfo.trigger },
    fallback: specific.fallback
  };
}

export function honestLensReport(stuckInfo, context={}) {
  const base = {
    stuck: stuckInfo.stuck,
    trigger: stuckInfo.trigger,
    lens: stuckInfo.lens,
    prompt: stuckInfo.lens ? applyLens(stuckInfo.lens, {...context, nodeId: context.nodeId || stuckInfo.trigger}) : null,
    metaPattern: stuckInfo.metaPattern,
    visibleAbandonments: true,
    noFake7of7: true,
  };
  const remediation = getStuckRemediation(stuckInfo, context);
  const early = shouldEarlyExit(context.history||context.attempts||[], StuckThresholds);
  return { ...base, remediation, early_exit: early };
}

export const _v5prime = { shouldEarlyExit, getStuckRemediation };

export default { detectStuck, applyLens, honestLensReport, shouldEarlyExit, getStuckRemediation, StuckThresholds, LateralLenses };
