#!/usr/bin/env python3
"""Generate a Cam Ed25519 pack-pin keypair on Cam's own device.

Writes the private key to the path Cam gives (mode 0600) and prints the
public key file contents for him to commit at
``apps/dottie-os/trust/cam_pin_ed25519.pub``. Never writes the private key
anywhere else. Never prints the private key.
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1] / "scripts" / "lab"
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

import cam_pin_spec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--private-key",
        type=Path,
        required=True,
        help="path on this device to write the 32-byte raw private key (0600)",
    )
    parser.add_argument(
        "--key-id",
        default="cam-pin-ed25519-1",
        help="cam_key_id to print as the first line of the public key file",
    )
    args = parser.parse_args(argv)
    dest = args.private_key
    if dest.exists():
        print(f"refused: {dest} already exists", file=sys.stderr)
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    raw_priv = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    raw_pub = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    cam_pin_spec.require_ed25519_point(raw_pub, field="cam_pin.pubkey")
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, raw_priv)
    finally:
        os.close(fd)
    pub_text = args.key_id + "\n" + base64.b64encode(raw_pub).decode("ascii") + "\n"
    sys.stdout.write(pub_text)
    sys.stdout.flush()
    print(
        f"private key written to {dest} (0600). commit the stdout block as "
        "apps/dottie-os/trust/cam_pin_ed25519.pub",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
