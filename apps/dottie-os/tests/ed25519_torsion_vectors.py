"""Ed25519 small-order, non-canonical, and mixed-order encodings.

Defined outside ``cam_pin_spec.py``. The 14 encodings are the libsodium
small-order block plus the non-canonical ``y >= p`` forms (ec/ed/ee).
Mixed-order vectors are a prime-order point plus each of the 7
non-identity torsion points. The production module must decode and
check ``[8]A`` / ``[L]A``, not match this list.
"""

from __future__ import annotations

# RFC 8032 group order. Tests compare S against this copy, not the module under test.
ED25519_L = 2**252 + 27742317777372353535851937790883648493
_P = 2**255 - 19
_D = (-121665 * pow(121666, -1, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _hex(text: str) -> bytes:
    return bytes.fromhex(text)


def _fill(first: int, last: int) -> bytes:
    return bytes([first] + [0xFF] * 30 + [last])


def _decode_point(raw: bytes) -> tuple[int, int] | None:
    """Independent RFC 8032 decode for building mixed-order test vectors."""
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        return None
    y2 = (y * y) % _P
    u = (y2 - 1) % _P
    v = (_D * y2 + 1) % _P
    x2 = (u * pow(v, -1, _P)) % _P
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = (x * _I) % _P
    if (x * x - x2) % _P != 0:
        return None
    if x == 0 and sign:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x, y


def _add_points(p1: tuple[int, int], p2: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = p1
    x2, y2 = p2
    t = (_D * x1 * x2 * y1 * y2) % _P
    x3 = ((x1 * y2 + x2 * y1) * pow(1 + t, -1, _P)) % _P
    y3 = ((y1 * y2 + x1 * x2) * pow(1 - t, -1, _P)) % _P
    return x3, y3


def _encode_point(point: tuple[int, int]) -> bytes:
    x, y = point
    bits = y
    if x & 1:
        bits |= 1 << 255
    return bits.to_bytes(32, "little")


# 14 encodings: 8 libsodium torsion points + high-bit 0/1 + y>=p (ed/ee).
TORSION_ENCODINGS: tuple[tuple[str, bytes], ...] = (
    ("identity", bytes([0x01] + [0x00] * 31)),
    ("all_zero", bytes(32)),
    ("identity_sign", bytes([0x01] + [0x00] * 30 + [0x80])),
    ("all_zero_sign", bytes([0x00] * 31 + [0x80])),
    (
        "order8_26e8_pos",
        _hex("26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05"),
    ),
    (
        "order8_26e8_neg",
        _hex("26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85"),
    ),
    (
        "order8_c717_pos",
        _hex("c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a"),
    ),
    (
        "order8_c717_neg",
        _hex("c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa"),
    ),
    ("order2_ecff_7f", _fill(0xEC, 0x7F)),
    ("order2_ecff_ff", _fill(0xEC, 0xFF)),
    ("noncanonical_edff_7f", _fill(0xED, 0x7F)),
    ("noncanonical_edff_ff", _fill(0xED, 0xFF)),
    ("noncanonical_eeff_7f", _fill(0xEE, 0x7F)),
    ("noncanonical_eeff_ff", _fill(0xEE, 0xFF)),
)

IDENTITY = TORSION_ENCODINGS[0][1]
ALL_ZERO = TORSION_ENCODINGS[1][1]
ORDER2 = TORSION_ENCODINGS[8][1]

# The 8 torsion subgroup points minus identity. Non-canonical encodings are
# not group elements we can add (they fail decode).
_SKIP_MIXED = frozenset(
    {
        "identity",
        "identity_sign",
        "order2_ecff_ff",
        "noncanonical_edff_7f",
        "noncanonical_edff_ff",
        "noncanonical_eeff_7f",
        "noncanonical_eeff_ff",
    }
)
NON_IDENTITY_TORSION_ENCODINGS: tuple[tuple[str, bytes], ...] = tuple(
    (name, raw) for name, raw in TORSION_ENCODINGS if name not in _SKIP_MIXED
)


def mixed_order_encodings(prime_order_raw: bytes) -> tuple[tuple[str, bytes], ...]:
    """Prime-order point plus each of the 7 non-identity torsion points."""
    base = _decode_point(prime_order_raw)
    if base is None:
        raise ValueError("prime-order point must decode")
    out: list[tuple[str, bytes]] = []
    for name, raw in NON_IDENTITY_TORSION_ENCODINGS:
        torsion = _decode_point(raw)
        if torsion is None:
            raise ValueError(f"torsion {name} must decode")
        mixed = _add_points(base, torsion)
        out.append((f"mixed_{name}", _encode_point(mixed)))
    if len(out) != 7:
        raise ValueError(f"expected 7 mixed-order encodings, got {len(out)}")
    return tuple(out)
