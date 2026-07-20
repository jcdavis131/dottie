# Solo personal project, no connection to employer, built with public/free-tier only
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import typer

from bigbang.core.output import emit
from bigbang.core.registry import list_tools


def _is_resolvable_fast(host: str, timeout: float = 0.8) -> bool:
    if not host:
        return False
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    if host == "host.docker.internal":
        allow = (
            os.environ.get("OLLAMA_ALLOW_DOCKER_HOST")
            or os.environ.get("BIGBANG_USE_DOCKER_HOST")
            or os.environ.get("OLLAMA_BASE", "")
        )
        if "host.docker.internal" not in allow:
            try:
                with open("/etc/hosts", encoding="utf-8", errors="ignore") as f:
                    if "host.docker.internal" not in f.read():
                        return False
            except Exception:
                return False
    result: list[bool] = []

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


# Try to reuse core llm helpers
try:
    from bigbang.core.llm import (
        OLLAMA_URLS,
        PREFERRED_MODELS,
        extract_json_from_text,
        get_best_model,
        get_ollama_base,
        list_ollama_models,
        ollama_chat,
    )

    _HAS_LLM = True
except Exception:
    _HAS_LLM = False
    OLLAMA_URLS = ["http://localhost:11434", "http://host.docker.internal:11434"]
    PREFERRED_MODELS = [
        "qwen3:32b",
        "qwen3",
        "llama3.1:8b",
        "llama3.1",
        "qwen2.5:32b",
        "qwen2.5",
    ]

    _FALLBACK_CACHE_BASE: str | None = None
    _FALLBACK_CACHE_AT: float = 0.0

    def _httpx_client_fallback(timeout: float = 2.0):
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

    def extract_json_from_text(text: str):
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
        s = t.find("[")
        e = t.rfind("]")
        if s != -1 and e != -1 and e > s:
            try:
                return json.loads(t[s : e + 1])
            except Exception:
                pass
        s = t.find("{")
        e = t.rfind("}")
        if s != -1 and e != -1 and e > s:
            try:
                return json.loads(t[s : e + 1])
            except Exception:
                pass
        return None

    def get_ollama_base(timeout=2.0):
        global _FALLBACK_CACHE_BASE, _FALLBACK_CACHE_AT
        now = time.time()
        if _FALLBACK_CACHE_BASE is not None and (now - _FALLBACK_CACHE_AT) < 30.0:
            return _FALLBACK_CACHE_BASE
        if (
            _FALLBACK_CACHE_AT
            and (now - _FALLBACK_CACHE_AT) < 5.0
            and _FALLBACK_CACHE_BASE is None
        ):
            return None
        try:
            import httpx
        except ImportError:
            return None
        found = None
        for base in OLLAMA_URLS:
            parsed = urlparse(base)
            host = parsed.hostname or ""
            if host not in ("localhost", "127.0.0.1", ""):
                if not _is_resolvable_fast(host, timeout=0.8):
                    continue
            client = _httpx_client_fallback(timeout=timeout)
            if client is None:
                return None
            try:
                r = client.get(f"{base.rstrip('/')}/api/tags")
                if r.status_code == 200:
                    found = base.rstrip("/")
                    break
            except Exception:
                continue
            finally:
                try:
                    client.close()
                except Exception:
                    pass
        _FALLBACK_CACHE_BASE = found
        _FALLBACK_CACHE_AT = now
        return found

    def ollama_chat(model, messages, json_mode=False, base=None, timeout=60.0):
        if base is None:
            base = get_ollama_base(timeout=2.0)
        if not base:
            return None
        client = _httpx_client_fallback(timeout=timeout)
        if client is None:
            return None
        try:
            payload = {"model": model, "messages": messages, "stream": False}
            if json_mode:
                payload["format"] = "json"
            r = client.post(f"{base}/api/chat", json=payload)
            if r.status_code != 200:
                return None
            data = r.json()
            if isinstance(data, dict):
                msg = data.get("message", {})
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if content:
                        return content
                if "response" in data:
                    return data["response"]
            return None
        except Exception:
            return None
        finally:
            try:
                client.close()
            except Exception:
                pass

    def list_ollama_models(base=None, timeout=2.0):
        return []

    def get_best_model(base=None, timeout=2.0):
        return "qwen3:32b"


app = typer.Typer(
    name="agent",
    help="🤖 Agent — Ava-native planner that routes to any tool",
    no_args_is_help=True,
)


def _httpx_client(timeout: float = 2.0):
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


def _heuristic_plan(task: str) -> dict[str, Any]:
    q = task.lower()
    tools = list_tools()
    plan: list[str] = []

    builtin_hints = {
        "task": "bb tasks list",
        "todo": "bb tasks list",
        "lina": "bb tasks lists",
        "morning": "bb tasks list",
        "github": "bb tools search github",
        "pr": "bb tools search github",
        "vector": "bb vector list",
        "hoops": "bb vector hoops --daily"
        if "daily" in q
        else "bb vector hoops --list",
        "tennis": "bb tennis serve --help",
        "family": "bb family brain",
        "brain": "bb brain goals",
        "memory": "bb brain memory",
        "goals": "bb brain goals",
        "ava": "bb ava status",
        "tool": "bb tools list",
        "mcp": "bb mcp manifest",
        "system": "bb system doctor",
        "slop": "bb write scan -t '...'",
        "write": "bb write check -t '...'",
        "authentic": "bb write generate 'Turnover Shield email' --no-ollama",
        "humanize": "bb write humanize -t '...'",
        "mrr": "bb lab mrr",
        "passive": "bb lab ideas",
        "turnover": "bb lab shield",
        "lab": "bb lab ideas",
        "shield": "bb lab shield",
        "rtx": "bb rtx status",
        "offload": "bb rtx queue add --task '...' --program programs/program-ava.md",
        "alienware": "bb rtx status",
        "autoresearch": "bb rtx programs",
        "graphify": "scout graphify query 'how does Scout connect to Ava?'",
        "pgraphify": "scout graphify onboard",
        "knowledge graph": "scout graphify onboard",
        "god node": "scout graphify onboard",
        "task compiler": "scout graphify task 'wire Scout to Ava'",
        "herd": "scout --json herd status",
        "multiplexer": "scout --json herd herdr",
        "blocked": "scout --json herd list --status blocked",
        "dottie": "scout skill teach --target dottie",
        "skill": "scout skill list",
        "teach": "scout skill teach --target dottie",
        "curriculum": "scout skill show scout",
        "planes": "scout --json planes status",
        "judgment": "scout --json planes thesis",
        "herdr": "scout --json planes compare",
        "flywheel": "scout --json planes loop",
        "differentiat": "scout --json planes compare",
    }

    for k, v in builtin_hints.items():
        if k in q:
            if v not in plan:
                plan.append(v)

    for name, m in tools.items():
        desc = m.get("description", "").lower()
        if any(word in name.lower() or word in desc for word in q.split()[:6]):
            cmd = f"bb {name} --help"
            if len(plan) < 5 and cmd not in plan:
                if name in ("vector", "family", "ava", "tools", "mcp", "system"):
                    continue
                plan.append(cmd)

    if not plan:
        plan = ["bb system doctor", "bb tools list", "bb mcp manifest"]

    cleaned = []
    for p in plan:
        if not p.startswith("bb "):
            cleaned.append(f"bb {p}")
        else:
            cleaned.append(p)

    return {
        "planner_type": "heuristic",
        "plan": cleaned[:6],
        "available_tools": list(tools.keys())[:20],
        "reason": "keyword matching + builtin hints",
    }


def _ollama_planner(task: str, system_prefix: str | None = None) -> dict[str, Any]:
    base = get_ollama_base(timeout=2.0)
    if not base:
        raise RuntimeError(
            "Ollama not available at localhost:11434 or host.docker.internal:11434"
        )

    best_model = get_best_model(base=base, timeout=2.0) if _HAS_LLM else "qwen3:32b"

    tools = list_tools()
    tool_desc = "\n".join(
        [
            f"- bb {name}: {m.get('description', '')[:80]}"
            for name, m in list(tools.items())[:25]
        ]
    )

    # A dynamic profile (Hermes/OpenClaw, core.profiles) prepends its system role so the
    # planner operates inside that loop's doctrine.
    system = f'You are Ava planner for BigBang CLI. Available tools:\n{tool_desc}\nYou must output JSON only with a plan: {{"plan": ["bb ...", "bb ..."], "reason": "..."}}. Plan should be 2-4 bb commands to accomplish task. Use only bb commands.'
    if system_prefix:
        system = system_prefix + "\n\n" + system
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"Task: {task}\nReturn JSON with plan array of bb commands.",
        },
    ]

    raw = ollama_chat(
        model=best_model, messages=messages, json_mode=True, base=base, timeout=30.0
    )
    if not raw:
        raise RuntimeError("Ollama chat empty response")

    parsed = extract_json_from_text(raw)
    if not parsed:
        raise ValueError(f"Failed to parse planner JSON: {raw[:500]}")

    plan = parsed.get("plan") if isinstance(parsed, dict) else parsed
    if isinstance(parsed, dict) and "plan" in parsed:
        plan = parsed["plan"]
    if not isinstance(plan, list):
        # try steps
        if isinstance(parsed, dict):
            plan = parsed.get("steps") or []

    normalized = []
    if isinstance(plan, list):
        for item in plan:
            if isinstance(item, str):
                if item.startswith("bb "):
                    normalized.append(item)
                else:
                    normalized.append(f"bb {item}")
            elif isinstance(item, dict):
                cmd = item.get("command") or item.get("cmd") or item.get("tool")
                if cmd:
                    if isinstance(cmd, str) and cmd.startswith("bb "):
                        normalized.append(cmd)
                    elif isinstance(cmd, str):
                        normalized.append(f"bb {cmd}")
    if not normalized:
        raise ValueError("Ollama planner returned empty plan")

    return {
        "planner_type": "ollama",
        "planner_model": best_model,
        "planner_base": base,
        "plan": normalized[:6],
        "reason": parsed.get("reason", "ollama qwen3:32b + Frontier rubric")
        if isinstance(parsed, dict)
        else "ollama",
        "raw": raw[:500],
    }


_SHELL_META_RE = re.compile(r"[|&;<>`$\n\\]")


def _policy_check_step(step: str) -> tuple:
    """Validate a plan step before execution. Returns (ok, reason, argv)."""
    from bigbang.core.plugin_loader import list_plugin_names

    if _SHELL_META_RE.search(step):
        return False, "shell metacharacters not allowed in plan steps", None
    try:
        parts = shlex.split(step)
    except ValueError as e:
        return False, f"unparseable step: {e}", None
    if len(parts) < 2 or parts[0] not in ("bb", "scout", "bigbang", "dv", "kitty"):
        return False, "step must start with a scout-cli alias (bb/scout) + plugin", None
    plugin = parts[1]
    known = set(list_plugin_names()) | {"doctor"}
    if plugin not in known:
        return False, f"unknown plugin '{plugin}' — not in {sorted(known)}", None
    argv = [sys.executable, "-m", "bigbang.cli", "--json"] + parts[1:]
    return True, "ok", argv


def _execute_plan(plan: list[str]) -> list[dict[str, Any]]:
    """Run each plan step as a subprocess of this CLI, policy-checked first."""
    results: list[dict[str, Any]] = []
    for step in plan:
        ok, reason, argv = _policy_check_step(step)
        if not ok:
            results.append(
                {"step": step, "executed": False, "policy": f"denied: {reason}"}
            )
            continue
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
            out = proc.stdout.strip()
            try:
                parsed = json.loads(out) if out else None
            except json.JSONDecodeError:
                parsed = None
            results.append(
                {
                    "step": step,
                    "executed": True,
                    "policy": "checked",
                    "exit_code": proc.returncode,
                    "output": parsed if parsed is not None else out[:2000],
                    "stderr": proc.stderr.strip()[:500] if proc.returncode != 0 else "",
                }
            )
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "step": step,
                    "executed": False,
                    "policy": "checked",
                    "error": "timed out after 120s",
                }
            )
    return results


@app.command(
    "run",
    epilog=(
        "\nExamples:\n"
        '  scout agent run "list my tools"                 # plan only (safe default)\n'
        '  scout --json agent run "system doctor" --execute\n'
        '  scout agent run "check write slop on README" --execute\n'
    ),
)
def run(
    task: str = typer.Argument(
        ...,
        help="natural language e.g. 'summarize my GitHub PRs and post to family brain'",
    ),
    execute: bool = typer.Option(
        False, "--execute", help="Actually run the plan steps (default: plan only)"
    ),
    profile: str = typer.Option(
        None,
        "--profile",
        help="dynamic runtime profile: hermes | openclaw (or DOTTIE_PROFILE env)",
    ),
    session: str = typer.Option(
        "scout", "--session", help="session id for persistent context / task logs"
    ),
):
    """Plan (default) or execute a natural-language task via Ava routing."""
    from bigbang.core.profiles import after_run, build_system_prompt, get_profile

    try:
        prof = get_profile(profile)
    except KeyError as e:
        emit({"error": str(e)}, command="agent run")
        return
    prof_prompt = build_system_prompt(prof, session_id=session) if prof else None

    def _finish(payload: dict[str, Any], executed: bool) -> None:
        """Attach profile state + post-run persistence to the outgoing payload."""
        if prof is None:
            return
        payload["profile"] = {
            "name": prof.name,
            "persistence": prof_prompt["persistence"],
        }
        if prof_prompt["context"] is not None:
            payload["profile"]["session_context"] = prof_prompt["context"]
        outcome = "ok" if executed else "planned"
        payload["profile"]["post_run"] = after_run(
            prof,
            session_id=session,
            task=task,
            outcome=outcome,
            plan=payload.get("plan"),
        )

    tools = list_tools()
    base = get_ollama_base(timeout=2.0) if _HAS_LLM else None
    try:
        if base:
            try:
                result = _ollama_planner(
                    task, system_prefix=prof_prompt["system"] if prof_prompt else None
                )
                payload = {
                    "task": task,
                    "planner": f"Ava v6.4 local (ollama) — Ollama {result.get('planner_model')} + Frontier rubric + real router",
                    "planner_type": "ollama",
                    "planner_model": result.get("planner_model"),
                    "ollama_base": base,
                    "ollama": {
                        "available": True,
                        "base": base,
                        "model": result.get("planner_model"),
                    },
                    "available_tools": list(tools.keys())[:20],
                    "plan": result.get("plan", []),
                    "reason": result.get("reason"),
                    "security": "Every step checked before execution, secrets vaulted, audit.jsonl appended",
                    "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
                }
                if execute:
                    payload["execution"] = "executed"
                    payload["results"] = _execute_plan(payload["plan"])
                else:
                    payload["execution"] = (
                        "plan only — pass --execute to run the steps (policy-checked, audited)"
                    )
                _finish(payload, executed=execute)
                emit(payload, command="agent run")
                return
            except Exception as e:
                heuristic = _heuristic_plan(task)
                heuristic["ollama_error"] = str(e)[:300]
                heuristic["ollama_base"] = base
        else:
            heuristic = _heuristic_plan(task)
            heuristic["ollama_base"] = None

        payload = {
            "task": task,
            "planner": f"Ava v6.4 local ({heuristic.get('planner_type')}) — "
            + (
                "heuristic keyword matching + builtin hints"
                if heuristic.get("planner_type") == "heuristic"
                else "ollama"
            ),
            "planner_type": heuristic.get("planner_type", "heuristic"),
            "ollama_base": heuristic.get("ollama_base"),
            "ollama": {
                "available": base is not None,
                "base": base,
            },
            "available_tools": heuristic.get(
                "available_tools", list(tools.keys())[:20]
            ),
            "candidate_tools": [
                p.split()[1] if len(p.split()) > 1 else p
                for p in heuristic.get("plan", [])
            ],
            "plan": heuristic.get("plan", []),
            "reason": heuristic.get("reason"),
            "security": "Every step checked before execution, secrets vaulted, audit.jsonl appended",
            "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
        }
        if execute:
            payload["execution"] = "executed"
            payload["results"] = _execute_plan(payload["plan"])
        else:
            payload["execution"] = (
                "plan only — pass --execute to run the steps (policy-checked, audited)"
            )
        _finish(payload, executed=execute)
        emit(payload, command="agent run")

    except Exception as e:
        fallback = _heuristic_plan(task)
        emit(
            {
                "task": task,
                "planner": "Ava v6.4 local (heuristic) — fallback",
                "planner_type": "heuristic",
                "plan": fallback.get("plan", ["bb system doctor", "bb tools list"]),
                "error": str(e)[:300],
                "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
            },
            command="agent run",
        )


@app.command("bus")
def bus(
    threshold: int = typer.Option(
        3, "--threshold", help="suggest commands repeated at least this many times"
    ),
):
    """Scan audit.jsonl for recurring commands and suggest automation candidates."""
    from bigbang.core import audit as _audit

    audit_file = _audit.AUDIT_FILE
    if not audit_file.exists():
        emit(
            {
                "audit_log": str(audit_file),
                "suggestions": [],
                "count": 0,
                "note": "audit log not present yet — run some commands first",
            },
            command="agent bus",
        )
        return
    counts: Counter = Counter()
    for line in audit_file.read_text().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        cmd = entry.get("command")
        if cmd and cmd != "unknown":
            counts[cmd] += 1
    suggestions = [
        {
            "command": cmd,
            "times_run": n,
            "suggest": f"recurring pattern — consider a skill or alias for '{cmd}'",
        }
        for cmd, n in counts.most_common()
        if n >= threshold
    ]
    emit(
        {
            "audit_log": str(audit_file),
            "threshold": threshold,
            "commands_seen": len(counts),
            "suggestions": suggestions,
            "count": len(suggestions),
        },
        command="agent bus",
    )


def _slugify(text: str, max_words: int = 6) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())[:max_words]
    return "-".join(words) or "skill"


SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"


@app.command("teach")
def teach(
    example: str = typer.Argument(
        ..., help="show agent how to do something once, it learns"
    ),
):
    """Store the taught example as a real skill file in bigbang/skills/<slug>.md."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slugify(example)
    path = SKILLS_DIR / f"{slug}.md"
    content = (
        f"# Skill: {slug}\n\n"
        f"Taught: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"## Example\n\n{example}\n"
    )
    path.write_text(content)
    emit(
        {
            "teaching": example,
            "skill_file": str(path),
            "slug": slug,
            "learned": True,
            "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
        },
        command="agent teach",
    )


def register(root):
    root.add_typer(app, name="agent")


# Solo personal project, no connection to employer, built with public/free-tier only
