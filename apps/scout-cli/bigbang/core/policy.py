"""Capability-based policy engine — security first, default-deny"""

import os
from pathlib import Path
from urllib.parse import urlparse

import yaml

DEFAULT_POLICY = {
    "allow_network": False,
    "allowed_domains": [],
    "allow_fs_write": False,
    "allowed_paths": [],
    "allow_secrets": [],
}

# ---------------------------------------------------------------------------
# User-level network allowlist — persisted, default-deny.
# Vacuous per-call manifests ("allow exactly the URL I'm about to hit") are
# not a policy; this file is the user's actual say on what the CLI may reach.
# ---------------------------------------------------------------------------

DEFAULT_USER_POLICY = {
    "network": {
        # Sane default: local-only. Everything else is denied until the user
        # adds it here explicitly.
        "allowed_domains": ["localhost", "127.0.0.1", "::1"],
    }
}


def user_policy_file() -> Path:
    override = os.environ.get("BIGBANG_POLICY_FILE")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "bigbang" / "policy.yaml"


def load_user_policy() -> dict:
    fp = user_policy_file()
    if not fp.exists():
        # Materialize the default so users have a real file to edit.
        try:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(
                "# scout-cli user policy — default-deny.\n"
                "# Add domains under network.allowed_domains to allow outbound calls.\n"
                + yaml.safe_dump(DEFAULT_USER_POLICY, sort_keys=False)
            )
        except OSError:
            pass
        return DEFAULT_USER_POLICY
    try:
        data = yaml.safe_load(fp.read_text())
    except Exception:
        # Unparseable policy = deny-everything, never fail-open.
        return {"network": {"allowed_domains": []}}
    return data if isinstance(data, dict) else {"network": {"allowed_domains": []}}


def _host_of(resource: str) -> str:
    if resource.startswith(("http://", "https://")):
        return urlparse(resource).hostname or resource
    return resource


def _domain_matches(domain: str, resource: str) -> bool:
    host = _host_of(resource)
    if domain == resource or domain == host:
        return True
    if host.endswith("." + domain):
        return True
    # legacy substring semantics kept for manifest entries that store full URLs
    return bool(domain) and (domain in resource or resource.endswith(domain))


def check_user_url(url: str) -> tuple[bool, str]:
    """Check a URL against the persisted user allowlist. Default-deny."""
    policy = load_user_policy()
    domains = (policy.get("network") or {}).get("allowed_domains") or []
    if not domains:
        return False, (
            f"user network allowlist is empty (default-deny) — add domains to {user_policy_file()}"
        )
    if any(_domain_matches(str(d), url) for d in domains):
        return True, "ok"
    return False, (
        f"host {_host_of(url)} not in user allowlist {domains} — edit {user_policy_file()}"
    )


def enforce_user_url_or_raise(url: str, context: str = ""):
    ok, reason = check_user_url(url)
    if not ok:
        import typer

        typer.secho(
            f"⛔ Policy denied [network {url}]{' (' + context + ')' if context else ''}: {reason}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    return True


# ---------------------------------------------------------------------------
# Manifest capability checks — default-deny on every axis.
# ---------------------------------------------------------------------------


def load_manifest(plugin_path: Path) -> dict:
    manifest = plugin_path / "manifest.yaml"
    if not manifest.exists():
        return {}
    try:
        return yaml.safe_load(manifest.read_text()) or {}
    except Exception:
        return {}


def check_permission(manifest: dict, action: str, resource: str) -> tuple[bool, str]:
    """Returns (allowed, reason). Default-deny: empty allowlists deny everything."""
    caps = manifest.get("capabilities", {})
    if action == "network":
        net = caps.get("network", {})
        if not net.get("enabled", False):
            return (
                False,
                f"network disabled for {manifest.get('name', 'tool')} — add manifest capabilities.network.enabled",
            )
        domains = net.get("domains", []) or []
        if not domains:
            # documented default-deny: enabling network without naming domains allows nothing
            return False, (
                f"network enabled but domain allowlist is empty for {manifest.get('name', 'tool')} "
                "— default-deny; list domains in manifest capabilities.network.domains"
            )
        # explicit deny on mismatch for every resource shape (URLs and bare hosts alike)
        if not any(_domain_matches(str(d), resource) for d in domains):
            return False, f"domain {resource} not in allowlist {domains}"
    if action == "fs_write":
        if not caps.get("filesystem", {}).get("write", False):
            return (
                False,
                "filesystem write disabled — add manifest capabilities.filesystem.write=true",
            )
    if action == "secret":
        allowed = caps.get("secrets", {}).get("allow", [])
        if allowed and resource not in allowed:
            return False, f"secret {resource} not in allowlist {allowed}"
    return True, "ok"


def enforce_or_raise(manifest: dict, action: str, resource: str):
    ok, reason = check_permission(manifest, action, resource)
    if not ok:
        import typer
        from typer import Exit

        typer.secho(
            f"⛔ Policy denied [{action} {resource}]: {reason}", fg=typer.colors.RED
        )
        typer.secho(
            f"   Manifest: {manifest.get('name')} v{manifest.get('version')} — edit {manifest.get('name')}/manifest.yaml to allow",
            fg=typer.colors.YELLOW,
        )
        raise Exit(code=1)
    return True
