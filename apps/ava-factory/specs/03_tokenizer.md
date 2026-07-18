# Spec 03 — Tokenizer (byte-level BPE, trained locally)

- **Spec ID:** 03_tokenizer
- **Worker tier:** Sonnet
- **Dependencies:** 01_environment (env + AvaConfig); 02_data_generation (needs raw JSONL in
  `data/nano/raw/` — at least partial output is sufficient: ≥60MB across ≥3 generator sources.
  If the foreman dispatches this before 02 finishes, the worker may train on whatever shards
  exist as long as the stratification rule below is satisfiable; otherwise it must fail fast
  with a clear "insufficient raw data" error).
- **Consumers:** packer/trainer (token ids), eval harness (concept-token reportability targets),
  server.

## Purpose

Train a byte-level BPE tokenizer LOCALLY with the `tokenizers` library on our own synthetic
corpus. huggingface.co is proxy-blocked: no `from_pretrained`, no hub downloads, no
`transformers` — only the `tokenizers` PyPI package, offline. Vocab 8192 for nano
(parameterized so GPU presets can later use 32000). The artifact is a single JSON file the
whole pipeline loads.

## Deliverable files (exact paths)

1. `ava/tokenizer.py` (module + CLI)
2. `tests/test_tokenizer.py`
3. Artifact produced by running the CLI: `data/nano/tokenizer/ava_nano_bpe.json`
   (+ sidecar `data/nano/tokenizer/train_meta.json`, see below). Artifacts live under the
   gitignored `data/nano/` — the worker generates them but does not commit them.

## Detailed requirements

### Special tokens (order and spelling frozen — ids 0..5)
```
0 <|pad|>   1 <|bos|>   2 <|eos|>   3 <|endofdoc|>   4 <|user|>   5 <|assistant|>
```
Registered as `special_tokens` at trainer time AND wired into the tokenizer so `encode` never
splits them (they appear literally in B4 chat data and must map to single ids). Byte-level BPE:
`tokenizers.models.BPE` + `pre_tokenizers.ByteLevel(add_prefix_space=False)` +
`decoders.ByteLevel` + `processors.ByteLevel(trim_offsets=False)` — lossless on arbitrary UTF-8,
so no UNK token exists.

### Training corpus: ~50MB stratified sample
- Input: `data/nano/raw/*.jsonl` (schema from spec 02: `text/task_type/concept/phase/source`).
- Stratify by phase with target byte proportions `p0:15% p1:18% p2:37% p3:14% p4:6% p5:10%`
  (mirrors the 30M-token curriculum weights 5/6/10/4.5/1.5/3). Sample docs with a seeded
  `random.Random(1234)` reservoir/shuffle per phase until each bucket reaches its byte quota or
  its raw data is exhausted (then log a warning and rebalance the remainder proportionally —
  never fail if one phase is light). Cap total at 52MB.
- Write the sample to a temp file(s) under the scratch dir and train from files (constant
  memory); training must stay under 6GB RSS and finish <10 min on 4 CPU cores.
- Trainer: `BpeTrainer(vocab_size=cfg.vocab_size, min_frequency=2, special_tokens=[...6 above...],
  initial_alphabet=pre_tokenizers.ByteLevel.alphabet())`.

### API (frozen contract)
```python
class AvaTokenizer:
    @classmethod
    def train(cls, preset: str, raw_dir: str | None = None, seed: int = 1234) -> "AvaTokenizer"
    @classmethod
    def load(cls, path: str | None = None, preset: str = "nano") -> "AvaTokenizer"  # default data/{preset}/tokenizer/ava_{preset}_bpe.json
    def encode(self, text: str, add_bos: bool = False, add_eos: bool = False) -> list[int]
    def decode(self, ids: list[int]) -> str
    def concept_token(self, concept: str) -> int   # first token id of encode(concept) — the reportability target
    @property
    def vocab_size(self) -> int
    # id constants: .pad_id .bos_id .eos_id .eod_id .user_id .assistant_id  (0..5)
```
- Round-trip guarantee: `decode(encode(t)) == t` for any str `t` (byte-level BPE gives this;
  a failure is a wiring bug, not a data problem).
- Vocab size is read from `AvaConfig.load(preset).vocab_size` — nano→8192; the code takes it
  from config, never hardcodes 8192, so mini/base1b (32000) work later unchanged.
- `train()` also writes `data/{preset}/tokenizer/train_meta.json`:
  `{"preset", "vocab_size", "seed", "sample_bytes", "bytes_per_phase": {...}, "input_shards": [...names...], "sha256_artifact"}`.

### CLI
- `python -m ava.tokenizer train --preset nano [--raw-dir data/nano/raw] [--seed 1234]`
  → trains, writes artifact + meta, prints one JSON line
  `{"artifact": "data/nano/tokenizer/ava_nano_bpe.json", "vocab_size": 8192, "sample_bytes": N, "compression_chars_per_token": X.XX}`
  where compression is measured on a held-out 2MB sample (docs NOT in the training sample —
  reserve them by seeded split before training).
- `python -m ava.tokenizer encode --text "spider has 8 legs"` → prints ids (debug convenience).
- Exit 1 with message `insufficient raw data: found X MB in <dir>, need >= 60` when applicable.

### tests/test_tokenizer.py
(Tests must run fast: if the artifact is missing, train a throwaway 1024-vocab tokenizer on
2MB of raw data into a tmp dir via the same code path; if `data/nano/tokenizer/ava_nano_bpe.json`
exists, test the real artifact.)
- `test_roundtrip_1k_docs`: sample 1000 docs across all raw shards (seeded), assert
  `decode(encode(text)) == text` for every one, including docs containing `<|user|>` markers
  and non-ASCII (Spanish/French from B3).
- `test_special_token_ids`: the 6 constants map to ids 0–5 and each encodes to exactly one id.
- `test_chat_markers_atomic`: `encode("<|user|>hi<|assistant|>")[0] == 4` and contains 5.
- `test_concept_token`: `concept_token("spider")` is a stable int in `[6, vocab_size)`;
  calling twice returns the same id.
- `test_load_speed`: `AvaTokenizer.load()` completes in < 1.0s (time.perf_counter).
- `test_compression`: on the held-out sample, `total_chars / total_tokens >= 3.0`
  (skip with a clear message if only the throwaway 1024-vocab tokenizer is available — the 3.0
  bar applies to the real 8192 artifact only).
- `test_determinism`: train twice at vocab 1024 on the same 2MB sample, same seed → identical
  artifact file bytes.

## Interfaces / schemas
- Artifact is a standard `tokenizers.Tokenizer.save()` JSON — loadable by
  `tokenizers.Tokenizer.from_file()` directly; `AvaTokenizer` is a thin wrapper, so future GPU-side
  code (transformers on the Alienware) can consume the same file.
- Downstream contract: packer calls `encode(doc["text"]) + [eod_id]`; eval harness calls
  `concept_token(doc["concept"])`; trainer reads `pad_id` for attention masking.

## Acceptance criteria (foreman runs, from repo root, after spec 02 data exists)
1. `python -m ava.tokenizer train --preset nano` → exits 0 in <10 min;
   `data/nano/tokenizer/ava_nano_bpe.json` and `train_meta.json` exist; printed
   `compression_chars_per_token >= 3.0` and `vocab_size == 8192`.
2. `python -c "from ava.tokenizer import AvaTokenizer; t=AvaTokenizer.load(); ids=t.encode('<|user|>Is 17 prime?<|assistant|>'); assert ids[0]==4 and 5 in ids; assert t.decode(t.encode('araña ↔ 蜘蛛'))=='araña ↔ 蜘蛛'; print('ok', t.vocab_size)"`
   → prints `ok 8192`.
3. `python -c "import time,importlib; s=time.perf_counter(); from ava.tokenizer import AvaTokenizer; AvaTokenizer.load(); print(time.perf_counter()-s)"` → < 1.0.
4. `pytest tests/test_tokenizer.py` → all green (compression test not skipped).
5. No network: run acceptance 1 with `HF_HUB_OFFLINE=1 HTTPS_PROXY=http://127.0.0.1:9` — must
   still succeed (proves zero hub/network dependency).

## Out of scope
- 32000-vocab training runs for mini/base1b (parameterization only, not execution).
- Sequence packing, `<|bos|>`-per-sequence policy, curriculum batching — packer spec.
- SentencePiece/transformers wrappers, hub upload, tokenizer vocabulary analysis reports.
- Modifying blueprint files; committing artifacts or data to git.
