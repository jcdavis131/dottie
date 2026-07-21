"""python -m harness [run] ... — documented CLI entrypoint.

Solo personal project, no connection to employer, built with public/free-tier only
"""

import sys

from .runner import main

if __name__ == "__main__":
    # `run` is the documented (and only) subcommand; accept and strip it so
    # `python -m harness run --mode mock` works as README/HARNESS_SPEC/CI state.
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        del sys.argv[1]
    sys.exit(main())
