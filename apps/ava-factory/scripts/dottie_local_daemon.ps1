# Solo personal project, no connection to employer, built with public/free-tier only
# Dottie Local Daemon — Alienware Windows PowerShell version
# 4h data 10M loop, daily train, logs to logs/dottie_local.log
# Usage: .\scripts\dottie_local_daemon.ps1 -Mode start|run-once|stop|status

param(
  [string]$Mode = "start",
  [string]$Tokens = "10M",
  [switch]$Full = $true,
  [switch]$DryRun
)

$Disclaimer = "Solo personal project, no connection to employer, built with public/free-tier only"
Write-Host "[$Disclaimer] Dottie Local Daemon Windows"

$ScriptDir = $PSScriptRoot
$RepoDir = Split-Path -Parent $ScriptDir
$LogFile = Join-Path $RepoDir "logs\dottie_local.log"
$null = New-Item -ItemType Directory -Force -Path (Join-Path $RepoDir "logs"), (Join-Path $RepoDir "reports"), (Join-Path $RepoDir "data\daily_expanded") | Out-Null

function Write-Log($msg) {
  $ts = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
  $line = "[$ts] $msg"
  Write-Host $line
  Add-Content -Path $LogFile -Value $line
}

function Run-Once {
  Write-Log "Run once start Full=$Full Tokens=$Tokens"
  $dry = if ($DryRun) { "--dry-run" } else { "" }
  $fullFlag = if ($Full) { "--full" } else { "" }

  try {
    Write-Log "Data $Tokens expansion start"
    $cmd = "python scripts/dottie_continuous_loop.py --mode data --tokens $Tokens $fullFlag $dry"
    Invoke-Expression "cd `"$RepoDir`"; $cmd" | Tee-Object -FilePath $LogFile -Append
  } catch { Write-Log "Data failed $_" }

  try {
    Write-Log "Ecosystem"
    Invoke-Expression "cd `"$RepoDir`"; python scripts/dottie_continuous_loop.py --mode ecosystem $dry" | Tee-Object -FilePath $LogFile -Append
  } catch { Write-Log "Eco failed $_" }

  try {
    Write-Log "Train mini"
    Invoke-Expression "cd `"$RepoDir`"; python scripts/dottie_continuous_loop.py --mode train --preset mini --steps 1000 --resume $dry" | Tee-Object -FilePath $LogFile -Append
  } catch { Write-Log "Train failed $_" }

  try {
    Write-Log "Eval"
    Invoke-Expression "cd `"$RepoDir`"; python scripts/dottie_continuous_loop.py --mode eval --branch all $dry" | Tee-Object -FilePath $LogFile -Append
  } catch { Write-Log "Eval failed $_" }

  Write-Log "Run once finished"
}

switch ($Mode.ToLower()) {
  "run-once" { Run-Once }
  "daemon" {
    Write-Log "Daemon loop start (Ctrl+C to stop)"
    while ($true) {
      Run-Once
      Write-Log "Sleeping 4h"
      Start-Sleep -Seconds 14400
    }
  }
  "start" {
    Write-Log "Starting Task Scheduler jobs (see instructions below) and running once"
    Run-Once
    Write-Host ""
    Write-Host "Task Scheduler instructions:"
    Write-Host "1. Open Task Scheduler -> Create Task"
    Write-Host "2. General: Dottie-Data-4h, run whether user logged in"
    Write-Host "3. Trigger: Daily, repeat every 4h"
    Write-Host "4. Action: Start program: powershell.exe Args: -ExecutionPolicy Bypass -File $RepoDir\scripts\dottie_local_daemon.ps1 -Mode run-once -Tokens 10M"
    Write-Host "5. Condition: Uncheck 'power' restrictions"
    Write-Host "6. Duplicate for train weekly: Trigger weekly Sun 3am, Action -Mode train"
    Write-Host ""
    Write-Host "Or via cmd: schtasks /create /tn DottieData4h /tr `"powershell -File $RepoDir\scripts\dottie_local_daemon.ps1 -Mode run-once`" /sc hourly /mo 4 /st 00:00"
  }
  "stop" {
    Write-Log "Stop not implemented for PowerShell jobs, check Task Scheduler"
  }
  "status" {
    Get-Content $LogFile -Tail 50
  }
  default { Write-Host "Usage: .\dottie_local_daemon.ps1 -Mode start|run-once|daemon|status" }
}

Write-Host ""
Write-Host "Logs: $LogFile"
Write-Host "Reports: $RepoDir\reports\dottie_live_status.json + dottie_telemetry.jsonl"
Write-Host "Compliance: $Disclaimer"
