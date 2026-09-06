# Solo personal project, no connection to employer, built with public/free-tier only.
#
# The MLOps line's nightly window on the Windows home box (docs/FACTORY.md section 3).
# Registers ONE Task Scheduler task that runs `python -m factory train run --next` once a
# night: the first queued job whose preflight passes, logged under factory/runs/. The
# queue is the serialisation point for every GPU retrain (DAG node gpu-box-dedicated), so
# there is exactly one task and it never runs two jobs at once.
#
# Same conventions as vector-unified/SCHEDULING.md and jarvisd_start.ps1: /RL LIMITED (no
# elevation to read JSON and launch a trainer), -Install/-Uninstall/-Status/-RunNow, and
# the script only ever PROPOSES the schtasks command unless you pass -Install. Registering
# a scheduled task modifies the machine, and that is the operator's call.
#
# ASCII-ONLY BY DESIGN: Windows PowerShell 5.1 reads .ps1 as ANSI unless the file has a
# UTF-8 BOM, so smart dashes corrupt into parser errors. Keep it plain.
#
#   .\scripts\train_window.ps1                 # show the command that -Install would run
#   .\scripts\train_window.ps1 -Install        # register "Factory train window" nightly at 01:30
#   .\scripts\train_window.ps1 -Install -At 02:15
#   .\scripts\train_window.ps1 -RunNow         # fire the task once, by hand
#   .\scripts\train_window.ps1 -Status         # schtasks /Query + the last result per job
#   .\scripts\train_window.ps1 -Uninstall
#
# Exit codes: 0 ok; 2 python or the factory package not found; 3 schtasks failed.

[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Status,
    [switch]$RunNow,
    [string]$At = "01:30",
    [string]$TaskName = "Factory train window",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not $Python) {
    $venv = Join-Path $repo ".venv\Scripts\python.exe"
    if (Test-Path $venv) { $Python = $venv } else { $Python = "python" }
}
try {
    & $Python -c "import factory" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "factory not importable" }
} catch {
    Write-Host "python -m factory does not import with '$Python' from $repo. Run 'uv sync' there, or pass -Python." -ForegroundColor Red
    exit 2
}

# Task Scheduler runs with no cwd guarantee; cmd /c cd first so registries and runs/ resolve.
$log = Join-Path $repo "factory\runs\train_window.log"
$action = "cmd /c cd /d `"$repo`" && `"$Python`" -m factory train run --next >> `"$log`" 2>&1"

if ($Status) {
    schtasks /Query /TN "$TaskName" /V /FO LIST 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "task '$TaskName' is not registered" }
    Push-Location $repo
    & $Python -m factory train list
    Pop-Location
    exit 0
}
if ($Uninstall) {
    schtasks /Delete /TN "$TaskName" /F
    if ($LASTEXITCODE -ne 0) { exit 3 }
    Write-Host "removed '$TaskName'"
    exit 0
}
if ($RunNow) {
    schtasks /Run /TN "$TaskName"
    if ($LASTEXITCODE -ne 0) { exit 3 }
    Write-Host "started '$TaskName'; tail $log"
    exit 0
}

$cmd = "schtasks /Create /TN `"$TaskName`" /SC DAILY /ST $At /RL LIMITED /F /TR `"$action`""
if (-not $Install) {
    Write-Host "Would register (pass -Install to do it):"
    Write-Host "  $cmd"
    Write-Host ""
    Write-Host "Preflight now (what --next would pick tonight):"
    Push-Location $repo
    & $Python -m factory train next
    Pop-Location
    exit 0
}
schtasks /Create /TN "$TaskName" /SC DAILY /ST $At /RL LIMITED /F /TR "$action"
if ($LASTEXITCODE -ne 0) { exit 3 }
Write-Host "registered '$TaskName' daily at $At; log: $log"
exit 0
