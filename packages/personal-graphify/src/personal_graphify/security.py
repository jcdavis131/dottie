"""
security.py — input validation for personal graphify
Solo personal project, no connection to employer, built with public/free-tier only
"""

import html
from pathlib import Path

# NOTE: no URL-fetching code path exists in this tool, so there is deliberately no
# is_safe_url/SSRF machinery here — vacuous security code would only misstate the
# real surface (local files + local HTTP server).


def sanitize_label(label: str) -> str:
    return html.escape(label, quote=True)


def ensure_containment(target: Path, root: Path) -> Path:
    target = target.resolve()
    root = root.resolve()
    if root not in target.parents and target != root:
        raise ValueError(f"Path {target} escapes root {root}")
    return target
