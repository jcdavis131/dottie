# Disk watchdog — scheduled task proposal (OPERATOR OPEN ITEM, not registered)

Status: **PROPOSED ONLY.** Nothing has been registered. Run the block below in an elevated
PowerShell if you want the watchdog on a schedule.

## Why

The 2026-07 disk-full event took the whole factory down; root cause was 211GB of unpruned
checkpoints inside `docker_data.vhdx` (currently ~363GB). `scripts\disk_watchdog.ps1`
reports headroom on every run and, only when C: free drops below 15GB, prunes an explicit
allowlist (pip cache, npm cache, %TEMP% files older than 7 days). It **never** touches
checkpoints or the VHDX — those get a report + proposal line only, because deleting a
checkpoint the live trainer references bricks the run.

## Exact command proposed

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\Users\jcdav\dottie\scripts\disk_watchdog.ps1" -ThresholdGB 15 -LogFile "C:\Users\jcdav\dottie\logs\disk_watchdog.log"'
$trigger = New-ScheduledTaskTrigger -Daily -At 06:30
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "Dottie Disk Watchdog" -Action $action -Trigger $trigger `
    -Settings $settings `
    -Description "Reports C: headroom + docker_data.vhdx + cache sizes; prunes pip/npm/temp allowlist only when free < 15GB. Never prunes checkpoints."
```

Notes for the operator:

- Daily at 06:30 keeps it clear of the 10-minute "Dottie Status publisher" cadence and of
  overnight training checkpoint writes.
- The script exits 1 when C: is still below threshold *after* the allowlist prune — that is
  the "checkpoints are eating the disk again" signal. `-LogFile` appends a transcript so
  the history survives unattended runs.
- Watchdog exit 1 means the real fix is trainer-side checkpoint retention
  (keep-last-N + keep-best) followed by VHDX compaction — both are operator actions with
  the trainer stopped, deliberately not automated here.
- Dry-run any time with: `.\scripts\disk_watchdog.ps1 -WhatIf` (optionally
  `-ThresholdGB 99` to preview the prune lines while headroom is healthy).
