# Solo personal project, no connection to employer, built with public/free-tier only
import typer
from bigbang.core.output import emit
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

FACTORY = Path.home() / "workspace" / "ava-agi-factory-v6-4"

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
        OLLAMA_URLS,
        PREFERRED_MODELS,
    )
    _HAS_CORE_LLM = True
except Exception:
    _HAS_CORE_LLM = False
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
    """Fallback keyword router, no Ollama required"""
    q = task.lower()
    tools = list_tools()
    # Simple heuristic mapping
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


@app.command("train")
def train(smoke: bool = typer.Option(False), offline: bool = typer.Option(True), steps: int = typer.Option(1000)):
    emit({
        "action": "ava train",
        "smoke": smoke,
        "offline": offline,
        "steps": steps,
        "cmd": f"docker compose --profile cuda up -d && python train_1b_deepspeed.py --smoke={smoke}",
        "audit": "Training logs -> ~/workspace/ava-agi-factory-v6-4/logs/, eval via Frontier rubric",
        "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
    }, command="ava train")


@app.command("eval")
def eval_cmd(frontier: bool = typer.Option(False, help="run Frontier 11-cat rubric")):
    emit({
        "eval": "frontier" if frontier else "branch-harness",
        "harness": "eval_branch_harness.py + eval_frontier_rubric.py",
        "judge": "Ollama qwen3:32b",
        "bigbang_use": "Ava scores if a new tool/skill is worth promoting to core",
        "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
    }, command="ava eval")


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
