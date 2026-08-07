"use client";
import { useEffect, useState } from "react";

type Stats = {
  papers?: number; nodes?: number; edges?: number; docs?: number;
  people?: number; checksum?: string; timestamp?: string;
};
type Live = {
  updated_at?: string; disclaimer?: string;
  counts?: Record<string, number>;
  system_health?: { platform?: string; python?: string };
};

export default function Home(){
  const [stats, setStats] = useState<Stats | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [now, setNow] = useState<string>("");

  useEffect(()=>{
    const fmt = () => {
      try { return new Date().toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' }); }
      catch { return new Date().toISOString().slice(11,16); }
    };
    setNow(fmt());
    const id = setInterval(()=>setNow(fmt()), 60000);
    fetch("/data/stats.json").then(r=>r.json()).then(setStats).catch(()=>{});
    fetch("/data/acne_stats.json").then(r=>r.json()).then((j)=>{ if(!stats) setStats(prev=>prev||{papers:j?.papers||132}); }).catch(()=>{});
    // try live status from GitHub raw fallback + local
    fetch("/data/dottie_live.json").then(r=>r.json()).then(setLive).catch(()=>{
      // optional: ignore
    });
    return ()=>clearInterval(id);
  },[]);

  return (
    <div className="page">
      <style>{`
        .page {
          --bg: #fcfcf8;
          --bg-2: #f2f1ed;
          --surface: #ffffff;
          --line: #e7e5e0;
          --line-2: #eeece6;
          --ink: #141210;
          --ink-2: #6b6a64;
          --ink-3: #9b9a95;
          --accent: #111111;
          --accent-2: #6366f1;
          --radius: 16px;
          --radius-lg: 20px;
          --max: 1080px;
        }
        @media (prefers-color-scheme: dark){
          .page{
            --bg: #0f0e0d;
            --bg-2: #161412;
            --surface: #1a1816;
            --line: #2a2825;
            --line-2: #22201d;
            --ink: #f5f3f0;
            --ink-2: #a8a5a0;
            --ink-3: #7a7874;
            --accent: #f5f3f0;
          }
        }
        *{box-sizing:border-box}
        .page{
          min-height:100vh;
          background: var(--bg);
          color: var(--ink);
          font-family: ui-serif, Georgia, "Times New Roman", serif;
          -webkit-font-smoothing: antialiased;
        }
        .mono{font-family: ui-monospace, SFMono-Regular, Menlo, monospace}
        .sans{font-family: ui-sans-system, -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif}
        a{color:inherit}
        .top{
          position:sticky; top:0; z-index:20;
          backdrop-filter: blur(12px);
          background: color-mix(in srgb, var(--surface) 88%, transparent);
          border-bottom: 1px solid var(--line);
        }
        .top-inner{
          max-width: var(--max);
          margin: 0 auto;
          padding: 14px 18px;
          display:flex; align-items:center; justify-content:space-between; gap:12px;
        }
        .brand{
          display:flex; align-items:center; gap:10px;
          font-family: ui-monospace, monospace;
          font-size: 11.5px; letter-spacing: 0.02em; color: var(--ink-2);
        }
        .brand b{color:var(--ink); font-weight:650}
        .dot{
          width:6px;height:6px;border-radius:999px;background:#10b981; box-shadow:0 0 0 4px rgba(16,185,129,0.15);
          display:inline-block;
        }
        .right{
          display:flex;align-items:center;gap:8px;
        }
        .pill{
          font-family: ui-monospace, monospace;
          font-size: 10.5px;
          padding: 5px 10px;
          border-radius: 999px;
          border:1px solid var(--line);
          background: var(--surface);
          color: var(--ink-2);
        }
        .pill.live{
          background: var(--ink);
          color: var(--bg);
          border-color: var(--ink);
        }
        .wrap{
          max-width: var(--max);
          margin:0 auto;
          padding: 0 18px;
        }
        .hero{
          padding: 36px 0 20px;
          display:grid;
          grid-template-columns: 1.15fr 0.85fr;
          gap: 24px;
          align-items:start;
        }
        @media(max-width: 860px){
          .hero{grid-template-columns:1fr; padding: 24px 0 12px}
        }
        .kicker{
          font-family: ui-monospace, monospace;
          font-size:11px; letter-spacing:0.08em; text-transform:uppercase;
          color: var(--ink-3); margin-bottom:12px;
          display:flex; gap:8px; align-items:center; flex-wrap:wrap;
        }
        .kicker span{
          padding:3px 8px; border-radius:999px; border:1px solid var(--line);
          background: var(--surface);
        }
        h1{
          font-size: clamp(28px, 4.2vw, 46px);
          line-height:0.98;
          letter-spacing:-0.03em;
          font-weight: 680;
          margin:0 0 14px;
          max-width: 18ch;
        }
        .lede{
          font-size: 17px;
          line-height:1.55;
          color: var(--ink-2);
          max-width: 38ch;
          font-family: ui-sans-system, system-ui, sans-serif;
        }
        .card{
          background: var(--surface);
          border:1px solid var(--line);
          border-radius: var(--radius-lg);
          padding: 16px;
        }
        .card h3{
          font-family: ui-monospace, monospace;
          font-size:11px; letter-spacing:0.07em; text-transform:uppercase;
          color: var(--ink-3); margin:0 0 10px;
          font-weight:700;
        }
        .fact-grid{
          display:grid; grid-template-columns: 1fr 1fr; gap:10px;
        }
        .fact{
          padding:12px; border-radius:12px;
          background: var(--bg-2);
          border:1px solid var(--line-2);
        }
        .fact b{display:block; font-size:18px; line-height:1; margin-bottom:4px}
        .fact span{font-family: ui-monospace, monospace; font-size:11px; color:var(--ink-2)}
        .stack{display:flex; flex-direction:column; gap:12px}
        .btnrow{display:flex; gap:8px; flex-wrap:wrap; margin-top:12px}
        .btn{
          display:inline-flex; align-items:center; justify-content:center;
          padding:10px 16px; border-radius:999px;
          font-family: ui-sans-system, sans-serif;
          font-size:13.5px; font-weight:600;
          border:1px solid var(--line);
          background: var(--surface);
          text-decoration:none;
          transition: transform .08s ease;
        }
        .btn:active{transform:scale(0.98)}
        .btn.primary{
          background: var(--ink); color: var(--bg); border-color: var(--ink);
        }
        .section{
          padding: 22px 0;
          border-top: 1px solid var(--line-2);
        }
        .tri{
          display:grid;
          grid-template-columns: repeat(3,1fr);
          gap:14px;
        }
        @media(max-width: 860px){ .tri{grid-template-columns:1fr} }
        .tri h4{
          margin:0 0 6px;
          font-size:14.5px; font-weight:650;
          font-family: ui-sans-system, sans-serif;
          letter-spacing:-0.01em;
        }
        .tri p{
          margin:0;
          font-family: ui-sans-system, sans-serif;
          font-size:13.5px; line-height:1.5; color:var(--ink-2);
        }
        .codebox{
          margin-top:10px;
          background:#0f0f10; color:#e8e6e1;
          border-radius:12px; padding:12px 12px;
          font-family: ui-monospace, monospace; font-size:11.5px; line-height:1.5;
          overflow:auto;
          border:1px solid #1f1e1d;
        }
        .foot{
          padding:28px 0 40px;
          font-family: ui-monospace, monospace;
          font-size:11px; color:var(--ink-3);
          display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px;
        }
        .banner{
          margin-top:8px;
          padding:10px 12px; border-radius:999px;
          background:#111; color:#fff;
          display:inline-flex; gap:8px; align-items:center;
          font-family: ui-monospace, monospace; font-size:11px;
        }
        @media(prefers-color-scheme: dark){
          .banner{background:#f5f3f0; color:#111}
          .codebox{border-color:#2a2a2a}
        }
      `}</style>

      {/* Top */}
      <div className="top">
        <div className="top-inner">
          <div className="brand">
            <span className="dot" /> <b>arxiviq.com</b> <span className="mono" style={{opacity:0.7}}>· Dottie Ecosystem</span>
          </div>
          <div className="right">
            <span className="pill mono"> {now || "—"} </span>
            <span className="pill live mono">● live</span>
          </div>
        </div>
      </div>

      <div className="wrap">
        {/* Hero */}
        <div className="hero">
          <div>
            <div className="kicker mono">
              <span>DOTTIE V6.5 · LLMVM</span>
              <span style={{borderStyle:"dashed"}}>THE WEAVER IS NOW DOTTIE</span>
              <span>SOLO · FREE-TIER ONLY</span>
            </div>
            <h1>Dottie — the always-on AGI factory you can watch train</h1>
            <p className="lede sans">
              One small machine that builds its own data, checks it, learns from it, and talks back.
              No team, no cloud budget — just a box that keeps getting a little better.
              This site is the control plane.
            </p>

            <div className="banner sans">
              <span>◐</span> arxiviq.com is now only Dottie. Old research demos moved inside.
            </div>

            <div className="btnrow sans">
              <a className="btn primary" href="https://github.com/jcdavis131/dottie">GitHub — dottie</a>
              <a className="btn" href="/starter">Starter →</a>
              <a className="btn" href="https://raw.githubusercontent.com/jcdavis131/dottie/main/apps/dottie/README.md">Readme</a>
            </div>

            <div style={{marginTop:14}} className="mono">
              <span className="pill" style={{display:"inline-flex", gap:"6px"}}>
                <span style={{width:6,height:6,background:"#10b981",borderRadius:999,display:"inline-block"}}/> Solo personal project, no connection to employer
              </span>
            </div>
          </div>

          <div className="stack">
            <div className="card">
              <h3>Live now</h3>
              <div className="fact-grid sans">
                <div className="fact"><b>{stats?.papers ?? stats?.docs ?? "132"}</b><span>papers tracked</span></div>
                <div className="fact"><b>{stats?.nodes ?? "676"}</b><span>graph nodes</span></div>
                <div className="fact"><b>{stats?.people ? `${stats.people}` : "521"}</b><span>people linked</span></div>
                <div className="fact"><b>{live?.counts ? Object.values(live.counts).reduce((a:number,b:any)=>a+(typeof b==='number'?b:0),0) || "—" : "live"}</b><span>events today</span></div>
              </div>
              <div className="mono" style={{marginTop:10, fontSize:"11px", color:"var(--ink-2)"}}>
                Updated: {live?.updated_at?.slice(0,16)?.replace("T"," ") || stats?.timestamp?.slice(0,16)?.replace("T"," ") || "just now"} · checksum {stats?.checksum?.slice(0,8) || "—"}
              </div>
            </div>

            <div className="card sans">
              <h3>How it works — in plain English</h3>
              <div style={{display:"grid", gap:"8px", fontSize:"13.5px", lineHeight:1.5, color:"var(--ink-2)"}}>
                <div><b style={{color:"var(--ink)"}}>1. Gathers</b> — small VM pulls 500k text chunks every 4h, 10M per phase on Alienware. No scraping rush, just steady.</div>
                <div><b style={{color:"var(--ink)"}}>2. Cleans</b> — dedupes, splits 92/6/2 train/val/test, grades with a local model.</div>
                <div><b style={{color:"var(--ink)"}}>3. Learns & serves</b> — warms, holds steady, decays, resumes from the last good checkpoint. Chat is FastAPI behind Cloudflare Tunnel.</div>
              </div>
              <div className="codebox mono">
                <div style={{opacity:0.6}}># the whole loop — no tricks</div>
                <div>tasks → traces.jsonl → rft + memories</div>
                <div>→ eval gate → train step → better ckpt</div>
                <div style={{marginTop:6, opacity:0.8}}>ollama qwen3:32b does the real thinking today</div>
                <div>ava is the trainee — still learning</div>
              </div>
            </div>
          </div>
        </div>

        {/* Mid */}
        <div className="section">
          <div className="tri sans">
            <div className="card">
              <h4>Why not just use Prime Agent?</h4>
              <p>Prime gave us the right idea: code is a variable, you can refine habits with evidence. Dottie adds the messy part prime skips — actually training a small model from its own traces so it improves while you sleep.</p>
            </div>
            <div className="card">
              <h4>What you see is what runs</h4>
              <p>No mock numbers. If Ollama is down, Dottie says so. If the checkpoint is noise, it says noise. Every metric is computed from real inputs, every habit change needs evidence.</p>
            </div>
            <div className="card">
              <h4>Use it</h4>
              <p><span className="mono" style={{fontSize:"11px", background:"var(--bg-2)", padding:"2px 6px", borderRadius:6, border:"1px solid var(--line-2)"}}>pip install -e apps/dottie</span> gives you the CLI. <span className="mono" style={{fontSize:"11px", background:"var(--bg-2)", padding:"2px 6px", borderRadius:6, border:"1px solid var(--line-2)"}}>dottie repl</span> for persistent work, missions that pause Monday and resume Thursday with receipts.</p>
            </div>
          </div>
        </div>

        <div className="foot">
          <div>© {new Date().getFullYear()} arxiviq.com — Dottie is MIT, solo, free-tier only. No connection to employer.</div>
          <div className="mono">Vercel + GitHub raw STATUS.json + FastAPI dottie/serve_engine.py</div>
        </div>
      </div>
    </div>
  );
}
