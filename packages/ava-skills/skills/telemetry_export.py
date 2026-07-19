"""
telemetry_export — cron entrypoint: flush J-Space task_logs into the telemetry JSONL.

`python -m skills.telemetry_export --path <reports>/dottie_telemetry.jsonl` appends only
records newer than the stored watermark (see JSpaceStateStore.export_telemetry_incremental),
so an hourly scheduled task is idempotent. The path is passed by the machine-local task
registration — the module has no baked-in box paths.

Solo personal project, no connection to employer, built with public/free-tier only.
"""
from __future__ import annotations

import argparse
import json

from skills.state_store import JSpaceStateStore, default_db_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.telemetry_export")
    ap.add_argument("--path", required=True, help="JSONL file to append to (gitignored!)")
    args = ap.parse_args(argv)
    with JSpaceStateStore() as st:
        n = st.export_telemetry_incremental(args.path)
    print(json.dumps({"ok": True, "exported": n, "path": args.path,
                      "db": str(default_db_path())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
