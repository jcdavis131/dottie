# GOAT Audit — Dottie Monorepo (Carmack/Bellard rubric)

READ-ONLY static audit. Date 2026-07-23. Scope: `apps/dottie`, `apps/ava-factory`, `apps/bluehenre`, `apps/scout-cli`, `packages/*`. Excluded from analysis: `.claude/worktrees/**`, `.venv`, `node_modules`, `*.egg-info`, `__pycache__`.

Rubric dimensions (1-10, 10 = exemplary):
1. Dependency economy (Bellard) · 2. Dead code & speculative abstraction (Carmack) · 3. Self-containedness · 4. Test honesty · 5. Hot-path clarity · 6. Honest notes.

---

## TL;DR — where the quality actually lives

The **best code in the monorepo is the FROZEN trainer** (`apps/ava-factory/dottie/train.py`, `dottie/pipeline/pack.py`) and the **research validator** (`apps/dottie/dottie/research/validate.py`). These are the true quality bar: linear control flow, zero speculative abstraction, and *every* non-obvious line is anchored to a dated, measured incident. The task hypothesized scout-cli's `openswap` family as the bar — it is an excellent, correctly-justified abstraction, but it sits a notch below the frozen trainer's measured-incident rigor.

The **worst structural problem is duplication + lineage drift** in `apps/ava-factory` (two parallel Python stacks, `ava/**` and `dottie/**`), and the single highest-value concrete defect is that this drift **breaks a clean-checkout of `apps/dottie`**: Dottie's resolver hunts for the CodeAct substrate at the pre-rename path `ava/rl/codeact_loop.py`, but the monorepo now ships it at `dottie/rl/codeact_loop.py`.

---

## Hot-path clarity (rubric #5) — audited first-hand

### `apps/ava-factory/dottie/train.py` (704 LOC) — FROZEN, bind-mounted. Score 10/10.
One linear `main()` training loop. Not a single indirection layer. Every "optimization" carries a measured justification:
- `train.py:88-95` `gpu_stats()` — the nvidia-smi readout exists because battery throttling capped the GPU at ~17-22W and collapsed throughput ~6x, indistinguishable from a hang for 3 days.
- `train.py:165-191` `_rotate_step_ckpts` — keep-last-N, armed only above a deploy floor, born from a **211 GB dead-checkpoint disk incident (2026-07-22)**.
- `train.py:201-219` `load_ckpt` maps to CPU not CUDA to avoid a measured **12.5 GB resume peak on a 12.3 GB card**.
- `train.py:597-600` `del out, parts, mj` to free ~0.5 GB logits on a GPU at 97% VRAM; `train.py:547-552` `empty_cache()` at the p3→p4 seq-doubling boundary (exact CUDA error cited).
- `train.py:309-319` SIGTERM→SystemExit so the sampler's `with`-block releases its shard claim on `docker stop`.
Honest notes are impeccable (`train.py:2-4`: "Replaces train_1b_deepspeed.py, which ran 5 steps of `loss=torch.tensor(1.0)` and wrote text files as checkpoints").

### `apps/ava-factory/dottie/pipeline/pack.py` (183 LOC). Score 10/10.
Tokenise+pack to uint16 shards. Atomic writes (`pack.py:163-173`: fsync both tmp files, `os.replace` bin-then-idx so a crash never leaves a torn shard). `vocab<=65535` is **asserted, not assumed** (`pack.py:82-85`). The `concept=None` → `UNTAGGED(-1)` handling (`pack.py:112-121`) is documented with the exact failure it prevents ("teach the reportability loss the answer is almost always <|endofdoc|>").

### `apps/dottie/dottie/research/validate.py` (1109 LOC). Score 9/10.
The 6-stage fail-fast validator that keeps unsound LLM PyTorch off the GPU. Linear `validate()` (`validate.py:811-854`), each gate grounded in a post-mortem: the degeneracy gate (`:725-748`) and zero-param gate (`:789-799`) both cite the MLBR false-SOTA and the measured **"11 of 20 passing candidates had zero learnable params — 55%, ZERO real wins"** (`:781-783`). Comments are painfully honest about the loop's own failures. Minor: the ~250-LOC `OBLIGATIONS` proof-ledger layer (`:303-439`, added 2026-07-23) is the one place complexity is *growing* faster than the core needs — well-tested and documented, but the closest thing here to gold-plating. Import order nit at `:38-46` (`inspect` after `shutil`).

**Verdict:** the frozen hot paths are the north star. Nothing else in the repo matches their measurement-per-line density.

---

## OPENSWAP verdict (scout-cli's claimed quality bar)

`apps/scout-cli/bigbang/core/openswap.py` (167 LOC) is a **genuinely earned abstraction**, not speculative. It defines a 3-invariant contract (local-capability probe → tiered native/fallback/unavailable resolution → normalized diagnostic schema) consumed by **~10 real adapters** (prose, seo, links, uptime, certmon, glitch, heartbeat, leaks, runtrack, smoke — each a `core/*.py` + `plugins/*/cli.py` pair, 250-814 LOC each). Carmack's test for an abstraction — more than one real implementation — passes decisively (10 impls). Pure logic + local subprocess probing only, no network/writes (`openswap.py:20-23`). The privacy guarantee is architectural and falsifiable ("NEVER a network/SaaS fallback tier", `:12-16`); tiers never silently no-op; a failing version probe cannot demote a real install (`:109-114`). **It deserves its reputation and is a valid bar for the CLI/plugin layer** — but the frozen trainer sets a higher bar (measured-incident justification) that openswap, not being a hot path, doesn't need to meet.

*(scout-cli detailed scorecard below is corroborated against this first-hand read.)*

---

## Single worst offense (monorepo)

**A stale physical-file marker in `apps/dottie` breaks a clean checkout, even though the underlying import already works.** `apps/ava-factory` ships two lineages (`ava/**`, `dottie/**`), but `ava/**` is deliberately a **backward-compat shim**: `ava/__init__.py:20-43` installs a meta-path finder aliasing every `ava.*` import to the live `dottie.*` module object, and `ava/rl/__init__.py:3-7` rebinds `sys.modules["ava.rl"]` to `dottie.rl`. So `engine.py:135` `from ava.rl.codeact_loop import run_code_act` **resolves at runtime** once `apps/ava-factory` is on `sys.path`. The bug is that `resolve.py:53-55` `_has_factory_code` gates on the **physical file** `<root>/ava/rl/codeact_loop.py`, which the shim intentionally never materializes (the real file is `apps/ava-factory/dottie/rl/codeact_loop.py`). So from a fresh checkout with `AVA_FACTORY_ROOT` unset, `factory_code_root()` reports the in-repo factory *absent*, skips the POSIX default `/home/user/ava-agi-factory-v6-4` (dead on Windows), and raises `DottieResolutionError` — the documented cause of the ~36-40 red engine/RL tests. Today it only works because the research daemon sets `AVA_FACTORY_ROOT` (gitignored `research_env.local.ps1:31`) to an **external legacy checkout** that still carries a physical `ava/rl/codeact_loop.py`. Fix is one line: point the marker at `dottie/rl/codeact_loop.py` (or import-probe instead of file-probe). Lane-free (`apps/dottie`). (Rubric #3.)

---

## Monorepo-level notes (self-containedness)

- **Root is a `uv` workspace** (`pyproject.toml:6-13`) with members ava-skills, ava-open-harness, personal-graphify, scout-cli; **`apps/ava-factory` and `apps/scout-rtx` excluded by design**. `apps/dottie` is **neither a member nor excluded** — it installs from its own `.venv`, out of the locked workspace (has `uv.lock` at root, 736 KB, only covers members).
- **`make test`** (`Makefile:7-10`) runs ava-skills, ava-open-harness, scout-cli — **skips apps/dottie and apps/ava-factory**, so the codeact test breakage above is invisible to the default gate.
- **Ruff config is copy-pasted and drifting** across 3 files: root `pyproject.toml:18-33`, `apps/dottie/pyproject.toml:39-54`, `apps/scout-cli/pyproject.toml:55-71` are near-identical (same `known-first-party = ["dottie","bigbang","skills","harness","personal_graphify"]`) but the `ignore` lists have diverged (dottie/scout add B008, RUF003, W505, RUF005; root does not).
- **Junk artifact:** `apps/ava-factory/C:/Program Files/` — a literal `C:` path-bug directory (empty) committed into the tree from a mis-formed mkdir.

---

## Per-app scorecards

Scores: [1] dep-economy · [2] dead-code · [3] self-contained · [4] test-honesty · [5] hot-path · [6] honest-notes.

### apps/dottie — [1] 9 · [2] 6 · [3] 4 · [4] 8 · [5] 9 · [6] 9
- **[1] 9** — every declared dep used; `torch`/`numpy` genuinely lazy+guarded (policy.py:305 `except ImportError`, validate.py:638 `_find_torch`); no top-level torch in `dottie/`. The pyproject's "torch deliberately optional" claim is true.
- **[2] 6** — `dottie/kg/**` is a fully orphaned subsystem: **1308 LOC, zero importers** outside itself (no `dottie.kg` refs in app/scripts), yet ships a 379-LOC test suite. `FactoryPolicy` (policy.py:438-543, ~106 LOC) unreachable — user backends are `Literal["ollama","ava","echo"]` (api.py:193/215/247).
- **[3] 4** — the worst-offense resolver defect (resolve.py:55); ~36-40 engine/RL tests only pass with an external factory checkout via gitignored `AVA_FACTORY_ROOT`. Not a member of the root uv workspace.
- **[4] 8** — 270 collected, 0 collection errors; 0 permanent skips/xfail (3 honest `skipif` on torch/factory); 0 network (unroutable-endpoint `127.0.0.1:9`, conftest.py:33); drives the real CodeAct sandbox via echo. Fragility: the engine-path tests need the external factory env.
- **[5] 9** — validate.py linear fail-fast, every gate measurement-cited (see hot-path section).
- **[6] 9** — zero bare TODO/FIXME/HACK; "TODO" hits are dated `TODOS §5.3.R##` design-log citations. One stale docstring: validate.py:815 says "Run L1→L4" but the function runs L1→L6.
- **Worst offense:** resolve.py:55 stale physical-file marker (see above).

### apps/scout-cli — [1] 4 · [2] 7 · [3] 5 · [4] 9 · [5] 8 · [6] 7
- **[1] 4** — **4 of 9 core deps never imported**: `pydantic`, `pydantic-settings`, `python-dotenv`, `click` (pyproject.toml:13,14,17,18); `click` fully redundant with bundled `typer[all]`. The `all` extra's `gspread`/`supabase`/`onnxruntime`/`cryptography` also never imported (only `keyring` is, guarded); `graphify=[]` is an empty named extra.
- **[2] 7** — `bigbang/core/discovery.py` (27 LOC) dead (no importers). openswap base is **justified, not speculative** — `probe_binary`/`capability_report` called by all 10 adapters' `detect()`.
- **[3] 5** — no lockfile (setuptools, `>=` floors); older plugins hardcode `~/workspace/...` (graphify/runner.py:52, brain/cli.py:54/143); registry.py:9 does a `mkdir` at import time. openswap adapters themselves use clean relative `.scout/`.
- **[4] 9** — 371 collected, **0 skipped, 0 network** (detection monkeypatches `openswap.shutil.which`); openswap family = 188 behavior tests, all 3 tiers covered; no tautological tests.
- **[5] 8** — cli.py linear (UTF-8 reconfigure → `discover_plugins` → callback); openswap dispatch flat. Minor: plugin_loader.py:39-52 swallows import failures.
- **[6] 7** — near-zero stale debt; **lying comment** plugin_loader.py:48 `# fail silent but log` (no logging exists); ruff `known-first-party` (pyproject.toml:70) leaks sibling-app names; OPENSWAP.md:6 "zero network calls" header contradicted by adapters with `network.enabled: true`.
- **Worst offense:** a third of the runtime dep surface (`pydantic`, `pydantic-settings`, `python-dotenv`, `click`) installed on every user, imported by nothing.

### apps/bluehenre — [1] 9 · [2] 8 · [3] 4 · [4] 7 · [5] 8 · [6] 9
- **[1] 9** — truly zero runtime deps: every import is Node stdlib (`server.mjs:8-13`); `fetch`/`AbortSignal` are globals.
- **[2] 8** — all exports used; main smell is **duplication**: `npcChat` in `server.mjs:51-76` re-implemented in `api/npc-chat.mjs:4-32` (~30 LOC, two provenance paths to keep in sync).
- **[3] 4** — **no `package.json`/lockfile anywhere**; `node>=18` only in a comment (server.mjs:2); no `engines`/`type`/`test` script; can't `npm ci`. Env vars all defaulted/documented.
- **[4] 7** — one real suite `public/js/twin.contract.test.mjs` (~90 behavior checks incl. honesty branches like "Wall 0.00s → 0 not null"); zero coverage of request handlers / `api/*.mjs` / frontend (SPEC admits it).
- **[5] 8** — `createServer` handler (server.mjs:78-193) linear if/else route table; path-traversal confinement correct+commented (server.mjs:176-181).
- **[6] 9** — exemplary provenance doctrine enforced in code (`source:"local"` gates every number); no lying comments/stale TODOs.
- **Worst offense:** no manifest/lockfile — deps (even "zero"), Node version, and build/test entrypoints all undeclared.

### packages/ava-open-harness — [1] 6 · [2] 6 · [3] 6 · [4] 9 · [5] 8 · [6] 9
- **[1] 6** — `transformers`+`safetensors` (torch extra, pyproject:19) never imported; `numpy` declared core but only torch-path-used; **`pyyaml` used (runner.py:42) but undeclared anywhere**.
- **[2] 6** — 3 unused utilities in `common.py`: `greedy_decode` (301-328), `logprob_of` (330-355), `cosine_sim` (357-367) ≈ **65 deletable LOC** (real compute delegated to the factory).
- **[3] 6** — clean `pip install -e .[dev] && pytest` **fails** because `TestYamlTasks` needs the undeclared `pyyaml`. One honest overridable absolute default (`common.py:19`).
- **[4] 9** — best of the set: genuine anti-mock guard (`test_no_mock.py`: seed-variation, report-grep for forbidden literals), AUC tie-handling pinned (`auc_trapezoid([1,1,0,0],[.5,.5,.5,.5])==0.5`).
- **[5] 8** — `run_harness` (runner.py:108-252) linear; honest-failure branch cleanly separated.
- **[6] 9** — dense accurate rationale; `real_unimplemented` never fabricates.
- **Worst offense:** `pyyaml` is a hidden hard dependency (imported + test-required) absent from the manifest — fresh-checkout tests fail on an unnamed dep.

### packages/ava-skills — [1] 5 · [2] 8 · [3] 7 · [4] 8 · [5] 7 · [6] 9
- **[1] 5** — **`numpy>=1.24` declared core (pyproject:9) but imported nowhere** (0 hits); `pyyaml` declared core but only used behind a `try/except` with a hand-rolled fallback (loader.py:33-41).
- **[2] 8** — all 10 skills live and discovered by `SkillLoader.scan`; loader methods all exercised; `wrrf_rerank` even documents removing a dead signal.
- **[3] 7** — state DB defaults outside repo (`~/.dottie-claw/`, DOTTIE_STATE_DB override); unused numpy inflates every install.
- **[4] 8** — 80 collected, honesty invariants (unevaluated tasks keep `None` not 0.0); **coverage gap: 4 of 10 skills have no dedicated test** (family-brain-wiki, jspace-context-engine, jspace-inspector, openwiki-sync).
- **[5] 7** — `run_with_graph` (loader.py:296-331) readable, pins safety-scanner to position 0 with a clear comment.
- **[6] 9** — tri-state NULL comments honest; "real mode not implemented" errors truthful.
- **Worst offense:** `numpy` core dep never imported — pure unused install weight.

### packages/personal-graphify — [1] 8 · [2] 7 · [3] 8 · [4] 8 · [5] 7 · [6] 8
- **[1] 8** — cleanest deps: core `networkx`+`python-frontmatter` both hard-used; everything heavy (`ollama`, `fastapi`, `tree-sitter*`, `numpy`) `try/except`-guarded and mapped to opt-in extras.
- **[2] 7** — all 11 `src` modules wired to the CLI; minor: `subgraph_for_query` imported unused (cli.py:144); duplicated in-function `analyze` imports (query.py:580,677).
- **[3] 8** — setuptools + `src` layout, extras well-defined, no magic absolute paths.
- **[4] 8** — 68 behavior tests (detect allowlist, public-sanitize, MCP stdio + path containment, query-cost, incremental cache); `importorskip("numpy")` honest optional gate.
- **[5] 7** — `cmd_build` linear; deduction for **bare `except:` swallows** at cli.py:225 and cli.py:273.
- **[6] 8** — provenance banners consistent; no stale TODOs.
- **Worst offense:** bare `except:` clauses (cli.py:225, 273) hiding real failures behind silent no-ops.

### apps/ava-factory — [1] 3 · [2] 3 · [3] 4 · [4] 8 · [5] 9*/4 · [6] 6
*Structural fact:* `ava/**` is **not** a divergent duplicate — it's a **236-LOC / 25-file backward-compat shim** (meta-path finder, see worst-offense section). The real stack is `dottie/**` = **32,970 LOC / 115 files**. Twist: `dottie/**` reaches up to **bare repo-root modules** (`dottie/model.py:12 from model_1b import ...`, `dottie/jlosses.py:24 from multi_jspace_module import ...`, `dottie/rl/codeact_eg_gate.py:27 from efficiency_gain import ...`), so `model_1b.py`, `multi_jspace_module.py`, `efficiency_gain.py`, `streaming_data.py` are **live**, not orphans.
- **[1] 3** — root `requirements.txt` declares ~30 deps; **≥10 have zero import lines**: `deepspeed, accelerate, wandb, scikit-learn, dolma, nemo-curator, tiktoken, webdataset, einops, psutil` (`scikit-learn` is *actively avoided* — evals/jspace_tests.py:30 "ROC AUC without sklearn"). `dolma/nemo-curator/safetensors/einops/websockets` carry **no version pin**. Mitigant: the real install path `docker/requirements.{cpu,gpu}.txt` is lean and fully pinned with load-bearing comments.
- **[2] 3** — `train_1b_deepspeed.py` (957 LOC, superseded mock trainer, see worst offense); ~**1,489 LOC** of truly-orphan root scripts (prefect_flows.py 443, data_builder_agent.py 451, trainer_agent.py 358, j_space_eval*.py 121, …) + **1,040 LOC** in `docs/blueprint/` that duplicates 7 of them; 8 dead per-file `ava/*.py` stubs shadowed by the finder.
- **[3] 4** — no `pyproject.toml`; `dottie/` resolves bare root modules only with app-root on `sys.path`. **~58 env vars via getenv, only 3 in `.env.example`** (several are secrets/keys). Junk dir `C:/Program Files/Git/ckpt/chat`. Positive: no hardcoded absolute paths in any `.py` (grep clean).
- **[4] 8** — 556 collected, 0 collection errors, **0 network tests**; real behavior tests (test_model.py causality, test_train_smoke.py WSD-monotonicity) alongside some parity/plumbing; 20 files with documented image-split skips.
- **[5] 9\*/4** — the **live frozen hot loop `dottie/train.py` + `dottie/pipeline/pack.py` is exemplary (10)** and is what rubric #5 names (audited first-hand above). The **legacy non-frozen `train_1b_deepspeed.py` is the mess (4)**: a real loss path AND a mock path gated by arg-branching, hard to tell which runs. Since it's superseded, it belongs in dead-code, not the hot path.
- **[6] 6** — dragged down by `train_1b_deepspeed.py`'s grandiose docstring over a mock body and `os.system("... --mode mock")` (:907). But strong positives: only 9 TODOs / 0 FIXME/HACK/XXX in core; `tests/conftest.py:29-36` honestly documents a measured silent-drop bug; `ava/__init__.py` docstring explains the double-module bug it fixes.
- **Worst offense:** `train_1b_deepspeed.py:915-929` — a 957-LOC "1B DeepSpeed trainer" with an elaborate WSD/YaRN/multi-J-space docstring whose observed path is a 5-step mock loop (`loss = torch.tensor(1.0, requires_grad=True); loss.backward(); optimizer.step()`) that never imports the `deepspeed` it's named after. (It's already honestly disowned by `dottie/train.py:3` — so **delete it**, don't trust it.)

---

## Portfolio ranking — top 10 fixes by (risk × inverse-effort)

Lane key: **FROZEN** = `apps/ava-factory/dottie/**` and `apps/ava-factory/configs/**` (off-limits for edits). Everything below is **lane-free**. Each fix is independently verifiable via its gate.

| # | Fix | App | Lane | ~LOC | Why it ranks (risk × inverse-effort) | Gate |
|---|-----|-----|------|------|--------------------------------------|------|
| 1 | Point the factory marker at the real file: `resolve.py:55` `ava/rl/codeact_loop.py` → `dottie/rl/codeact_loop.py` (or import-probe) | dottie | free | 1 | Unblocks a **clean checkout** + ~36-40 engine/RL tests that currently only pass via an external legacy checkout. Highest impact, 1 line. | `AVA_FACTORY_ROOT= python -c "from dottie import resolve; print(resolve._has_factory_code(resolve.dottie_root()/'apps'/'ava-factory'))"` → must print `True` |
| 2 | Declare `pyyaml>=6` (used runner.py:42, test-required); drop never-imported `transformers`/`safetensors` | ava-open-harness | free | 2 | Fresh-checkout **test suite fails today** on an undeclared hard dep. Tiny. | `pip install -e .[dev] && pytest tests/test_runner.py::TestYamlTasks -q` |
| 3 | Remove 4 unused **core** deps: `pydantic`, `pydantic-settings`, `python-dotenv`, `click` (`click` redundant with `typer`) | scout-cli | free | 4 | A third of the runtime dep surface installed for nothing. | `grep -rnE 'pydantic|dotenv|\bclick\b' bigbang --include=*.py || echo SAFE` → `SAFE`; `pytest --collect-only -q` still 371 |
| 4 | Add a minimal `package.json` (`type:module`, `engines.node>=18`, `scripts.test`) + lockfile | bluehenre | free | ~15 | App has **no manifest at all** — undeclared deps/Node version, no `npm ci`/test entrypoint. | `cd apps/bluehenre && node --check server.mjs && node public/js/twin.contract.test.mjs` |
| 5 | Delete the committed junk dir `apps/ava-factory/C:/Program Files/Git/ckpt/chat` | ava-factory | free | 0 | Zero-risk (empty dirs, no source refs); removes an MSYS path-mangling artifact from history. | `find "apps/ava-factory/C:" -type f | wc -l` → `0` |
| 6 | Remove `numpy>=1.24` from `[project.dependencies]` (imported nowhere) | ava-skills | free | 1 | Pure unused install weight on every consumer. | `python -c "import skills.loader, skills.state_store" && pytest -q` |
| 7 | Prune the ~10 zero-import deps from root `requirements.txt` (`deepspeed, accelerate, wandb, scikit-learn, dolma, nemo-curator, tiktoken, webdataset, einops, psutil`) | ava-factory | free | ~10 | Install honesty: the root manifest advertises a heavy stack the code never imports (real install is `docker/requirements.*`). | `grep -rnE '^\s*(import|from)\s+(deepspeed|accelerate|wandb|sklearn|dolma|nemo_curator|tiktoken|webdataset|einops|psutil)\b' ava dottie *.py scripts | grep -v __pycache__` → empty |
| 8 | Fix stale docstring `validate.py:815` "Run L1→L4" → "L1→L6" (code runs all 6) | dottie | free | 1 | Honest-notes: the one lying comment in an otherwise scrupulous module. | `grep -c 'L1->L4' dottie/research/validate.py` → `0` |
| 9 | Narrow two bare `except:` swallows (`cli.py:225`, `:273`) to specific exceptions | personal-graphify | free | 2 | Correctness/observability: silently hides real read/subprocess failures. | `pytest tests/test_cli.py tests/test_query_cost.py -q` |
| 10 | Delete dead `bigbang/core/discovery.py` (27 LOC, no importers) + drop sibling-app names from ruff `known-first-party` (pyproject:70) | scout-cli | free | ~28 | Dead module + copy-paste config leak, both zero-risk. | `grep -rn 'discovery' bigbang --include=*.py | grep -i import || echo SAFE` → `SAFE`; `python -c "import bigbang.cli"` |

**Larger structural cleanups (higher effort, deferred out of the top-10 but high-value):**
- **dottie** `kg/**` — 1,308 LOC orphaned subsystem (zero importers, own 379-LOC test suite): wire a CLI/API entrypoint or delete. Gate: `grep -rn 'dottie.kg\|from dottie import kg' dottie/ scripts/ --include='*.py' | grep -v 'dottie/kg/'` → empty (proves unwired).
- **ava-factory** delete `train_1b_deepspeed.py` (957 LOC mock trainer) + `docs/blueprint/` duplicate (1,040 LOC) + the other ~1,489 LOC of zero-ref root scripts (prefect_flows.py, data_builder_agent.py, trainer_agent.py, …). All lane-free (root files, not `dottie/**`). ~3,500 deletable LOC.
- **dottie** `FactoryPolicy` (policy.py:438-543, ~106 LOC) unreachable from the CLI/API `Literal["ollama","ava","echo"]` backends — delete or expose.
- **bluehenre / ava-factory** de-duplicate the two `npcChat` provenance paths; consolidate the drifting ruff configs (root vs dottie vs scout-cli).

---

## Cross-cutting observations
- **The provenance / anti-fabrication doctrine is real and enforced in code**, not just claimed: bluehenre gates every number on `source:"local"`; ava-skills/harness keep honest-`None` invariants and `real_unimplemented`; validate.py refuses to launder `skipped` into `pass`. This is the monorepo's strongest cultural signal.
- **The quality gradient is inverted from age:** the newest frozen trainer + validator are the best code; the oldest superseded trainers (`train_1b_deepspeed.py`) and the wide dependency manifests are the worst. The cleanup direction is clear — **delete the disowned legacy, raise the older CLI core up to the `openswap` bar.**

