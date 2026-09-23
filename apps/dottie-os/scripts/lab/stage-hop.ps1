param(
  [string]$PackId = ''
)
$ErrorActionPreference = 'Stop'
$outRoot = 'C:\Users\JCD\Projects\dataset-collect\out'
if (-not $PackId) {
  $latest = Get-ChildItem $outRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $latest) { throw "No packs under $outRoot" }
  $PackId = $latest.Name
}
$src = Join-Path $outRoot $PackId
if (-not (Test-Path $src)) { throw "Missing $src" }
$zip = Join-Path $outRoot ($PackId + '.zip')
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $src '*') -DestinationPath $zip -Force
Write-Output "PACK_ID=$PackId"
Write-Output "ZIP=$zip"
Write-Output ("ZIP_BYTES=" + (Get-Item $zip).Length)
