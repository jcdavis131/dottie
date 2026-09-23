param(
  [Parameter(Mandatory=$true)][string]$ZipPath,
  [string]$PackId = ''
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $ZipPath)) { throw "Missing zip $ZipPath" }
if (-not $PackId) {
  $PackId = [IO.Path]::GetFileNameWithoutExtension($ZipPath)
}
$inbox = 'C:\Users\jcdav\Projects\factory-trainer\runs\inbox'
$dest = Join-Path $inbox $PackId
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Expand-Archive -Path $ZipPath -DestinationPath $dest -Force
Write-Output "PACK_ID=$PackId"
Write-Output "DEST=$dest"
Get-ChildItem $dest -Recurse -File | Select-Object FullName,Length | Format-Table -AutoSize
