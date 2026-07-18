# Spec 09 — Checkpoint Conversion + Release Packaging

- **Spec ID:** 09_conversion_release
- **Worker tier:** Sonnet
- **Dependencies:** Spec 01 (env, `.gitignore` already contains `export/` and `runs/`); model spec
  (`ava/model.py` + `ava/config.py` able to rebuild the nano architecture from a config); training
  spec (checkpoints `runs/chat/ava_nano_chat.pt`, `runs/base/ava_nano_final.pt`,
  `runs/base/ava_nano_stable.pt`, metrics `runs/*/metrics.jsonl`); tokenizer spec
  (`data/nano/tokenizer/ava_nano_bpe.json`); eval spec (`reports/branch_eval_results_real.json`).
- **Status when done:** `python scripts/convert_checkpoint.py --ckpt runs/chat/ava_nano_chat.pt
  --out export/ava-nano && python scripts/convert_checkpoint.py --verify --ckpt
  runs/chat/ava_nano_chat.pt --out export/ava-nano` both exit 0 in the container.

## Purpose

Produce an honest, self-contained, verifiable export of a trained nano checkpoint. This
SUPERSEDES the blueprint's fake `convert_to_hf.py` (which writes a hardcoded
`{"hidden_size":2048,"num_layers":48}` config regardless of input); that file stays UNTOUCHED as
reference. The export must reload bit-faithfully (logit comparison) and carry a truthful
config.json describing the real 14M-param nano model — no aspirational 1B numbers. Also delivers
the release/distribution documentation (README "Nano pilot results" section template + git-LFS
policy).

## Deliverable files (exact paths, repo-relative)

1. `scripts/convert_checkpoint.py` (new)
2. `docs/RELEASE.md` (new — results template + distribution policy)
3. `tests/test_convert.py` (new)
4. Generated at runtime, gitignored, never committed: `export/ava-nano/` containing
   `model.safetensors`, `config.json`, `tokenizer.json`, `modeling/` (source copies),
   `README.md`, `checksums.txt`.
5. Additive edit to `scripts/setup_env.sh`: add `safetensors>=0.4` to the pip install list
   (pure-Python-wheel dep from PyPI; spec 01's exclusion list is amended by exactly this one
   package, nothing else).

## Detailed requirements

### scripts/convert_checkpoint.py — export mode

CLI: `python scripts/convert_checkpoint.py --ckpt <path> --out <dir> [--verify] [--prompts N]`.
Default `--ckpt runs/chat/ava_nano_chat.pt`, default `--out export/ava-nano`. Loads with
`torch.load(..., map_location="cpu", weights_only=True)` (fall back to `weights_only=False` with
a printed warning only if the checkpoint contains the config object). Writes:

- **`model.safetensors`** — the full state_dict via `safetensors.torch.save_file`, tensors kept
  in fp32 (nano trains fp32 on CPU; do NOT downcast — verification is atol 1e-5). Tied tensors:
  save one copy and record the tying in config.json (`tie_embeddings: true`), since safetensors
  rejects shared storage.
- **`config.json`** — HONEST, machine-generated from the checkpoint's actual config/shapes, never
  hardcoded. Required keys and their real nano values:
  `{"model_type": "ava-nano", "architectures": ["AvaModel"], "vocab_size": 8192, "d_model": 256,
  "n_heads": 4, "head_dim": 64, "n_layers_text": 2, "n_layers_fusion": 6, "n_layers_reasoning":
  2, "jspace_slots": {"S1": 32, "S2": 64, "Critic": 16, "Planner": 32}, "jspace_half_life":
  {"S1": 8, "S2": 60, "Critic": 30, "Planner": 50}, "rope_base": 10000, "tie_embeddings": true,
  "torch_dtype": "float32", "tokenizer_file": "tokenizer.json", "param_count": <real int from
  sum(numel)>, "training_tokens": <from the last line of the source run's metrics.jsonl, null if
  unavailable>, "source_checkpoint": "<--ckpt value>", "ava_version": "6.4", "export_utc":
  "<ISO8601>"}`. Values MUST be read from the loaded config/state_dict (e.g. d_model from an
  embedding shape) so a mini/base1b checkpoint later exports correct numbers with zero code
  change.
- **`tokenizer.json`** — byte-identical copy of `data/nano/tokenizer/ava_nano_bpe.json`.
- **`modeling/`** — source copies making the export self-contained: `ava/model.py`,
  `ava/config.py`, every other `ava/*.py` module needed to instantiate the model (resolve by
  following imports), plus the blueprint references `model_1b.py` and `multi_jspace_module.py`
  (copied verbatim, labeled `# reference blueprint` in a `modeling/README_SOURCES.txt` manifest
  listing each file's origin path and sha256).
- **`README.md`** (inside the export) — model card: honest one-paragraph description ("14M-param
  nano pilot of the Ava Multi-J-Space architecture, trained on synthetic curriculum data on CPU"),
  a working load snippet (build model from `modeling/` + `config.json`, load safetensors, tie
  embeddings), the eval summary if `reports/branch_eval_results_real.json` exists, and the
  standard disclaimer line ("Solo personal project, no connection to employer").
- **`checksums.txt`** — `sha256sum` of every file in the export dir (itself excluded).
- Exit non-zero with a clear message if the checkpoint or tokenizer is missing. Overwriting an
  existing `--out` is allowed (delete-and-recreate).

### scripts/convert_checkpoint.py — verify mode (`--verify`)

- Rebuilds the model FROM THE EXPORT ONLY: read `export/.../config.json`, construct the
  architecture via `ava.model` (the repo import is acceptable; the `modeling/` copies exist for
  off-repo users), load `model.safetensors`, re-tie tied weights.
- Loads the ORIGINAL `--ckpt` into a second instance.
- Runs 10 FIXED prompts (hardcoded list in the script — must include at minimum
  `"The number of legs on the animal that spins webs is"`, `"2 + 3 ="`, `"If all A are B and x is
  A then x is"`, plus 7 more covering logic/math/chat registers; `--prompts N` may lower the
  count for debugging but acceptance uses all 10). For each: tokenize, single teacher-forced
  forward, full-sequence logits from both models, compare with
  `torch.allclose(a, b, atol=1e-5, rtol=0)`. Both models `.eval()`, `torch.no_grad()`,
  `torch.manual_seed(0)`, fp32, CPU.
- Prints one line per prompt (`ok max_abs_diff=<x>` / `MISMATCH max_abs_diff=<x>`) and a final
  `VERIFY PASS 10/10` or `VERIFY FAIL k/10`; exit 0 only on 10/10.

### docs/RELEASE.md

Two sections, both concrete:
1. **"Nano pilot results" README section template** — a ready-to-paste markdown block with
   placeholder tokens (`{{param_count}}`, `{{training_tokens}}`, `{{final_loss}}`,
   `{{verbalizable_mass}}`, `{{broadcast_strength}}`, `{{eval_table}}`) plus one sentence of
   instructions to fill them from `runs/*/metrics.jsonl` and
   `reports/branch_eval_results_real.json`. Must include an honest-limitations paragraph
   (14M params, synthetic data, CPU-trained pilot — results validate the pipeline, not the
   capability claims of the 1B blueprint).
2. **Distribution & git-LFS policy** — checkpoints and exports are NOT committed: `runs/` and
   `export/` are gitignored (spec 01). Distribution paths: (a) copy `export/ava-nano/` out of the
   container, or (b) deterministic retrain (`make data tokenizer && python -m ava.train --preset
   nano --seed 1234` — same seed, same data, same checkpoint). Include the exact git-LFS commands
   (`git lfs install`, `git lfs track "*.safetensors"`, edit `.gitattributes`) as
   DOCUMENTED-BUT-NOT-EXECUTED, with a warning about LFS quota on free GitHub. State explicitly
   that `convert_to_hf.py` is superseded and kept only as blueprint reference.

### tests/test_convert.py

- `test_export_creates_files`: run export (skip via `pytest.skip` if
  `runs/chat/ava_nano_chat.pt` absent); assert the 6 artifacts exist and `config.json` parses
  with `model_type == "ava-nano"`, `d_model == 256`, `vocab_size == 8192`, `param_count` in
  [13_000_000, 16_000_000].
- `test_verify_passes`: `--verify` returns exit code 0.
- `test_tamper_detected`: copy export to a temp dir under the scratch/tmp area, add 1e-3 to one
  tensor in `model.safetensors`, re-save; `--verify --out <tampered>` exits non-zero.
- `test_tokenizer_copy_identical`: sha256 of export `tokenizer.json` equals source file's.

## Interfaces

- Frozen contract for any future publishing spec: export directory layout above; `config.json`
  key set above; `scripts/convert_checkpoint.py --ckpt X --out Y [--verify]` CLI. The script must
  work unchanged on future mini/base1b checkpoints (all dims read from the checkpoint, only the
  default `model_type` string may then be overridden via `--model-type`).

## Acceptance criteria (foreman runs, from repo root)

1. `python scripts/convert_checkpoint.py --ckpt runs/chat/ava_nano_chat.pt --out export/ava-nano`
   → exit 0; `ls export/ava-nano` shows `model.safetensors config.json tokenizer.json modeling
   README.md checksums.txt`.
2. `python -c "import json; c=json.load(open('export/ava-nano/config.json')); assert c['model_type']=='ava-nano' and c['d_model']==256 and c['vocab_size']==8192 and 13e6<c['param_count']<16e6"`
   → exit 0 (proves the config is real, unlike convert_to_hf.py's hardcoded 2048/48).
3. `python scripts/convert_checkpoint.py --verify --ckpt runs/chat/ava_nano_chat.pt --out export/ava-nano`
   → prints `VERIFY PASS 10/10`, exit 0.
4. `pytest tests/test_convert.py` → all pass (tamper test proves FAIL path works).
5. `git check-ignore export/ava-nano/model.safetensors` → exit 0 (never committable).
6. `git diff --stat convert_to_hf.py` → empty output (blueprint untouched).
7. `git status --porcelain` → only new `scripts/convert_checkpoint.py`, `docs/RELEASE.md`,
   `tests/test_convert.py`, plus the one-line `scripts/setup_env.sh` edit.

## Out of scope

- Actual HuggingFace-Hub upload or `transformers.AutoModel` compatibility shims (hub is
  network-blocked in the container; config.json is honest-custom, not a transformers config).
- Quantized/gguf/onnx exports; mini/base1b conversion runs (the script must merely not hardcode
  nano dims so it will work later).
- Executing git-lfs commands, committing checkpoints, or any git commit at all.
- Modifying or deleting `convert_to_hf.py`, `model_1b.py`, `multi_jspace_module.py` (they are
  copied, never edited).
