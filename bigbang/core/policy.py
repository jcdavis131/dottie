"""Capability-based policy engine — security first"""
from pathlib import Path
import yaml
from typing import List, Dict

# Default deny + explicit allow per plugin/tool
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

def check_permission(manifest: Dict, action: str, resource: str) -> tuple[bool, str]:
    """Returns (allowed, reason)"""
    caps = manifest.get("capabilities", {})
    if action == "network":
        if not caps.get("network", {}).get("enabled", False):
            return False, f"network disabled for this tool — add manifest capabilities.network.enabled"
        domains = caps.get("network", {}).get("domains", [])
        if domains and not any(resource.endswith(d) or d in resource for d in domains):
            return False, f"domain {resource} not in allowlist {domains}"
    if action == "fs_write":
        if not caps.get("filesystem", {}).get("write", False):
            return False, "filesystem write disabled"
    if action == "secret":
        allowed = caps.get("secrets", {}).get("allow", [])
        if allowed and resource not in allowed:
            return False, f"secret {resource} not in allowlist {allowed}"
    return True, "ok"
