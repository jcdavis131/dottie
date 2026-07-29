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
    """Exact-host or dot-suffix (subdomain) match ONLY.

    The old "legacy substring" branch (`domain in resource`) nullified the whole
    default-deny story: with `localhost` allowlisted, `http://evil.com/localhost`
    passed (substring in the PATH), and with `127.0.0.1` allowlisted,
    `http://127.0.0.1.evil.com/x` passed (substring in a crafted HOSTNAME). Both
    were reproduced live in the 2026-07-22 monorepo review. Matching is now done
    on the parsed HOST only. Manifest entries that store full URLs keep working
    because the allowlist entry itself is normalized through _host_of too."""
    if not domain:
        return False
    want = _host_of(domain)  # legacy full-URL entries match by their host
    if not want:
        return False
    host = _host_of(resource)
    return host == want or host.endswith("." + want)


def _norm_path(p: str, base: str | None = None) -> str:
    """Lexically normalize a path for allowlist comparison.

    `base` anchors RELATIVE declared entries somewhere other than the process
    CWD. It exists because two plugins write under a root discovered at runtime
    — tasks uses _repo_root() (walks up from __file__ for pyproject.toml) and
    reviewgraph uses --root — and a static allowlist cannot name a root it does
    not know. A "<repo>" token in the manifest could not fix this either: the
    root is a runtime value (tasks' own test monkeypatches _repo_root to a temp
    dir), so only the caller knows it. Absolute and ~-prefixed entries ignore
    `base` entirely.

    Deliberately does NOT touch the filesystem: a write target usually does not
    exist yet, so Path.resolve()/os.path.realpath would be both wrong (no file
    to stat) and a TOCTOU footgun. abspath() -> normpath() collapses ".." and
    "." LEXICALLY, which is exactly what defeats `.scout/../../etc/passwd`, and
    normcase() case-folds and unifies "/" with "\\" on Windows so the same
    resource spelled either way lands on the same string.

    This function stays lexical. The SYMLINK escape it used to disclaim is now
    caught by _resolves_within(), called from _path_matches() as a second,
    filesystem-aware gate — see the note there, which corrects the reason given
    for leaving it open."""
    # Suppressions below are deliberate: ruff's PTH rules want
    # Path.expanduser()/Path.resolve() here. expanduser is a pure swap, but
    # resolve() is NOT — it stats the tree and follows symlinks, which is
    # precisely what the docstring above rules out. pathlib has no lexical-only
    # normalizer, so os.path stays. (This comment must not begin with the word
    # n-o-q-a: ruff reads that as a blanket directive and then reports it
    # unused.)
    s = os.path.expanduser(str(p).strip())  # noqa: PTH111
    # The is_absolute() guard states the intent; it is not load-bearing, and no
    # test can kill removing it. `Path(base) / s` already discards `base`
    # whenever s is absolute, so `if base:` alone behaves identically for every
    # path shape that occurs here — a genuinely equivalent mutant rather than a
    # coverage gap. Kept because a security predicate should say what it means
    # instead of leaning on a stdlib side effect.
    if base and not Path(s).is_absolute():
        s = str(Path(base) / s)
    return os.path.normcase(os.path.abspath(s))  # noqa: PTH100


def _path_matches(declared: str, resource: str, base: str | None = None) -> bool:
    """Exact-file or directory-prefix match ONLY, on a separator boundary.

    The separator boundary is the whole point. A bare `startswith` makes
    `paths: [".scout"]` also allow `.scoutevil/x` — the same shape of bypass the
    2026-07-22 review reproduced against the substring domain matcher (see
    _domain_matches). Comparing against `root + os.sep` means a declared
    directory grants its subtree and nothing that merely shares its prefix.

    `base` is the anchor for relative declared entries, not the prefix being
    matched — see _norm_path."""
    if not declared:
        return False
    root = _norm_path(declared, base)
    # The RESOURCE is a concrete path the caller already resolved, so it anchors
    # to CWD when relative — never to `base`. Anchoring both sides would let a
    # relative resource match a relative declaration by coincidence.
    target = _norm_path(resource)
    if not (target == root or target.startswith(root.rstrip(os.sep) + os.sep)):
        return False
    return _resolves_within(root, target)


def _resolves_within(root: str, target: str) -> bool:
    """Second gate: the lexical match must survive symlink resolution.

    _norm_path() is deliberately lexical, and that leaves one hole it used to
    disclaim: a symlink (or, on Windows, a directory junction) INSIDE an allowed
    directory pointing outside it satisfies the string comparison while writing
    somewhere else entirely.

    **The stated reason for leaving that open was wrong, and it is worth naming
    because it blocked the fix.** The claim was that blocking it "needs realpath
    on an existing tree, which the not-yet-created-write case rules out".
    os.path.realpath is NOT strict — it resolves whatever prefix exists and
    appends the rest untouched. Measured on this box, with a junction
    allowed/escape -> outside and a target that does not exist:

        lexical  target:  ...\\allowed\\escape\\not_yet_created.txt   inside? True
        realpath target:  ...\\outside\\not_yet_created.txt           inside? False

    So the not-yet-created case never ruled it out. A non-existent path is
    simply returned normalized, which is exactly the old behaviour, so this
    check is a no-op wherever there is nothing to resolve.

    BOTH sides are resolved, which is what keeps legitimate setups working: if
    the allowed root is ITSELF a symlink (a symlinked /tmp on macOS, a redirected
    data dir), root and target move together and the write is still allowed. Only
    a target that leaves the root's REAL location is denied.

    Honest residual, not papered over: this is TOCTOU-checkable, not TOCTOU-proof
    — the link can be swapped between this check and the open(). Closing that
    needs the write to go through an fd opened with O_NOFOLLOW semantics, which
    is a change at every call site, not here. This raises the bar from "string
    prefix" to "must survive resolution at check time"; it does not claim more.
    """
    real_root = os.path.normcase(os.path.realpath(root))
    real_target = os.path.normcase(os.path.realpath(target))
    if real_target == real_root:
        return True
    return real_target.startswith(real_root.rstrip(os.sep) + os.sep)


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


def add_allowed_domain(host: str) -> tuple[bool, str]:
    """Persist a host into the user network allowlist (self-unblock, network axis).

    Returns (changed, message). Idempotent — re-adding an already-allowed host
    is a no-op success. This is how the LLM unblocks itself on a policy-denied
    reach: an explicit, auditable edit to the user's own allowlist file, never a
    silent fail-open or an in-memory override that evaporates next call.

    Only a bare host is accepted (parsed out of a URL if one is passed). Wildcard
    or empty entries are refused so the allowlist can't be widened to match-all.
    """
    host = _host_of(str(host).strip())
    if not host or host in ("*", "0.0.0.0") or "*" in host:
        return False, f"refusing to allowlist {host!r} — must be a concrete host"
    policy = load_user_policy()
    net = policy.get("network")
    if not isinstance(net, dict):
        net = {}
        policy["network"] = net
    domains = net.get("allowed_domains")
    if not isinstance(domains, list):
        domains = []
        net["allowed_domains"] = domains
    if host in domains:
        return False, f"{host} already allowed"
    domains.append(host)
    fp = user_policy_file()
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(
            "# scout-cli user policy — default-deny.\n"
            "# Add domains under network.allowed_domains to allow outbound calls.\n"
            + yaml.safe_dump(policy, sort_keys=False)
        )
    except OSError as e:
        return False, f"could not write {fp}: {e}"
    return True, f"{host} added to network allowlist ({fp})"


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


# Two filesystem-write actions, because "where may this plugin write" and "where
# did the operator just tell it to write" are different questions:
#
#   fs_write      — a path the PLUGIN chose (its sqlite store, ledger, cache).
#                   capabilities.filesystem.paths is enforced. This is the axis
#                   with security value: it stops a plugin that advertises a
#                   report from also dropping a file in ~/.ssh.
#   fs_write_arg  — a destination the OPERATOR named on the command line
#                   (--out/--db/--csv). Only the write flag is checked. Typing
#                   the path IS the authorization, and re-confirming it against
#                   a manifest is theatre: no allowlist can enumerate every
#                   directory an operator might legitimately choose.
#
# Collapsing these into one action was tried first and is what makes this gate
# unusable. Enforcing `paths` on operator-named destinations denied
# `statuspage render --out /var/www/status.html`, so the only way to ship a
# working plugin would be to declare `paths: ["/"]` — a gate that protects
# nothing while still reading as enforced. Two ungameable-by-accident actions
# beat one gate everybody routes around.
#
# The integrity of fs_write_arg rests on call sites being honest about
# provenance, exactly as the pre-existing "the plugin loader does not check
# fs_write for us" comments already admit. It is kept auditable by being
# greppable: tests/test_policy.py pins the exact set of fs_write_arg call sites,
# so adding one is a deliberate edit to a test rather than a quiet drift.
FS_WRITE_ACTIONS = ("fs_write", "fs_write_arg")

# Every axis this function knows how to gate. An action outside this set is a
# typo, and a typo used to FAIL OPEN: the branches below are all `if action ==`,
# so `enforce_or_raise(mf, "fs_wrile", path)` fell through to `return True, "ok"`
# and wrote wherever it liked while reading, at the call site, exactly like an
# enforced gate. Verified there are no dynamic action arguments anywhere in the
# tree — every caller passes a literal — so validating the name costs nothing
# and removes a silent bypass that adding "fs_write_arg" would only widen.
KNOWN_ACTIONS = ("network", "secret") + FS_WRITE_ACTIONS


def check_permission(
    manifest: dict, action: str, resource: str, base: str | None = None
) -> tuple[bool, str]:
    """Returns (allowed, reason). Default-deny: empty allowlists deny everything.

    Actions: "network", "fs_write", "fs_write_arg", "secret". Anything else is
    denied as a probable typo; see FS_WRITE_ACTIONS for why writes have two.

    `base` anchors relative entries in capabilities.filesystem.paths for the
    plugins that write under a runtime-discovered root — see _norm_path. It does
    not widen anything: the bound is still "resource inside a declared entry",
    and a plugin that wanted to escape could simply not call this gate, which is
    already true of 16 write-capable plugins today (counted with ast — a grep for
    "enforce_or_raise" says 14, because `quality` names it only in a comment and
    `tools` calls it only with "network")."""
    if action not in KNOWN_ACTIONS:
        return False, (
            f"unknown policy action {action!r} — fail closed; expected one of "
            f"{list(KNOWN_ACTIONS)}"
        )
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
    if action in FS_WRITE_ACTIONS:
        fs = caps.get("filesystem", {}) or {}
        if not fs.get("write", False):
            return (
                False,
                "filesystem write disabled — add manifest capabilities.filesystem.write=true",
            )
        # "fs_write_arg" stops at the write flag by design — see FS_WRITE_ACTIONS.
        if action == "fs_write":
            # The path allowlist was declared in 47 of 56 manifests and enforced
            # in NONE of them: `write: true` alone granted the entire
            # filesystem, so a manifest narrowing itself to [".scout"] held
            # exactly the authority of one asking for "/". DEFAULT_POLICY has
            # carried an empty "allowed_paths" key since the first commit — the
            # intent was always here, only the check was missing.
            paths = fs.get("paths") or []
            if isinstance(paths, str):
                # `paths: .scout` is valid YAML and a plausible authoring slip.
                # Iterating the str would test each CHARACTER and deny
                # everything — safe, but inexplicable to whoever hits it.
                paths = [paths]
            if not paths:
                # default-deny, same as network.domains and secrets.allow
                return False, (
                    f"filesystem write enabled but path allowlist is empty for "
                    f"{manifest.get('name', 'tool')} — default-deny; list files "
                    "or directories in manifest capabilities.filesystem.paths"
                )
            if not any(_path_matches(str(p), resource, base) for p in paths):
                suffix = f" (relative entries resolved against {base})" if base else ""
                return False, f"path {resource} not in allowlist {paths}{suffix}"
    if action == "secret":
        allowed = caps.get("secrets", {}).get("allow", [])
        # default-deny like every other axis: an EMPTY allowlist grants nothing.
        # (The old `if allowed and ...` guard silently allowed EVERY secret when
        # the list was empty — the opposite of this function's own docstring.)
        if not allowed:
            return False, (
                f"secrets allowlist is empty for {manifest.get('name', 'tool')} — "
                "default-deny; name each secret in manifest capabilities.secrets.allow"
            )
        if resource not in allowed:
            return False, f"secret {resource} not in allowlist {allowed}"
    return True, "ok"


def enforce_or_raise(manifest: dict, action: str, resource: str, base: str | None = None):
    ok, reason = check_permission(manifest, action, resource, base)
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
