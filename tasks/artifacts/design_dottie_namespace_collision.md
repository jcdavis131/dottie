# Design note: resolve the two-`dottie`-package namespace collision

Status: **proposal**. Diagnoses GOAT-audit finding #1 (the ~36 always-failing
apps/dottie engine/RL tests). No code changed by this note. The blast radius
touches `apps/ava-factory/dottie/__init__.py` (was frozen for the live trainer;
the run is DONE, so it is editable — but it is still the factory package root,
so this is an operator-greenlit change, not an autonomous one).

## The bug, precisely (verified 2026-07-23)

There are two regular Python packages both named `dottie`:
- `apps/dottie/dottie/` — the research/agent platform (api, engine, research,
  kg, policy, resolve, flywheel, status, tasks, climb, skill_tools).
- `apps/ava-factory/dottie/` — the factory (rl/, pipeline/, train, model,
  datagen, embeddings, optim, muon, decoding, … ~30 modules).

Both have `__init__.py`, so both are **regular packages**. Python resolves
`import dottie` to the *first* `dottie` on `sys.path` and that one package
shadows the other **entirely** — you can import `dottie.research` XOR
`dottie.rl`, never both in one interpreter. The ~36 failing tests import
factory code (`dottie.rl.codeact_loop` via the engine) while `dottie` is bound
to the research package → `ModuleNotFoundError: No module named 'dottie.rl'`.

**Proven this session:** the failure is NOT a missing file (the real
`codeact_loop.py` exists at `apps/ava-factory/dottie/rl/`), and it is NOT fixed
by `AVA_FACTORY_ROOT` (setting it still yields the same ModuleNotFoundError).
The earlier resolver-marker fix (3c84164) was necessary but insufficient. The
`ava.*→dottie.*` import shim and `resolve.ensure_factory_on_path()` (inserts
factory root at `sys.path[0]`) both assume ONE `dottie` — inserting the factory
root just flips which package wins, breaking `dottie.research` instead.

Origin: git `5cb75c4` "consolidate to monorepo — sync from
ava-agi-factory-v6-4" split one monolithic `dottie` into two app dirs, both
keeping the package name and an `__init__.py`.

## The enabling fact (why a clean fix exists)

The two packages' submodules are **disjoint** — the only name in common is
`__init__.py` (verified: `comm -12` of the two dir listings = `__init__.py`
only). So if `dottie` were a **namespace package** spanning both roots, every
submodule resolves unambiguously (`dottie.research` from apps/dottie,
`dottie.rl` from apps/ava-factory) with no collision.

## Options (ranked)

1. **PEP-420 namespace package + migrate the factory's lazy exports.** Remove
   both `dottie/__init__.py` so `dottie` becomes an implicit namespace package;
   with both roots on `sys.path`, submodules merge (disjoint, so no conflict).
   **BUT this is NOT the clean two-file removal the audit implied** — VERIFIED:
   `apps/ava-factory/dottie/__init__.py` (48 lines) is LOAD-BEARING. It
   implements PEP 562 lazy top-level exports (`__getattr__` over `_LAZY_EXPORTS`:
   `from dottie import DottieModel1B/DottieConfig/DottieTokenizer` + the `Ava*`
   aliases resolve lazily so the torch-free CPU fleet does not import torch at
   package load — an eager version "took the whole CPU fleet down at import time,
   cutover 2026-07-19"). A namespace package has no `__init__.py`, so it cannot
   carry that `__getattr__`. So Option 1 REQUIRES first migrating every
   `from dottie import DottieModel1B`-style call to `from dottie.model import
   DottieModel1B` (grep the monorepo for the 6 exported names + aliases), OR
   moving the lazy-export shim into a real submodule (e.g. `dottie.factory`)
   that callers import explicitly. `apps/dottie/dottie/__init__.py` (28 lines)
   is trivial (docstring + `__version__="0.1.0"`) — drop or move to `_version`.
   Gate: the ~36 tests green from a clean checkout with both roots discoverable,
   AND the CPU fleet still imports torch-free (the reason the lazy shim exists),
   AND no `dottie.__file__`/`__version__` consumer breaks. Blast radius = the
   whole monorepo's imports → operator greenlight + full cross-suite run.

2. **Single package location.** Move the factory `dottie/*` under
   `apps/dottie/dottie/` (or vice-versa) so there is one `dottie`. Cleanest
   conceptually, largest diff, and re-entangles the app boundary the monorepo
   split deliberately created. Not recommended.

3. **Rename the factory package** `dottie`→`avafactory` (or similar) and update
   the `ava.*` shim + all factory-internal imports. Removes the collision by
   removing the shared name. Large mechanical diff across the frozen factory;
   defeats the `ava→dottie` naming history. Not recommended.

4. **Do nothing / keep the two-checkout workaround.** The daemon runs with a
   `sys.path` where the factory `dottie` wins (its own runtime), and the ~36
   tests stay red. This is the status quo — honest but leaves a real
   self-containedness defect (a clean monorepo checkout cannot run its own
   engine tests).

## Recommendation

Option 1, operator-greenlit, on a branch, with the full cross-suite run
(apps/dottie + apps/ava-factory + packages) as the gate — the 36 reds turning
green and NO new reds elsewhere. First concrete step for whoever picks this up:
read both `__init__.py` files and confirm neither does load-bearing import-time
work; if clean, the fix is two file removals + a conftest/path tweak + the
gate.

## Verify the diagnosis (reproduce)
```
cd apps/dottie
$env:AVA_FACTORY_ROOT='C:\Users\jcdav\dottie\apps\ava-factory'
.venv\Scripts\python.exe -m pytest tests/test_verified_engine.py -q
# -> ModuleNotFoundError: No module named 'dottie.rl' (NOT a resolver error,
#    NOT fixed by the env var — the collision, as described above)
```
