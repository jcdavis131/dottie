"use client";
export default function Starter(){
  return (
    <div className="starter">
      <style>{`
        .starter{
          --bg:#fcfcf8; --surface:#ffffff; --line:#e7e5e0; --ink:#141210; --ink2:#6b6a64; --ink3:#9b9a95;
          min-height:100vh; background:var(--bg); color:var(--ink);
          font-family: ui-sans-system,-apple-system,BlinkMacSystemFont,sans-serif;
          padding: 40px 18px 60px;
        }
        @media(prefers-color-scheme:dark){ .starter{--bg:#0f0e0d; --surface:#1a1816; --line:#2a2825; --ink:#f5f3f0; --ink2:#a8a5a0; --ink3:#7a7874} }
        .box{max-width:720px;margin:0 auto}
        .k{font-family:ui-monospace,monospace;font-size:11px;color:var(--ink3);margin-bottom:12px;letter-spacing:0.04em}
        h1{font-size: clamp(24px,4vw,34px); line-height:1.05; letter-spacing:-0.02em; margin:0 0 10px; font-weight:700}
        .lede{color:var(--ink2); font-size:15px; line-height:1.55; max-width:48ch; margin:0 0 18px}
        .card{background:var(--surface); border:1px solid var(--line); border-radius:16px; padding:14px 16px; margin:14px 0}
        .mono{font-family:ui-monospace,monospace}
        .pill{font-size:11px; padding:4px 8px; border-radius:999px; border:1px solid var(--line); background:var(--surface); display:inline-block}
        .btns{display:flex; flex-wrap:wrap; gap:8px; margin-top:16px}
        .b{padding:10px 16px; border-radius:999px; border:1px solid var(--line); background:var(--surface); text-decoration:none; font-size:13.5px; font-weight:600; color:inherit; display:inline-flex}
        .b.primary{background:var(--ink); color:var(--bg); border-color:var(--ink)}
        .list{display:grid; gap:10px; margin-top:10px}
        .it{padding:10px 12px; border-radius:12px; background:var(--surface); border:1px solid var(--line); font-size:13.5px; line-height:1.45; color:var(--ink2)}
        .it b{color:var(--ink)}
        .foot{margin-top:24px; font-size:11px; color:var(--ink3); font-family:ui-monospace,monospace}
      `}</style>
      <div className="box">
        <div className="k">arxiviq.com / starter · v5 Prime via Dottie</div>
        <h1>Scout v5 Prime — Mission OS</h1>
        <p className="lede">Not 13 agents theatre. Four fixes that make a basic harness actually keep running when you close the lid.</p>

        <div className="card mono" style={{fontSize:"12.5px"}}>
          <div style={{fontSize:"11px", color:"var(--ink3)", marginBottom:"6px"}}>Teammates — 10 sec:</div>
          git clone https://github.com/jcdavis131/scout-sota-starter ~/workspace/scout-lean
        </div>

        <div className="list">
          <div className="it"><b>1. Mission Log</b> — <span className="mono" style={{fontSize:"11px"}}>missions/id/timeline.jsonl</span> — pause Monday, resume Thursday with receipts you can read.</div>
          <div className="it"><b>2. Stuck Detector</b> — same loop twice, 2 fails, conf under 0.4 → one lateral lens, not spam. Shows what you missed.</div>
          <div className="it"><b>3. People Write-Back</b> — ask who someone is once, save trigger to MEMORY, under 50ms next time.</div>
          <div className="it"><b>4. Verifier That Ships</b> — score 1-10, fix biggest gap once if under 8, max 2 loops, then it goes out.</div>
        </div>

        <div className="card" style={{fontSize:"12.5px", color:"var(--ink2)"}}>
          Core under 900 bytes. No extra installs unless you want the graph. Works with your normal memory files.
          <div style={{marginTop:"8px"}} className="mono">Dottie view: <a href="/" style={{textDecoration:"underline"}}>arxiviq.com</a> — live factory</div>
        </div>

        <div className="btns">
          <a className="b primary" href="https://github.com/jcdavis131/scout-sota-starter">GitHub — scout-sota-starter</a>
          <a className="b" href="https://raw.githubusercontent.com/jcdavis131/scout-sota-starter/main/FULL_HARNESS_PROMPT_V5.md">v5 Prime prompt</a>
          <a className="b" href="https://raw.githubusercontent.com/jcdavis131/scout-sota-starter/main/extras/acne.md">ACNE optional</a>
        </div>

        <div className="foot">Copy one link, paste to teammate, they’re running. No keys, no OAuth. <a href="/">← back to arxiviq</a></div>
      </div>
    </div>
  );
}
