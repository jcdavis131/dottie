# pack_v2 UltraData handoff — executor blocked on nugatron local-exec

**Time:** 2026-09-21 ~18:30 CT  
**Executor:** sand-subagent (Forge)  
**Blocker:** Shell `machineId` is **ignored** on sand-subagent (known; see `dottieos-jev-cuda-python-inventory-2026-09-19.md`). No Tailscale from box to `100.70.133.21`. Cannot Read/Edit `C:\Users\jcdav\workspace\dottie-os\...` or run the Windows venv.

**Champion / LIVE / FT:** untouched (no curl `:8770`, no train kick).

## What is ready on the box

`/workspace/uploads/pack_v2_handoff/`

| Path | Role |
|---|---|
| `sidecar/curation/ultradata_curriculum.py` | P1 Agent / P2 Code / P3 Math curators + `curate_pack_v2` + holdout |
| `scripts/patch_hf_to_system_one.py` | Idempotent wire into existing factory (UTF-8 no BOM; backup `.bak_pre_pack_v2`) |
| `scripts/apply_and_run_pack_v2.ps1` | Copy + patch + run + smoke on nugatron |
| `scripts/smoke_pack_v2.py` | Count L3 actions / tiers / champion=false / holdout≥20% |
| `staging_box/` | Box-side UltraData-only smoke (no v1) — proves HF streaming + heuristics |

## Parent must run on nugatron (`machineId=601c5317-a131-420f-b826-ec9425042a51`)

### 1) Ferry handoff → nugatron

Copy entire `/workspace/uploads/pack_v2_handoff` to e.g.  
`C:\Users\jcdav\workspace\dottie-os\_handoff\pack_v2_handoff\`  
(via CopyFromBox / your local-exec ferry).

### 2) Apply + curate

```powershell
$env:PACK_V2_HANDOFF = "C:\Users\jcdav\workspace\dottie-os\_handoff\pack_v2_handoff"
powershell -ExecutionPolicy Bypass -File "$env:PACK_V2_HANDOFF\scripts\apply_and_run_pack_v2.ps1"
```

Or manually:

```powershell
cd C:\Users\jcdav\workspace\dottie-os
copy _handoff\pack_v2_handoff\sidecar\curation\ultradata_curriculum.py sidecar\curation\
C:\Users\jcdav\dottie\.venv\Scripts\python.exe _handoff\pack_v2_handoff\scripts\patch_hf_to_system_one.py --target sidecar\curation\hf_to_system_one.py
C:\Users\jcdav\dottie\.venv\Scripts\python.exe -m sidecar.curation.hf_to_system_one --dataset pack_v2 --n 400
C:\Users\jcdav\dottie\.venv\Scripts\python.exe registry\datasets\staging\smoke_pack_v2.py
```

Caps inside `curate_pack_v2`: agent≈400 (300–500), code≈300 (200–400), math≈200 (150–300). Carries P0 `curated_pack_v1.jsonl` if present (else component JSONLs / optional `curate_all`).

### 3) Expected outputs

- `registry\datasets\staging\curated_pack_v2.jsonl` (full)
- `registry\datasets\staging\curated_pack_v2_train.jsonl`
- `registry\datasets\staging\curated_pack_v2_holdout.jsonl` (≥20%)
- `registry\datasets\staging\curated_pack_v2_summary.json` (tiers/sources + gold heuristic doc)

## Box smoke (UltraData-only, no v1) — already ran

- total 150 · L3 80 · L2 70 · holdout 20% · champion_true 0  
- L3 actions (streaming mix): execute≈52, escalate≈27, halt≈1 (halt rare in UltraData traces; heuristics validated on synthetic destructive strings)  
- schema `dottie-os-decision-schema-1.0.0` · multi-head ≥3 questions ≈80%

## Gold heuristics (HELPER / champion:false)

Documented in module `GOLD_HEURISTICS_DOC` and summary JSON — L3 from first tool_call; HALT/ESCALATE/EXECUTE rules per brief; Math = Score+Noul only (no solution SFT); Nimble = reuse existing mined flips only.

## Do not

- Commit/push unless Cam asks  
- Kick FT  
- Touch champion `:8770` or LIVE gate code  
