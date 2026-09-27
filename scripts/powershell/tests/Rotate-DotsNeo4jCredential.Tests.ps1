$script:RotationScriptPath = Join-Path $PSScriptRoot '..\Rotate-DotsNeo4jCredential.ps1'
. $script:RotationScriptPath

function New-DotsRotationMountFixture {
    param(
        [bool]$AuthReadOnly = $true,
        [bool]$IncludeTmpfs = $true,
        [bool]$ExtraMount = $false,
        [string]$TmpfsValue = ''
    )

    $mounts = @(
        [pscustomobject]@{ Type = 'volume'; Destination = '/data'; Name = 'founder-graph-local_founder_graph_neo4j_data'; RW = $true },
        [pscustomobject]@{ Type = 'bind'; Destination = '/run/secrets/founder_graph_auth'; Source = 'C:\fake\auth'; RW = -not $AuthReadOnly }
    )
    if ($ExtraMount) { $mounts += [pscustomobject]@{ Type = 'volume'; Destination = '/logs'; Name = 'unexpected-logs-volume'; RW = $true } }
    $tmpfs = if ($IncludeTmpfs) { [pscustomobject]@{ '/logs' = $TmpfsValue } } else { $null }
    return [pscustomobject]@{
        Mounts = $mounts
        HostConfig = [pscustomobject]@{ Tmpfs = $tmpfs }
    }
}

Describe 'Dots Neo4j credential-rotation safety contracts' {
    BeforeEach {
        $script:FakeOldCredential = 'FakeOld-credential-091'
        $script:FakeNewCredential = 'FakeNew-credential-482'
    }

    It 'sends password change parameters through stdin and never builds them into Docker arguments' {
        $old = ConvertTo-DotsRotationSecureString -Value $script:FakeOldCredential
        $new = ConvertTo-DotsRotationSecureString -Value $script:FakeNewCredential
        try {
            $writer = New-DotsRotationInputWriter -OldPassword $old -NewPassword $new -Kind alter
            $input = New-Object System.IO.StringWriter
            & $writer $input
            $script:CapturedCypherInput = $input.ToString()

            $script:CapturedCypherInput | Should Match ':param oldPassword => ''(?:\\u[0-9a-f]{4})+'
            $script:CapturedCypherInput | Should Match ':param newPassword => ''(?:\\u[0-9a-f]{4})+'
            $script:CapturedCypherInput | Should Match 'ALTER CURRENT USER SET PASSWORD FROM \$oldPassword TO \$newPassword;'
            $script:CapturedCypherInput | Should Not Match $script:FakeOldCredential
            $script:CapturedCypherInput | Should Not Match $script:FakeNewCredential
        }
        finally { $old.Dispose(); $new.Dispose() }

        $arguments = @('exec', '-i', '-e', 'NEO4J_USERNAME', '-e', 'NEO4J_PASSWORD', 'container-id', 'cypher-shell')
        ($arguments -join ' ') | Should Not Match $script:FakeOldCredential
        ($arguments -join ' ') | Should Not Match $script:FakeNewCredential
    }

    It 'uses read-only authentication probes with history disabled and keeps credentials out of argv' {
        $old = ConvertTo-DotsRotationSecureString -Value $script:FakeOldCredential
        try {
            Mock Invoke-DotsRotationDocker {
                $script:CapturedArguments = @($Arguments)
                $script:CapturedEnvironment = @{} + $ChildEnvironment
                [pscustomobject]@{ ExitCode = 0; StdOut = ''; TimedOut = $false }
            }

            (Test-DotsRotationAuthentication -DockerCliPath 'docker.exe' -ContainerId ('a' * 64) -Password $old) | Should Be $true
            ($script:CapturedArguments -join ' ') | Should Match '--access-mode read'
            ($script:CapturedArguments -join ' ') | Should Match '--history disable'
            ($script:CapturedArguments -join ' ') | Should Not Match $script:FakeOldCredential
            $script:CapturedEnvironment.NEO4J_PASSWORD | Should Be $script:FakeOldCredential
            $script:CapturedEnvironment.NEO4J_CYPHER_SHELL_HISTORY | Should Be 'disable'
        }
        finally { $old.Dispose() }
    }

    It 'requires both query parameter and early raw logging to be disabled' {
        $old = ConvertTo-DotsRotationSecureString -Value $script:FakeOldCredential
        try {
            Mock Invoke-DotsRotationDocker {
                $script:CapturedArguments = @($Arguments)
                [pscustomobject]@{
                    ExitCode = 0
                    StdOut = "setting`r`n`"db.logs.query.early_raw_logging_enabled=false`"`r`n`"db.logs.query.parameter_logging_enabled=false`"`r`n"
                    TimedOut = $false
                }
            }

            (Test-DotsRotationLogSettingsSafe -DockerCliPath 'docker.exe' -ContainerId ('a' * 64) -Password $old) | Should Be $true
            ($script:CapturedArguments -join ' ') | Should Match '--access-mode read'
            $queryWriter = New-DotsRotationLogSettingsInputWriter
            $queryBuffer = New-Object System.IO.StringWriter
            & $queryWriter $queryBuffer
            $script:CapturedSettingsQuery = $queryBuffer.ToString()
            $script:CapturedSettingsQuery | Should Match 'SHOW SETTINGS'
            $script:CapturedSettingsQuery | Should Not Match $script:FakeOldCredential
        }
        finally { $old.Dispose() }
    }

    It 'replaces a protected auth file using a real filesystem backup and removes the backup after verification' {
        $authPath = Join-Path $TestDrive 'fake-auth'
        $backupPath = $authPath + '.dots-auth-replacement-backup'
        [System.IO.File]::WriteAllText($authPath, 'neo4j/FakeOld-credential-091', [System.Text.UTF8Encoding]::new($false))
        [void](Protect-DotsSecretFile -LiteralPath $authPath)
        $new = ConvertTo-DotsRotationSecureString -Value $script:FakeNewCredential
        try {
            Write-DotsRotationAuthFile -AuthPath $authPath -Password $new

            [System.IO.File]::ReadAllText($authPath) | Should Be ('neo4j/' + $script:FakeNewCredential)
            (Test-DotsRotationCurrentUserAcl -Path $authPath) | Should Be $true
            (Test-Path -LiteralPath $backupPath) | Should Be $false
        }
        finally { $new.Dispose() }
    }

    It 'reads only a protected current auth file and generates a distinct printable credential' {
        $authPath = Join-Path $TestDrive 'fake-current-auth'
        [System.IO.File]::WriteAllText($authPath, ('neo4j/' + $script:FakeOldCredential), [System.Text.UTF8Encoding]::new($false))
        [void](Protect-DotsSecretFile -LiteralPath $authPath)
        $old = Get-DotsRotationProtectedCurrentPassword -AuthPath $authPath
        $new = New-DotsRotationGeneratedPassword
        try {
            (ConvertTo-DotsRotationPlainText -Secret $old) | Should Be $script:FakeOldCredential
            $generated = ConvertTo-DotsRotationPlainText -Secret $new
            $generated | Should Match '^[0-9a-f]{64}$'
            $generated | Should Not Be $script:FakeOldCredential
            (Test-DotsRotationCredential -Secret $new) | Should Be $true
        }
        finally { $old.Dispose(); $new.Dispose() }
    }

    It 'rejects a malformed protected auth file before constructing a credential' {
        $authPath = Join-Path $TestDrive 'fake-malformed-auth'
        [System.IO.File]::WriteAllText($authPath, ('wrong/' + $script:FakeOldCredential), [System.Text.UTF8Encoding]::new($false))
        [void](Protect-DotsSecretFile -LiteralPath $authPath)
        $threw = $false
        try { [void](Get-DotsRotationProtectedCurrentPassword -AuthPath $authPath) } catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'fails closed when query parameters may be logged or logging settings are unavailable' {
        $old = ConvertTo-DotsRotationSecureString -Value $script:FakeOldCredential
        try {
            Mock Invoke-DotsRotationDocker {
                [pscustomobject]@{
                    ExitCode = 0
                    StdOut = "setting`r`ndb.logs.query.early_raw_logging_enabled=false`r`ndb.logs.query.parameter_logging_enabled=true`r`n"
                    TimedOut = $false
                }
            }
            (Test-DotsRotationLogSettingsSafe -DockerCliPath 'docker.exe' -ContainerId ('a' * 64) -Password $old) | Should Be $false
        }
        finally { $old.Dispose() }
    }

    It 'rejects a mismatched live project identity before issuing any Docker command' {
        Mock Get-DotsRotationMetadata { throw 'unexpected Docker metadata call' }

        $threw = $false
        try { Assert-DotsRotationLiveIdentity -DockerCliPath 'docker.exe' -ContainerId ('a' * 64) -Project 'wrong-project' -VolumeName $script:DotsRotationVolumeName -AuthPath 'C:\fake\auth' } catch { $threw = $true }
        $threw | Should Be $true
        Assert-MockCalled Get-DotsRotationMetadata -Times 0
    }

    It 'accepts only the expected data volume, read-only auth bind, and /logs tmpfs' {
        $container = New-DotsRotationMountFixture
        { Assert-DotsRotationMountPolicy -Container $container -VolumeName $script:DotsRotationVolumeName -AuthPath 'C:\fake\auth' } | Should Not Throw
    }

    It 'rejects a writable auth bind' {
        $container = New-DotsRotationMountFixture -AuthReadOnly $false
        $threw = $false
        try { Assert-DotsRotationMountPolicy -Container $container -VolumeName $script:DotsRotationVolumeName -AuthPath 'C:\fake\auth' } catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'rejects extra mounts even when the required data and auth mounts are present' {
        $container = New-DotsRotationMountFixture -ExtraMount $true
        $threw = $false
        try { Assert-DotsRotationMountPolicy -Container $container -VolumeName $script:DotsRotationVolumeName -AuthPath 'C:\fake\auth' } catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'rejects a missing /logs tmpfs' {
        $container = New-DotsRotationMountFixture -IncludeTmpfs $false
        $threw = $false
        try { Assert-DotsRotationMountPolicy -Container $container -VolumeName $script:DotsRotationVolumeName -AuthPath 'C:\fake\auth' } catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'rejects tmpfs options or additional tmpfs targets' {
        $options = New-DotsRotationMountFixture -TmpfsValue 'rw,noexec'
        $extraTarget = New-DotsRotationMountFixture
        $extraTarget.HostConfig.Tmpfs | Add-Member -NotePropertyName '/cache' -NotePropertyValue ''
        foreach ($container in @($options, $extraTarget)) {
            $threw = $false
            try { Assert-DotsRotationMountPolicy -Container $container -VolumeName $script:DotsRotationVolumeName -AuthPath 'C:\fake\auth' } catch { $threw = $true }
            $threw | Should Be $true
        }
    }

    It 'requires explicit backup-to-volume confirmation before inspecting a backup path' {
        $missingConfirmationThrew = $false
        try { Assert-DotsRotationOfflineBackup -Path 'C:\nonexistent\fake-backup' -VolumeName $script:DotsRotationVolumeName } catch { $missingConfirmationThrew = $true }
        $missingConfirmationThrew | Should Be $true

        $wrongVolumeThrew = $false
        try { Assert-DotsRotationOfflineBackup -Path 'C:\nonexistent\fake-backup' -VolumeName 'wrong-volume' -BackupForExpectedVolume } catch { $wrongVolumeThrew = $true }
        $wrongVolumeThrew | Should Be $true
    }

    It 'keeps ambiguous old-and-new authentication state unresolved without writing the auth file' {
        $pending = Join-Path $TestDrive 'fake.rotation-pending'
        [System.IO.File]::WriteAllLines($pending, @(
            'DOTS_ROTATION_PENDING_V1',
            ('old=neo4j/' + $script:FakeOldCredential),
            ('new=neo4j/' + $script:FakeNewCredential)
        ))
        try {
            Mock Test-DotsRotationCurrentUserAcl { $true }
            Mock Test-DotsRotationRegularFile { $true }
            Mock Test-DotsRotationAuthentication { $true }
            Mock Write-DotsRotationAuthFile { throw 'auth file write must not happen in ambiguity' }
            $result = Resolve-DotsRotationPending -DockerCliPath 'docker.exe' -ContainerId ('a' * 64) -AuthPath (Join-Path $TestDrive 'fake-auth') -PendingPath $pending

            $result.State | Should Be 'ambiguous'
            $result.Success | Should Be $false
            Test-Path -LiteralPath $pending | Should Be $true
            Assert-MockCalled Write-DotsRotationAuthFile -Times 0
        }
        finally { }
    }

    It 'uses protected-file generation without prompting and stops before mutation when log preflight fails' {
        $authPath = Join-Path $TestDrive 'fake-generated-path-auth'
        [System.IO.File]::WriteAllText($authPath, ('neo4j/' + $script:FakeOldCredential), [System.Text.UTF8Encoding]::new($false))
        Mock Protect-DotsSecretFile { $true }
        Mock Test-DotsRotationCurrentUserAcl { $true }
        Mock Assert-DotsRotationOfflineBackup { }
        Mock Assert-DotsRotationLiveIdentity { [pscustomobject]@{ ContainerId = ('a' * 64) } }
        Mock Read-Host { throw 'the protected-file path must not prompt' }
        Mock Test-DotsRotationAuthentication {
            (ConvertTo-DotsRotationPlainText -Secret $Password) -eq $script:FakeOldCredential
        }
        Mock Test-DotsRotationLogSettingsSafe { $false }
        Mock Invoke-DotsRotationPasswordChange { throw 'password change must not run after failed preflight' }
        Mock Write-DotsRotationProtectedFile { throw 'pending record must not be written after failed preflight' }
        Mock Write-DotsRotationAuthFile { throw 'auth file must not be updated after failed preflight' }

        $threw = $false
        try {
            Invoke-DotsNeo4jCredentialRotation `
                -ExpectedProject $script:DotsRotationProject `
                -ExpectedContainerId ('a' * 64) `
                -ExpectedVolumeName $script:DotsRotationVolumeName `
                -AuthFilePath $authPath `
                -BackupDirectory (Join-Path $TestDrive 'fake-backup') `
                -BackupForExpectedVolume `
                -UseProtectedAuthFileAndGenerate
        }
        catch { $threw = $true }

        $threw | Should Be $true
        [System.IO.File]::ReadAllText($authPath) | Should Be ('neo4j/' + $script:FakeOldCredential)
        Test-Path -LiteralPath ($authPath + $script:DotsRotationPendingSuffix) | Should Be $false
        Assert-MockCalled Read-Host -Times 0
        Assert-MockCalled Test-DotsRotationAuthentication -Times 2
        Assert-MockCalled Test-DotsRotationLogSettingsSafe -Times 1
        Assert-MockCalled Invoke-DotsRotationPasswordChange -Times 0
        Assert-MockCalled Write-DotsRotationProtectedFile -Times 0
        Assert-MockCalled Write-DotsRotationAuthFile -Times 0
    }
}
