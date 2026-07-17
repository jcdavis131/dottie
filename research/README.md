# research/ — unwired research prototypes

Solo personal project, no connection to employer, built with public/free-tier only.

These modules were moved out of `ava/` because **nothing in the shipped
AvaModel/training/eval/serving stack imports them** — they are research
sketches with no tests and no integration:

| Module | Sketch of |
|---|---|
| `attention/gated_deltanet.py` | Gated DeltaNet linear attention (note: the *shipped* DeltaNet lives in `model_1b.py::DeltaNetBlock` and is tested — this file is an unrelated standalone sketch) |
| `attention/compressed_conv.py` | Compressed convolutional attention |
| `attention/sparse_compressed.py` | Sparse compressed attention |
| `audio/conformer.py` | Conformer audio encoder |
| `decoding/diffusion_gemma.py` | Diffusion-style decoding |
| `embeddings/per_layer.py` | Per-layer embeddings / MatFormer nesting (imported only by `mobile/matformer.py` below) |
| `mobile/matformer.py`, `mobile/export_executorch.py` | MatFormer nesting + ExecuTorch export |
| `memory/openwiki_adapter.py` | `~/.openwiki/wiki` → S2 workspace bridge (consumed only by the legacy blueprint trainer `train_1b_deepspeed.py`) |

Properties:

- **Not part of AvaModel** — `ava/model.py` / `model_1b.py` never touch these.
- **No tests** cover them; treat as untested reference code.
- The internal `mobile/matformer.py` → `embeddings/per_layer.py` relative import
  is preserved (namespace packages), so `import research.mobile.matformer` works.
- Browsing-citation artifacts (`【...】` markers) were stripped when the files
  moved; the code content is otherwise unchanged.

If one of these graduates into the real model, port it into `ava/` behind a
config flag with tests (see `tasks/`/`specs/` for the hill-climb process).
