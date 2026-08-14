// @ts-nocheck
"use client";
/**
 * AgentConductorPanel — polished thin UI
 * Sticky 40px, purely presentational, no raw logs in prod.
 * 5 tabs: Dashboard | Guardrails | Feedback | Scratchpad | Todos
 * Pro designer + UX research swarm: tight, calm, consistent, everyday language.
 */

import React, { useEffect, useState, useRef, useCallback } from 'react';

let daemonCache: any = null;
function safeGetDaemon() {
  if (daemonCache) return daemonCache;
  try {
    const mod = require('../acd/daemon' as any);
    const fn = mod.getDaemon;
    if (fn) { daemonCache = fn(); return daemonCache; }
  } catch {}
  try {
    const { getDaemon } = require('../acd/daemon');
    daemonCache = getDaemon();
    return daemonCache;
  } catch {}
  return null;
}
function safeGetModules() {
  try {
    const g = require('../acd/guardrails');
    const f = require('../acd/feedback');
    const sp = require('../acd/scratchpad');
    const td = require('../acd/todolist');
    return { guardrails: g?.getGuardrails?.(), feedback: f?.getFeedbackHub?.(), scratch: sp?.getScratchpad?.(), todo: td?.getTodoList?.() };
  } catch { return {} as any; }
}

type NavTab = 'Dashboard'|'Guardrails'|'Feedback'|'Scratchpad'|'Todos';
const NAV: NavTab[] = ['Dashboard','Guardrails','Feedback','Scratchpad','Todos'];

export default function AgentConductorPanel({ tandem = false, pairCode }: { tandem?: boolean; pairCode?: string } = {}) {
  const [active, setActive] = useState<NavTab>('Dashboard');
  const [snap, setSnap] = useState<any>(null);
  const [agents, setAgents] = useState<any[]>([
    { id:'agt_claude_refactor', host:'devserver-A', task:'refactor auth', status:'running' },
    { id:'agt_codex_api', host:'devserver-A', task:'scaffold new API layer', status:'running' },
  ]);
  const [hosts] = useState(['devserver-A','devserver-B','devserver-C']);
  const [approvalMode, setApprovalMode] = useState<'auto'|'manual'>('auto');
  const [yubiTouched, setYubiTouched] = useState(false);
  const [guardList, setGuardList] = useState<any[]>([]);
  const [fbList, setFbList] = useState<any[]>([]);
  const [scratchEntries, setScratchEntries] = useState<any[]>([]);
  const [todos, setTodos] = useState<any[]>([]);
  const [todoInput, setTodoInput] = useState('');
  const [scratchInput, setScratchInput] = useState('');
  const [feedbackMsg, setFeedbackMsg] = useState('');
  const [tandemState, setTandemState] = useState<{ paired:boolean; code?:string; wireBadge?:string; hash6?:string; pwaBadge?:string }>({ paired:false, code: pairCode });
  const confettiRef = useRef<HTMLDivElement>(null);

  const getHash6 = useCallback((s:string)=>{
    let h = 2166136261;
    const buf = new TextEncoder().encode(s);
    for(let i=0;i<buf.length;i++){ h ^= buf[i]; h = Math.imul(h, 16777619); }
    return (h>>>0).toString(16).padStart(8,'0').slice(0,6);
  },[]);

  const computeWireBadge = useCallback((hash6:string, wireVersion=6, pwa=67)=>{
    return { wire:`v${wireVersion}@${hash6}`, pwa:`v${pwa}@${hash6}`, hash6 };
  },[]);

  useEffect(()=>{
    let alive=true;
    const tick = ()=>{
      try {
        const d = safeGetDaemon();
        const s = d?.snapshot?.() ?? { daemonPid: 21475, ptyCount: agents.length, tunnelCount: 1, uptimeMs: 123456, ipcOk:true };
        if (!alive) return;
        setSnap(s);
        const mods = safeGetModules();
        try { if (mods?.guardrails?.list) setGuardList(mods.guardrails.list() ?? []); } catch {}
        try { if (mods?.feedback?.list) setFbList(mods.feedback.list(20) ?? []); } catch {}
        try {
          if (mods?.scratch?.read) {
            const m = mods.scratch.read('default',0,50);
            setScratchEntries((m as any)?.entries ?? []);
          } else if (mods?.scratch?.snapshot) {
            const m = mods.scratch.snapshot('default');
            setScratchEntries((m as any)?.entries ?? []);
          }
        } catch {}
        try {
          if (mods?.todo?.list) setTodos(mods.todo.list() ?? []);
          else if (mods?.todo?._raw?.list) setTodos(mods.todo._raw.list() ?? []);
        } catch {}
        try {
          const hash = (s as any)?.binaryHash ?? 'acd-v6-placeholder-binary';
          const h6 = getHash6(hash);
          const badges = computeWireBadge(h6, 6, 67);
          if (!tandemState.wireBadge) setTandemState(ts=> ({ ...ts, wireBadge: badges.wire, hash6: h6, pwaBadge: badges.pwa }));
        } catch {}
      } catch {}
    };
    tick();
    const iv = setInterval(tick, 2200);
    return ()=> { alive=false; clearInterval(iv); };
  },[]);

  useEffect(()=>{
    if (!tandem) return;
    let alive=true;
    const probe = async ()=>{
      try{
        const r = await fetch('/api/pair/status'+(pairCode?`?code=${encodeURIComponent(pairCode)}`:''), { cache:'no-store' }).then(x=> x.ok ? x.json() : null).catch(()=> null);
        if (!alive) return;
        if (r){
          const hash6 = r.hash6 ?? getHash6(r.hash ?? pairCode ?? 'acd-v6-placeholder-binary');
          const wire = r.wireBadge ?? `v6@${hash6}`;
          const pwa = r.pwaBadge ?? `v67@${hash6}`;
          setTandemState(s=> ({ ...s, paired: !!r.paired || !!r.ok, code: s.code || pairCode, wireBadge: s.wireBadge || wire, hash6, pwaBadge: s.pwaBadge || pwa }));
        } else if (pairCode) {
          const hash6 = getHash6(pairCode);
          const badges = computeWireBadge(hash6, 6, 67);
          setTandemState(s=> ({ ...s, paired: s.paired, wireBadge: s.wireBadge || badges.wire, hash6, pwaBadge: s.pwaBadge || badges.pwa }));
        }
      }catch{
        if (pairCode) {
          const hash6 = getHash6(pairCode);
          const badges = computeWireBadge(hash6, 6, 67);
          setTandemState(s=> ({ ...s, wireBadge: s.wireBadge || badges.wire, hash6, pwaBadge: s.pwaBadge || badges.pwa }));
        }
      }
    };
    probe();
    const iv = setInterval(probe, 8000);
    return ()=>{ alive=false; clearInterval(iv); };
  },[tandem, pairCode]);

  const doConfetti = useCallback((e?: React.MouseEvent)=>{
    const root = confettiRef.current;
    if (!root) return;
    // reduced-motion gate — prod accessibility
    try { if (typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return; } catch {}
    if (root.querySelectorAll('[data-vh-confetti-particle]').length > 80) return; // 80max hard cap
    const src = (e?.currentTarget as HTMLElement)?.getBoundingClientRect?.();
    const lx = src ? src.left + src.width/2 : innerWidth/2;
    const ty = src ? src.top : innerHeight/2;
    for (let i=0;i< (Math.random()<0.5?18:28); i++){
      const dot = document.createElement('span');
      dot.setAttribute('data-vh-confetti-particle','');
      dot.style.position='absolute';
      dot.style.left=`${lx}px`;
      dot.style.top=`${ty}px`;
      dot.style.width='6px'; dot.style.height='6px';
      dot.style.borderRadius='99px';
      dot.style.background=`hsl(${120+Math.random()*60} 90% 60%)`;
      dot.style.pointerEvents='none';
      root.appendChild(dot);
      const dx = (Math.random()-0.5)*260;
      const dy = (Math.random()-0.2)*-180-40;
      const anim = dot.animate([
        { transform:'translate3d(0,0,0) scale(1)', opacity:1 },
        { transform:`translate3d(${dx}px,${dy}px,0) scale(0.2)`, opacity:0 }
      ], { duration:1800+Math.random()*600, easing:'cubic-bezier(.22,1,.36,1)' });
      anim.onfinish=()=> dot.remove();
    }
  },[]);

  const rpc = useCallback(async (method:string, payload:any)=>{
    try{
      const d = safeGetDaemon();
      const disp = d?.getDispatcher?.();
      if (!disp) throw new Error('no daemon');
      const req = { id:`rpc_${Date.now()}_${Math.random().toString(16).slice(2)}`, method, payload, authTag: yubiTouched?'yubi-once-tag':undefined };
      const r = await disp.dispatch(req as any);
      if (!r.ok) throw new Error((r.error as any)?.message ?? 'rpc error');
      if (method.startsWith('todo')) {
        const mods = safeGetModules(); setTodos(mods?.todo?.list?.() ?? []);
      }
      if (method.startsWith('scratchpad')) {
        const mods = safeGetModules(); const m = mods?.scratch?.read?.('default',0,50); setScratchEntries((m as any)?.entries ?? []);
      }
      if (method.startsWith('feedback')) {
        const mods = safeGetModules(); setFbList(mods?.feedback?.list?.(20) ?? []);
      }
      return r.payload;
    }catch{
      // thin UI silent fail — no dev spam
      return null;
    }
  },[yubiTouched]);

  const handleClone = (host:string)=>{
    const next={id:`agt_${Date.now()}`, host, task:'interactive learning', status:'running'};
    setAgents(a=>[...a,next]);
    rpc('feedback.push',{ kind:'note', message:`new session on ${host}`, strength:0.4 }).catch(()=>{});
  };

  const handleTodoCreate = async ()=>{
    if(!todoInput.trim()) return;
    doConfetti();
    await rpc('todo.create',{ title: todoInput, priority:'mid', status:'open' });
    setTodoInput('');
  };

  const handleScratchWrite = async ()=>{
    if(!scratchInput.trim()) return;
    await rpc('scratchpad.write',{ missionId:'default', append:true, text: scratchInput, author:'human' });
    setScratchInput('');
  };

  const handleFeedback = async (kind:string)=>{
    if(!feedbackMsg.trim() && kind==='note') return;
    await rpc('feedback.push',{ kind, message: feedbackMsg || (kind==='thumbs_up'?'This is working well': kind==='thumbs_down'?'Needs attention':'Quick note'), strength: kind==='thumbs_up'?1: kind==='thumbs_down'?-0.6:0.2 });
    setFeedbackMsg('');
    doConfetti();
  };

  return (
    <div data-conductor-root style={{ fontFamily:'ui-sans-system, -apple-system, Segoe UI, Roboto, sans-serif', background:'#080A0F', color:'#E6F1EB', minHeight:640, position:'relative', borderRadius:16, overflow:'hidden', border:'1px solid #1E3328' }}>
      <div ref={confettiRef} style={{ position:'absolute', inset:0, pointerEvents:'none', overflow:'hidden', zIndex:99 }} />

      {/* Sticky 40px nav — pro pill nav */}
      <div style={{ position:'sticky', top:0, zIndex:40, height:40, display:'flex', alignItems:'center', gap:10, padding:'0 12px', background:'rgba(8,10,15,0.92)', backdropFilter:'blur(12px)', borderBottom:'1px solid #1E3328' }}>
        <div style={{ fontWeight:700, letterSpacing:-0.2, whiteSpace:'nowrap', fontSize:13.5, color:'#E8FFF0' }}>Conductor</div>
        <div style={{ display:'flex', gap:6, marginLeft:12 }}>
          {NAV.map(n=>(
            <button key={n} onClick={()=>setActive(n)} aria-selected={active===n} style={{
              height:28,
              background: active===n ? '#132E20' : 'transparent',
              border: '1px solid',
              borderColor: active===n ? '#21402E' : 'transparent',
              color: active===n ? '#7CFFB2' : '#8BA998',
              fontSize:12.2,
              cursor:'pointer',
              fontWeight: active===n ? 600:450,
              padding:'0 11px',
              borderRadius:999,
              whiteSpace:'nowrap',
              transition:'all .16s ease'
            }}>{n}</button>
          ))}
        </div>
        <div style={{ marginLeft:'auto', display:'flex', gap:8, alignItems:'center' }}>
          <span style={{ width:7, height:7, borderRadius:99, background:'#22c55e', boxShadow:'0 0 0 2px rgba(34,197,94,.22)' }} />
          <span style={{ fontSize:11, color:'#86A99A', letterSpacing:0.1 }}>live • {agents.length} warm</span>
        </div>
      </div>

      {tandem && (
        <div style={{ display:'flex', gap:8, alignItems:'center', padding:'0 12px', height:36, background:'#0C1A14', borderBottom:'1px solid #1E3328', fontSize:11.2, flexWrap:'wrap', overflow:'hidden' }}>
          <span style={{ fontWeight:700, color:'#8AFFBE', letterSpacing:0.15 }}>Tandem</span>
          <span style={{ display:'inline-flex', alignItems:'center', gap:6, padding:'4px 10px', borderRadius:99, background: snap ? '#10271B':'#141A15', border:'1px solid #1F3A28', color: snap ? '#7CFFB2' : '#8BA998' }}>
            <span style={{ width:6, height:6, borderRadius:99, background: snap ? '#22c55e' : '#f59e0b', display:'inline-block' }} /> Local {snap ? 'on' : 'checking'}
          </span>
          <span style={{ display:'inline-flex', alignItems:'center', gap:6, padding:'4px 10px', borderRadius:99, background:'#102019', border:'1px solid #1F3A28', color:'#7CFFB2' }}>
            <span style={{ width:6, height:6, borderRadius:99, background:'#22c55e', display:'inline-block' }} /> Cloud ok
          </span>
          <span style={{ display:'inline-flex', alignItems:'center', gap:6, padding:'4px 10px', borderRadius:99, background: tandemState.paired?'#122F1E':'#1A1E16', border:'1px solid', borderColor: tandemState.paired?'#22402E':'#1E3328', color: tandemState.paired ? '#7CFFB2' : '#8BA998', fontWeight: tandemState.paired?600:400 }}>
            <span style={{ width:6, height:6, borderRadius:99, background: tandemState.paired ? '#22c55e' : '#6b7280', display:'inline-block' }} /> {tandemState.paired ? 'Paired' : 'Unpaired'}{tandemState.code ? ` · ${tandemState.code}` : pairCode ? ` · ${pairCode}` : ''}
          </span>
          {(tandemState.code || pairCode) && (
            <button onClick={async (e)=>{
              const c = (tandemState.code || pairCode || '').toString();
              try{ await navigator.clipboard.writeText(c); (e.currentTarget as any).textContent='Copied ✓'; setTimeout(()=>{(e.currentTarget as any).textContent='Copy';},1400);}catch{}
              doConfetti(e as any);
            }} style={{ fontSize:11, padding:'4px 10px', borderRadius:999, background:'#132B21', color:'#7CFFB2', border:'1px solid #1F3A28', cursor:'pointer' }}>Copy</button>
          )}
          {tandemState.paired && (tandemState.pwaBadge || tandemState.wireBadge) && (
            <span style={{ display:'inline-flex', alignItems:'center', gap:6, padding:'4px 10px', borderRadius:99, background:'#122C1E', border:'1px solid #21402E', color:'#7CFFB2', fontWeight:600, fontSize:11 }} title="same binary auto-updates">
              {tandemState.pwaBadge ?? tandemState.wireBadge}
            </span>
          )}
          <span style={{ color:'#7E9F8F', fontSize:10.8, marginLeft:2 }}>One touch covers all / tunnel warm</span>
        </div>
      )}

      <div style={{ maxWidth:1140, margin:'0 auto', padding:'14px 12px' }}>

        {active==='Dashboard' && (
          <>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:12 }}>
              <div style={{ background:'#0F1E16', border:'1px solid #1E3328', borderRadius:12, padding:12 }}>
                <div style={{ fontSize:10.5, color:'#7E9F8F', textTransform:'uppercase', letterSpacing:.7, fontWeight:600 }}>How it works</div>
                <div style={{ marginTop:7, fontSize:13, lineHeight:1.5, color:'#D7EFE2' }}>Parallel sessions, same machine, shared notes, one place.</div>
                <div style={{ marginTop:6, fontSize:12, color:'#8BA998' }}>One daemon keeps sessions warm — instantly resumes.</div>
              </div>
              <div style={{ background:'#0F1E16', border:'1px solid #1E3328', borderRadius:12, padding:12 }}>
                <div style={{ fontSize:10.5, color:'#7E9F8F', textTransform:'uppercase', letterSpacing:.7, fontWeight:600 }}>Approval</div>
                <div style={{ display:'flex', gap:8, marginTop:9 }}>
                  <button onClick={()=>setApprovalMode('auto')} style={{ height:32, padding:'0 14px', borderRadius:999, background: approvalMode==='auto' ? '#7CFFB2':'#122117', color: approvalMode==='auto' ? '#04210F':'#8BA998', border:'1px solid #1F3A28', fontSize:12, fontWeight:600 }}>Auto</button>
                  <button onClick={()=>setApprovalMode('manual')} style={{ height:32, padding:'0 14px', borderRadius:999, background: approvalMode==='manual' ? '#7CFFB2':'#122117', color: approvalMode==='manual' ? '#04210F':'#8BA998', border:'1px solid #1F3A28', fontSize:12, fontWeight:600 }}>Manual</button>
                </div>
                <div style={{ fontSize:11, color:'#7E9F8F', marginTop:8 }}>Risky actions pause for a check in either mode.</div>
              </div>
            </div>

            <div style={{ background:'#0F1E16', border:'1px solid #1E3328', borderRadius:12, padding:12, marginBottom:12 }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                <div style={{ fontWeight:600, fontSize:12.5, color:'#D7EFE2' }}>Machines • one connection, all tools</div>
                <button onClick={()=>{ setYubiTouched(v=>!v); }} style={{ height:28, fontSize:11, padding:'0 10px', borderRadius:999, background: yubiTouched ? '#7CFFB2':'#122117', color: yubiTouched ? '#04210F':'#8BA998', border:'1px solid #1F3A28' }}>{yubiTouched?'Touch active':'One touch'}</button>
              </div>
              <div style={{ display:'flex', gap:8, marginTop:10, flexWrap:'wrap' }}>
                {hosts.map(h=>(
                  <div key={h} style={{ background:'#0A1610', border:'1px solid #1E3328', borderRadius:10, padding:'10px 12px', minWidth:168 }}>
                    <div style={{ fontSize:12.5, fontWeight:600, color:'#D7EFE2' }}>{h}</div>
                    <div style={{ fontSize:11, marginTop:2, color:'#7E9F8F' }}>single WS • survives restarts</div>
                    <button onClick={()=>handleClone(h)} style={{ marginTop:9, height:26, fontSize:11, padding:'0 10px', borderRadius:999, background:'#132B21', color:'#7CFFB2', border:'1px solid #1F3A28' }}>+ new session</button>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display:'grid', gridTemplateColumns:'300px 1fr', gap:10 }}>
              <div style={{ background:'#0F1E16', border:'1px solid #1E3328', borderRadius:12, padding:10 }}>
                <div style={{ fontSize:11, color:'#7E9F8F', marginBottom:8, fontWeight:600 }}>Sessions — {agents.length} warm</div>
                {agents.map(a=>(
                  <div key={a.id} style={{ display:'flex', justifyContent:'space-between', padding:'8px 6px', borderBottom:'1px dashed #1E3328' }}>
                    <div><div style={{ fontSize:11.5, fontWeight:600, color:'#D7EFE2' }}>{a.id.slice(0,18)}</div><div style={{ fontSize:10.5, color:'#7E9F8F' }}>{a.host} • {a.task}</div></div>
                    <div style={{ fontSize:10, background:'#143222', color:'#7CFFB2', padding:'3px 7px', borderRadius:999, height:'fit-content', marginTop:2 }}>●</div>
                  </div>
                ))}
              </div>
              <div style={{ background:'#0A1510', border:'1px solid #1E3328', borderRadius:12, padding:14, fontSize:12.5, lineHeight:1.6 }}>
                <div style={{ fontWeight:600, marginBottom:6, color:'#D7EFE2' }}>Why it feels different</div>
                <div style={{ color:'#8BA998' }}>Single daemon keeps sessions warm. Same binary everywhere — auto-updates. One channel many streams, tunnel stays up, no re-auth. One touch covers everything.</div>
                <div style={{ marginTop:12, display:'flex', gap:7, flexWrap:'wrap' }}>
                  {['single daemon','same binary','survives restarts','one touch'].map(k=>(
                    <span key={k} style={{ fontSize:10.5, padding:'4px 9px', borderRadius:999, background:'#112117', border:'1px solid #1E3328', color:'#7E9F8F' }}>{k}</span>
                  ))}
                </div>
              </div>
            </div>
          </>
        )}

        {active==='Guardrails' && (
          <div style={{ background:'#0F1E16', border:'1px solid #1E3328', borderRadius:12, padding:14 }}>
            <div style={{ fontWeight:600, fontSize:13, color:'#D7EFE2' }}>Guardrails — quiet safety</div>
            <div style={{ fontSize:12, color:'#7E9F8F', marginTop:4, marginBottom:12 }}>Risky commands ask first, usage is capped, sessions pause gracefully and resume later.</div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8 }}>
              {(guardList.length?guardList:[
                {id:'approval-destructive',name:'Destructive needs approval',desc:'Deletes and force pushes pause for a check',enabled:true},
                {id:'quota-pty',name:'Session limits',desc:'Keeps things tidy when you have many machines',enabled:true},
                {id:'rate-limit',name:'Fair use',desc:'Prevents runaway loops from hogging a machine',enabled:true},
                {id:'auth-24h',name:'Fresh check',desc:'Re-confirms once a day or when tools update',enabled:true},
                {id:'expiry-48h',name:'Pause after 2 days',desc:'Puts long sessions to sleep with a receipt',enabled:true},
              ] as any).map((p:any)=>(
                <div key={p.id} style={{ display:'flex', justifyContent:'space-between', padding:'11px 12px', background:'#0A1610', border:'1px solid #1E3328', borderRadius:10 }}>
                  <div style={{ paddingRight:10 }}><div style={{ fontSize:12.5, fontWeight:600, color:'#D7EFE2' }}>{p.name}</div><div style={{ fontSize:11, color:'#7E9F8F', marginTop:2 }}>{p.desc}</div></div>
                  <button onClick={()=>rpc('guardrail.toggle',{id:p.id, enabled:!p.enabled})} style={{ fontSize:11, padding:'0 11px', height:26, borderRadius:999, background:p.enabled?'#132B21':'#121A15', color:'#7CFFB2', border:'1px solid #1E3328', alignSelf:'center' }}>{p.enabled?'on':'off'}</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {active==='Feedback' && (
          <div style={{ display:'grid', gridTemplateColumns:'340px 1fr', gap:10 }}>
            <div style={{ background:'#0F1E16', border:'1px solid #1E3328', borderRadius:12, padding:12 }}>
              <div style={{ fontWeight:600, fontSize:13, marginBottom:8, color:'#D7EFE2' }}>Feedback</div>
              <div style={{ display:'flex', gap:6, marginBottom:10 }}>
                <button onClick={()=>handleFeedback('thumbs_up')} style={{ height:30, fontSize:12, padding:'0 10px', borderRadius:999, background:'#132B21', color:'#7CFFB2', border:'1px solid #1E3328' }}>↑ Good</button>
                <button onClick={()=>handleFeedback('thumbs_down')} style={{ height:30, fontSize:12, padding:'0 10px', borderRadius:999, background:'#21190E', color:'#FFC37C', border:'1px solid #3A2E1E' }}>↓ Fix</button>
                <button onClick={()=>rpc('feedback.compact',{ recentMessages: fbList.map(f=>f.message||f.text).slice(0,20)})} style={{ height:30, fontSize:11, padding:'0 10px', borderRadius:999, background:'#121A15', color:'#7E9F8F', border:'1px solid #1E3328' }}>Tidy up</button>
              </div>
              <textarea value={feedbackMsg} onChange={e=>setFeedbackMsg(e.target.value)} placeholder="What should be better? Becomes a compact note the system learns from." style={{ width:'100%', minHeight:72, background:'#0A1610', color:'#E6F1EB', border:'1px solid #1E3328', borderRadius:10, padding:'9px 10px', fontSize:12, fontFamily:'ui-sans-system, sans-serif' }} />
              <div style={{ marginTop:8, display:'flex', gap:6 }}>
                <button onClick={()=>handleFeedback('note')} style={{ height:30, fontSize:11, padding:'0 12px', borderRadius:999, background:'#7CFFB2', color:'#04210F', border:'1px solid #1E3328', fontWeight:600 }}>Send note</button>
              </div>
              <div style={{ marginTop:10, fontSize:11, color:'#7E9F8F' }}>Notes are grouped and summarized to keep context clean.</div>
            </div>
            <div style={{ background:'#0A1510', border:'1px solid #1E3328', borderRadius:12, padding:10, maxHeight:380, overflow:'auto' }}>
              <div style={{ fontSize:11, color:'#7E9F8F', marginBottom:8, fontWeight:600 }}>Recent</div>
              {(fbList.length?fbList:[
                {id:'fb1', kind:'note', message:'Multi-session on one machine feels smooth', ts:Date.now(), strength:0.5},
                {id:'fb2', kind:'note', message:'Blocked a risky delete — good catch', ts:Date.now()-2000, strength:-0.3},
                {id:'fb3', kind:'note', message:'Compacted notes kept the important bits', ts:Date.now()-6000, strength:0.4},
              ]).map((f:any)=>(
                <div key={f.id} style={{ padding:'8px 10px', borderBottom:'1px dashed #1E3328', fontSize:12 }}>
                  <div style={{ color: f.strength<0?'#FF9A9A':'#7CFFB2', fontSize:10.5 }}>{f.kind} • {new Date(f.ts).toLocaleTimeString()}</div>
                  <div style={{ color:'#D7EFE2', marginTop:2 }}>{String(f.message||f.text||'').slice(0,180)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {active==='Scratchpad' && (
          <div style={{ display:'grid', gridTemplateColumns:'1fr 320px', gap:10 }}>
            <div style={{ background:'#0F1E16', border:'1px solid #1E3328', borderRadius:12, padding:12 }}>
              <div style={{ fontWeight:600, fontSize:13, marginBottom:10, color:'#D7EFE2' }}>Shared notes</div>
              <div style={{ display:'flex', gap:8 }}>
                <input value={scratchInput} onChange={e=>setScratchInput(e.target.value)} onKeyDown={e=>e.key==='Enter'&&handleScratchWrite()} placeholder="Breadcrumb for future you or another agent…" style={{ flex:1, background:'#0A1610', color:'#E6F1EB', border:'1px solid #1E3328', borderRadius:999, padding:'0 12px', height:36, fontSize:12.5 }} />
                <button onClick={handleScratchWrite} style={{ height:36, fontSize:12.5, padding:'0 16px', borderRadius:999, background:'#7CFFB2', color:'#04210F', border:'1px solid #1E3328', fontWeight:600 }}>Add</button>
              </div>
              <div style={{ marginTop:10, fontSize:11, color:'#7E9F8F' }}>{scratchEntries.length} notes • same everywhere on this mission</div>
              <div style={{ marginTop:10, maxHeight:300, overflow:'auto', background:'#0A1610', border:'1px solid #1E3328', borderRadius:10, padding:8 }}>
                {(scratchEntries.length?scratchEntries:[
                  {ts:Date.now()-10000, author:'you', text:'Two sessions on same box — one refactoring auth'},
                  {ts:Date.now()-6000, author:'agent', text:'Keeping tunnel alive so reconnect is instant'},
                  {ts:Date.now()-3000, author:'system', text:'Risky command paused for review — continue?'},
                ]).map((e:any,i:number)=>(
                  <div key={i} style={{ fontSize:12, padding:'6px 0', borderBottom:'1px dashed #1E3328' }}>
                    <span style={{ color:'#7E9F8F' }}>{new Date(e.ts).toLocaleTimeString()} {e.author}:</span> <span style={{ color:'#D7EFE2' }}>{e.text}</span>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ background:'#0A1510', border:'1px solid #1E3328', borderRadius:12, padding:14, fontSize:12, lineHeight:1.6, color:'#7E9F8F' }}>
              <div style={{ fontWeight:600, color:'#D7EFE2', fontSize:12.5 }}>How it works</div>
              <div style={{ marginTop:6 }}>Mission-scoped. Everyone on this mission sees the same notes. Saved automatically when a session exits. Conflicts keep both versions so nothing gets lost.</div>
            </div>
          </div>
        )}

        {active==='Todos' && (
          <div style={{ display:'grid', gridTemplateColumns:'340px 1fr', gap:10 }}>
            <div style={{ background:'#0F1E16', border:'1px solid #1E3328', borderRadius:12, padding:12 }}>
              <div style={{ fontWeight:600, fontSize:13, marginBottom:10, color:'#D7EFE2' }}>Tasks — one at a time</div>
              <div style={{ display:'flex', gap:8 }}>
                <input value={todoInput} onChange={e=>setTodoInput(e.target.value)} onKeyDown={e=> e.key==='Enter' && handleTodoCreate()} placeholder="What’s next?" style={{ flex:1, background:'#0A1610', color:'#E6F1EB', border:'1px solid #1E3328', borderRadius:999, padding:'0 12px', height:36, fontSize:12.5 }} />
                <button onClick={handleTodoCreate} style={{ height:36, fontSize:12.5, padding:'0 16px', borderRadius:999, background:'#7CFFB2', color:'#04210F', border:'1px solid #1E3328', fontWeight:600 }}>Add</button>
              </div>
              <div style={{ marginTop:10, maxHeight:320, overflow:'auto' }}>
                {(todos.length?todos:[
                  {id:'t1', text:'Prune unused operator entry in config', status:'open'},
                  {id:'t2', text:'Wire guardrails into conductor panel', status:'in_progress'},
                  {id:'t3', text:'Wire scratchpad + todos as shared tools', status:'open'},
                  {id:'t4', text:'Add subtle confetti on task complete', status:'completed'},
                ] as any).map((t:any)=>(
                  <div key={t.id} style={{ display:'flex', gap:10, alignItems:'center', padding:'8px 9px', background: t.status==='in_progress'?'#132B21':'transparent', border:'1px solid', borderColor: t.status==='in_progress'?'#1F3A28':'transparent', borderRadius:10, marginBottom:6 }}>
                    <input type="checkbox" checked={t.status==='completed'} onChange={()=>rpc('todo.move',{id:t.id, status: t.status==='completed'?'open':'completed'})} />
                    <div style={{ flex:1, fontSize:12.5, textDecoration: t.status==='completed'?'line-through':'none', color: t.status==='completed'?'#6B8A7A':'#D7EFE2' }}>{t.text}</div>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ background:'#0A1510', border:'1px solid #1E3328', borderRadius:12, padding:14, fontSize:12, lineHeight:1.55, color:'#7E9F8F' }}>
              <div style={{ fontWeight:600, color:'#D7EFE2', fontSize:12.5 }}>Why one at a time</div>
              <div style={{ marginTop:6 }}>Only one task is active globally for a mission — prevents two agents from stepping on each other. Persists across parallel sessions. Finishes ping your desktop. Risky tasks always ask first.</div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
