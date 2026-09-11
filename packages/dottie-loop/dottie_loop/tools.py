"""Scout CLI tool plane (spec §12): one governed tool surface, ``scout --json …``.

Registry, policy, execution and audit stay OUTSIDE the model. Tool resolution:

1. parse the command and resolve a registered plugin/version
2. load manifest metadata and declared capabilities
3. validate arguments against the command schema
4. ask policy to authorize filesystem, network, secrets and side effects
5. execute with a normalized environment and resource limits
6. emit a versioned JSON envelope and append a REDACTED audit line

Policy invariants pinned here: unknown plugin or command is denied; capabilities
are enforced, not merely declared; paths are canonicalized before comparison;
secrets travel by brokered reference and never appear in argv, logs or the
envelope; JSON mode never mixes prose into stdout; dry-run performs no effect;
a plugin cannot broaden its own manifest at call time; a rate-limit block ends
the provider scope.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dottie_loop.errors import (
    InvalidInputError,
    PolicyDeniedError,
    RateLimitedError,
)
from dottie_loop.execution import canonical_in_root, check_url_allowed, run_argv
from dottie_loop.hashing import new_id, now_iso
from dottie_loop.schema import active, check_compatible

SIDE_EFFECTS = frozenset({"none", "read", "write_local", "external_send", "production_mutate"})
FS_MODES = frozenset({"read", "read_write"})
_SECRET_REF_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")


# --- manifest minimum (§12) ------------------------------------------------------------


def validate_manifest(m: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized manifest or raise InvalidInputError naming the field."""
    for k in ("name", "version", "commands", "capabilities", "side_effects", "timeouts", "output_schema"):
        if k not in m:
            raise InvalidInputError(f"manifest missing {k}", field=k)
    if not isinstance(m["commands"], list) or not m["commands"]:
        raise InvalidInputError("manifest.commands must be a non-empty list", "commands")
    caps = m["capabilities"] or {}
    net = caps.get("network") or {"domains": [], "methods": []}
    fs = caps.get("filesystem") or {"paths": [], "mode": "read"}
    if fs.get("mode", "read") not in FS_MODES:
        raise InvalidInputError("filesystem.mode must be read|read_write", "capabilities.filesystem.mode")
    secrets = list(caps.get("secrets") or [])
    for s in secrets:
        if not _SECRET_REF_RE.match(str(s)):
            raise InvalidInputError(f"secret reference {s!r} is not a reference name", "capabilities.secrets")
    for cmd in m["commands"]:
        se = (m["side_effects"] or {}).get(cmd)
        if se not in SIDE_EFFECTS:
            raise InvalidInputError(f"side_effects.{cmd} must be one of {sorted(SIDE_EFFECTS)}", "side_effects")
    check_compatible(m["output_schema"], "scout-result")
    timeout = float((m["timeouts"] or {}).get("default_seconds", 0) or 0)
    if timeout <= 0:
        raise InvalidInputError("timeouts.default_seconds must be positive", "timeouts")
    return {
        "name": m["name"],
        "version": str(m["version"]),
        "commands": list(m["commands"]),
        "network": {"domains": list(net.get("domains") or []), "methods": [x.upper() for x in (net.get("methods") or [])]},
        "filesystem": {"paths": list(fs.get("paths") or []), "mode": fs.get("mode", "read")},
        "secrets": secrets,
        "side_effects": dict(m["side_effects"]),
        "timeout_s": timeout,
        "output_schema": m["output_schema"],
        "arg_schema": dict(m.get("arg_schema") or {}),
    }


# --- result envelope (§12) ----------------------------------------------------------------


def validate_result_envelope(env: dict[str, Any]) -> dict[str, Any]:
    for k in ("ok", "plugin", "version", "command", "request_id", "data", "warnings", "metrics", "provenance"):
        if k not in env:
            raise InvalidInputError(f"result envelope missing {k}", field=k)
    check_compatible(env.get("schema", active("scout-result")), "scout-result")
    if not isinstance(env["warnings"], list) or not isinstance(env["metrics"], dict):
        raise InvalidInputError("warnings must be a list and metrics an object", "envelope")
    if "latency_ms" not in env["metrics"]:
        raise InvalidInputError("metrics.latency_ms is required", "metrics.latency_ms")
    prov = env["provenance"]
    if not isinstance(prov, dict) or "source" not in prov:
        raise InvalidInputError("provenance.source is required", "provenance")
    return env


def parse_json_stdout(stdout: str) -> dict[str, Any]:
    """JSON mode never mixes human prose into stdout: exactly one JSON document."""
    stripped = stdout.strip()
    if not stripped:
        raise InvalidInputError("empty stdout in JSON mode", field="stdout")
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise InvalidInputError("stdout is not exactly one JSON document (prose mixed in?)", "stdout") from e
    if not isinstance(obj, dict):
        raise InvalidInputError("stdout JSON must be an object envelope", field="stdout")
    return obj


# --- secrets by reference -------------------------------------------------------------------


class SecretBroker:
    """Holds reference -> value. Values reach a tool only as env vars at exec time."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = dict(values or {})

    def refs(self) -> list[str]:
        return sorted(self._values)

    def env_for(self, refs: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for r in refs:
            if r not in self._values:
                raise PolicyDeniedError(f"secret reference {r!r} is not connected", field="secrets")
            out["DOTTIE_SECRET_" + r.upper().replace(".", "_").replace("-", "_")] = self._values[r]
        return out

    def redact(self, text: str) -> str:
        for v in self._values.values():
            if v and v in text:
                text = text.replace(v, "[SECRET]")
        return text

    def leaks_into(self, argv: list[str]) -> bool:
        return any(v and v in a for a in argv for v in self._values.values())


# --- the tool plane ------------------------------------------------------------------------


@dataclass
class ToolCall:
    plugin: str
    command: str
    args: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)  # filesystem resources touched
    urls: list[str] = field(default_factory=list)  # network resources touched
    method: str = "GET"
    secrets: list[str] = field(default_factory=list)  # references, never values
    dry_run: bool = False


@dataclass
class AuditLine:
    at: str
    request_id: str
    plugin: str
    version: str
    command: str
    args_digest: str
    ok: bool
    latency_ms: int
    denied_reason: str | None = None


class ScoutToolPlane:
    def __init__(self, manifests: list[dict[str, Any]], *, root: Path, broker: SecretBroker | None = None, scout_argv: list[str] | None = None) -> None:
        self.registry = {m["name"]: validate_manifest(m) for m in manifests}
        self.root = Path(root)
        self.broker = broker or SecretBroker()
        self.scout_argv = scout_argv or ["scout", "--json"]
        self.audit: list[AuditLine] = []
        self.blocked_providers: set[str] = set()

    # 1-2. resolve
    def resolve(self, plugin: str, command: str) -> dict[str, Any]:
        m = self.registry.get(plugin)
        if m is None:
            raise PolicyDeniedError(f"unknown plugin {plugin!r}", field="plugin")
        if command not in m["commands"]:
            raise PolicyDeniedError(f"unknown command {command!r} for {plugin}", field="command")
        return m

    # 3. validate args
    @staticmethod
    def validate_args(m: dict[str, Any], command: str, args: list[str]) -> None:
        schema = m["arg_schema"].get(command)
        if schema is None:
            return
        max_args = int(schema.get("max_args", len(args)))
        if len(args) > max_args:
            raise InvalidInputError(f"{command} accepts at most {max_args} args", field="args")
        pattern = schema.get("pattern")
        if pattern and not all(re.fullmatch(pattern, a) for a in args):
            raise InvalidInputError(f"{command} args must match {pattern}", field="args")

    # 4. authorize
    def authorize(self, m: dict[str, Any], call: ToolCall) -> dict[str, Any]:
        if m["name"] in self.blocked_providers:
            raise RateLimitedError(f"provider scope {m['name']} is blocked for this task")
        if self.broker.leaks_into(call.args):
            raise PolicyDeniedError("a secret VALUE appears in argv; pass a reference", field="args")
        for ref in call.secrets:
            if ref not in m["secrets"]:
                raise PolicyDeniedError(f"secret {ref!r} not declared by {m['name']}", field="secrets")
        for p in call.paths:
            cand = canonical_in_root(p, self.root)
            allowed_roots = [canonical_in_root(a, self.root) for a in m["filesystem"]["paths"]]
            if not any(cand == r or r in cand.parents for r in allowed_roots):
                raise PolicyDeniedError(f"path {p} outside declared filesystem paths", field="paths")
        for u in call.urls:
            if not m["network"]["domains"]:
                raise PolicyDeniedError(f"{m['name']} declares no network capability", field="urls")
            check_url_allowed(u, m["network"]["domains"], m["network"]["methods"], call.method)
        effect = m["side_effects"][call.command]
        if effect in ("external_send", "production_mutate") and not call.dry_run:
            # the plane does not hold approvals; the kernel must have consumed one
            return {"effect": effect, "requires_approval": True}
        return {"effect": effect, "requires_approval": False}

    # 5-6. execute + audit
    def call(self, call: ToolCall, *, approval_consumed: bool = False, runner=None) -> dict[str, Any]:
        m = self.resolve(call.plugin, call.command)
        self.validate_args(m, call.command, call.args)
        auth = self.authorize(m, call)
        if auth["requires_approval"] and not approval_consumed:
            raise PolicyDeniedError("side effect requires a consumed approval", field="approval")
        request_id = new_id("req_")
        argv = [*self.scout_argv, call.plugin, call.command, *call.args]
        if call.dry_run:
            env = {"ok": True, "schema": active("scout-result"), "plugin": m["name"], "version": m["version"], "command": call.command, "request_id": request_id, "data": {"dry_run": True, "argv": argv}, "warnings": [], "metrics": {"latency_ms": 0}, "provenance": {"source": "dry_run", "retrieved_at": now_iso()}}
            self._audit(request_id, m, call, ok=True, latency_ms=0)
            return env
        exec_fn = runner or self._run
        try:
            proc = exec_fn(argv, m, call)
        except RateLimitedError:
            self.blocked_providers.add(m["name"])
            self._audit(request_id, m, call, ok=False, latency_ms=0, denied="rate_limited")
            raise
        stdout = self.broker.redact(proc["stdout"])
        try:
            env = validate_result_envelope(parse_json_stdout(stdout))
        except InvalidInputError:
            self._audit(request_id, m, call, ok=False, latency_ms=proc["latency_ms"], denied="malformed_envelope")
            raise
        if env["plugin"] != m["name"]:
            raise PolicyDeniedError("envelope names a different plugin than resolved", field="plugin")
        env["request_id"] = request_id
        self._audit(request_id, m, call, ok=bool(env["ok"]), latency_ms=int(env["metrics"]["latency_ms"]))
        return env

    def _run(self, argv: list[str], m: dict[str, Any], call: ToolCall) -> dict[str, Any]:
        env = self.broker.env_for(call.secrets)
        allow = ["PATH", "HOME", "LANG", *env]
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            return run_argv(argv, cwd=self.root, timeout_s=m["timeout_s"], env_allow=allow)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def _audit(self, request_id: str, m: dict[str, Any], call: ToolCall, *, ok: bool, latency_ms: int, denied: str | None = None) -> None:
        from dottie_loop.hashing import digest

        self.audit.append(AuditLine(at=now_iso(), request_id=request_id, plugin=m["name"], version=m["version"], command=call.command, args_digest=digest([self.broker.redact(a) for a in call.args]), ok=ok, latency_ms=latency_ms, denied_reason=denied))
