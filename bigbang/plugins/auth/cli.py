import typer
from bigbang.core.output import emit
from bigbang.core.security import set_secret, get_secret
from pathlib import Path
import json

app = typer.Typer(name="auth", help="🔑 Auth — OAuth device flow + API keys for any service", no_args_is_help=True)

REG = Path.home() / ".local" / "share" / "bigbang" / "auth.json"

def _load():
    if REG.exists():
        try: return json.loads(REG.read_text())
        except: return {}
    return {}
def _save(d): REG.write_text(json.dumps(d, indent=2))

@app.command("login")
def login(service: str = typer.Argument(..., help="service name e.g. github, openai, notion, linear"),
          method: str = typer.Option("api_key", help="api_key|oauth|oauth_device")):
    emit({
        "service": service,
        "method": method,
        "flow": {
            "api_key": "bb secrets set <SERVICE>_TOKEN <value>",
            "oauth": "open oauth browser, then bb auth set-token",
            "oauth_device": "device flow code -> poll"
        }[method],
        "next": f"bb secrets set {service.upper()}_TOKEN your-token-here",
        "storage": "vault 0600 + keyring + audit log"
    }, command="auth login")

@app.command("list")
def list_auth():
    db = _load()
    emit({"authenticated_services": list(db.keys()), "vault_keys_via_secrets": "bb secrets list"}, command="auth list")

@app.command("set-token")
def set_token(service: str, token: str):
    set_secret(f"{service.upper()}_TOKEN", token)
    db = _load()
    db[service] = {"method": "token", "vault_key": f"{service.upper()}_TOKEN"}
    _save(db)
    emit({"service": service, "status": "token vaulted"}, command="auth set-token")

def register(root): root.add_typer(app, name="auth")
