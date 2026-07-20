# Solo personal project, no connection to employer, built with public/free-tier only.
#
# Re-enable and restart the research daemon, then PROVE it actually started on current code.
#
# ASCII-ONLY BY DESIGN: Windows PowerShell 5.1 reads .ps1 as ANSI unless the file has a
# UTF-8 BOM, so smart dashes corrupt into parser errors. Keep it plain.
#
# Why this exists: prepare_fleet_recovery.ps1 DISABLES the task as its step 1, and on
# 2026-07-20 the sequence was interrupted after that step. Training stayed off, silently,
# with no error anywhere -- the task was simply Disabled and nothing said so. Re-enabling
# is three commands plus a verification that is easy to skip, so this makes the whole
# thing one command that refuses to claim success it did not observe.
#
#   .\scripts\restart_research.ps1
#   .\scripts\restart_research.ps1 -MinFreeMB 2000    # require more headroom first

[CmdletBinding()]
param(
    [string]$TaskName = "Dottie Research runner",
    [int]$MinFreeMB = 1500,
    [int]$WaitSeconds = 90
)

function Avail { [math]::Round((Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue) }

$app = Join-Path (Split-Path -Parent $PSScriptRoot) "apps\dottie"
$log = Join-Path $app "data\research\logs\run.log"

Write-Host "[1] Preconditions" -ForegroundColor Cyan
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) { Write-Host "  task '$TaskName' NOT FOUND - nothing to start." -ForegroundColor Red; exit 1 }
Write-Host "  task state: $($task.State)"

# The daemon was OOM-killed at 110 MB free on 2026-07-20 and the 15-minute trigger fed it
# back into the same wall, so starting it into low memory just repeats that.
#
# TWO thresholds, because one is misleading. The hard floor is where a start is hopeless.
# But the loop loads an Ollama model within seconds of its first ideate -- qwen3:8b is
# ~5 GB RESIDENT (NUM_GPU=0 puts it in system RAM, which is what caused the 02:05 outage).
# So "1500 MB free" passes a naive check and then hits the wall anyway. Warn on the number
# that actually matters.
$free = Avail
$modelMB = 5200            # qwen3:8b measured resident; qwen3:14b is ~7000 and does NOT fit
Write-Host "  available memory: $free MB"
if ($free -lt $MinFreeMB) {
    Write-Host "  REFUSING to start: below the hard floor of $MinFreeMB MB. The daemon would" -ForegroundColor Red
    Write-Host "  be OOM-killed mid-stage with no traceback (TODOS 5.3.R51)." -ForegroundColor Red
    exit 2
}
if ($free -lt ($modelMB + $MinFreeMB)) {
    Write-Host "  WARNING: $free MB free, but the first ideate loads a ~$modelMB MB model into" -ForegroundColor Yellow
    Write-Host "  SYSTEM RAM, leaving roughly $($free - $modelMB) MB. That is the condition that" -ForegroundColor Yellow
    Write-Host "  killed the daemon (110 MB) and the WSL VM (281 MB) on 2026-07-20." -ForegroundColor Yellow
    Write-Host "  Proceeding, because the in-loop guard will now REFUSE stages instead of" -ForegroundColor Yellow
    Write-Host "  dying silently -- but expect refusals until memory is freed." -ForegroundColor Yellow
}

# Orphaned python children survive Stop-ScheduledTask and would race a new daemon.
$orphans = @(Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
             Where-Object { $_.CommandLine -and $_.CommandLine -match 'dottie\.research' })
if ($orphans) {
    Write-Host "  WARNING: $($orphans.Count) research process(es) already running:" -ForegroundColor Yellow
    foreach ($o in $orphans) { Write-Host "    pid $($o.ProcessId)" -ForegroundColor Yellow }
    Write-Host "  Starting now would run two daemons against one ledger. Kill them first:" -ForegroundColor Yellow
    Write-Host "    Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" |" -ForegroundColor Yellow
    Write-Host "      Where-Object { `$_.CommandLine -match 'dottie\.research' } |" -ForegroundColor Yellow
    Write-Host "      ForEach-Object { Stop-Process -Id `$_.ProcessId -Force }" -ForegroundColor Yellow
    exit 3
}

# Note the log length BEFORE starting, so the boot line we look for is provably the new one.
$before = if (Test-Path $log) { (Get-Item $log).Length } else { 0 }

Write-Host "`n[2] Enable + start" -ForegroundColor Cyan
Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
Start-ScheduledTask  -TaskName $TaskName -ErrorAction Stop
Write-Host "  enabled and started"

Write-Host "`n[3] Verify it actually booted (up to $WaitSeconds s)" -ForegroundColor Cyan
# The daemon prints a `boot` record with git_sha + prompts_sha256 at start (TODOS 5.3.R9).
# Waiting for THAT is the difference between "the scheduler accepted the request" and
# "the loop is running the code you think it is".
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$boot = $null
while ((Get-Date) -lt $deadline -and -not $boot) {
    Start-Sleep -Seconds 3
    if (-not (Test-Path $log)) { continue }
    $raw = [System.IO.File]::ReadAllBytes($log)
    $text = try { [System.Text.Encoding]::Unicode.GetString($raw) } catch { [System.Text.Encoding]::UTF8.GetString($raw) }
    foreach ($line in ($text -split "`r?`n")) {
        if ($line -match '"action":\s*"boot"') { $boot = $line }
    }
    if ($boot -and $before -gt 0 -and (Get-Item $log).Length -le $before) { $boot = $null }  # stale
}

if ($boot) {
    Write-Host "  BOOT OBSERVED:" -ForegroundColor Green
    Write-Host "    $boot"
    Write-Host "`n  Compare git_sha above with: git log --oneline -1" -ForegroundColor Gray
    Write-Host "  If they differ, the daemon is running older code and the fixes you just" -ForegroundColor Gray
    Write-Host "  committed are NOT live (TODOS 5.3.R30)." -ForegroundColor Gray
    exit 0
}

Write-Host "  NO boot line seen within $WaitSeconds s." -ForegroundColor Red
Write-Host "  The task may be queued, or the wrapper may have exited before python started." -ForegroundColor Red
Write-Host "  Check: Get-ScheduledTask -TaskName '$TaskName' | Select State" -ForegroundColor Red
Write-Host "  And the tail of: $log" -ForegroundColor Red
exit 4
