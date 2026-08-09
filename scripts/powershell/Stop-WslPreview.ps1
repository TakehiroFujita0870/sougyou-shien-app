[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Initialize-Utf8Preflight.ps1')
if (-not (Test-Utf8Preflight)) { throw 'UTF-8 preflight failed.' }
$statePath = Join-Path (Join-Path $env:LOCALAPPDATA 'Kadode') 'wsl-preview.json'
if (-not (Test-Path -LiteralPath $statePath)) { throw "Preview state is missing: $statePath" }
$state = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json

& wsl.exe -d $state.Distribution -u $state.User -- systemctl --user stop $state.ViteUnit $state.ApiUnit
if ($LASTEXITCODE -ne 0) { throw 'Recorded preview units could not be stopped.' }
foreach ($processId in @([int]$state.ViteHostPid, [int]$state.ApiHostPid)) {
    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) { Stop-Process -Id $processId -ErrorAction Stop }
}
Remove-Item -LiteralPath $statePath -Force
