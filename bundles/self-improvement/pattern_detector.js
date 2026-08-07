/**
 * pattern_detector.js — SOTA Self-Improvement Pattern Detector v3.3
 * Zero deps, Node.js stdlib only
 * Reads bundles/ultra/runs/metrics.jsonl + timeline.jsonl + self-improvement/metrics.json
 * Detects: repeat fix, high token waste, low verification, slow tempo, operational noise, stuck loops
 * Exports detect() for require, CLI for cron
 *
 * Usage: node pattern_detector.js --days 7 --threshold 3
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const HOME = os.homedir();
const WORKSPACE = path.join(HOME,'workspace');
const BUNDLES = path.join(WORKSPACE,'bundles');
const ULTRA_RUNS = path.join(BUNDLES,'ultra','runs');
const SELF_DIR = path.join(BUNDLES,'self-improvement');
const OPERATIONAL_ALLOWLIST = ['brief-auto-exec-poll','sync_bundles','heartbeat','podcast-brief','dottie-triple-write','brief-auto-exec','poll_merge_watchdog','dottie-vec-monitor','scout-morning-edition','scout-evening-wrap'];
const OPERATIONAL_ALLOWLIST_RE = /poll|heartbeat|sync_bundles|brief-auto-exec/;


function parseArgs(){
  const a = process.argv.slice(2);
  const o={days:7,threshold:3,dry:false};
  for(let i=0;i<a.length;i++){
    if(a[i]==='--days') o.days=parseInt(a[i+1],10)||7;
    if(a[i]==='--threshold') o.threshold=parseInt(a[i+1],10)||3;
    if(a[i]==='--dry') o.dry=true;
  }
  return o;
}

function listRunDirs(days){
  if(!fs.existsSync(ULTRA_RUNS)) return [];
  const cutoff = Date.now() - days*24*60*60*1000;
  try{
    return fs.readdirSync(ULTRA_RUNS).map(n=>path.join(ULTRA_RUNS,n))
      .filter(p=>{
        try{
          const st=fs.statSync(p);
          if(!st.isDirectory()) return false;
          return st.mtimeMs >= cutoff;
        }catch{return false}
      });
  }catch{return []}
}

function readJsonlFiles(dir){
  const out=[];
  const files=['timeline.jsonl','metrics.jsonl','checkpoint.json'];
  for(const f of files){
    const p=path.join(dir,f);
    try{
      if(!fs.existsSync(p)) continue;
      const txt=fs.readFileSync(p,'utf8');
      const lines=txt.split('\n').filter(Boolean);
      for(const line of lines){
        try{ out.push({file:p, data:JSON.parse(line), raw:line}); }catch{ out.push({file:p, data:null, raw:line}); }
      }
    }catch{}
  }
  return out;
}

function detect({days=7, threshold=3}={}){
  const runDirs = listRunDirs(days);
  let allEntries=[];
  for(const d of runDirs){
    allEntries.push(...readJsonlFiles(d));
  }
  // also self-improvement metrics
  const selfMetricsPath = path.join(SELF_DIR,'metrics.json');
  let selfMetrics={};
  try{ if(fs.existsSync(selfMetricsPath)) selfMetrics=JSON.parse(fs.readFileSync(selfMetricsPath,'utf8')); }catch{}

  const patterns=[];

  // helper counters
  const errorClassCount = new Map();
  const nodeRetryCount = new Map();
  let totalLatency=0, totalTokens=0, count=0, lowScores=[];
  let operationalNoise=0;

  for(const e of allEntries){
    const d=e.data||{};
    const ec = d.errorClass || d.error || '';
    const nodeId = d.nodeId || d.node_id || 'unknown';
    const latency = d.latency || d.latency_ms || 0;
    const tokens = d.tokens || 0;
    const status = d.status||'';
    if(ec && ec!=='none'){
      errorClassCount.set(ec, (errorClassCount.get(ec)||0)+1);
    }
    nodeRetryCount.set(nodeId, (nodeRetryCount.get(nodeId)||0)+1);
    totalLatency+= (typeof latency==='number'?latency:0);
    totalTokens+= (typeof tokens==='number'?parseInt(tokens):0);
    if(typeof d.score==='number' && d.score<7.5) lowScores.push({nodeId, score:d.score, file:e.file});
    if(status==='suppressed_dup' || (e.raw && e.raw.includes('state.json'))) operationalNoise++;
    count++;
  }

  const avgLatency = count? totalLatency/count : 0;
  const avgTokens = count? totalTokens/count : 0;

  // 1. repeat fix — same errorClass >3x
  for(const [ec,c] of errorClassCount.entries()){
    if(c>=threshold){
      patterns.push({
        type:'repeat_fix',
        severity: c>=5?'high':'medium',
        count:c,
        errorClass:ec,
        examples: allEntries.filter(x=> (x.data?.errorClass===ec)).slice(0,3).map(x=>x.raw.slice(0,200)),
        suggestion:`Add resilient handler for ${ec} in workflow or add critic rule. Consider router retry->patch->replan.`,
        ice_score: Math.min(0.9, 0.4 + c*0.1),
        proposed_action:'workflow_patch'
      });
    }
  }

  // 2. stuck loops — same nodeId >3 (allowlist excludes expected operational poller noise)
  // v5 Prime honest: loop>3 only if failures / plateau / low-conf / high-latency, not healthy repeat runs
  // Build detailed per-node entries for honest lens
  const nodeDetail = new Map(); // nodeId -> entries
  for(const e of allEntries){
    const nid = e.data?.nodeId || e.data?.node_id || 'unknown';
    if(!nodeDetail.has(nid)) nodeDetail.set(nid, []);
    nodeDetail.get(nid).push(e.data || {});
  }

  for(const [nodeId,c] of nodeRetryCount.entries()){
    if(OPERATIONAL_ALLOWLIST.includes(nodeId) || OPERATIONAL_ALLOWLIST_RE.test(nodeId)) continue;
    if(c>=4 && nodeId!=='unknown'){
      const details = nodeDetail.get(nodeId) || [];
      const runIds = new Set(details.map(d=>d.runId||'').filter(Boolean));
      const statuses = details.map(d=> (d.status||'').toString().toLowerCase());
      const failures = statuses.filter(s=> !['ok','completed','success','done','passed'].includes(s));
      const errorClasses = details.map(d=>d.errorClass).filter(ec=> ec && ec!=='none');
      const attempts = details.map(d=> d.attempt||1);
      const latencies = details.map(d=> d.latency_ms||d.latency||0).filter(n=> typeof n==='number');
      const confidences = details.map(d=> d.confidence).filter(n=> typeof n==='number');
      const obsHashes = details.map(d=> d.observationHash||d.obsHash||'').filter(Boolean);

      const distinctRuns = runIds.size;
      const isHealthyRepetition = failures.length===0 && errorClasses.length===0 && distinctRuns>=Math.min(c,3) && details.every(d=>['ok','completed','success','done'].includes((d.status||'ok').toLowerCase()));
      if(isHealthyRepetition){
        // Not a stuck loop — healthy repeated use across distinct runs (e.g., deep.list 4x over 7d each ok)
        continue;
      }

      // Failure taxonomy per AGENTS.md
      let failureClass = 'none';
      if(errorClasses.length>=2) failureClass = errorClasses[0]||'TOOL_FAILURE';
      else if(failures.length>=2) failureClass = 'TOOL_FAILURE';
      else if(confidences.length>=2 && confidences.slice(-2).every(v=>v<0.4)) failureClass = 'CONTEXT_STARVATION';
      else if(latencies.length>=2){
        const last = latencies[latencies.length-1];
        const rest = latencies.slice(0,-1);
        const p95 = (arr)=>{ if(!arr.length) return 0; const s=[...arr].sort((a,b)=>a-b); return s[Math.floor(0.95*(s.length-1))]; };
        const thr = rest.length>=3 ? p95(rest)*2.0 : 180000;
        if(last>thr && last>1000) failureClass = 'TOOL_FAILURE';
      }
      if(failureClass==='none' && isHealthyRepetition) continue;
      if(failureClass==='none' && failures.length===0) {
        // still healthy — skip unless same runId repeated attempts
        const sameRunRepeat = details.reduce((acc,d)=>{ const r=d.runId||''; acc[r]=(acc[r]||0)+1; return acc; }, {});
        const maxSameRun = Math.max(...Object.values(sameRunRepeat),0);
        if(maxSameRun<4) continue;
        failureClass='REASONING_COLLAPSE';
      }

      // v5 Prime triggers: loop>3 conf<0.4 latency>thr -> 1 lens
      const triggers=[];
      if(c>3) triggers.push(`loop>${3}`);
      if(confidences.length>=2 && confidences.slice(-2).every(v=>typeof v==='number' && v<0.4)) triggers.push('conf<0.4 x2');
      if(latencies.length>=2){
        const last=latencies[latencies.length-1]; const rest=latencies.slice(0,-1);
        const p95=(arr)=>{ if(!arr.length) return 0; const s=[...arr].sort((a,b)=>a-b); return s[Math.floor(0.95*(s.length-1))]; };
        const thr=rest.length>=3 ? p95(rest)*2 : 180000;
        if(last>thr && last>1000) triggers.push(`latency>${Math.round(thr)}ms`);
      }
      if(errorClasses.length>=2) triggers.push(`error:${errorClasses[0]} x${errorClasses.length}`);
      if(obsHashes.length>=3 && new Set(obsHashes.slice(-3)).size===1) triggers.push('obs-stalled');

      // pick lens
      const lenses=["inversion","scamper","analogy","worst-idea","provocation","concept-fan","random-stimulus","six-hats","lateral"];
      const hash=(s)=>{let h=0; for(let i=0;i<s.length;i++) h=Math.imul(31,h)+s.charCodeAt(i)|0; return Math.abs(h); };
      const lens = lenses[hash(nodeId+triggers.join(',')) % lenses.length];

      patterns.push({
        type:'stuck_loop',
        severity: failures.length>=2||errorClasses.length>=2?'high':'medium',
        count:c,
        nodeId,
        failureClass,
        triggers,
        lens,
        honest: true,
        early_exit: c>=6,
        examples:[`node ${nodeId} retried ${c} times in ${days}d distinctRuns=${distinctRuns} failures=${failures.length} err=${errorClasses.length} trigger=${triggers[0]||'loop'} lens=${lens}`],
        suggestion:`Stuck Detector v5 Prime: ${triggers.join(', ')||'loop>3'} -> 1 lens ${lens}. FailureClass=${failureClass}. ${failureClass==='CONTEXT_STARVATION'?'Expand memory lattice 1-2 hops +2 sources':failureClass==='INPUT_CORRUPTION'?'Re-fetch input + validate schema':failureClass==='TOOL_FAILURE'?'Retry alt tool sandbox 30s×2 + early exit after 2':'Patch prompt reduce scope single-resp'} Honest lens visibleAbandonment noFake7of7.`,
        ice_score: 0.75,
        proposed_action:'stuck_detector_upgrade',
        remediation: {
          lens,
          failureClass,
          early_exit_after: 2,
          honest_lens: { visibleAbandonments:true, noFake7of7:true, metaPattern: triggers.join(',')||'loop' }
        }
      });
    }
  }

  // 3. high token waste
  if(avgTokens> 25000 && count>5){
    patterns.push({
      type:'high_token_waste',
      severity:'medium',
      count: Math.round(avgTokens),
      avg_tokens: avgTokens,
      examples:[`avg ${Math.round(avgTokens)} tokens/run over ${count} runs`],
      suggestion:`Compress GraphRAG to 600 token budget, earlyExit delta 0.3, MoMA-lite tier cheaper.`,
      ice_score:0.6,
      proposed_action:'verification_economics_tweak'
    });
  }

  // 4. low verification
  if(lowScores.length >= threshold){
    patterns.push({
      type:'low_verification',
      severity: lowScores.length>5?'high':'medium',
      count: lowScores.length,
      low_score_avg: lowScores.reduce((s,x)=>s+x.score,0)/lowScores.length,
      examples: lowScores.slice(0,3).map(x=>`${x.nodeId} scored ${x.score}`),
      suggestion:`Tighten critic: raise threshold to 8.0, fix once if <8, single enforcement point verifier-with-budget.js`,
      ice_score:0.7,
      proposed_action:'critic_recalibration'
    });
  }

  // 5. slow tempo
  if(avgLatency> 45000 && count>3){
    patterns.push({
      type:'slow_tempo',
      severity:'medium',
      count: count,
      avg_latency_ms: avgLatency,
      examples:[`avg latency ${Math.round(avgLatency)}ms over ${count} runs`],
      suggestion:`Optimize pacing filter max3/4, tempo :13, event-driven > polling, reduce 7-field log bloat.`,
      ice_score:0.55,
      proposed_action:'pacing_filter_tune'
    });
  }

  // 6. operational noise >80%
  if(count>0 && operationalNoise / count > 0.8){
    patterns.push({
      type:'operational_noise',
      severity:'low',
      count: operationalNoise,
      ratio: operationalNoise/count,
      examples:[`${operationalNoise}/${count} entries are operational noise (state.json / suppressed_dup)`],
      suggestion:`Filter operational noise from pattern detection, reduce confidence to <0.6 for ops patterns. Keep core signals clean.`,
      ice_score:0.4,
      proposed_action:'filter_operational_noise'
    });
  }

  // ICE ranking
  patterns.sort((a,b)=> b.ice_score - a.ice_score);
  const top = patterns.slice(0,5);

  return {
    scanned_runs: runDirs.length,
    scanned_entries: count,
    days,
    threshold,
    totalLatency: Math.round(totalLatency),
    avgLatency: Math.round(avgLatency),
    avgTokens: Math.round(avgTokens),
    operationalNoise,
    lowScoresCount: lowScores.length,
    patterns: top,
    all_patterns_raw_count: patterns.length,
    self_metrics_last_run: selfMetrics.last_run||null,
    next_step: top.length ? `Top ICE ${top[0].type} -> ${top[0].proposed_action}` : 'No strong patterns — continue monitoring'
  };
}

function main(){
  const opts=parseArgs();
  const result=detect(opts);
  const outPath = path.join(SELF_DIR,'metrics.json');
  try{
    let prev={};
    if(fs.existsSync(outPath)) prev=JSON.parse(fs.readFileSync(outPath,'utf8'));
    prev.last_run = new Date().toISOString();
    prev.detections_last_7d = result.patterns.length;
    prev.avg_latency = result.avgLatency;
    prev.avg_tokens = result.avgTokens;
    prev.operational_ratio = result.scanned_entries? result.operationalNoise/result.scanned_entries : 0;
    prev.candidates = result.patterns;
    fs.writeFileSync(outPath, JSON.stringify(prev,null,2));
  }catch{}

  console.log(JSON.stringify(result,null,2));
  return result;
}

if(require.main===module){ main(); }

module.exports = { detect };
