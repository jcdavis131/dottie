# Solo personal project, no connection to employer, built with public/free-tier only.
#
# Registers the CONTINUOUS research runner on Windows Task Scheduler (replaces the old
# four per-stage hourly tasks — those are removed on every install). The runner chains
# evaluate -> train -> implement -> ideate the moment each stage finishes; see
# `python -m dottie.research run --help` for the policy and back-off semantics.
#
#   Dottie Research runner    at startup + hourly heartbeat (self-heal: the heartbeat
#                             no-ops while the runner holds the wrapper lock, and
#                             restarts it within the hour if it died)
#
# Run:  powershell -ExecutionPolicy Bypass -File install_tasks.ps1
# Remove all:  powershell -File install_tasks.ps1 -Uninstall

param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$Wrapper = Join-Path $PSScriptRoot "research_worker.ps1"

# Legacy per-stage tasks (pre-runner cadence) — removed on every install.
$Legacy = @("Dottie Research ideate", "Dottie Research implement",
            "Dottie Research train", "Dottie Research evaluate")
foreach ($l in $Legacy) {
    if (Get-ScheduledTask -TaskName $l -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $l -Confirm:$false
        Write-Host "removed legacy task: $l"
    }
}

# 5 retries: transport failures are auto-repaired, so the budget goes to real
# content-level correction passes. ExecutionTimeLimit zero — runs forever by design.
$Defs = @(
    @{ Name = "Dottie Research runner";
       Args = ("run --trainer factory --steps 150 --max-retries 5 --n 3 " +
               "--bottleneck `"held-out LM loss plateaus while train loss keeps " +
               "dropping (memorization gap) on the nano pilot corpus`"");
       # Hourly heartbeat only: -AtStartup needs admin elevation (0x80070005 observed).
       # StartWhenAvailable fires a missed heartbeat at logon, so a reboot costs at
       # most one hour of runner downtime — acceptable, no elevation required.
       Trigger = New-ScheduledTaskTrigger -Once -At "00:05" `
                    -RepetitionInterval (New-TimeSpan -Hours 1) }
)

foreach ($d in $Defs) {
    $existing = Get-ScheduledTask -TaskName $d.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $d.Name -Confirm:$false
        Write-Host "removed existing task: $($d.Name)"
    }
    if ($Uninstall) { continue }

    # Hidden + NonInteractive: a visible console invites an accidental close mid-run
    # (LastTaskResult 0xC000013A, observed live).
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument ("-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass " +
                   "-File `"$Wrapper`" $($d.Args)")
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $d.Name -Action $action -Trigger $d.Trigger `
        -Settings $settings | Out-Null
    Write-Host "registered: $($d.Name)"
}

if (-not $Uninstall) {
    Write-Host "`nContinuous research runner is on the scheduler (startup + hourly self-heal)."
    Write-Host "Watch: python -m dottie.research status   |   logs: data\research\logs\run.log"
}
