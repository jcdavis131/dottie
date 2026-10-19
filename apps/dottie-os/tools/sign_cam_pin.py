#!/usr/bin/env python3
"""Sign a Swarm HQ pack-pin on Cam's own device.

Reads Cam's Ed25519 private key from a path he gives. Prints the base64
``cam_sig`` to stdout. Never writes the key anywhere (not to the pin, not
to disk, not to evidence).
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1] / "scripts" / "lab"
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

import cam_pin_spec


def _read_private(path: Path) -> bytes:
    raw = path.read_bytes()
    if len(raw) == 32:
        return raw
    text = raw.decode("utf-8").strip()
    decoded = base64.b64decode(text, validate=True)
    if len(decoded) != 32:
        raise SystemExit("private key must be 32 raw bytes or base64 of 32 bytes")
    return decoded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--private-key",
        type=Path,
        required=True,
        help="path on this device to Cam's 32-byte Ed25519 private key",
    )
    parser.add_argument(
        "--pin",
        type=Path,
        required=True,
        help="JSON pin (must include the eight signed fields)",
    )
    args = parser.parse_args(argv)
    private = _read_private(args.private_key)
    payload = json.loads(args.pin.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        print("pin must be a JSON object", file=sys.stderr)
        return 1
    fmt = cam_pin_spec.pin_format_of(payload)
    if fmt == cam_pin_spec.PIN_FORMAT_V2:
        message = cam_pin_spec.canonical_pin_bytes_v2(payload)
    else:
        message = cam_pin_spec.canonical_pin_bytes(payload)
    cam_pin_spec.require_ed25519_point(
        cam_pin_spec.raw_public_from_private(private), field="cam_pin.pubkey"
    )
    signature = cam_pin_spec.sign_pin_bytes(message, private)
    cam_pin_spec.require_ed25519_signature(
        base64.b64decode(signature, validate=True), field="cam-pin.cam_sig"
    )
    sys.stdout.write(signature + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
