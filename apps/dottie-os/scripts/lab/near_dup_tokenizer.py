#!/usr/bin/env python3
"""Mill message-only near-dup tokenizer (vendored path).

Kick and Mill load this file by sha256 from CODE_PINS. Until Mill vendors
the live tokenizer, this placeholder fails closed. Tests inject a stand-in
via ``content_uuid.install_test_near_dup_tokenizer``; that stand-in is never
shipped in this module.
"""
from __future__ import annotations

from typing import Any

# Explicit placeholder. Cam/Mill replace this file and the CODE_PINS sha together.
NEAR_DUP_TOKENIZER_PLACEHOLDER = True
NEAR_DUP_TOKENIZER_ID = "NEAR_DUP_TOKENIZER_SHA256_PLACEHOLDER_NOT_A_LIVE_FILE"


def tokenize_message(_text: str) -> frozenset[str]:
    raise RuntimeError(
        "near_dup_tokenizer: Mill tokenizer not vendored "
        f"({NEAR_DUP_TOKENIZER_ID})"
    )


def tokenize_row(_row: Any) -> frozenset[str]:
    raise RuntimeError(
        "near_dup_tokenizer: Mill tokenizer not vendored "
        f"({NEAR_DUP_TOKENIZER_ID})"
    )
