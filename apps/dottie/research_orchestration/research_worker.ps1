# Solo personal project, no connection to employer, built with public/free-tier only.
#
# Windows twin of research_worker.sh: single-instance wrapper for one research-loop worker.
# An exclusive lock file makes a Task Scheduler tick a no-op if the same worker is still busy
# from the previous tick — a long training run is never stacked on top of a running one.
#
# Usage: powershell -File research_worker.ps1 <ideate|implement|train|evaluate|loop> [args...]
#
# Machine-local env (Ollama URL/model, AVA_FACTORY_ROOT, timeouts) goes in
# research_env.local.ps1 next to this script (gitignored; see the .example file).

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("ideate", "implement", "train", "evaluate", "loop", "run")]
    [string]$Worker,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"

$App = Split-Path -Parent $PSScriptRoot                      # apps/dottie
$LogDir = if ($env:DOTTIE_RESEARCH_LOG_DIR) { $env:DOTTIE_RESEARCH_LOG_DIR }
          else { Join-Path $App "data\research\logs" }
New-Item -ItemType Directory -Force $LogDir | Out-Null

# Machine-local env overrides (never committed).
$LocalEnv = Join-Path $PSScriptRoot "research_env.local.ps1"
if (Test-Path $LocalEnv) { . $LocalEnv }

# Night window: a bigger model can hold the GPU when nothing else needs it.
# Set DOTTIE_OLLAMA_MODEL_NIGHT (and optionally DOTTIE_NIGHT_START/END, 24h ints,
# default 22-6) in the local env; outside the window the day model applies untouched.
#
# SCOPED TO PER-TICK WORKERS ON PURPOSE (TODOS 5.3.R41). The hour is read ONCE, here, before
# python starts. That is correct for ideate/implement/train/evaluate, which the scheduler
# invokes fresh each tick. It is meaningless for `run`, which is a FOREVER-DAEMON: a daemon
# started at 21:59 would keep the day model all night, and one started at 22:01 would keep
# the night model all day. The window it thinks it is honouring does not exist.
#
# This is also the exact feature that caused the 2026-07-20 outage: with NUM_GPU=0 the night
# model loaded 7.0 GB into SYSTEM RAM, starved the WSL2 VM to 281 MB, and took down all 14
# containers for 90+ minutes. Leaving it armed AND non-functional under the current
# architecture is the worst of both. It now refuses loudly for `run` instead of silently
# doing the wrong thing.
if ($env:DOTTIE_OLLAMA_MODEL_NIGHT -and $Worker -eq "run") {
    Write-Warning ("DOTTIE_OLLAMA_MODEL_NIGHT is set but IGNORED for the 'run' daemon: the " +
                   "night window is evaluated once at start, so a long-lived daemon would " +
                   "pin whichever model matched its start hour. Use a per-tick worker if " +
                   "you want the night model, and check free RAM first (see TODOS 5.3).")
}
if ($env:DOTTIE_OLLAMA_MODEL_NIGHT -and $Worker -ne "run") {
    $nightStart = if ($env:DOTTIE_NIGHT_START) { [int]$env:DOTTIE_NIGHT_START } else { 22 }
    $nightEnd   = if ($env:DOTTIE_NIGHT_END)   { [int]$env:DOTTIE_NIGHT_END }   else { 6 }
    $h = (Get-Date).Hour
    $inWindow = if ($nightStart -le $nightEnd) { ($h -ge $nightStart) -and ($h -lt $nightEnd) }
                else { ($h -ge $nightStart) -or ($h -lt $nightEnd) }
    if ($inWindow) { $env:DOTTIE_OLLAMA_MODEL = $env:DOTTIE_OLLAMA_MODEL_NIGHT }
}

# Prefer the app's own venv; fall back to python on PATH.
$Python = Join-Path $App ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

# Single instance per worker: open the lock file exclusively; if it is held, skip this tick.
$LockPath = Join-Path ([System.IO.Path]::GetTempPath()) "dottie_research_$Worker.lock"
try {
    $Lock = [System.IO.File]::Open($LockPath, "OpenOrCreate", "ReadWrite", "None")
} catch [System.IO.IOException] {
    # Previous tick still running — silent no-op, exactly like flock -n.
    exit 0
}

$LogFile = Join-Path $LogDir "$Worker.log"
try {
    Set-Location $App
    # $ErrorActionPreference MUST be Continue across this call. In Windows PowerShell 5.1
    # `*>>` redirects the native process's STDERR, and every stderr line is wrapped in an
    # ErrorRecord (NativeCommandError) — which, under the script-level "Stop", is a
    # TERMINATING error. torch prints FutureWarnings to stderr during the train stage and
    # the dry-run validator, so the wrapper was being killed mid-run and the daemon died
    # with it: exit 1, no python traceback, nothing in the event log.
    # MEASURED 2026-07-20: three silent daemon deaths (~05:25, ~05:42 and the 03:05 stall
    # family) all fit this signature. The python side was never at fault.
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Python -m dottie.research $Worker @Rest *>> $LogFile
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP
    exit $exitCode
} finally {
    $Lock.Close()
}
