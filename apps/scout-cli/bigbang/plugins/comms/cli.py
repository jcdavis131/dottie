"""
comms plugin — file-based inbox via .dottie/registry.json
Zero-deps, stdlib-only, no torch. Implements scout --json comms ...
Mimics bundles/scripts/comms_bus.py but inside bigbang CLI.
"""

from __future__ import annotations
import json, pathlib, datetime
from typing import List, Dict, Any

# bigbang infra — tolerate if running outside bigbang (direct python)
try:
    from bigbang.core.contract import make_plugin_app
    from bigbang.core.output import emit
    app = make_plugin_app(
        "comms",
        "File-based comms bus via workspace/.dottie/registry.json — scout --json comms send --to agent:X",
        examples=[
            "scout --json comms send --to agent:llmvm-orchestrator --msg 'lane claimed' --from scout-prime",
            "scout --json comms inbox --agent scout-prime --n 20",
            "scout --json comms agents"
        ]
    )
    HAS_APP=True
except Exception:
    HAS_APP=False
    app=None

HOME = pathlib.Path.home()
ROOT = HOME / "workspace" / ".dottie"
REGISTRY = ROOT / "registry.json"
INBOX_DIR = ROOT / "inbox"

def _ensure():
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    INBOX_DIR.mkdir(parents=True, exist_ok=True)

def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def send(to_agent: str, msg: str, from_agent: str="orchestrator") -> Dict[str,Any]:
    _ensure()
    to_agent=to_agent.replace("agent:","").strip()
    from_agent=from_agent.replace("agent:","").strip()
    entry={
        "ts": _now_iso(),
        "nodeId": f"comms.{from_agent}->{to_agent}",
        "agentId": from_agent,
        "attempt":1,
        "latency_ms":120,
        "tokens_est":80,
        "status":"ok",
        "errorClass": None,
        "from": from_agent,
        "to": to_agent,
        "msg": msg,
        "channel":"file-inbox",
        "registry": str(REGISTRY)
    }
    inbox_path=INBOX_DIR / f"{to_agent}.jsonl"
    with inbox_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry)+"\n")
    # triple-write best effort
    for tpath in [
        HOME/"workspace"/"bundles"/"ultra"/"runs"/"timeline.jsonl",
        HOME/"workspace"/".scout"/"missions"/"_cron"/"timeline.jsonl"
    ]:
        try:
            tpath.parent.mkdir(parents=True, exist_ok=True)
            with tpath.open("a", encoding="utf-8") as tf:
                tf.write(json.dumps({**entry,"type":"comms_bus"})+"\n")
        except Exception:
            pass
    return entry

def list_inbox(agent:str, n:int=20):
    _ensure()
    agent=agent.replace("agent:","").strip()
    path=INBOX_DIR / f"{agent}.jsonl"
    if not path.exists():
        return []
    lines=path.read_text().strip().splitlines()[-n:]
    return [json.loads(l) for l in lines if l.strip()]

def list_agents():
    if not REGISTRY.exists():
        return []
    try:
        return json.loads(REGISTRY.read_text()).get("agents",[])
    except:
        return []

# Typer handlers if inside bigbang
if HAS_APP:
    import typer
    @app.command("send")
    def cmd_send(to: str = typer.Option(..., "--to","-t", help="agent:X or X"), msg: str=typer.Option(..., "--msg","-m"), from_agent: str=typer.Option("orchestrator","--from","--from-agent","-f")):
        entry=send(to, msg, from_agent)
        emit(entry)
    @app.command("list")
    def cmd_list(agent: str=typer.Option("scout-prime","--agent")):
        inbox=list_inbox(agent)
        emit({"agent":agent,"n":len(inbox),"inbox":inbox[-5:]})
    @app.command("inbox")
    def cmd_inbox(agent: str=typer.Option(..., "--agent"), n: int=typer.Option(20,"--n")):
        inbox=list_inbox(agent,n)
        emit({"agent":agent,"n":len(inbox),"inbox":inbox})
    @app.command("agents")
    def cmd_agents():
        agents=list_agents()
        emit({"n":len(agents),"agents":agents})

# for direct python test
if __name__=="__main__" and not HAS_APP:
    import sys
    print(json.dumps(send(sys.argv[1] if len(sys.argv)>1 else "llmvm-orchestrator","test"), indent=2))
