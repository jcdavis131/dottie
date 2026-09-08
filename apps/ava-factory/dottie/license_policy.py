"""Canonical fail-closed license and dataset revision policy."""

from __future__ import annotations

import re

LICENSE_DENY_TOKENS = {
    "nd": "NoDerivatives — training a model on the work is a derivative use",
    "nc": "NonCommercial — incompatible with a revenue mission",
}

LICENSE_ALLOW = {
    "mit",
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "isc",
    "cc0-1.0",
    "cc-by-2.0",
    "cc-by-3.0",
    "cc-by-4.0",
    "cc-by-sa-3.0",
    "cc-by-sa-4.0",
    "odc-by-1.0",
    "odc-by",
    "pddl-1.0",
    "unlicense",
}

_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


class LicensePolicyError(ValueError):
    """A source lacks the facts required for training-data ingestion."""


def _license_values(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple, set)):
        out: list[str] = []
        for item in raw:
            out.extend(_license_values(item))
        return out
    return [str(raw)]


def gate_license(raw: object) -> tuple[bool, str]:
    """Return whether every explicit license identifier is allowlisted."""
    values = _license_values(raw)
    if not values:
        return False, "no license stated — deny by default (unverified is not permissive)"
    normalized: list[str] = []
    for value in values:
        ident = value.strip().lower()
        if not ident:
            return False, "empty license value — deny by default"
        for token, why in LICENSE_DENY_TOKENS.items():
            if token in ident.split("-"):
                return False, f"{ident}: {why}"
        if ident not in LICENSE_ALLOW:
            return False, (
                f"{ident} is not in the permissive allowlist — deny by default"
            )
        normalized.append(ident)
    return True, f"permissive: {', '.join(sorted(set(normalized)))}"


def validate_dataset_source(
    *,
    gated: bool | None,
    license_id: object,
    revision: str | None,
) -> None:
    """Reject unverified HF source metadata before any network operation."""
    if gated is not False:
        raise LicensePolicyError("dataset must explicitly declare gated: false")
    allowed, reason = gate_license(license_id)
    if not allowed:
        raise LicensePolicyError(reason)
    if not isinstance(revision, str) or _REVISION_RE.fullmatch(revision) is None:
        raise LicensePolicyError(
            "dataset revision must be a full lowercase 40-hex commit"
        )


def dataset_source_is_active(
    *,
    gated: bool | None,
    license_id: object,
    revision: str | None,
) -> bool:
    """Return false for any source that cannot pass the ingestion policy."""
    try:
        validate_dataset_source(
            gated=gated,
            license_id=license_id,
            revision=revision,
        )
    except LicensePolicyError:
        return False
    return True


__all__ = [
    "LICENSE_ALLOW",
    "LICENSE_DENY_TOKENS",
    "LicensePolicyError",
    "dataset_source_is_active",
    "gate_license",
    "validate_dataset_source",
]
