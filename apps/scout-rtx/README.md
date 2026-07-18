# Scout RTX Offload — Alienware RTX 4080/4090 + Scout CLI 🐾

> Solo personal project, no connection to employer, built with public/free-tier only. Fork of [jsegov/autoresearch-win-rtx](https://github.com/jsegov/autoresearch-win-rtx).

**Integrated with [jcdavis131/scout-cli](https://github.com/jcdavis131/scout-cli) — primary command `scout` (aliases `bb`, `bigbang`, `kitty`, `dv`) v0.6.0**

## Why this custom?
| Feature | Upstream win-rtx | This custom |
|---------|------------------|-------------|
| GPU | Generic 8/10GB | Alienware RTX 4080 16GB ada-16gb batch32 / RTX 4090 24GB ada-24gb-plus batch64 |
| Programs | Single | 4 tracks: base, ava, turnover, write |
| Orchestration | Manual | Scout plugin `scout rtx` + Hatch sync + PowerShell auto-loop + auto-publish |
| Offload | Local only | Cloud → local via `bb-offload/queue.json` |
| Dashboard | None | `scout rtx dashboard` + web artifact auto-reads GH releases |
| Releases | None | `gh release create` results.tsv/jsonl → dashboard 60s + hourly cron |

## Quickstart — Alienware (Windows PowerShell)
```powershell
git clone https://github.com/jcdavis131/scout-rtx.git
cd scout-rtx
.\scripts\setup-win.ps1 -Program programs\program-ava.md -Tag scout-ava
.\scripts\run-autonomous.ps1 -Program programs\program-ava.md -Tag scout-ava -MaxExperiments 20
# every 5 exps auto-publishes release, final publish at end
```

## Cloud → Local offload
```bash
# In Hatch / anywhere
scout rtx status                          # queue_pending, best val_bpb so far
scout rtx queue add --task "Optimize Ava router entropy 0.7" --program programs/program-ava.md
scout rtx queue list
scout rtx releases list                   # GH releases
scout rtx releases sync --tag v0.6.0-ava-0716
scout rtx results --best                  # best val_bpb from real runs
scout rtx dashboard                       # auto-reads every 60s
```

## GitHub Releases → Dashboard Auto-Read (v0.6.0) 🐾

```
Alienware RTX (run-autonomous.ps1 every 5 exps)
  → gh release create v0.6.0-<prog>-<MMdd-HHmm> results.tsv + results.jsonl
  → https://github.com/jcdavis131/scout-rtx/releases
  ↓
Hatch cloud (scout rtx releases list|sync)
  → api.github.com/repos/jcdavis131/scout-rtx/releases poll every 60s (client)
  → hourly server cron rtx-releases-hourly-sync (server-side)
  ↓
Dashboard rtx-offload-dashboard
  → server actions listGithubReleases + syncReleaseResults (parse TSV/JSONL dedup commit_sha)
  → UI GITHUB RELEASES section SYNC GH + IMPORT → LOG button
  → bestOverall computed from synced release results
```

### Commands

```bash
# Hatch cloud
scout --json rtx status
scout --json rtx releases list             # releases with assets
scout --json rtx releases sync --tag v0.6.0-ava-0716
scout --json rtx results --best

# Alienware
.\scripts\publish-release.ps1 -Program programs\program-ava.md -Tag v0.6.0-ava-0716
.\scripts\publish-release.ps1 -Program programs\program-ava.md  # auto tag
./scripts/publish-release.sh programs/program-ava.md v0.6.0-ava-0716

# Dashboard
scout rtx dashboard
```

### Verification (2026-07-15)

- Pipeline verified end-to-end with a demo-seeded release `v0.6.0-demo-0715`
  (`results.tsv 337B 4 rows` + `results.jsonl 625B 3 rows`). The 0.9935 val_bpb in that
  release is a **synthetic demo value, not a real training result**. Publish scripts now
  refuse to fabricate rows: they exit if `results.tsv` is missing unless `-Demo`/`--demo`
  is passed, which tags the row `status=demo`.
- GitHub API returns tag + assets verified via `scout --json rtx releases list`
- Client `releasesQuery` refetchInterval 60_000 + server cron `rtx-releases-hourly-sync` interval@1h (in scout-cli dashboard)
- Auto-publish wired in `run-autonomous.ps1` every 5 exps + final

### Programs
- `program-base.md` — RTX baseline 5-min bpb hill-climb
- `program-ava.md` — Ava v6.4 Jacobian + Router entropy + WSD + Critic hl=30 + Frontier 11 cats
- `program-turnover.md` — Turnover Shield <2MB ONNX 120d+4heads
- `program-write.md` — evolve write detector weights participial 0.5 char 0.8 phrase 3.0

### Files added v0.6.0
- `scripts/publish-release.ps1/.sh` — GH release with TSV/JSONL assets (this repo)
- `scripts/run-autonomous.ps1` auto-publish every 5 exps + final (this repo)
- `bigbang-bridge/cli.py` — `scout rtx` plugin incl. `releases list|sync` (this repo)
- Dashboard code (`server/src/actions.ts`, `server/src/schema.ts`, `drizzle/0003_add_github_releases.sql`, `client/src/App.tsx`, cron `rtx-releases-hourly-sync`) lives in [jcdavis131/scout-cli](https://github.com/jcdavis131/scout-cli), not in this repo

Solo personal project, no connection to employer, built with public/free-tier only.
