$script:LiveRegistrationScriptPath = Join-Path $PSScriptRoot '..\Register-NebulaLiveLogonTask.ps1'
. $script:LiveRegistrationScriptPath

Describe 'Register-NebulaLiveLogonTask' {
    BeforeEach {
        $script:RegisteredLiveTask = $null
        $script:ProtectNebulaSecretFileCalls = 0
        Mock Protect-NebulaSecretFile { $script:ProtectNebulaSecretFileCalls++; $true }
        Mock Get-NebulaLiveExistingTask { $null }
        Mock New-NebulaLiveTaskAction {
            [pscustomobject]@{ Execute = $Execute; Argument = $Argument }
        }
        Mock New-NebulaLiveTaskTrigger {
            [pscustomobject]@{ AtLogOn = $true; User = $User }
        }
        Mock New-NebulaLiveTaskPrincipal {
            [pscustomobject]@{ UserId = $UserId; LogonType = $LogonType; RunLevel = $RunLevel }
        }
        Mock New-NebulaLiveTaskSettings {
            [pscustomobject]@{
                MultipleInstances = $MultipleInstances
                StartWhenAvailable = $StartWhenAvailable
                DisallowStartIfOnBatteries = -not [bool]$AllowStartIfOnBatteries
                StopIfGoingOnBatteries = -not [bool]$DontStopIfGoingOnBatteries
                ExecutionTimeLimit = $ExecutionTimeLimit
            }
        }
        Mock Register-NebulaLiveTaskDefinition {
            $script:RegisteredLiveTask = [pscustomobject]@{
                TaskName = $TaskName
                Action = $Action
                Trigger = $Trigger
                Principal = $Principal
                Settings = $Settings
                Description = $Description
            }
        }
    }

    It 'protects the supplied auth file and registers a current-user limited interactive task' {
        $authFile = Join-Path $TestDrive 'normal-auth.secret'
        [System.IO.File]::Create($authFile).Dispose()

        $result = Register-NebulaLiveLogonTask -WindowsNeo4jAuthFile $authFile -CredentialRotationVerified

        Assert-MockCalled Protect-NebulaSecretFile -Times 1 -ParameterFilter { $LiteralPath -eq $authFile }
        $result.Registered | Should Be $true
        $script:RegisteredLiveTask.Principal.UserId | Should Be ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
        $script:RegisteredLiveTask.Principal.LogonType | Should Be 'Interactive'
        $script:RegisteredLiveTask.Principal.RunLevel | Should Be 'Limited'
        $script:RegisteredLiveTask.Action.Argument | Should Match 'Start-NebulaLiveAtLogon.ps1'
        $script:RegisteredLiveTask.Action.Argument | Should Not Match 'normal-auth.secret'
        $script:RegisteredLiveTask.Settings.ExecutionTimeLimit | Should Be ([TimeSpan]::FromMinutes(3))
        $script:RegisteredLiveTask.Settings.DisallowStartIfOnBatteries | Should Be $false
        $script:RegisteredLiveTask.Settings.StopIfGoingOnBatteries | Should Be $false
    }

    It 'does not replace an existing task with unknown ownership' {
        $authFile = Join-Path $TestDrive 'normal-auth.secret'
        [System.IO.File]::Create($authFile).Dispose()
        Mock Get-NebulaLiveExistingTask { [pscustomobject]@{ TaskName = 'Nebula Founder Graph live database at logon' } }
        $didThrow = $false
        $errorMessage = ''
        try { Register-NebulaLiveLogonTask -WindowsNeo4jAuthFile $authFile -CredentialRotationVerified } catch { $didThrow = $true; $errorMessage = $_.Exception.Message }

        $didThrow | Should Be $true
        $errorMessage | Should Match 'already exists'
        $script:RegisteredLiveTask | Should Be $null
    }

    It 'does not register when auth-file ACL protection fails' {
        $authFile = Join-Path $TestDrive 'normal-auth.secret'
        [System.IO.File]::Create($authFile).Dispose()
        Mock Protect-NebulaSecretFile { throw 'safe fake ACL failure' }

        $didThrow = $false
        $errorMessage = ''
        try { Register-NebulaLiveLogonTask -WindowsNeo4jAuthFile $authFile -CredentialRotationVerified } catch { $didThrow = $true; $errorMessage = $_.Exception.Message }

        $didThrow | Should Be $true
        $errorMessage | Should Match 'could not be protected'
        $script:RegisteredLiveTask | Should Be $null
    }

    It 'requires explicit credential-rotation confirmation before changing ACLs' {
        $authFile = Join-Path $TestDrive 'normal-auth.secret'
        [System.IO.File]::Create($authFile).Dispose()

        $didThrow = $false
        $errorMessage = ''
        try { Register-NebulaLiveLogonTask -WindowsNeo4jAuthFile $authFile } catch { $didThrow = $true; $errorMessage = $_.Exception.Message }

        $didThrow | Should Be $true
        $errorMessage | Should Match 'Credential rotation confirmation is required'
        $script:ProtectNebulaSecretFileCalls | Should Be 0
        $script:RegisteredLiveTask | Should Be $null
    }
}

Describe 'New-NebulaLiveTaskSettings battery mapping' {
    It 'creates Task Scheduler settings that allow start and continuation on battery' {
        $settings = New-NebulaLiveTaskSettings `
            -MultipleInstances IgnoreNew `
            -StartWhenAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::FromMinutes(3))

        $settings.DisallowStartIfOnBatteries | Should Be $false
        $settings.StopIfGoingOnBatteries | Should Be $false
    }
}

Describe 'Protect-OrAccept-NebulaLiveAuthFile' {
    BeforeEach {
        $script:AllowedLiveSids = @()
        Mock Assert-RegularSecretFile {}
        Mock Get-Acl { [pscustomobject]@{ AreAccessRulesProtected = $true } }
        Mock Test-ExactSecretAcl {
            $script:AllowedLiveSids = @($AllowedSidValues)
            return (@($AllowedSidValues).Count -eq 3)
        }
        Mock Protect-NebulaSecretFile { $true }
    }

    It 'accepts the exact current-user, SYSTEM, and Administrators ACL without rewriting it' {
        $result = Protect-OrAccept-NebulaLiveAuthFile -LiteralPath 'C:\fake\live-auth.secret'

        $result | Should Be $true
        @($script:AllowedLiveSids).Count | Should Be 3
        (@($script:AllowedLiveSids) -contains [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value) | Should Be $true
        (@($script:AllowedLiveSids) -contains 'S-1-5-18') | Should Be $true
        (@($script:AllowedLiveSids) -contains 'S-1-5-32-544') | Should Be $true
        Assert-MockCalled Protect-NebulaSecretFile -Times 0
        Assert-MockCalled Test-ExactSecretAcl -Times 1
    }

    It 'uses the existing current-user-only protection for any other ACL' {
        Mock Test-ExactSecretAcl { $false }

        $result = Protect-OrAccept-NebulaLiveAuthFile -LiteralPath 'C:\fake\live-auth.secret'

        $result | Should Be $true
        Assert-MockCalled Protect-NebulaSecretFile -Times 1 -ParameterFilter { $LiteralPath -eq 'C:\fake\live-auth.secret' }
    }
}
