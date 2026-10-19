#!/usr/bin/env python3
"""Mill message-only near-dup tokenizer.

Kick and Mill import this file byte-identical. Tokenize nested ``message``
strings only: NFKC, strip format/combining marks, casefold, split on
whitespace. Schema keys and question boilerplate are never tokens, so two
unrelated short Math rows do not score as near-dups.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Mapping

NEAR_DUP_TOKENIZER_PLACEHOLDER = False
NEAR_DUP_TOKENIZER_ID = "neardup_tokens-v1-dottie"

_STRIP_CATS = frozenset({"Cc", "Cf", "Mn", "Me"})
# Schema / rubric boilerplate only. Do not drop short content words ("a", "the")
# that Mill's Jaccard boundary vectors use.
_STOPWORDS = frozenset(
    {
        "type",
        "score",
        "noul",
        "instructions",
        "criteria",
        "difficulty",
        "solvable",
        "easy",
        "hard",
        "problem",
        "question",
        "questions",
        "kind",
        "math_problem",
        "schema",
        "choice",
    }
)


def tokenize_message(text: str) -> frozenset[str]:
    if type(text) is not str:
        return frozenset()
    folded = unicodedata.normalize("NFKC", text)
    folded = "".join(ch for ch in folded if unicodedata.category(ch) not in _STRIP_CATS)
    folded = unicodedata.normalize("NFKC", folded).casefold()
    return frozenset(part for part in folded.split() if part and part not in _STOPWORDS)


def tokenize_row(row: Any) -> frozenset[str]:
    texts: list[str] = []

    def walk(node: Any, *, message: bool = False) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                walk(child, message=message or key == "message")
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                walk(child, message=message)
            return
        if isinstance(node, str) and (message or not isinstance(row, Mapping)):
            texts.append(node)

    walk(row)
    tokens: set[str] = set()
    for text in texts:
        tokens.update(tokenize_message(text))
    return frozenset(tokens)
