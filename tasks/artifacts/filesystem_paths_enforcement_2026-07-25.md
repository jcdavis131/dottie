# `capabilities.filesystem.paths` — enforcement, and what enforcing it revealed

Operator decision #3 was "implement the `paths` allowlist in
`bigbang/core/policy.py::check_permission`'s `fs_write` branch, mirroring the `secret`
branch — go." Mirroring the `secret` branch literally turned out to be wrong, for a
reason only measurement surfaced. This records what shipped, what it found, and what it
deliberately did **not** close.

## The hole, measured

`capabilities.filesystem.paths` was declared by **47 of 56 manifests and enforced by
none of them**. `write: true` alone granted the entire filesystem, so a manifest
narrowing itself to `[".scout"]` held exactly the authority of one asking for `/`.
`DEFAULT_POLICY` has carried an empty `"allowed_paths"` key since the first commit — the
intent was always there, only the check was missing.

Two existing tests encoded the hole as the contract:

- `test_fs_write_allowed_when_declared` asserted `write:true` alone allowed `/tmp/x`.
- `TestFsWriteEnforcementWired` asserted `check_permission(mf, "fs_write", "/anywhere")`
  was **allowed** for tasks/rft/graphify — literally naming the resource `/anywhere`
  and passing.

Both now assert the opposite.

## Why one action was not enough

Strict enforcement on every gated write broke 7 tests immediately, all of the shape
`--out <path the operator typed>`. A subagent traced all 44 call sites, and the split is
lopsided: **ARG=42, AMB=2**. Every store helper (`_open_store`/`_open_new`/`_open_ledger`
/`_open_registry`/`_open_existing`/`_open_history`/`_ledger`) funnels through
`_db_path(db) -> Path(db or $SCOUT_*_DB or DB_REL)`, and in every case some caller
passes a `--db`. `.scout/x.db` is only ever the **default**.

So enforcing `paths` at those sites has exactly two possible outcomes, both bad:
deny every legitimate redirect, or push authors to declare `paths: ["/"]` — a gate that
protects nothing while still reading as enforced. Same failure mode as a permanently-red
required CI check: everyone learns to route around it.

The resolution is two actions, `FS_WRITE_ACTIONS`:

| action | provenance | `paths` enforced? |
|---|---|---|
| `fs_write` | the **plugin** chose the path (store, ledger, cache) | **yes** |
| `fs_write_arg` | the **operator** named it (`--out`/`--db`/`--csv`) | no — typing it is the authorization |

42 call sites moved to `fs_write_arg`. An independent regex found exactly 42 non-excluded
sites, matching the subagent's ARG count from a different method — two measurements
agreeing.

Integrity of `fs_write_arg` rests on call sites being honest about provenance, exactly as
the pre-existing "the plugin loader does not check fs_write for us" comments already
admit. It is kept auditable by being greppable, and `paths` still constrains the
defaults via a test (below).

## Three defects found by turning the check on

1. **`reviewgraph` declared the literal `"<root>/.scout/"`** — the description's prose
   placeholder (legitimate there) leaked verbatim into the allowlist. Nothing ever
   substituted it. Unenforced it was inert config; enforced it denies every write.
2. **`tasks` declared `"~/workspace/bigbang-cli/docs/llm-wiki/"`** while `export` writes
   `_repo_root()/docs/llm-wiki/`, where `_repo_root()` walks up from `__file__` for
   `pyproject.toml`. The declared path was baked in from a machine where the checkout sat
   at `~/workspace/bigbang-cli`; here the package resolves to `dottie/apps/scout-cli`, so
   it matched nothing.
3. **An unknown action FAILED OPEN.** Every branch is `if action == ...`, so
   `enforce_or_raise(mf, "fs_wrile", path)` fell through to `return True, "ok"` — writing
   wherever it liked while reading, at the call site, exactly like an enforced gate.
   Verified no dynamic action arguments exist anywhere (every caller passes a literal),
   so `KNOWN_ACTIONS` now fails closed. Adding `fs_write_arg` would only have widened
   this.

## The structural gap — found, then closed with `base`

Defects 1 and 2 share a cause: **a static allowlist cannot express "the root this
package was installed under."** reviewgraph tried to spell it `<root>`; tasks hardcoded
one machine's answer. `.scout` works only because it is CWD-relative and `abspath`
resolves it against the process CWD.

The first attempted fix — declare `docs/llm-wiki` relative — passed in isolation and
**failed the full board**: `test_export_writes_to_repo_docs` monkeypatches `_repo_root`
to a temp dir precisely so the test never touches real `docs/`, so CWD and the resolved
root diverge and the write was denied (`click.exceptions.Exit`).

That failure also rules out the obvious design. A `<repo>` token substituted from the
manifest's own location **cannot work**, because the root is a **runtime** value — the
test relocates it, and in production it depends on where the package is installed. Only
the caller knows it.

So the caller supplies it. `check_permission(..., base=...)` anchors **relative** declared
entries to a caller-provided root; absolute and `~` entries ignore `base` entirely. The
tasks call site becomes:

```python
root = _repo_root()
out_path = root / "docs" / "llm-wiki" / f"tasks-{tasklist}.json"
enforce_or_raise(manifest, "fs_write", str(out_path), base=str(root))
```

`base` does not widen anything — the bound is still "resource inside a declared entry" —
and a plugin wanting to escape could simply not call the gate, which is already true of
the 14 below. When reviewgraph's gate is wired it should pass `base=--root`.

## The larger hole this does NOT close

**14 of 47 write-capable plugins never call the gate at all** — the plugin loader does
not enforce it, and these call sites do not either:

```
auth  ava  brain  dev_loop  herd  lab  mcp  reviewgraph  rtx  secrets  skill  system
tennis  write
```

That list is the inverse of reassuring: `auth` writes `auth.json`/`secrets.json`,
`secrets` writes `~/.local/share/bigbang/`, `brain` writes `~/MEMORY.md` and `~/memory/`,
`skill` writes `~/.claude/skills/`. These are precisely the plugins where a path bound
matters most, and for them `paths` remains documentation. **Enforcing `check_permission`
cannot fix this**; the gate has to be invoked. That is the highest-value follow-up, and
it is larger than this change.

## What the matcher guarantees

`_path_matches` is exact-file or directory-subtree, on a **separator boundary**. A bare
`startswith` would let `paths: [".scout"]` also grant `.scoutevil/` — the same bypass
shape the 2026-07-22 review reproduced against the substring domain matcher.
`_norm_path` normalizes lexically (`expanduser` → `abspath` → `normcase`) and never
touches the filesystem, because a write target usually does not exist yet and
`resolve()`/`realpath` would be both wrong and a TOCTOU footgun. `..` is collapsed
lexically, which is what defeats `.scout/../../etc/passwd`.

**Stated, not papered over:** a **symlink** inside an allowed directory pointing outside
it still escapes. Blocking that needs `realpath` on an existing tree, which the
not-yet-created-write case rules out.

## Verification

**71 tests in `tests/test_policy.py`** (was 22). Mutation tested: **12 of 13 killed**.

The one survivor is reported as a survivor rather than papered over. Mutating
`if base and not Path(s).is_absolute():` to `if base:` changes nothing, because
`Path(base) / s` already discards `base` when `s` is absolute — an **equivalent mutant**,
not a coverage gap. The guard stays because a security predicate should say what it means
rather than lean on a stdlib side effect. Writing a test to manufacture a 13/13 would
have been dishonest.

The first mutation run reported 6/6 killed and was **entirely invalid** — every "kill"
was `ModuleNotFoundError: No module named 'typer'`, returncode 2, a collection error
rather than a test failure, because bare `python` in `subprocess.run` resolves a
different interpreter than bash's `python`. Re-run with `sys.executable` and a
green-baseline assertion: 8/9 killed and **`normcase` SURVIVED**, an untested line the
broken run had falsely certified. Now covered by
`test_case_folding_follows_the_platform`.

A fleet invariant also had to be rebuilt: the first version keyed on module-level
`*_REL` constants and reached **2 of 47 plugins** while its `checked > 0` guard passed
happily (`DB_REL` lives in `bigbang/core/<plugin>.py` and is referenced
module-qualified, so `dir(cli)` never saw it). It now calls each plugin's real resolver
with `None` — "the operator did not redirect me" — and asserts a measured floor of 20;
**23 resolvers exercised, 0 defaults outside their own allowlist.**

## Side note for operator decision #5 (reviewgraph) — measured, and it reframes the task

`apps/scout-cli/.scout/reviewgraph.db` **already exists on this box**: 1,073,152 bytes,
**81 files · 690 nodes · 1,773 edges · 4,247 refs · 0 warnings**. `tests/test_reviewgraph.py`
is in the tree. `.scout/` is gitignored, so this copy is local and untracked.

Read from `meta` rather than assumed:

| key | value |
|---|---|
| `schema_version` | 1 |
| `root` | `C:\Users\jcdav\dottie\apps\scout-cli` |
| `last_index_at` | `2026-07-19T16:27:25Z` |

So it indexes **only `apps/scout-cli`** — not the monorepo — and is **six days stale**:
64 `bigbang` files when that tree now ships 58 plugins. By top-level dir: bigbang 64,
tests 13, scripts 2, arxiviq 2.

**This reframes #5.** The db is **regenerable**, so recovering it from `stash@{0}` is
probably not the valuable part — rebuilding is a single index run, and any rebuild will be
strictly better than a 6-day-old 81-file snapshot. What is worth preserving is whatever in
that stash is *not* regenerable. The real work is the integration the operator asked for:
point it at the monorepo root rather than `apps/scout-cli`, and feed blast-radius into the
research loop.

**Related finding from this change:** `reviewgraph` is one of the 14 plugins that **never
calls the fs_write gate**, so its `paths` entry was pure documentation — which is exactly
how the `"<root>/.scout/"` placeholder survived unnoticed. When wiring its gate, pass
`base=<--root>` (see the `base` section above).
