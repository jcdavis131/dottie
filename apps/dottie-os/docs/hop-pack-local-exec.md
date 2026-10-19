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
5. On nugatron, point-of-use integrity then HELPER kick (no override, no auto-promote). The only anchor is Cam's Ed25519 signature over the canonical pin bytes in `scripts/lab/cam_pin_spec.py`, verified against `trust/cam_pin_ed25519.pub`. Swarm HQ is transport only (`GET {SWARM_HQ_ORIGIN}/api/packs/<pack_id>/pin` over HTTPS, no redirects, no `SWARM_HQ_URL` env). `stampVerified` and `pack_matches` are advisory. There is no ticket, Mill-signed, or `--cam-pin` paste path.
   `python C:\Users\jcdav\workspace\dottie-os\scripts\lab\kick_helper_ft.py --pack C:\Users\jcdav\Projects\factory-trainer\runs\inbox\<pack_id> --log C:\Users\jcdav\Projects\factory-trainer\runs\<pack_id>\helper_ft.log`
   Re-hashes pack/train/holdout while copying into a 0400/0700 run-private dir. Cam's Ed25519 pin must match both `MANIFEST.json` and the copied bytes. `--cam-pin`, a pin env var, and a local pin file are refused before hashing. After the gate passes, the script POSTs a kick event (`run_id` + input shas) to the pinned HQ origin, then POSTs `:8765/train/kickoff` itself with the named `pack_id`, shas, **run-dir copy paths only**, evidence, and the same pin. The trainer never receives the inbox/source pack path. The `:8765` handler re-fetches the pin from the pinned origin itself; a body-only pin is not provenance. `ok: true` evidence is not trust. `inbox: latest` and every other HELPER FT start route are refused. Missing pin, unreachable HQ, mismatch, missing field, or symlink exits non-zero. Evidence JSON is written in the run directory. On nugatron, the same process that launched training waits for the trainer to exit, then re-hashes the recorded run-dir paths (hostname + resolved paths + shas) into `<checkpoint>/integrity_evidence.json` (mode 0400). `result` and `sha256_evidence` are taken from that 0400 file (never scraped stdout). Nonzero trainer exit, a signal, or a timeout is `REFUSED` even when hashes match. Prints one `HELPER_FT_INTEGRITY_EVIDENCE sha256_evidence=... result=MATCH|REFUSED` line for humans, then POSTs a completion event to HQ. A local `origin/main` ancestry check is a hint only; CODEOWNERS + branch protection are the real boundary.

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
