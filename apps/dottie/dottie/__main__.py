# Solo personal project, no connection to employer, built with public/free-tier only
"""Dottie CLI: ``python -m dottie serve|run|status``.

  serve  — uvicorn on the FastAPI app (default port 8100)
  run    — one task through the engine, JSON record to stdout (honest error + exit 2 when
           the backend is unavailable)
  status — the same honest status JSON the /status endpoint serves (without a task store)
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="dottie", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="run the Dottie API server")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8100)

    rp = sub.add_parser("run", help="run one task and print the trace record")
    rp.add_argument("prompt")
    rp.add_argument("--backend", default="ollama", choices=["ollama", "ava", "echo"])
    rp.add_argument("--max-steps", type=int, default=8)
    rp.add_argument("--data-dir", default=None)

    st = sub.add_parser("status", help="print the honest status JSON")
    st.add_argument("--data-dir", default=None)

    args = ap.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("dottie.api:app", host=args.host, port=args.port)
        return 0

    if args.cmd == "run":
        from dottie.engine import DottieEngine
        from dottie.policy import DottiePolicyUnavailable

        engine = DottieEngine(args.data_dir)
        try:
            record = engine.run_task(
                args.prompt, backend=args.backend, max_steps=args.max_steps
            )
        except DottiePolicyUnavailable as e:
            print(f"[dottie] backend unavailable (honest refusal, no fake reply): {e}",
                  file=sys.stderr)
            return 2
        print(json.dumps(record, indent=2))
        return 0

    if args.cmd == "status":
        from dottie.engine import DottieEngine
        from dottie.status import build_status

        print(json.dumps(build_status(DottieEngine(args.data_dir)), indent=2))
        return 0

    return 1  # pragma: no cover - argparse enforces choices


if __name__ == "__main__":
    raise SystemExit(main())
