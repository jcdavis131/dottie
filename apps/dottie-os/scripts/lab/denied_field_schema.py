#!/usr/bin/env python3
"""Denied-field schema is mill v2.2's. This file re-exports the row_fields seam.

Do not author path lists, DENY_KEYS, or schema rules here.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import row_fields

DeniedFieldError = row_fields.RowFieldsError
MILL_EXTRACT_PATHS_READY = row_fields.extract_paths_ready


def check_denied_fields(row: object) -> None:
    row_fields.check_denied(row)


def trainer_input_from_row(row: Mapping[str, Any]) -> Sequence[tuple[Any, ...]]:
    return row_fields.trainer_input_from_row(row)
