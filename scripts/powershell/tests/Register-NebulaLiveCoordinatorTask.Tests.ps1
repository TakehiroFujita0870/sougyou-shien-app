$script:CoordinatorRegistrationPath = Join-Path $PSScriptRoot '..\Register-NebulaLiveCoordinatorTask.ps1'
$script:RegistrationScriptDirectory = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. $script:CoordinatorRegistrationPath

function New-FakeNebulaLegacyTask {
    param([string]$Name, [string]$StartupName, [string]$State, [TimeSpan]$TimeLimit)
    $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $startupPath = Join-Path $script:RegistrationScriptDirectory $StartupName
    return [pscustomobject]@{
        TaskName = $Name
        State = $State
        Actions = @([pscustomobject]@{
            Execute = $powershell
            Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $startupPath
            WorkingDirectory = ''
        })
        Triggers = @([pscustomobject]@{
            CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskLogonTrigger' }
            UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            Enabled = $true
        })
        Principal = [pscustomobject]@{
            UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            LogonType = 'Interactive'
            RunLevel = 'Limited'
        }
        Settings = [pscustomobject]@{
            Enabled = $true
            MultipleInstances = 'IgnoreNew'
            StartWhenAvailable = $true
            DisallowStartIfOnBatteries = $false
            StopIfGoingOnBatteries = $false
            Hidden = $false
            ExecutionTimeLimit = $TimeLimit
        }
    }
}

Describe 'Register-NebulaLiveCoordinatorTask' {
    BeforeEach {
        $script:FakeTaskCalls = @()
        $script:ExportCalls = @()
        $script:CoordinatorRegistration = $null
        $script:OriginalTaskStates = @{ 'Nebula Founder Graph live database at logon' = 'Ready'; 'Nebula live MCP tunnel at logon' = 'Running' }
        $script:FakeTaskXml = @{
            'Nebula Founder Graph live database at logon' = '<Task><RegistrationInfo><URI>\Nebula Founder Graph live database at logon</URI></RegistrationInfo></Task>'
            'Nebula live MCP tunnel at logon' = '<Task><RegistrationInfo><URI>\Nebula live MCP tunnel at logon</URI></RegistrationInfo></Task>'
        }
        $script:FakeTasks = @{
            'Nebula Founder Graph live database at logon' = New-FakeNebulaLegacyTask -Name 'Nebula Founder Graph live database at logon' -StartupName 'Start-NebulaLiveAtLogon.ps1' -State 'Ready' -TimeLimit ([TimeSpan]::FromMinutes(3))
            'Nebula live MCP tunnel at logon' = New-FakeNebulaLegacyTask -Name 'Nebula live MCP tunnel at logon' -StartupName 'Start-NebulaLiveMcpAtLogon.ps1' -State 'Running' -TimeLimit ([TimeSpan]::Zero)
        }

        Mock Get-NebulaCoordinatorTask { return $script:FakeTasks[$TaskName] }
        Mock Export-NebulaCoordinatorTask { $script:ExportCalls += $TaskName; return $script:FakeTaskXml[$TaskName] }
        Mock Assert-NebulaCoordinatorControlServiceHook {}
        Mock Disable-NebulaCoordinatorTask { $script:FakeTaskCalls += "disable:$TaskName"; $script:FakeTasks[$TaskName].Settings.Enabled = $false; if ($script:FakeTasks[$TaskName].State -ne 'Running') { $script:FakeTasks[$TaskName].State = 'Disabled' } }
        Mock Enable-NebulaCoordinatorTask { $script:FakeTaskCalls += "enable:$TaskName"; $script:FakeTasks[$TaskName].Settings.Enabled = $true; $script:FakeTasks[$TaskName].State = $script:OriginalTaskStates[$TaskName] }
        Mock Remove-NebulaCoordinatorTask { $script:FakeTaskCalls += "remove:$TaskName"; $script:FakeTasks.Remove($TaskName) }
        Mock New-NebulaCoordinatorTaskArguments { return '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $ScriptPath }
        Mock New-NebulaCoordinatorTaskAction { [pscustomobject]@{ Execute = $Execute; Arguments = $Argument; WorkingDirectory = $WorkingDirectory } }
        Mock New-NebulaCoordinatorTaskTrigger { [pscustomobject]@{ CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskLogonTrigger' }; UserId = $User; Enabled = $true; Repetition = [pscustomobject]@{ Interval = 'PT5M'; Duration = ''; StopAtDurationEnd = $false } } }
        Mock New-NebulaCoordinatorTaskPrincipal { [pscustomobject]@{ UserId = $UserId; LogonType = 'Interactive'; RunLevel = 'Limited' } }
        Mock New-NebulaCoordinatorTaskSettings { [pscustomobject]@{ Enabled = $true; MultipleInstances = 'IgnoreNew'; Hidden = $true; ExecutionTimeLimit = [TimeSpan]::FromMinutes(8) } }
        Mock Register-NebulaCoordinatorTaskDefinition {
            $script:FakeTaskCalls += "register:$TaskName"
            $script:CoordinatorRegistration = [pscustomobject]@{ Action = $Action; Trigger = $Trigger; Principal = $Principal; Settings = $Settings; Description = $Description }
            $script:FakeTasks[$TaskName] = [pscustomobject]@{
                TaskName = $TaskName
                State = 'Ready'
                Actions = @($Action)
                Triggers = @($Trigger)
                Principal = $Principal
                Settings = $Settings
            }
        }
    }

    It 'exports both verified definitions and registers one hidden limited task before leaving old tasks disabled' {
        $result = Register-NebulaLiveCoordinatorTask -BackupRoot (Join-Path $TestDrive 'backups') -Confirm:$false

        $result.Registered | Should Be $true
        $result.TaskName | Should Be 'Nebula Founder Graph live startup coordinator at logon'
        @($result.BackupFiles).Count | Should Be 2
        ([System.IO.File]::ReadAllText($result.BackupFiles[0])) | Should Be $script:FakeTaskXml['Nebula Founder Graph live database at logon']
        ([System.IO.File]::ReadAllText($result.BackupFiles[1])) | Should Be $script:FakeTaskXml['Nebula live MCP tunnel at logon']
        $script:CoordinatorRegistration.Action.Arguments | Should Match '-WindowStyle Hidden'
        $script:CoordinatorRegistration.Action.Arguments | Should Match '-File "[^"]+Start-NebulaLiveCoordinatorAtLogon.ps1"'
        $script:CoordinatorRegistration.Principal.LogonType | Should Be 'Interactive'
        $script:CoordinatorRegistration.Principal.RunLevel | Should Be 'Limited'
        $script:CoordinatorRegistration.Settings.Hidden | Should Be $true
        $script:CoordinatorRegistration.Settings.ExecutionTimeLimit | Should Be ([TimeSpan]::FromMinutes(8))
        $script:CoordinatorRegistration.Trigger.Repetition.Interval | Should Be 'PT5M'
        $script:FakeTasks['Nebula Founder Graph live database at logon'].State | Should Be 'Disabled'
        $script:FakeTasks['Nebula live MCP tunnel at logon'].State | Should Be 'Running'
        $script:FakeTasks['Nebula Founder Graph live database at logon'].Settings.Enabled | Should Be $false
        $script:FakeTasks['Nebula live MCP tunnel at logon'].Settings.Enabled | Should Be $false
        # Disabling a Windows scheduled task does not rewrite its trigger's
        # Enabled field. Its Task.State is the effective safety check.
        $script:FakeTasks['Nebula Founder Graph live database at logon'].Triggers[0].Enabled | Should Be $true
        $script:FakeTasks['Nebula live MCP tunnel at logon'].Triggers[0].Enabled | Should Be $true
        @($script:FakeTaskCalls | Where-Object { $_ -like 'disable:*' }).Count | Should Be 2
    }

    It 'quotes coordinator paths that contain spaces in the task action' {
        $arguments = New-NebulaCoordinatorTaskArguments -ScriptPath 'C:\Users\A User\Nebula Graph\Start-NebulaLiveCoordinatorAtLogon.ps1'
        $arguments | Should Be '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\A User\Nebula Graph\Start-NebulaLiveCoordinatorAtLogon.ps1"'
    }

    It 'fails closed and preserves XML when a legacy action path differs' {
        $script:FakeTasks['Nebula live MCP tunnel at logon'].Actions[0].Arguments = '-NoProfile -File "C:\unexpected\Start-NebulaLiveMcpAtLogon.ps1"'
        $didThrow = $false
        try { Register-NebulaLiveCoordinatorTask -BackupRoot (Join-Path $TestDrive 'backups') -Confirm:$false } catch { $didThrow = $true }

        $didThrow | Should Be $true
        @($script:FakeTaskCalls).Count | Should Be 0
        (Test-Path -LiteralPath (Join-Path $TestDrive 'backups')) | Should Be $true
    }

    It 'fails closed when the current-user principal does not match' {
        $script:FakeTasks['Nebula live MCP tunnel at logon'].Principal.UserId = 'other-user'
        $didThrow = $false
        try { Register-NebulaLiveCoordinatorTask -BackupRoot (Join-Path $TestDrive 'backups') -Confirm:$false } catch { $didThrow = $true }

        $didThrow | Should Be $true
        @($script:FakeTaskCalls).Count | Should Be 0
    }

    It 'fails closed when the existing task is not an enabled current-user logon trigger' {
        $script:FakeTasks['Nebula live MCP tunnel at logon'].Triggers[0].UserId = 'other-user'
        $didThrow = $false
        try { Register-NebulaLiveCoordinatorTask -BackupRoot (Join-Path $TestDrive 'backups') -Confirm:$false } catch { $didThrow = $true }

        $didThrow | Should Be $true
        @($script:FakeTaskCalls).Count | Should Be 0
    }

    It 'fails closed when a legacy task is disabled' {
        $script:FakeTasks['Nebula live MCP tunnel at logon'].State = 'Disabled'
        $didThrow = $false
        try { Register-NebulaLiveCoordinatorTask -BackupRoot (Join-Path $TestDrive 'backups') -Confirm:$false } catch { $didThrow = $true }

        $didThrow | Should Be $true
        @($script:FakeTaskCalls).Count | Should Be 0
    }

    It 'fails closed when either legacy task is missing' {
        $script:FakeTasks.Remove('Nebula live MCP tunnel at logon')
        $didThrow = $false
        try { Register-NebulaLiveCoordinatorTask -BackupRoot (Join-Path $TestDrive 'backups') -Confirm:$false } catch { $didThrow = $true }

        $didThrow | Should Be $true
        @($script:FakeTaskCalls).Count | Should Be 0
        @($script:ExportCalls).Count | Should Be 0
    }

    It 'restores both old tasks and removes the new task when registration fails' {
        Mock Register-NebulaCoordinatorTaskDefinition { throw 'fake registration failure' }
        $didThrow = $false
        try { Register-NebulaLiveCoordinatorTask -BackupRoot (Join-Path $TestDrive 'backups') -Confirm:$false } catch { $didThrow = $true }

        $didThrow | Should Be $true
        $script:FakeTasks['Nebula Founder Graph live database at logon'].State | Should Be 'Ready'
        $script:FakeTasks['Nebula live MCP tunnel at logon'].State | Should Be 'Running'
        $script:FakeTasks['Nebula Founder Graph live database at logon'].Triggers[0].Enabled | Should Be $true
        $script:FakeTasks['Nebula live MCP tunnel at logon'].Triggers[0].Enabled | Should Be $true
        @($script:FakeTaskCalls | Where-Object { $_ -like 'enable:*' }).Count | Should Be 2
    }

    It 'does not overwrite a pre-existing coordinator task' {
        $script:FakeTasks['Nebula Founder Graph live startup coordinator at logon'] = [pscustomobject]@{ TaskName = 'existing' }
        $didThrow = $false
        try { Register-NebulaLiveCoordinatorTask -BackupRoot (Join-Path $TestDrive 'backups') -Confirm:$false } catch { $didThrow = $true }

        $didThrow | Should Be $true
        @($script:FakeTaskCalls).Count | Should Be 0
        @($script:ExportCalls).Count | Should Be 0
    }

    It 'does not migrate until the control-service startup hook precedes the stop-marker check' {
        Mock Assert-NebulaCoordinatorControlServiceHook { throw 'control service startup hook is not implemented' }
        $didThrow = $false
        try { Register-NebulaLiveCoordinatorTask -BackupRoot (Join-Path $TestDrive 'backups') -Confirm:$false } catch { $didThrow = $true }

        $didThrow | Should Be $true
        @($script:FakeTaskCalls).Count | Should Be 0
    }

    It 'does not write backup files or change tasks in WhatIf mode' {
        Mock Assert-NebulaCoordinatorControlServiceHook { throw 'control service startup hook is not implemented' }

        $result = Register-NebulaLiveCoordinatorTask -BackupRoot (Join-Path $TestDrive 'backups') -WhatIf

        $result.WhatIf | Should Be $true
        @($result.BackupFiles).Count | Should Be 0
        @($script:FakeTaskCalls).Count | Should Be 0
    }

    It 'still rejects mismatched legacy definitions in WhatIf mode' {
        $whatIfBackupRoot = Join-Path $TestDrive 'whatif-mismatch-backups'
        $script:FakeTasks['Nebula live MCP tunnel at logon'].Actions[0].Arguments = '-File wrong.ps1'
        $didThrow = $false
        try { Register-NebulaLiveCoordinatorTask -BackupRoot $whatIfBackupRoot -WhatIf } catch { $didThrow = $true }

        $didThrow | Should Be $true
        @($script:FakeTaskCalls).Count | Should Be 0
        Test-Path -LiteralPath $whatIfBackupRoot | Should Be $false
    }

    It 'exports protected backups without changing tasks in BackupOnly mode while the control hook is pending' {
        Mock Assert-NebulaCoordinatorControlServiceHook { throw 'control service startup hook is not implemented' }

        $result = Register-NebulaLiveCoordinatorTask -BackupRoot (Join-Path $TestDrive 'backups') -BackupOnly

        $result.BackupOnly | Should Be $true
        $result.Blocked | Should Be $true
        @($result.BackupFiles).Count | Should Be 2
        @($script:FakeTaskCalls).Count | Should Be 0
    }
}

Describe 'Recurring coordinator trigger' {
    It 'uses an indefinitely repeating current-user logon trigger' {
        $trigger = New-NebulaCoordinatorTaskTrigger -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)

        $trigger.CimClass.CimClassName | Should Be 'MSFT_TaskLogonTrigger'
        $trigger.Repetition.Interval | Should Be 'PT5M'
        [string]$trigger.Repetition.Duration | Should Be ''
        $trigger.Repetition.StopAtDurationEnd | Should Be $false
    }
}

Describe 'Coordinator registration dependency' {
    It 'requires the controller startup before stop-marker checking' {
        { Assert-NebulaCoordinatorControlServiceHook } | Should Not Throw
    }

    It 'accepts the ISO durations returned by the real Windows scheduler' {
        (Convert-NebulaTaskExecutionTimeLimit -Value 'PT3M') | Should Be ([TimeSpan]::FromMinutes(3))
        (Convert-NebulaTaskExecutionTimeLimit -Value 'PT0S') | Should Be ([TimeSpan]::Zero)
    }
}
