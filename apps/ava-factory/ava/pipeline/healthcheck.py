"""Container healthcheck: is this worker alive and is the manifest reachable?

Deliberately *not* a liveness check on throughput -- a collector that is
correctly paused by backpressure is healthy, not sick.
"""

from __future__ import annotations

import argparse
import sys

from ava.pipeline.manifest import Manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True, choices=["collector", "curator", "janitor"])
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    try:
        with Manifest(args.db, timeout=5.0) as m:
            m.counts_by_state()
    except Exception as exc:  # noqa: BLE001 - healthcheck reports, never raises
        print(f"{args.role}: manifest unreachable: {exc}", file=sys.stderr)
        return 1
    print(f"{args.role}: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
