# Solo personal project, no connection to employer, built with public/free-tier only.
#
# Prepare this box for a Docker/WSL fleet recovery, then STOP and tell you what to run.
#
# ASCII-ONLY BY DESIGN: Windows PowerShell 5.1 reads .ps1 as ANSI unless the file has a
# UTF-8 BOM, so smart dashes/arrows corrupt into parser errors. Keep it plain.
#
# Why this exists: on 2026-07-20 the WSL2 VM died at ~02:05 and could not reboot, taking
# all 14 containers down for hours. It was not a Docker fault -- a CPU-resident Ollama
# model (qwen3:14b, 7.0 GB) had squeezed available memory to 281 MB, and the VM could not
# get what it needs. Running "wsl --shutdown" in that state just fails again.
#
# Order matters: the research daemon cycles every ~4 min and reloads the model within
# seconds, so freeing memory BEFORE stopping the daemon is useless.
#
#   .\scripts\prepare_fleet_recovery.ps1            # do it
#   .\scripts\prepare_fleet_recovery.ps1 -DryRun    # show what it would do, change nothing
#
# This script deliberately does NOT run "wsl --shutdown" itself: that restarts every
# container on the box, so it stays a human decision. It prints the exact command and a
# go/no-go based on measured free memory.

[CmdletBinding()]
param(
    [switch]$DryRun,
    [int]$RequiredFreeMB = 4000,
    [string]$Model = "qwen3:8b",
    [string]$TaskName = "Dottie Research runner"
)

function Get-AvailMB {
    [math]::Round((Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue)
}

function Step($n, $text) { Write-Host "`n[$n] $text" -ForegroundColor Cyan }

$before = Get-AvailMB
Write-Host "available memory before: $before MB" -ForegroundColor Yellow
if ($DryRun) { Write-Host "DRY RUN - nothing will be changed." -ForegroundColor Magenta }

# --- 1. Pause the research daemon -------------------------------------------------
Step 1 "Pause the research daemon (it holds the model resident between stages)"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "  scheduled task '$TaskName' not found - skipping" -ForegroundColor DarkGray
} elseif ($DryRun) {
    Write-Host "  would run: Stop-ScheduledTask + Disable-ScheduledTask  (state now: $($task.State))"
} else {
    Stop-ScheduledTask    -TaskName $TaskName -ErrorAction SilentlyContinue
    Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
    Write-Host "  stopped + disabled (re-enable in step 5 after the fleet is healthy)"
}

# --- 2. Release the resident model ------------------------------------------------
Step 2 "Release the Ollama model ($Model) so its RAM comes back"
if ($DryRun) {
    Write-Host "  would POST /api/generate with keep_alive=0"
} else {
    try {
        $body = @{ model = $Model; keep_alive = 0 } | ConvertTo-Json
        Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
            -ContentType "application/json" -Body $body -TimeoutSec 30 | Out-Null
        Start-Sleep -Seconds 4
        Write-Host "  unload requested"
    } catch {
        Write-Host "  Ollama did not respond ($($_.Exception.Message)) - continuing" -ForegroundColor DarkGray
    }
}

# --- 3. Check for a factory train still holding memory ----------------------------
Step 3 "Check for a research train still holding RAM (a torch process peaks ~3.8 GB)"
$heavy = Get-Process python*, llama-server -ErrorAction SilentlyContinue |
         Where-Object { $_.WorkingSet64 -gt 500MB }
if ($heavy) {
    foreach ($p in $heavy) {
        Write-Host ("  still resident: {0} (pid {1}) {2} MB" -f $p.ProcessName, $p.Id,
                    [math]::Round($p.WorkingSet64 / 1MB)) -ForegroundColor Yellow
    }
    Write-Host "  a nano train finishes in ~4 min; waiting beats killing it"
} else {
    Write-Host "  nothing heavy left resident"
}

# --- 4. Verdict --------------------------------------------------------------------
$after = Get-AvailMB
Step 4 "Result"
Write-Host ("  available memory: {0} MB -> {1} MB  (need at least {2} MB)" -f $before, $after, $RequiredFreeMB)
if ($after -ge $RequiredFreeMB) {
    Write-Host "  GO - enough headroom for the VM and the fleet." -ForegroundColor Green
} else {
    Write-Host "  NO-GO - still tight. Close some browser/editor sessions, or wait for a" -ForegroundColor Red
    Write-Host "  train to finish, then re-run this script." -ForegroundColor Red
}

Write-Host ""
Write-Host "NEXT (run these yourself - they restart every container on this box):" -ForegroundColor Gray
Write-Host '  wsl --shutdown        # if the engine does not return in ~2 min, restart Docker Desktop' -ForegroundColor Gray
Write-Host '  docker ps --format "{{.Names}}`t{{.Status}}"     # expect 13-14 containers' -ForegroundColor Gray
Write-Host ""
Write-Host "DECIDE before the fleet returns - the T9.4 chat trainer AUTO-RESUMES from" -ForegroundColor Gray
Write-Host "step_15.pt (its container has --restart on-failure AND --resume). Its step-15" -ForegroundColor Gray
Write-Host "gate already showed +2.04% general CE, the same forgetting mode that failed" -ForegroundColor Gray
Write-Host "T9.3. To stop it instead:" -ForegroundColor Gray
Write-Host "  docker update --restart no dottie-chat-branch" -ForegroundColor Gray
Write-Host "  docker stop dottie-chat-branch" -ForegroundColor Gray
Write-Host ""
Write-Host "THEN bring research back:" -ForegroundColor Gray
Write-Host "  Enable-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Gray
Write-Host "  Start-ScheduledTask  -TaskName '$TaskName'" -ForegroundColor Gray
