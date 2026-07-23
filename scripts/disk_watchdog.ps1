# Solo personal project, no connection to employer, built with public/free-tier only.
#
# Disk watchdog for the dottie box. Born from the 2026-07 disk-full event that took the
# whole factory down (root cause: 211GB of unpruned checkpoints inside docker_data.vhdx).
#
# REPORTS (always):
#   - C: free GB
#   - docker_data.vhdx size (the checkpoint mass lives INSIDE this VHDX, in the ava_state
#     docker volume -- it is not visible from the host filesystem, so the VHDX size is the
#     host-side proxy for it)
#   - pip cache / npm cache / %TEMP% sizes
#   - checkpoint locations: size plus a PROPOSAL line only. This script NEVER prunes them.
#
# PRUNES (only when C: free < -ThresholdGB, default 15) an explicit allowlist:
#   - pip cache                      (safe: pip re-downloads wheels on demand)
#   - npm cache                      (safe: content-addressed store, npm re-fetches)
#   - %TEMP% files older than 7 days (files only; locked files skipped silently)
# Nothing outside that allowlist is ever deleted. A guard refuses any allowlist entry
# whose path looks like a checkpoint dir or a VHDX, so a future edit cannot quietly
# widen the blast radius.
#
# ASCII-ONLY BY DESIGN: Windows PowerShell 5.1 reads .ps1 as ANSI unless the file has a
# UTF-8 BOM, so smart dashes corrupt into parser errors. Keep it plain.
#
#   .\scripts\disk_watchdog.ps1 -WhatIf              # report + show what would be pruned
#   .\scripts\disk_watchdog.ps1                      # report; prune only if below threshold
#   .\scripts\disk_watchdog.ps1 -ThresholdGB 25      # raise the prune trigger
#
# Exit codes: 0 = healthy (or prune restored headroom); 1 = still below threshold after
# the allowlist prune -- checkpoint growth is then the prime suspect, see PROPOSAL lines.

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [double]$ThresholdGB = 15,
    [string]$LogFile = ""       # optional transcript target, for scheduled-task runs
)

if ($LogFile -ne "") {
    $logDir = Split-Path $LogFile -Parent
    if ($logDir -and -not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
    Start-Transcript -Path $LogFile -Append | Out-Null
}

function Get-DirSizeGB {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    $sum = (Get-ChildItem $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
        Measure-Object Length -Sum).Sum
    if ($null -eq $sum) { $sum = 0 }
    return [math]::Round($sum / 1GB, 2)
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "=== disk watchdog $stamp (threshold ${ThresholdGB}GB) ===" -ForegroundColor Cyan

# --- report: C: headroom -------------------------------------------------------------
$freeGB = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
Write-Host ("C: free                    {0,10:N2} GB" -f $freeGB)

# --- report: docker_data.vhdx --------------------------------------------------------
# Size read via the filesystem only -- no docker/wsl commands, a trainer is live in there.
$vhdx = Join-Path $env:LOCALAPPDATA "Docker\wsl\disk\docker_data.vhdx"
if (Test-Path $vhdx) {
    $vhdxGB = [math]::Round((Get-Item $vhdx).Length / 1GB, 2)
    Write-Host ("docker_data.vhdx           {0,10:N2} GB  ({1})" -f $vhdxGB, $vhdx)
} else {
    Write-Host "docker_data.vhdx           not found at $vhdx" -ForegroundColor Yellow
}

# --- report: cache dirs --------------------------------------------------------------
$pipCache = Join-Path $env:LOCALAPPDATA "pip\cache"
$npmCache = Join-Path $env:LOCALAPPDATA "npm-cache"
$caches = @(
    @{ Name = "pip cache";  Path = $pipCache; Mode = "all" }
    @{ Name = "npm cache";  Path = $npmCache; Mode = "all" }
    @{ Name = "TEMP";       Path = $env:TEMP; Mode = "older7d" }
)
foreach ($c in $caches) {
    $gb = Get-DirSizeGB $c.Path
    if ($null -eq $gb) {
        Write-Host ("{0,-26} absent      ({1})" -f $c.Name, $c.Path) -ForegroundColor DarkGray
    } else {
        Write-Host ("{0,-26} {1,10:N2} GB  ({2})" -f $c.Name, $gb, $c.Path)
    }
}

# --- report: checkpoint locations (NEVER pruned here) --------------------------------
# The disk-full root cause. Deleting a checkpoint the live trainer still references
# bricks the run, so retention is an operator/trainer-side decision, never this script's.
$checkpointLocations = @(
    @{ Name = "trainer checkpoints (ava_state volume, inside docker_data.vhdx)"; Path = $vhdx }
    @{ Name = "ava-factory runs (host-side)"; Path = "C:\Users\jcdav\dottie\apps\ava-factory\runs" }
)
Write-Host ""
Write-Host "checkpoint locations (report-only, this script never prunes these):" -ForegroundColor Cyan
foreach ($cp in $checkpointLocations) {
    if (-not (Test-Path $cp.Path)) {
        Write-Host ("  {0}: not found" -f $cp.Name) -ForegroundColor DarkGray
        continue
    }
    $item = Get-Item $cp.Path
    if ($item.PSIsContainer) { $gb = Get-DirSizeGB $cp.Path } else { $gb = [math]::Round($item.Length / 1GB, 2) }
    Write-Host ("  {0}: {1:N2} GB" -f $cp.Name, $gb)
    Write-Host ("  PROPOSAL: operator open item -- apply a keep-last-N + keep-best retention policy from the trainer side, then compact the VHDX. Not automated here by design.") -ForegroundColor Yellow
}

# --- prune: only below threshold, only the allowlist ---------------------------------
Write-Host ""
if ($freeGB -ge $ThresholdGB) {
    Write-Host ("free {0:N2} GB >= threshold {1:N2} GB -- no pruning." -f $freeGB, $ThresholdGB) -ForegroundColor Green
    if ($LogFile -ne "") { Stop-Transcript | Out-Null }
    exit 0
}

Write-Host ("free {0:N2} GB < threshold {1:N2} GB -- pruning allowlist." -f $freeGB, $ThresholdGB) -ForegroundColor Yellow
foreach ($entry in $caches) {
    # Belt and braces: the allowlist is hardcoded above, but refuse anything that ever
    # starts to look like a checkpoint store or a VHDX.
    if ($entry.Path -match "(?i)checkpoint|\.vhdx") {
        Write-Host ("  REFUSING {0}: path matches checkpoint/vhdx guard" -f $entry.Path) -ForegroundColor Red
        continue
    }
    if (-not (Test-Path $entry.Path)) {
        Write-Host ("  skip {0}: absent" -f $entry.Name) -ForegroundColor DarkGray
        continue
    }
    if ($entry.Mode -eq "all") {
        $gb = Get-DirSizeGB $entry.Path
        if ($PSCmdlet.ShouldProcess($entry.Path, "prune $($entry.Name) contents ($gb GB)")) {
            $children = Get-ChildItem $entry.Path -Force -ErrorAction SilentlyContinue
            foreach ($ch in $children) {
                Remove-Item $ch.FullName -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue
            }
            Write-Host ("  pruned {0} ({1} GB reclaimed at most)" -f $entry.Name, $gb) -ForegroundColor Green
        }
    } else {
        # older7d: files only, so in-flight temp files and dir skeletons survive.
        $cutoff = (Get-Date).AddDays(-7)
        $old = @(Get-ChildItem $entry.Path -Recurse -File -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -lt $cutoff })
        $oldGB = [math]::Round((($old | Measure-Object Length -Sum).Sum) / 1GB, 2)
        if ($old.Count -eq 0) { Write-Host "  skip TEMP: no files older than 7 days" -ForegroundColor DarkGray; continue }
        if ($PSCmdlet.ShouldProcess($entry.Path, "delete $($old.Count) TEMP file(s) older than 7 days ($oldGB GB)")) {
            foreach ($f in $old) {
                Remove-Item $f.FullName -Force -Confirm:$false -ErrorAction SilentlyContinue
            }
            Write-Host ("  pruned TEMP: {0} file(s), {1} GB reclaimed at most" -f $old.Count, $oldGB) -ForegroundColor Green
        }
    }
}

$freeAfter = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
Write-Host ""
Write-Host ("C: free after prune        {0,10:N2} GB" -f $freeAfter)
if ($freeAfter -lt $ThresholdGB) {
    Write-Host "STILL below threshold after allowlist prune -- checkpoint growth is the prime suspect; see PROPOSAL lines above." -ForegroundColor Red
    if ($LogFile -ne "") { Stop-Transcript | Out-Null }
    exit 1
}
if ($LogFile -ne "") { Stop-Transcript | Out-Null }
exit 0
