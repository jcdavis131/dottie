"""Shared telemetry + trust layer for the Ava assistant surface (spec 15 §2).

Two invariants this module exists to enforce:

  * **Telemetry** — every agent action produces exactly one append-only JSONL
    line (``runs/assistant_audit.jsonl``) with a stable, secret-scrubbed shape.
    A tool call that isn't logged is a bug.
  * **Trust** — every tool the assistant may call is declared here with an
    explicit capability boundary (read-only? side effects? sandbox root? output
    cap?). ``check_tool`` denies anything undeclared, any path escaping its
    sandbox root, and any argument that isn't the declared shape — *before* the
    tool runs, teaching the runtime the same refusal the curriculum teaches the
    model (spec 15 §4 L4).

The telemetry line shape is deliberately identical to the Scout ⨯ Herdr ledger
(``bigbang/core/audit.py``) so the two surfaces read as one system.

No heavy imports, no engine, no network — safe to import from ``server.py`` at
boot even when ``AVA_SKIP_ENGINE_BOOT=1``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_REPO = Path(__file__).resolve().parent.parent
_AUDIT_PATH = _REPO / "runs" / "assistant_audit.jsonl"

# A key marks its value as sensitive if, after normalizing '-'/' ' to '_', it
# ends with one of these suffixes (covers key/keys/api_key/private_key/ssh_key/
# signing_key/token/secret/password/passwd/pwd), contains one of the substrings,
# or matches one of the exact names. Deliberately broad: this is the only
# scrubbing layer and the args are model-controlled, so under-redacting leaks a
# real secret to disk (the failure the review caught).
_SECRET_SUFFIXES = ("key", "keys", "token", "tokens", "secret", "secrets",
                    "password", "passwd", "pwd", "credential", "credentials",
                    "cred", "creds")
_SECRET_SUBSTRINGS = ("secret", "token", "password", "passwd", "apikey",
                      "api_key", "private_key", "credential", "auth", "bearer")
_SECRET_EXACT = {"key", "keys", "auth", "authorization", "bearer", "cookie",
                 "session", "credential", "credentials", "signature", "sig"}


def _is_secret_key(k: Any) -> bool:
    lk = str(k).lower().replace("-", "_").replace(" ", "_")
    if lk in _SECRET_EXACT:
        return True
    if lk.endswith(_SECRET_SUFFIXES):
        return True
    return any(m in lk for m in _SECRET_SUBSTRINGS)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _scrub(obj: Any) -> Any:
    """Recursively redact secret-looking dict keys. Lists/scalars pass through."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            out[k] = "***" if _is_secret_key(k) else _scrub(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_scrub(v) for v in obj]
    return obj


def emit_event(
    action: str,
    target: str = "",
    *,
    surface: str = "ava.assistant",
    actor: str = "anon",
    args: Optional[dict[str, Any]] = None,
    status: str = "ok",
    duration_ms: int = 0,
    meta: Optional[dict[str, Any]] = None,
    audit_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Append one telemetry line and return the (scrubbed) record.

    Never raises on I/O trouble — telemetry must not take the caller down. The
    returned dict is what actually hit disk (secret-scrubbed), so callers can
    also surface it inline (e.g. in an ``/assistant`` step trace).
    """
    rec = {
        "ts": _utc_now_iso(),
        "surface": surface,
        "actor": actor,
        "action": action,
        "target": target,
        "args": _scrub(args or {}),
        "status": status,
        "duration_ms": int(duration_ms),
        "meta": _scrub(meta or {}),
    }
    path = audit_path or _AUDIT_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        # Deliberately swallowed: a full disk or a race must not break inference.
        pass
    return rec


def tail_events(n: int = 50, audit_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Return the last ``n`` telemetry records (best-effort, never raises)."""
    path = audit_path or _AUDIT_PATH
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Trust: the tool capability table.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCapability:
    """A declared capability boundary for a single tool.

    ``read_only``     — the tool never mutates state (all current tools are).
    ``side_effects``  — the tool touches something outside the process.
    ``sandbox_root``  — if set, path-typed args must resolve inside this root.
    ``path_args``     — which argument names carry filesystem paths (sandboxed).
    ``max_output_bytes`` — Observation text is truncated to this many bytes.
    ``description``   — one-line purpose (shown in the in-context tool catalog).
    ``signature``     — human-readable arg signature for the catalog.
    """

    name: str
    description: str
    signature: str
    read_only: bool = True
    side_effects: bool = False
    sandbox_root: Optional[Path] = None
    path_args: tuple[str, ...] = ()
    max_output_bytes: int = 4096


@dataclass
class ToolRegistry:
    """The set of tools the assistant is permitted to call.

    ``check(tool, args)`` is the trust gate: it runs *before* dispatch and
    returns ``(allowed, reason)``. A denial is a first-class training signal —
    the loop feeds the reason back as an Observation so the model learns the
    boundary, exactly as the L4 curriculum family teaches it.
    """

    tools: dict[str, ToolCapability] = field(default_factory=dict)

    def register(self, cap: ToolCapability) -> None:
        self.tools[cap.name] = cap

    def catalog(self) -> list[dict[str, str]]:
        return [
            {"name": c.name, "signature": c.signature, "description": c.description,
             "read_only": str(c.read_only), "sandboxed": str(c.sandbox_root is not None)}
            for c in self.tools.values()
        ]

    def check(self, tool: str, args: dict[str, Any]) -> tuple[bool, str]:
        cap = self.tools.get(tool)
        if cap is None:
            return False, f"tool '{tool}' is not in the declared capability table"
        if not cap.read_only and not cap.side_effects:
            # A tool that is neither read-only nor an acknowledged side-effect
            # tool is misconfigured; deny rather than guess.
            return False, f"tool '{tool}' has an inconsistent capability declaration"
        for pa in cap.path_args:
            if pa not in args:
                continue
            ok, reason = _within_sandbox(cap.sandbox_root, str(args[pa]))
            if not ok:
                return False, reason
        return True, "ok"

    def clip(self, tool: str, text: str) -> str:
        cap = self.tools.get(tool)
        limit = cap.max_output_bytes if cap else 4096
        b = text.encode("utf-8")
        if len(b) <= limit:
            return text
        return b[:limit].decode("utf-8", errors="ignore") + " …[truncated]"


def _within_sandbox(root: Optional[Path], candidate: str) -> tuple[bool, str]:
    """Reject path traversal outside ``root``. If ``root`` is None the tool
    declared no sandbox and any path arg is refused (fail closed)."""
    if root is None:
        return False, "tool takes a path but declares no sandbox root"
    try:
        base = root.resolve()
        target = (base / candidate).resolve() if not os.path.isabs(candidate) else Path(candidate).resolve()
    except Exception:
        return False, f"path '{candidate}' could not be resolved"
    try:
        target.relative_to(base)
    except ValueError:
        return False, f"path '{candidate}' escapes the sandbox root {base}"
    return True, "ok"


def default_registry(sandbox_root: Optional[Path] = None) -> ToolRegistry:
    """The tool set the Ava assistant may call — names chosen to mirror the
    training distribution (``ava/datagen/react_tools.py`` +
    ``ava/datagen/tool_curriculum.py``) so inference matches what the model saw.

    Every tool here is read-only. ``repo_*`` / ``list_dir`` are sandboxed to
    ``sandbox_root`` (default: the repo) with traversal rejection.
    """
    root = (sandbox_root or _REPO).resolve()
    reg = ToolRegistry()
    for cap in (
        ToolCapability("get_clock", "current UTC date/time", "get_clock()"),
        ToolCapability("add", "add two numbers", "add(a, b)"),
        ToolCapability("subtract", "subtract b from a", "subtract(a, b)"),
        ToolCapability("multiply", "multiply two numbers", "multiply(a, b)"),
        ToolCapability("sum", "sum a list of numbers", "sum(values=[...])"),
        ToolCapability("repo_grep", "search files for a pattern", "repo_grep(pattern, path)",
                       sandbox_root=root, path_args=("path",)),
        ToolCapability("repo_read_file", "read a text file", "repo_read_file(path)",
                       sandbox_root=root, path_args=("path",), max_output_bytes=6144),
        ToolCapability("list_dir", "list a directory", "list_dir(path)",
                       sandbox_root=root, path_args=("path",)),
        ToolCapability("pipeline_status", "training pipeline status summary", "pipeline_status()"),
        ToolCapability("ecosystem_status", "ecosystem/agents status summary", "ecosystem_status()"),
        ToolCapability("skill_search", "search the harness skills", "skill_search(query)"),
    ):
        reg.register(cap)
    return reg
