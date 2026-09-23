# Pack hop interface — jcd-pc outbox → nugatron inbox — 2026-09-21

**Freeze before more parallel work** (Drip).  
**Sole writer:** Forge (harvest). **Pulse only:** Radar. **Docs:** Brief.

---

## Paths

| Side | Path |
|---|---|
| jcd-pc outbox | `C:\Users\JCD\ai-lab\hop\outbox\` |
| nugatron inbox | hop inbox awaiting UltraData / `curated_pack_v2` (Forge canonical path on nugatron) |

Transport: Tailscale hop (existing collect/hop lane). Do **not** write packs into champion serve dirs.

---

## Artifacts (deterministic)

Every hop **must** include:

1. `curated_pack_v2.jsonl` — System One rows (Choice/Score/Noul; L3 tool-gate shape per curriculum brief)  
2. `MANIFEST.json` — done evidence (below)  
3. Optional: `holdout.jsonl` or holdout ids listed in MANIFEST (≥20% never in FT)

Caps for this harvest run (Forge): agent **120** / code **80** / math **60**.

---

## `MANIFEST.json` schema (required)

```json
{
  "pack_id": "curated_pack_v2-<YYYYMMDD-HHMMSS>",
  "produced_at": "<ISO8601>",
  "producer_host": "jcd-pc",
  "rows": 0,
  "sha256_pack": "<hex of curated_pack_v2.jsonl>",
  "holdout_frac": 0.20,
  "holdout_rows": 0,
  "tier_counts": {"L0": 0, "L1": 0, "L2": 0, "L3": 0},
  "source_caps": {"agent": 120, "code": 80, "math": 60},
  "champion_touched": false,
  "live_gate_touched": false,
  "ft_kicked": false,
  "consent_champion_false": true,
  "harvest_container": "jcd-ultradata-harvest",
  "harvest_log": "C:\\\\Users\\\\JCD\\\\ai-lab\\\\harvest.log"
}
```

**Done** = outbox has both files + Radar pulse confirms nugatron inbox received matching `sha256_pack` + `rows`. No “done” without hash + row count.

---

## Consumers (read-only through interface)

| Consumer | May |
|---|---|
| nugatron inbox / registry staging | Ingest pack + MANIFEST; verify sha256 |
| Radar | Pulse outbox/inbox presence + health; no edits |
| Brief | Update lab brief from MANIFEST fields |
| FT job (later, Cam kick only) | Read pack; never if `champion_touched` path confused with HELPER |

---

## Non-goals

- Editing champion weights or `:8770` as part of hop  
- Parallel writers on `ai-lab` or hop dirs  
- Naive merge of two packs without specialist review  

---

## Related

- Conway: `/workspace/briefs/swarm-conway-control-plane-2026-09-21.md`  
- Curriculum: `/workspace/briefs/dottie-os-system-one-curriculum-2026-09-21.md`  
- Quality bar: `/workspace/briefs/dottie-os-dataset-quality-bar-2026-09-21.md`


## Cap amendment 2026-09-22

Overnight OOM on prior caps (120/80/60). Live harvest caps now **agent 40 / code 40 / math 30** (Forge lean restart). `source_caps` in MANIFEST must reflect actual run.
