"""`python -m jarvisd` entrypoint."""

from __future__ import annotations

import sys

from jarvisd.cli import main

if __name__ == "__main__":
    sys.exit(main())
