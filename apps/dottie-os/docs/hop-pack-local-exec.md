# Hop pack jcd-pc to nugatron (local-exec / Grok Bot)

No SSH required. Agent (or Cam) runs both machine sides; box is the ferry.

## Paths
- **Source out:** `C:\Users\JCD\Projects\dataset-collect\out\<pack_id>\`
- **Stage zip (jcd):** `C:\Users\JCD\Projects\dataset-collect\out\<pack_id>.zip`
- **Box ferry:** `/workspace/uploads/hops/<pack_id>.zip`
- **Dest inbox:** `C:\Users\jcdav\Projects\factory-trainer\runs\inbox\<pack_id>\` (+ `.zip`)

## Steps
1. On **jcd-pc**: `powershell -ExecutionPolicy Bypass -File C:\Users\JCD\Projects\dataset-collect\jobs\stage-hop.ps1 [-PackId <id>]`
2. Agent: `CopyToBox` the zip from jcd to `/workspace/uploads/hops/<pack_id>.zip`
3. Agent: `CopyFromBox` the zip to `C:\Users\jcdav\Projects\factory-trainer\runs\inbox\<pack_id>.zip`
4. On **nugatron**: `powershell -ExecutionPolicy Bypass -File C:\Users\jcdav\Projects\factory-trainer\jobs\receive-hop.ps1 -ZipPath ...`
5. On nugatron, point-of-use integrity then HELPER kick (no override, no auto-promote):
   `python C:\Users\jcdav\workspace\dottie-os\scripts\lab\kick_helper_ft.py --pack C:\Users\jcdav\Projects\factory-trainer\runs\inbox\<pack_id> --log C:\Users\jcdav\Projects\factory-trainer\runs\<pack_id>\helper_ft.log`
   Re-hashes pack/train/holdout vs `MANIFEST.json` (`sha256_pack`, `sha256_train`, `sha256_holdout`). Mismatch or missing field exits non-zero. Evidence JSON is written next to the run log.
6. Optional GPU: `POST :8765/train/kickoff` only after the gate exits 0. `{"mode":"inbox-validate","inbox":"latest"}` stays validate-only (no GPU train while gated).

## Lifecycle after pack is used (Cam)
Compact → Google Drive → wipe **jcd-pc** collect artifacts only.

```powershell
# Dry-run (default): sha256 + receipt + agent handoff
powershell -ExecutionPolicy Bypass -File C:\Users\JCD\Projects\dataset-collect\jobs\archive-to-gdrive.ps1 -PackId <pack_id>

# After Drive upload verified, wipe jcd packs/out/zip only:
powershell -ExecutionPolicy Bypass -File ...\archive-to-gdrive.ps1 -PackId <pack_id> -Method manual -Execute
```

Upload path for agents: `CopyToBox` zip → `upload_file` connection `user-Google-drive` into folder e.g. `swarm-collect-archive`. Optional alternate: `-Method rclone` if Cam configures a remote.

**Never** delete `factory-trainer\runs\inbox` from this script (no mid-run inbox wipe on nugatron). Inbox retention is a separate Cam decision after train/validate completes.
