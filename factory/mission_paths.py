"""Fail-closed filesystem containment for mission inputs and publication."""

from __future__ import annotations

import stat
from pathlib import Path

from factory.config import FactoryError

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_link_or_reparse(path: Path) -> bool:
    details = path.lstat()
    attributes = getattr(details, "st_file_attributes", 0)
    return stat.S_ISLNK(details.st_mode) or bool(
        attributes & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def contained_path(
    root: Path,
    candidate: Path,
    *,
    require_file: bool = False,
) -> Path:
    """Return an absolute path only when no existing component can redirect it."""
    root = Path(root).absolute()
    candidate = Path(candidate).absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise FactoryError(f"path escapes containment root: {candidate}") from exc

    current = root
    for component in (Path(), *relative.parents[::-1], relative):
        path = root / component
        if path.exists() or path.is_symlink():
            if _is_link_or_reparse(path):
                raise FactoryError(f"symlink or reparse point is forbidden: {path}")
            current = path

    resolved_root = root.resolve(strict=True)
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise FactoryError(f"resolved path escapes containment root: {candidate}") from exc
    if require_file and (not candidate.is_file() or _is_link_or_reparse(candidate)):
        raise FactoryError(f"contained regular file is required: {candidate}")
    return candidate


def same_file(left: Path, right: Path) -> bool:
    """Compare ownership through stable filesystem identity."""
    try:
        return left.samefile(right)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise FactoryError(
            f"filesystem identity could not be verified: {left} vs {right}"
        ) from exc
