"""Rewrite MANIFEST.json to pack-hop interface schema. Read-only on pack bytes except MANIFEST."""
from __future__ import annotations
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main(dest: Path) -> int:
    pack = dest / "curated_pack_v2.jsonl"
    summary_path = dest / "curated_pack_v2_summary.json"
    holdout = dest / "curated_pack_v2_holdout.jsonl"
    if not pack.is_file():
        raise SystemExit(f"missing pack: {pack}")
    with pack.open(encoding="utf-8") as pf:
        rows = sum(1 for line in pf if line.strip())
    holdout_rows = 0
    if holdout.is_file():
        with holdout.open(encoding="utf-8") as hf:
            holdout_rows = sum(1 for line in hf if line.strip())
    tier_counts = {"L0": 0, "L1": 0, "L2": 0, "L3": 0}
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        counts = summary.get("counts") or summary
        tc = counts.get("by_tier") or {}
        for k in tier_counts:
            tier_counts[k] = int(tc.get(k, 0) or 0)
        if not rows:
            rows = int(counts.get("total") or 0)
    stamp = dest.name.replace("ultradata_harvest_", "")
    manifest = {
        "pack_id": f"curated_pack_v2-{stamp}",
        "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "producer_host": "jcd-pc",
        "rows": rows,
        "sha256_pack": sha256_file(pack),
        "holdout_frac": (holdout_rows / rows) if rows else 0.0,
        "holdout_rows": holdout_rows,
        "tier_counts": tier_counts,
        "source_caps": {"agent": 120, "code": 80, "math": 60},
        "champion_touched": False,
        "live_gate_touched": False,
        "ft_kicked": False,
        "consent_champion_false": True,
        "harvest_container": "jcd-ultradata-harvest",
        "harvest_log": r"C:\Users\JCD\ai-lab\harvest.log",
    }
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0

if __name__ == "__main__":
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    raise SystemExit(main(dest))