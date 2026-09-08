"""Build the public harness status page without publishing unverified claims."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = PACKAGE_ROOT / "index.html"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Dottie Harness API</title>
<style>
:root { color-scheme: light dark; font-family: system-ui, sans-serif; }
body { margin: 0; padding: 2rem; background: Canvas; color: CanvasText; }
main { max-width: 44rem; margin: 10vh auto; }
.card { border: 1px solid GrayText; border-radius: .75rem; padding: 1.5rem; }
h1 { margin-top: 0; }
code { font-family: ui-monospace, monospace; }
.status { font-weight: 700; }
</style>
</head>
<body>
<main>
<section class="card" aria-labelledby="title">
<h1 id="title">Dottie Harness API</h1>
<p class="status">Service boundary available; production artifacts unavailable.</p>
<p>No production model, corpus, analytics, or vector artifact is available.</p>
<p>Synthetic fallbacks are disabled. Protected routes require a separately configured
<code>HARNESS_API_BEARER</code>. Only <code>GET /api/health</code> is public.</p>
<p>This page intentionally publishes no model result, corpus count, benchmark,
operational metric, filesystem path, or API success simulation.</p>
</section>
</main>
</body>
</html>
"""


def atomic_write_utf8(path: Path, contents: str) -> None:
    expected = contents.encode("utf-8")
    if path.exists() and path.read_bytes() != expected:
        raise RuntimeError(f"refusing to overwrite non-identical output: {path}")

    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(contents, encoding="utf-8", newline="\n")
        if temporary.read_bytes() != expected:
            raise RuntimeError(f"UTF-8 parity check failed for generated output: {path}")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build() -> None:
    atomic_write_utf8(OUTPUT, PAGE)
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
