"""Shared helpers: polite HTTP, JSONL (optionally gzip), stable ids."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
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
# data/ is gitignored repo-wide: curated packs are regenerable, never committed.
DATA = APP_ROOT / "data"
USER_AGENT = "arxiviq-factory/0.1 (+https://github.com/jcdavis131/dottie)"

_last: dict[str, float] = {}


class HttpError(Exception):
    def __init__(self, code: int, url: str, retry_after: str | None = None):
        super().__init__(f"HTTP {code} from {url[:120]}")
        self.code = code
        self.retry_after = retry_after


def _fetch(url: str, *, timeout: float, data: bytes | None, headers: dict[str, str]) -> bytes:
    """One request through curl (HTTP/2). urllib's HTTP/1.1 requests draw
    spurious 406s from export.arxiv.org behind some proxies; curl does not."""
    if not shutil.which("curl"):
        req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **headers})  # noqa: S310 - https URLs built here
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - https URLs built here
                return r.read()
        except urllib.error.HTTPError as e:
            raise HttpError(e.code, url, e.headers.get("Retry-After")) from e
    cmd = ["curl", "-sS", "-L", "--max-time", str(int(timeout)), "-A", USER_AGENT, "-D", "-", "-o", "-"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    if data is not None:
        cmd += ["--data-binary", "@-"]
    cmd.append(url)
    proc = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout + 15, check=False)
    if proc.returncode != 0:
        raise urllib.error.URLError(proc.stderr.decode("utf-8", "ignore")[:200])
    raw = proc.stdout
    # Split off the last header block (redirects and proxy CONNECT add earlier ones).
    body_at = 0
    status, retry = 0, None
    while raw.startswith(b"HTTP/", body_at):
        end = raw.find(b"\r\n\r\n", body_at)
        if end < 0:
            break
        head = raw[body_at:end].decode("latin-1")
        status = int(head.split()[1])
        m = re.search(r"(?im)^retry-after:\s*(\S+)", head)
        retry = m.group(1) if m else None
        body_at = end + 4
    if status >= 400:
        raise HttpError(status, url, retry)
    return raw[body_at:]


def polite_get(url: str, *, host_gap_s: float, timeout: float = 60.0, data: bytes | None = None, headers: dict[str, str] | None = None, tries: int = 4) -> bytes:
    """GET (or POST when data is given) with a per-host minimum gap and retries on 429/5xx."""
    host = url.split("/")[2]
    wait = 2.0
    for attempt in range(1, tries + 1):
        gap = host_gap_s - (time.monotonic() - _last.get(host, 0.0))
        if gap > 0:
            time.sleep(gap)
        _last[host] = time.monotonic()
        try:
            return _fetch(url, timeout=timeout, data=data, headers=headers or {})
        except HttpError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries:
                r = e.retry_after
                time.sleep(float(r) if r and r.isdigit() and int(r) < 120 else wait)
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
        # mtime=0 keeps the gzip bytes stable for identical content.
        with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            for row in rows:
                gz.write((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
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


def stable_id(*parts: str, n: int = 12) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()[:n]
