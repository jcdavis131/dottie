"""Dottie tandem pair/queue — jarvisd-first with labeled filesystem fallback.

Implements: scout pair create | verify | status  +  scout queue push/poll/list

Prefer JARVIS_URL (default http://127.0.0.1:8790) + JARVIS_BEARER + X-Agent-Id.
Filesystem fallback at ~/.config/dottie pair + ~/.local/share/dottie/queue.
Legacy DOTTIE_API_URL (8787) kept as tertiary with source=legacy_8787.

Zero-deps true — stdlib only, pip/uv both work, no pip extra, torch-free.
"""

from __future__ import annotations

import json
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

import typer

app = typer.Typer(help="Dottie tandem pairing — local 6-char code + queue")

CONFIG_DIR = Path.home() / ".config" / "dottie"
DATA_DIR = Path.home() / ".local" / "share" / "dottie"
QUEUE_DIR = DATA_DIR / "queue"

PAIR_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L
DEFAULT_JARVIS_URL = "http://127.0.0.1:8790"


def _load_bearer() -> str:
    env = os.environ.get("DOTTIE_DEV_BEARER")
    if env:
        return env
    try:
        fp = CONFIG_DIR / ".env"
        if fp.exists():
            for ln in fp.read_text().splitlines():
                if ln.startswith("DOTTIE_DEV_BEARER="):
                    return ln.split("=", 1)[1].strip()
    except Exception:
        pass
    return "dm_dev_local"


def _api_base() -> str:
    return os.environ.get("DOTTIE_API_URL", "http://127.0.0.1:8787")


def _jarvis_base() -> str:
    return (os.environ.get("JARVIS_URL") or DEFAULT_JARVIS_URL).strip().rstrip("/")


def _jarvis_bearer() -> str | None:
    raw = (os.environ.get("JARVIS_BEARER") or "").strip()
    return raw or None


def _agent_id() -> str:
    return (os.environ.get("DOTTIE_AGENT_ID") or os.environ.get("JARVIS_AGENT") or "scout").strip() or "scout"


def _pair_file() -> Path:
    ws = os.environ.get("DOTTIE_WORKSPACE")
    if ws:
        return Path(ws) / ".dottie" / "pair.json"
    return CONFIG_DIR / "pair.json"


def _gen_code() -> str:
    return "".join(secrets.choice(PAIR_ALPHABET) for _ in range(6))


def _jarvis_headers(extra: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json", "X-Agent-Id": _agent_id()}
    bearer = _jarvis_bearer()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if extra:
        headers.update(extra)
    return headers


def _jarvis_json(method: str, path: str, body: dict | None = None, timeout: float = 5) -> dict | None:
    """POST/GET jarvisd. Returns parsed JSON (incl. ok:false bodies) or None on transport failure."""
    url = f"{_jarvis_base()}{path}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=_jarvis_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "error": f"jarvisd HTTP {e.code}"}
    except Exception:
        return None


def _write_pair_file(payload: dict) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    pf = _pair_file()
    pf.parent.mkdir(parents=True, exist_ok=True)
    try:
        pf.write_text(json.dumps(payload))
        try:
            os.chmod(pf, 0o600)
        except Exception:
            pass
    except Exception:
        pass
    return pf


def _read_pair_file() -> dict:
    pf = _pair_file()
    try:
        if pf.exists():
            return json.loads(pf.read_text())
    except Exception:
        pass
    return {}


@app.command("create")
def create(expire_min: int = typer.Option(10, help="expiry mins")):
    """Generate 6-char pairing code via jarvisd, else filesystem / legacy 8787."""
    # 1) Prefer jarvisd
    j = _jarvis_json("POST", "/api/pair/create", {"expire_min": expire_min})
    if j and j.get("ok") and j.get("code"):
        code = j["code"]
        exp = j.get("exp", int(time.time()) + expire_min * 60)
        created = j.get("created", int(time.time()))
        pf = _write_pair_file(
            {"code": code, "exp": exp, "created": created, "from": "jarvis", "source": "jarvis"}
        )
        typer.echo(
            json.dumps(
                {
                    "ok": True,
                    "code": code,
                    "exp": exp,
                    "source": "jarvis",
                    "api": True,
                    "pair_file": str(pf),
                }
            )
        )
        return code

    # 2) Filesystem fallback (labeled)
    code = _gen_code()
    exp = int(time.time()) + expire_min * 60
    created = int(time.time())
    pf = _write_pair_file(
        {"code": code, "exp": exp, "created": created, "from": "local", "source": "file"}
    )

    # 3) Legacy 8787 tertiary — if it returns a code, prefer that and label legacy_8787
    api_ok = False
    source = "file"
    try:
        url = f"{_api_base()}/api/dev/pair/create"
        req = urllib.request.Request(
            url,
            data=json.dumps({}).encode(),
            headers={
                "Authorization": f"Bearer {_load_bearer()}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            leg = json.loads(r.read().decode())
            if leg.get("code"):
                code = leg["code"]
                exp = leg.get("exp", exp)
                api_ok = True
                source = "legacy_8787"
                _write_pair_file(
                    {
                        "code": code,
                        "exp": exp,
                        "created": created,
                        "from": "legacy_8787",
                        "source": "legacy_8787",
                    }
                )
    except Exception:
        api_ok = False

    typer.echo(
        json.dumps(
            {
                "ok": True,
                "code": code,
                "exp": exp,
                "source": source,
                "api": api_ok,
                "pair_file": str(pf),
                "jarvis_unreachable": True,
            }
        )
    )
    return code


@app.command("verify")
def verify(
    code: str = typer.Argument(..., help="6-char code"),
    remote: bool = typer.Option(False, help="also verify against cloud arxiviq"),
):
    """Verify a code against jarvisd, then file / legacy / optional cloud."""
    code = code.strip().upper()
    if len(code) != 6:
        typer.echo(json.dumps({"ok": False, "error": "code must be 6 chars"}))
        raise typer.Exit(1)

    source = None
    # 1) jarvisd
    j = _jarvis_json("POST", "/api/pair/verify", {"code": code})
    if j is not None:
        ok = bool(j.get("ok") or j.get("paired"))
        source = "jarvis"
        out = {
            "ok": ok,
            "paired": ok,
            "code": code,
            "source": source,
            "jarvis": j,
            "local_ok": None,
            "api_ok": None,
            "cloud_ok": None,
        }
        if not ok:
            out["error"] = j.get("error") or "verify failed"
        typer.echo(json.dumps(out, indent=2))
        if not ok:
            raise typer.Exit(1)
        return

    # 2) local file
    local_ok = False
    try:
        jfile = _read_pair_file()
        local_ok = jfile.get("code", "").upper() == code and int(time.time()) < int(jfile.get("exp", 0))
    except Exception:
        local_ok = False

    # 3) legacy 8787
    api_ok = None
    try:
        url = f"{_api_base()}/api/dev/pair/verify"
        req = urllib.request.Request(
            url,
            data=json.dumps({"code": code}).encode(),
            headers={
                "Authorization": f"Bearer {_load_bearer()}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            leg = json.loads(r.read().decode())
            api_ok = bool(leg.get("ok") or leg.get("paired"))
            if api_ok:
                local_ok = True
                source = "legacy_8787"
    except Exception:
        api_ok = None

    if local_ok and source is None:
        source = "file"

    cloud_ok = None
    if remote:
        try:
            base = os.environ.get("DOTTIE_CLOUD_URL", "https://arxiviq.com")
            url = f"{base.rstrip('/')}/api/pair/verify"
            req = urllib.request.Request(
                url,
                data=json.dumps({"code": code}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                cloud = json.loads(r.read().decode())
                cloud_ok = bool(cloud.get("ok") or cloud.get("paired"))
        except Exception:
            cloud_ok = None

    ok = local_ok or bool(api_ok)
    out = {
        "ok": ok,
        "local_ok": local_ok,
        "api_ok": api_ok,
        "cloud_ok": cloud_ok,
        "code": code,
        "paired": ok,
        "source": source or ("file" if local_ok else "unreachable"),
        "jarvis_unreachable": True,
    }
    typer.echo(json.dumps(out, indent=2))
    if not out["ok"]:
        raise typer.Exit(1)


@app.command("status")
def status():
    """Show pairing status — jarvisd first, then file / legacy health."""
    j = _jarvis_json("GET", "/api/pair/status", None)
    if j is not None and j.get("ok") is not None:
        code = None
        pf = _read_pair_file()
        code = pf.get("code")
        if code:
            detail = _jarvis_json("GET", f"/api/pair/status?code={code}", None) or {}
            typer.echo(
                json.dumps(
                    {
                        "ok": True,
                        "source": "jarvis",
                        "code": code,
                        "exp": detail.get("exp") or pf.get("exp"),
                        "paired": bool(detail.get("paired")),
                        "jarvis": detail or j,
                        "queue_count": _queue_count(),
                    },
                    indent=2,
                )
            )
            return
        typer.echo(
            json.dumps(
                {
                    "ok": True,
                    "source": "jarvis",
                    "paired_count": j.get("paired_count"),
                    "count": j.get("count"),
                    "jarvis": j,
                    "queue_count": _queue_count(),
                },
                indent=2,
            )
        )
        return

    pf_data = _read_pair_file()
    health = None
    source = "file" if pf_data.get("code") else "unreachable"
    try:
        with urllib.request.urlopen(f"{_api_base()}/api/dev/health", timeout=4) as r:
            health = json.loads(r.read().decode())
            if health:
                source = "legacy_8787" if not pf_data.get("code") else source
    except Exception:
        health = None

    typer.echo(
        json.dumps(
            {
                "ok": True,
                "source": source,
                "code": pf_data.get("code"),
                "exp": pf_data.get("exp"),
                "paired": bool(pf_data.get("code") and time.time() < pf_data.get("exp", 0)),
                "local_api": bool(health),
                "health": health,
                "queue_count": _queue_count(),
                "jarvis_unreachable": True,
            },
            indent=2,
        )
    )


def _queue_count() -> int:
    try:
        ws = os.environ.get("DOTTIE_WORKSPACE")
        qdir = Path(ws) / ".dottie" / "queue" if ws else QUEUE_DIR
        if qdir.exists():
            return len(list(qdir.glob("*.json")))
    except Exception:
        pass
    return 0


# ---- queue subcommands ---------------------------------------------------

queue_app = typer.Typer(help="tandem queue local↔cloud")


@queue_app.command("push")
def queue_push(task: str = typer.Argument(..., help="task json or string"), frm: str = typer.Option("cloud", "--from")):
    """Push task into tandem queue — POST to api then filesystem fallback."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    eid = str(int(time.time() * 1000))
    doc = {"id": eid, "ts": int(time.time()), "task": task, "from": frm, "status": "queued"}
    pushed = False
    try:
        url = f"{_api_base()}/api/dev/queue/push"
        req = urllib.request.Request(
            url,
            data=json.dumps(doc).encode(),
            headers={"Authorization": f"Bearer {_load_bearer()}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            j = json.loads(r.read().decode())
            pushed = bool(j.get("ok"))
    except Exception:
        pushed = False
    if not pushed:
        (QUEUE_DIR / f"{eid}.json").write_text(json.dumps(doc))
    typer.echo(json.dumps({"ok": True, "id": eid, "pushed_api": pushed}))


@queue_app.command("poll")
def queue_poll(since: int = typer.Option(0, help="since ts ms")):
    """List queued tasks since ts."""
    tasks = []
    try:
        with urllib.request.urlopen(f"{_api_base()}/api/dev/queue/list?since={since}", timeout=5) as r:
            j = json.loads(r.read().decode())
            tasks = j.get("tasks", [])
    except Exception:
        pass
    if not tasks:
        try:
            if QUEUE_DIR.exists():
                for f in sorted(QUEUE_DIR.glob("*.json")):
                    try:
                        d = json.loads(f.read_text())
                        ts = d.get("ts", 0)
                        ts_ms = int(ts * 1000 if ts < 1e12 else ts)
                        if ts_ms >= since:
                            tasks.append(d)
                    except Exception:
                        pass
        except Exception:
            pass
    typer.echo(json.dumps({"ok": True, "tasks": tasks}, indent=2))


@queue_app.command("list")
def queue_list():
    queue_poll(0)


try:
    app.add_typer(queue_app, name="queue")
except Exception:
    pass
