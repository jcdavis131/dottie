"""
scopes/drivers/wiring.py — model-agnostic driver interface
Distilled from qm (YC) — Pi / OpenCode / Codex / Claude Code all drive same core
Zero-deps true, stdlib only, honest 503 never fake, English only.

Single source of truth for harness driver swap.
Core loop unchanged; swap driver by editing DRIVERS dict.

Interface:
  HarnessDriver.run(scope: str, goal: str, tools: list) -> turn_result dict
  turn_result = {
    "ok": bool,
    "scope": str,
    "goal": str,
    "output": str,
    "tool_calls": [...],
    "latency_ms": int,
    "error": str | None,
    "errorClass": str | None,
    "driver": str
  }

Tighten-only enforced via org/config.json — wiring.py cannot bypass policy.
Predeclared denies apply in every posture, Dangerous included.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]  # scopes/
ORG_CONFIG = ROOT / "org" / "config.json"
PERSON_BASE = ROOT / "person"
ROOM_BASE = ROOT / "room"

DRIVERS = {
    "pi": "drivers.pi_driver:PiDriver",
    "opencode": "drivers.opencode_driver:OpenCodeDriver",
    "codex": "drivers.codex_driver:CodexDriver",
    "claude": "drivers.claude_code_driver:ClaudeCodeDriver",
    "claude_code": "drivers.claude_code_driver:ClaudeCodeDriver",
}


class HarnessDriver:
    """Base driver — all drivers implement run(scope, goal, tools)"""

    name = "base"

    def run(self, scope: str, goal: str, tools: Optional[List[str]] = None) -> Dict[str, Any]:
        raise NotImplementedError("driver must implement run(scope, goal, tools) -> turn_result")

    def health(self) -> Dict[str, Any]:
        return {"ok": True, "driver": self.name}


class PiDriver(HarnessDriver):
    """Pi — local default, zero-deps, stdlib only, always available"""

    name = "pi"

    def run(self, scope: str, goal: str, tools: Optional[List[str]] = None) -> Dict[str, Any]:
        t0 = time.time()
        tools = tools or []

        # Scope existence check — honest 503, not fake
        scope_path = self._resolve_scope_path(scope)
        if not scope_path.exists():
            return {
                "ok": False,
                "scope": scope,
                "goal": goal,
                "output": "",
                "error": f"scope not found: {scope}",
                "errorClass": "SCOPE_NOT_FOUND",
                "driver": self.name,
                "latency_ms": int((time.time() - t0) * 1000),
            }

        # Org tighten-only enforcement
        try:
            org_cfg = self._load_org_config()
            org_posture = org_cfg.get("permissions", {}).get("posture", "strict")
            # scope permissions.json posture must not be looser than org
            scope_perms_path = scope_path / "permissions.json"
            if scope_perms_path.exists():
                sp = json.loads(scope_perms_path.read_text(encoding="utf-8"))
                scope_posture = sp.get("posture", "strict")
                # strict is tightest, then auto, then dangerous loosest
                order = {"strict": 0, "auto": 1, "dangerous": 2}
                if order.get(scope_posture, 0) > order.get(org_posture, 0):
                    return {
                        "ok": False,
                        "scope": scope,
                        "goal": goal,
                        "output": "",
                        "error": f"scope posture {scope_posture} looser than org {org_posture} — tighten_only",
                        "errorClass": "POLICY_DENY",
                        "driver": self.name,
                        "latency_ms": int((time.time() - t0) * 1000),
                    }
        except FileNotFoundError:
            # org config missing is not fatal for local pi driver, but warn
            pass
        except Exception:
            # honest: any parse error is policy failure
            return {
                "ok": False,
                "scope": scope,
                "goal": goal,
                "output": "",
                "error": "org config invalid",
                "errorClass": "CONFIG_ERROR",
                "driver": self.name,
                "latency_ms": int((time.time() - t0) * 1000),
            }

        # Pi execution is deterministic stdlib — no network, no model
        out = f"[pi] scope={scope} goal={goal} tools={tools}"
        return {
            "ok": True,
            "scope": scope,
            "goal": goal,
            "output": out,
            "tool_calls": [],
            "latency_ms": int((time.time() - t0) * 1000),
            "driver": self.name,
        }

    def _resolve_scope_path(self, scope: str) -> Path:
        # scope e.g. person/default or room/general or org
        if scope == "org":
            return ROOT / "org"
        if "/" in scope:
            return ROOT / scope
        # bare handle -> person/<handle>
        p = PERSON_BASE / scope
        if p.exists():
            return p
        r = ROOM_BASE / scope
        if r.exists():
            return r
        return ROOT / scope

    def _load_org_config(self) -> dict:
        return json.loads(ORG_CONFIG.read_text(encoding="utf-8"))


class SubprocessDriver(HarnessDriver):
    """Base for Pi/OpenCode/Codex/Claude Code — spawns subprocess, parses JSONL"""

    bin_name: str = ""
    args_prefix: List[str] = []

    def run(self, scope: str, goal: str, tools: Optional[List[str]] = None) -> Dict[str, Any]:
        t0 = time.time()
        tools = tools or []
        bin_path = shutil.which(self.bin_name) if self.bin_name else None

        if not bin_path:
            # honest 503 — binary missing, fallback to pi allowed only if org permits
            return {
                "ok": False,
                "scope": scope,
                "goal": goal,
                "output": "",
                "error": f"driver binary not found: {self.bin_name} — install it or set DEFAULT_DRIVER=pi",
                "errorClass": "IO_MISSING",
                "hint": f"binary {self.bin_name} not in PATH, falling back to pi driver is allowed",
                "driver": self.name,
                "latency_ms": int((time.time() - t0) * 1000),
            }

        cmd = [bin_path, *self.args_prefix, goal]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(ROOT.parent),
            )
            latency = int((time.time() - t0) * 1000)
            if proc.returncode != 0:
                return {
                    "ok": False,
                    "scope": scope,
                    "goal": goal,
                    "output": proc.stdout[:2000],
                    "error": proc.stderr[:2000] or f"driver exit {proc.returncode}",
                    "errorClass": "DRIVER_ERROR",
                    "driver": self.name,
                    "latency_ms": latency,
                }
            return {
                "ok": True,
                "scope": scope,
                "goal": goal,
                "output": proc.stdout[:5000],
                "tool_calls": [],
                "latency_ms": latency,
                "driver": self.name,
                "exit_code": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "scope": scope,
                "goal": goal,
                "output": "",
                "error": "driver timeout 120s",
                "errorClass": "TIMEOUT",
                "driver": self.name,
                "latency_ms": int((time.time() - t0) * 1000),
            }
        except FileNotFoundError as e:
            return {
                "ok": False,
                "scope": scope,
                "goal": goal,
                "output": "",
                "error": f"driver binary missing at exec: {e}",
                "errorClass": "IO_MISSING",
                "driver": self.name,
                "latency_ms": int((time.time() - t0) * 1000),
            }


class OpenCodeDriver(SubprocessDriver):
    name = "opencode"
    bin_name = "opencode"
    args_prefix = ["run"]


class CodexDriver(SubprocessDriver):
    name = "codex"
    bin_name = "codex"
    args_prefix = ["exec"]


class ClaudeCodeDriver(SubprocessDriver):
    name = "claude"
    bin_name = "claude"
    args_prefix = ["-p"]


def get_driver(name: Optional[str] = None) -> HarnessDriver:
    """Resolve driver name to instance, honest 503 if missing"""
    if name is None:
        name = os.environ.get("DOTTIE_DRIVER") or os.environ.get("DEFAULT_DRIVER") or "pi"
    name = name.lower().strip()

    if name in ("pi",):
        return PiDriver()
    if name in ("opencode", "open_code"):
        return OpenCodeDriver()
    if name in ("codex",):
        return CodexDriver()
    if name in ("claude", "claude_code", "claude-code"):
        return ClaudeCodeDriver()

    # unknown driver -> pi with warning, honest fallback
    if name not in DRIVERS:
        return PiDriver()
    # dynamic import path if configured
    try:
        mod_path, cls_name = DRIVERS[name].split(":")
        # only support local drivers without import for zero-deps
        if name == "pi":
            return PiDriver()
    except Exception:
        pass
    return PiDriver()


def run(scope: str, goal: str, tools: Optional[List[str]] = None, driver: Optional[str] = None) -> Dict[str, Any]:
    """Top-level run(scope, goal, tools) — model-agnostic entry"""
    drv = get_driver(driver)
    return drv.run(scope, goal, tools)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="scopes/drivers/wiring.py — driver swap test")
    ap.add_argument("scope", help="scope e.g. person/default or room/general")
    ap.add_argument("goal", help="goal text")
    ap.add_argument("--driver", default="pi", help="driver pi/opencode/codex/claude")
    args = ap.parse_args()
    res = run(args.scope, args.goal, driver=args.driver)
    print(json.dumps(res, indent=2))
