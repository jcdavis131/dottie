import statsData from "../public/data/stats.json";
import AgentConductorPanel from "./components/AgentConductorPanel";

export default function Home() {
  const stats: any = (statsData as any) || { nodes: 676, edges: 758, docs: 132, papers: 132, people: 521, checksum: "a3f9c1e2" };
  const papers = stats.papers ?? stats.docs ?? 132;
  const nodes = stats.nodes ?? 676;
  const people = stats.people ?? 521;
  const edges = stats.edges ?? 758;
  return (
    <div className="site">
      <style>{`
        .site{--bg:#fcfcf8;--surface:#fff;--line:#e7e5e0;--line2:#ece9e3;--ink:#141210;--ink2:#6b6a64;--ink3:#9b9a95;--max:980px;--r-lg:20px;min-height:100vh;background:var(--bg);color:var(--ink);font-family:ui-sans-system,-apple-system,BlinkMacSystemFont,"SF Pro Text",Inter,sans-serif;-webkit-font-smoothing:antialiased}
        @media(prefers-color-scheme:dark){.site{--bg:#0f0e0d;--surface:#1a1816;--line:#2a2825;--line2:#24211e;--ink:#f5f3f0;--ink2:#a8a5a0;--ink3:#7a7874}}
        *{box-sizing:border-box}a{color:inherit}
        .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
        .top{position:sticky;top:0;z-index:10;backdrop-filter:blur(10px);background:color-mix(in srgb,var(--surface) 86%,transparent);border-bottom:1px solid var(--line)}
        .top-in{max-width:var(--max);margin:0 auto;padding:12px 18px;display:flex;justify-content:space-between;align-items:center;gap:12px}
        .brand{font-size:11.5px;color:var(--ink2);display:flex;gap:8px;align-items:center}
        .dot{width:6px;height:6px;border-radius:999px;background:#10b981;box-shadow:0 0 0 4px rgba(16,185,129,.15);display:inline-block}
        .pill{font-size:10.5px;padding:5px 10px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--ink2)}
        .pill.live{background:var(--ink);color:var(--bg);border-color:var(--ink)}
        .wrap{max-width:var(--max);margin:0 auto;padding:0 18px}
        .hero{padding:32px 0 18px;display:grid;grid-template-columns:1.15fr .85fr;gap:22px}
        @media(max-width:860px){.hero{grid-template-columns:1fr;padding:20px 0 12px}}
        .kicker{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
        .kicker span{font-size:10.5px;border:1px solid var(--line);background:var(--surface);padding:3px 8px;border-radius:999px;color:var(--ink3)}
        h1{font-size:clamp(28px,4.6vw,44px);line-height:.98;letter-spacing:-.03em;margin:0 0 12px;font-weight:730;max-width:16ch}
        .lede{font-size:16.5px;line-height:1.5;color:var(--ink2);max-width:36ch;margin:0 0 14px}
        .btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
        .b{padding:10px 16px;border-radius:999px;border:1px solid var(--line);background:var(--surface);text-decoration:none;font-size:13.5px;font-weight:600}
        .b.primary{background:var(--ink);color:var(--bg);border-color:var(--ink)}
        .card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);padding:14px 16px}
        .card h3{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink3);margin:0 0 10px;font-weight:700}
        .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
        .fact{padding:12px;border-radius:12px;background:var(--bg);border:1px solid var(--line2)}
        .fact b{display:block;font-size:18px;line-height:1}
        .fact span{font-size:11px;color:var(--ink2)}
        .stack{display:flex;flex-direction:column;gap:12px}
        .section{padding:18px 0;border-top:1px solid var(--line2)}
        .tri{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
        @media(max-width:860px){.tri{grid-template-columns:1fr}}
        .tri h4{margin:0 0 6px;font-size:14.5px;letter-spacing:-.01em}
        .tri p{margin:0;font-size:13.5px;line-height:1.5;color:var(--ink2)}
        .code{margin-top:10px;background:#111;color:#e9e6e1;border-radius:12px;padding:10px 12px;font-size:11.5px;line-height:1.5;border:1px solid #222}
        @media(prefers-color-scheme:dark){.code{background:#161412;border-color:#2a2825}}
        .foot{padding:24px 0 36px;font-size:11px;color:var(--ink3);display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;border-top:1px solid var(--line2);margin-top:14px}
      `}</style>
      <div className="top mono">
        <div className="top-in">
          <div className="brand"><span className="dot"/> <b>arxiviq.com</b> <span style={{opacity:.7}}>· Dottie factory</span></div>
          <div style={{display:"flex",gap:10,alignItems:"center"}}><a href="/conductor" style={{fontSize:11, padding:'5px 10px', borderRadius:999, background:'#0F1A12', border:'1px solid #1E3A2F', color:'#7CFFB2', textDecoration:'none'}}>ACD /conductor →</a><span className="pill">solo · MIT · no employer</span><span className="pill live">● live</span></div>
        </div>
      </div>
      <div className="wrap">
        <div className="hero">
          <div>
            <div className="kicker mono"><span>DOTTIE v6.5</span><span style={{borderStyle:"dashed"}}>WEAVER IS NOW DOTTIE</span><span>FREE-TIER ONLY</span></div>
            <h1>Dottie — small factory that learns out loud</h1>
            <p className="lede">One machine that gathers data, cleans it, learns from it, and talks back. No team, no big budget — just a box getting a little better each day. This site is the control plane.</p>
            <div className="btns"><a className="b primary" href="https://github.com/jcdavis131/dottie">GitHub — dottie</a><a className="b" href="/starter">Starter v5.1 →</a><a className="b" href="https://raw.githubusercontent.com/jcdavis131/dottie/main/apps/dottie/README.md">Readme</a></div>
            <div className="mono" style={{marginTop:12,fontSize:"11px",color:"var(--ink3)"}}>checksum {String(stats.checksum||"a3f9c1e2").slice(0,8)} · {String(stats.timestamp||"").slice(0,10)||"2026-08-05"} · local-first</div>
          </div>
          <div className="stack">
            <div className="card">
              <h3 className="mono">Live now — real numbers</h3>
              <div className="grid2 mono"><div className="fact"><b>{papers}</b><span>papers</span></div><div className="fact"><b>{nodes}</b><span>nodes</span></div><div className="fact"><b>{people}</b><span>people</span></div><div className="fact"><b>{edges}</b><span>edges</span></div></div>
              <div className="mono" style={{marginTop:10,fontSize:"11px",color:"var(--ink2)"}}>{stats.cache||"graph cache 84% hit"} · {stats.token_saving||"71.5× via Graphify"}</div>
            </div>
            <div className="card">
              <h3 className="mono">How it works — plain English</h3>
              <div style={{display:"grid",gap:"8px",fontSize:"13.5px",lineHeight:1.5,color:"var(--ink2)"}}><div><b style={{color:"var(--ink)"}}>1. Gathers</b> — pulls text steady, not fast. Hatch VM 500k every 4h, Alienware 10M chunks when free.</div><div><b style={{color:"var(--ink)"}}>2. Cleans</b> — dedupes, splits 92/6/2, grades locally. No vector DB, just files you can read.</div><div><b style={{color:"var(--ink)"}}>3. Learns & serves</b> — trains from its own traces, keeps last good checkpoint, serves chat when box is on.</div></div>
              <div className="code mono"><div style={{opacity:.6}}># the loop — no tricks</div><div>tasks → traces.jsonl → rft + memories</div><div>→ eval gate → train step → better ckpt</div><div style={{marginTop:6,opacity:.8}}>ollama qwen3:32b thinks today — ava still training</div></div>
            </div>
          </div>
        </div>
        <div className="section">
          <div className="tri">
            <div className="card"><h4>Why Dottie not just Prime Agent?</h4><p>Prime says code is a variable you can refine. Dottie adds the messy bit — actually training a tiny model from its own traces so it improves while you sleep. Solo, free-tier, honest 503 if down.</p></div>
            <div className="card"><h4>What you see is what runs</h4><p>No fake numbers. If Ollama is down, Dottie says so. If checkpoint is noise, it says noise. Every metric is computed from real inputs, every habit needs evidence.</p></div>
            <div className="card"><h4>Use it</h4><p><span className="mono" style={{background:"var(--bg)",padding:"2px 6px",border:"1px solid var(--line2)",borderRadius:6,fontSize:"11px"}}>pip install -e apps/dottie</span> gives you CLI. <span className="mono" style={{background:"var(--bg)",padding:"2px 6px",border:"1px solid var(--line2)",borderRadius:6,fontSize:"11px"}}>dottie repl</span> stays warm, missions pause Monday resume Thursday with receipts. Starter at <a href="/starter">/starter</a> → 10 sec clone.</p></div>
          </div>
        </div>

        {/* Agent Conductor */}
        <div className="section" id="conductor">
          <div className="mono" style={{fontSize:11, color:"var(--ink3)", marginBottom:12}}>Agent Conductor — one place to herd agents</div>
          <AgentConductorPanel />
        </div>

        <div className="foot mono"><div>© {new Date().getFullYear()} arxiviq.com — Dottie is MIT, solo, free-tier only. No connection to employer.</div><div>Vercel + GitHub raw + local box when on</div></div>
      </div>
    </div>
  );
}
