// @ts-nocheck
"use client";
/**
 * AgentConductorPanel — polished thin-UI
 * Clean, readable, everyday language. No internal machinery in UI.
 * Keeps: 5 tabs Dashboard | Guardrails | Feedback | Scratchpad | Todos
 * Single daemon owns PTY/tunnel/file/ISL, snapshot fast, peers same binary, one channel many streams
 * First-class: scratchpad, todos, guardrails, feedback/compaction
 * Real RPCs, PWA, delight confetti 29JS 9CSS 80max WebAnimations translate3d .22,1,.36,1
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

export default function AgentConductorPanel() {
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
  const confettiRef = useRef<HTMLDivElement>(null);

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
      } catch {}
    };
    tick();
    const iv = setInterval(tick, 2000);
    const auto = setTimeout(()=> setYubiTouched(false), 300);
    return ()=> { alive=false; clearInterval(iv); clearTimeout(auto); };
  },[]);

  const doConfetti = useCallback((e?: React.MouseEvent)=>{
    const root = confettiRef.current;
    if (!root) return;
    if (root.querySelectorAll('[data-vh-confetti-particle]').length > 80) return;
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
    }catch(e:any){
      console.warn('rpc fail', e?.message);
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
    <div style={{ fontFamily:'ui-sans-system, -apple-system, Segoe UI, Roboto, sans-serif', background:'#080A0F', color:'#E6F1EB', minHeight:640, position:'relative', borderRadius:16, overflow:'hidden', border:'1px solid #1E3A2F' }}>
      <div ref={confettiRef} style={{ position:'absolute', inset:0, pointerEvents:'none', overflow:'hidden', zIndex:99 }} />

      {/* Sticky 40px nav — clean */}
      <div style={{ position:'sticky', top:0, zIndex:40, height:40, display:'flex', alignItems:'center', gap:8, padding:'0 12px', background:'rgba(8,10,15,0.92)', backdropFilter:'blur(8px)', borderBottom:'1px solid #1E3A2F' }}>
        <div style={{ fontWeight:700, letterSpacing:-0.2, whiteSpace:'nowrap', fontSize:13 }}>Conductor</div>
        <div style={{ display:'flex', gap:6, marginLeft:12 }}>
          {NAV.map(n=>(
            <button key={n} onClick={()=>setActive(n)} aria-selected={active===n} style={{ background:active===n?'#102019':'transparent', border:'1px solid', borderColor: active===n?'#1E3A2F':'transparent', color: active===n ? '#7CFFB2' : '#8BA998', fontSize:12, cursor:'pointer', fontWeight: active===n ? 600:400, padding:'5px 10px', borderRadius:8, whiteSpace:'nowrap' }}>{n}</button>
          ))}
        </div>
        <div style={{ marginLeft:'auto', display:'flex', gap:8, alignItems:'center' }}>
          <span style={{ width:7, height:7, borderRadius:99, background:'#22c55e', boxShadow:'0 0 0 2px rgba(34,197,94,.22)' }} />
          <span style={{ fontSize:11, color:'#8BA998' }}>live</span>
        </div>
      </div>

      <div style={{ maxWidth:1180, margin:'0 auto', padding:'16px 12px' }}>

        {active==='Dashboard' && (
          <>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:12 }}>
              <div style={{ background:'#0F1A12', border:'1px solid #1E3A2F', borderRadius:12, padding:12 }}>
                <div style={{ fontSize:11, color:'#8BA998', textTransform:'uppercase', letterSpacing:.6 }}>How it works</div>
                <div style={{ marginTop:6, fontSize:12.5, lineHeight:1.55 }}>One agent, one window used to be the limit. Now you can run two or more on the same machine — parallel, share notes, and stay organized in one place.</div>
                <div style={{ marginTop:8, fontSize:11, color:'#8BA998' }}>Lightweight • Reliable • Parallel</div>
              </div>
              <div style={{ background:'#0F1A12', border:'1px solid #1E3A2F', borderRadius:12, padding:12 }}>
                <div style={{ fontSize:11, color:'#8BA998', textTransform:'uppercase', letterSpacing:.6 }}>Approval</div>
                <div style={{ display:'flex', gap:8, marginTop:8 }}>
                  <button onClick={()=>setApprovalMode('auto')} style={{ padding:'6px 12px', borderRadius:8, background: approvalMode==='auto' ? '#7CFFB2':'#132019', color: approvalMode==='auto' ? '#04210F':'#8BA998', border:'1px solid #1E3A2F', fontSize:12 }}>Auto</button>
                  <button onClick={()=>setApprovalMode('manual')} style={{ padding:'6px 12px', borderRadius:8, background: approvalMode==='manual' ? '#7CFFB2':'#132019', color: approvalMode==='manual' ? '#04210F':'#8BA998', border:'1px solid #1E3A2F', fontSize:12 }}>Manual</button>
                </div>
                <div style={{ fontSize:11, color:'#8BA998', marginTop:8 }}>Destructive actions always ask for approval in either mode.</div>
              </div>
            </div>

            <div style={{ background:'#0F1A12', border:'1px solid #1E3A2F', borderRadius:12, padding:12, marginBottom:12 }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                <div style={{ fontWeight:600, fontSize:12.5 }}>Machines</div>
                <button onClick={()=>{ setYubiTouched(v=>!v); }} style={{ fontSize:11, padding:'5px 10px', borderRadius:8, background: yubiTouched ? '#7CFFB2':'#1A2E22', color: yubiTouched ? '#04210F':'#8BA998', border:'1px solid #1E3A2F' }}>{yubiTouched?'One touch active':'One touch covers everything'}</button>
              </div>
              <div style={{ display:'flex', gap:8, marginTop:10, flexWrap:'wrap' }}>
                {hosts.map(h=>(
                  <div key={h} style={{ background:'#0A1410', border:'1px solid #1E3A2F', borderRadius:10, padding:'10px 12px', minWidth:156 }}>
                    <div style={{ fontSize:12, fontWeight:600 }}>{h}</div>
                    <div style={{ fontSize:11, marginTop:2, color:'#8BA998' }}>one connection • all tools</div>
                    <button onClick={()=>handleClone(h)} style={{ marginTop:8, fontSize:11, padding:'4px 8px', borderRadius:7, background:'#14291E', color:'#7CFFB2', border:'1px solid #1E3A2F' }}>+ new session</button>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display:'grid', gridTemplateColumns:'300px 1fr', gap:10 }}>
              <div style={{ background:'#0F1A12', border:'1px solid #1E3A2F', borderRadius:12, padding:10 }}>
                <div style={{ fontSize:11, color:'#8BA998', marginBottom:8 }}>Sessions — {agents.length} warm</div>
                {agents.map(a=>(
                  <div key={a.id} style={{ display:'flex', justifyContent:'space-between', padding:'7px 6px', borderBottom:'1px dashed #1E2A1F' }}>
                    <div><div style={{ fontSize:11, fontWeight:600 }}>{a.id.slice(0,18)}</div><div style={{ fontSize:10, color:'#8BA998' }}>{a.host} • {a.task}</div></div>
                    <div style={{ fontSize:10, background:'#14331F', color:'#7CFFB2', padding:'2px 7px', borderRadius:99, height:'fit-content' }}>●</div>
                  </div>
                ))}
              </div>
              <div style={{ background:'#0A120E', border:'1px solid #1E3A2F', borderRadius:12, padding:12, fontSize:12, lineHeight:1.6 }}>
                <div style={{ fontWeight:600, marginBottom:6 }}>Why this feels different</div>
                <div style={{ color:'#8BA998' }}>Single daemon keeps sessions warm — single daemon owns PTY/tunnel/file/ISL. Peers same binary — same binary auto-updates. One channel many streams, tunnel stays up no re-auth. One touch covers everything.</div>
                <div style={{ marginTop:10, display:'flex', gap:6, flexWrap:'wrap' }}>
                  <span style={{ fontSize:10, padding:'3px 8px', borderRadius:99, background:'#102019', border:'1px solid #1E3A2F', color:'#8BA998' }}>single daemon</span>
                  <span style={{ fontSize:10, padding:'3px 8px', borderRadius:99, background:'#102019', border:'1px solid #1E3A2F', color:'#8BA998' }}>same binary everywhere</span>
                  <span style={{ fontSize:10, padding:'3px 8px', borderRadius:99, background:'#102019', border:'1px solid #1E3A2F', color:'#8BA998' }}>survives restarts</span>
                  <span style={{ fontSize:10, padding:'3px 8px', borderRadius:99, background:'#102019', border:'1px solid #1E3A2F', color:'#8BA998' }}>one touch</span>
                </div>
              </div>
            </div>
          </>
        )}

        {active==='Guardrails' && (
          <div style={{ background:'#0F1A12', border:'1px solid #1E3A2F', borderRadius:12, padding:14 }}>
            <div style={{ fontWeight:700, marginBottom:6 }}>Guardrails — safety without getting in the way</div>
            <div style={{ fontSize:11.5, color:'#8BA998', marginBottom:12 }}>Quiet protection: risky commands ask first, usage is capped, sessions pause gracefully and resume later.</div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8 }}>
              {(guardList.length?guardList:[
                {id:'approval-destructive',name:'Destructive commands need approval',desc:'Even in auto mode, deletes and force pushes pause for a check',enabled:true},
                {id:'quota-pty',name:'Session limits',desc:'Keeps things tidy when you have many machines',enabled:true},
                {id:'rate-limit',name:'Fair use',desc:'Prevents runaway loops from hogging a machine',enabled:true},
                {id:'auth-24h',name:'Fresh check',desc:'Re-confirms once a day or when tools update',enabled:true},
                {id:'expiry-48h',name:'Pause after 2 days',desc:'Puts long-running sessions to sleep with a receipt',enabled:true},
              ] as any).map((p:any)=>(
                <div key={p.id} style={{ display:'flex', justifyContent:'space-between', padding:'10px 12px', background:'#0A1410', border:'1px solid #1E3A2F', borderRadius:10 }}>
                  <div><div style={{ fontSize:12, fontWeight:600 }}>{p.name}</div><div style={{ fontSize:11, color:'#8BA998', marginTop:2 }}>{p.desc}</div></div>
                  <button onClick={()=>rpc('guardrail.toggle',{id:p.id, enabled:!p.enabled})} style={{ fontSize:11, padding:'4px 8px', borderRadius:8, background:p.enabled?'#1A2E22':'#14291E', color:'#7CFFB2', border:'1px solid #1E3A2F', height:'fit-content' }}>{p.enabled?'on':'off'}</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {active==='Feedback' && (
          <div style={{ display:'grid', gridTemplateColumns:'340px 1fr', gap:10 }}>
            <div style={{ background:'#0F1A12', border:'1px solid #1E3A2F', borderRadius:12, padding:12 }}>
              <div style={{ fontWeight:600, fontSize:12.5, marginBottom:8 }}>Feedback</div>
              <div style={{ display:'flex', gap:6, marginBottom:10 }}>
                <button onClick={()=>handleFeedback('thumbs_up')} style={{ fontSize:12, padding:'6px 10px', borderRadius:8, background:'#14291E', color:'#7CFFB2', border:'1px solid #1E3A2F' }}>👍 Good</button>
                <button onClick={()=>handleFeedback('thumbs_down')} style={{ fontSize:12, padding:'6px 10px', borderRadius:8, background:'#1A150F', color:'#FFC37C', border:'1px solid #3A2E1E' }}>👎 Fix</button>
                <button onClick={()=>rpc('feedback.compact',{ recentMessages: fbList.map(f=>f.message||f.text).slice(0,20)})} style={{ fontSize:11, padding:'6px 10px', borderRadius:8, background:'#132019', color:'#8BA998', border:'1px solid #1E3A2F' }}>Tidy up</button>
              </div>
              <textarea value={feedbackMsg} onChange={e=>setFeedbackMsg(e.target.value)} placeholder="What should be better? This becomes a compact note the system learns from." style={{ width:'100%', minHeight:68, background:'#0A1410', color:'#E6F1EB', border:'1px solid #1E3A2F', borderRadius:10, padding:'8px 10px', fontSize:11.5 }} />
              <div style={{ marginTop:8, display:'flex', gap:6 }}>
                <button onClick={()=>handleFeedback('note')} style={{ fontSize:11, padding:'5px 10px', borderRadius:8, background:'#7CFFB2', color:'#04210F', border:'1px solid #1E3A2F' }}>Send note</button>
              </div>
              <div style={{ marginTop:10, fontSize:11, color:'#8BA998' }}>Notes are grouped and summarized every so often to keep context clean.</div>
            </div>
            <div style={{ background:'#0A120E', border:'1px solid #1E3A2F', borderRadius:12, padding:10, maxHeight:380, overflow:'auto' }}>
              <div style={{ fontSize:11, color:'#8BA998', marginBottom:8 }}>Recent</div>
              {(fbList.length?fbList:[
                {id:'fb1', kind:'note', message:'Multi-session on one machine feels smooth', ts:Date.now(), strength:0.5},
                {id:'fb2', kind:'note', message:'Blocked a risky delete — good catch', ts:Date.now()-2000, strength:-0.3},
                {id:'fb3', kind:'note', message:'Compacted notes kept the important bits', ts:Date.now()-6000, strength:0.4},
              ]).map((f:any)=>(
                <div key={f.id} style={{ padding:'8px 10px', borderBottom:'1px dashed #1E2A1F', fontSize:11.5 }}>
                  <div style={{ color: f.strength<0?'#FF9A9A':'#7CFFB2', fontSize:10 }}>{f.kind} • {new Date(f.ts).toLocaleTimeString()}</div>
                  <div style={{ color:'#E6F1EB', marginTop:2 }}>{String(f.message||f.text||'').slice(0,180)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {active==='Scratchpad' && (
          <div style={{ display:'grid', gridTemplateColumns:'1fr 320px', gap:10 }}>
            <div style={{ background:'#0F1A12', border:'1px solid #1E3A2F', borderRadius:12, padding:12 }}>
              <div style={{ fontWeight:600, fontSize:12.5, marginBottom:10 }}>Shared notes</div>
              <div style={{ display:'flex', gap:8 }}>
                <input value={scratchInput} onChange={e=>setScratchInput(e.target.value)} onKeyDown={e=>e.key==='Enter'&&handleScratchWrite()} placeholder="Breadcrumb for future you or another agent…" style={{ flex:1, background:'#0A1410', color:'#E6F1EB', border:'1px solid #1E3A2F', borderRadius:10, padding:'8px 12px', fontSize:12 }} />
                <button onClick={handleScratchWrite} style={{ fontSize:12, padding:'8px 14px', borderRadius:10, background:'#7CFFB2', color:'#04210F', border:'1px solid #1E3A2F', fontWeight:600 }}>Add</button>
              </div>
              <div style={{ marginTop:10, fontSize:11, color:'#8BA998' }}>{scratchEntries.length} notes • same everywhere on this mission</div>
              <div style={{ marginTop:10, maxHeight:300, overflow:'auto', background:'#0A1410', border:'1px solid #1E3A2F', borderRadius:10, padding:8 }}>
                {(scratchEntries.length?scratchEntries:[
                  {ts:Date.now()-10000, author:'you', text:'Two sessions on same box — one refactoring auth, one scaffolding API'},
                  {ts:Date.now()-6000, author:'agent', text:'Keeping tunnel alive so reconnect is instant'},
                  {ts:Date.now()-3000, author:'system', text:'Risky command paused for review — looks right to continue?'},
                ]).map((e:any,i:number)=>(
                  <div key={i} style={{ fontSize:11.5, padding:'6px 0', borderBottom:'1px dashed #1E2A1F' }}>
                    <span style={{ color:'#8BA998' }}>{new Date(e.ts).toLocaleTimeString()} {e.author}:</span> <span style={{ color:'#E6F1EB' }}>{e.text}</span>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ background:'#0A120E', border:'1px solid #1E3A2F', borderRadius:12, padding:12, fontSize:11.5, lineHeight:1.6, color:'#8BA998' }}>
              <div style={{ fontWeight:600, color:'#E6F1EB', fontSize:12 }}>How it works</div>
              <div style={{ marginTop:6 }}>Mission-scoped. Everyone watching this mission sees the same notes. Saved automatically when a session exits. Conflicts keep both versions so nothing gets lost.</div>
            </div>
          </div>
        )}

        {active==='Todos' && (
          <div style={{ display:'grid', gridTemplateColumns:'340px 1fr', gap:10 }}>
            <div style={{ background:'#0F1A12', border:'1px solid #1E3A2F', borderRadius:12, padding:12 }}>
              <div style={{ fontWeight:600, fontSize:12.5, marginBottom:10 }}>Tasks — one at a time</div>
              <div style={{ display:'flex', gap:8 }}>
                <input value={todoInput} onChange={e=>setTodoInput(e.target.value)} onKeyDown={e=> e.key==='Enter' && handleTodoCreate()} placeholder="What’s next?" style={{ flex:1, background:'#0A1410', color:'#E6F1EB', border:'1px solid #1E3A2F', borderRadius:10, padding:'8px 12px', fontSize:12 }} />
                <button onClick={handleTodoCreate} style={{ fontSize:12, padding:'8px 14px', borderRadius:10, background:'#7CFFB2', color:'#04210F', border:'1px solid #1E3A2F', fontWeight:600 }}>Add</button>
              </div>
              <div style={{ marginTop:10, maxHeight:320, overflow:'auto' }}>
                {(todos.length?todos:[
                  {id:'t1', text:'Prune unused operator entry in config', status:'open'},
                  {id:'t2', text:'Wire guardrails into conductor panel', status:'in_progress'},
                  {id:'t3', text:'Wire scratchpad + todos as shared tools', status:'open'},
                  {id:'t4', text:'Add subtle confetti on task complete', status:'completed'},
                ] as any).map((t:any)=>(
                  <div key={t.id} style={{ display:'flex', gap:10, alignItems:'center', padding:'8px 8px', background: t.status==='in_progress'?'#14291E':'transparent', border:'1px solid', borderColor: t.status==='in_progress'?'#1E3A2F':'transparent', borderRadius:10, marginBottom:6 }}>
                    <input type="checkbox" checked={t.status==='completed'} onChange={()=>rpc('todo.move',{id:t.id, status: t.status==='completed'?'open':'completed'})} />
                    <div style={{ flex:1, fontSize:12, textDecoration: t.status==='completed'?'line-through':'none', color: t.status==='completed'?'#6B8A7A':'#E6F1EB' }}>{t.text}</div>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ background:'#0A120E', border:'1px solid #1E3A2F', borderRadius:12, padding:12, fontSize:11.5, lineHeight:1.55, color:'#8BA998' }}>
              <div style={{ fontWeight:600, color:'#E6F1EB', fontSize:12 }}>Why one at a time</div>
              <div style={{ marginTop:6 }}>Only one task is active globally for a mission — prevents two agents from stepping on each other. Persists across parallel sessions. Finishes ping your desktop. Risky tasks always ask first.</div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
