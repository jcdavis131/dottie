"""Pass-only SWE trajectories → fixed-catalog ReAct (Spec 15).

Maps ``SWE-bench/SWE-smith-trajectories`` (split ``tool``, ``resolved=true``)
onto the small tool catalog already used by ``tool_curriculum``:

  repo_read_file, repo_grep, run_tests, apply_patch

Foreign shell / browser actions are dropped; a traj must yield ≥1 mapped
Action or it is skipped. Observations are taken from tool results when
present, else a deterministic stub.

Collector wiring: ``adapter: swe_react``.
"""

from __future__ import annotations

import json
import re
from typing import Any

USER = "<|user|>"
ASSISTANT = "<|assistant|>"

_CATALOG = """Available tools (fixed catalog — use only these):
- repo_read_file(path) — read a text file's contents
- repo_grep(pattern, path) — count/search matches of a pattern
- run_tests(target) — run the test suite or a target
- apply_patch(path, patch) — apply a unified diff to a file"""

# Map common SWE-agent / tool-call names → catalog tools.
_NAME_MAP = {
    "repo_read_file": "repo_read_file",
    "read_file": "repo_read_file",
    "view": "repo_read_file",
    "open": "repo_read_file",
    "cat": "repo_read_file",
    "str_replace_editor": "repo_read_file",  # view mode; edits → apply_patch below
    "repo_grep": "repo_grep",
    "grep": "repo_grep",
    "find": "repo_grep",
    "search": "repo_grep",
    "search_dir": "repo_grep",
    "search_file": "repo_grep",
    "run_tests": "run_tests",
    "pytest": "run_tests",
    "run": "run_tests",
    "execute": "run_tests",
    "bash": "run_tests",
    "shell": "run_tests",
    "apply_patch": "apply_patch",
    "edit": "apply_patch",
    "str_replace": "apply_patch",
    "create": "apply_patch",
    "insert": "apply_patch",
}


def _loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _dialogue(turns: list[tuple[str, str]]) -> str:
    parts = []
    for role, content in turns:
        marker = USER if role == "user" else ASSISTANT
        parts.append(f"{marker}\n{content}")
    return "\n".join(parts)


def _format_arg_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    if v is None:
        return "null"
    s = str(v)
    if len(s) > 240:
        s = s[:237] + "..."
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{s}"'


def _map_tool(raw_name: str, arguments: dict) -> tuple[str, dict] | None:
    key = re.sub(r"[^a-zA-Z0-9_]", "_", (raw_name or "").strip().lower())
    key = re.sub(r"_+", "_", key).strip("_")
    # str_replace_editor: command=view → read; command=create/str_replace → patch
    if key in {"str_replace_editor", "editor", "edit_file"}:
        cmd = str(arguments.get("command") or arguments.get("cmd") or "").lower()
        if cmd in {"create", "str_replace", "insert", "edit"}:
            mapped = "apply_patch"
        else:
            mapped = "repo_read_file"
    else:
        mapped = _NAME_MAP.get(key)
        if mapped is None:
            for needle, dest in _NAME_MAP.items():
                if needle in key:
                    mapped = dest
                    break
    if mapped is None:
        return None

    if mapped == "repo_read_file":
        path = (
            arguments.get("path")
            or arguments.get("file")
            or arguments.get("filename")
            or arguments.get("target")
            or "unknown.py"
        )
        return mapped, {"path": path}
    if mapped == "repo_grep":
        pat = (
            arguments.get("pattern")
            or arguments.get("query")
            or arguments.get("search")
            or "TODO"
        )
        path = (
            arguments.get("path")
            or arguments.get("dir")
            or arguments.get("file")
            or "."
        )
        return mapped, {"pattern": pat, "path": path}
    if mapped == "run_tests":
        target = (
            arguments.get("target")
            or arguments.get("command")
            or arguments.get("cmd")
            or "pytest"
        )
        return mapped, {"target": target}
    # apply_patch
    path = arguments.get("path") or arguments.get("file") or "unknown.py"
    patch = (
        arguments.get("patch")
        or arguments.get("diff")
        or arguments.get("new_str")
        or ""
    )
    return mapped, {"path": path, "patch": patch}


def _extract_calls(msg: dict) -> list[tuple[str, dict, str | None]]:
    """Yield (raw_name, arguments, observation_hint) from one assistant message."""
    out: list[tuple[str, dict, str | None]] = []
    tool_calls = msg.get("tool_calls") or msg.get("function_call")
    if isinstance(tool_calls, dict):
        tool_calls = [tool_calls]
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or tc.get("function_call") or tc
            if not isinstance(fn, dict):
                continue
            name = fn.get("name") or tc.get("name") or ""
            args = (
                fn.get("arguments") or fn.get("parameters") or tc.get("arguments") or {}
            )
            args = _loads(args)
            if not isinstance(args, dict):
                args = {}
            out.append((str(name), args, None))
    # Inline Action: lines in content (already-ReAct trajs)
    content = msg.get("content")
    if isinstance(content, str):
        for m in re.finditer(
            r"Action:\s*([a-zA-Z_][a-zA-Z0-9_]*)\((.*)\)\s*$", content, re.M
        ):
            # Best-effort: leave args empty; path-like content often in thought.
            out.append((m.group(1), {}, None))
        # SWE-agent XML-ish: <function=name> ... </function>
        for m in re.finditer(
            r"<function=([a-zA-Z_][\w.]*)>(.*?)</function>",
            content,
            re.S,
        ):
            name = m.group(1)
            body = m.group(2)
            args: dict[str, Any] = {}
            for pm in re.finditer(
                r"<parameter=([a-zA-Z_]\w*)>(.*?)</parameter>", body, re.S
            ):
                args[pm.group(1)] = pm.group(2).strip()
            out.append((name, args, None))
    return out


def _iter_messages(raw: Any) -> list[dict]:
    raw = _loads(raw)
    if isinstance(raw, dict) and "messages" in raw:
        raw = raw["messages"]
    if not isinstance(raw, list):
        return []
    return [m for m in raw if isinstance(m, dict)]


def record_to_react(rec: dict) -> dict | None:
    """Convert one pass-only SWE traj into a ReAct doc, or None."""
    if rec.get("resolved") is False:
        return None
    # Prefer explicit True; also accept missing resolved when filtered upstream.
    if "resolved" in rec and rec.get("resolved") is not True:
        return None

    messages = _iter_messages(rec.get("messages"))
    if not messages:
        return None

    # Problem statement: first user message.
    problem = "Fix the failing issue using the catalog tools."
    for m in messages:
        if m.get("role") in {"user", "human"} and isinstance(m.get("content"), str):
            content = m["content"].strip()
            if content:
                problem = content[:1200]
                break

    turns: list[tuple[str, str]] = [
        ("user", f"{_CATALOG}\n\nIssue:\n{problem}"),
    ]
    n_actions = 0
    # Pair tool results when role==tool follows.
    i = 0
    while i < len(messages):
        m = messages[i]
        role = m.get("role")
        if role in {"assistant", "ai"}:
            calls = _extract_calls(m)
            for raw_name, args, _ in calls:
                mapped = _map_tool(raw_name, args)
                if mapped is None:
                    continue
                tool, mapped_args = mapped
                inner = ", ".join(
                    f"{k}={_format_arg_value(v)}" for k, v in mapped_args.items()
                )
                turns.append(
                    (
                        "assistant",
                        f"Thought: use {tool} from the fixed catalog.\n"
                        f"Action: {tool}({inner})",
                    )
                )
                obs = None
                # Look ahead for tool / function response.
                if i + 1 < len(messages):
                    nxt = messages[i + 1]
                    if nxt.get("role") in {"tool", "function", "user"}:
                        c = nxt.get("content")
                        if isinstance(c, str) and c.strip():
                            obs = c.strip()[:800]
                if obs is None:
                    obs = f"ok: {tool}"
                turns.append(("user", f"Observation: {obs}"))
                n_actions += 1
        i += 1

    if n_actions < 1:
        return None

    patch = rec.get("patch")
    if isinstance(patch, str) and patch.strip():
        final = "Resolved. Patch applied; tests reported pass."
    else:
        final = "Resolved. Catalog tools were sufficient; tests reported pass."
    turns.append(("assistant", final))
    return {
        "text": _dialogue(turns),
        "_task_type": "tool_selection",
        "_concept": "swe_pass_traj",
    }


def adapt_record(rec: dict) -> dict | None:
    """Collector adapter entrypoint (``adapter: swe_react``)."""
    return record_to_react(rec)
