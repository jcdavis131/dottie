# Gigatoken investigation — verified claims, substrate map, bake-in plan

**Executive summary (3 lines):**
1. Gigatoken (github.com/marcelroed/gigatoken, MIT, ~1.9k stars) is real and its README honestly discloses that the 989x/24.53 GB/s headline compares an unsplit+cached path against presplit uncached baselines — the honest like-for-like advantage is ~1–2 orders of magnitude (author's compat mode: 200–300x; independent repro: 26.2x vs tiktoken), not ~1000x.
2. Our tokenization is already Rust (HF `tokenizers`) but is driven one-doc-at-a-time from a single-threaded Python loop in `pack_docs` (pack.py:106) — the transferable wins are `encode_batch` (GIL-released, rayon-parallel, zero new deps), a concept-string memo cache (pack.py:120 re-encodes a tiny closed set per doc), and gigatoken's benchmark-disclosure discipline for our own harness; a pure-Python pretoken LRU and the Rust crate itself are rejected (would move work into Python / add an untested-on-Windows native dep against the frozen-sha gate).
3. Nothing can be applied yet — `dottie/pipeline/pack.py` and `curator.py` are under the bind-mounted freeze; diff-shaped patches and a staged (NOT run) benchmark script `tasks/artifacts/tokenizer_bench.py` are ready for when the run ends.

---

## 1. Provenance and claim verification (fetched 2026-07-23)

Shortlink resolution (via LinkedIn interstitial pages, treated as data):
- `https://lnkd.in/g3y2rngU` -> **https://github.com/marcelroed/gigatoken** (the repo)
- `https://lnkd.in/gTTFyCHP` -> **https://www.marktechpost.com/2026/07/23/meet-gigatoken-a-rust-bpe-tokenizer-that-encodes-text-at-24-53-gb-s-up-to-989x-faster-than-huggingface-tokenizers/** (the analysis article)

Repo facts (from repo page + README): MIT license; Rust 66.2% / Python 33.3%; ~1.9k stars; top-level docs include `README.md`, `design_doc.md`, and `pretokenizer_optimization_log.md`.

### Claims vs. evidence

| Post claim | Verified? | Evidence / caveat |
|---|---|---|
| 24.53 GB/s GPT-2 encode on 144-core EPYC 9565 | Stated in README; not independently reproduced by us | Baselines: HF `encode_batch_fast` 24.8 MB/s (first 100 MB, **presplit**), tiktoken 36.0 MB/s (first 1 GB, **presplit**) |
| ~1000x vs HF/tiktoken | **Methodology-inflated as a headline** | Author *does* disclose: "Gigatoken encodes the whole file un-split, and is thus doing more work... to find split boundaries" — but gigatoken also benefits from pretoken caching while baselines run uncached, and the compared work units differ. Author's own HF-compatible mode: 200–300x. Independent reproduction cited by the article: 26.2x vs tiktoken on smaller data. SentencePiece vocabs: only 7–22x. So: honest disclosure, inflated headline. |
| Single-thread pretokenizer progression 47 -> 462 -> 830 -> 1049 MiB/s | Verified in `pretokenizer_optimization_log.md` | fancy-regex 47 -> hand state machine 380 -> winnow+NEON 462 -> **LUT dispatch + SWAR** 830 -> unsafe bounds-check removal 840 -> advance/count split 848 -> **dual-cursor ILP** 1,049 MiB/s. Log also records honest failures: hot/cold split reverted (580), two-pass SWAR abandoned (354), PGO nil (842). |
| Pretoken caching as a pillar | Partially | Post/article mention it; the optimization log documents **no cache hit rates**; article notes long-tail distribution + Python FFI overhead limit gains. The cache lives *below* the Rust FFI boundary — key detail for us. |
| Full-file boundary finding vs presplit | Verified as disclosed methodology difference | This is precisely why the headline number is not apples-to-apples. |
| Windows support | Caveat | Author: "Windows has not been tested much" — directly relevant to this box. |

**Assessment:** claims are plausible and the methodology note is honest (the disclosure is in the README, not buried). The 989x/1000x figure should be quoted only with the presplit/caching asymmetry attached. The genuinely transferable engineering lessons are (a) parallelism and staying below the FFI boundary dominate; (b) measured-progression optimization logs with reverted failures are the credibility mechanism; (c) disclose your benchmark's split/caching methodology.

---

## 2. Our substrate map (read-only, file:line)

All paths relative to `C:\Users\jcdav\dottie` unless absolute.

**Tokenizer implementation** — HF `tokenizers` (Rust core), locally trained byte-level BPE, NOT tiktoken/rustbpe:
- `apps/ava-factory/dottie/tokenizer.py:50-81` — `DottieTokenizer` wraps `tokenizers.Tokenizer`; `encode()` at :80-81 is `self._tok.encode(text).ids`.
- `apps/ava-factory/dottie/tokenizer.py:156` — pretokenizer is `pre_tokenizers.ByteLevel` (GPT-2-style regex, **already in Rust**, not Python).
- `apps/ava-factory/dottie/tokenizer.py:29-37` — special ids pinned 0..5; :149 uint16 vocab guard.

**Frozen artifact + freeze gate** — sha-bound, lives on the `ava_state` docker volume:
- `apps/ava-factory/dottie/tokenizer.py:39` — `AVA_TOKENIZER` default `/state/tokenizer.json`; freeze doctrine at :6-9; `Manifest.freeze_tokenizer` at :186.
- `apps/ava-factory/docker-compose.yml:39` — `AVA_TOKENIZER: /state/tokenizer.json`; :5 and :256 — shared external `ava_state` volume. Host-side copies resolve per `scripts/bench_pipeline.py:33-57` (`data/{preset}/tokenizer/ava_{preset}_bpe.json` or `configs/{preset}.yaml -> data.tokenizer_path`).
- `apps/ava-factory/dottie/pipeline/pack.py:59-88` — `load_tokenizer()` validates `<|endofdoc|>` + uint16 and computes the sha threaded into `manifest.complete(tokenizer_sha=...)` (the gate; :13-17).

**Where tokenization actually happens** — in the curator's pack step, on CPU, in Python-driven per-doc calls:
- `apps/ava-factory/dottie/pipeline/pack.py:91-138` — `pack_docs()`: per-doc Python loop; `ids = tok.encode(d["text"]).ids` at :106; a **second** `tok.encode(concept)` per doc at :120; Python `list.extend` stream build at :108; `np.array(..., uint16)` at :134.
- `apps/ava-factory/dottie/pipeline/curator.py:259` — `pack_docs(docs, self.lt)` per split, inside `process_shard` (:160-246) after clean -> english -> gopher -> edu -> PII-scrub -> MinHash(128 perm) dedup -> 13-gram decontam.
- **No `encode_batch` anywhere in ava-factory** (grep over the tree: only per-doc `encode`).
- Concurrency model: one curator process per shard lease; parallelism only via docker replicas over the manifest (docker-compose.yml:71-167) — within a shard, tokenization is single-threaded Python.

**The collector does NOT tokenize** (fraction of collector work that is tokenization: ~0):
- `apps/ava-factory/dottie/pipeline/collector.py:208` (sha1 doc ids), :458 (jsonl bytes) — hash+write only; :761+ is Stage-5 *text sampling* for tokenizer training, not encoding.
- Exception: the bench harness itself double-encodes during the collector bench purely to estimate tokens — `scripts/bench_pipeline.py:91`.

**What fraction of curator work is tokenization? UNMEASURED.** Static evidence only:
- `reports/` contains **no** `bench_pipeline.json` (the harness at `scripts/bench_pipeline.py:121-197` has never persisted a report on this box), and its curator bench reports one aggregate tok/s across clean+dedup+decontam+pack — it cannot isolate the tokenize fraction even when run.
- The only live datapoint: `curator.py:182-183` comment — "leases expire mid-shard (seen live: ~15–25 min packs)" — per-shard wall time with all stages aggregated. MinHash-128 and the PII/quality regexes plausibly rival encode; do not assume tokenize dominates. Patch B below adds stage timers so this becomes a measurement.

**Prior art in the ecosystem:**
- `apps/scout-rtx/prepare.py:22` (`import rustbpe`), :307-313 (rustbpe BPE training), :319-324 (encode via `tiktoken.Encoding` built from rustbpe ranks) — the karpathy/nanochat pattern: train in Rust, encode via tiktoken. **Not usable today**: `SPEC.md:21` marks scout-rtx UNMEASURED; `TODOS.md:3972-3977` — 7 of 10 declared deps missing on this box, `rustbpe` is a native extension with Windows-wheel risk, install deliberately declined.
- `~/ava-agi/streaming_data.py` and `~/ava-agi-factory-v6-4/streaming_data.py` (also mirrored at `apps/ava-factory/streaming_data.py:228-267`) — legacy demo stubs (`SimpleTokenizer` byte fallback, `AutoTokenizer` placeholder). Not production prior art.

---

## 3. Learnings ranked (impact on OUR pipeline x implementation cost)

### Adopted

**A1. `encode_batch` in `pack_docs` — top win.** Rank 1: high impact, near-zero cost, zero new deps.
Our per-doc loop (pack.py:106) crosses the Python/Rust FFI once per doc and holds encode to one core. HF `tokenizers.encode_batch` releases the GIL and fans out over rayon threads inside the Rust library we already ship. This is the gigatoken lesson ("parallelism + stay below the FFI boundary") delivered through the dependency we already have. Docs are already materialized as a list per split (curator.py:174, :224-232), so batching adds no memory phase we don't already pay. Output ids are identical to the loop (same tokenizer, same per-item encode) — the sha freeze gate is untouched; the bench script asserts id-equality anyway.

**A2. Concept-string memo cache — the honest version of "pretoken caching" for us.** Rank 2: small-moderate impact, trivial cost.
pack.py:120 re-encodes `d["concept"]` for every synthetic doc; concepts are a small closed set (exactly the long-tailed distribution the post describes, but at string granularity where a Python dict beats re-entering Rust). One local dict.

**A3. Benchmark-methodology discipline for our own harness.** Rank 3: medium impact (decision quality), low cost.
Adopt from gigatoken: (i) disclose split/caching methodology next to every number; (ii) fresh-process runs, best-of-3, variants interleaved on the same data; (iii) keep an optimization log that records reverted failures (their hot/cold-split revert and abandoned two-pass SWAR are what make the 1049 MiB/s credible). Concretely for us: persist `reports/bench_pipeline.json` when run, and add stage timers to `process_shard` (Patch B) so "what fraction is tokenization" becomes measured, not vibes. This is the confirm-why doctrine applied to perf numbers.

### Rejected (explicitly)

**R1. Pure-Python pretoken LRU in the packing loop — rejected for the encode hot path.**
Gigatoken's cache sits *below* the FFI boundary in Rust. Ours would sit above it: a Python word-split + per-word dict lookup wrapped around an encode that already runs in Rust moves work *into* the slow layer; expected net loss except on pathologically templated text. The bench script includes this variant behind a flag specifically to validate the rejection with a measurement rather than an assertion. (The concept-memo A2 is the surviving special case: guaranteed repetition, short strings, one dict hit replaces a full FFI round-trip.)

**R2. LUT/SWAR/dual-cursor pretokenization — rejected: nothing to replace.**
Our pretokenizer is HF `ByteLevel` in Rust (tokenizer.py:156), not Python regex. These techniques live inside tokenizer libraries; at our shard sizes the curator is not pretokenizer-bound in any way we could act on without becoming a tokenizer-library maintainer.

**R3. Adopting the gigatoken crate (or rustbpe) as a pipeline dep — rejected by default; operator option only.**
Against the no-deps bar: new native extension; author states Windows is barely tested; scout-rtx precedent shows native-wheel risk on this box (TODOS.md:3976). Against correctness: our vocab is custom-trained HF-format with special ids pinned 0..5 and shards sha-bound to the artifact — an encoder swap must be bit-identical or it invalidates every packed shard via the freeze gate, and gigatoken's HF-compat mode is the 200–300x path, not 989x. **Operator option**: revisit only if, after A1+A3 land and are measured, tokenization is still the binding constraint on the curation >= 3x trainer gate (bench_pipeline.py:352-384) by an order of magnitude.

**R4. Full-file boundary finding — rejected: not our shape.**
Our documents arrive as discrete jsonl records; there is no presplit cost to avoid. Concatenation with `<|endofdoc|>` happens post-encode (pack.py:110).

---

## 4. Diff-shaped patch proposals (apply ONLY after the freeze lifts)

Both targets are currently under the bind-mounted freeze (`apps/ava-factory/dottie/...`). Do not apply while the trainer runs.

### Patch A — `apps/ava-factory/dottie/pipeline/pack.py` (A1 + A2)

```diff
--- a/dottie/pipeline/pack.py
+++ b/dottie/pipeline/pack.py
@@ def pack_docs(docs: list[dict], lt: LoadedTokenizer) -> tuple[np.ndarray, dict]:
     tok = lt.tokenizer
     stream: list[int] = []
     index: list[dict] = []
+    # Batch-encode releases the GIL and parallelizes in the Rust library
+    # (rayon). Ids are identical to per-doc encode; the freeze gate binds the
+    # tokenizer artifact sha, which this does not touch.
+    encodings = tok.encode_batch([d["text"] for d in docs]) if docs else []
+    # Concepts are a small closed set re-encoded per doc; memoize above the
+    # FFI boundary (this is the honest slice of "pretoken caching" for us).
+    concept_cache: dict[str, int] = {}
 
-    for d in docs:
-        ids = tok.encode(d["text"]).ids
+    for d, enc in zip(docs, encodings):
+        ids = enc.ids
         start = len(stream)
         stream.extend(ids)
         end = len(stream)
         stream.append(lt.eod_id)  # separator, not counted in [start, end)
@@
         concept = d.get("concept") or ""
-        concept_ids = tok.encode(concept).ids if concept else []
-        concept_token_id = concept_ids[0] if concept_ids else UNTAGGED_CONCEPT
+        if concept:
+            if concept not in concept_cache:
+                cids = tok.encode(concept).ids
+                concept_cache[concept] = cids[0] if cids else UNTAGGED_CONCEPT
+            concept_token_id = concept_cache[concept]
+        else:
+            concept_token_id = UNTAGGED_CONCEPT
```

Notes: preserves the exact idx sidecar schema, the eod separator placement, and the uint16 asserts; behavior-identical output (assert with the bench script's equivalence check before committing). `tests/test_curator.py:359-401` and `test_tokenizer.py` are the relevant suites — run them post-freeze, not now.

### Patch B — `apps/ava-factory/dottie/pipeline/curator.py` (A3: measure the tokenize fraction)

```diff
--- a/dottie/pipeline/curator.py
+++ b/dottie/pipeline/curator.py
@@ def process_shard(self, m: Manifest, shard) -> dict:
         counts = {
             "read": 0,
             "kept": 0,
             "empty": 0,
             "non_english": 0,
             "edu_reject": 0,
             "duplicate": 0,
             "gopher_reject": {},
             "contaminated": {},
+            "stage_s": {"clean": 0.0, "dedup": 0.0, "decontam": 0.0, "pack": 0.0},
         }
```
plus `t = time.perf_counter()` / `counts["stage_s"][...] += time.perf_counter() - t` brackets around: the clean/gopher/pii block (curator.py:193-212), `deduper.add_if_new` (:213), `is_contaminated` (:216), and the `pack_docs` call inside `_emit_packed` (:259). Stage seconds then flow into the existing per-shard counts log for free. This converts "~15-25 min packs, fraction unknown" (curator.py:182-183) into a measured breakdown after one live shard.

### How to measure before/after honestly

Staged (written, NOT run) at `C:\Users\jcdav\dottie\tasks\artifacts\tokenizer_bench.py`:
- tokenizes real raw-shard docs with the **current** per-doc path, the encode_batch path, and (behind a flag) the rejected pure-Python word-cache path, on the same docs, interleaved A,B,C x N, best-of-N reported;
- asserts id-equality between loop and batch before reporting any speedup;
- refuses to run without `--trainer-idle` (CPU contention would corrupt both the bench and the live run);
- run it 3x in fresh processes and take the best per variant (allocator/cache warmth disclosure), record `os.cpu_count()` and doc/byte counts in the JSON it writes.
Before/after protocol: (1) freeze lifts; (2) run bench 3x on current code -> baseline JSON; (3) apply Patch A; (4) rerun identically; (5) only then quote a speedup, with the methodology line attached, gigatoken-style. For pipeline-level truth, land Patch B and read `stage_s` off one live shard.

---

## 5. Open questions

1. Is tokenization actually the curator bottleneck vs MinHash-128/PII regex? Unmeasured until Patch B or the staged bench + a dedup micro-bench run post-freeze.
2. `encode_batch` thread count on this box under docker CPU limits — verify rayon actually fans out inside the curator container (TOKENIZERS_PARALLELISM / RAYON_NUM_THREADS env).
3. Peak-memory delta of materializing all `Encoding` objects for a shard at once (shard docs are already fully materialized, but Encoding objects carry offsets; if it matters, chunk the batch at ~1k docs).
4. Does the curation >= 3x trainer gate currently pass on mini? `reports/bench_pipeline.json` has never been persisted here.
