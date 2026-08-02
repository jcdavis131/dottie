"""The release-asset download URL comes from the API response, so it must be gated.

`scout rtx releases sync --tag X` reads a release from api.github.com and then fetches
`asset["browser_download_url"]` — a URL taken out of the RESPONSE — with
follow_redirects=True, and writes the body to disk. That is "observed content decides the
next request", which is the shape the network allowlist exists to bound.

Smaller than forge's hole (be9890d), which took an arbitrary user `--url`: over TLS to
api.github.com the response is authentic unless GitHub itself is compromised. Same shape
though, and this one ends in a file write.

DELIBERATE ASYMMETRY, pinned here so it is not read as an oversight: the two other
httpx.get calls in that command target GITHUB_API, built from the hardcoded GITHUB_REPO.
They are fixed destinations, and gating them would make `scout rtx releases list` fail
until someone allowlists api.github.com — friction with no matching risk. Only the
response-derived URL is gated.
"""

from __future__ import annotations

from pathlib import Path

from bigbang.plugins.rtx import cli as rtx


def test_the_download_url_is_response_derived_not_a_constant():
    """Pins WHY this gate exists. If the code is ever changed to build the download URL
    from GITHUB_API instead, the risk disappears and this whole file can go."""
    src = Path(rtx.__file__).read_text(encoding="utf-8")
    assert 'asset["browser_download_url"]' in src, (
        "the download URL is no longer taken from the API response — re-evaluate whether "
        "this gate is still needed"
    )
    assert "check_user_url" in src, "the gate was removed"


def test_the_hardcoded_calls_are_still_hardcoded():
    """The asymmetry is only defensible while the other calls really are fixed.

    If GITHUB_API ever becomes user- or response-controlled, leaving those two ungated
    stops being a judgement and becomes a hole.
    """
    src = Path(rtx.__file__).read_text(encoding="utf-8")
    assert 'GITHUB_REPO = "jcdavis131/scout-rtx"' in src, (
        "GITHUB_REPO is no longer a constant; the ungated calls above it need re-checking"
    )
    assert "GITHUB_API = f\"https://api.github.com/repos/{GITHUB_REPO}\"" in src


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.text = "irrelevant"

    def json(self):
        return self._payload


def _release_with_asset(url):
    return {"assets": [{"name": "results.tsv", "browser_download_url": url}]}


def test_denied_asset_url_is_never_fetched(monkeypatch, capsys):
    """The property that matters: policy is consulted BEFORE the download happens.

    Drives the real `releases sync` path rather than asserting on a stub. The first
    httpx.get (the release lookup, hardcoded host) is allowed through; the second — the
    response-derived asset URL — must not be reached at all.
    """
    fetched = []

    def fake_get(url, *a, **kw):
        fetched.append(url)
        if "releases/tags" in url:
            return _Resp(_release_with_asset("https://evil.example/results.tsv"))
        raise AssertionError(f"asset was downloaded despite the gate: {url}")

    monkeypatch.setattr(rtx.httpx, "get", fake_get)
    monkeypatch.setattr(
        "bigbang.core.policy.check_user_url",
        lambda url: (False, "user network allowlist is empty (default-deny)"),
    )

    # Returns rather than raising — see the comment at the gate: a typer.Exit here would
    # be swallowed by the branch's blanket `except Exception` and re-emitted as
    # {"error": "1"}. The contract is "does not download", not "raises".
    rtx.releases_cmd(action="sync", tag="v0.0.0-test")

    assert len(fetched) == 1, f"expected only the release lookup, got {fetched}"
    out = capsys.readouterr().out
    assert "denied by network policy" in out, out
    assert "scout reach allow evil.example" in out, out


def test_an_allowed_asset_url_still_downloads(monkeypatch, tmp_path):
    """Non-vacuity: the gate must be able to PASS.

    Without this, a `releases sync` that always exited would satisfy the test above.
    """
    monkeypatch.setattr(rtx, "CUSTOM_ROOT", tmp_path)
    monkeypatch.setattr(rtx, "BB_OFFLOAD", tmp_path / "bb-offload")
    monkeypatch.setattr(rtx, "RESULTS_TSV", tmp_path / "results.tsv")

    def fake_get(url, *a, **kw):
        if "releases/tags" in url:
            return _Resp(_release_with_asset("https://ok.example/results.tsv"))
        return _Resp({}, status=200)

    monkeypatch.setattr(rtx.httpx, "get", fake_get)
    monkeypatch.setattr("bigbang.core.policy.check_user_url", lambda url: (True, "ok"))
    rtx.releases_cmd(action="sync", tag="v0.0.0-test")


# --- scout-rtx root resolution (added 2026-08-02) ------------------------------------
#
# _resolve_custom_root() resolved to ~/workspace/autoresearch-rtx-custom, which does not
# exist on this box, while <repo>/apps/scout-rtx does and was never a candidate. CUSTOM_ROOT
# and the BB_OFFLOAD derived from it therefore pointed at a missing directory. Same omission
# as ava/cli.py (0c89edd); the correct version already existed in
# apps/scout-rtx/bigbang-bridge/cli.py, which checks the containing checkout second.


def test_custom_root_resolves_to_an_existing_directory():
    """The defect: it returned a legacy path that was not there."""
    from bigbang.plugins.rtx import cli as rc

    assert rc._resolve_custom_root().exists(), rc._resolve_custom_root()


def test_custom_root_is_the_checkout_this_plugin_lives_in():
    """Pins the ORDER. 'Resolves to something that exists' would pass on a stray checkout."""
    from pathlib import Path

    from bigbang.plugins.rtx import cli as rc

    got = rc._resolve_custom_root()
    repo = Path(rc.__file__).resolve().parents[5]
    assert str(got).lower().startswith(str(repo).lower()), f"{got} outside {repo}"
    assert got.name == "scout-rtx", got


def test_bb_offload_derives_from_a_real_root():
    from bigbang.plugins.rtx import cli as rc

    assert rc.BB_OFFLOAD.exists(), rc.BB_OFFLOAD


def test_scout_rtx_root_env_override_wins(tmp_path, monkeypatch):
    """Non-vacuity: a resolver hardcoded to the repo path would pass the tests above."""
    from bigbang.plugins.rtx import cli as rc

    monkeypatch.setenv("SCOUT_RTX_ROOT", str(tmp_path))
    assert rc._resolve_custom_root() == tmp_path
