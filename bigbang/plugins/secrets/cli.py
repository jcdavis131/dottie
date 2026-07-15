import typer
from bigbang.core.output import emit
from bigbang.core.security import set_secret, get_secret, list_secrets, delete_secret

app = typer.Typer(name="secrets", help="🔐 Vault — secrets never in repo, keyring + OS perms + audit", no_args_is_help=True)

@app.command("set")
def set_cmd(key: str = typer.Argument(..., help="secret name e.g. GITHUB_TOKEN"), value: str = typer.Argument(..., help="value (will be vaulted, not logged)")):
    set_secret(key, value)
    emit({"message": f"secret {key} vaulted", "stored_in": "~/.local/share/bigbang/secrets.json (0600)", "audit": "logged without value"}, command="secrets set")

@app.command("get")
def get_cmd(key: str = typer.Argument(...)):
    v = get_secret(key)
    if not v:
        emit({"error": f"{key} not found", "hint": "bb secrets set <key> <value> or BB_SECRET_<KEY> env"}, command="secrets get")
    else:
        # only show masked in human mode, full in json mode via emit still masked audit
        masked = v[:4] + "****" if len(v) > 8 else "****"
        emit({"key": key, "value": v, "masked": masked, "source": "vault/keyring/env"}, command="secrets get")

@app.command("list")
def list_cmd():
    keys = list_secrets()
    emit({"secrets": keys, "count": len(keys), "note": "values never listed"}, command="secrets list")

@app.command("rm")
def rm_cmd(key: str):
    ok = delete_secret(key)
    emit({"deleted": key, "ok": ok}, command="secrets rm")

def register(root): root.add_typer(app, name="secrets")
