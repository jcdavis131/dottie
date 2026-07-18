param(
    [string]$Program = "programs\program-base.md",
    [string]$Tag = "",
    [switch]$SkipSetup
)

# Davis Custom setup for Alienware RTX 4080/4090 Windows
# Solo personal project, no connection to employer, built with public/free-tier only

$ErrorActionPreference = "Stop"
Write-Host "=== Davis Custom autoresearch-win-rtx setup (Alienware RTX 4080/4090) ===" -ForegroundColor Cyan

if (-not $Tag) {
    $Tag = "rtx-" + (Get-Date -Format "MMMdd-HHmm")
}
Write-Host "Tag: $Tag  Program: $Program"

# 1. Check GPU
try {
    nvidia-smi | Out-Host
    $gpu = (nvidia-smi --query-gpu=name,memory.total --format=csv,noheader).Trim()
    Write-Host "GPU detected: $gpu" -ForegroundColor Green
} catch {
    Write-Host "WARNING: nvidia-smi failed, continuing anyway" -ForegroundColor Yellow
}

# 2. Install uv if missing
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","User") + ";" + [System.Environment]::GetEnvironmentVariable("Path","Machine")
}

# 3. Python 3.10+ check
python --version
uv --version

# 4. uv sync deps (torch 2.9.1 cu128 as per upstream)
Write-Host "uv sync (may take a few mins first time, torch 2.9.1 cu128)..." -ForegroundColor Yellow
uv sync

# 5. Prepare data + tokenizer (one-time, ~2 min, caches to %LOCALAPPDATA%\autoresearch)
if (-not $SkipSetup) {
    Write-Host "Running prepare.py (downloads TinyStories GPT-4 clean)..." -ForegroundColor Yellow
    uv run prepare.py
} else {
    Write-Host "SkipSetup flag — skipping prepare.py" -ForegroundColor Yellow
}

# 6. Smoke test
Write-Host "Running smoke test (quick validation)..." -ForegroundColor Yellow
uv run train.py --smoke-test

# 7. Init results.tsv if not exists
if (-not (Test-Path "results.tsv")) {
    "commit`tval_bpb`tmemory_gb`tstatus`tdescription" | Out-File -Encoding utf8 results.tsv
    Write-Host "Initialized results.tsv" -ForegroundColor Green
}

# 8. Copy chosen program to program.md if different
if ($Program -ne "program.md" -and (Test-Path $Program)) {
    Copy-Item $Program program.md -Force
    Write-Host "Copied $Program -> program.md (active program)" -ForegroundColor Green
}

# 9. Optional Ollama check (for Ava judges)
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "Ollama found, listing models..." -ForegroundColor Yellow
    ollama list
} else {
    Write-Host "Ollama not found — optional, for Frontier rubric judging. Install via winget install Ollama.Ollama" -ForegroundColor Yellow
}

Write-Host "`n=== Setup complete ===" -ForegroundColor Green
Write-Host "Next: .\scripts\run-autonomous.ps1 -Program $Program -Tag $Tag"
Write-Host "Or: uv run train.py for single 5-min experiment"
Write-Host "Docs: README.md, docs/OFFLOAD_GUIDE.md, docs/HARDWARE_PROFILE.md"
