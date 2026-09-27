[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Set', 'Test', 'Clear')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'

try {
    . (Join-Path $PSScriptRoot 'Start-DotsLiveCoordinatorAtLogon.ps1')
    switch ($Action) {
        'Set' {
            if (-not (Set-DotsLiveStopIntent)) { throw 'Stop intent was not confirmed.' }
            [Console]::Out.WriteLine('ok')
        }
        'Test' {
            if (Test-DotsLiveStopIntent) { [Console]::Out.WriteLine('stopped=true') }
            else { [Console]::Out.WriteLine('stopped=false') }
        }
        'Clear' {
            if (-not (Clear-DotsLiveStopIntent)) { throw 'Stop intent was not cleared.' }
            [Console]::Out.WriteLine('ok')
        }
    }
    exit 0
}
catch {
    [Console]::Error.WriteLine('Stop intent operation failed.')
    exit 1
}
