# Solo personal project, no connection to employer, built with public/free-tier only.
#
# Windows twin of `crontab research_orchestration/crontab`: registers four Task Scheduler tasks
# with the same cadence as the cron file. Idempotent — re-running replaces the existing tasks.
#
#   Dottie Research ideate     daily 00:00   (grounds N hypotheses in baseline + dead ends)
#   Dottie Research implement  hourly :15    (draft + 4-level validation)
#   Dottie Research train      hourly :30    (real measurement; lock skips if a run is in flight)
#   Dottie Research evaluate   hourly :45    (hill-climb; promotes only on a real improvement)
#
# Run:  powershell -ExecutionPolicy Bypass -File install_tasks.ps1
# Remove all:  powershell -File install_tasks.ps1 -Uninstall

param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$Wrapper = Join-Path $PSScriptRoot "research_worker.ps1"

$Defs = @(
    @{ Name = "Dottie Research ideate";
       Args = "ideate --n 3 --bottleneck `"held-out LM loss plateaus while train loss keeps dropping (memorization gap) on the nano pilot corpus`"";
       Trigger = New-ScheduledTaskTrigger -Daily -At "00:00" },
    # 5 retries: transport failures are auto-repaired now, so the budget goes to real
    # content-level correction passes (conversion rate was 0/7 at 3 retries, 2026-07-19).
    @{ Name = "Dottie Research implement"; Args = "implement --max-retries 5";
       Trigger = New-ScheduledTaskTrigger -Once -At "00:15" `
                 -RepetitionInterval (New-TimeSpan -Hours 1) }   # no duration = repeat indefinitely,
    @{ Name = "Dottie Research train"; Args = "train --steps 150 --trainer factory";
       Trigger = New-ScheduledTaskTrigger -Once -At "00:30" `
                 -RepetitionInterval (New-TimeSpan -Hours 1) }   # no duration = repeat indefinitely,
    @{ Name = "Dottie Research evaluate"; Args = "evaluate";
       Trigger = New-ScheduledTaskTrigger -Once -At "00:45" `
                 -RepetitionInterval (New-TimeSpan -Hours 1) }   # no duration = repeat indefinitely
)

foreach ($d in $Defs) {
    $existing = Get-ScheduledTask -TaskName $d.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $d.Name -Confirm:$false
        Write-Host "removed existing task: $($d.Name)"
    }
    if ($Uninstall) { continue }

    # Hidden + NonInteractive: a visible console invites an accidental close mid-run — a tick
    # died exactly that way (LastTaskResult 0xC000013A, STATUS_CONTROL_C_EXIT, observed live).
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
    Write-Host "`nAll four research workers are on the scheduler (cadence mirrors the crontab)."
    Write-Host "Watch: python -m dottie.research status   |   logs: data\research\logs\*.log"
}
