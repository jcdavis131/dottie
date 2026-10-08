"""`python -m factory` shim (deprecated). Delegates to dottie_loop.factory_cli."""

from __future__ import annotations

import sys

from dottie_loop.factory_cli import main

if __name__ == "__main__":
    sys.exit(main())
