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

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from dottie.serve_engine import get_engine

_REPO = Path(__file__).resolve().parent
# Compose mounts the shared reports volume at AVA_REPORTS_DIR (/reports);
# fall back to repo-local reports/ for bare-metal / smoke boots.
# Host Spec-06 artifacts (eval_mini_base.json etc.) are also mounted read-only
# at AVA_HOST_REPORTS_DIR=/host_reports so /evals sees rung results without
# docker-cp into the volume.
_REPORTS = Path(os.environ.get("AVA_REPORTS_DIR", str(_REPO / "reports")))
_EVAL_JSON = _REPORTS / "branch_eval_results_real.json"  # legacy default; prefer resolve_*
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


class AssistantReq(BaseModel):
    messages: list[ChatMessage]
    max_steps: int = 4
    max_tokens: int = 160
    temperature: float = 0.7


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Boot-time load: broken checkpoint fails here, not on first request.
    # Tests may set AVA_SKIP_ENGINE_BOOT=1 and inject a mock via get_engine.
    if os.environ.get("AVA_SKIP_ENGINE_BOOT", "0") != "1":
        get_engine()
    yield


app = FastAPI(title="Ava J-Space Viewer v6.4", lifespan=lifespan)

# Opt-in CORS for the arxiviq.com assistant surface (spec 15 §5). Default OFF:
# when AVA_ASSISTANT_CORS is unset no middleware is added, so existing routes
# and the running dashboard are unaffected. Set it to a comma-separated origin
# allowlist (e.g. "https://arxiviq.com") only when exposing /assistant to a
# browser frontend through a tunnel.
_ASSISTANT_CORS = [o.strip() for o in os.environ.get("AVA_ASSISTANT_CORS", "").split(",") if o.strip()]
if _ASSISTANT_CORS:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ASSISTANT_CORS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

# Opt-in bearer auth for POST /assistant only (spec 15 §2.2 "Trust"). Default
# OFF (open locally); when AVA_ASSISTANT_TOKEN is set, /assistant requires
# `Authorization: Bearer <token>`. Never applied to the read-only status/HTML
# routes or any pre-existing endpoint.
def _require_assistant_token(authorization: Optional[str] = Header(None)) -> None:
    expected = os.environ.get("AVA_ASSISTANT_TOKEN", "")
    if not expected:
        return  # auth disabled
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="assistant requires a bearer token")
    if authorization.split(" ", 1)[1].strip() != expected:
        raise HTTPException(status_code=403, detail="invalid assistant token")


@app.get("/", response_class=HTMLResponse)
async def root():
    return (
        "<a href='/app'>/app</a> (Dottie console — chat + operations) · "
        "<a href='/dashboard'>/dashboard</a> (training run) · "
        "<a href='/network'>/network</a> (live architecture) · "
        "<a href='/ecosystem'>/ecosystem</a> (harness/skills/agent-eval) · "
        "<a href='/evals'>/evals</a> · "
        "<a href='/chat'>/chat</a> · "
        "<a href='/assistant'>/assistant</a> (Dottie tool-use assistant) · "
        "<a href='/jspace/viewer'>/jspace/viewer</a> · "
        "<a href='/health'>/health</a> · "
        "<a href='/report'>/report</a>"
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    from dottie.dashboard_html import DASHBOARD_HTML

    return HTMLResponse(DASHBOARD_HTML)


@app.get("/evals", response_class=HTMLResponse)
async def evals_page():
    from dottie.evals_html import EVALS_HTML

    return HTMLResponse(EVALS_HTML)


@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    """The chat UI. Coexists with POST /chat (the JSON API below) on the same
    path -- FastAPI dispatches by method, so this only ever serves GET."""
    from dottie.chat_html import CHAT_HTML

    return HTMLResponse(CHAT_HTML)


@app.get("/pipeline/status")
async def pipeline_status():
    from dottie.pipeline_status import collect_status

    return collect_status()


@app.get("/ecosystem", response_class=HTMLResponse)
async def ecosystem():
    from dottie.ecosystem_html import ECOSYSTEM_HTML

    return HTMLResponse(ECOSYSTEM_HTML)


@app.get("/ecosystem/status")
async def ecosystem_status():
    from dottie.ecosystem_status import collect_ecosystem_status

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


@app.get("/assistant", response_class=HTMLResponse)
async def assistant_page():
    """Dottie assistant UI. Coexists with POST /assistant (same method-dispatch
    pattern as /chat). Self-contained; safe with AVA_SKIP_ENGINE_BOOT=1."""
    from dottie.assistant_html import ASSISTANT_HTML

    return HTMLResponse(ASSISTANT_HTML)


@app.get("/assistant/status")
async def assistant_status():
    """Read-only capability/telemetry snapshot the arxiviq.com surface polls.
    Never 500s (collector swallows its own errors)."""
    from dottie.assistant_status import collect_assistant_status

    return collect_assistant_status()


@app.post("/assistant", dependencies=[Depends(_require_assistant_token)])
async def assistant(req: AssistantReq):
    """Dottie — the server-side ReAct tool loop (spec 15 §5). Grounded,
    trust-gated, telemetered. Degrades to a structured 503 when the engine is
    absent (AVA_SKIP_ENGINE_BOOT=1) rather than crashing."""
    from dottie.assistant import engine_generate_fn, run_assistant

    if not req.messages:
        raise HTTPException(status_code=422, detail="messages must be non-empty")
    try:
        engine = get_engine()
    except Exception as exc:  # broken/absent checkpoint -> graceful 503
        raise HTTPException(
            status_code=503,
            detail=f"assistant engine unavailable ({type(exc).__name__}); "
                   "the trainer likely owns the GPU (AVA_SKIP_ENGINE_BOOT=1)",
        )
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    result = run_assistant(
        messages,
        engine_generate_fn(engine),
        sandbox_root=_REPO,
        max_steps=min(req.max_steps, 6),
        max_tokens=min(req.max_tokens, 200),
        temperature=req.temperature,
    )
    return result.as_dict()


# Research service (:8100, apps/dottie) proxy. The webapp fetches :8100
# directly first; when the browser can't (CORS allow-list, tunnel), this
# server-side hop keeps the Research panel honest instead of dark. 502 with the
# real error when the service is down — never a fabricated body.
_RESEARCH_URLS = [
    u.strip().rstrip("/")
    for u in os.environ.get(
        "AVA_RESEARCH_URL",
        # In-container (Docker Desktop) the host's :8100 is host.docker.internal;
        # bare-metal boots reach it on localhost. Try both, first hit wins.
        "http://host.docker.internal:8100,http://localhost:8100",
    ).split(",")
    if u.strip()
]


@app.get("/research/status")
async def research_status_proxy():
    import asyncio
    import urllib.request

    def _fetch(url: str) -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=4) as resp:  # noqa: S310 — operator-configured URL
            return json.loads(resp.read().decode("utf-8"))

    errors: list[str] = []
    for base in _RESEARCH_URLS:
        url = f"{base}/research/status"
        try:
            data = await asyncio.to_thread(_fetch, url)
            return {"ok": True, "source": url, "status": data}
        except Exception as exc:  # noqa: BLE001 — report, don't fabricate
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=502,
        content={"ok": False, "error": "; ".join(errors), "tried": _RESEARCH_URLS},
    )


@app.get("/report", response_class=HTMLResponse)
async def report():
    """Live, screenshot-optimized training report. Packs the full pipeline
    status into one viewport for sharing with LLM agent assistants."""
    from dottie.report_html import REPORT_HTML

    return HTMLResponse(REPORT_HTML)


@app.get("/network", response_class=HTMLResponse)
async def network_page():
    """Live neural-network visualizer: config architecture + trainer peel +
    CPU checkpoint weight-group norms. Safe with AVA_SKIP_ENGINE_BOOT=1."""
    from dottie.network_html import NETWORK_HTML

    return HTMLResponse(NETWORK_HTML)


@app.get("/network/status")
async def network_status(norms: int = 0):
    """JSON for the network visualizer (architecture + live + optional norms).

    Pass ``?norms=1`` to peek CPU weight-group RMS from the latest checkpoint
    (cached by mtime). Heavy I/O runs in a worker thread so live polls stay snappy.
    """
    import asyncio

    from dottie.network_viz import collect_network_status

    return await asyncio.to_thread(
        collect_network_status, include_ckpt_norms=bool(norms)
    )

@app.get("/report/offline")
async def report_offline():
    """Pre-built static training report from scripts/make_report.py (loss
    curves, LR schedule, half-lives, routing, eval). Kept as a sibling so
    the live /report page stays focused on a single-screen summary."""
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


@app.get("/jspace/eval_catalog")
async def eval_catalog():
    """List available Spec-06 harness JSON artifacts (mini/nano/legacy)."""
    from dottie.eval_artifacts import list_eval_jsons, resolve_eval_json

    active = resolve_eval_json()
    return {
        "active": str(active) if active else None,
        "active_name": active.name if active else None,
        "artifacts": list_eval_jsons(),
    }


@app.get("/jspace/eval_branch")
async def eval_branch(
    branch: str = "all",
    source: str | None = Query(default=None, description="eval_mini_base | legacy | …"),
):
    from dottie.eval_artifacts import load_eval_json, resolve_eval_json

    path = resolve_eval_json(source=source) or (
        _EVAL_JSON if _EVAL_JSON.is_file() else None
    )
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="no eval JSON found — run harness with --out-json reports/eval_<preset>_base.json",
        )
    data: dict[str, Any] = load_eval_json(path)
    data.setdefault("meta", {})
    data["meta"]["_artifact"] = path.name
    data["meta"]["_artifact_path"] = str(path)
    if branch and branch != "all":
        if branch not in data:
            raise HTTPException(status_code=404, detail=f"unknown branch {branch!r}")
        return _json_safe({branch: data[branch], "meta": data.get("meta")})
    return _json_safe(data)


@app.get("/jspace/eval_report")
async def eval_report(
    source: str | None = Query(default=None, description="eval_mini_base | legacy | …"),
):
    from dottie.eval_artifacts import resolve_compare_md, resolve_eval_md

    path = resolve_eval_md(source=source) or (_EVAL_MD if _EVAL_MD.is_file() else None)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="no eval markdown found — run harness with --out-md reports/eval_<preset>_base.md",
        )
    body: dict[str, Any] = {
        "report_markdown": path.read_text(encoding="utf-8"),
        "artifact": path.name,
    }
    compare = resolve_compare_md()
    if compare is not None:
        body["compare_markdown"] = compare.read_text(encoding="utf-8")
        body["compare_artifact"] = compare.name
    return body


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


# The Dottie console SPA (dottie/webapp — plain ES modules, no build step, no
# CDN). Mounted last so it can never shadow an API route; check_dir=False keeps
# boot alive on a checkout without the webapp (requests then 404 honestly).
# fastapi.staticfiles is starlette's — already a dependency, nothing new.
from fastapi.staticfiles import StaticFiles  # noqa: E402

app.mount(
    "/app",
    StaticFiles(directory=str(_REPO / "dottie" / "webapp"), html=True, check_dir=False),
    name="webapp",
)


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
