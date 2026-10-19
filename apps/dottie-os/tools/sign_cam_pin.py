#!/usr/bin/env python3
"""Cam-side CLI: sign a Swarm HQ pack-pin on Cam's own device.

This is the only v2 signer. Cam runs it locally. It reads his Ed25519
private key from a filesystem path he passes, or from stdin
(``--private-key -``). It prints ``cam_sig`` (base64) to stdout. It never
writes the key (not to the pin, not to disk, not to evidence). It does not
read env, CI secrets, or repo files for key material.

``kick_helper_ft.py`` and ``helper_ft_kickoff.py`` must not import or call
this tool. A pin in an agent-supplied HTTP body is not provenance.
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

STDIN_KEY = "-"


def _read_private_bytes(raw: bytes) -> bytes:
    if len(raw) == 32:
        return raw
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise SystemExit("private key must be 32 raw bytes or base64 of 32 bytes") from exc
    try:
        decoded = base64.b64decode(text, validate=True)
    except (ValueError, TypeError) as exc:
        raise SystemExit("private key must be 32 raw bytes or base64 of 32 bytes") from exc
    if len(decoded) != 32:
        raise SystemExit("private key must be 32 raw bytes or base64 of 32 bytes")
    return decoded


def _read_private(source: str) -> bytes:
    if source == STDIN_KEY:
        return _read_private_bytes(sys.stdin.buffer.read())
    return _read_private_bytes(Path(source).read_bytes())


def sign_pin(payload: dict, private: bytes) -> str:
    """Cam-side only. v2 uses ``sign_pin_v2``; v1 stays history."""
    fmt = cam_pin_spec.pin_format_of(payload)
    if fmt == cam_pin_spec.PIN_FORMAT_V2:
        return cam_pin_spec.sign_pin_v2(payload, private)
    message = cam_pin_spec.canonical_pin_bytes(payload)
    return cam_pin_spec.sign_pin_bytes(message, private)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--private-key",
        required=True,
        help="path on this device to Cam's 32-byte Ed25519 private key, or - for stdin",
    )
    parser.add_argument(
        "--pin",
        type=Path,
        required=True,
        help="JSON pin (v2 signed fields, or v1 history fields)",
    )
    args = parser.parse_args(argv)
    private = _read_private(args.private_key)
    payload = json.loads(args.pin.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        print("pin must be a JSON object", file=sys.stderr)
        return 1
    cam_pin_spec.require_ed25519_point(
        cam_pin_spec.raw_public_from_private(private), field="cam_pin.pubkey"
    )
    signature = sign_pin(payload, private)
    cam_pin_spec.require_ed25519_signature(
        base64.b64decode(signature, validate=True), field="cam-pin.cam_sig"
    )
    sys.stdout.write(signature + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
