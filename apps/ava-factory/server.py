"""
server.py - Live J-Lens Viewer
Solo personal project, no connection to employer

Wires FastAPI endpoints to ``ava.serve_engine.ServeEngine``. Checkpoint loads
in the lifespan handler so a broken ``AVA_CKPT`` fails at boot, not on first
request. Hot-reload of ``ckpt/latest`` (text pointer) lives inside the engine.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ava.serve_engine import get_engine

_REPO = Path(__file__).resolve().parent
# Compose mounts the shared reports volume at AVA_REPORTS_DIR (/reports);
# fall back to repo-local reports/ for bare-metal / smoke boots.
_REPORTS = Path(os.environ.get("AVA_REPORTS_DIR", str(_REPO / "reports")))
_EVAL_JSON = _REPORTS / "branch_eval_results_real.json"
_EVAL_MD = _REPORTS / "REPORT_REAL.md"
_REPORT_HTML = _REPORTS / "index.html"
# Read-only mount of the sibling agent-eval repo (see docker-compose.yml's
# `server` service) -- the Ava-claw / AgenticOS agentic hill-climb scoreboard,
# a different axis from the pretraining evals above (tool-use/grounding vs.
# perplexity/probes/J-Space). Optional: /agent_eval/scoreboard 404s cleanly
# if the mount isn't present (e.g. a bare-metal boot with no AGENT_EVAL_DIR).
_AGENT_EVAL_DIR = Path(os.environ.get("AGENT_EVAL_DIR", str(_REPO.parent / "agent-eval")))
_AGENT_EVAL_SCOREBOARD = _AGENT_EVAL_DIR / "scoreboard.md"

# All metric fields render as "—" until the page fetches real values from
# /jspace/inspect (and /jspace/eval_branch). No fabricated defaults: if the
# engine or eval report is unavailable, the UI says so instead of showing
# invented numbers.
VIEWER_HTML = """
<!DOCTYPE html><html><head><title>Ava J-Space Viewer v6.4</title>
<style>
body{background:#0a0a0f;color:#e0e0ff;font-family:Inter,monospace;margin:0;padding:20px}
.header{display:flex;justify-content:space-between;align-items:center}
.badge{padding:4px 12px;border-radius:20px;font-size:12px}
.audit{background:#6c5ce7;color:white}
.research{background:#ff4757;color:white;animation:pulse 2s infinite}
@keyframes pulse{0%{opacity:1}50%{opacity:0.6}100%{opacity:1}}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:20px}
.card{background:#151522;border:1px solid #252540;border-radius:12px;padding:16px}
.chip{display:inline-block;padding:4px 8px;margin:2px;border-radius:6px;background:#252540;font-size:12px}
.high{background:#00b89433;border:1px solid #00b894}
.med{background:#fdcb6e33;border:1px solid #fdcb6e}
.low{background:#636e7233;border:1px solid #636e72}
.safety{background:#ff475733;border:1px solid #ff4757;animation:pulse 1s infinite}
.bar{height:8px;background:#252540;border-radius:4px;overflow:hidden;margin:6px 0}
.fill{height:100%;background:linear-gradient(90deg,#6c5ce7,#00cec9)}
.muted{color:#888;font-size:12px}
button{padding:8px 16px;border-radius:8px;border:1px solid #6c5ce7;background:#1a1a2e;color:#e0e0ff;cursor:pointer;margin:2px}
button:disabled{opacity:0.3;cursor:not-allowed}
.toggle{display:flex;gap:8px;margin:10px 0}
.toggle .active{background:#6c5ce7;color:white}
</style></head><body>
<div class="header">
<h2>🧠 Ava J-Space Viewer v6.4 — Multi-JSpace S1/S2/Critic/Planner</h2>
<div><span id="modeBadge" class="badge audit">🔍 Read-Only (Audit)</span> <select id="branchSel"><option>base</option><option>code</option><option>math</option><option>chat</option></select></div>
</div>
<div id="banner" style="padding:10px;background:#6c5ce733;border-radius:8px;margin:10px 0">Read-only J-lens, no writes, safe for prod, surfaces leverage/blackmail/threat before output</div>
<div class="toggle">
<button id="auditBtn" class="active" onclick="setMode('audit')">🔍 Read-Only (Audit)</button>
<button id="researchBtn" onclick="setMode('research')">🧪 Intervene (Research)</button>
</div>
<div class="grid">
<div class="card"><h3>Top Concepts (verbalizable mass target 0.06)</h3><div id="concepts"><span class="muted">—</span></div><div>Mass: <span id="mass">—</span></div><div class="bar"><div id="massBar" class="fill" style="width:0%"></div></div></div>
<div class="card"><h3>Broadcast Strength (target 20%)</h3><div>Strength: <span id="bcast">—</span></div><div class="bar"><div id="bcastBar" class="fill" style="width:0%"></div></div><div class="muted">Half-life targets: S1 hl=8 tok | S2 hl=300 | Critic hl=30 | Planner hl=150</div></div>
<div class="card"><h3>Per-Space View</h3><div id="perSpace"><span class="muted">—</span></div><div>Routing: <span id="routing">—</span></div></div>
<div class="card"><h3>Interventions (research only)</h3><button id="btnSpider" onclick="intervene('spider','ant')">Spider→Ant</button><button onclick="intervene('soccer','rugby')">Soccer→Rugby</button><button onclick="intervene('france','china')">France→China broadcast</button><button onclick="intervene('spanish','french')">Spanish→French</button><div id="interveneLog" style="font-size:11px;margin-top:8px;color:#aaa"></div></div>
</div>
<div class="card" style="margin-top:16px"><h3>Layer Stream</h3><div id="stream" style="height:120px;overflow-y:auto;background:#0a0a0a;padding:8px;border-radius:8px;font-size:12px"><span class="muted">No stream yet — toggle the live WebSocket to see real per-block traces.</span></div><button onclick="toggleWS()">Toggle Live WebSocket</button></div>
<div class="card" style="margin-top:16px"><h3>5 Properties + Safety</h3><div id="props"><span class="muted">—</span></div><button onclick="runEval()">Run 5-Test Eval</button><div id="evalOut"></div></div>
<script>
const DEFAULT_PROMPT='The number of legs on the animal that spins webs is';
const SPACE_LABELS={system1:'S1 Fast',system2:'S2 Slow',critic:'Critic',planner:'Planner'};
let mode = new URLSearchParams(window.location.search).get('mode')||'audit';
function setMode(m){mode=m; if(m=='research'){if(!confirm('You will be able to EDIT internal workspace, causally changes outputs, all logged, requires ENABLE_JSPACE_WRITE=1. Confirm?')) return; window.location.search='?mode='+m;} else window.location.search='?mode='+m;}
function updateModeUI(){document.getElementById('modeBadge').textContent = mode=='audit'?'🔍 Read-Only (Audit)':'🧪 Intervene (Research)'; document.getElementById('modeBadge').className='badge '+(mode=='audit'?'audit':'research'); document.getElementById('banner').textContent = mode=='audit'?'Read-only J-lens, no writes, safe for prod, surfaces leverage/blackmail/threat before output':'You are editing internal workspace, causally changes outputs, all logged, requires ENABLE_JSPACE_WRITE=1'; document.getElementById('banner').style.background=mode=='audit'?'#6c5ce733':'#ff475733'; document.getElementById('auditBtn').className=mode=='audit'?'active':''; document.getElementById('researchBtn').className=mode=='research'?'active':''; let dis = mode!='research'; document.querySelectorAll('button').forEach(b=>{if(b.textContent.includes('→')) b.disabled=dis; if(dis) b.title='(research only)';});}
function fmt(x,d){return (typeof x==='number' && isFinite(x)) ? x.toFixed(d===undefined?3:d) : '—';}
function renderInspect(j){
  const cdiv=document.getElementById('concepts'); cdiv.innerHTML='';
  (j.top_concepts||[]).forEach(c=>{const s=document.createElement('span'); const p=c.p||0; s.className='chip '+(p>0.15?'high':p>0.05?'med':'low'); s.textContent=(c.concept||'').trim()+' '+fmt(p); cdiv.appendChild(s);});
  if(!(j.top_concepts||[]).length) cdiv.innerHTML='<span class="muted">no concepts returned</span>';
  document.getElementById('mass').textContent=fmt(j.verbalizable_mass);
  document.getElementById('massBar').style.width=Math.min(100,(j.verbalizable_mass||0)*1000)+'%';
  document.getElementById('bcast').textContent=fmt(j.broadcast_strength);
  document.getElementById('bcastBar').style.width=Math.min(100,(j.broadcast_strength||0)*100)+'%';
  const ps=j.per_space||{}; const lines=Object.keys(ps).map(k=>{const v=ps[k]; return (SPACE_LABELS[k]||k)+': broadcast '+fmt(v.broadcast)+' hl_est '+fmt(v.hl_est,1)+' mass '+fmt(v.mass);});
  document.getElementById('perSpace').innerHTML=lines.length?lines.join('<br>'):'<span class="muted">no per-space data</span>';
  const rp=j.route_probs||[]; document.getElementById('routing').textContent=rp.length? ['S1','S2','Critic','Planner'].map((n,i)=>n+' '+Math.round((rp[i]||0)*100)+'%').join(' ') : '—';
}
async function loadInspect(){
  try{
    const res=await fetch('/jspace/inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:DEFAULT_PROMPT})});
    if(!res.ok) throw new Error('HTTP '+res.status);
    renderInspect(await res.json());
  }catch(e){
    document.getElementById('concepts').innerHTML='<span class="muted">engine unavailable ('+e+') — boot the server with a real checkpoint (AVA_CKPT)</span>';
  }
}
async function loadEvalSummary(){
  const props=document.getElementById('props');
  try{
    const res=await fetch('/jspace/eval_branch?branch=all');
    if(res.status===404){props.innerHTML='<span class="muted">no eval report yet — run `make eval` to produce real measurements</span>'; return;}
    if(!res.ok) throw new Error('HTTP '+res.status);
    const j=await res.json();
    props.textContent=JSON.stringify(j).slice(0,400)+' …';
  }catch(e){
    props.innerHTML='<span class="muted">eval report unavailable ('+e+') — run `make eval`</span>';
  }
}
async function intervene(from,to){let branch=document.getElementById('branchSel').value||'base'; if(mode!='research'){alert('Intervene requires ?mode=research + ENABLE_JSPACE_WRITE=1. Research-only: editing internal workspace changes outputs causally. All interventions logged.'); return;} let res=await fetch('/jspace/intervene?mode=research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from,to,branch,text:DEFAULT_PROMPT})}); let j=await res.json(); document.getElementById('interveneLog').innerText = JSON.stringify(j,null,2); console.log('[J-SPACE INTERVENE AUDIT LOG]',{ts:Date.now(),from,to,branch});}
async function runEval(){let branch=document.getElementById('branchSel').value; let res=await fetch('/jspace/eval_branch?branch='+branch); if(res.status===404){document.getElementById('evalOut').innerText='no eval report yet — run `make eval` first'; return;} let j=await res.json(); document.getElementById('evalOut').innerText=JSON.stringify(j,null,2);}
let ws=null; function toggleWS(){if(ws){ws.close();ws=null;return;} ws=new WebSocket((location.protocol=='https:'?'wss://':'ws://')+location.host+'/jspace/stream'); ws.onopen=()=>{document.getElementById('stream').innerText=''; ws.send(DEFAULT_PROMPT);}; ws.onmessage=(e)=>{document.getElementById('stream').innerText+= '\\n'+e.data;};}
updateModeUI();
loadInspect();
loadEvalSummary();
</script></body></html>
"""


class InspectReq(BaseModel):
    text: str
    instruction: Optional[str] = None
    image: Optional[str] = None


class InterveneReq(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    branch: str = "base"
    text: Optional[str] = None
    space: str = "system2"
    from_c: Optional[str] = None
    to_c: Optional[str] = None

    @property
    def from_concept(self) -> str:
        return self.from_ or self.from_c or "spider"

    @property
    def to_concept(self) -> str:
        return self.to or self.to_c or "ant"


class GenerateReq(BaseModel):
    text: str
    max_tokens: int = 64
    temperature: float = 0.8
    task_type: str = "chat"


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant" — matches ava/tokenizer.py's frozen
    #            <|user|>/<|assistant|> specials (ids 0-5); no <|tool|> special
    #            exists, so tool results are also sent as role="user" (see
    #            AgenticOS/ava_bridge.py, which owns that convention).
    content: str


class ChatReq(BaseModel):
    messages: list[ChatMessage]
    max_tokens: int = 256
    temperature: float = 0.8


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Boot-time load: broken checkpoint fails here, not on first request.
    # Tests may set AVA_SKIP_ENGINE_BOOT=1 and inject a mock via get_engine.
    if os.environ.get("AVA_SKIP_ENGINE_BOOT", "0") != "1":
        get_engine()
    yield


app = FastAPI(title="Ava J-Space Viewer v6.4", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def root():
    return (
        "<a href='/dashboard'>/dashboard</a> (training run) · "
        "<a href='/ecosystem'>/ecosystem</a> (harness/skills/agent-eval) · "
        "<a href='/evals'>/evals</a> · "
        "<a href='/chat'>/chat</a> · "
        "<a href='/jspace/viewer'>/jspace/viewer</a> · "
        "<a href='/health'>/health</a> · "
        "<a href='/report'>/report</a>"
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    from ava.dashboard_html import DASHBOARD_HTML

    return HTMLResponse(DASHBOARD_HTML)


@app.get("/evals", response_class=HTMLResponse)
async def evals_page():
    from ava.evals_html import EVALS_HTML

    return HTMLResponse(EVALS_HTML)


@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    """The chat UI. Coexists with POST /chat (the JSON API below) on the same
    path -- FastAPI dispatches by method, so this only ever serves GET."""
    from ava.chat_html import CHAT_HTML

    return HTMLResponse(CHAT_HTML)


@app.get("/pipeline/status")
async def pipeline_status():
    from ava.pipeline_status import collect_status

    return collect_status()


@app.get("/ecosystem", response_class=HTMLResponse)
async def ecosystem():
    from ava.ecosystem_html import ECOSYSTEM_HTML

    return HTMLResponse(ECOSYSTEM_HTML)


@app.get("/ecosystem/status")
async def ecosystem_status():
    from ava.ecosystem_status import collect_ecosystem_status

    return collect_ecosystem_status()


@app.get("/health")
async def health():
    st = get_engine().stats()
    return {
        "status": "ok",
        "ckpt": st["ckpt"],
        "params": st["params"],
        "vocab": st["vocab"],
    }


@app.post("/generate")
async def generate(req: GenerateReq):
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=422, detail="text must be non-empty")
    return get_engine().generate(
        req.text,
        max_tokens=min(req.max_tokens, 256),
        temperature=req.temperature,
        task_type=req.task_type,
    )


_ROLE_TAGS = {"user": "<|user|>", "assistant": "<|assistant|>"}
# generate() has no early-stop on <|eos|>/<|user|> (it fills max_tokens every
# call — see ava/serve_engine.py:258's plain for-loop) — an undertrained chat
# checkpoint can ramble past its own turn into fabricated follow-up turns.
# Truncate at the first token that would start a new turn.
_TURN_END_RE = re.compile(r"<\|eos\|>|<\|user\|>|<\|assistant\|>")


@app.post("/chat")
async def chat(req: ChatReq):
    """Thin wrapper over ServeEngine.generate() using the <|user|>/<|assistant|>
    convention already frozen in ava/tokenizer.py (SPECIALS ids 0-5) — the same
    convention ava/datagen/chat_safety.py already generates training data in.
    AgenticOS/ava_bridge.py is the client: formats a ReAct tool-calling
    conversation into this shape and regex-parses the response back into the
    tool_calls shape harness.py's Ollama-backed chat() already returns, so the
    ReAct loop itself doesn't need to know which brain it's talking to.
    """
    if not req.messages:
        raise HTTPException(status_code=422, detail="messages must be non-empty")
    prompt = "".join(
        f"{_ROLE_TAGS.get(m.role, '<|user|>')}{m.content}" for m in req.messages
    ) + "<|assistant|>"
    result = get_engine().generate(
        prompt,
        max_tokens=min(req.max_tokens, 256),
        temperature=req.temperature,
        task_type="chat",
    )
    content = result["text"]
    m = _TURN_END_RE.search(content)
    if m:
        content = content[: m.start()]
    return {"content": content, "tokens": result["tokens"], "latency_ms": result["latency_ms"]}


@app.get("/report")
async def report():
    if not _REPORT_HTML.is_file():
        raise HTTPException(
            status_code=404, detail="run scripts/make_report.py first"
        )
    return FileResponse(_REPORT_HTML)


@app.get("/jspace/viewer", response_class=HTMLResponse)
async def viewer(mode: str = Query("audit")):
    return HTMLResponse(VIEWER_HTML)


@app.post("/jspace/inspect")
async def inspect(req: InspectReq):
    return get_engine().inspect(req.text)


@app.post("/jspace/intervene")
async def intervene(req: InterveneReq, mode: str = Query("audit")):
    env_write = os.getenv("ENABLE_JSPACE_WRITE", "0") == "1"
    if mode != "research" or not env_write:
        raise HTTPException(
            status_code=403,
            detail=(
                "Intervene requires?mode=research + ENABLE_JSPACE_WRITE=1. "
                "Research-only: editing internal workspace changes outputs causally. "
                "All interventions logged."
            ),
        )
    text = req.text or "The number of legs on the animal that spins webs is"
    return get_engine().intervene(
        text, req.from_concept, req.to_concept, space=req.space
    )


@app.post("/jspace/safety")
async def safety(req: InspectReq):
    scan = get_engine().inspect(req.text)["safety_scan"]
    hits = [w for w, p in scan.items() if w != "total" and float(p) > 0.01]
    # Also surface literal substring hits for operator visibility.
    lower = req.text.lower()
    for w in scan:
        if w != "total" and w in lower and w not in hits:
            hits.append(w)
    return {"safety_scan": scan, "hits": hits, "total": scan.get("total", 0.0)}


def _json_safe(obj: Any) -> Any:
    """Replace NaN/Inf so FastAPI's strict JSON encoder does not raise."""
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):  # NaN / Inf
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


@app.get("/jspace/eval_branch")
async def eval_branch(branch: str = "all"):
    if not _EVAL_JSON.is_file():
        raise HTTPException(
            status_code=404, detail="run eval first: make eval"
        )
    with open(_EVAL_JSON, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    if branch and branch != "all":
        if branch not in data:
            raise HTTPException(status_code=404, detail=f"unknown branch {branch!r}")
        return _json_safe({branch: data[branch]})
    return _json_safe(data)


@app.get("/jspace/eval_report")
async def eval_report():
    if not _EVAL_MD.is_file():
        raise HTTPException(
            status_code=404, detail="run eval first: make eval"
        )
    return {"report_markdown": _EVAL_MD.read_text(encoding="utf-8")}


@app.get("/agent_eval/scoreboard")
async def agent_eval_scoreboard():
    """agent-eval's scoreboard.md (Ava-claw / AgenticOS hill-climb results) --
    see ava_claw_run.py in the agent-eval repo. 404 if that repo isn't
    mounted or hasn't produced a scoreboard yet (no run against Ava so far
    is not an error state, just "nothing to show")."""
    if not _AGENT_EVAL_SCOREBOARD.is_file():
        raise HTTPException(
            status_code=404,
            detail="no agent-eval scoreboard found (not mounted, or no runs yet)",
        )
    return {"scoreboard_markdown": _AGENT_EVAL_SCOREBOARD.read_text(encoding="utf-8")}


@app.websocket("/jspace/stream")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    raw = await ws.receive_text()
    prompt = raw.strip() if raw and raw.strip() and raw.strip() != "subscribe" else (
        "The number of legs on the animal that spins webs is"
    )
    for block in get_engine().block_stream(prompt):
        await ws.send_text(json.dumps(block))
    await ws.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
