"""Ed25519 small-order and non-canonical encodings.

Defined outside ``cam_pin_spec.py``. The 14 encodings are the libsodium
small-order block plus the non-canonical ``y >= p`` forms (ec/ed/ee).
The production module must decode the point and refuse ``[8]A == identity``,
not match this list.
"""

from __future__ import annotations

# RFC 8032 group order. Tests compare S against this copy, not the module under test.
ED25519_L = 2**252 + 27742317777372353535851937790883648493


def _hex(text: str) -> bytes:
    return bytes.fromhex(text)


def _fill(first: int, last: int) -> bytes:
    return bytes([first] + [0xFF] * 30 + [last])


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
