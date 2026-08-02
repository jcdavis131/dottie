import typer

from bigbang.core.cli_ux import (
    examples_epilog,
    fail_agent,
    is_interactive,
    require_secret_value,
)
from bigbang.core.output import emit, is_json
from bigbang.core.security import delete_secret, get_secret, list_secrets, set_secret

app = typer.Typer(
    name="secrets",
    help="🔐 Vault — secrets never in repo, keyring + OS perms + audit",
    no_args_is_help=True,
    epilog=examples_epilog(
        [
            "scout secrets set GITHUB_TOKEN --value ghp_xxx",
            "printf '%s' \"$TOKEN\" | scout secrets set GITHUB_TOKEN --stdin",
            "scout --json secrets list",
            "scout secrets get GITHUB_TOKEN",
            "scout secrets rm OLD_KEY --force",
        ]
    ),
)


@app.command(
    "set",
    epilog=examples_epilog(
        [
            "scout secrets set GITHUB_TOKEN --value ghp_xxx",
            "printf '%s' \"$TOKEN\" | scout secrets set GITHUB_TOKEN --stdin",
            "scout secrets set GITHUB_TOKEN ghp_xxx   # positional still works",
        ]
    ),
)
def set_cmd(
    key: str = typer.Argument(..., help="secret name e.g. GITHUB_TOKEN"),
    value: str | None = typer.Argument(
        None, help="value (prefer --value or --stdin so it stays out of shell history)"
    ),
    value_opt: str | None = typer.Option(
        None, "--value", help="secret value (preferred for scripting; not logged)"
    ),
    use_stdin: bool = typer.Option(
        False, "--stdin", help="read secret value from stdin (pipeline-friendly)"
    ),
):
    """Vault a secret (0600 file store + optional keyring). Value never audited."""
    resolved = require_secret_value(
        positional=value,
        flag_value=value_opt,
        use_stdin=use_stdin,
        command="secrets set",
        example=f"scout secrets set {key} --value <secret>   # or: … | scout secrets set {key} --stdin",
    )
    set_secret(key, resolved)
    emit(
        {
            "message": f"secret {key} vaulted",
            "stored_in": "~/.local/share/bigbang/secrets.json (0600)",
            "audit": "logged without value",
        },
        command="secrets set",
    )


@app.command(
    "get",
    epilog=examples_epilog(
        [
            "scout --json secrets get GITHUB_TOKEN",
            "scout secrets get GITHUB_TOKEN",
        ]
    ),
)
def get_cmd(key: str = typer.Argument(..., help="secret name")):
    """Retrieve a vaulted secret (full value in JSON; masked for humans)."""
    v = get_secret(key)
    if not v:
        fail_agent(
            f"{key} not found",
            command="secrets get",
            example=f"scout secrets set {key} --value <secret>",
            discover="scout secrets list",
        )
    masked = v[:4] + "****" if len(v) > 8 else "****"
    # The docstring promises "full value in JSON; masked for humans". Only the first half
    # was true. emit() renders a dict in human mode with _console.print_json(data=data) —
    # the WHOLE dict — so `value` was printed in plaintext directly beside `masked`, and
    # the mask was decoration next to the thing it was supposed to replace.
    #
    # Verified 2026-08-02 before changing anything: `scout secrets get X` without --json
    # printed {"key": ..., "value": "SUPERSECRETVALUE123", "masked": "SUPE****", ...}.
    # The AUDIT trail was never affected — output.py redacts before log_event — which is
    # why this survived a check that confirmed redaction was working. Terminal output and
    # the audit log are different surfaces.
    #
    # JSON mode keeps `value`: agents call this to USE the secret, and that half of the
    # contract is documented and load-bearing.
    payload = {"key": key, "masked": masked, "source": "vault/keyring/env"}
    if is_json():
        payload["value"] = v
    else:
        payload["note"] = "value withheld in human output; use --json to retrieve it"
    emit(payload, command="secrets get")


@app.command(
    "list",
    epilog=examples_epilog(["scout --json secrets list"]),
)
def list_cmd():
    """List secret keys only (values never listed)."""
    keys = list_secrets()
    emit(
        {"secrets": keys, "count": len(keys), "note": "values never listed"},
        command="secrets list",
    )


@app.command(
    "rm",
    epilog=examples_epilog(
        [
            "scout secrets rm OLD_KEY --force",
            "scout secrets rm OLD_KEY --dry-run",
        ]
    ),
)
def rm_cmd(
    key: str = typer.Argument(..., help="secret name to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="skip confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="show what would be deleted"),
):
    """Delete a vaulted secret. Idempotent: missing key → ok=false, exit 0 with --force."""
    exists = get_secret(key) is not None
    if dry_run:
        emit(
            {"would_delete": key, "exists": exists, "dry_run": True},
            command="secrets rm",
        )
        return
    if exists and not force and is_interactive():
        typer.confirm(f"Delete secret {key}?", abort=True)
    elif exists and not force and not is_interactive():
        fail_agent(
            "Refusing to delete without --force in non-interactive mode",
            command="secrets rm",
            example=f"scout secrets rm {key} --force",
        )
    ok = delete_secret(key) if exists else False
    emit({"deleted": key, "ok": ok, "existed": exists}, command="secrets rm")


def register(root):
    root.add_typer(app, name="secrets")
