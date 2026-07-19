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
    [ValidateSet("ideate", "implement", "train", "evaluate", "loop")]
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
    & $Python -m dottie.research $Worker @Rest *>> $LogFile
    exit $LASTEXITCODE
} finally {
    $Lock.Close()
}
