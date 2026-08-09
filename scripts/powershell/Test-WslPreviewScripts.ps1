[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$required = @('Start-WslPreview.ps1', 'Get-WslPreviewStatus.ps1', 'Stop-WslPreview.ps1')
foreach ($name in $required) {
    $path = Join-Path $PSScriptRoot $name
    $tokens = $null; $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw "PowerShell parse failed: $name" }
}
$start = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Start-WslPreview.ps1') -Raw -Encoding utf8
$status = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Get-WslPreviewStatus.ps1') -Raw -Encoding utf8
$stop = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Stop-WslPreview.ps1') -Raw -Encoding utf8
foreach ($needle in @('Test-Utf8Preflight', 'HoldSeconds', 'Start-Process', 'WindowStyle Hidden', 'Port conflict', 'systemd-run')) { if (-not $start.Contains($needle)) { throw "Start contract missing: $needle" } }
foreach ($needle in @('WindowsViteHostPid', 'LinuxViteMainPid', 'UiListening', 'UiHttpStatus')) { if (-not $status.Contains($needle)) { throw "Status contract missing: $needle" } }
foreach ($needle in @('systemctl', 'Stop-Process -Id', 'Remove-Item -LiteralPath')) { if (-not $stop.Contains($needle)) { throw "Stop contract missing: $needle" } }
if ($stop -match 'taskkill|wsl.exe --shutdown|Stop-Process\s+-Name') { throw 'Unsafe broad stop operation detected.' }
Write-Output 'WSL preview script contract tests passed.'
