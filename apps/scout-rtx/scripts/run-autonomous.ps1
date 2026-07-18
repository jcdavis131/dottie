param(
    [string]$Program = "program.md",
    [string]$Tag = "",
    [int]$MaxExperiments = 0,  # 0 = infinite
    [string]$BranchPrefix = "autoresearch"
)

# Autonomous research loop for Windows — tailored for Alienware RTX 4080/4090
# Solo personal project, no connection to employer

$ErrorActionPreference = "Continue"
if (-not $Tag) { $Tag = "rtx-" + (Get-Date -Format "MMMdd-HHmm") }
$branch = "$BranchPrefix/$Tag"

Write-Host "=== Autonomous Research Loop ===" -ForegroundColor Cyan
Write-Host "Program: $Program  Branch: $branch  MaxExperiments: $(if($MaxExperiments -eq 0){'infinite'}else{$MaxExperiments})"

# Ensure branch
try {
    $existing = git branch --list $branch
    if (-not $existing) {
        git checkout -b $branch
        Write-Host "Created branch $branch" -ForegroundColor Green
    } else {
        git checkout $branch
        Write-Host "Checked out existing branch $branch" -ForegroundColor Yellow
    }
} catch {
    Write-Host "Git branch creation failed, continuing on current branch" -ForegroundColor Yellow
}

# Ensure results.tsv exists
if (-not (Test-Path "results.tsv")) {
    "commit`tval_bpb`tmemory_gb`tstatus`tdescription" | Out-File -Encoding utf8 results.tsv
}

# Copy program if needed
if ($Program -ne "program.md" -and (Test-Path $Program)) {
    Copy-Item $Program program.md -Force
    Write-Host "Active program set to $Program" -ForegroundColor Green
}

$expCount = 0
while ($true) {
    $expCount++
    if ($MaxExperiments -gt 0 -and $expCount -gt $MaxExperiments) { break }

    # Reset per-iteration state so stale values (e.g. a previous crash description)
    # never leak into this experiment's log row.
    $desc = ""
    $val_bpb = 0.0
    $peak_mb = 0.0
    $status = "crash"

    Write-Host "`n--- Experiment #$expCount at $(Get-Date) ---" -ForegroundColor Cyan

    # Agent prompt — tell Claude/Codex to do one iteration
    # This script is meant to be run alongside your agent (Claude Code etc) that edits train.py
    # If you're running manually without agent, it will just run baseline repeatedly

    # Run training
    $logFile = "run.log"
    Write-Host "Running uv run train.py > $logFile  (5-min budget)..." -ForegroundColor Yellow
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        # Redirect all output, no tee to keep agent context clean
        uv run train.py > $logFile 2>&1
    } catch {
        Write-Host "train.py failed to start: $_" -ForegroundColor Red
    }
    $sw.Stop()

    if (-not (Test-Path $logFile)) {
        Write-Host "No run.log, treating as crash" -ForegroundColor Red
        $val_bpb = 0.0
        $peak_mb = 0.0
        $status = "crash"
        $desc = "no log"
    } else {
        $valLine = Select-String -Path $logFile -Pattern "^val_bpb:" | Select-Object -Last 1
        $memLine = Select-String -Path $logFile -Pattern "^peak_vram_mb:" | Select-Object -Last 1
        if (-not $valLine) {
            Write-Host "Crash detected, tail 50 lines:" -ForegroundColor Red
            Get-Content $logFile -Tail 50 | Write-Host
            $val_bpb = 0.0
            $peak_mb = 0.0
            $status = "crash"
            $desc = "crash"
        } else {
            $val_bpb = [double]($valLine.Line -replace ".*val_bpb:\s*","" -replace "\s.*","" ).Trim()
            if ($memLine) {
                $peak_mb = [double]($memLine.Line -replace ".*peak_vram_mb:\s*","" -replace "\s.*","" ).Trim()
            } else { $peak_mb = 0 }
            Write-Host "Result: val_bpb=$val_bpb peak_mb=$peak_mb" -ForegroundColor Green
            $status = "keep" # agent will decide keep/discard via git, this script just runs

            # Timeout check >10 min
            if ($sw.Elapsed.TotalSeconds -gt 600) {
                Write-Host "Timeout >10min, discarding" -ForegroundColor Red
                $status = "discard"
            }
        }
    }

    # Git commit hash short
    try {
        $commit = (git rev-parse --short HEAD).Trim()
    } catch { $commit = "unknown" }

    $mem_gb = if ($peak_mb -gt 0) { [math]::Round($peak_mb/1024,1) } else { 0.0 }

    # If program-ava/turnover/write, also prepare custom jsonl logs (if train.py wrote custom metrics)
    # For now, just log TSV
    if (-not $desc) { $desc = "exp $expCount $Program" }

    # Append to TSV — always record every measurement (repeated runs of the same
    # commit are distinct data points; the old commit-based dedup dropped them)
    $tsvLine = "$commit`t$val_bpb`t$mem_gb`t$status`t$desc"
    Add-Content -Path results.tsv -Value $tsvLine -Encoding utf8

    # Also sync to bb-offload results for Hatch cloud pull
    $queueDir = "bb-offload/results"
    if (-not (Test-Path $queueDir)) { New-Item -ItemType Directory -Force -Path $queueDir | Out-Null }
    $jsonObj = @{
        ts = (Get-Date -Format o)
        commit = $commit
        val_bpb = $val_bpb
        memory_gb = $mem_gb
        status = $status
        program = $Program
        branch = $branch
        exp = $expCount
    } | ConvertTo-Json -Compress
    Add-Content -Path "$queueDir/results.jsonl" -Value $jsonObj -Encoding utf8

    Write-Host "Logged to results.tsv + $queueDir/results.jsonl" -ForegroundColor Green

    # --- AUTO PUBLISH to GitHub Releases every 5 exps + scout sync ---
    if ($expCount % 5 -eq 0) {
        try {
            $relTag = "v0.6.0-" + (Split-Path $Program -Leaf).Replace("program-","").Replace(".md","") + "-" + (Get-Date -Format "MMdd-HHmm")
            Write-Host "Auto-publishing release $relTag (every 5 exps)..." -ForegroundColor Magenta
            & "$PSScriptRoot/publish-release.ps1" -Program $Program -Tag $relTag -ErrorAction Continue
            Write-Host "Dashboard will auto-read in <60s: https://github.com/jcdavis131/scout-rtx/releases/tag/$relTag" -ForegroundColor Cyan
            # Also try scout CLI sync if available (Hatch path)
            try { scout rtx releases sync --tag $relTag --json 2>$null | Out-Null } catch {}
        } catch {
            Write-Host "Auto-publish failed (will retry next 5): $_" -ForegroundColor Yellow
        }
    }

    # If MaxExperiments, break
    if ($MaxExperiments -gt 0 -and $expCount -ge $MaxExperiments) { break }

    # Sleep tiny to avoid tight loop if crash (agent should edit train.py between runs)
    # When used with Claude/Codex agent, agent loop handles editing — this script just runs.
    # For fully autonomous with agent, you actually want agent to loop, not this script.
    # This script is helper for manual loop.

    Write-Host "Waiting 2s before next iteration... (Agent should edit train.py now if autonomous)" -ForegroundColor Yellow
    Start-Sleep -Seconds 2

    # NOTE: In true autonomous mode (per program.md), your AI agent (Claude) is supposed to:
    # 1. Edit train.py with new idea
    # 2. git commit
    # 3. Run this script OR uv run train.py directly
    # 4. Check result, decide keep/discard, git reset if discard
    # This PS loop is just a runner, not the agent itself.

    # For this helper, we don't auto git reset — agent does.

    if ($expCount -ge 100 -and $MaxExperiments -eq 0) {
        Write-Host "100 experiments done overnight — consider pausing to review results.tsv" -ForegroundColor Cyan
    }
}

Write-Host "`n=== Autonomous loop finished after $expCount experiments ===" -ForegroundColor Cyan
Write-Host "Review results.tsv, then sync to Hatch via .\scripts\sync-to-hatch.ps1"

# Final publish — best-of run -> GitHub release -> dashboard auto-read in 60s
try {
    $finalTag = "v0.6.0-" + (Split-Path $Program -Leaf).Replace("program-","").Replace(".md","") + "-" + (Get-Date -Format "MMdd")
    Write-Host "Final publish $finalTag -> scout-rtx releases..." -ForegroundColor Green
    & "$PSScriptRoot/publish-release.ps1" -Program $Program -Tag $finalTag -ErrorAction Continue
    Write-Host "Done. Verify: scout rtx releases list | scout rtx releases sync --tag $finalTag" -ForegroundColor Cyan
    Write-Host "Dashboard: rtx-offload-dashboard auto-reads every 60s + hourly server cron rtx-releases-hourly-sync" -ForegroundColor Cyan
} catch {
    Write-Host "Final publish failed: $_ . Run manually: .\scripts\publish-release.ps1 -Program $Program" -ForegroundColor Yellow
}

