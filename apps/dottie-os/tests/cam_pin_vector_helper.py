#!/usr/bin/env python3
"""Test-only Cam pin verify. Takes a public key argument. Never reads trust/."""
from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from cam_pin_spec import CamPinError, canonical_pin_bytes


def verify_with_key(message: bytes, signature: bytes, public_key_b64: str) -> None:
    """Verify Ed25519 with an explicit key. Does not load apps/dottie-os/trust/."""
    if "trust" in public_key_b64:
        raise CamPinError("cam_pin.pubkey", "vector test key", "trust path")
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise CamPinError("cam_pin.pubkey", "base64 public key", "invalid") from exc
    if len(raw) != 32:
        raise CamPinError("cam_pin.pubkey", "32-byte public key", f"len {len(raw)}")
    public = Ed25519PublicKey.from_public_bytes(raw)
    try:
        public.verify(signature, message)
    except InvalidSignature as exc:
        raise CamPinError("cam-pin.cam_sig", "valid Ed25519 signature", "invalid") from exc


def verify_pin_with_key(pin: dict, public_key_b64: str) -> None:
    sig = base64.b64decode(pin["cam_sig"] if "cam_sig" in pin else pin.get("signature", ""), validate=True)
    verify_with_key(canonical_pin_bytes(pin), sig, public_key_b64)
