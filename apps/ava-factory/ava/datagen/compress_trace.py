"""Phase-2/3/4 compression & information-theory corpus: ET-CoT docs that
trace real compression algorithms state-by-state -- the sliding window of
LZ77, Huffman tree merges and bit assignments, timestamp delta+varint
packing, INT8 quantization scale/zero-point math, and arithmetic coding with
Equal-Info Windows (window-aligned bit flushes that keep the bitstream
learnable instead of opaque).

Every emitted number is computed by actually running the algorithm; every
encoder is round-tripped through its decoder before the doc is yielded, so a
generator bug cannot silently poison a shard.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Iterator

from ava.datagen.base import Generator
from ava.datagen.trace_common import elide, render_etcot, step_lines

# ---------------------------------------------------------------------------
# RLE
# ---------------------------------------------------------------------------

_RLE_ALPHA = "ABCDEFGH"


def _rle_encode(data: str) -> list[tuple[str, int]]:
    runs: list[tuple[str, int]] = []
    for ch in data:
        if runs and runs[-1][0] == ch:
            runs[-1] = (ch, runs[-1][1] + 1)
        else:
            runs.append((ch, 1))
    return runs


def _rle_doc(rng, n: int, elide_over: int):
    runs_in = [(rng.choice(_RLE_ALPHA), rng.randint(1, 9)) for _ in range(n)]
    # merge accidental equal neighbours so the input has exactly n runs
    data_parts: list[str] = []
    prev = None
    for ch, ln in runs_in:
        while ch == prev:
            ch = rng.choice(_RLE_ALPHA)
        data_parts.append(ch * ln)
        prev = ch
    data = "".join(data_parts)

    runs = _rle_encode(data)
    assert "".join(c * k for c, k in runs) == data  # round trip

    raw_steps, states = [], []
    pos = 0
    for ch, ln in runs:
        raw_steps.append(
            f"scan pos {pos}: byte '{ch}' repeats; count forward -> run length {ln}; "
            f"emit pair ({ch},{ln}); pos -> {pos + ln}"
        )
        pos += ln
        states.append(f"pos={pos}, pairs so far={[(c, k) for c, k in runs[: len(states) + 1]]}")
    encoded = "".join(f"{k}{c}" for c, k in runs)
    task = (
        "### Task: simulate run-length encoding (RLE)\n"
        f"Input byte string ({len(data)} bytes):\n"
        f"  {data}\n"
        "Encode as (byte, run-length) pairs, rendered as <count><byte>."
    )
    answer = [
        f"encoded: {encoded}",
        f"pairs: {runs}",
        f"size: {len(data)} bytes -> {len(runs) * 2} pair fields "
        f"(ratio {len(data) / (len(runs) * 2):.2f}x)",
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    return text, "deliberate", "rle_trace", {"data": data, "runs": runs}


# ---------------------------------------------------------------------------
# LZ77
# ---------------------------------------------------------------------------

_LZ_WINDOW = 16
_LZ_LOOKAHEAD = 8
_LZ_MIN_MATCH = 2


def _lz77_encode(data: str) -> list[tuple[int, int, str]]:
    """Classic (offset, length, next-literal) triples; offsets count back from
    the cursor; overlapping matches allowed (decoder copies byte-by-byte)."""
    out: list[tuple[int, int, str]] = []
    i = 0
    while i < len(data):
        best_len, best_off = 0, 0
        max_len = min(_LZ_LOOKAHEAD, len(data) - i - 1)
        for off in range(1, min(i, _LZ_WINDOW) + 1):
            length = 0
            while length < max_len and data[i - off + length] == data[i + length]:
                length += 1
            if length > best_len:
                best_len, best_off = length, off
        if best_len >= _LZ_MIN_MATCH:
            out.append((best_off, best_len, data[i + best_len]))
            i += best_len + 1
        else:
            out.append((0, 0, data[i]))
            i += 1
    return out


def _lz77_decode(triples: list[tuple[int, int, str]]) -> str:
    buf: list[str] = []
    for off, length, lit in triples:
        for _ in range(length):
            buf.append(buf[-off])
        buf.append(lit)
    return "".join(buf)


def _lz77_doc(rng, n: int, elide_over: int):
    # small alphabet + phrase reuse so real back-references occur
    phrases = ["".join(rng.choice("abcd") for _ in range(rng.randint(2, 4))) for _ in range(3)]
    parts = []
    while sum(len(p) for p in parts) < n:
        parts.append(rng.choice(phrases) if rng.random() < 0.7 else rng.choice("abcd"))
    data = "".join(parts)[:n]

    triples = _lz77_encode(data)
    assert _lz77_decode(triples) == data  # round trip

    raw_steps, states = [], []
    i = 0
    for off, length, lit in triples:
        window = data[max(0, i - _LZ_WINDOW): i]
        look = data[i: i + _LZ_LOOKAHEAD]
        if length:
            src = data[i - off: i - off + length]
            raw_steps.append(
                f"pos {i}: window='{window}' lookahead='{look}' -> longest match "
                f"'{src}' at offset {off}, length {length}; emit ({off},{length},'{lit}'); "
                f"pos -> {i + length + 1}"
            )
            i += length + 1
        else:
            raw_steps.append(
                f"pos {i}: window='{window}' lookahead='{look}' -> no match >= "
                f"{_LZ_MIN_MATCH}; emit literal (0,0,'{lit}'); pos -> {i + 1}"
            )
            i += 1
        states.append(f"pos={i}, triples emitted={len(states) + 1}")

    task = (
        "### Task: simulate LZ77 compression\n"
        f"Input ({len(data)} bytes): {data}\n"
        f"Parameters: search window {_LZ_WINDOW} bytes, lookahead {_LZ_LOOKAHEAD} bytes, "
        f"minimum match {_LZ_MIN_MATCH}. Emit (offset, length, next-literal) triples."
    )
    answer = [
        f"triples ({len(triples)}): {triples}",
        f"tokens: {len(data)} input bytes -> {len(triples)} triples",
        "decode check: expanding the triples reproduces the input exactly.",
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    return text, "deliberate", "lz77_trace", {"data": data, "triples": triples}


# ---------------------------------------------------------------------------
# Huffman
# ---------------------------------------------------------------------------


def _huffman_codes(freqs: dict[str, int]):
    """Deterministic Huffman: ties broken by node creation order (leaves in
    alphabetical order first). Returns (codes, merge trace rows)."""
    nodes = [(f, i, sym, None, None) for i, (sym, f) in enumerate(sorted(freqs.items()))]
    labels = {i: f"'{sym}'({f})" for i, (sym, f) in enumerate(sorted(freqs.items()))}
    next_id = len(nodes)
    merges = []
    while len(nodes) > 1:
        nodes.sort(key=lambda t: (t[0], t[1]))
        a, b = nodes[0], nodes[1]
        merged = (a[0] + b[0], next_id, None, a, b)
        labels[next_id] = f"T{next_id - len(freqs) + 1}({a[0] + b[0]})"
        merges.append((labels[a[1]], labels[b[1]], labels[next_id]))
        nodes = nodes[2:] + [merged]
        next_id += 1

    codes: dict[str, str] = {}

    def walk(node, prefix):
        _, _, sym, left, right = node
        if sym is not None:
            codes[sym] = prefix or "0"
            return
        walk(left, prefix + "0")
        walk(right, prefix + "1")

    walk(nodes[0], "")
    return codes, merges


def _huffman_doc(rng, n: int, elide_over: int):
    alpha = sorted(rng.sample("abcdefgnorst", rng.randint(4, 6)))
    weights = [rng.randint(1, 9) for _ in alpha]
    data = "".join(rng.choices(alpha, weights=weights, k=n))
    while len(set(data)) < 2:  # need a real tree
        data = "".join(rng.choices(alpha, weights=weights, k=n))
    freqs = {s: data.count(s) for s in sorted(set(data))}

    codes, merges = _huffman_codes(freqs)
    encoded = "".join(codes[c] for c in data)

    # round trip: decode by prefix-walking the code table
    inv = {v: k for k, v in codes.items()}
    out, cur = [], ""
    for bit in encoded:
        cur += bit
        if cur in inv:
            out.append(inv[cur])
            cur = ""
    assert cur == "" and "".join(out) == data

    raw_steps, states = [], []
    for a, b, m in merges:
        raw_steps.append(f"pop two lowest-frequency nodes {a} and {b} -> merge into {m} (left={a} gets bit 0, right={b} gets bit 1)")
        states.append(f"merged nodes={len(states) + 1}")
    raw_steps.append("assign codes by walking the tree root->leaf: " + ", ".join(f"'{s}'={codes[s]}" for s in sorted(codes)))
    states.append("code table complete")
    group = 12
    for gi in range(0, len(data), group):
        chunk = data[gi: gi + group]
        bits = "".join(codes[c] for c in chunk)
        raw_steps.append(f"encode '{chunk}' -> " + " ".join(codes[c] for c in chunk) + f" ({len(bits)} bits)")
        states.append(f"encoded {min(gi + group, len(data))}/{len(data)} symbols, {len(''.join(codes[c] for c in data[: gi + group]))} bits so far")

    fixed_bits = len(data) * 8
    task = (
        "### Task: simulate Huffman coding\n"
        f"Input ({len(data)} symbols): {data}\n"
        f"Symbol frequencies: {freqs}\n"
        "Build the Huffman tree (ties broken by node creation order, leaves in "
        "alphabetical order first; first-popped child takes bit 0), derive the "
        "code table, and encode the input."
    )
    answer = [
        f"code table: {codes}",
        f"encoded bitstream ({len(encoded)} bits): {encoded}",
        f"size: {fixed_bits} bits fixed-width -> {len(encoded)} bits "
        f"(ratio {fixed_bits / len(encoded):.2f}x)",
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    return text, "deliberate", "huffman_trace", {"data": data, "freqs": freqs, "codes": codes, "encoded": encoded}


# ---------------------------------------------------------------------------
# Delta + varint (TSDB-style timestamp packing)
# ---------------------------------------------------------------------------


def _varint(x: int) -> list[int]:
    """Unsigned LEB128: little-endian 7-bit groups, MSB = continuation."""
    out = []
    while True:
        b = x & 0x7F
        x >>= 7
        if x:
            out.append(b | 0x80)
        else:
            out.append(b)
            return out


def _unvarint(stream: list[int]) -> list[int]:
    vals, cur, shift = [], 0, 0
    for b in stream:
        cur |= (b & 0x7F) << shift
        if b & 0x80:
            shift += 7
        else:
            vals.append(cur)
            cur, shift = 0, 0
    return vals


def _delta_varint_doc(rng, n: int, elide_over: int):
    t0 = 1_700_000_000 + rng.randint(0, 10 ** 6)
    ts = [t0]
    for _ in range(n - 1):
        ts.append(ts[-1] + rng.randint(1, 300))
    deltas = [ts[0]] + [b - a for a, b in zip(ts, ts[1:])]
    stream: list[int] = []
    raw_steps, states = [], []
    for i, d in enumerate(deltas):
        enc = _varint(d)
        stream.extend(enc)
        what = f"t[0]={d} (raw first timestamp)" if i == 0 else f"delta t[{i}]-t[{i - 1}] = {ts[i]} - {ts[i - 1]} = {d}"
        raw_steps.append(
            f"{what}; varint: {d} = 0b{d:b} -> 7-bit groups little-endian -> bytes "
            f"[{', '.join(f'0x{b:02X}' for b in enc)}]"
        )
        states.append(f"encoded {i + 1}/{n} points, {len(stream)} bytes so far")

    decoded = _unvarint(stream)
    rebuilt = [decoded[0]]
    for d in decoded[1:]:
        rebuilt.append(rebuilt[-1] + d)
    assert rebuilt == ts  # round trip

    task = (
        "### Task: simulate time-series timestamp compression (delta + varint)\n"
        f"Input: {n} timestamps (unix seconds):\n  {ts}\n"
        "Store the first timestamp raw, then successive deltas, each encoded as an "
        "unsigned LEB128 varint (little-endian 7-bit groups, high bit = continuation)."
    )
    answer = [
        f"byte stream ({len(stream)} bytes): [{', '.join(f'0x{b:02X}' for b in stream)}]",
        f"size: {n * 8} bytes as raw int64 -> {len(stream)} bytes "
        f"(ratio {n * 8 / len(stream):.2f}x)",
        "decode check: cumulative sum of decoded varints reproduces every timestamp.",
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    return text, "temporal", "delta_varint_trace", {"ts": ts, "stream": stream}


# ---------------------------------------------------------------------------
# INT8 quantization (neural compression)
# ---------------------------------------------------------------------------


def _quant_int8_doc(rng, n: int, elide_over: int):
    vals = [rng.randint(-4999, 4999) / 1000.0 for _ in range(n)]
    while not any(vals):  # all-zero tensor would make the scale degenerate
        vals = [rng.randint(-4999, 4999) / 1000.0 for _ in range(n)]
    amax = max(abs(v) for v in vals)
    scale = amax / 127.0
    q = [max(-127, min(127, round(v / scale))) for v in vals]
    deq = [qi * scale for qi in q]
    errs = [abs(v - d) for v, d in zip(vals, deq)]

    raw_steps = [
        f"amax = max(|x_i|) = {amax:.3f}; scale = amax/127 = {amax:.3f}/127 = {scale:.6f}; "
        "zero_point = 0 (symmetric int8)"
    ]
    states = [f"scale={scale:.6f}"]
    for i, (v, qi, d, e) in enumerate(zip(vals, q, deq, errs)):
        raw_steps.append(
            f"x[{i}] = {v:.3f}: q = clamp(round({v:.3f}/{scale:.6f}), -127, 127) = {qi}; "
            f"dequant = {qi}*{scale:.6f} = {d:.6f}; |err| = {e:.6f}"
        )
        states.append(f"quantized {i + 1}/{n}, q so far={q[: i + 1]}")

    task = (
        "### Task: simulate symmetric INT8 tensor quantization\n"
        f"Input tensor ({n} float32 values):\n  [{', '.join(f'{v:.3f}' for v in vals)}]\n"
        "Compute the scale from the absolute maximum (zero_point = 0), quantize each "
        "element to int8 with round-to-nearest and clamping, then dequantize and "
        "report the reconstruction error."
    )
    answer = [
        f"scale = {scale:.6f}, zero_point = 0",
        f"quantized int8 tensor: {q}",
        f"max |reconstruction error| = {max(errs):.6f}",
        f"size: {n * 4} bytes float32 -> {n} bytes int8 (+4-byte scale), ratio ~{n * 4 / (n + 4):.2f}x",
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    return text, "deliberate", "quant_int8_trace", {"vals": vals, "scale": scale, "q": q}


# ---------------------------------------------------------------------------
# Arithmetic coding with Equal-Info Windows
# ---------------------------------------------------------------------------

_AC_P = {"A": Fraction(1, 2), "B": Fraction(1, 4), "C": Fraction(1, 4)}
_AC_CUM = {"A": Fraction(0), "B": Fraction(1, 2), "C": Fraction(3, 4)}
_AC_BITS = {"A": 1, "B": 2, "C": 2}
_AC_BUDGET = 8


def _ac_encode_windows(seq: str) -> list[tuple[str, int, str]]:
    """Arithmetic-code `seq`, flushing the interval whenever the accumulated
    information reaches the window budget. Because every symbol probability is
    dyadic, each flush point has interval width exactly 2^-bits and a dyadic
    lower bound, so the window's code is simply `bits` binary digits of `low`.
    Returns [(window_symbols, bits, code_bits), ...]."""
    windows = []
    low, width, bits, syms = Fraction(0), Fraction(1), 0, ""
    for s in seq:
        low += width * _AC_CUM[s]
        width *= _AC_P[s]
        bits += _AC_BITS[s]
        syms += s
        if bits >= _AC_BUDGET:
            k = low * (1 << bits)
            assert k.denominator == 1 and width == Fraction(1, 1 << bits)
            windows.append((syms, bits, format(int(k), f"0{bits}b")))
            low, width, bits, syms = Fraction(0), Fraction(1), 0, ""
    if syms:
        k = low * (1 << bits)
        assert k.denominator == 1
        windows.append((syms, bits, format(int(k), f"0{bits}b")))
    return windows


def _ac_decode_window(bits: int, code: str) -> str:
    v = Fraction(int(code, 2), 1 << bits)
    out, low, width, used = "", Fraction(0), Fraction(1), 0
    while used < bits:
        for s in "ABC":
            lo = low + width * _AC_CUM[s]
            if lo <= v < lo + width * _AC_P[s]:
                out += s
                low, width, used = lo, width * _AC_P[s], used + _AC_BITS[s]
                break
        else:  # pragma: no cover - unreachable on well-formed windows
            raise AssertionError("no symbol interval contains the code value")
    return out


def _arith_eiw_doc(rng, n: int, elide_over: int):
    seq = "".join(rng.choices("ABC", weights=[2, 1, 1], k=n))
    windows = _ac_encode_windows(seq)
    assert "".join(_ac_decode_window(b, c) for _, b, c in windows) == seq  # round trip

    raw_steps, states = [], []
    low, width, bits = Fraction(0), Fraction(1), 0
    widx = 0
    for s in seq:
        low += width * _AC_CUM[s]
        width *= _AC_P[s]
        bits += _AC_BITS[s]
        denom = 1 << bits
        raw_steps.append(
            f"symbol '{s}' (p={_AC_P[s]}, {_AC_BITS[s]}-bit info): interval -> "
            f"[{low.numerator * denom // low.denominator if low else 0}/{denom}, "
            f"{(low + width).numerator * denom // (low + width).denominator}/{denom}); "
            f"window info = {bits}/{_AC_BUDGET} bits"
        )
        if bits >= _AC_BUDGET:
            syms, b, code = windows[widx]
            raw_steps.append(
                f"window {widx + 1} full: width = 2^-{b}, low = {code} (binary) -> "
                f"FLUSH '{syms}' as bits {code}; reset interval to [0,1)"
            )
            states.append(f"windows flushed={widx + 1}, symbols consumed incl. this window")
            low, width, bits = Fraction(0), Fraction(1), 0
            widx += 1
        states.append(f"low={low}, width={width}, window bits={bits}, windows flushed={widx}")
    if bits:
        syms, b, code = windows[widx]
        raw_steps.append(f"end of input: flush final partial window '{syms}' ({b} bits) as {code}")
        states.append(f"windows flushed={widx + 1}")

    bitstream = "".join(c for _, _, c in windows)
    task = (
        "### Task: simulate arithmetic coding with Equal-Info Windows\n"
        f"Input ({n} symbols): {seq}\n"
        f"Model: P(A)=1/2, P(B)=1/4, P(C)=1/4 (so A carries 1 bit, B and C carry 2 bits).\n"
        f"Narrow the interval [low, low+width) per symbol; whenever accumulated "
        f"information reaches the {_AC_BUDGET}-bit window budget, flush the window as "
        "the binary expansion of `low` and reset the interval. Window resets make each "
        "window independently decodable (this is what keeps the bitstream learnable)."
    )
    answer = [
        f"windows ({len(windows)}): " + ", ".join(f"'{s}'->{c}" for s, _, c in windows),
        f"bitstream ({len(bitstream)} bits): {bitstream}",
        f"size: {n} symbols -> {len(bitstream)} bits "
        f"(entropy-optimal for this model: {sum(_AC_BITS[s] for s in seq)} bits)",
    ]
    # states list is per raw step (flush lines add one extra state each); align lengths
    states = states[: len(raw_steps)] + ["done"] * max(0, len(raw_steps) - len(states))
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    return text, "deliberate", "arith_eiw_trace", {"seq": seq, "windows": windows}


# ---------------------------------------------------------------------------
# DEFLATE-style composition: LZ77 stage feeding a Huffman stage
# ---------------------------------------------------------------------------

_DEFLATE_OFF_BITS = 5   # offsets 0..16 (window 16)
_DEFLATE_LEN_BITS = 4   # lengths 0..8 (lookahead 8)


def _deflate_pack(triples: list[tuple[int, int, str]], codes: dict[str, str]) -> str:
    bits = []
    for off, length, lit in triples:
        bits.append(format(off, f"0{_DEFLATE_OFF_BITS}b"))
        bits.append(format(length, f"0{_DEFLATE_LEN_BITS}b"))
        bits.append(codes[lit])
    return "".join(bits)


def _deflate_unpack(bitstream: str, codes: dict[str, str]) -> list[tuple[int, int, str]]:
    inv = {v: k for k, v in codes.items()}
    triples, i = [], 0
    while i < len(bitstream):
        off = int(bitstream[i: i + _DEFLATE_OFF_BITS], 2)
        i += _DEFLATE_OFF_BITS
        length = int(bitstream[i: i + _DEFLATE_LEN_BITS], 2)
        i += _DEFLATE_LEN_BITS
        cur = ""
        while cur not in inv:
            cur += bitstream[i]
            i += 1
        triples.append((off, length, inv[cur]))
    return triples


def _deflate_doc(rng, n: int, elide_over: int):
    phrases = ["".join(rng.choice("abcd") for _ in range(rng.randint(2, 4))) for _ in range(3)]
    parts: list[str] = []
    while sum(len(p) for p in parts) < n:
        parts.append(rng.choice(phrases) if rng.random() < 0.7 else rng.choice("abcd"))
    data = "".join(parts)[:n]

    triples = _lz77_encode(data)
    lit_freqs: dict[str, int] = {}
    for _, _, lit in triples:
        lit_freqs[lit] = lit_freqs.get(lit, 0) + 1
    codes, merges = _huffman_codes(lit_freqs)
    bitstream = _deflate_pack(triples, codes)
    # full two-stage round trip before the doc is yielded
    assert _lz77_decode(_deflate_unpack(bitstream, codes)) == data

    raw_steps, states = [], []
    for idx, (off, length, lit) in enumerate(triples):
        raw_steps.append(
            f"stage 1 (LZ77): emit triple ({off},{length},'{lit}')"
            + (f" -- back-reference offset {off}, copy {length}" if length else " -- literal")
        )
        states.append(f"triples emitted={idx + 1}/{len(triples)}")
    raw_steps.append(f"stage 1 done: {len(data)} bytes -> {len(triples)} triples; "
                     f"literal frequencies {dict(sorted(lit_freqs.items()))}")
    states.append("stage 1 done")
    for a, b, m in merges:
        raw_steps.append(f"stage 2 (Huffman over literals): merge {a} + {b} -> {m}")
        states.append("building literal tree")
    raw_steps.append("stage 2 code table: " + ", ".join(f"'{s}'={codes[s]}" for s in sorted(codes)))
    states.append("code table done")
    for off, length, lit in triples:
        raw_steps.append(
            f"pack ({off},{length},'{lit}') -> offset {format(off, f'0{_DEFLATE_OFF_BITS}b')} | "
            f"length {format(length, f'0{_DEFLATE_LEN_BITS}b')} | literal {codes[lit]} "
            f"({_DEFLATE_OFF_BITS + _DEFLATE_LEN_BITS + len(codes[lit])} bits)"
        )
        states.append(f"bits so far<= {len(bitstream)}")

    fixed_bits = len(data) * 8
    task = (
        "### Task: simulate DEFLATE-style two-stage compression (LZ77 -> Huffman)\n"
        f"Input ({len(data)} bytes): {data}\n"
        f"Stage 1: LZ77 with window {_LZ_WINDOW}, lookahead {_LZ_LOOKAHEAD}, minimum match "
        f"{_LZ_MIN_MATCH} emits (offset, length, next-literal) triples.\n"
        f"Stage 2: Huffman-code the literals (ties broken by node creation order); pack each "
        f"triple as {_DEFLATE_OFF_BITS}-bit offset | {_DEFLATE_LEN_BITS}-bit length | literal code."
    )
    answer = [
        f"triples ({len(triples)}): {triples}",
        f"literal code table: {codes}",
        f"bitstream ({len(bitstream)} bits): {bitstream}",
        f"size: {fixed_bits} bits fixed-width -> {len(bitstream)} bits "
        f"(ratio {fixed_bits / len(bitstream):.2f}x; both stages verified by decoding)",
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"data": data, "triples": triples, "codes": codes, "bitstream": bitstream}
    return text, "deliberate", "deflate_trace", meta


# ---------------------------------------------------------------------------
# Magnitude pruning (neural compression)
# ---------------------------------------------------------------------------


def _prune_doc(rng, n: int, elide_over: int):
    vals = [rng.randint(-4999, 4999) / 1000.0 for _ in range(n)]
    while not any(vals):
        vals = [rng.randint(-4999, 4999) / 1000.0 for _ in range(n)]
    frac = rng.choice([0.25, 0.5, 0.75])
    k = min(n - 1, max(1, round(n * frac)))
    order = sorted(range(n), key=lambda i: (abs(vals[i]), i))
    pruned = set(order[:k])
    threshold = abs(vals[order[k - 1]])
    out = [0.0 if i in pruned else v for i, v in enumerate(vals)]
    assert sum(1 for v in out if v == 0.0) >= k  # ties/zeros can only add sparsity

    rank = {i: r for r, i in enumerate(order)}
    raw_steps = [
        f"sort by |x| (ties by index): magnitude order = "
        f"[{', '.join(f'x[{i}]={abs(vals[i]):.3f}' for i in order)}]; prune the k = {k} "
        f"smallest -> threshold |x| = {threshold:.3f}"
    ]
    states = [f"k={k}, threshold={threshold:.3f}"]
    for i, v in enumerate(vals):
        if i in pruned:
            raw_steps.append(
                f"x[{i}] = {v:.3f}: magnitude rank {rank[i]} < k={k} -> ZERO"
            )
        else:
            raw_steps.append(
                f"x[{i}] = {v:.3f}: magnitude rank {rank[i]} >= k={k} -> keep"
            )
        states.append(f"processed {i + 1}/{n}, zeros so far={sum(1 for j in range(i + 1) if j in pruned)}")

    task = (
        "### Task: simulate magnitude pruning of a tensor (neural compression)\n"
        f"Input tensor ({n} float32 values):\n  [{', '.join(f'{v:.3f}' for v in vals)}]\n"
        f"Prune the k = {k} elements of smallest absolute magnitude (ties broken by lower "
        "index) by setting them to zero; report the sparse tensor and sparsity."
    )
    answer = [
        f"pruned tensor: [{', '.join(f'{v:.3f}' for v in out)}]",
        f"zeroed indices: {sorted(pruned)}",
        f"sparsity: {k}/{n} = {100 * k / n:.1f}% (kept {n - k} weights, "
        f"prune threshold |x| = {threshold:.3f})",
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"vals": vals, "k": k, "pruned": sorted(pruned), "out": out, "threshold": threshold}
    return text, "deliberate", "prune_magnitude", meta


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class CompressTraceGenerator(Generator):
    """Execution-trace compression corpus. Phase sizing = context-window
    management: p2 emits micro-traces that fit seq 2048/4096, p3 emits
    medium traces with checkpoint elision past PHASE_ELIDE_OVER steps, p4
    grows inputs until the doc clears the spec-02 long-doc band."""

    name = "compress_trace"
    phases = (2, 3, 4)

    # (weight, builder, source, p2 n-range, p3 n-range,
    #  p4 growth (start_n, step, target_chars, max_n))
    _FAMILIES = [
        (0.11, _rle_doc, "compress/rle", (5, 9), (18, 36), (45, 8, 6200, 160)),
        (0.15, _lz77_doc, "compress/lz77", (10, 16), (36, 64), (60, 10, 6200, 220)),
        (0.15, _huffman_doc, "compress/huffman", (12, 20), (30, 48), (90, 16, 6200, 900)),
        (0.12, _delta_varint_doc, "compress/delta_varint", (5, 8), (16, 34), (36, 6, 6200, 140)),
        (0.13, _quant_int8_doc, "compress/quant_int8", (5, 8), (16, 34), (34, 6, 6200, 140)),
        (0.12, _arith_eiw_doc, "compress/arith_eiw", (8, 14), (24, 44), (48, 8, 6200, 200)),
        (0.12, _deflate_doc, "compress/deflate", (10, 16), (24, 40), (44, 8, 6200, 200)),
        (0.10, _prune_doc, "compress/prune", (6, 10), (14, 28), (30, 6, 6200, 160)),
    ]

    _PHASE_MIX = [(0.35, 2), (0.45, 3), (0.20, 4)]

    def generate(self, target_bytes: int) -> Iterator[dict]:
        from ava.datagen.trace_common import PHASE_ELIDE_OVER

        fam_cum, fam_total = [], 0.0
        for w, *_ in self._FAMILIES:
            fam_total += w
            fam_cum.append(fam_total)
        phase_cum, phase_total = [], 0.0
        for w, _ in self._PHASE_MIX:
            phase_total += w
            phase_cum.append(phase_total)

        produced = 0
        while produced < target_bytes:
            r = self.rng.random() * fam_total
            fi = 0
            while r > fam_cum[fi]:
                fi += 1
            _, builder, source, p2_range, p3_range, p4_growth = self._FAMILIES[fi]

            r2 = self.rng.random() * phase_total
            pi = 0
            while r2 > phase_cum[pi]:
                pi += 1
            _, phase = self._PHASE_MIX[pi]

            elide_over = PHASE_ELIDE_OVER[phase]
            if phase == 4:
                start_n, step, target_chars, max_n = p4_growth
                n = start_n
                text, task_type, concept, _meta = builder(self.rng, n, elide_over)
                while len(text) < target_chars and n < max_n:
                    n = min(n + step, max_n)
                    text, task_type, concept, _meta = builder(self.rng, n, elide_over)
            else:
                lo, hi = p2_range if phase == 2 else p3_range
                text, task_type, concept, _meta = builder(self.rng, self.rng.randint(lo, hi), elide_over)

            d = self.doc(text=text, task_type=task_type, concept=concept, phase=phase, source=source)
            produced += len(d["text"].encode("utf-8"))
            yield d


if __name__ == "__main__":
    from ava.datagen.base import run_cli

    run_cli(CompressTraceGenerator)
