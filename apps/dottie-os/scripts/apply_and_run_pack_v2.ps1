# Apply UltraData pack_v2 on nugatron. No FT. Do not touch :8770 / LIVE gate.
$ErrorActionPreference = "Stop"
$Root = "C:\Users\jcdav\workspace\dottie-os"
$Py = "C:\Users\jcdav\dottie\.venv\Scripts\python.exe"
$Handoff = if ($env:PACK_V2_HANDOFF) { $env:PACK_V2_HANDOFF } else { Resolve-Path (Join-Path $PSScriptRoot "..") }
$Curation = Join-Path $Root "sidecar\curation"
$Staging = Join-Path $Root "registry\datasets\staging"

Write-Host "handoff=$Handoff"
Write-Host "root=$Root"

New-Item -ItemType Directory -Force -Path $Curation | Out-Null
New-Item -ItemType Directory -Force -Path $Staging | Out-Null

Copy-Item -Force (Join-Path $Handoff "sidecar\curation\ultradata_curriculum.py") (Join-Path $Curation "ultradata_curriculum.py")
Copy-Item -Force (Join-Path $Handoff "scripts\patch_hf_to_system_one.py") (Join-Path $Curation "_patch_hf_to_system_one.py")
Copy-Item -Force (Join-Path $Handoff "scripts\smoke_pack_v2.py") (Join-Path $Staging "smoke_pack_v2.py")

& $Py (Join-Path $Curation "_patch_hf_to_system_one.py") --target (Join-Path $Curation "hf_to_system_one.py")
& $Py -c "import datasets; print('datasets', datasets.__version__)"

Set-Location $Root
& $Py -m sidecar.curation.hf_to_system_one --dataset pack_v2 --n 400
& $Py (Join-Path $Staging "smoke_pack_v2.py")

Write-Host "DONE pack_v2 — champion/LIVE untouched; no FT kicked"
