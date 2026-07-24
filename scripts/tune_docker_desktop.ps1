# Solo personal project, no connection to employer, built with public/free-tier only.
#
# Tune Docker Desktop's settings for the dottie research-loop workload.
#
# ASCII-ONLY BY DESIGN: Windows PowerShell 5.1 reads .ps1 as ANSI unless the file has a
# UTF-8 BOM, so smart dashes corrupt into parser errors. Keep it plain.
#
# MUST RUN WITH DOCKER DESKTOP STOPPED. It rewrites settings-store.json, which Docker
# Desktop reads at start and REWRITES on exit -- editing it live gets silently clobbered.
#
#   .\scripts\tune_docker_desktop.ps1 -WhatIf     # show the diff, change nothing
#   .\scripts\tune_docker_desktop.ps1
#
# Companion to .wslconfig, which governs the VM's RAM/CPU and was tuned separately.

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$IncludeOptional   # also disable Docker AI / SBOM background indexing
)

$settings = Join-Path $env:APPDATA "Docker\settings-store.json"
if (-not (Test-Path $settings)) { Write-Host "settings-store.json not found at $settings" -ForegroundColor Red; exit 1 }

# Refuse to run while Docker Desktop is up: it rewrites this file on exit, so any change
# made now would be lost without any error to show for it.
$running = Get-Process -Name "Docker Desktop", "com.docker.backend" -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "Docker Desktop is RUNNING ($($running.Count) process(es))." -ForegroundColor Red
    Write-Host "It rewrites settings-store.json on exit, so edits made now are silently lost." -ForegroundColor Red
    Write-Host "Quit Docker Desktop from the tray, then re-run this script." -ForegroundColor Red
    exit 2
}

$json = Get-Content $settings -Raw | ConvertFrom-Json

# key -> @(desired value, why)
$changes = [ordered]@{
    # The whole point of this project is a loop that runs unattended. With AutoStart false,
    # a reboot leaves the fleet down until a human notices -- the same failure mode that
    # left Ollama dead after an unattended reboot on 2026-07-20.
    "AutoStart" = @($true, "fleet must survive a reboot without a human")

    # Resource Saver pauses the VM after AutoPauseTimeoutSeconds of no container activity.
    # For a 24/7 training fleet whose containers carry --restart on-failure and --resume,
    # a paused VM adds wake latency and has been a source of 'engine unresponsive' states.
    # The research loop also idles between stages by design, which is exactly the pattern
    # that trips this.
    "UseResourceSaver" = @($false, "do not pause a 24/7 fleet that idles between stages")

    # Belt and braces: if Resource Saver is ever re-enabled from the UI, do not let it act
    # on a 5-minute idle window.
    "AutoPauseTimeoutSeconds" = @(3600, "if re-enabled, one hour not five minutes")
}

if ($IncludeOptional) {
    # Background image indexing on a box whose binding constraint is RAM. Useful features,
    # but they compete with llama-server and the fleet for the same 15.7GB.
    $changes["SbomIndexing"] = @($false, "background indexing competes for scarce RAM")
    $changes["EnableDockerAI"] = @($false, "same; re-enable when the box is not memory-bound")
}

Write-Host "Current -> desired:" -ForegroundColor Cyan
$dirty = $false
foreach ($k in $changes.Keys) {
    $want = $changes[$k][0]
    $why = $changes[$k][1]
    $have = $json.$k
    if ($have -ne $want) {
        $dirty = $true
        Write-Host ("  {0,-26} {1,-8} -> {2,-8}  ({3})" -f $k, $have, $want, $why) -ForegroundColor Yellow
    } else {
        Write-Host ("  {0,-26} {1,-8} already correct" -f $k, $have) -ForegroundColor DarkGray
    }
}

# Informational only: this one LOOKS alarming and is not. Verified 2026-07-20 by reading
# /proc/meminfo inside the distro -- the VM reported 9,942MB and 24 CPUs, matching
# .wslconfig exactly, not this 2048. MemoryMiB governs the Hyper-V backend; with the WSL2
# backend it is inert. Do not "fix" it.
Write-Host ""
Write-Host ("NOTE: MemoryMiB is {0} in this file, which looks like a 2GB cap. It is INERT" -f $json.MemoryMiB) -ForegroundColor Gray
Write-Host "      on the WSL2 backend -- the VM measured 9,942MB, matching .wslconfig." -ForegroundColor Gray
Write-Host "      Set VM memory in .wslconfig, not here." -ForegroundColor Gray

if (-not $dirty) { Write-Host "`nNothing to change." -ForegroundColor Green; exit 0 }

if ($PSCmdlet.ShouldProcess($settings, "apply $($changes.Count) setting(s)")) {
    $backup = "$settings.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Copy-Item $settings $backup
    Write-Host "`nbacked up to $backup" -ForegroundColor Gray
    foreach ($k in $changes.Keys) { $json.$k = $changes[$k][0] }
    $json | ConvertTo-Json -Depth 10 | Set-Content $settings -Encoding utf8
    Write-Host "written. Start Docker Desktop to apply." -ForegroundColor Green
}
