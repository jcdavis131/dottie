param(
    [switch]$Watch,
    [int]$IntervalSec = 30,
    [string]$HatchSyncPath = ""  # optionally copy to Hatch cloud via mounted drive / WSL / etc
)

# Sync results back to Hatch cloud for bb rtx results
# Watches bb-offload/results/results.jsonl and copies/prints

$ErrorActionPreference = "Continue"
$resultsFile = "bb-offload/results/results.jsonl"
$queueFile = "bb-offload/queue.json"

Write-Host "=== Hatch Sync ===" -ForegroundColor Cyan
Write-Host "Local results: $resultsFile"
Write-Host "Queue: $queueFile"
if ($HatchSyncPath) { Write-Host "Hatch sync path: $HatchSyncPath" }

function Show-Status {
    if (Test-Path $resultsFile) {
        $lines = Get-Content $resultsFile | Measure-Object -Line
        Write-Host "Results lines: $($lines.Lines)" -ForegroundColor Green
        Get-Content $resultsFile -Tail 5 | ForEach-Object { Write-Host $_ }
        # Also show best val_bpb
        try {
            $best = Get-Content $resultsFile | ConvertFrom-Json | Sort-Object val_bpb | Select-Object -First 1
            if ($best) { Write-Host "Best: val_bpb=$($best.val_bpb) commit=$($best.commit) program=$($best.program)" -ForegroundColor Cyan }
        } catch {}
    } else {
        Write-Host "No results yet" -ForegroundColor Yellow
    }
    if (Test-Path $queueFile) {
        Write-Host "Queue file exists, tasks:" -ForegroundColor Yellow
        Get-Content $queueFile | Write-Host
    }
    if (Test-Path "results.tsv") {
        Write-Host "`nresults.tsv tail:" -ForegroundColor Yellow
        Get-Content results.tsv -Tail 10 | Write-Host
    }
}

if (-not $Watch) {
    Show-Status
    Write-Host "`nTo watch: .\scripts\sync-to-hatch.ps1 -Watch"
    exit 0
}

Write-Host "Watching every $IntervalSec sec — Ctrl+C to stop" -ForegroundColor Cyan
while ($true) {
    Clear-Host
    Write-Host "=== Hatch Sync Watch $(Get-Date) ===" -ForegroundColor Cyan
    Show-Status

    if ($HatchSyncPath -and (Test-Path $resultsFile)) {
        try {
            Copy-Item $resultsFile $HatchSyncPath -Force
            Write-Host "Copied to $HatchSyncPath" -ForegroundColor Green
        } catch {
            Write-Host "Copy failed: $_" -ForegroundColor Red
        }
    }

    Start-Sleep -Seconds $IntervalSec
}
