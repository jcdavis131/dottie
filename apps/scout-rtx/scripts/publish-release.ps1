param(
  [string]$Program = "programs/program-ava.md",
  [string]$Tag = "",
  [string]$Notes = "",
  [switch]$DryRun,
  [switch]$Demo
)
# Publish current results.tsv + results.jsonl as GitHub release assets for scout-rtx
# Usage: .\scripts\publish-release.ps1 -Program programs/program-ava.md -Tag v0.6.0-ava-0715

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $Tag) {
  $date = Get-Date -Format "MMdd"
  $prog = (Split-Path $Program -Leaf).Replace("program-","").Replace(".md","")
  $Tag = "v0.6.0-$prog-$date"
}

# Ensure gh logged in
gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "gh not logged in. Run gh auth login"; exit 1 }

# Require real results unless -Demo is explicitly requested
if (-not (Test-Path "results.tsv")) {
  if ($Demo) {
    "commit`tval_bpb`tmemory_gb`tstatus`tdescription" | Out-File -Encoding utf8 results.tsv
    "demo000`t0.9979`t11.7`tdemo`tdemo row (synthetic, published with -Demo)" | Out-File -Encoding utf8 -Append results.tsv
    Write-Host "Demo mode: seeded results.tsv with a synthetic row tagged status=demo" -ForegroundColor Yellow
  } else {
    Write-Error "no results.tsv - run experiments first (or pass -Demo to publish a synthetic demo row)"
    exit 1
  }
}

# Read best val_bpb from results.tsv if exists
$best = "unknown"
if (Test-Path "results.tsv") {
  $lines = Get-Content "results.tsv" | Select-Object -Skip 1
  $bestVal = 999
  foreach ($line in $lines) {
    $parts = $line -split "`t"
    if ($parts.Length -ge 2) {
      try { $v = [double]$parts[1]; if ($v -lt $bestVal) { $bestVal = $v } } catch {}
    }
  }
  if ($bestVal -ne 999) { $best = "$bestVal" }
}

if (-not $Notes) {
  $commit = git rev-parse --short HEAD 2>$null
  if (-not $commit) { $commit = "unknown" }
  $Notes = "Best val_bpb $best from $Program commit $commit | Auto-published by publish-release.ps1 | See dashboard rtx-offload-dashboard"
}

Write-Host "Tag: $Tag | Best: $best | Program: $Program" -ForegroundColor Cyan

$assets = @()
if (Test-Path "results.tsv") { $assets += "results.tsv" }
if (Test-Path "bb-offload/results/results.jsonl") { $assets += "bb-offload/results/results.jsonl" }
if (Test-Path "results.jsonl") { $assets += "results.jsonl" }

if ($DryRun) {
  Write-Host "[DRYRUN] Would create release $Tag with assets: $($assets -join ', ')" -ForegroundColor Yellow
  exit 0
}

# Create release if not exists, then upload
$exists = gh release view $Tag --json tagName 2>$null
if (-not $?) {
  Write-Host "Creating release $Tag..." -ForegroundColor Green
  gh release create $Tag --title "$Tag best $best" --notes $Notes $assets --repo jcdavis131/scout-rtx
} else {
  Write-Host "Release $Tag exists, uploading assets (clobber)..." -ForegroundColor Yellow
  gh release upload $Tag $assets --clobber --repo jcdavis131/scout-rtx
  gh release edit $Tag --notes $Notes --repo jcdavis131/scout-rtx
}

Write-Host "Done. Dashboard will auto-read in <60s: https://github.com/jcdavis131/scout-rtx/releases/tag/$Tag" -ForegroundColor Green
Write-Host "scout rtx dashboard" -ForegroundColor Cyan
