"""Security helpers the §29 test matrix needs beyond what the kernel already enforces.

* :func:`safe_extract` — archive extraction with traversal, symlink, absolute-path
  and size-bomb protection (zip and tar).
* :func:`safe_json_load` — the only deserializer this package accepts; pickle,
  marshal and eval are never used on untrusted bytes.
* :func:`fetch_with_checked_redirects` — every hop of a redirect chain is re-checked
  against the domain/method allowlist; DNS-rebinding style host changes are denied.
* :func:`redact_for_report` — secret substrings never reach reports or comments.

Everything here fails closed: an unrecognised state raises a typed error.
"""

from __future__ import annotations

import json
import tarfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dottie_loop.errors import InvalidInputError, PolicyDeniedError
from dottie_loop.execution import canonical_in_root, check_url_allowed

if TYPE_CHECKING:
    from collections.abc import Callable

MAX_ARCHIVE_MEMBERS = 10_000
MAX_EXTRACTED_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200.0
MAX_REDIRECTS = 5


def safe_extract(archive: Path, dest: Path, *, max_bytes: int = MAX_EXTRACTED_BYTES) -> dict[str, Any]:
    """Extract only regular files whose canonical path stays inside ``dest``."""
    archive = Path(archive)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    total = 0
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ARCHIVE_MEMBERS:
                raise PolicyDeniedError("archive has too many members", field="archive")
            for info in infos:
                name = info.filename
                if name.endswith("/"):
                    continue
                if Path(name).is_absolute() or ".." in Path(name).parts:
                    raise PolicyDeniedError(f"archive member escapes destination: {name}", field="archive")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise PolicyDeniedError(f"symlink member refused: {name}", field="archive")
                if info.compress_size and info.file_size / max(1, info.compress_size) > MAX_COMPRESSION_RATIO:
                    raise PolicyDeniedError(f"compression ratio too high (bomb?): {name}", field="archive")
                total += info.file_size
                if total > max_bytes:
                    raise PolicyDeniedError("archive exceeds the extraction size cap", field="archive")
                target = canonical_in_root(name, dest)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as out:
                    out.write(src.read())
                extracted.append(name)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            members = tf.getmembers()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise PolicyDeniedError("archive has too many members", field="archive")
            for m in members:
                if m.isdir():
                    continue
                if m.issym() or m.islnk():
                    raise PolicyDeniedError(f"link member refused: {m.name}", field="archive")
                if m.isdev() or m.isfifo():
                    raise PolicyDeniedError(f"special member refused: {m.name}", field="archive")
                if Path(m.name).is_absolute() or ".." in Path(m.name).parts:
                    raise PolicyDeniedError(f"archive member escapes destination: {m.name}", field="archive")
                total += m.size
                if total > max_bytes:
                    raise PolicyDeniedError("archive exceeds the extraction size cap", field="archive")
                target = canonical_in_root(m.name, dest)
                target.parent.mkdir(parents=True, exist_ok=True)
                f = tf.extractfile(m)
                if f is None:
                    continue
                target.write_bytes(f.read())
                extracted.append(m.name)
    else:
        raise InvalidInputError("not a zip or tar archive", field="archive")
    return {"extracted": extracted, "bytes": total, "dest": str(dest)}


def safe_json_load(data: bytes | str, *, max_bytes: int = 16 * 1024 * 1024, max_depth: int = 64) -> Any:
    """JSON only. Size-capped, depth-capped, no object hooks, no NaN/Infinity constants."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > max_bytes:
        raise InvalidInputError("payload exceeds size cap", field="payload")

    def reject_constant(_c: str) -> Any:
        raise InvalidInputError("non-finite JSON constants are not accepted", field="payload")

    try:
        obj = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise InvalidInputError("payload is not valid JSON", field="payload") from e
    _check_depth(obj, max_depth)
    return obj


def _check_depth(obj: Any, remaining: int) -> None:
    if remaining <= 0:
        raise InvalidInputError("JSON nesting too deep", field="payload")
    if isinstance(obj, dict):
        for v in obj.values():
            _check_depth(v, remaining - 1)
    elif isinstance(obj, list):
        for v in obj:
            _check_depth(v, remaining - 1)


def fetch_with_checked_redirects(url: str, *, domains: list[str], methods: list[str], fetch: Callable[[str], tuple[int, str | None, bytes]], method: str = "GET") -> dict[str, Any]:
    """Follow at most MAX_REDIRECTS hops; every hop must satisfy the allowlist.

    ``fetch(url)`` returns ``(status, location_or_None, body)``. A redirect to a host
    outside the allowlist, to a private address, or over a non-http scheme is denied
    and the chain so far is reported.
    """
    chain = [url]
    check_url_allowed(url, domains, methods, method)
    for _ in range(MAX_REDIRECTS + 1):
        status, location, body = fetch(chain[-1])
        if status in (301, 302, 303, 307, 308) and location:
            check_url_allowed(location, domains, methods, method)  # re-checked per hop
            chain.append(location)
            if len(chain) > MAX_REDIRECTS + 1:
                raise PolicyDeniedError("too many redirects", field="url")
            continue
        return {"status": status, "final_url": chain[-1], "chain": chain, "body": body}
    raise PolicyDeniedError("too many redirects", field="url")


def redact_for_report(text: str, secrets: list[str]) -> str:
    out = text
    for s in secrets:
        if s and s in out:
            out = out.replace(s, "[SECRET]")
    return out
