"""
Auth plugin — OAuth device flow + API keys for any service
Implements GitHub device flow fully, generic device flow, PAT fallback,
secure vault storage, and env fallback.

Solo personal project, no connection to employer, built with public/free-tier only
"""
import json
import os
import time
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timezone

import typer
from rich.console import Console

from bigbang.core.cli_ux import examples_epilog, prompt_secret_or_fail, require_secret_value
from bigbang.core.output import emit
from bigbang.core.security import set_secret, get_secret
from bigbang.core.http_utils import sanitize_no_proxy_env

# Ensure NO_PROXY sanitized for httpx
sanitize_no_proxy_env()

app = typer.Typer(
    name="auth",
    help="🔑 Auth — OAuth device flow + API keys for any service",
    no_args_is_help=True,
    epilog=examples_epilog(
        [
            "scout auth set-token github --token ghp_xxx",
            "printf '%s' \"$TOKEN\" | scout auth set-token github --stdin",
            "scout auth login github --method pat --token ghp_xxx",
            "scout --json auth list",
            "scout auth status github",
        ]
    ),
)

_console = Console()

# Storage path: ~/.local/share/bigbang/auth.json (keep existing)
REG = Path.home() / ".local" / "share" / "bigbang" / "auth.json"

# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _load_auth() -> Dict[str, Any]:
    """Load auth registry from REG. Returns {} if missing/corrupt."""
    if REG.exists():
        try:
            return json.loads(REG.read_text())
        except Exception:
            return {}
    return {}

def _save_auth(data: Dict[str, Any]) -> None:
    """Save auth registry with 0600 perms."""
    REG.parent.mkdir(parents=True, exist_ok=True)
    REG.write_text(json.dumps(data, indent=2))
    try:
        os.chmod(REG, 0o600)
    except Exception:
        pass

# Backward compat shims for old names
def _load() -> Dict[str, Any]:
    return _load_auth()

def _save(d: Dict[str, Any]) -> None:
    return _save_auth(d)

# ---------------------------------------------------------------------------
# Service configs for device flow
# ---------------------------------------------------------------------------

SERVICE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "github": {
        "display_name": "GitHub",
        "device_code_url": "https://github.com/login/device/code",
        "access_token_url": "https://github.com/login/oauth/access_token",
        "default_scopes": "repo read:user user:email",
        "vault_key": "GITHUB_TOKEN",
        "client_id_env_vars": ["BB_SECRET_GITHUB_CLIENT_ID", "GITHUB_CLIENT_ID"],
        "client_id_secret_keys": ["GITHUB_CLIENT_ID"],
        "docs": "https://docs.github.com/en/developers/apps/building-oauth-apps/authorizing-oauth-apps#device-flow",
        "token_url_docs": "https://github.com/settings/tokens",
    },
    "google": {
        "display_name": "Google",
        "device_code_url": "https://oauth2.googleapis.com/device/code",
        "access_token_url": "https://oauth2.googleapis.com/token",
        "default_scopes": "openid email profile",
        "vault_key": "GOOGLE_TOKEN",
        "client_id_env_vars": ["BB_SECRET_GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_ID"],
        "client_id_secret_keys": ["GOOGLE_CLIENT_ID"],
        "docs": "https://developers.google.com/identity/protocols/oauth2/limited-input-device",
    },
    "notion": {
        "display_name": "Notion",
        "device_code_url": None,  # Notion uses browser OAuth, no device flow
        "access_token_url": "https://api.notion.com/v1/oauth/token",
        "vault_key": "NOTION_TOKEN",
        "client_id_env_vars": ["BB_SECRET_NOTION_CLIENT_ID", "NOTION_CLIENT_ID"],
        "client_id_secret_keys": ["NOTION_CLIENT_ID"],
        "docs": "https://developers.notion.com/docs/authorization",
    },
    "linear": {
        "display_name": "Linear",
        "device_code_url": None,
        "vault_key": "LINEAR_TOKEN",
        "client_id_env_vars": ["BB_SECRET_LINEAR_CLIENT_ID"],
        "client_id_secret_keys": ["LINEAR_CLIENT_ID"],
    },
    "openai": {
        "display_name": "OpenAI",
        "device_code_url": None,
        "vault_key": "OPENAI_API_KEY",
        "client_id_env_vars": [],
        "client_id_secret_keys": [],
    },
}

# ---------------------------------------------------------------------------
# Token retrieval with env fallback
# ---------------------------------------------------------------------------

def get_token(service: str) -> Optional[str]:
    """
    Internal helper: retrieve token for service via security.get_secret with env fallback.
    Order:
      1. security.get_secret(f"{SERVICE}_TOKEN")
      2. security.get_secret(service) / service.upper()
      3. Direct os.environ fallback for common variants like GITHUB_TOKEN
      4. Auth.json has no secret values, only metadata - so no read there
    """
    if not service:
        return None
    svc = service.lower().strip()
    # Normalize vault keys to try
    candidates = []
    cfg = SERVICE_CONFIGS.get(svc)
    if cfg and cfg.get("vault_key"):
        candidates.append(cfg["vault_key"])
    # Generic variants
    candidates.extend([
        f"{svc.upper()}_TOKEN",
        f"{svc.upper()}_API_KEY",
        f"{svc.upper()}_PAT",
        svc.upper(),
        svc,
    ])
    # Deduplicate preserve order
    seen = set()
    uniq = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)

    for key in uniq:
        try:
            v = get_secret(key)
            if v:
                return v
        except Exception:
            continue

    # Direct env fallback (get_secret already checks BB_SECRET_{key}, but also check bare tokens for DX)
    for env_name in [f"{svc.upper()}_TOKEN", f"{svc.upper()}_API_KEY", f"{svc.upper()}_PAT"]:
        if env_name in os.environ and os.environ[env_name].strip():
            return os.environ[env_name].strip()

    return None


def _resolve_client_id(service: str, cfg: Dict[str, Any], explicit: Optional[str] = None) -> Optional[str]:
    """Resolve OAuth client_id from explicit arg, env vars, or vault."""
    if explicit and explicit.strip():
        return explicit.strip()

    # Env vars listed
    for env_name in cfg.get("client_id_env_vars", []):
        if env_name in os.environ and os.environ[env_name].strip():
            return os.environ[env_name].strip()
        # Also try via get_secret for BB_SECRET_ prefix
        # get_secret expects key without BB_SECRET_ prefix? It checks BB_SECRET_{KEY}
        # So for BB_SECRET_GITHUB_CLIENT_ID, we need get_secret("GITHUB_CLIENT_ID")
        # Let's try both paths
        # Direct get_secret lookup for similar key
        # strip BB_SECRET_ prefix
        if env_name.startswith("BB_SECRET_"):
            inner = env_name[len("BB_SECRET_"):]
            v = get_secret(inner)
            if v:
                return v

    # Secret keys
    for sk in cfg.get("client_id_secret_keys", []):
        try:
            v = get_secret(sk)
            if v:
                return v
        except Exception:
            continue

    # Generic fallback: BB_SECRET_GITHUB_CLIENT_ID is also checked via os.environ directly
    generic_env = f"BB_SECRET_{service.upper()}_CLIENT_ID"
    if generic_env in os.environ:
        return os.environ[generic_env].strip()
    # Also try generic secret
    try:
        v = get_secret(f"{service.upper()}_CLIENT_ID")
        if v:
            return v
    except Exception:
        pass

    return None

# ---------------------------------------------------------------------------
# Device flow helpers
# ---------------------------------------------------------------------------

def _prompt_for_pat(service: str, flag_value: Optional[str] = None) -> Optional[str]:
    """Resolve PAT/API key from --token, else prompt on TTY, else fail (never hang)."""
    svc_display = SERVICE_CONFIGS.get(service.lower(), {}).get("display_name", service)
    cfg = SERVICE_CONFIGS.get(service.lower(), {})
    example = (
        f"scout auth login {service} --method pat --token <token>  "
        f"# or: scout auth set-token {service} --token <token>"
    )
    if flag_value and str(flag_value).strip():
        return str(flag_value).strip()
    try:
        _console.print(
            f"[yellow]No OAuth client configured for {svc_display}. "
            f"Falling back to personal access token.[/yellow]"
        )
        if cfg.get("token_url_docs"):
            _console.print(f"Create token at: {cfg['token_url_docs']}")
        return prompt_secret_or_fail(
            f"Enter {svc_display} token (input hidden)",
            command="auth login",
            example=example,
        )
    except typer.Exit:
        raise
    except (KeyboardInterrupt, EOFError):
        _console.print("\n[cancelled] cancelled")
        return None


def _open_browser_url(url: str, do_open: bool) -> None:
    if not do_open or not url:
        return
    try:
        webbrowser.open(url)
        _console.print(f"[dim]Opened browser to {url}[/dim]")
    except Exception as e:
        _console.print(f"[dim]Could not open browser automatically: {e}. Please open {url} manually.[/dim]")


def _do_github_device_flow(
    client_id: str,
    scopes: Optional[str] = None,
    open_browser_flag: bool = True,
) -> Optional[str]:
    """
    Full GitHub OAuth device flow:
    POST https://github.com/login/device/code with client_id
    -> device_code, user_code, verification_uri
    Poll POST https://github.com/login/oauth/access_token
    """
    sanitize_no_proxy_env()
    try:
        import httpx
    except ImportError:
        emit(
            {
                "error": "httpx not installed",
                "hint": "pip install httpx",
            },
            command="auth login",
        )
        return None

    cfg = SERVICE_CONFIGS["github"]
    device_url = cfg["device_code_url"]
    token_url = cfg["access_token_url"]
    scope = scopes or cfg.get("default_scopes") or "repo"

    # Step 1: Request device code
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            resp = client.post(
                device_url,
                data={"client_id": client_id, "scope": scope},
                headers={"Accept": "application/json"},
            )
            # GitHub may return 200 with error json if bad client_id
            if resp.status_code != 200:
                try:
                    err_j = resp.json()
                    msg = err_j.get("error_description") or err_j.get("error") or resp.text
                except Exception:
                    msg = resp.text
                _console.print(f"[red]Failed to start device flow ({resp.status_code}): {msg}[/red]")
                return None

            data = resp.json() if "application/json" in resp.headers.get("content-type", "") else {}
            if not data:
                # Try urlencoded fallback
                try:
                    from urllib.parse import parse_qs

                    qs = parse_qs(resp.text)
                    data = {k: v[0] for k, v in qs.items()}
                except Exception:
                    data = resp.json()

            device_code = data.get("device_code")
            user_code = data.get("user_code")
            verification_uri = data.get("verification_uri") or "https://github.com/login/device"
            verification_uri_complete = data.get("verification_uri_complete") or verification_uri
            expires_in = int(data.get("expires_in", 900))
            interval = int(data.get("interval", 5))

            if not device_code or not user_code:
                _console.print(f"[red]Device flow initiation failed, response: {data}[/red]")
                return None

            # Step 2: Instruct user
            _console.print("\n[bold]🔑 GitHub Device Flow[/bold]")
            _console.print(f"  1. Go to: [bold cyan]{verification_uri}[/bold cyan]")
            _console.print(f"  2. Enter code: [bold green]{user_code}[/bold green]")
            _console.print(f"  3. Complete URL (with code): {verification_uri_complete}")
            _console.print(f"  Expires in {expires_in}s, polling every {interval}s")
            _console.print("  Waiting for authorization...\n")

            _open_browser_url(verification_uri_complete, open_browser_flag)

            # Step 3: Poll
            start = time.time()
            poll_interval = interval

            while True:
                if time.time() - start > expires_in:
                    _console.print("[red]Device code expired, please run `scout auth login github` again.[/red]")
                    return None

                time.sleep(poll_interval)

                try:
                    poll_resp = client.post(
                        token_url,
                        data={
                            "client_id": client_id,
                            "device_code": device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                        headers={"Accept": "application/json"},
                    )
                    poll_data = poll_resp.json() if "application/json" in poll_resp.headers.get("content-type", "") else {}
                    if not poll_data:
                        from urllib.parse import parse_qs

                        qs = parse_qs(poll_resp.text)
                        poll_data = {k: v[0] for k, v in qs.items()}

                    if "access_token" in poll_data:
                        token = poll_data["access_token"]
                        _console.print("[green]✓ Authorization successful![/green]")
                        return token

                    err = poll_data.get("error")
                    if err == "authorization_pending":
                        # continue polling
                        _console.print("[dim].[/dim] waiting...", end="\r")
                        continue
                    elif err == "slow_down":
                        poll_interval += 5
                        _console.print(f"[yellow]Slow down requested, now polling every {poll_interval}s[/yellow]")
                        continue
                    elif err == "expired_token":
                        _console.print("[red]Device code expired (expired_token).[/red]")
                        return None
                    elif err == "unsupported_grant_type":
                        _console.print(f"[red]Unsupported grant type: {poll_data}[/red]")
                        return None
                    elif err == "incorrect_client_credentials" or err == "incorrect_device_code":
                        _console.print(f"[red]Client error: {poll_data.get('error_description') or err}[/red]")
                        return None
                    elif err == "access_denied":
                        _console.print("[red]Access denied by user.[/red]")
                        return None
                    elif err:
                        # Other errors
                        _console.print(f"[yellow]Poll error {err}: {poll_data.get('error_description','')}, retrying...[/yellow]")
                        continue

                except Exception as e:
                    _console.print(f"[yellow]Poll request failed: {e}, retrying...[/yellow]")
                    continue

    except Exception as e:
        _console.print(f"[red]Device flow failed: {e}[/red]")
        return None


def _do_generic_device_flow(
    service: str,
    cfg: Dict[str, Any],
    client_id: str,
    scopes: Optional[str] = None,
    open_browser_flag: bool = True,
) -> Optional[str]:
    """
    Generic OAuth device flow if service defines device_code_url and access_token_url.
    Implements RFC 8628 generic.
    """
    sanitize_no_proxy_env()
    try:
        import httpx
    except ImportError:
        emit({"error": "httpx not installed, need httpx for OAuth"}, command="auth login")
        return None

    device_url = cfg.get("device_code_url")
    token_url = cfg.get("access_token_url")
    if not device_url or not token_url:
        return None

    scope = scopes or cfg.get("default_scopes") or "openid email"
    display = cfg.get("display_name", service)

    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            # Device code request typically form-encoded
            resp = client.post(
                device_url,
                data={"client_id": client_id, "scope": scope},
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                _console.print(f"[red]{display} device flow start failed {resp.status_code}: {resp.text[:500]}[/red]")
                return None
            try:
                data = resp.json()
            except Exception:
                from urllib.parse import parse_qs

                qs = parse_qs(resp.text)
                data = {k: v[0] for k, v in qs.items()}

            device_code = data.get("device_code")
            user_code = data.get("user_code")
            verification_uri = data.get("verification_uri") or data.get("verification_url")
            verification_complete = data.get("verification_uri_complete") or data.get("verification_url_complete") or verification_uri
            expires_in = int(data.get("expires_in", 600))
            interval = int(data.get("interval", 5))

            if not device_code or not user_code:
                _console.print(f"[red]Could not start {display} device flow: {data}[/red]")
                return None

            _console.print(f"\n[bold]🔑 {display} Device Flow[/bold]")
            _console.print(f"  URL: [cyan]{verification_uri}[/cyan]")
            _console.print(f"  Code: [green]{user_code}[/green]")
            if verification_complete and verification_complete != verification_uri:
                _console.print(f"  Complete: {verification_complete}")
            _console.print(f"  Expires in {expires_in}s")

            _open_browser_url(verification_complete or verification_uri, open_browser_flag)

            start = time.time()
            poll_interval = interval
            while True:
                if time.time() - start > expires_in:
                    _console.print("[red]Code expired[/red]")
                    return None
                time.sleep(poll_interval)
                try:
                    poll_resp = client.post(
                        token_url,
                        data={
                            "client_id": client_id,
                            "device_code": device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                        headers={"Accept": "application/json"},
                    )
                    poll_data = {}
                    try:
                        poll_data = poll_resp.json()
                    except Exception:
                        from urllib.parse import parse_qs

                        qs = parse_qs(poll_resp.text)
                        poll_data = {k: v[0] for k, v in qs.items()}

                    if "access_token" in poll_data:
                        _console.print("[green]✓ Authorized[/green]")
                        return poll_data["access_token"]
                    err = poll_data.get("error")
                    if err == "authorization_pending":
                        continue
                    if err == "slow_down":
                        poll_interval += 5
                        continue
                    if err in ("expired_token", "access_denied"):
                        _console.print(f"[red]{err}[/red]")
                        return None
                    if err:
                        _console.print(f"[yellow]{err}: {poll_data.get('error_description','')} retrying[/yellow]")
                        continue
                except Exception as e:
                    _console.print(f"[yellow]Poll error {e}[/yellow]")
                    continue

    except Exception as e:
        _console.print(f"[red]{display} device flow error: {e}[/red]")
        return None

# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------

@app.command(
    "login",
    epilog=examples_epilog(
        [
            "scout auth login github --method pat --token ghp_xxx",
            "scout auth login github --no-browser   # device flow, print URL only",
            "scout auth set-token notion --token ntn_xxx",
        ]
    ),
)
def login(
    service: str = typer.Argument(..., help="service name e.g. github, google, notion, linear, openai"),
    method: str = typer.Option("auto", "--method", "-m", help="auto|device|pat|api_key|oauth_device|token"),
    client_id: Optional[str] = typer.Option(None, "--client-id", help="OAuth client_id, or set BB_SECRET_GITHUB_CLIENT_ID"),
    open_browser: bool = typer.Option(True, "--browser/--no-browser", help="Open browser automatically for device flow"),
    scope: Optional[str] = typer.Option(None, "--scope", help="OAuth scopes (e.g. 'repo read:user')"),
    token: Optional[str] = typer.Option(
        None, "--token", "-t", help="PAT/API key for non-interactive login (skip prompt)"
    ),
):
    """
    Authenticate a service. Uses OAuth device flow if client_id available, else PAT.

    Agents: pass --token (or use set-token --token/--stdin). Never hangs waiting for a prompt.
    """
    svc = service.lower().strip()
    cfg = SERVICE_CONFIGS.get(svc)

    # Normalize method
    method_norm = method.lower().strip()
    if method_norm not in ("auto", "device", "oauth_device", "oauth", "pat", "api_key", "token"):
        emit(
            {
                "error": f"Unknown method {method}",
                "allowed": ["auto", "device", "pat", "api_key", "token"],
                "example": f"scout auth login {svc} --method pat --token <token>",
            },
            command="auth login",
        )
        raise typer.Exit(code=1)

    # If explicitly pat/api_key/token -> prompt (or --token)
    if method_norm in ("pat", "api_key", "token"):
        token_val = _prompt_for_pat(svc, flag_value=token)
        if not token_val:
            emit({"service": svc, "status": "cancelled"}, command="auth login")
            raise typer.Exit(code=1)
        vault_key = (cfg.get("vault_key") if cfg else f"{svc.upper()}_TOKEN") or f"{svc.upper()}_TOKEN"
        set_secret(vault_key, token_val)
        db = _load_auth()
        db[svc] = {
            "method": "token",
            "vault_key": vault_key,
            "service": svc,
            "authenticated_at": datetime.now(timezone.utc).isoformat(),
            "has_token": True,
        }
        _save_auth(db)
        emit(
            {
                "service": svc,
                "status": "authenticated",
                "method": "token",
                "vault_key": vault_key,
                "message": "Token vaulted securely (0600 + keyring + audit). Value not displayed.",
            },
            command="auth login",
        )
        return

    # Try device flow path if cfg exists and has device_code_url
    if cfg and cfg.get("device_code_url"):
        resolved_cid = _resolve_client_id(svc, cfg, explicit=client_id)

        if not resolved_cid:
            # No client_id -> fallback messaging and PAT prompt for MVP v0.4
            if svc == "github":
                _console.print(
                    f"[yellow]GitHub client_id not found. Set via --client-id, "
                    f"or env BB_SECRET_GITHUB_CLIENT_ID, or via: scout secrets set GITHUB_CLIENT_ID --value <id>[/yellow]"
                )
                _console.print(
                    "[dim]Falling back to PAT flow. Create PAT at https://github.com/settings/tokens "
                    "(classic or fine-grained) with repo scope.[/dim]"
                )
            else:
                _console.print(
                    f"[yellow]{cfg.get('display_name', svc)} client_id not configured. "
                    f"Set --client-id or {cfg.get('client_id_env_vars', ['CLIENT_ID'])[0] if cfg.get('client_id_env_vars') else 'CLIENT_ID'}"
                )

            if method_norm in ("device", "oauth_device"):
                # User explicitly asked device but no client_id -> error then fallback prompt
                emit(
                    {
                        "service": svc,
                        "status": "client_id_missing",
                        "hint": f"Set {cfg.get('client_id_env_vars', ['BB_SECRET_'+svc.upper()+'_CLIENT_ID'])[0]} or pass --client-id, or use PAT fallback",
                        "fallback": f"scout auth set-token {svc} <token>",
                    },
                    command="auth login",
                )
                # Still offer PAT for UX
                token_val = _prompt_for_pat(svc, flag_value=token)
                if token_val:
                    vault_key = cfg.get("vault_key") or f"{svc.upper()}_TOKEN"
                    set_secret(vault_key, token_val)
                    db = _load_auth()
                    db[svc] = {
                        "method": "token",
                        "vault_key": vault_key,
                        "service": svc,
                        "authenticated_at": datetime.now(timezone.utc).isoformat(),
                        "has_token": True,
                    }
                    _save_auth(db)
                    emit(
                        {
                            "service": svc,
                            "status": "authenticated",
                            "method": "token",
                            "vault_key": vault_key,
                            "message": "Token vaulted via PAT fallback.",
                        },
                        command="auth login",
                    )
                    return
                else:
                    raise typer.Exit(code=1)
            else:
                # auto mode -> PAT fallback
                token_val = _prompt_for_pat(svc, flag_value=token)
                if not token_val:
                    emit({"service": svc, "status": "cancelled"}, command="auth login")
                    raise typer.Exit(code=1)
                vault_key = cfg.get("vault_key") or f"{svc.upper()}_TOKEN"
                set_secret(vault_key, token_val)
                db = _load_auth()
                db[svc] = {
                    "method": "token",
                    "vault_key": vault_key,
                    "service": svc,
                    "authenticated_at": datetime.now(timezone.utc).isoformat(),
                    "has_token": True,
                }
                _save_auth(db)
                emit(
                    {
                        "service": svc,
                        "status": "authenticated",
                        "method": "token",
                        "vault_key": vault_key,
                        "message": "Token vaulted securely. Value not displayed.",
                    },
                    command="auth login",
                )
                return
        else:
            # Have client_id -> run device flow
            if svc == "github":
                token_val = _do_github_device_flow(resolved_cid, scopes=scope, open_browser_flag=open_browser)
            else:
                token_val = _do_generic_device_flow(svc, cfg, resolved_cid, scopes=scope, open_browser_flag=open_browser)

            if not token_val:
                emit(
                    {
                        "service": svc,
                        "status": "failed",
                        "method": "oauth_device",
                        "hint": f"Try PAT fallback: scout auth set-token {svc} <token>",
                    },
                    command="auth login",
                )
                raise typer.Exit(code=1)

            vault_key = cfg.get("vault_key") or f"{svc.upper()}_TOKEN"
            set_secret(vault_key, token_val)
            db = _load_auth()
            db[svc] = {
                "method": "oauth_device",
                "vault_key": vault_key,
                "service": svc,
                "authenticated_at": datetime.now(timezone.utc).isoformat(),
                "has_token": True,
                "scopes": scope or cfg.get("default_scopes"),
            }
            _save_auth(db)
            emit(
                {
                    "service": svc,
                    "status": "authenticated",
                    "method": "oauth_device",
                    "vault_key": vault_key,
                    "message": "OAuth token obtained via device flow and vaulted securely. Value not displayed.",
                },
                command="auth login",
            )
            return
    else:
        # Service not in SERVICE_CONFIGS or no device_code_url -> generic manual instructions
        # For MVP v0.4: prompt PAT and store
        if cfg and not cfg.get("device_code_url"):
            _console.print(f"[dim]{cfg.get('display_name', svc)} does not support device flow; using token flow.[/dim]")

        token_val: Optional[str] = None

        # If user is in auto and service unknown, show generic flow description but still allow PAT
        if method_norm == "auto":
            # For unknown services, explain both options
            _console.print(f"[bold]Auth for {svc}[/bold]")
            _console.print(f"  No device flow configured for {svc}.")
            _console.print(f"  Options:")
            _console.print(f"    1. scout auth set-token {svc} <token>  (stores via vault)")
            _console.print(f"    2. Set env {svc.upper()}_TOKEN or BB_SECRET_{svc.upper()}_TOKEN")
            # Still prompt
            token_val = _prompt_for_pat(svc, flag_value=token)
        else:
            token_val = _prompt_for_pat(svc, flag_value=token)

        if not token_val:
            # Emit instruction JSON
            flow_desc = {
                "api_key": f"scout secrets set {svc.upper()}_TOKEN <value> or scout auth set-token {svc} <token>",
                "oauth": f"open browser for {svc} oauth, then scout auth set-token {svc} <token>",
                "oauth_device": "device flow code -> poll (if service supports RFC8628)",
            }
            emit(
                {
                    "service": svc,
                    "method": method_norm,
                    "flow": flow_desc.get(method_norm, flow_desc["api_key"]),
                    "next": f"scout auth set-token {svc} <token>",
                    "storage": "vault 0600 + keyring + audit log",
                    "known_services": list(SERVICE_CONFIGS.keys()),
                },
                command="auth login",
            )
            return

        vault_key = (cfg.get("vault_key") if cfg else None) or f"{svc.upper()}_TOKEN"
        set_secret(vault_key, token_val)
        db = _load_auth()
        db[svc] = {
            "method": "token",
            "vault_key": vault_key,
            "service": svc,
            "authenticated_at": datetime.now(timezone.utc).isoformat(),
            "has_token": True,
        }
        _save_auth(db)
        emit(
            {
                "service": svc,
                "status": "authenticated",
                "method": "token",
                "vault_key": vault_key,
                "message": "Token vaulted securely (0600 + keyring). Value not displayed.",
            },
            command="auth login",
        )
        return


@app.command(
    "set-token",
    epilog=examples_epilog(
        [
            "scout auth set-token github --token ghp_xxx",
            "printf '%s' \"$TOKEN\" | scout auth set-token github --stdin",
            "scout auth set-token github ghp_xxx   # positional still works",
        ]
    ),
)
def set_token(
    service: str = typer.Argument(..., help="service name e.g. github, notion, openai"),
    token: Optional[str] = typer.Argument(
        None,
        help="Token value (prefer --token or --stdin so it stays out of shell history)",
    ),
    token_opt: Optional[str] = typer.Option(
        None, "--token", "-t", help="Token value (preferred for scripting)"
    ),
    use_stdin: bool = typer.Option(
        False, "--stdin", help="read token from stdin (pipeline-friendly)"
    ),
):
    """
    Store token in vault (0600 + keyring + audit) and link in auth.json.
    Never reveals token in output. Agents: always pass --token or --stdin.
    """
    actual_token = require_secret_value(
        positional=token,
        flag_value=token_opt,
        use_stdin=use_stdin,
        command="auth set-token",
        example=(
            f"scout auth set-token {service} --token <token>  "
            f"# or: printf '%s' \"$TOKEN\" | scout auth set-token {service} --stdin"
        ),
    )
    svc = service.lower().strip()
    cfg = SERVICE_CONFIGS.get(svc)
    vault_key = (cfg.get("vault_key") if cfg else None) or f"{svc.upper()}_TOKEN"

    # Store via security.set_secret (vault 0600 + keyring + audit)
    set_secret(vault_key, actual_token)

    # Also store metadata in auth.json
    db = _load_auth()
    db[svc] = {
        "method": "token",
        "vault_key": vault_key,
        "service": svc,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "has_token": True,
    }
    _save_auth(db)

    # Explicitly do not reveal token; clear local var
    del actual_token

    emit(
        {
            "service": svc,
            "status": "token vaulted",
            "vault_key": vault_key,
            "auth_file": str(REG),
            "message": "Token stored securely (0600 + keyring). Auth mapping updated. Value never displayed.",
        },
        command="auth set-token",
    )


@app.command("list")
def list_auth():
    """
    List services with token present (keys only, no values).
    """
    db = _load_auth()
    services = sorted(db.keys())

    # Also check for vault keys that might not have auth.json entry? For UX, include those if they match *_TOKEN pattern?
    # But spec says list services with token present (keys only, not values) from auth.json
    # We'll keep auth.json as source of truth, plus hint about secrets

    emit(
        {
            "authenticated_services": services,
            "count": len(services),
            "auth_file": str(REG),
            "vault_hint": "scout secrets list (values never listed)",
        },
        command="auth list",
    )


@app.command("get-token")
def get_token_cmd(
    service: str = typer.Argument(..., help="service name"),
    reveal: bool = typer.Option(False, "--reveal", help="Reveal full token value (default masks, for scripting)"),
):
    """
    Retrieve token via security.get_secret with env fallback.
    Masks value by default; never logs secret.
    """
    svc = service.lower().strip()
    token_val = get_token(svc)

    if not token_val:
        emit(
            {
                "service": svc,
                "found": False,
                "vault_key": f"{svc.upper()}_TOKEN",
                "hint": f"scout auth login {svc} or scout auth set-token {svc} <token> or set env {svc.upper()}_TOKEN",
                "auth_file": str(REG),
            },
            command="auth get-token",
        )
        raise typer.Exit(code=1)

    masked = (token_val[:4] + "****") if len(token_val) > 8 else "****"

    out: Dict[str, Any] = {
        "service": svc,
        "found": True,
        "masked": masked,
        "vault_key": f"{svc.upper()}_TOKEN",
        "source": "vault/keyring/env",
        "length": len(token_val),
    }
    if reveal:
        out["value"] = token_val
        out["warning"] = "Full token revealed because --reveal was passed. Avoid logging."
    else:
        out["value"] = None
        out["note"] = "Use --reveal to show full value, or env BB_SECRET_..."

    emit(out, command="auth get-token")


@app.command("status")
def status_cmd(service: Optional[str] = typer.Argument(None, help="Service to check, or all if omitted")):
    """
    Show auth status without revealing secrets.
    """
    db = _load_auth()
    if service:
        svc = service.lower().strip()
        token_val = get_token(svc)
        meta = db.get(svc, {})
        emit(
            {
                "service": svc,
                "authenticated": token_val is not None,
                "has_token": token_val is not None,
                "method": meta.get("method", "unknown" if token_val else "none"),
                "vault_key": meta.get("vault_key", f"{svc.upper()}_TOKEN"),
                "auth_file_entry": bool(svc in db),
                "source": "vault/keyring/env" if token_val else "none",
            },
            command="auth status",
        )
    else:
        rows = []
        for s, meta in db.items():
            has = get_token(s) is not None
            rows.append(
                {
                    "service": s,
                    "authenticated": has,
                    "method": meta.get("method"),
                    "vault_key": meta.get("vault_key"),
                }
            )
        emit(
            {
                "services": rows,
                "count": len(rows),
                "authenticated_count": sum(1 for r in rows if r["authenticated"]),
            },
            command="auth status",
        )


@app.command("logout")
def logout(
    service: str = typer.Argument(..., help="service to logout"),
    delete_vault: bool = typer.Option(True, "--delete-vault/--keep-vault", help="Delete from vault as well"),
):
    """
    Remove service from auth.json and optionally delete vault secret.
    """
    svc = service.lower().strip()
    db = _load_auth()
    existed = svc in db
    if existed:
        del db[svc]
        _save_auth(db)

    vault_deleted = False
    if delete_vault:
        cfg = SERVICE_CONFIGS.get(svc)
        vault_key = (cfg.get("vault_key") if cfg else None) or f"{svc.upper()}_TOKEN"
        try:
            from bigbang.core.security import delete_secret

            vault_deleted = delete_secret(vault_key)
        except Exception:
            # Fallback: overwrite with empty? security.delete_secret handles keyring too
            vault_deleted = False

    emit(
        {
            "service": svc,
            "removed_from_auth_json": existed,
            "vault_deleted": vault_deleted,
            "auth_file": str(REG),
        },
        command="auth logout",
    )


def register(root):
    root.add_typer(app, name="auth")

# Solo personal project, no connection to employer, built with public/free-tier only
