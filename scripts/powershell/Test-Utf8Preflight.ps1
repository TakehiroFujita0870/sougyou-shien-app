[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('uninitialized', 'initialized', 'invalid')]
    [string]$Scenario
)

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'Initialize-Utf8Preflight.ps1'
$fixtureName = ([string]([char]0x65E5) + [char]0x672C + [char]0x8A9E + [char]0x30D1 + [char]0x30B9 + '.txt')
$fixturePath = Join-Path (Join-Path $PSScriptRoot 'fixtures') $fixtureName

if ($Scenario -eq 'uninitialized') {
    & $scriptPath -Check
    if ($LASTEXITCODE -eq 0) {
        throw 'Uninitialized safety check unexpectedly succeeded.'
    }
    exit 0
}

. $scriptPath
if ($Scenario -eq 'invalid') {
    Set-Variable -Name OutputEncoding -Scope Global -Value ([System.Text.Encoding]::ASCII) -Force
    if (Test-Utf8Preflight) {
        throw 'Invalid encoding safety check unexpectedly succeeded.'
    }
    exit 0
}

if (-not (Test-Utf8Preflight)) {
    throw 'UTF-8 safety check failed after dot-sourcing.'
}
if (-not (Test-Utf8ReadBack -LiteralPath $fixturePath)) {
    throw 'UTF-8 read-back failed for the Japanese fixture path.'
}
