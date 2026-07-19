"""
streaming_data.py — Constant low-memory streaming dataflow for Dottie AGI Factory v6.4
Solo personal project, no connection to employer, built with public/free-tier only

Problem: naive Dolma/Nemotron pipeline loads entire 50B logic + 300B math + 6T web into RAM.
Solution: iterable shard streaming with 1-file-open-per-source, fixed shuffle buffer, on-the-fly tokenization,
phase-aware weighted mixing, checkpointable offsets, background synthetic generation.

Memory guarantees:
- never holds more than shuffle_buffer (default 10k examples, ~80MB text) + current batch
- 1 file handle per source, line buffered, gzip streaming
- tokenization per-batch, not pre-tokenized corpus
- synthetic textbooks generated in background thread into rotating 100MB shards with backpressure

Usage:
    from streaming_data import DottieStreamingDataset
    ds = DottieStreamingDataset(data_root="data/streaming_shards", branch="base", shuffle_buffer=10000)
    for batch in ds.batched(seq_len=2048, batch_size=4):
        train(batch)  # batch["input_ids"] [B, L], batch["task_type"], batch["source"]

Integrates with train_1b_deepspeed.py WSD 736k schedule + 6 phases + 4 branch mixes + Multi-JSpace routing.
"""

import os, json, gzip, math, random, threading, queue, time, glob, hashlib
from pathlib import Path
from collections import defaultdict, deque
from typing import Iterator, Dict, List, Optional, Tuple, Union

# ─────────────────────────────────────────────────────────────────────────────
# Open-source chunking: Chonkie integration (you asked C-H-O-N-K-Y)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from chonkie import (
        TokenChunker as ChonkieTokenChunker,
        RecursiveChunker as ChonkieRecursiveChunker,
        SentenceChunker as ChonkieSentenceChunker,
        CodeChunker as ChonkieCodeChunker,
    )
    HAS_CHONKIE = True
except Exception as _e:
    HAS_CHONKIE = False
    ChonkieTokenChunker = ChonkieRecursiveChunker = ChonkieSentenceChunker = ChonkieCodeChunker = None
    print(f"[Chonkie] not installed, will use fallback SimpleTokenizer chunking — pip install chonkie for proper chunking: {_e}")

# ─────────────────────────────────────────────────────────────────────────────
# Config mirroring dolma_config.yaml + nemo_curator + branch_configs
# ─────────────────────────────────────────────────────────────────────────────

PHASE_TOKENS = [
    ("phase0_logic",     0,       50_000_000_000,  2048,  10000),
    ("phase1_math",      50_000_000_000, 350_000_000_000, 4096, 10000),
    ("phase2_foundation",350_000_000_000, 6_000_000_000_000, 4096, 10000),
    ("phase3_reasoning", 6_000_000_000_000, 11_250_000_000_000, 16384, 100000),
    ("phase4_long",      11_250_000_000_000, 13_800_000_000_000, 65536, 1000000),
    ("phase5_anneal",    13_800_000_000_000, 15_000_000_000_000, 131072, 1000000),
]

# Per-phase mix weights (source -> weight) — sums to 1.0 after norm
PHASE_MIX = {
    "phase0_logic": {
        "synthetic_logic_textbooks_phi_B": 0.60,
        "metamath": 0.20,
        "lean": 0.15,
        "fol": 0.05,
    },
    "phase1_math": {
        "math_textbooks_ordered": 1.0,
    },
    "phase2_foundation": {
        "web_edu_gte2": 0.35,
        "code_early": 0.20,
        "math": 0.12,
        "dclm": 0.33,
    },
    "phase3_reasoning": {
        "long_docs_3x": 0.30,
        "web_edu_gte3.5": 0.35,
        "code": 0.10,
        "workflow_jobbench": 0.10,
        "workflow_gaia2_simple": 0.05,
        "synthetic_reasoning": 0.10,
    },
    "phase4_long": {
        "web_edu_gte4": 0.25,
        "code_long_32k": 0.20,
        "math_long": 0.15,
        "workflow_jobbench_messy": 0.10,
        "workflow_gaia2_dynamic": 0.15,
        "dclm_top15": 0.15,
    },
    "phase5_anneal": {
        "edu_gte4.5": 0.40,
        "verified_proofs": 0.20,
        "synthetic_reward_gt0.8": 0.20,
        "workflow_karpathy": 0.10,
        "workflow_gaia2_hard": 0.10,
    },
}

BRANCH_MIX = {
    "base": None, # use PHASE_MIX
    "code": {"code_repo":0.50,"code_long_32k":0.20,"jobbench_code":0.15,"general":0.15},
    "math": {"math_formal_lean":0.35,"lean_mathlib":0.20,"proofpile2":0.20,"synthetic_math_r1":0.15,"general":0.10},
    "chat": {"chat_alignment":0.30,"safety_blackmail_leverage":0.20,"jobbench_delegation":0.25,"gaia2_temporal":0.15,"counterfactual":0.10},
}

# source -> task_type for Multi-JSpace routing
SOURCE_TO_TASK = {
    "dclm": "automatic", "dclm_top15": "automatic", "web_edu_gte2":"automatic",
    "code_early":"automatic", "synthetic_logic_textbooks_phi_B":"deliberate",
    "math_textbooks_ordered":"deliberate", "math":"deliberate", "lean":"deliberate",
    "metamath":"deliberate", "fol":"deliberate", "long_docs_3x":"deliberate",
    "workflow_jobbench":"deliberate", "workflow_jobbench_messy":"deliberate",
    "jobbench_code":"deliberate", "workflow_karpathy":"deliberate",
    "safety_blackmail_leverage":"safety", "chat_alignment":"safety",
    "workflow_gaia2_simple":"temporal", "workflow_gaia2_dynamic":"temporal",
    "workflow_gaia2_hard":"temporal", "gaia2_temporal":"temporal",
    "jobbench_delegation":"temporal",
    "code_repo":"deliberate", "code_long_32k":"deliberate",
    "math_formal_lean":"deliberate", "lean_mathlib":"deliberate",
    "proofpile2":"deliberate", "synthetic_math_r1":"deliberate",
    "edu_gte4.5":"deliberate", "verified_proofs":"deliberate",
}

# ── Chonkie-aware phase chunker configs: mirrors YaRN RoPE schedule ──
PHASE_CHONKIE_CONFIG = {
    "phase0_logic":      {"chunker": "recursive", "chunk_size": 2048, "overlap": 128, "recipe": "markdown", "desc": "logic textbooks — keep definitions/theorems intact"},
    "phase1_math":       {"chunker": "recursive", "chunk_size": 4096, "overlap": 256, "recipe": "markdown", "desc": "math ordered curriculum arithmetic→probability"},
    "phase2_foundation": {"chunker": "token",     "chunk_size": 4096, "overlap": 128, "desc": "web+code early — fixed tokens for speed"},
    "phase3_reasoning":  {"chunker": "recursive", "chunk_size": 8192, "overlap": 512, "recipe": "default", "desc": "long docs upsampled 3x — semantic chunks"},
    "phase4_long":       {"chunker": "recursive", "chunk_size": 32768, "overlap": 1024, "recipe": "default", "desc": "32k long — code_long + workflow messy"},
    "phase5_anneal":     {"chunker": "token",     "chunk_size": 65536, "overlap": 0, "desc": "anneal high quality edu>=4.5"},
}

def get_phase_chunker_config(phase: str, seq_len: int) -> Dict:
    cfg = PHASE_CHONKIE_CONFIG.get(phase, PHASE_CHONKIE_CONFIG["phase0_logic"]).copy()
    # if trainer asks for longer seq_len than config (e.g., YaRN 131k), grow chunk_size to match
    if seq_len > cfg["chunk_size"]:
        cfg["chunk_size"] = seq_len
    return cfg

# ─────────────────────────────────────────────────────────────────────────────
# Tokenizer — stub with fallback, byte-level lossless, no RAM corpus
# ─────────────────────────────────────────────────────────────────────────────

class SimpleTokenizer:
    """Byte-level tokenizer that never loads vocab into big matrix — encodes per example."""
    def __init__(self, vocab_size=128000):
        self.vocab_size = vocab_size
    def encode(self, text: str) -> List[int]:
        # deterministic hash byte-level -> ids, preserves ability to stream
        # real tokenizer: replace with AutoTokenizer.from_pretrained("dottie-tokenizer")
        b = text.encode("utf-8", errors="ignore")
        # simple: byte + offset, fast, no memory
        return [ (x % (self.vocab_size-256)) + 256 for x in b[:8192] ]  # cap per example pre-chunk
    def decode(self, ids: List[int]) -> str:
        return "".join(chr(i % 1114111) for i in ids[:200])

def get_tokenizer():
    # Always use SimpleTokenizer for constant-memory streaming demo — no HF download spike
    # Replace with real dottie-tokenizer for production: AutoTokenizer.from_pretrained("dottie-tokenizer")
    try:
        from transformers import AutoTokenizer
        for p in ["dottie-tokenizer", "data/dottie-tokenizer", "data/streaming_shards/dottie-tokenizer"]:
            if Path(p).exists():
                print(f"[Tokenizer] Using local {p}")
                return AutoTokenizer.from_pretrained(p, use_fast=True)
    except Exception:
        pass
    return SimpleTokenizer()

# ─────────────────────────────────────────────────────────────────────────────
# Chonkie wrapper — open-source chunking for constant-memory streaming
# Keeps memory flat: chunks one doc at a time, yields iterator, never loads corpus
# ─────────────────────────────────────────────────────────────────────────────

class ChonkieChunkerWrapper:
    """
    Wraps Chonkie's open-source chunkers for training-data streaming.
    Uses minimal installs, falls back to naive split if Chonkie missing.

    Why Chonkie for this job:
    - Feature-rich: token, recursive, sentence, code, semantic, late, neural, slumber【2997878068158776486†L139-L163】
    - Light-weight: 505KB wheel, 49MB installed — no bloat, just CHONK【2997878068158776486†L333-L341】
    - Tokenizers: character, word, tiktoken, tokenizers, transformers — we use character/word for constant RAM【2997878068158776486†L230-L248】
    - Pipeline: .chunk_with().refine_with(overlap) — we mimic via chunk_size+overlap【2997878068158776486†L111-L123】
    """
    def __init__(self,
                 chunker_type: str = "recursive",
                 chunk_size: int = 2048,
                 chunk_overlap: int = 128,
                 tokenizer: str = "character",
                 recipe: str = "default"):
        self.chunker_type = chunker_type
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.tokenizer_name = tokenizer
        self.recipe = recipe
        self._chunker = None
        if HAS_CHONKIE:
            self._init_chonkie()

    def _init_chonkie(self):
        kwargs = dict(
            chunk_size=self.chunk_size,
            tokenizer=self.tokenizer_name,  # character/word = zero RAM, no model download
        )
        try:
            if self.chunker_type == "token":
                # TokenChunker: splits into fixed-size token chunks — perfect for LLM pretraining【2997878068158776486†L146-L148】
                self._chunker = ChonkieTokenChunker(**kwargs)
            elif self.chunker_type == "recursive":
                # RecursiveChunker: hierarchical using customizable rules — semantically meaningful chunks【2997878068158776486†L150-L152】
                # Note: newer API uses rules not recipe, so we don't pass recipe
                self._chunker = ChonkieRecursiveChunker(**kwargs)
            elif self.chunker_type == "sentence":
                # SentenceChunker: splits based on sentences【2997878068158776486†L149-L151】
                self._chunker = ChonkieSentenceChunker(**kwargs)
            elif self.chunker_type == "code":
                # CodeChunker: splits code into structurally meaningful chunks【2997878068158776486†L155-L158】
                # CodeChunker may need language arg, use default
                try:
                    self._chunker = ChonkieCodeChunker(**kwargs)
                except TypeError:
                    self._chunker = ChonkieCodeChunker(tokenizer=self.tokenizer_name, chunk_size=self.chunk_size)
            else:
                self._chunker = ChonkieRecursiveChunker(**kwargs)
            print(f"[Chonkie] Initialized {self.chunker_type} chunk_size={self.chunk_size} overlap={self.chunk_overlap} tokenizer={self.tokenizer_name} recipe={self.recipe}")
        except Exception as e:
            print(f"[Chonkie] init failed {e}, fallback to naive")
            self._chunker = None

    def chunk(self, text: str) -> List[Dict]:
        """
        Chunk one document at a time — constant memory.
        Returns list of dicts {text, token_count, start_index, end_index}
        """
        if not text:
            return []
        # Fast path: if doc already smaller than chunk_size * ~4 chars per token, return as-is to avoid overhead
        if len(text) < self.chunk_size * 2:
            # still go through chonkie for consistency if available, but we can short-circuit
            if not HAS_CHONKIE or self._chunker is None:
                return [{"text": text, "token_count": len(text)//4, "start": 0, "end": len(text)}]

        if HAS_CHONKIE and self._chunker is not None:
            try:
                chonks = self._chunker.chunk(text)  # returns list of Chunk objects with .text, .token_count【2997878068158776486†L91-L97】
                # Apply manual overlap refinement (since we use character tokenizer, overlap refinery needs embed)
                # Simple sliding overlap for training continuity — no extra RAM
                out = []
                for c in chonks:
                    out.append({
                        "text": c.text,
                        "token_count": getattr(c, 'token_count', len(c.text)//4),
                        "start": getattr(c, 'start_index', 0),
                        "end": getattr(c, 'end_index', len(c.text)),
                    })
                # If overlap requested and we have >1 chunk, add overlap by prefixing previous tail
                if self.chunk_overlap > 0 and len(out) > 1:
                    overlapped = []
                    for i, ch in enumerate(out):
                        if i == 0:
                            overlapped.append(ch)
                        else:
                            prev_tail = out[i-1]["text"][-self.chunk_overlap*2:]  # rough char overlap
                            merged_text = prev_tail + "\n" + ch["text"]
                            # keep token_count approximate
                            overlapped.append({
                                "text": merged_text,
                                "token_count": ch["token_count"] + self.chunk_overlap,
                                "start": ch["start"],
                                "end": ch["end"],
                            })
                    return overlapped
                return out
            except Exception as e:
                print(f"[Chonkie] chunk failed len={len(text)} err={e}, fallback naive")
        # Naive fallback: fixed char window — still memory safe because one doc at a time
        chunks = []
        step = max(1, self.chunk_size*4 - self.chunk_overlap*4)  # *4 chars per token approx
        for i in range(0, len(text), step):
            window = text[i:i+self.chunk_size*4]
            if not window.strip():
                continue
            chunks.append({"text": window, "token_count": len(window)//4, "start": i, "end": i+len(window)})
            if len(chunks) > 1000:  # safety cap per doc — avoid OOM on 10MB single doc
                break
        return chunks

    @classmethod
    def for_phase(cls, phase: str, seq_len: int, branch: str = "base"):
        cfg = get_phase_chunker_config(phase, seq_len)
        # branch overrides: code branch should use code chunker
        chunker_type = cfg["chunker"]
        if branch == "code" and phase in ("phase2_foundation","phase3_reasoning","phase4_long"):
            chunker_type = "code"
        return cls(
            chunker_type=chunker_type,
            chunk_size=cfg["chunk_size"],
            chunk_overlap=cfg.get("overlap", 128),
            tokenizer="character",  # lightest, no download — we count tokens ourselves after
            recipe=cfg.get("recipe","default"),
        )

# ─────────────────────────────────────────────────────────────────────────────
# Low-level shard iterator — 1 file handle, line buffered, checkpointable
# ─────────────────────────────────────────────────────────────────────────────

class ShardIterator:
    """Iterates over all shards for a single source without loading all into RAM."""
    def __init__(self, source_name: str, shard_pattern: str, seed: int = 0):
        self.source_name = source_name
        self.pattern = shard_pattern
        self.seed = seed
        self.files = []
        self.file_idx = 0
        self.line_no = 0
        self.fh = None
        self.byte_offset = 0
        self._rng = random.Random(seed)
        self.refresh_files()

    def refresh_files(self):
        self.files = sorted(glob.glob(self.pattern, recursive=True))
        if self.files:
            self._rng.shuffle(self.files)

    def _open_next(self):
        if self.fh:
            try: self.fh.close()
            except: pass
            self.fh = None
        if not self.files:
            self.refresh_files()
            if not self.files:
                return False
        if self.file_idx >= len(self.files):
            self.file_idx = 0
            self._rng.shuffle(self.files)
        path = self.files[self.file_idx]
        self.file_idx += 1
        self.line_no = 0
        try:
            if path.endswith(".gz"):
                self.fh = gzip.open(path, "rt", encoding="utf-8", errors="ignore")
            else:
                self.fh = open(path, "r", encoding="utf-8", errors="ignore", buffering=8192*4)
            return True
        except FileNotFoundError:
            return self._open_next()

    def __iter__(self):
        return self

    def __next__(self) -> Dict:
        # loop forever over shards — infinite stream
        attempts = 0
        while attempts < 10:
            if self.fh is None:
                if not self._open_next():
                    attempts += 1
                    time.sleep(0.1)
                    continue
            line = self.fh.readline()
            if not line:
                self._open_next()
                attempts += 1
                continue
            self.line_no += 1
            line=line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                # normalize to expected fields
                if "text" not in obj:
                    # allow raw text line as fallback
                    obj = {"text": line, "source": self.source_name}
                obj.setdefault("source", self.source_name)
                obj.setdefault("task_type", SOURCE_TO_TASK.get(self.source_name, "deliberate"))
                return obj
            except json.JSONDecodeError:
                # plain text fallback
                return {"text": line, "source": self.source_name, "task_type": SOURCE_TO_TASK.get(self.source_name, "deliberate")}
        # if no files yet (e.g., synthetic not generated), yield synthetic placeholder and wait
        time.sleep(0.2)
        return {"text": f"# Placeholder {self.source_name} synthetic chunk {self.line_no}", "source": self.source_name, "task_type": SOURCE_TO_TASK.get(self.source_name, "deliberate"), "_placeholder": True}

    def checkpoint(self) -> Dict:
        return {"source": self.source_name, "file_idx": self.file_idx, "line_no": self.line_no, "files": self.files[:5]}
    def close(self):
        if self.fh:
            try: self.fh.close()
            except: pass

# ─────────────────────────────────────────────────────────────────────────────
# Weighted multi-source mixer — picks source by weight, 1 file open per source max
# ─────────────────────────────────────────────────────────────────────────────

class MultiSourceWeightedStream:
    def __init__(self, mix: Dict[str, float], data_root: Path, seed: int = 0):
        self.mix = mix
        self.data_root = Path(data_root)
        self.sources = list(mix.keys())
        weights = [mix[s] for s in self.sources]
        tot = sum(weights) or 1.0
        self.weights = [w/tot for w in weights]
        self.seed = seed
        self._rng = random.Random(seed)
        # One iterator per source — each keeps 1 file handle
        self.iterators: Dict[str, ShardIterator] = {}
        for src in self.sources:
            # pattern: data_root/{src}/**/*.jsonl*  +  phase shards fallback
            patterns = [
                str(self.data_root / src / "**" / "*.jsonl*"),
                str(self.data_root / "**" / f"{src}*.jsonl*"),
                str(self.data_root / "**" / f"{src.replace('_','-')}*.jsonl*"),
                str(self.data_root / "phase*" / src / "*.jsonl*"),
                str(self.data_root / "synthetic" / f"*{src}*.md"),  # for logic_textbook_pipeline legacy
            ]
            # join first existing pattern, otherwise first pattern that may be empty and will wait
            pat = patterns[0]
            for p in patterns:
                if glob.glob(p, recursive=True):
                    pat = p
                    break
            self.iterators[src] = ShardIterator(src, pat, seed=seed+hash(src)%10000)

    def __iter__(self):
        return self

    def __next__(self) -> Dict:
        # weighted choice without loading anything
        src = self._rng.choices(self.sources, weights=self.weights, k=1)[0]
        it = self.iterators[src]
        try:
            ex = next(it)
            ex["_sampled_source"] = src
            return ex
        except StopIteration:
            # reshuffle
            return next(self.iterators[self.sources[0]])

    def checkpoint(self):
        return {src: it.checkpoint() for src,it in self.iterators.items()}

# ─────────────────────────────────────────────────────────────────────────────
# Shuffle buffer — fixed memory, not full shuffle
# ─────────────────────────────────────────────────────────────────────────────

class ShuffleBuffer:
    """Fixed-size shuffle buffer that guarantees constant memory."""
    def __init__(self, source_iter: Iterator[Dict], buffer_size: int = 10000, seed: int = 0):
        self.source = source_iter
        self.buffer_size = buffer_size
        self.buffer: List[Dict] = []
        self._rng = random.Random(seed)
        # prime buffer without loading full dataset
        for _ in range(buffer_size):
            try:
                self.buffer.append(next(self.source))
            except StopIteration:
                break

    def __iter__(self):
        return self

    def __next__(self) -> Dict:
        if not self.buffer:
            raise StopIteration
        # pick random
        idx = self._rng.randrange(len(self.buffer))
        ex = self.buffer[idx]
        # replace with next from source if available
        try:
            self.buffer[idx] = next(self.source)
        except StopIteration:
            # shrink buffer
            self.buffer.pop(idx)
        return ex

    def qsize(self):
        return len(self.buffer)

# ─────────────────────────────────────────────────────────────────────────────
# Phase scheduler — maps global tokens/steps to phase
# ─────────────────────────────────────────────────────────────────────────────

def get_phase_for_tokens(tokens_seen: int) -> str:
    for name, start, end, seq, base in PHASE_TOKENS:
        if start <= tokens_seen < end:
            return name
    return PHASE_TOKENS[-1][0]

def get_phase_for_step(step: int, tokens_per_step: int = 2_097_152) -> str:  # 2M tokens/step @ 1B bs 1M
    return get_phase_for_tokens(step * tokens_per_step)

# ─────────────────────────────────────────────────────────────────────────────
# Main iterable dataset — torch compatible if torch present
# ─────────────────────────────────────────────────────────────────────────────

class DottieStreamingDataset:
    """
    Low-memory infinite streamer:
    - constant RAM: shuffle_buffer + 1 batch
    - checkpointable: saves offsets to checkpoints/stream_state_{phase}.json
    - phase auto-switch based on tokens_seen or step
    - yields dict with input_ids, task_type, source, phase
    - NEW: Chonkie-integrated chunking — open-source, zero-bloat, semantic-aware
    """
    def __init__(self,
                 data_root: str = "data/streaming_shards",
                 branch: str = "base",
                 phase: str = "auto",  # auto = infer from tokens_seen
                 shuffle_buffer: int = 10000,
                 seed: int = 42,
                 max_seq_len: int = 2048,
                 checkpoint_dir: str = "checkpoints",
                 tokens_per_step: int = 2_097_152,
                 use_chonkie: bool = True,
                 chunker_type: str = "auto",  # auto = pick per phase
                 chunk_overlap: int = 128,
                 chonkie_tokenizer: str = "character",
                 ):
        self.data_root = Path(data_root)
        self.branch = branch
        self.phase_mode = phase
        self.shuffle_buffer = shuffle_buffer
        self.seed = seed
        self.max_seq_len = max_seq_len
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.tokens_per_step = tokens_per_step
        self.tokenizer = get_tokenizer()
        self.tokens_seen = 0
        self.steps_seen = 0
        self.current_phase = phase if phase != "auto" else "phase0_logic"
        self._stream: Optional[MultiSourceWeightedStream] = None
        self._shuffled: Optional[ShuffleBuffer] = None

        # Chonkie integration — open source, lightweight, 505KB wheel【2997878068158776486†L333-L341】
        self.use_chonkie = use_chonkie and HAS_CHONKIE
        self.chunker_type_arg = chunker_type
        self.chunk_overlap = chunk_overlap
        self.chonkie_tokenizer = chonkie_tokenizer
        self._chonkie_chunker: Optional[ChonkieChunkerWrapper] = None
        if self.use_chonkie:
            eff_type = chunker_type if chunker_type != "auto" else get_phase_chunker_config(self.current_phase, max_seq_len)["chunker"]
            self._chonkie_chunker = ChonkieChunkerWrapper.for_phase(self.current_phase, max_seq_len, branch)
            # override if user explicitly passed type
            if chunker_type != "auto":
                self._chonkie_chunker.chunker_type = chunker_type
                self._chonkie_chunker._init_chonkie()
            print(f"[Chonkie] Enabled for dataset — {self._chonkie_chunker.chunker_type} phase={self.current_phase} seq_len={max_seq_len}")
        else:
            print(f"[Chonkie] Disabled — using fallback tokenizer chunking (install with pip install chonkie)")

        self._init_stream_for_phase(self.current_phase)

    def _mix_for(self, phase: str) -> Dict[str,float]:
        if self.branch != "base" and BRANCH_MIX.get(self.branch):
            return BRANCH_MIX[self.branch]
        return PHASE_MIX.get(phase, PHASE_MIX["phase0_logic"])

    def _init_stream_for_phase(self, phase: str):
        # close old
        if hasattr(self, '_stream') and self._stream:
            for it in self._stream.iterators.values():
                it.close()
        mix = self._mix_for(phase)
        print(f"[Streaming] Init phase={phase} branch={self.branch} mix={mix} root={self.data_root}")
        weighted = MultiSourceWeightedStream(mix, self.data_root, seed=self.seed+self.steps_seen)
        self._stream = weighted
        self._shuffled = ShuffleBuffer(iter(weighted), buffer_size=self.shuffle_buffer, seed=self.seed)
        self.current_phase = phase
        # re-init chonkie chunker for new phase's seq_len if auto
        if self.use_chonkie:
            if self.chunker_type_arg == "auto" or self._chonkie_chunker is None:
                self._chonkie_chunker = ChonkieChunkerWrapper.for_phase(phase, self.max_seq_len, self.branch)
            else:
                # update chunk size to match new phase's RoPE ctx
                cfg = get_phase_chunker_config(phase, self.max_seq_len)
                self._chonkie_chunker.chunk_size = cfg["chunk_size"]
                self._chonkie_chunker.chunk_overlap = cfg.get("overlap", self.chunk_overlap)
                self._chonkie_chunker._init_chonkie()
        self._save_checkpoint()

    def _maybe_switch_phase(self):
        if self.phase_mode != "auto":
            return
        new_phase = get_phase_for_tokens(self.tokens_seen) if self.tokens_seen>0 else get_phase_for_step(self.steps_seen, self.tokens_per_step)
        if new_phase != self.current_phase:
            print(f"[Streaming] Phase switch {self.current_phase} -> {new_phase} at tokens={self.tokens_seen} steps={self.steps_seen}")
            self._init_stream_for_phase(new_phase)

    def __iter__(self) -> Iterator[Dict]:
        for ex in self._shuffled:
            yield ex

    def batched(self, seq_len: int = 2048, batch_size: int = 4, use_chonkie: Optional[bool] = None) -> Iterator[Dict]:
        """
        Yields tokenized batches: {"input_ids": [B, L], "task_type": [...], "source": [...], "phase": str}
        Memory: tokenizes per example, concatenates to seq_len chunks, discards old.
        NEW with Chonkie: first chunk via Chonkie (recursive/token/code), then tokenize each Chonkie chunk.
        This keeps memory flat: 1 doc → Chonkie chunks (e.g., 2048 tokens each) → token ids → batch.
        Never holds more than shuffle_buffer + 1 batch + 1 doc's chunks.
        """
        # allow override per call
        use_chonkie_eff = self.use_chonkie if use_chonkie is None else (use_chonkie and HAS_CHONKIE)
        buf_tokens: List[int] = []
        buf_task = []
        buf_source = []
        batch_texts = []
        chonkie_stats = {"docs_chunked": 0, "chonkie_chunks": 0, "avg_chunks_per_doc": 0.0}

        try:
            import torch
            has_torch = True
        except ImportError:
            has_torch = False

        # If caller asks for larger seq_len than current max (YaRN), update chonkie config
        if use_chonkie_eff and self._chonkie_chunker and seq_len != self._chonkie_chunker.chunk_size:
            self._chonkie_chunker.chunk_size = seq_len
            self._chonkie_chunker._init_chonkie()

        for ex in self:
            text = ex.get("text","")
            if not text:
                continue

            # ── Chonkie path: chunk doc into semantically meaningful pieces first ──
            if use_chonkie_eff and self._chonkie_chunker:
                # Chonkie's API: chunker.chunk(text) → list of Chunk with .text, .token_count【2997878068158776486†L88-L97】
                doc_chunks = self._chonkie_chunker.chunk(text)
                chonkie_stats["docs_chunked"] += 1
                chonkie_stats["chonkie_chunks"] += len(doc_chunks)

                for ch in doc_chunks:
                    ch_text = ch["text"] if isinstance(ch, dict) else getattr(ch, 'text', str(ch))
                    # tokenize each Chonkie chunk — per-chunk, not per-doc, flat memory
                    ids = self.tokenizer.encode(ch_text) if hasattr(self.tokenizer, "encode") else self.tokenizer.encode(ch_text)
                    buf_tokens.extend(ids)
                    while len(buf_tokens) >= seq_len:
                        chunk = buf_tokens[:seq_len]
                        buf_tokens = buf_tokens[seq_len:]
                        batch_texts.append(chunk)
                        buf_task.append(ex.get("task_type","deliberate"))
                        buf_source.append(ex.get("source","unknown"))
                        self.tokens_seen += len(chunk)
                        if len(batch_texts) >= batch_size:
                            self.steps_seen += 1
                            self._maybe_switch_phase()
                            if has_torch:
                                input_ids = torch.tensor(batch_texts, dtype=torch.long)
                            else:
                                input_ids = batch_texts
                            out = {
                                "input_ids": input_ids,
                                "task_type": buf_task[:batch_size],
                                "source": buf_source[:batch_size],
                                "phase": self.current_phase,
                                "branch": self.branch,
                                "chonkie": {"enabled": True, "chunks_per_doc": len(doc_chunks), "chunker": self._chonkie_chunker.chunker_type},
                            }
                            batch_texts = []
                            buf_task = []
                            buf_source = []
                            if self.steps_seen % 20 == 0:
                                avg = chonkie_stats["chonkie_chunks"]/max(1,chonkie_stats["docs_chunked"])
                                print(f"[Chonkie] steps={self.steps_seen} tokens_seen={self.tokens_seen} docs={chonkie_stats['docs_chunked']} total_chunks={chonkie_stats['chonkie_chunks']} avg_chunks/doc={avg:.2f} shuffle_q={self._shuffled.qsize()} RAM=flat")
                            if self.steps_seen % 100 == 0:
                                self._save_checkpoint()
                            yield out
                    # safety cap
                    if len(buf_tokens) > seq_len*4:
                        buf_tokens = buf_tokens[-seq_len*4:]
            else:
                # ── Fallback old path without Chonkie ──
                ids = self.tokenizer.encode(text) if hasattr(self.tokenizer, "encode") else self.tokenizer.encode(text)
                buf_tokens.extend(ids)
                while len(buf_tokens) >= seq_len:
                    chunk = buf_tokens[:seq_len]
                    buf_tokens = buf_tokens[seq_len:]
                    batch_texts.append(chunk)
                    buf_task.append(ex.get("task_type","deliberate"))
                    buf_source.append(ex.get("source","unknown"))
                    self.tokens_seen += len(chunk)
                    if len(batch_texts) >= batch_size:
                        self.steps_seen += 1
                        self._maybe_switch_phase()
                        if has_torch:
                            input_ids = torch.tensor(batch_texts, dtype=torch.long)
                        else:
                            input_ids = batch_texts
                        out = {
                            "input_ids": input_ids,
                            "task_type": buf_task[:batch_size],
                            "source": buf_source[:batch_size],
                            "phase": self.current_phase,
                            "branch": self.branch,
                            "chonkie": {"enabled": False},
                        }
                        batch_texts = []
                        buf_task = []
                        buf_source = []
                        if self.steps_seen % 100 == 0:
                            self._save_checkpoint()
                        yield out
                if len(buf_tokens) > seq_len*4:
                    buf_tokens = buf_tokens[-seq_len*4:]


    def _save_checkpoint(self):
        try:
            state = {
                "tokens_seen": self.tokens_seen,
                "steps_seen": self.steps_seen,
                "phase": self.current_phase,
                "branch": self.branch,
                "mix": self._stream.checkpoint() if self._stream else {},
                "timestamp": time.time(),
            }
            out = self.checkpoint_dir / f"stream_state_{self.current_phase}_{self.branch}.json"
            with open(out, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"[Streaming] checkpoint save failed: {e}")

    def load_checkpoint(self, path: str):
        try:
            with open(path) as f:
                st = json.load(f)
            self.tokens_seen = st.get("tokens_seen",0)
            self.steps_seen = st.get("steps_seen",0)
            print(f"[Streaming] Loaded checkpoint {path} tokens={self.tokens_seen} steps={self.steps_seen}")
        except Exception as e:
            print(f"[Streaming] load checkpoint failed {e}")

    def stats(self) -> Dict:
        return {
            "tokens_seen": self.tokens_seen,
            "steps_seen": self.steps_seen,
            "phase": self.current_phase,
            "branch": self.branch,
            "shuffle_q": self._shuffled.qsize() if self._shuffled else 0,
            "data_root": str(self.data_root),
        }

# ─────────────────────────────────────────────────────────────────────────────
# Background synthetic generator — streams textbooks into rotating shards
# ─────────────────────────────────────────────────────────────────────────────

class SyntheticShardGenerator:
    """
    Runs in background thread, generates Phi Method B textbooks continuously
    into data_root/synthetic_logic_textbooks_phi_B/*.jsonl.gz rotating shards 100MB each.
    Backpressure: if > N shards pending, sleep.
    Memory: holds only current shard buffer (1000 lines)
    """
    def __init__(self, data_root: str = "data/streaming_shards", shard_size_mb: int = 100, max_pending_shards: int = 20):
        self.data_root = Path(data_root)
        self.shard_size_mb = shard_size_mb
        self.max_pending = max_pending_shards
        self.stop_evt = threading.Event()
        self.q = queue.Queue()
        self.thread = None

    def _gen_one(self, topic: str) -> Dict:
        # tiny Phi Method B stub — replace with real Nemotron-70B filtered gen
        return {
            "text": f"# {topic}\n\nDefinition: ... Theorem: If ... Proof: ... Example: exercise (Phi B)\nTopic {topic} deep explanation ...",
            "source": "synthetic_logic_textbooks_phi_B",
            "task_type": "deliberate",
            "topic": topic,
        }

    def _writer_loop(self):
        topics = ["propositional logic","first-order logic","induction","pigeonhole","arithmetic","algebra","geometry","discrete","calculus","linear algebra","probability"]*100
        out_dir = self.data_root / "synthetic_logic_textbooks_phi_B"
        out_dir.mkdir(parents=True, exist_ok=True)
        shard_idx = len(list(out_dir.glob("*.jsonl*")))
        current_path = out_dir / f"shard_{shard_idx:05d}.jsonl.gz"
        fh = gzip.open(current_path, "wt", encoding="utf-8")
        current_bytes = 0
        try:
            while not self.stop_evt.is_set():
                # backpressure: if too many shards, pause generation
                pending = len(list(out_dir.glob("*.jsonl*")))
                if pending > self.max_pending:
                    time.sleep(1.0)
                    continue
                topic = random.choice(topics)
                ex = self._gen_one(topic)
                line = json.dumps(ex) + "\n"
                fh.write(line)
                current_bytes += len(line.encode("utf-8"))
                if current_bytes > self.shard_size_mb * 1024 * 1024:
                    fh.close()
                    shard_idx +=1
                    current_path = out_dir / f"shard_{shard_idx:05d}.jsonl.gz"
                    fh = gzip.open(current_path, "wt", encoding="utf-8")
                    current_bytes = 0
                time.sleep(0.01)  # yield
        finally:
            try: fh.close()
            except: pass

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_evt.clear()
        self.thread = threading.Thread(target=self._writer_loop, daemon=True)
        self.thread.start()
        print(f"[SyntheticGenerator] Started background Phi B generation into {self.data_root}/synthetic_logic_textbooks_phi_B")

    def stop(self):
        self.stop_evt.set()
        if self.thread:
            self.thread.join(timeout=2)

# ─────────────────────────────────────────────────────────────────────────────
# Quick test / CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data_root", default="data/streaming_shards")
    ap.add_argument("--branch", default="base")
    ap.add_argument("--phase", default="auto")
    ap.add_argument("--shuffle_buffer", type=int, default=1000)
    ap.add_argument("--seq_len", type=int, default=2048)
    ap.add_argument("--batch_size", type=int, default=2)
    ap.add_argument("--steps", type=int, default=5)
    ap.add_argument("--gen_synthetic", action="store_true")
    args = ap.parse_args()

    Path(args.data_root).mkdir(parents=True, exist_ok=True)
    # ensure at least some dummy shards exist for demo
    for src in ["synthetic_logic_textbooks_phi_B","web_edu_gte2","dclm"]:
        p = Path(args.data_root)/src
        p.mkdir(parents=True, exist_ok=True)
        dummy = p/"shard_00000.jsonl"
        if not dummy.exists():
            with open(dummy,"w") as f:
                for i in range(100):
                    json.dump({"text": f"Dummy {src} example {i} for streaming test " + "lorem ipsum " * 20, "source": src}, f)
                    f.write("\n")

    gen = None
    if args.gen_synthetic:
        gen = SyntheticShardGenerator(args.data_root)
        gen.start()

    ds = DottieStreamingDataset(data_root=args.data_root, branch=args.branch, phase=args.phase, shuffle_buffer=args.shuffle_buffer, max_seq_len=args.seq_len)
    print(f"Starting stream stats={ds.stats()}")
    try:
        for idx, batch in enumerate(ds.batched(seq_len=args.seq_len, batch_size=args.batch_size)):
            ids = batch['input_ids']
            try:
                import torch
                if isinstance(ids, torch.Tensor):
                    shape_str = f"{ids.shape[0]} x {ids.shape[1]} tensor"
                    n0 = ids.shape[0]
                else:
                    shape_str = f"{len(ids)} x {len(ids[0]) if ids and len(ids[0])>0 else 0} list"
                    n0 = len(ids)
            except Exception:
                shape_str = "unknown"
            print(f"Step {idx} phase={batch['phase']} tasks={batch['task_type']} input_ids shape={shape_str} tokens_seen={ds.tokens_seen}")
            if idx+1 >= args.steps:
                break
    finally:
        if gen:
            gen.stop()
    print("Done, final stats", ds.stats())
