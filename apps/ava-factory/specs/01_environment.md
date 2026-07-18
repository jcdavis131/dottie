# Spec 01 — Environment & Scaffolding

- **Spec ID:** 01_environment
- **Worker tier:** Sonnet
- **Dependencies:** none (first spec to run; all other specs depend on this one)
- **Status when done:** `bash scripts/setup_env.sh` + `make test` green on a fresh container

## Purpose

Stand up the Python environment and package scaffolding for the real-mode Ava build inside the
CPU-only execution container (4 cores, 15GB RAM, no GPU, Python 3.11, PyPI reachable,
huggingface.co hub BLOCKED, wandb blocked — zero network calls in any pipeline code).
Blueprint files at repo root (logic_textbook_pipeline.py, train_1b_deepspeed.py, dolma_config.yaml,
requirements.txt, etc.) are reference-only and MUST NOT be modified by THIS spec's worker.
Exceptions defined elsewhere: `model_1b.py`, `multi_jspace_module.py` (surgical in-place fixes,
spec 04 only) and `server.py` (spec 07 only) — and `ava/` code DOES import `model_1b.py` /
`multi_jspace_module.py` (they are the real model modules). All new code lives under `ava/`,
`scripts/`, `tests/`, `configs/`.

## Deliverable files (exact paths, all repo-relative)

1. `scripts/setup_env.sh`
2. `ava/__init__.py`
3. `ava/config.py`
4. `configs/nano.yaml`
5. `configs/nano_quick.yaml`
6. `pytest.ini`
7. `Makefile`
8. `.gitignore` (append-only edit — see below; this is the ONLY pre-existing file that may be touched, and only appended to. If no `.gitignore` exists, create it.)
9. `tests/test_config.py`

## Detailed requirements

### scripts/setup_env.sh
- `#!/usr/bin/env bash`, `set -euo pipefail`.
- Installs pinned deps via pip (CPU-only torch wheel from the standard PyPI index — do NOT point at
  download.pytorch.org; plain `pip install "torch>=2.4"` resolves to the CPU wheel on this container):
  `torch>=2.4`, `tokenizers>=0.19`, `numpy>=1.26`, `pyyaml>=6.0.1`, `pydantic>=2.6`,
  `fastapi>=0.110`, `uvicorn[standard]>=0.27`, `websockets>=12`, `pytest>=8`, `tqdm>=4.66`.
- Also installs `safetensors>=0.4` (pure-local serialization; spec 09 conversion needs it).
- MUST NOT install: deepspeed, dolma, nemo-curator, wandb, datasets, transformers, accelerate,
  einops. Do not `pip install -r requirements.txt` (that file is blueprint-only).
- Sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` in the script env and prints a reminder that
  huggingface.co is proxy-blocked (the `tokenizers` PyPI package itself installs fine).
- Ends with a self-check: `python -c "import torch, tokenizers, numpy, yaml, pydantic, fastapi, uvicorn, websockets, tqdm; print('env OK', torch.__version__)"`.
- Idempotent: safe to run twice.

### ava/config.py — AvaConfig
- **The committed `configs/nano.yaml`, `configs/mini.yaml`, `configs/base1b.yaml` are the
  authoritative schema — do NOT overwrite them.** They use nested sections
  `model:` / `jspace:` / `training:` / `phases:` / `branch_chat:` (nano) / `milestones:`+`branches:`
  (base1b) / `data:`. Space keys are `system1,system2,critic,planner` (matching
  `freeze_spaces()` / `BRANCH_CONFIGS` naming in the blueprint code).
- `AvaConfig` is a typed dataclass tree mirroring those sections (e.g. `cfg.model.d_model`,
  `cfg.jspace.slots["system1"]`, `cfg.training.wsd.lr_max`, `cfg.phases[0].mix`).
- `AvaConfig.load(preset_name: str) -> AvaConfig` reads `configs/{preset_name}.yaml`
  (raise `FileNotFoundError` with a message listing available presets on miss). Unknown YAML keys
  are a hard error (catch typos early).
- `count_params(cfg) -> int` builds the actual nano model on CPU (meta device or real — a plain
  `torch.nn` construction is fine at 14M) and returns `sum(p.numel())`. If the model module
  (spec 04+, not yet written) is absent, fall back to an analytic formula:
  embeddings `vocab*d_model` (tied output head, count once) + per-layer
  `12*d_model^2` approx for attn+MLP(4x) + J-space slot memories `sum(slots)*d_model` + verbalizer
  `d_model*vocab is tied` — document the formula in a docstring. Analytic and built counts must
  agree within 10% once the model exists.
- CLI: `python -m ava.config --preset nano --count-params` prints exactly one line:
  `preset=nano params=<N> (~<N/1e6:.1f>M)`. `--preset nano_quick` also works.
  Exit code 0 on success, 2 on unknown preset.

### configs/nano.yaml — ALREADY COMMITTED, authoritative
Do not rewrite it; `AvaConfig` must parse it as-is (headline values: vocab 8192, d_model 256,
4 heads × 64, layers 2/6/2, J-slots 32/64/16/32, half-lives 8/60/30/50, 30M-token 6-phase
curriculum, WSD warmup 110 / stable_frac 0.92 / lr 1e-3→1e-4, `branch_chat` section).
`configs/nano_quick.yaml`: CREATE it as a copy of nano.yaml with `preset: nano_quick`,
`training.tokens_total: 15_000_000`, and phase token counts halved proportionally.
GPU presets `configs/mini.yaml` / `configs/base1b.yaml` are also already committed —
`AvaConfig.load` must parse them too (they add `milestones:`/`branches:`/`frac:` fields).

### pytest.ini
- `[pytest]` with `testpaths = tests`, `addopts = -q --tb=short`,
  `filterwarnings = ignore::DeprecationWarning`.

### Makefile (phony targets; each a thin wrapper, one command per line)
- `setup` → `bash scripts/setup_env.sh`
- `data` → `python scripts/gen_all_data.py --seed 1234` (spec 02 delivers the script; target may fail until then — that is fine)
- `tokenizer` → `python -m ava.tokenizer train --preset nano` (spec 03)
- `pack` → `python -m ava.data.pack --preset nano` (future spec; stub target OK)
- `smoke` → `python -m ava.train --preset nano_quick --max-steps 20` (future spec; stub target OK)
- `train-nano` → `python -m ava.train --preset nano` (future)
- `eval` → `python -m ava.eval --preset nano` (future)
- `serve` → `uvicorn server:app --host 0.0.0.0 --port 8000` (spec 07 rewires the root server.py)
- `report` → `python -m ava.report --out reports/` (future)
- `test` → `pytest`
Targets referencing not-yet-written modules must still be present verbatim so the foreman's later
specs plug in without Makefile edits.

### .gitignore additions (append this block)
```
data/nano/
runs/
export/
__pycache__/
*.pyc
.pytest_cache/
```
`reports/*.json` stays tracked — do NOT ignore `reports/`.

### tests/test_config.py
- `test_nano_loads`: `AvaConfig.load("nano")` returns the exact values above.
- `test_nano_quick_budget`: budget == 15_000_000.
- `test_unknown_preset_raises`: `FileNotFoundError`.
- `test_param_count_range`: `count_params(load("nano"))` in `[13_000_000, 16_000_000]`.

## Interfaces / schemas
- Downstream specs import `from ava.config import AvaConfig` and call `AvaConfig.load(preset)`.
  Field names above are a frozen contract — do not rename.
- All paths in configs are repo-root-relative; code resolves them against the repo root
  (locate via `pathlib.Path(__file__).resolve().parents[1]`), never against CWD.

## Acceptance criteria (foreman runs, from repo root)
1. `bash scripts/setup_env.sh && python -c "import torch, tokenizers, fastapi; print(torch.__version__)"`
   → exits 0, prints a torch version >= 2.4.
2. `pip show deepspeed wandb transformers datasets dolma nemo-curator 2>/dev/null | grep -c Name` → prints `0`.
3. `python -m ava.config --preset nano --count-params` → exits 0, printed param count between
   13,000,000 and 16,000,000.
4. `python -m ava.config --preset nano_quick --count-params` → exits 0.
5. `pytest tests/test_config.py` → all pass.
6. `make test` → runs pytest successfully; `make -n data tokenizer smoke` → prints the commands above (dry run).
7. `git status --porcelain` shows only NEW files under ava/, scripts/, configs/, tests/, specs/,
   pytest.ini, Makefile, plus the .gitignore append — no blueprint file modified.

## Out of scope
- Model architecture code (ava/model.py), training loop, packing, eval, server — later specs.
- GPU presets (mini, base1b), deepspeed configs, WSL2/Alienware setup.
- Any network access beyond `pip install` from PyPI inside setup_env.sh.
- Modifying requirements.txt or any blueprint file; committing to git.
