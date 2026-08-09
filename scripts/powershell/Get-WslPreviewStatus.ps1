[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Initialize-Utf8Preflight.ps1')
if (-not (Test-Utf8Preflight)) { throw 'UTF-8 preflight failed.' }
$statePath = Join-Path (Join-Path $env:LOCALAPPDATA 'Kadode') 'wsl-preview.json'
if (-not (Test-Path -LiteralPath $statePath)) { throw "Preview state is missing: $statePath" }
$state = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json

function Get-HostProcessState([int]$ProcessId) {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    return [bool]$process
}

function Get-LinuxMainPid([string]$Unit) {
    $value = & wsl.exe -d $state.Distribution -u $state.User -- systemctl --user show --property MainPID --value $Unit
    if ($LASTEXITCODE -ne 0) { return $null }
    return $value
}

$listeners = & wsl.exe -d $state.Distribution -u $state.User -- ss -ltnH
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect WSL listen ports.' }
$uiResponse = Invoke-WebRequest -UseBasicParsing "http://localhost:$($state.UiPort)/" -ErrorAction SilentlyContinue
$apiResponse = Invoke-WebRequest -UseBasicParsing "http://localhost:$($state.ApiPort)/health" -ErrorAction SilentlyContinue
[pscustomobject]@{
    WindowsViteHostPid = $state.ViteHostPid
    WindowsViteHostRunning = Get-HostProcessState $state.ViteHostPid
    WindowsApiHostPid = $state.ApiHostPid
    WindowsApiHostRunning = Get-HostProcessState $state.ApiHostPid
    LinuxViteMainPid = Get-LinuxMainPid $state.ViteUnit
    LinuxApiMainPid = Get-LinuxMainPid $state.ApiUnit
    UiListening = [bool]($listeners -match ":$($state.UiPort)\s")
    ApiListening = [bool]($listeners -match ":$($state.ApiPort)\s")
    UiHttpStatus = $uiResponse.StatusCode
    ApiHttpStatus = $apiResponse.StatusCode
}
