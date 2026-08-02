"""The auth plugin's own commands. 989 loc, no test file until 2026-08-02.

GOAT scored auth 6.33 with D4 0 -- the largest untested command surface in the CLI, and
an authentication one. Same shape as the secrets plugin one commit earlier (2a24c22):
bigbang.core.security was covered, the plugin sitting on top of it was not.

WHAT THIS COVERS, and why these commands. `logout` is the one with a claim worth pinning:
it deletes exactly ONE vault key, while get_token() reads five key variants plus three
bare env vars. "Logged out" was therefore free to be false at the moment it printed. The
read path and the delete path disagreeing is the same defect this session found inside
core/security.py itself (see tests/test_security_stores.py).

conftest.py redirects HOME, so every vault and auth.json here is a throwaway.
"""

from __future__ import annotations

import json

import pytest

from bigbang.core.output import set_json_mode
from bigbang.core.security import set_secret
from bigbang.plugins.auth import cli as ac

# Named PROBE_VALUE, not PROBE_TOKEN: ruff S105 flags a literal assigned to a name ending
# in TOKEN, and a noqa would spend a suppression on a test fixture. The literal is
# self-describing so nobody greps it and panics.
PROBE_VALUE = "pt-4c81-not-a-real-credential"


@pytest.fixture(autouse=True)
def _json_mode():
    set_json_mode(True)
    yield
    set_json_mode(False)


@pytest.fixture(autouse=True)
def _clean_slate(monkeypatch):
    """Start every test from a known vault + environment.

    Two separate leaks to close. The env vars matter because get_token() reads bare
    GITHUB_TOKEN, so a developer with one exported would have their real token pulled
    into the assertions. The vault matters because conftest redirects HOME ONCE for the
    session, so it is shared mutable state across tests: written first, the fallback test
    below read a leftover vault entry and failed on the previous test's value. Order
    dependence in an auth suite is not a thing to leave in.
    """
    for name in (
        "GITHUB_TOKEN",
        "GITHUB_API_KEY",
        "GITHUB_PAT",
        "BB_SECRET_GITHUB_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    from bigbang.core.security import delete_secret

    for key in ("GITHUB_TOKEN", "GITHUB_API_KEY", "GITHUB_PAT", "GITHUB"):
        delete_secret(key)
    db = ac._load_auth()
    if db.pop("github", None) is not None:
        ac._save_auth(db)


@pytest.fixture
def logged_in():
    ac.set_token(service="github", token=None, token_opt=PROBE_VALUE, use_stdin=False)
    return "github"


def _emitted(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


# --- storage round-trip -------------------------------------------------------------


def test_set_token_vaults_under_the_configured_key(logged_in, capsys):
    """github's config pins vault_key GITHUB_TOKEN; logout recomputes it independently."""
    assert ac.get_token("github") == PROBE_VALUE


def test_set_token_never_prints_the_token(capsys):
    ac.set_token(service="github", token=None, token_opt=PROBE_VALUE, use_stdin=False)
    assert PROBE_VALUE not in capsys.readouterr().out


# --- get-token ----------------------------------------------------------------------


def test_get_token_masks_by_default(logged_in, capsys):
    ac.get_token_cmd(service="github", reveal=False)
    payload = _emitted(capsys)
    assert payload["value"] is None
    assert payload["masked"] == PROBE_VALUE[:4] + "****"
    assert payload["found"] is True


def test_get_token_reveal_returns_the_value(logged_in, capsys):
    """Non-vacuity for the test above: --reveal must actually reveal, or masking is
    untested behaviour rather than a choice."""
    ac.get_token_cmd(service="github", reveal=True)
    assert _emitted(capsys)["value"] == PROBE_VALUE


def test_get_token_exits_nonzero_when_absent(capsys):
    import typer

    with pytest.raises(typer.Exit) as exc:
        ac.get_token_cmd(service="nosuchservice", reveal=False)
    assert exc.value.exit_code == 1
    assert _emitted(capsys)["found"] is False


# --- logout -------------------------------------------------------------------------


def test_logout_makes_the_token_unreadable(logged_in, capsys):
    """The property the word promises."""
    ac.logout(service="github", delete_vault=True)
    payload = _emitted(capsys)
    assert payload["vault_deleted"] is True
    assert payload.get("still_readable") is not True
    assert ac.get_token("github") is None


def test_logout_admits_when_an_env_var_still_provides_the_token(
    logged_in, monkeypatch, capsys
):
    """logout deletes one vault key; it cannot unset a var in the caller's shell.

    Before this, `auth logout github` with GITHUB_TOKEN exported printed
    vault_deleted: true and `auth get-token github` kept working -- two commands giving
    contradictory answers about the same credential.
    """
    monkeypatch.setenv("GITHUB_TOKEN", "still-here-in-the-environment")
    ac.logout(service="github", delete_vault=True)
    payload = _emitted(capsys)
    assert payload["still_readable"] is True
    assert payload["env_vars_set"] == ["GITHUB_TOKEN"]
    assert "GITHUB_TOKEN" in payload["note"]


def test_logout_keep_vault_leaves_the_token(logged_in, capsys):
    """--keep-vault is documented; assert it rather than trust it."""
    ac.logout(service="github", delete_vault=False)
    assert _emitted(capsys)["vault_deleted"] is False
    assert ac.get_token("github") == PROBE_VALUE


def test_logout_of_an_unknown_service_is_not_an_error(capsys):
    ac.logout(service="neverloggedin", delete_vault=True)
    payload = _emitted(capsys)
    assert payload["removed_from_auth_json"] is False
    assert payload["vault_deleted"] is False


# --- status / list ------------------------------------------------------------------


def test_status_reports_authenticated_after_set_token(logged_in, capsys):
    ac.status_cmd(service="github")
    payload = _emitted(capsys)
    assert payload["authenticated"] is True
    assert payload["method"] == "token"
    assert PROBE_VALUE not in json.dumps(payload)


def test_status_all_never_leaks_values(logged_in, capsys):
    ac.status_cmd(service=None)
    payload = _emitted(capsys)
    assert payload["authenticated_count"] >= 1
    assert PROBE_VALUE not in json.dumps(payload)


def test_list_reports_keys_only(logged_in, capsys):
    ac.list_auth()
    payload = _emitted(capsys)
    assert "github" in payload["authenticated_services"]
    assert PROBE_VALUE not in json.dumps(payload)


# --- login argument validation ------------------------------------------------------


def test_login_rejects_an_unknown_method(capsys):
    import typer

    with pytest.raises(typer.Exit) as exc:
        ac.login(
            service="github",
            method="telepathy",
            client_id=None,
            open_browser=False,
            scope=None,
            token=None,
        )
    assert exc.value.exit_code == 1
    assert "Unknown method" in _emitted(capsys)["error"]


def test_login_pat_with_token_vaults_without_prompting(capsys):
    """Documented as the agent path ("Never hangs waiting for a prompt")."""
    ac.login(
        service="github",
        method="pat",
        client_id=None,
        open_browser=False,
        scope=None,
        token=PROBE_VALUE,
    )
    payload = _emitted(capsys)
    assert payload["status"] == "authenticated"
    assert PROBE_VALUE not in json.dumps(payload)
    assert ac.get_token("github") == PROBE_VALUE


# --- get_token resolution -----------------------------------------------------------


def test_get_token_falls_back_to_a_bare_env_var(monkeypatch):
    """Documented fallback, and the reason logout cannot promise unreadability."""
    monkeypatch.setenv("GITHUB_TOKEN", "from-the-environment")
    assert ac.get_token("github") == "from-the-environment"


def test_get_token_prefers_the_vault_over_env(monkeypatch):
    set_secret("GITHUB_TOKEN", PROBE_VALUE)
    monkeypatch.setenv("GITHUB_TOKEN", "from-the-environment")
    assert ac.get_token("github") == PROBE_VALUE


def test_get_token_of_empty_service_is_none():
    assert ac.get_token("") is None
