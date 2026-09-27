$script:registerScript = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot '..\Register-DotsSyntheticLogonTask.ps1')
)

Describe 'Register-DotsSyntheticLogonTask.ps1 safety gates' {
    It 'explicitly permits the synthetic logon task to start and continue on battery power' {
        $tokens = $null
        $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile(
            $script:registerScript,
            [ref]$tokens,
            [ref]$parseErrors
        )
        $parseErrors.Count | Should Be 0

        $settingsCall = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.CommandAst] -and
            $node.GetCommandName() -eq 'New-ScheduledTaskSettingsSet'
        }, $true)
        $settingsCall | Should Not Be $null
        $settingsCall.Extent.Text | Should Match '(?s)-AllowStartIfOnBatteries.*-DontStopIfGoingOnBatteries'

        $settings = New-ScheduledTaskSettingsSet `
            -MultipleInstances IgnoreNew `
            -StartWhenAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero)
        $settings.DisallowStartIfOnBatteries | Should Be $false
        $settings.StopIfGoingOnBatteries | Should Be $false
    }

    It 'uses a dedicated synthetic credential parameter instead of the live parameter' {
        $tokens = $null
        $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile(
            $script:registerScript,
            [ref]$tokens,
            [ref]$parseErrors
        )
        $parseErrors.Count | Should Be 0
        $parameterNames = @($ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
        ($parameterNames -notcontains 'WindowsNeo4jAuthFile') | Should Be $true
        ($parameterNames -contains 'WindowsSyntheticNeo4jAuthFile') | Should Be $true
    }

    It 'rejects a missing control-plane secret file before registering a scheduled task' {
        $missingControlPlanePath = Join-Path $TestDrive 'missing-control-plane.env'
        $missingSyntheticAuthPath = Join-Path $TestDrive 'missing-synthetic-neo4j-auth.secret'
        $script:taskRegistrationReached = $false

        Mock Register-ScheduledTask {
            $script:taskRegistrationReached = $true
        }

        $failureMessage = ''
        try {
            & $script:registerScript `
                -WindowsControlPlaneEnvFile $missingControlPlanePath `
                -WindowsSyntheticNeo4jAuthFile $missingSyntheticAuthPath
        }
        catch {
            $failureMessage = $_.Exception.Message
        }

        $failureMessage | Should Be 'Secret path must refer to an existing file.'
        $script:taskRegistrationReached | Should Be $false
        $failureMessage.Contains($missingControlPlanePath) | Should Be $false
    }
}
