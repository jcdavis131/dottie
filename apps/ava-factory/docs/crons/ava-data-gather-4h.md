---
id: ava-data-gather-4h
enabled: true
mode: task
schedule:
  kind: interval
  timezone: UTC
  at: 2026-07-11T08:00:00
  every: 4h
metadata:
  created_by: dataset_expansion
  note: HOME persona only, solo project, no employer resources
---
# Ava Dataset Expansion — Every 4h (Hatch VM Efficient Downstream)
# Solo personal project, no connection to employer, built with public/free-tier only. HOME only.

Purpose: Continuously expand training data more frequently than daily. Efficient for downstream.

**Live tested 2026-07-11 in Hatch VM:**
- 500K tokens: 35s, 5048 docs, dup filtered 13.5k, qual 10.8k, 150KB gzipped shard + 1.7M manifest (Hatch VM safe)
- 100K tokens: 967 docs, 26KB gzipped, ~8s
- Earlier 1M attempt SIGTERM after 44s in backgrounded exec (timeout) — now fixed by using 500K in Hatch VM, 10M on Alienware.
- Disk Hatch: 6.4G/100G used (7%), OK. Avail 93G.
- Guard: WORK DRIVE DETECTED correctly via gchak_health.json owner gchak@meta.com, lockedunn_health.json — blocked upload, saved to data/for_upload/

Recommended sizing:
- Hatch VM: 500K per run (00,04,08,12,16,20 UTC) = 3M/day = 90M/month safe within exec timeouts
- Alienware RTX 4090: 10M per run = 60M/day = 1.8B/month (crontab: 0 */4 * * *)

Steps:
1. cd ~/workspace/ava-agi-factory-v6-4
2. Check disk: df -h, ensure <80% usage, else rotate old shards to data/for_upload/ and clean data/daily_expanded/ keeping last 2 days.
3. Run expansion (Hatch VM size):
   python3 scripts/dataset_expansion.py --tokens 500K --phases p0_logic p1_math p2_foundation --out data/daily_expanded --upload-mode local
   - Uses simhash dedup threshold 3 + md5 + quality filter (alpha_ratio >0.6, reward >0.8)
   - Writes content-addressable shards: packed_{timestamp}_{idx}_{rand}.jsonl.gz with sha256 first12 in manifest
   - Append-only global data/manifest.jsonl with sha256_full, tokens_est, source, phase, timestamp, version
4. Check Drive guard before ANY upload:
   python3 scripts/gdrive_uploader.py --check
   - If WORK DRIVE DETECTED (owners @meta.com, health.json files like gchak_health.json), ABORT upload, save to data/for_upload/ only
   - Log warning: "WORK DRIVE DETECTED — Home/Work separation violation risk, not uploading Home data to work Drive. Please connect personal Drive jcdavis131@gmail.com or use R2"
5. If personal Drive connected AND safe:
   python3 scripts/gdrive_uploader.py --upload data/daily_expanded/ --folder Ava-Datasets-Expansion --dry-run (first)
   Then real: --upload data/daily_expanded/ --folder Ava-Datasets-Expansion
   - Batch 2 workers, dedup by sha12 in filename, retry 3x backoff
6. Else if R2 creds present (CLOUDFLARE_R2_*):
   python3 scripts/dataset_expansion.py --tokens 500K --upload-mode r2 (or 10M on Alienware)
   - Uploads to s3://ava-datasets/expansion/ with content-addressable keys
7. Else local fallback:
   - Copy manifest to data/for_upload/upload_manifest_{ts}.json
   - Write your_files/ava-agi/runs/expansion-{date}.log with tokens, shards, disk usage
   - For Alienware: rsync -avz data/daily_expanded/ your-alienware:~/ava-agi-factory-v6-4/data/daily_expanded/
8. Update STATUS.json: builder.last_expansion tokens, shards, timestamp

Efficiency:
- Chunked 50MB shards gzipped, incremental manifest push, content-addressable filename = sha256 first12 avoids re-upload
- Simhash dedup O(1) with 15k window, keeps Hatch VM RAM low (no torch needed, uses hashlib, gzip, json)
- Public pip only
- Hatch VM exec limit: keep <60s, so 500K not 10M in VM.

Compliance:
- HOME only, never touch 03_Meta_Work_ISOLATED, never upload Home data to work Drive camd@meta.com
- Disclaimer footer on all logs
- Tested: upload_manifest_20260711_134224.json saved locally, BLOCKED_WORK_DRIVE json when work detected.

Downstream usage (Alienware):
  ./scripts/local_train.sh python streaming_data.py --use_expanded data/daily_expanded/ --pack --seq 2048
  torchrun train_1b_deepspeed.py --preset mini --data_manifest data/manifest.jsonl --tokens_total 2B

Alienware crontab addition:
  0 */4 * * * cd ~/ava-agi-factory-v6-4 && python3 scripts/dataset_expansion.py --tokens 10M --phases p0_logic p1_math p2_foundation p3_code --out data/daily_expanded --upload-mode local >> logs/cron-expansion.log 2>&1

