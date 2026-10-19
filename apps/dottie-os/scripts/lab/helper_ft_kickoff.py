#!/usr/bin/env python3
"""Forge-runner HELPER FT ``POST /train/kickoff`` handler.

Refuses ``inbox: latest``, missing evidence, and evidence/shas that do not
match the named pack. Stdlib only. Does not promote, does not touch serve,
:8770, or champion files.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

CHUNK = 1 << 20
SHA_FIELDS = (
    ("sha256_pack", "pack"),
    ("sha256_train", "train"),
    ("sha256_holdout", "holdout"),
)


def _bad(field: str, expected: object, actual: object) -> dict[str, Any]:
    return {
        "ok": False,
        "field": field,
        "expected": expected,
        "actual": actual,
        "error": f"HELPER FT kickoff refused: {field}: expected {expected} actual {actual}",
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                break
            digest.update(block)
    finally:
        os.close(fd)
    return digest.hexdigest()


def handle_train_kickoff(body: dict[str, Any] | None) -> dict[str, Any]:
    """Refuse HELPER FT kickoff without matching named-pack evidence.

    ``inbox: latest`` is never accepted for HELPER FT.
    """
    if not isinstance(body, dict):
        return _bad("body", "object", type(body).__name__)
    inbox = body.get("inbox")
    mode = body.get("mode")
    if isinstance(inbox, str) and inbox.strip().lower() == "latest":
        return _bad("inbox", "named pack_id", "latest")
    if mode == "inbox-validate":
        return _bad("mode", "helper-ft", "inbox-validate")
    if mode != "helper-ft":
        return _bad("mode", "helper-ft", mode)
    evidence = body.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        return _bad("evidence", "present", "missing")
    if evidence.get("ok") is not True:
        return _bad("evidence.ok", True, evidence.get("ok"))
    pack_id = body.get("pack_id")
    if not isinstance(pack_id, str) or not pack_id:
        return _bad("pack_id", "present", "missing")
    if evidence.get("pack_id") != pack_id:
        return _bad("pack_id", pack_id, evidence.get("pack_id"))
    computed = evidence.get("computed_shas") if isinstance(evidence.get("computed_shas"), dict) else {}
    expected = evidence.get("expected_shas") if isinstance(evidence.get("expected_shas"), dict) else {}
    paths = body.get("paths") if isinstance(body.get("paths"), dict) else {}
    for sha_field, path_key in SHA_FIELDS:
        req = body.get(sha_field)
        if not isinstance(req, str) or not req:
            return _bad(sha_field, "present", "missing")
        ev_expected = expected.get(sha_field)
        ev_computed = computed.get(sha_field)
        if ev_expected is not None and req != ev_expected:
            return _bad(sha_field, ev_expected, req)
        if ev_computed is not None and req != ev_computed:
            return _bad(sha_field, ev_computed, req)
        named = paths.get(path_key)
        if isinstance(named, str) and named:
            path = Path(named)
            if not path.is_file():
                return _bad(path_key, "present", "missing")
            actual = _sha256_file(path)
            if actual != req:
                return _bad(sha_field, req, actual)
    return {"ok": True, "pack_id": pack_id}


def main(argv: list[str] | None = None) -> int:
    del argv
    raise SystemExit("helper_ft_kickoff is a library handler; factory-trainer POSTs JSON to it")


if __name__ == "__main__":
    raise SystemExit(main())
