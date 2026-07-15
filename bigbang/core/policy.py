"""Capability-based policy engine — security first"""
from pathlib import Path
import yaml
from typing import List, Dict, Tuple
import os

DEFAULT_POLICY = {
    "allow_network": False,
    "allowed_domains": [],
    "allow_fs_write": False,
    "allowed_paths": [],
    "allow_secrets": [],
}

def load_manifest(plugin_path: Path) -> Dict:
    manifest = plugin_path / "manifest.yaml"
    if not manifest.exists():
        return {}
    try:
        return yaml.safe_load(manifest.read_text()) or {}
    except Exception:
        return {}

def check_permission(manifest: Dict, action: str, resource: str) -> Tuple[bool, str]:
    """Returns (allowed, reason)"""
    caps = manifest.get("capabilities", {})
    if action == "network":
        if not caps.get("network", {}).get("enabled", False):
            return False, f"network disabled for {manifest.get('name','tool')} — add manifest capabilities.network.enabled"
        domains = caps.get("network", {}).get("domains", [])
        if domains:
            # allow if any domain substring matches resource
            if not any(d in resource or resource in d or resource.endswith(d) for d in domains):
                # also allow localhost variations
                if resource.startswith("http"):
                    return False, f"domain {resource} not in allowlist {domains}"
                # for non-url, check if any allowed domain appears
        # if no domains specified but network enabled, allow any
    if action == "fs_write":
        if not caps.get("filesystem", {}).get("write", False):
            return False, "filesystem write disabled — add manifest capabilities.filesystem.write=true"
    if action == "secret":
        allowed = caps.get("secrets", {}).get("allow", [])
        if allowed and resource not in allowed:
            return False, f"secret {resource} not in allowlist {allowed}"
    return True, "ok"

def enforce_or_raise(manifest: Dict, action: str, resource: str):
    ok, reason = check_permission(manifest, action, resource)
    if not ok:
        from typer import Exit
        import typer
        typer.secho(f"⛔ Policy denied [{action} {resource}]: {reason}", fg=typer.colors.RED)
        typer.secho(f"   Manifest: {manifest.get('name')} v{manifest.get('version')} — edit {manifest.get('name')}/manifest.yaml to allow", fg=typer.colors.YELLOW)
        raise Exit(code=1)
    return True

def load_tool_policy(tool_manifest: Dict) -> Dict:
    # tool manifest already contains capabilities
    return tool_manifest

def expand_path(p: str) -> str:
    return os.path.expanduser(p)
