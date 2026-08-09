[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Distribution,
    [Parameter(Mandatory = $true)][string]$User,
    [Parameter(Mandatory = $true)][string]$ClonePath,
    [int]$UiPort = 5174,
    [int]$ApiPort = 8000,
    [int]$HoldSeconds = 60
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Initialize-Utf8Preflight.ps1')
if (-not (Test-Utf8Preflight)) { throw 'UTF-8 preflight failed.' }
if ($ClonePath -like '/mnt/c/*') { throw 'WSL native clone is required; /mnt/c is not allowed.' }
if ($HoldSeconds -lt 60) { throw 'HoldSeconds must be at least 60.' }

$stateDirectory = Join-Path $env:LOCALAPPDATA 'Kadode'
$statePath = Join-Path $stateDirectory 'wsl-preview.json'
if (Test-Path -LiteralPath $statePath) { throw "Preview state already exists: $statePath" }

& wsl.exe -d $Distribution -u $User -- test -d $ClonePath
if ($LASTEXITCODE -ne 0) { throw "WSL clone is missing: $ClonePath" }
& wsl.exe -d $Distribution -u $User -- test ! -d "$ClonePath/node_modules"
if ($LASTEXITCODE -eq 0) { throw "WSL dependencies are missing: $ClonePath/node_modules" }
& wsl.exe -d $Distribution -u $User -- test ! -d "$ClonePath/.venv"
if ($LASTEXITCODE -eq 0) { throw "WSL dependencies are missing: $ClonePath/.venv" }

$listeners = & wsl.exe -d $Distribution -u $User -- ss -ltnH
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect WSL listen ports.' }
if (($listeners -match ":$UiPort\s") -or ($listeners -match ":$ApiPort\s")) { throw "Port conflict detected on $UiPort or $ApiPort; no process was stopped." }

New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null
$viteUnit = "kadode-preview-vite-$UiPort"
$apiUnit = "kadode-preview-api-$ApiPort"
$viteArgs = @('-d', $Distribution, '-u', $User, '--', 'systemd-run', '--user', "--unit=$viteUnit", '--collect', "--property=WorkingDirectory=$ClonePath", '/usr/bin/npm', 'run', 'dev', '--', '--host', '0.0.0.0', '--port', $UiPort)
$apiArgs = @('-d', $Distribution, '-u', $User, '--', 'systemd-run', '--user', "--unit=$apiUnit", '--collect', "--property=WorkingDirectory=$ClonePath", "/home/$User/.local/bin/uv", 'run', 'uvicorn', '--app-dir', 'backend', 'kadode_api.main:create_app', '--factory', '--host', '0.0.0.0', '--port', $ApiPort)
$viteHost = Start-Process -FilePath wsl.exe -ArgumentList $viteArgs -WindowStyle Hidden -PassThru
$apiHost = Start-Process -FilePath wsl.exe -ArgumentList $apiArgs -WindowStyle Hidden -PassThru

$state = [ordered]@{ Distribution = $Distribution; User = $User; ClonePath = $ClonePath; UiPort = $UiPort; ApiPort = $ApiPort; ViteUnit = $viteUnit; ApiUnit = $apiUnit; ViteHostPid = $viteHost.Id; ApiHostPid = $apiHost.Id; StartedAt = (Get-Date).ToString('o') }
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8

Start-Sleep -Seconds $HoldSeconds
$ui = Invoke-WebRequest -UseBasicParsing "http://localhost:$UiPort/"
$api = Invoke-WebRequest -UseBasicParsing "http://localhost:$ApiPort/health"
if ($ui.StatusCode -ne 200 -or $api.StatusCode -ne 200) { throw 'Preview smoke check did not return HTTP 200.' }
& (Join-Path $PSScriptRoot 'Get-WslPreviewStatus.ps1')
