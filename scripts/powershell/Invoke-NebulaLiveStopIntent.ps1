[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Set', 'Test', 'Clear')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'

try {
    . (Join-Path $PSScriptRoot 'Start-NebulaLiveCoordinatorAtLogon.ps1')
    switch ($Action) {
        'Set' {
            if (-not (Set-NebulaLiveStopIntent)) { throw 'Stop intent was not confirmed.' }
            [Console]::Out.WriteLine('ok')
        }
        'Test' {
            if (Test-NebulaLiveStopIntent) { [Console]::Out.WriteLine('stopped=true') }
            else { [Console]::Out.WriteLine('stopped=false') }
        }
        'Clear' {
            if (-not (Clear-NebulaLiveStopIntent)) { throw 'Stop intent was not cleared.' }
            [Console]::Out.WriteLine('ok')
        }
    }
    exit 0
}
catch {
    [Console]::Error.WriteLine('Stop intent operation failed.')
    exit 1
}
