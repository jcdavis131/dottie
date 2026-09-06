# Solo personal project, no connection to employer, built with public/free-tier only.
#
# Start the jarvisd daemon (docker-compose.jarvisd.yml) on the Windows home box and PROVE
# it answers on /api/health, in the style of restart_research.ps1. Optionally register a
# Task Scheduler task so it comes up at logon (mirrors install_tasks.ps1).
#
# ASCII-ONLY BY DESIGN: Windows PowerShell 5.1 reads .ps1 as ANSI unless the file has a
# UTF-8 BOM, so smart dashes corrupt into parser errors. Keep it plain.
#
#   .\scripts\jarvisd_start.ps1                  # up -d with the tunnel profile, wait for health
#   .\scripts\jarvisd_start.ps1 -NoTunnel        # daemon only (127.0.0.1:8790)
#   .\scripts\jarvisd_start.ps1 -Build           # rebuild the image first (after a git pull)
#   .\scripts\jarvisd_start.ps1 -Install         # register "Jarvisd daemon" at logon
#   .\scripts\jarvisd_start.ps1 -Install -NoTunnel
#   .\scripts\jarvisd_start.ps1 -Uninstall       # remove the task (containers keep running)
#   .\scripts\jarvisd_start.ps1 -Status          # compose ps + health, no changes
#   .\scripts\jarvisd_start.ps1 -Down            # stop the stack, keep the data volume
#
# Exit codes: 0 ok; 2 deploy\.env missing or JARVIS_BEARER empty; 3 Docker never came up;
# 4 compose up failed; 5 daemon never reported healthy within -WaitSeconds.

[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$NoTunnel,
    [switch]$Build,
    [switch]$Status,
    [switch]$Down,
    [int]$WaitSeconds = 120,
    [int]$DockerWaitSeconds = 180,
    [string]$TaskName = "Jarvisd daemon"
)

$ErrorActionPreference = "Stop"

$Root    = Split-Path -Parent $PSScriptRoot
$Compose = Join-Path $Root "docker-compose.jarvisd.yml"
$EnvFile = Join-Path $Root "deploy\.env"
$EnvEx   = Join-Path $Root "deploy\.env.example"
$Health  = "http://127.0.0.1:8790/api/health"
$Self    = $MyInvocation.MyCommand.Path

# Every compose call carries --env-file: ${VAR} substitution in the compose file reads the
# shell env / --env-file, NOT the service-level env_file (that only feeds the container).
$ComposeArgs = @("compose", "--env-file", $EnvFile, "-f", $Compose)
if (-not $NoTunnel) { $ComposeArgs += @("--profile", "tunnel") }

function Invoke-Compose {
    param([string[]]$Rest)
    & docker @ComposeArgs @Rest
    return $LASTEXITCODE
}

# ---- Task Scheduler ----------------------------------------------------------------------
if ($Install -or $Uninstall) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "removed existing task: $TaskName"
    }
    if ($Uninstall) {
        Write-Host "uninstalled. Containers were not touched; use -Down to stop them."
        exit 0
    }

    $scriptArgs = ""
    if ($NoTunnel) { $scriptArgs = " -NoTunnel" }
    # Hidden + NonInteractive: a visible console invites an accidental close (same lesson
    # as install_tasks.ps1). -AtLogOn needs no elevation, unlike -AtStartup.
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument ("-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass " +
                   "-File `"$Self`"$scriptArgs") `
        -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    # StartWhenAvailable: a missed logon trigger fires as soon as the scheduler can.
    # 30 min limit: this script exits once the daemon is healthy; compose keeps it running.
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings | Out-Null
    Write-Host "registered: $TaskName (at logon)"
    Write-Host "Docker Desktop must also start at login (Settings > General) or this waits up to $DockerWaitSeconds s for it."
    Write-Host "Run now:  Start-ScheduledTask -TaskName '$TaskName'"
    exit 0
}

# ---- preconditions -----------------------------------------------------------------------
Write-Host "[1] Preconditions" -ForegroundColor Cyan
if (-not (Test-Path $EnvFile)) {
    Copy-Item $EnvEx $EnvFile
    Write-Host "  created deploy\.env from the example. Set JARVIS_BEARER in it and re-run." -ForegroundColor Yellow
    Write-Host "  generate one:  python -c `"import secrets; print('jv_' + secrets.token_urlsafe(32))`"" -ForegroundColor Yellow
    exit 2
}
$vars = @{}
foreach ($line in Get-Content $EnvFile) {
    $t = $line.Trim()
    if ($t -eq "" -or $t.StartsWith("#")) { continue }
    $i = $t.IndexOf("=")
    if ($i -lt 1) { continue }
    $vars[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim()
}
if (-not $vars["JARVIS_BEARER"]) {
    Write-Host "  JARVIS_BEARER is empty in deploy\.env. jarvisd refuses a non-loopback bind without it." -ForegroundColor Red
    exit 2
}
if (-not $NoTunnel -and -not $vars["CLOUDFLARE_TUNNEL_TOKEN"]) {
    Write-Host "  CLOUDFLARE_TUNNEL_TOKEN is empty: starting the daemon only (add -NoTunnel to silence this)." -ForegroundColor Yellow
    $NoTunnel = $true
    $ComposeArgs = @("compose", "--env-file", $EnvFile, "-f", $Compose)
}
Write-Host "  deploy\.env ok (bearer set, tunnel: $(-not $NoTunnel))"

# Docker Desktop may still be booting right after logon. Try to launch it, then wait.
$dockerUp = $false
$deadline = (Get-Date).AddSeconds($DockerWaitSeconds)
$launched = $false
while ((Get-Date) -lt $deadline) {
    & docker info *> $null
    if ($LASTEXITCODE -eq 0) { $dockerUp = $true; break }
    if (-not $launched) {
        $dd = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
        if (Test-Path $dd) {
            Write-Host "  Docker engine not answering; launching Docker Desktop"
            Start-Process -FilePath $dd | Out-Null
        }
        $launched = $true
    }
    Start-Sleep -Seconds 5
}
if (-not $dockerUp) {
    Write-Host "  Docker engine did not come up within $DockerWaitSeconds s." -ForegroundColor Red
    exit 3
}
Write-Host "  docker engine up"

# ---- status / down -----------------------------------------------------------------------
if ($Status) {
    Invoke-Compose -Rest @("ps") | Out-Null
    try {
        $h = Invoke-RestMethod -Uri $Health -TimeoutSec 5
        Write-Host "  health: ok=$($h.ok) version=$($h.version) uptime_s=$($h.uptime_s) brain=$($h.brain)" -ForegroundColor Green
    } catch {
        Write-Host "  health: NOT answering on $Health" -ForegroundColor Red
        exit 5
    }
    exit 0
}
if ($Down) {
    Write-Host "[2] compose down (volume kept)" -ForegroundColor Cyan
    $rc = Invoke-Compose -Rest @("down")
    exit $rc
}

# ---- up ----------------------------------------------------------------------------------
Write-Host "[2] compose up" -ForegroundColor Cyan
$upArgs = @("up", "-d")
if ($Build) { $upArgs += "--build" }
$rc = Invoke-Compose -Rest $upArgs
if ($rc -ne 0) {
    Write-Host "  compose up failed (exit $rc)." -ForegroundColor Red
    exit 4
}

# ---- prove it ----------------------------------------------------------------------------
Write-Host "[3] Verify /api/health (up to $WaitSeconds s)" -ForegroundColor Cyan
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$ok = $null
while ((Get-Date) -lt $deadline -and -not $ok) {
    Start-Sleep -Seconds 3
    try { $ok = Invoke-RestMethod -Uri $Health -TimeoutSec 5 } catch { $ok = $null }
}
if ($ok) {
    Write-Host "  HEALTHY: version=$($ok.version) db=$($ok.db) brain=$($ok.brain)" -ForegroundColor Green
    if (-not $NoTunnel) {
        $host_ = $vars["JARVIS_PUBLIC_HOST"]
        Write-Host "  tunnel: docker compose ... logs cloudflared   (look for 'Registered tunnel connection')" -ForegroundColor Gray
        if ($host_) { Write-Host "  public check: curl https://$host_/api/health" -ForegroundColor Gray }
    }
    exit 0
}
Write-Host "  NO healthy response within $WaitSeconds s." -ForegroundColor Red
Write-Host "  docker compose --env-file deploy\.env -f docker-compose.jarvisd.yml logs jarvisd" -ForegroundColor Red
exit 5
