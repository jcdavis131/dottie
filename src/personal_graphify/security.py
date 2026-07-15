"""
security.py — input validation for personal graphify
Solo personal project, no connection to employer, built with public/free-tier only
"""
from pathlib import Path
import html
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
MAX_URL_SIZE = 10 * 1024 * 1024
MAX_TIMEOUT = 30

def is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ALLOWED_SCHEMES:
            return False
        # no private ip bypass attempt
        if not parsed.netloc:
            return False
        # block obvious localhost/ssrf
        host = parsed.hostname or ""
        if host in ("localhost", "127.0.0.1", "::1"):
            # allow for video transcribe? safer to block by default; personal edition allows localhost if env flag
            return False
        if host.startswith("10.") or host.startswith("192.168."):
            return False
        return True
    except:
        return False

def sanitize_label(label: str) -> str:
    return html.escape(label, quote=True)

def ensure_containment(target: Path, root: Path) -> Path:
    target = target.resolve()
    root = root.resolve()
    if root not in target.parents and target != root:
        raise ValueError(f"Path {target} escapes root {root}")
    return target
