$coordinatorPath = Join-Path $PSScriptRoot '..\Start-DotsLiveCoordinatorAtLogon.ps1'
. $coordinatorPath

Describe 'Invoke-DotsLiveStopIntent fixed action contract' {
    It 'allows only the three fixed marker actions' {
        $command = Get-Command (Join-Path $PSScriptRoot '..\Invoke-DotsLiveStopIntent.ps1')
        $validateSet = $command.Parameters['Action'].Attributes | Where-Object { $_ -is [System.Management.Automation.ValidateSetAttribute] }

        @($validateSet.ValidValues) | Should Be @('Set', 'Test', 'Clear')
    }

    It 'uses only the protected marker functions and never accepts a caller marker path' {
        $source = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot '..\Invoke-DotsLiveStopIntent.ps1'))

        $source | Should Match 'Set-DotsLiveStopIntent'
        $source | Should Match 'Test-DotsLiveStopIntent'
        $source | Should Match 'Clear-DotsLiveStopIntent'
        $source | Should Not Match '\[string\]\$Path'
        $source | Should Not Match '\$env:'
    }

    It 'does not emit marker paths in failure output' {
        $source = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot '..\Invoke-DotsLiveStopIntent.ps1'))

        $source | Should Match 'Stop intent operation failed\.'
        $source | Should Not Match 'Write-Error.*Exception'
    }
}
