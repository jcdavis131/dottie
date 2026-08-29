# Solo personal project, no connection to employer, built with public/free-tier only
"""glimmer — local Glimmer 30B agent for scout-cli, replaces cloud calls."""

import os
import json
from pathlib import Path
from typing import Optional, List

import typer

from bigbang.core.output import emit

try:
    from bigbang.core.glimmer import (
        GLIMMER_MODELS,
        REASONING_LEVELS,
        get_glimmer_endpoint,
        get_best_glimmer_model,
        is_glimmer_available,
        glimmer_chat,
        glimmer_chat_with_tools,
        test_glimmer_coding_task,
        test_glimmer_tool_calling,
        build_system_prompt,
    )
    _HAS_G = True
except ImportError as e:
    _HAS_G = False
    _IMPORT_ERR = str(e)

app = typer.Typer(name="glimmer", help="✨ Muse Glimmer 30B local agent — offline, text+image, reasoning effort", no_args_is_help=True)

@app.command("status")
def status_cmd(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose"),
):
    if not _HAS_G:
        emit({"ok": False, "error": f"glimmer module missing: {_IMPORT_ERR}", "available": False}, command="glimmer status")
        return
    base = get_glimmer_endpoint(timeout=2.0)
    avail = is_glimmer_available(timeout=2.0) if base else False
    best = get_best_glimmer_model(base=base) if base else "muse-glimmer:30b"
    from bigbang.core.llm import list_ollama_models
    models = list_ollama_models(base=base) if base else []
    glimmer_models = [m for m in models if "glimmer" in m.lower()]
    emit({
        "ok": True,
        "available": avail,
        "endpoint": base,
        "best_model": best,
        "ollama_models": models[:20],
        "glimmer_models": glimmer_models,
        "reasoning_levels": list(REASONING_LEVELS.keys()),
        "env": {
            "GLIMMER_BASE": os.environ.get("GLIMMER_BASE"),
            "OLLAMA_BASE": os.environ.get("OLLAMA_BASE"),
        },
        "hint": "ollama pull muse-glimmer:30b  # if missing, then scout glimmer chat 'hello'",
    }, command="glimmer status")

@app.command("chat")
def chat_cmd(
    prompt: str = typer.Argument(..., help="Prompt for Glimmer"),
    reasoning: str = typer.Option("medium", "--reasoning", "-r", help="low|medium|high|xhigh"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model name override"),
    image: Optional[List[Path]] = typer.Option(None, "--image", "-i", help="Image file(s) for multimodal"),
    json_mode: bool = typer.Option(False, "--json-mode", help="JSON mode"),
    system: Optional[str] = typer.Option(None, "--system", help="Extra system prompt"),
):
    if not _HAS_G:
        emit({"ok": False, "error": "glimmer core not loaded"}, command="glimmer chat")
        raise typer.Exit(1)
    images = [str(p) for p in image] if image else None
    res = glimmer_chat(prompt, images=images, reasoning=reasoning, model=model, system_extra=system, json_mode=json_mode, timeout=120)
    emit(res, command="glimmer chat")
    if not res.get("ok"):
        raise typer.Exit(1)

@app.command("code")
def code_cmd(
    task: str = typer.Argument(..., help="Coding task"),
    reasoning: str = typer.Option("high", "--reasoning", help="low|medium|high|xhigh"),
    model: Optional[str] = typer.Option(None, "--model"),
):
    if not _HAS_G:
        emit({"ok": False, "error": "no glimmer"}, command="glimmer code")
        raise typer.Exit(1)
    if task.lower() in ("test", "fib", "demo"):
        res = test_glimmer_coding_task(model=model)
    else:
        res = glimmer_chat(task, reasoning=reasoning, model=model, timeout=120)
    emit(res, command="glimmer code")
    if not res.get("ok"):
        raise typer.Exit(1)

@app.command("tools")
def tools_cmd(
    prompt: str = typer.Option("You need to read workspace file README.md then summarize it. Use read_file tool.", "--prompt", help="Tool-use prompt"),
    reasoning: str = typer.Option("medium", "--reasoning"),
):
    if not _HAS_G:
        emit({"ok": False, "error": "no glimmer"}, command="glimmer tools")
        raise typer.Exit(1)
    res = glimmer_chat_with_tools(prompt, reasoning=reasoning)
    tool_test = test_glimmer_tool_calling()
    emit({"function_calling": res, "tool_test": tool_test}, command="glimmer tools")
    if not res.get("ok"):
        raise typer.Exit(1)

@app.command("reason")
def reason_cmd(
    level: str = typer.Argument(..., help="low|medium|high|xhigh"),
):
    if not _HAS_G:
        emit({"ok": False}, command="glimmer reason")
        return
    sp = build_system_prompt(level)
    emit({"level": level, "system_prompt": sp, "length": len(sp), "all_levels": REASONING_LEVELS}, command="glimmer reason")

@app.command("pull")
def pull_cmd(
    model: str = typer.Option("muse-glimmer:30b", "--model", help="Model to pull"),
):
    import subprocess
    base = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
    try:
        proc = subprocess.run(["ollama", "pull", model], capture_output=True, text=True, timeout=600)
        emit({"ok": proc.returncode==0, "model": model, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:], "returncode": proc.returncode}, command="glimmer pull")
        if proc.returncode!=0:
            raise typer.Exit(1)
    except FileNotFoundError:
        emit({"ok": False, "error": "ollama CLI not found — use curl or set OLLAMA_BASE", "model": model, "endpoint": base, "manual": f"curl {base}/api/pull -d '{{\"name\":\"{model}\"}}'"}, command="glimmer pull")
        raise typer.Exit(1)

def register(root):
    root.add_typer(app, name="glimmer")
