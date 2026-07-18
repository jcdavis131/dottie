"""Systems-mechanics probe sets (spec 02 B6 eval side).

Every probe answer is re-derived here from the prompt's OWN numbers with
independent re-implementations (regex-parse the prompt, recompute, compare)
-- deliberately NOT importing the ava.datagen primitives the probe generator
reuses, so a bug there cannot hide. Also guards the decontamination contract:
the probe stems in evals/eval_sets.py SYSTEMS_PROMPTS must never appear in
the ET-CoT training corpora.
"""

from __future__ import annotations

import hashlib
import re

from evals.eval_sets import SYSTEMS_PROMPTS
from evals.probe_items_gen import generate_probe_items, load_items, _PROBE_DIR

_WORD = re.compile(r"\w+")


def _norm(s: str) -> str:
    return " ".join(_WORD.findall(s.lower()))


def _ints(s: str) -> list[int]:
    return [int(x) for x in re.findall(r"-?\d+", s)]


# ---------------------------------------------------------------------------
# independent re-implementations (mirrors test_datagen's _eval_prop pattern)
# ---------------------------------------------------------------------------

def _fnv1a_ref(s: str) -> int:
    h = 2166136261
    for ch in s:
        h = ((h ^ ord(ch)) * 16777619) % 2 ** 32
    return h


class _BTreeRef:
    """Independent CLRS order-4 B-tree (t=2, preemptive splits) -- the same
    published algorithm the generator implements, written from scratch."""

    def __init__(self):
        self.keys: list[int] = []
        self.children: list["_BTreeRef"] = []
        self.root = self

    def _split(self, parent, i):
        child = parent.children[i]
        right = _BTreeRef.__new__(_BTreeRef)
        right.keys, right.children = child.keys[2:], child.children[2:]
        median = child.keys[1]
        child.keys = child.keys[:1]
        if child.children:
            child.children = child.children[:2]
        parent.keys.insert(i, median)
        parent.children.insert(i + 1, right)

    def insert(self, key):
        if len(self.root.keys) == 3:
            new_root = _BTreeRef.__new__(_BTreeRef)
            new_root.keys, new_root.children = [], [self.root]
            self._split(new_root, 0)
            self.root = new_root
        node = self.root
        while node.children:
            i = sum(1 for k in node.keys if key > k)
            if len(node.children[i].keys) == 3:
                self._split(node, i)
                if key > node.keys[i]:
                    i += 1
            node = node.children[i]
        node.keys.append(key)
        node.keys.sort()

    def height(self):
        h, node = 1, self.root
        while node.children:
            h += 1
            node = node.children[0]
        return h


def _huffman_ref(freqs: dict[str, int]) -> dict[str, str]:
    nodes = [(f, i, s, None, None) for i, (s, f) in enumerate(sorted(freqs.items()))]
    nid = len(nodes)
    while len(nodes) > 1:
        nodes.sort(key=lambda t: (t[0], t[1]))
        a, b = nodes[0], nodes[1]
        nodes = nodes[2:] + [(a[0] + b[0], nid, None, a, b)]
        nid += 1
    codes = {}

    def walk(node, prefix):
        _, _, sym, left, right = node
        if sym is not None:
            codes[sym] = prefix or "0"
        else:
            walk(left, prefix + "0")
            walk(right, prefix + "1")

    walk(nodes[0], "")
    return codes


def _lz77_ref(data: str, window=16, lookahead=8, min_match=2):
    out, i = [], 0
    while i < len(data):
        best_len, best_off = 0, 0
        max_len = min(lookahead, len(data) - i - 1)
        for off in range(1, min(i, window) + 1):
            length = 0
            while length < max_len and data[i - off + length] == data[i + length]:
                length += 1
            if length > best_len:
                best_len, best_off = length, off
        if best_len >= min_match:
            out.append((best_off, best_len, data[i + best_len]))
            i += best_len + 1
        else:
            out.append((0, 0, data[i]))
            i += 1
    return out


def _varint_ref(x: int) -> list[int]:
    out = []
    while True:
        b = x & 0x7F
        x >>= 7
        if x:
            out.append(b | 0x80)
        else:
            out.append(b)
            return out


# ---------------------------------------------------------------------------
# generation determinism + probe answer re-verification
# ---------------------------------------------------------------------------

def test_probe_generation_is_deterministic():
    generate_probe_items()
    h1 = {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
          for f in sorted(_PROBE_DIR.glob("*.jsonl"))}
    generate_probe_items()
    h2 = {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
          for f in sorted(_PROBE_DIR.glob("*.jsonl"))}
    assert h1 == h2
    assert {"db_mechanics.jsonl", "compression.jsonl"} <= set(h1)


def test_db_mechanics_probe_answers():
    items = load_items("db_mechanics")
    assert len(items) == 200
    checked = set()
    for it in items:
        p, ans = it["prompt"], it["answer"]
        if "through FNV-1a onto a table of" in p:
            key = re.search(r"key '(\w+)'", p).group(1)
            m = int(re.search(r"table of (\d+) slots", p).group(1))
            assert ans == str(_fnv1a_ref(key) % m)
            checked.add("kv")
        elif "grown from inserting the key sequence" in p:
            seq = p.split("key sequence", 1)[1].split("ends at height", 1)[0]
            keys = _ints(seq)
            tree = _BTreeRef()
            for k in keys:
                tree.insert(k)
            assert ans == str(tree.height())
            checked.add("btree")
        elif "Following breadth-first hops across the edge list" in p:
            edges = [(int(a), int(b)) for a, b in re.findall(r"N(\d+)-N(\d+)", p)]
            target = int(re.search(r"node N(\d+) sits", p).group(1))
            adj = {}
            for a, b in edges:
                adj.setdefault(a, set()).add(b)
                adj.setdefault(b, set()).add(a)
            dist, q = {0: 0}, [0]
            while q:
                u = q.pop(0)
                for v in sorted(adj.get(u, ())):
                    if v not in dist:
                        dist[v] = dist[u] + 1
                        q.append(v)
            assert ans == str(dist[target])
            checked.add("bfs")
        elif "second windows anchored at base" in p:
            stamp = int(re.search(r"stamp (\d+)", p).group(1))
            window = int(re.search(r"(\d+)-second windows", p).group(1))
            base = int(re.search(r"base (\d+)", p).group(1))
            assert ans == str((stamp - base) // window)
            checked.add("ts")
        elif "squared Euclidean gap between vectors" in p:
            a, b = re.findall(r"\[([-\d, ]+)\]", p)
            va, vb = _ints(a), _ints(b)
            assert ans == str(sum((x - y) ** 2 for x, y in zip(va, vb)))
            checked.add("d2")
        elif "the sales block starts at byte" in p:
            rows = int(re.search(r"layout of (\d+) rows", p).group(1))
            assert ans == str(12 * rows)  # 4 (id) + 8 (region) bytes precede sales
            checked.add("col")
        elif "Counting the documents whose age reaches at least" in p:
            min_age = int(re.search(r"at least (\d+)", p).group(1))
            ages = _ints(re.search(r"\[([\d, ]+)\]", p).group(1))
            assert ans == str(sum(a >= min_age for a in ages))
            checked.add("docs")
        else:
            raise AssertionError(f"unrecognized db_mechanics probe: {p!r}")
    assert checked == {"kv", "btree", "bfs", "ts", "d2", "col", "docs"}


def test_compression_probe_answers():
    items = load_items("compression")
    assert len(items) == 200
    checked = set()
    for it in items:
        p, ans = it["prompt"], it["answer"]
        if "into count-byte run pairs yields" in p:
            s = re.search(r"string '([A-D]+)'", p).group(1)
            runs, prev = [], None
            for ch in s:
                if runs and prev == ch:
                    runs[-1][1] += 1
                else:
                    runs.append([ch, 1])
                prev = ch
            assert ans == "".join(f"{k}{c}" for c, k in runs)
            checked.add("rle")
        elif "Packed as a LEB128 varint" in p:
            d = int(re.search(r"delta (\d+)", p).group(1))
            assert ans == " ".join(f"0x{b:02X}" for b in _varint_ref(d))
            checked.add("varint")
        elif "receives a Huffman code of length" in p:
            freqs = {m.group(1): int(m.group(2))
                     for m in re.finditer(r"([a-g]):(\d+)", p)}
            sym = re.search(r"symbol '([a-g])'", p).group(1)
            assert ans == str(len(_huffman_ref(freqs)[sym]))
            checked.add("huffman")
        elif "to int8 symmetrically with scale" in p:
            x = float(re.search(r"Quantizing (-?[\d.]+)", p).group(1))
            scale = float(re.search(r"scale ([\d.]+)", p).group(1))
            assert ans == str(max(-127, min(127, round(x / scale))))
            checked.add("quant")
        elif "tokenizes into this many LZ77 triples" in p:
            s = re.search(r"string '([ab]+)'", p).group(1)
            assert ans == str(len(_lz77_ref(s)))
            checked.add("lz77")
        elif "carries this many bits of information" in p:
            s = re.search(r"string '([ABC]+)'", p).group(1)
            assert ans == str(sum(1 if c == "A" else 2 for c in s))
            checked.add("bits")
        else:
            raise AssertionError(f"unrecognized compression probe: {p!r}")
    assert checked == {"rle", "varint", "huffman", "quant", "lz77", "bits"}


# ---------------------------------------------------------------------------
# decontamination contract: probe stems never appear in training corpora,
# and every stem is long enough for the decontaminator to index (>= 5 words).
# ---------------------------------------------------------------------------

def test_systems_stems_are_indexable():
    from ava.pipeline.decontaminate import MIN_PHRASE_WORDS

    for stem in SYSTEMS_PROMPTS:
        assert len(_WORD.findall(stem.lower())) >= MIN_PHRASE_WORDS, (
            f"stem too short to index: {stem!r}")


def test_systems_stems_absent_from_training_corpora():
    from ava.datagen.compress_trace import CompressTraceGenerator
    from ava.datagen.db_trace import DBTraceGenerator

    stems = [_norm(s) for s in SYSTEMS_PROMPTS]
    for gen_cls in (DBTraceGenerator, CompressTraceGenerator):
        for d in gen_cls(seed=1234).generate(800_000):
            nd = _norm(d["text"])
            for stem in stems:
                assert stem not in nd, (
                    f"{gen_cls.__name__} {d['source']} leaks probe stem {stem!r}")


def test_systems_probes_survive_decontaminator_registration():
    """The decontaminator must index the systems set and flag a doc that
    embeds a probe verbatim, while passing the ET-CoT training phrasing."""
    from ava.pipeline.decontaminate import Decontaminator

    deco = Decontaminator()
    hit, which = deco.is_contaminated(
        "Filler text so the run is realistic. The squared Euclidean gap "
        "between vectors [1, 2] and [4, 6] equals 25. More filler follows.")
    assert hit and which == "systems"
    ok, _ = deco.is_contaminated(
        "### Task: simulate exact k-nearest-neighbour vector search with "
        "metric squared Euclidean distance over the candidate vectors.")
    assert not ok
