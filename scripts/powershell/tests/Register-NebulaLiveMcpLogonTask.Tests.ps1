$script:LiveMcpRegistrationScript = Join-Path $PSScriptRoot '..\Register-NebulaLiveMcpLogonTask.ps1'
. $script:LiveMcpRegistrationScript

Describe 'Register-NebulaLiveMcpLogonTask' {
    BeforeEach {
        $script:LiveMcpTaskDefinition = $null
        Mock Get-ScheduledTask { $null }
        Mock New-NebulaLiveMcpTaskAction { [pscustomobject]@{ Execute = $Execute; Argument = $Argument } }
        Mock New-NebulaLiveMcpTaskTrigger { [pscustomobject]@{ AtLogOn = $true; User = $User } }
        Mock New-NebulaLiveMcpTaskPrincipal { [pscustomobject]@{ UserId = $UserId; LogonType = $LogonType; RunLevel = $RunLevel } }
        Mock New-NebulaLiveMcpTaskSettings {
            [pscustomobject]@{ ExecutionTimeLimit = $ExecutionTimeLimit; MultipleInstances = $MultipleInstances }
        }
        Mock Register-NebulaLiveMcpTaskDefinition {
            $script:LiveMcpTaskDefinition = [pscustomobject]@{
                TaskName = $TaskName; Action = $Action; Trigger = $Trigger; Principal = $Principal
                Settings = $Settings; Description = $Description
            }
        }
    }

    It 'requires both live safety confirmations before task creation' {
        $threw = $false
        try { Register-NebulaLiveMcpLogonTask -TaskName 'fake live tunnel' } catch { $threw = $true }
        $threw | Should Be $true
        $script:LiveMcpTaskDefinition | Should Be $null
        Assert-MockCalled Register-NebulaLiveMcpTaskDefinition -Times 0
    }

    It 'registers a separate current-user login task with no automatic database command' {
        $script:NebulaLiveMcpStartupScript = Join-Path $TestDrive 'Start-NebulaLiveMcpAtLogon.ps1'
        [IO.File]::WriteAllText($script:NebulaLiveMcpStartupScript, '# fake only')
        Mock Test-Path { $true }

        $result = Register-NebulaLiveMcpLogonTask -CredentialRotationVerified -PrivateProjectionAndEgressReviewed -TaskName 'fake live tunnel'

        $result.Registered | Should Be $true
        $script:LiveMcpTaskDefinition.Trigger.AtLogOn | Should Be $true
        $script:LiveMcpTaskDefinition.Principal.LogonType | Should Be 'Interactive'
        $script:LiveMcpTaskDefinition.Principal.RunLevel | Should Be 'Limited'
        $script:LiveMcpTaskDefinition.Settings.ExecutionTimeLimit | Should Be ([TimeSpan]::Zero)
        $script:LiveMcpTaskDefinition.Action.Argument | Should Match 'Start-NebulaLiveMcpAtLogon.ps1'
        $script:LiveMcpTaskDefinition.Action.Argument | Should Not Match 'auth|password|secret'
        Assert-MockCalled Register-NebulaLiveMcpTaskDefinition -Times 1
    }

    It 'does not replace a task of unknown ownership' {
        Mock Get-ScheduledTask { [pscustomobject]@{ TaskName = 'fake live tunnel' } }
        $threw = $false
        try {
            Register-NebulaLiveMcpLogonTask -CredentialRotationVerified -PrivateProjectionAndEgressReviewed -TaskName 'fake live tunnel'
        } catch { $threw = $true }
        $threw | Should Be $true
        $script:LiveMcpTaskDefinition | Should Be $null
    }
}
