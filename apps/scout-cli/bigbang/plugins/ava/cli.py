# Solo personal project, no connection to employer, built with public/free-tier only
import typer
from bigbang.core.output import emit, is_json
from bigbang.core.registry import list_tools
from pathlib import Path
import json
import re
import time
import socket
import threading
import os
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any

app = typer.Typer(name="ava", help="🧠 Ava AGI Factory — brain of BigBang, local CUDA + Frontier eval", no_args_is_help=True)

def _resolve_factory_root() -> Path:
    """Resolve the Ava factory repo.

    Probes the dottie monorepo layout first (DOTTIE_ROOT/apps/ava-factory,
    ~/workspace/dottie/apps/ava-factory), then falls back to the standalone
    default ~/workspace/ava-agi-factory-v6-4 even when it doesn't exist yet.
    """
    candidates = []
    dottie = os.environ.get("DOTTIE_ROOT")
    if dottie:
        candidates.append(Path(dottie).expanduser() / "apps" / "ava-factory")
    candidates.append(Path.home() / "workspace" / "dottie" / "apps" / "ava-factory")
    for cand in candidates:
        try:
            if cand.exists():
                return cand
        except OSError:
            continue
    return Path.home() / "workspace" / "ava-agi-factory-v6-4"


FACTORY = _resolve_factory_root()


def _env_float(name: str, default: float) -> float:
    """Read a positive float from the environment, else fall back to `default`."""
    try:
        val = float(os.environ.get(name, ""))
        return val if val > 0 else default
    except (TypeError, ValueError):
        return default


# Hard ceiling (seconds) on a single factory subprocess. `_run_in_factory` uses
# capture_output=True, which buffers all stdout/stderr in memory until the child
# exits — so a hung job would block the CLI forever while growing that buffer
# unbounded. subprocess.run(timeout=...) force-kills it instead and raises
# TimeoutExpired. Override with FACTORY_SUBPROCESS_TIMEOUT (0/invalid = default).
FACTORY_SUBPROCESS_TIMEOUT = _env_float("FACTORY_SUBPROCESS_TIMEOUT", 900.0)


def _is_resolvable_fast(host: str, timeout: float = 0.8) -> bool:
    if not host:
        return False
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    if host == "host.docker.internal":
        allow = os.environ.get("OLLAMA_ALLOW_DOCKER_HOST") or os.environ.get("BIGBANG_USE_DOCKER_HOST") or os.environ.get("OLLAMA_BASE", "")
        if "host.docker.internal" not in allow:
            try:
                with open("/etc/hosts", "r", encoding="utf-8", errors="ignore") as f:
                    if "host.docker.internal" not in f.read():
                        return False
            except Exception:
                return False
    result: List[bool] = []
    def _do():
        try:
            socket.getaddrinfo(host, None)
            result.append(True)
        except Exception:
            result.append(False)
    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result[0] if result else False

# Try to import reusable llm helpers, but keep local fallback so no hard dep
try:
    from bigbang.core.llm import (
        get_ollama_base as _core_get_base,
        ollama_chat as _core_ollama_chat,
        list_ollama_models as _core_list_models,
        get_best_model as _core_best_model,
        extract_json_from_text as _extract_json,
        chat_with_metrics as _core_chat_metrics,
        koboldcpp_available as _core_kobold_available,
        OLLAMA_URLS,
        PREFERRED_MODELS,
    )
    _HAS_CORE_LLM = True
except Exception:
    _HAS_CORE_LLM = False
    _core_chat_metrics = None
    _core_kobold_available = None
    OLLAMA_URLS = [
        "http://localhost:11434",
        "http://host.docker.internal:11434",
    ]
    PREFERRED_MODELS = [
        "qwen3:32b",
        "qwen3:32b-instruct",
        "qwen3:14b",
        "qwen3:8b",
        "qwen3",
        "llama3.1:8b",
        "llama3.1",
        "qwen2.5:32b",
        "qwen2.5:14b",
        "qwen2.5:7b",
        "qwen2.5",
        "llama3",
        "llama3:8b",
        "mistral",
        "gemma3:4b",
    ]

    def _extract_json(text: str):
        if not text:
            return None
        t = text.strip()
        try:
            return json.loads(t)
        except Exception:
            pass
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.IGNORECASE)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except Exception:
                pass
        s = t.find("{")
        e = t.rfind("}")
        if s != -1 and e != -1 and e > s:
            try:
                return json.loads(t[s:e+1])
            except Exception:
                pass
        return None

# ---------- Caching for fast fallback ----------
_AVA_CACHED_BASE: Optional[str] = None
_AVA_CACHED_AT: float = 0.0
_AVA_CACHE_TTL: float = 30.0

def _clear_ava_cache():
    global _AVA_CACHED_BASE, _AVA_CACHED_AT
    _AVA_CACHED_BASE = None
    _AVA_CACHED_AT = 0.0

def _httpx_client_local(timeout: float = 2.0):
    try:
        import httpx
    except ImportError:
        return None
    try:
        to = httpx.Timeout(timeout, connect=min(timeout, 1.0))
    except Exception:
        to = timeout
    try:
        return httpx.Client(trust_env=False, timeout=to)
    except TypeError:
        try:
            return httpx.Client(timeout=to)
        except Exception:
            return None
    except Exception:
        return None

# ---------- Ollama helpers (spec requires these names) ----------

def _ollama_available() -> Optional[str]:
    """
    Tries http://localhost:11434/api/tags and http://host.docker.internal:11434/api/tags
    with httpx 2s timeout, return url base that works or None
    """
    global _AVA_CACHED_BASE, _AVA_CACHED_AT
    if _HAS_CORE_LLM:
        try:
            return _core_get_base(timeout=2.0)
        except Exception:
            pass

    now = time.time()
    if _AVA_CACHED_BASE is not None and (now - _AVA_CACHED_AT) < _AVA_CACHE_TTL:
        return _AVA_CACHED_BASE
    if _AVA_CACHED_AT and (now - _AVA_CACHED_AT) < 5.0 and _AVA_CACHED_BASE is None:
        return None

    # Env override
    env_base = os.environ.get("OLLAMA_BASE") or os.environ.get("OLLAMA_URL") or os.environ.get("OLLAMA_HOST")
    urls_try = []
    if env_base:
        b = env_base.rstrip("/")
        if b.endswith("/api/tags"):
            b = b[:-len("/api/tags")]
        urls_try.append(b.rstrip("/"))
    urls_try.extend(OLLAMA_URLS)

    try:
        import httpx  # noqa
    except ImportError:
        return None

    found = None
    for base in urls_try:
        b = base.rstrip("/")
        parsed = urlparse(b)
        host = parsed.hostname or ""
        if host not in ("localhost", "127.0.0.1", "::1", ""):
            if not _is_resolvable_fast(host, timeout=0.8):
                continue
        client = _httpx_client_local(timeout=2.0)
        if client is None:
            return None
        try:
            r = client.get(f"{b}/api/tags")
            if r.status_code == 200:
                found = b
                break
        except Exception:
            continue
        finally:
            try:
                client.close()
            except Exception:
                pass

    _AVA_CACHED_BASE = found
    _AVA_CACHED_AT = now
    return found


def _ollama_list_models_local(base: str) -> List[str]:
    if not base:
        return []
    try:
        parsed = urlparse(base)
        host = parsed.hostname or ""
        if host not in ("localhost", "127.0.0.1", "::1", ""):
            if not _is_resolvable_fast(host, timeout=0.8):
                return []
    except Exception:
        pass
    if _HAS_CORE_LLM:
        try:
            return _core_list_models(base=base, timeout=2.0)
        except Exception:
            pass
    client = _httpx_client_local(timeout=2.0)
    if client is None:
        return []
    try:
        r = client.get(f"{base.rstrip('/')}/api/tags")
        if r.status_code != 200:
            return []
        data = r.json()
        models = data.get("models", []) if isinstance(data, dict) else []
        names = []
        for m in models:
            if isinstance(m, dict):
                n = m.get("name") or m.get("model")
                if n:
                    names.append(n)
            elif isinstance(m, str):
                names.append(m)
        return names
    except Exception:
        return []
    finally:
        try:
            client.close()
        except Exception:
            pass


def _heuristic_route(task: str) -> Dict[str, Any]:
    """Fallback keyword router, no Ollama required — v0.6 with write/lab/brain/rtx/graphify"""
    q = task.lower()
    tools = list_tools()
    # Simple heuristic mapping
    if any(
        k in q
        for k in [
            "graphify",
            "pgraphify",
            "knowledge graph",
            "god node",
            "task compiler",
            "what connects",
            "shortest path",
            "impact analysis",
            "onboard repo",
        ]
    ):
        if "path" in q or "connect" in q:
            cmd = 'scout graphify path "Scout CLI" "Ava AGI Factory v6.4"'
        elif "task" in q or "wire" in q or "compile" in q:
            cmd = 'scout graphify task "wire Scout to Ava J-space"'
        elif "impact" in q or "breaks" in q:
            cmd = 'scout graphify impact "Scout CLI" --direction both'
        elif "onboard" in q:
            cmd = "scout graphify onboard"
        elif "build" in q or "ecosystem" in q:
            cmd = "scout graphify ecosystem"
        else:
            cmd = 'scout graphify query "how does Scout connect to Ava?"'
        return {
            "router": "stub",
            "picked_tool": "graphify",
            "picked_command": cmd,
            "confidence": 0.94,
            "reason": "graphify/pgraphify — query-first Personal Graphify baked into scout",
            "available_tools": list(tools.keys())[:12],
        }
    if any(
        k in q
        for k in [
            "judgment plane",
            "planes status",
            "planes compare",
            "compare herdr",
            "vs herdr",
            "differentiat",
            "flywheel",
            "five planes",
        ]
    ):
        cmd = "scout --json planes compare" if "compare" in q or "herdr" in q or "vs" in q else (
            "scout --json planes loop" if "flywheel" in q or "loop" in q else "scout --json planes status"
        )
        return {
            "router": "stub",
            "picked_tool": "planes",
            "picked_command": cmd,
            "confidence": 0.97,
            "reason": "judgment plane — Scout differentiator vs Herdr multiplexer",
            "available_tools": list(tools.keys())[:12],
        }
    if any(
        k in q
        for k in [
            "dottie",
            "dottie-claw",
            "teach scout",
            "skill install",
            "install skill",
            "openclaw skill",
        ]
    ):
        return {
            "router": "stub",
            "picked_tool": "skill",
            "picked_command": "scout skill teach --target dottie",
            "confidence": 0.96,
            "reason": "dottie-claw / teach — install Scout skills for the agent curriculum",
            "available_tools": list(tools.keys())[:12],
        }
    if any(
        k in q
        for k in [
            "herd",
            "herdr",
            "multiplexer",
            "agent status",
            "blocked agent",
            "wait for agent",
            "session ledger",
        ]
    ):
        if "wait" in q:
            cmd = "scout --json herd wait api --status done --timeout 120"
        elif "read" in q or "log" in q:
            cmd = "scout herd read api --lines 40"
        elif "start" in q or "run" in q:
            cmd = 'scout herd start --label api --cmd "pytest -q"'
        elif "herdr" in q:
            cmd = "scout --json herd herdr"
        else:
            cmd = "scout --json herd status"
        return {
            "router": "stub",
            "picked_tool": "herd",
            "picked_command": cmd,
            "confidence": 0.94,
            "reason": "herd/herdr — Scout session control surface (pairs with Herdr PTY multiplexer)",
            "available_tools": list(tools.keys())[:12],
        }
    if any(k in q for k in ["rtx", "offload", "alienware", "local gpu", "autoresearch"]):
        return {
            "router": "stub",
            "picked_tool": "rtx",
            "picked_command": "bb rtx status" if "status" in q else "bb rtx queue add --task \"...\" --program programs/program-ava.md" if "queue" in q or "offload" in q else "bb rtx results --best",
            "confidence": 0.95,
            "reason": "rtx/offload/alienware — bb rtx bridge to Alienware RTX 4080/4090",
            "available_tools": list(tools.keys())[:12],
        }
    if any(k in q for k in ["slop", "ai slop", "humanize", "authentic", "write", "blog", "email draft", "cold email"]):
        return {
            "router": "stub",
            "picked_tool": "write",
            "picked_command": "bb write check --text \"...\"" if "check" in q or "scan" in q else "bb write generate \"...\" --no-ollama",
            "confidence": 0.93,
            "reason": "write/authentic/slop — bb write scan/humanize/generate with real sources",
            "available_tools": list(tools.keys())[:12],
        }
    if any(k in q for k in ["mrr", "passive lab", "turnover shield", "turnover", "lab", "first 1k", "first 1000"]):
        return {
            "router": "stub",
            "picked_tool": "lab",
            "picked_command": "bb lab ideas" if "idea" in q else "bb lab mrr" if "mrr" in q else "bb lab shield",
            "confidence": 0.91,
            "reason": "Passive Lab / Turnover Shield / MRR — bb lab wired",
            "available_tools": list(tools.keys())[:12],
        }
    if any(k in q for k in ["goal", "memory", "brain sync", "hatch brain"]):
        return {
            "router": "stub",
            "picked_tool": "brain",
            "picked_command": "bb brain goals" if "goal" in q else "bb brain memory",
            "confidence": 0.90,
            "reason": "goals/memory/brain — bb brain bridge for Ava co-dev",
            "available_tools": list(tools.keys())[:12],
        }
    if "task" in q or "todo" in q or "lina" in q or "morning" in q or "afternoon" in q:
        # tasks plugin wired — check if bb tasks exists in plugin list via discovery
        return {
            "router": "stub",
            "picked_tool": "tasks",
            "picked_command": "bb tasks list" if "list" in q else "bb tasks status" if "status" in q else "bb tasks add 'New task from Ava'",
            "confidence": 0.92,
            "reason": "task mentions tasks/todo/Lina lists — Google Tasks wired",
            "available_tools": list(tools.keys())[:10],
        }
    if "hoops" in q or "basketball" in q or "nba" in q:
        return {
            "router": "stub",
            "picked_tool": "vector",
            "picked_command": "bb vector hoops --daily" if "daily" in q else "bb vector hoops --list",
            "confidence": 0.87,
            "reason": "task mentions hoops/basketball",
            "available_tools": list(tools.keys())[:10],
        }
    if "github" in q or "pr" in q or "pull request" in q:
        return {
            "router": "stub",
            "picked_tool": "tools",
            "picked_command": "bb tools search github",
            "confidence": 0.82,
            "reason": "task mentions github/pr",
            "available_tools": list(tools.keys())[:10],
        }
    if "family" in q or "brain" in q:
        return {
            "router": "stub",
            "picked_tool": "family",
            "picked_command": "bb family brain",
            "confidence": 0.8,
            "reason": "task mentions family brain",
            "available_tools": list(tools.keys())[:10],
        }
    if "ava" in q or "status" in q:
        return {
            "router": "stub",
            "picked_tool": "ava",
            "picked_command": "bb ava status",
            "confidence": 0.78,
            "reason": "task mentions ava",
            "available_tools": list(tools.keys())[:10],
        }
    if "tool" in q:
        return {
            "router": "stub",
            "picked_tool": "tools",
            "picked_command": "bb tools list",
            "confidence": 0.65,
            "reason": "generic tool query",
            "available_tools": list(tools.keys())[:10],
        }
    # default
    return {
        "router": "stub",
        "picked_tool": "system",
        "picked_command": "bb system doctor",
        "confidence": 0.5,
        "reason": "fallback",
        "available_tools": list(tools.keys())[:10],
    }


def _route_with_ollama(task: str) -> Dict[str, Any]:
    """Try real Ollama routing, raise if not available"""
    base = _ollama_available()
    if not base:
        raise RuntimeError("Ollama not available at localhost:11434 or host.docker.internal:11434")

    # Determine best model
    best_model = "qwen3:32b"
    if _HAS_CORE_LLM:
        try:
            best_model = _core_best_model(base=base, timeout=2.0)
        except Exception:
            pass
    else:
        models = _ollama_list_models_local(base)
        if models:
            # simple preference
            for pref in PREFERRED_MODELS:
                for m in models:
                    if pref.lower() in m.lower() or m.lower() in pref.lower():
                        best_model = m
                        break
                else:
                    continue
                break
            else:
                best_model = models[0]

    # Build prompt for routing
    tools = list_tools()
    tool_list_str = ", ".join(list(tools.keys())[:25])

    messages = [
        {"role": "system", "content": f"You are Ava router for BigBang CLI. Available tools: {tool_list_str}. Respond with JSON only: {{\"tool\": \"<name>\", \"command\": \"bb <tool> ...\", \"confidence\": 0.0-1.0, \"reason\": \"...\"}}. Task will be given."},
        {"role": "user", "content": f"Task: {task}\nReturn JSON with tool, command, confidence, reason. Command must be a valid bb command."},
    ]

    raw = None
    if _HAS_CORE_LLM:
        try:
            raw = _core_ollama_chat(model=best_model, messages=messages, json_mode=True, base=base, timeout=30.0)
        except Exception:
            raw = None
    else:
        client = _httpx_client_local(timeout=30.0)
        if client is None:
            raise RuntimeError("httpx not available")
        try:
            payload = {"model": best_model, "messages": messages, "stream": False, "format": "json"}
            r = client.post(f"{base}/api/chat", json=payload)
            if r.status_code == 200:
                data = r.json()
                msg = data.get("message", {}) if isinstance(data, dict) else {}
                raw = msg.get("content") if isinstance(msg, dict) else None
        except Exception:
            raw = None
        finally:
            try:
                client.close()
            except Exception:
                pass

    if not raw:
        raise RuntimeError("Ollama chat returned empty")

    parsed = _extract_json(raw)
    if not parsed:
        raise ValueError(f"Failed to parse Ollama JSON: {raw[:500]}")

    # Normalize
    picked_tool = parsed.get("tool") or parsed.get("picked_tool") or "system"
    picked_command = parsed.get("command") or parsed.get("picked_command") or f"bb {picked_tool} --help"
    confidence = parsed.get("confidence", 0.75)
    reason = parsed.get("reason", "ollama router")

    return {
        "router": "ollama",
        "ollama_base": base,
        "ollama_model": best_model,
        "picked_tool": picked_tool,
        "picked_command": picked_command,
        "confidence": confidence,
        "reason": reason,
        "raw": raw[:500],
    }


@app.command("status")
def status():
    compose = FACTORY / "docker-compose.yml"
    base = _ollama_available()
    models = _ollama_list_models_local(base) if base else []
    best = None
    if base:
        if _HAS_CORE_LLM:
            try:
                best = _core_best_model(base=base, timeout=2.0)
            except Exception:
                best = models[0] if models else None
        else:
            best = models[0] if models else None

    payload = {
        "factory": str(FACTORY),
        "exists": FACTORY.exists(),
        "compose": str(compose),
        "model": "1.17B d2048 48L YaRN 10k->1M, 4 workspaces, Frontier 11 cats",
        "judges": ["qwen3:32b via Ollama", "LocalHFJudge", "CriteriaJudge"],
        "role_in_bigbang": "Router + planner for bb agent run, evaluates if new tool automation is safe/useful",
        "ollama": {
            "available": base is not None,
            "base": base,
            "status": "up" if base else "down",
            "urls_tried": OLLAMA_URLS,
            "models": models,
            "models_count": len(models),
            "best_model": best,
            "preferred_order": PREFERRED_MODELS,
        },
        "next": "bb ava train --smoke, bb ava eval --frontier",
        "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
    }
    emit(payload, command="ava status")


@app.command("infer")
def infer(
    prompt: str = typer.Argument(..., help="the user prompt to send to the local model"),
    backend: str = typer.Option("ollama", "--backend", help="local runner: ollama | koboldcpp"),
    model: str = typer.Option("", "--model", help="model name; default = backend's best/loaded"),
    base: str = typer.Option("", "--base", help="override endpoint URL (else auto-detect)"),
    system: str = typer.Option("", "--system", help="optional system prompt"),
    json_mode: bool = typer.Option(False, "--json", help="ask the model for a JSON object"),
    max_tokens: int = typer.Option(0, "--max-tokens", help="cap generated tokens (0 = server default)"),
    context_shift: bool = typer.Option(False, "--context-shift", help="record that KoboldCpp ContextShift is enabled (telemetry only)"),
):
    """One local inference call against a pluggable backend, with tokens/sec telemetry.

    KoboldCpp is Ollama-API-compatible: launch it on :11434 and `--backend ollama`
    drives it unchanged. `--backend koboldcpp` instead targets its OpenAI-compatible
    :5001/v1 surface (auto-detected, or set KOBOLDCPP_BASE). The envelope is honest —
    on a backend failure it is ok:false + error, never a fabricated completion.

    Only ever install KoboldCpp from github.com/LostRuins/koboldcpp/releases/latest
    (the koboldcpp[.]com domain is a phishing clone).
    """
    if not _HAS_CORE_LLM or _core_chat_metrics is None:
        emit({"ok": False, "command": "ava infer",
              "error": "core.llm backend layer unavailable in this environment"},
             command="ava infer")
        raise typer.Exit(1)

    bk = (backend or "ollama").lower()
    mdl = model
    if not mdl:
        if bk in ("kobold", "koboldcpp", "openai"):
            mdl = "koboldcpp"  # KoboldCpp serves the one loaded GGUF; the name is ignored
        else:
            try:
                b = _ollama_available()
                mdl = (_core_best_model(base=b, timeout=2.0) if (b and _HAS_CORE_LLM) else "") or "qwen3:8b"
            except Exception:
                mdl = "qwen3:8b"

    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    res = _core_chat_metrics(
        bk, mdl, messages,
        base=(base or None), json_mode=json_mode,
        timeout=120.0, max_tokens=(max_tokens or None),
        context_shift=context_shift,
    )
    res["command"] = "ava infer"
    res["disclaimer"] = "Solo personal project, no connection to employer, built with public/free-tier only"
    emit(res, command="ava infer")
    if not res.get("ok"):
        raise typer.Exit(1)


def _run_in_factory(argv: list, yes: bool, command: str, description: str):
    """Run a command inside the factory repo, with an explicit confirm gate."""
    import subprocess
    if not FACTORY.exists():
        emit({
            "error": f"factory repo not present at {FACTORY}",
            "hint": "clone ava-agi-factory-v6-4 into ~/workspace first, "
                    "or use the dottie monorepo (apps/ava-factory; set DOTTIE_ROOT)",
        }, command=command)
        raise typer.Exit(1)
    if not yes:
        confirmed = typer.confirm(f"Run in {FACTORY}: {' '.join(argv)} ?")
        if not confirmed:
            emit({"cancelled": True, "cmd": " ".join(argv)}, command=command)
            raise typer.Exit(1)
    try:
        proc = subprocess.run(
            argv, cwd=str(FACTORY), capture_output=True, text=True,
            timeout=FACTORY_SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        # text=True means .stdout/.stderr are str|None; keep the partial capture.
        partial_out = exc.stdout if isinstance(exc.stdout, str) else ""
        partial_err = exc.stderr if isinstance(exc.stderr, str) else ""
        emit({
            "error": f"factory command timed out after {FACTORY_SUBPROCESS_TIMEOUT:g}s",
            "cmd": " ".join(argv),
            "cwd": str(FACTORY),
            "timeout_seconds": FACTORY_SUBPROCESS_TIMEOUT,
            "stdout": partial_out[-4000:],
            "stderr": partial_err[-2000:],
            "hint": "raise FACTORY_SUBPROCESS_TIMEOUT (seconds) for a longer ceiling, "
                    "or use `scout ava loop`, which streams long-running jobs instead "
                    "of buffering them",
            "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
        }, command=command)
        raise typer.Exit(124)  # conventional timeout exit code
    emit({
        "action": description,
        "cmd": " ".join(argv),
        "cwd": str(FACTORY),
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-2000:],
        "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
    }, command=command)
    if proc.returncode != 0:
        raise typer.Exit(proc.returncode)


LOOP_SCRIPT_REL = ("scripts", "dottie_continuous_loop.py")
LOOP_MODES = ("data", "train", "eval", "ecosystem", "all", "monitor", "aggregate")


def _loop_script() -> Path:
    """Path to the continuous-loop driver, resolved through the same FACTORY root.

    FACTORY already probes DOTTIE_ROOT/apps/ava-factory first (see
    _resolve_factory_root), so this inherits that lookup rather than re-deriving it.
    """
    return FACTORY.joinpath(*LOOP_SCRIPT_REL)


def _stream_in_factory(argv: list, yes: bool, command: str, description: str):
    """Run a long job in the factory and STREAM its output line-by-line.

    `_run_in_factory` uses subprocess.run(capture_output=True), which is right for the
    short scripts it drives but wrong here: the continuous loop runs for minutes to hours,
    and capture_output shows nothing until it exits. This uses Popen with an unbuffered
    child (PYTHONUNBUFFERED=1, bufsize=1) so progress is visible while it happens.

    In --json mode each line that parses as a JSON object is collected as a structured
    event and the rest are kept as text, so agents get one machine-readable payload while
    humans get a live feed. Solo personal project, public/free-tier only.
    """
    import subprocess

    script = _loop_script()
    if not script.exists():
        emit({
            "error": f"continuous loop script not found at {script}",
            "hint": "expected <factory>/scripts/dottie_continuous_loop.py; set DOTTIE_ROOT "
                    "to the monorepo root, or clone the factory into ~/workspace",
        }, command=command)
        raise typer.Exit(1)
    if not yes:
        if not typer.confirm(f"Run in {FACTORY}: {' '.join(argv)} ?"):
            emit({"cancelled": True, "cmd": " ".join(argv)}, command=command)
            raise typer.Exit(1)

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"          # the child must not sit on its own stdout
    json_mode = is_json()
    events: List[Dict[str, Any]] = []
    tail: List[str] = []
    try:
        proc = subprocess.Popen(
            argv, cwd=str(FACTORY), env=env, text=True, bufsize=1,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    except FileNotFoundError as e:
        emit({"error": f"cannot launch {argv[0]!r}: {e}",
              "hint": "uv is required for the isolated run path; install it or use "
                      "`scout ava train` for the direct script path"}, command=command)
        raise typer.Exit(1)

    assert proc.stdout is not None
    for line in proc.stdout:                # iterate as it arrives, never .read()
        line = line.rstrip("\n")
        if not line:
            continue
        if json_mode:
            stripped = line.lstrip()
            if stripped.startswith("{"):
                try:
                    events.append(json.loads(stripped))
                    continue
                except json.JSONDecodeError:
                    pass                     # not an event line; fall through to text
            tail.append(line)
            del tail[:-200]
        else:
            typer.echo(line)                 # immediate: no buffering between us and the user
    code = proc.wait()

    emit({
        "action": description,
        "cmd": " ".join(argv),
        "cwd": str(FACTORY),
        "script": str(script),
        "exit_code": code,
        "events": events,
        "output_tail": tail[-50:],
        "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
    }, command=command)
    if code != 0:
        raise typer.Exit(code)


@app.command("loop")
def loop(
    mode: str = typer.Option("all", "--mode", help=f"one of: {', '.join(LOOP_MODES)}"),
    full: bool = typer.Option(False, "--full", help="heavy mode (10M tokens, real train/eval)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="log commands without executing them"),
    preset: str = typer.Option("nano", "--preset", help="train preset nano/mini/base1b"),
    steps: int = typer.Option(0, "--steps", help="train max steps (0 = script default)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip confirmation prompt"),
):
    """Drive the continuous data/train/eval/ecosystem loop, streaming its output.

    Routes to <factory>/scripts/dottie_continuous_loop.py under `uv run` so the loop gets
    its own resolved environment rather than inheriting this CLI's.
    """
    if mode not in LOOP_MODES:
        emit({"error": f"unknown mode {mode!r}", "valid_modes": list(LOOP_MODES)},
             command="ava loop")
        raise typer.Exit(2)
    argv = ["uv", "run", "python", str(_loop_script()), "--mode", mode, "--preset", preset]
    if steps:
        argv += ["--steps", str(steps)]
    if full:
        argv.append("--full")
    if dry_run:
        argv.append("--dry-run")
    _stream_in_factory(argv, yes=yes, command="ava loop", description=f"ava loop --mode {mode}")


@app.command("data")
def data(
    tokens: str = typer.Option(None, "--tokens", help="e.g. 500K, 10M (default: script default)"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip confirmation prompt"),
):
    """Run the loop's data stage (harvest/pack) in the factory, streaming output."""
    argv = ["uv", "run", "python", str(_loop_script()), "--mode", "data"]
    if tokens:
        argv += ["--tokens", tokens]
    if dry_run:
        argv.append("--dry-run")
    _stream_in_factory(argv, yes=yes, command="ava data", description="ava data")


@app.command("train")
def train(
    smoke: bool = typer.Option(False),
    offline: bool = typer.Option(True),
    steps: int = typer.Option(1000),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip confirmation prompt"),
):
    """Run a real training job in the factory repo (requires it to be cloned locally)."""
    argv = ["python", "train_1b_deepspeed.py", f"--smoke={smoke}", f"--steps={steps}"]
    if offline:
        argv.append("--offline")
    _run_in_factory(argv, yes=yes, command="ava train", description="ava train")


@app.command("eval")
def eval_cmd(
    frontier: bool = typer.Option(False, help="run Frontier 11-cat rubric"),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip confirmation prompt"),
):
    """Run a real eval harness in the factory repo (requires it to be cloned locally)."""
    script = "eval_frontier_rubric.py" if frontier else "eval_branch_harness.py"
    _run_in_factory(["python", script], yes=yes, command="ava eval",
                    description=f"ava eval ({'frontier' if frontier else 'branch-harness'})")


@app.command("route")
def route(task: str = typer.Argument(..., help="task to route via Ava")):
    base = _ollama_available()
    result: Dict[str, Any]
    try:
        if base:
            result = _route_with_ollama(task)
        else:
            raise RuntimeError("Ollama not available")
    except Exception as e:
        # fallback to heuristic
        heuristic = _heuristic_route(task)
        heuristic["fallback_reason"] = str(e)[:300]
        heuristic["ollama_base"] = base
        result = heuristic

    payload = {
        "task": task,
        "router": result.get("router", "stub"),
        "ollama_base": result.get("ollama_base") or base,
        "picked_tool": result.get("picked_tool"),
        "picked_command": result.get("picked_command"),
        "confidence": result.get("confidence"),
        "reason": result.get("reason"),
        "ollama": {
            "available": base is not None,
            "base": base,
            "model": result.get("ollama_model"),
        },
        "details": result,
        "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
    }
    emit(payload, command="ava route")


def register(root):
    root.add_typer(app, name="ava")

# Solo personal project, no connection to employer, built with public/free-tier only
