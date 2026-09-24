"""Shared helpers: polite cached HTTP, JSONL (optionally gzip), stable ids.

Same conventions as apps/arxiviq-factory/arxiviq_factory/common.py (curl for
the network, gzip with mtime=0 so identical content gives identical bytes).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

APP_ROOT = Path(__file__).resolve().parent.parent
SOURCES = APP_ROOT / "sources"
# data/ is gitignored repo-wide: raw responses and curated packs are regenerable.
DATA = APP_ROOT / "data"
RAW = DATA / "raw"
USER_AGENT = "atlas-outcomes/0.1 (+https://github.com/jcdavis131/dottie)"

_last: dict[str, float] = {}


class HttpError(Exception):
    def __init__(self, code: int, url: str):
        super().__init__(f"HTTP {code} from {url[:160]}")
        self.code = code


def _fetch(url: str, timeout: float) -> bytes:
    if not shutil.which("curl"):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - https URLs built here
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - https URLs built here
                return r.read()
        except urllib.error.HTTPError as e:
            raise HttpError(e.code, url) from e
    cmd = ["curl", "-sS", "-L", "--compressed", "--max-time", str(int(timeout)), "-A", USER_AGENT,
           "-w", "\n%{http_code}", url]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 15, check=False)
    if proc.returncode != 0:
        raise urllib.error.URLError(proc.stderr.decode("utf-8", "ignore")[:200])
    body, _, code = proc.stdout.rpartition(b"\n")
    status = int(code or b"0")
    if status >= 400:
        raise HttpError(status, url)
    return body


def polite_get(url: str, *, host_gap_s: float = 1.0, timeout: float = 120.0, tries: int = 4) -> bytes:
    """GET with a per-host minimum gap and retries on 429/5xx and transport errors."""
    host = url.split("/")[2]
    wait = 3.0
    for attempt in range(1, tries + 1):
        gap = host_gap_s - (time.monotonic() - _last.get(host, 0.0))
        if gap > 0:
            time.sleep(gap)
        _last[host] = time.monotonic()
        try:
            return _fetch(url, timeout)
        except HttpError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries:
                time.sleep(wait)
                wait *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError, subprocess.TimeoutExpired):
            if attempt < tries:
                time.sleep(wait)
                wait *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def cached_get(url: str, cache_name: str, *, refresh: bool = False, host_gap_s: float = 1.0) -> bytes:
    """polite_get through a gzip cache under data/raw (gitignored), so a rerun costs no requests."""
    path = RAW / f"{cache_name}.gz"
    if path.exists() and not refresh:
        return gzip.decompress(path.read_bytes())
    body = polite_get(url, host_gap_s=host_gap_s)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(body, mtime=0))
    tmp.replace(path)
    return body


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    if path.suffix == ".gz":
        with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            for row in rows:
                gz.write((json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
                n += 1
        return n
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            n += 1
    return n


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_unit(*parts: str) -> float:
    """A deterministic number in [0, 1) from the parts (seeded sampling without RNG state)."""
    h = hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()
    return int(h[:12], 16) / float(1 << 48)


def stable_id(*parts: str, n: int = 12) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()[:n]
