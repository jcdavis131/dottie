# Agent OS review

## Findings
- 🔴 apps/scout-cli/bigbang/core/policy.py:74 — `_domain_matches` keeps "legacy substring semantics" (`domain in resource`), so the default-deny network allowlist is bypassable: with the out-of-the-box allowlist, `http://evil.com/localhost` and `http://127.0.0.1.evil.com/x` both pass every user and manifest check (verified live).
- 🔴 apps/scout-cli/bigbang/core/policy.py:137 — the secrets axis is default-ALLOW: `if allowed and resource not in allowed` means an empty/missing `capabilities.secrets.allow` grants every secret, contradicting the "default-deny on every axis" docstring, and tests/test_policy.py has zero secret-axis tests.
- 🟡 apps/dottie/dottie/resolve.py:54 — `_has_factory_code` probes `ava/rl/codeact_loop.py`, which the monorepo sibling does not have (real file is `dottie/rl/codeact_loop.py`; `ava/rl/` holds only a shim `__init__.py`), so dottie silently depends on the external checkout `/home/user/ava-agi-factory-v6-4` and breaks on any machine without it — and the shim's `from dottie.rl import *` would collide with the app's own `dottie` package if the marker were relaxed.
- 🟡 packages/ava-skills/skills/state_store.py:108 — `register_skill` does a non-transactional SELECT-then-UPDATE version bump while WAL explicitly invites multi-process sharing (scout CLI + engine), so concurrent writers can produce lost version bumps, and no caller path handles `sqlite3.DatabaseError` (a corrupt DB crashes scout raw; dottie's jspace_state.py:38 masks it as merely "unavailable").
- 🟡 apps/scout-cli/bigbang/plugins/ava/cli.py:615 — `_run_in_factory` calls `subprocess.run(..., capture_output=True)` with no timeout, so a hung factory job blocks `scout ava train/pilot` forever while buffering unbounded output in memory (dottie's own flywheel.py subprocess calls, by contrast, all have timeouts + rc checks + honest error excerpts).
- 🟢 apps/dottie/dottie/research/__main__.py:223 — the continuous runner is unbounded only by explicit `--max-actions 0` design, with capped 900s backoff and a 5-consecutive-error exit; flywheel ops are single-shot with timeouts, demand-queue phases iterate `range(N_PHASES)`, and the sandbox no-network/no-outside-write guardrails are structurally enforced (codeact_sandbox.py rebinds open/socket + rlimits), not prompt text.

## Risk
- Any forged/imported tool or coerced URL can exfiltrate to attacker hosts and read all secrets despite a "default-deny" policy the user believes is enforced — the two red findings together nullify the CLI's core security story.
- Dottie's engine/flywheel fail to start (or import the wrong `dottie` package) on any checkout without the out-of-repo factory clone, breaking CI and new-machine reproducibility.
- Concurrent scout+engine skill writes silently lose version history, undermining the audit trail the state store exists to provide.

## Recommendation
1. Fix policy.py now: drop the substring fallback in `_domain_matches` (exact host or dot-suffix only) and make the secrets axis deny on empty allowlist; add tests for both, including the two bypass URLs below.
2. Fix resolve.py's marker to accept `dottie/rl/codeact_loop.py` (or add a real `ava/rl/codeact_loop.py`), and rename/namespace one of the two `dottie` packages to kill the shim collision.
3. Wrap `register_skill` in a `BEGIN IMMEDIATE` transaction, catch `sqlite3.DatabaseError` with a quarantine-and-recreate path, add a timeout to `_run_in_factory`, and make research/logger.py:70 `write_status` atomic (tmp + os.replace) to match api.py:436's "atomically rewrite" claim.

## Evidence
```
$ python3 -c "from bigbang.core.policy import _domain_matches, check_permission; ..."
bypass1: True    # _domain_matches('localhost', 'http://evil.com/localhost')
bypass2: True    # _domain_matches('127.0.0.1', 'http://127.0.0.1.evil.com/x')
secrets_empty_allow: (True, 'ok')  # check_permission({'capabilities':{}}, 'secret', 'AWS_SECRET_KEY')
```
policy.py:74: `return bool(domain) and (domain in resource or resource.endswith(domain))`
policy.py:137: `if allowed and resource not in allowed:` — empty list never denies.
