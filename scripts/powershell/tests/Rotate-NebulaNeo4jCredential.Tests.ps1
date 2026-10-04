$script:RotationScriptPath = Join-Path $PSScriptRoot '..\Rotate-NebulaNeo4jCredential.ps1'
. $script:RotationScriptPath

function New-NebulaRotationMountFixture {
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

Describe 'Nebula Neo4j credential-rotation safety contracts' {
    BeforeEach {
        $script:FakeOldCredential = 'FakeOld-credential-091'
        $script:FakeNewCredential = 'FakeNew-credential-482'
    }

    It 'sends password change parameters through stdin and never builds them into Docker arguments' {
        $old = ConvertTo-NebulaRotationSecureString -Value $script:FakeOldCredential
        $new = ConvertTo-NebulaRotationSecureString -Value $script:FakeNewCredential
        try {
            $writer = New-NebulaRotationInputWriter -OldPassword $old -NewPassword $new -Kind alter
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
        $old = ConvertTo-NebulaRotationSecureString -Value $script:FakeOldCredential
        try {
            Mock Invoke-NebulaRotationDocker {
                $script:CapturedArguments = @($Arguments)
                $script:CapturedEnvironment = @{} + $ChildEnvironment
                [pscustomobject]@{ ExitCode = 0; StdOut = ''; TimedOut = $false }
            }

            (Test-NebulaRotationAuthentication -DockerCliPath 'docker.exe' -ContainerId ('a' * 64) -Password $old) | Should Be $true
            ($script:CapturedArguments -join ' ') | Should Match '--access-mode read'
            ($script:CapturedArguments -join ' ') | Should Match '--history disable'
            ($script:CapturedArguments -join ' ') | Should Not Match $script:FakeOldCredential
            $script:CapturedEnvironment.NEO4J_PASSWORD | Should Be $script:FakeOldCredential
            $script:CapturedEnvironment.NEO4J_CYPHER_SHELL_HISTORY | Should Be 'disable'
        }
        finally { $old.Dispose() }
    }

    It 'requires both query parameter and early raw logging to be disabled' {
        $old = ConvertTo-NebulaRotationSecureString -Value $script:FakeOldCredential
        try {
            Mock Invoke-NebulaRotationDocker {
                $script:CapturedArguments = @($Arguments)
                [pscustomobject]@{
                    ExitCode = 0
                    StdOut = "setting`r`n`"db.logs.query.early_raw_logging_enabled=false`"`r`n`"db.logs.query.parameter_logging_enabled=false`"`r`n"
                    TimedOut = $false
                }
            }

            (Test-NebulaRotationLogSettingsSafe -DockerCliPath 'docker.exe' -ContainerId ('a' * 64) -Password $old) | Should Be $true
            ($script:CapturedArguments -join ' ') | Should Match '--access-mode read'
            $queryWriter = New-NebulaRotationLogSettingsInputWriter
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
        $backupPath = $authPath + '.nebula-auth-replacement-backup'
        [System.IO.File]::WriteAllText($authPath, 'neo4j/FakeOld-credential-091', [System.Text.UTF8Encoding]::new($false))
        [void](Protect-NebulaSecretFile -LiteralPath $authPath)
        $new = ConvertTo-NebulaRotationSecureString -Value $script:FakeNewCredential
        try {
            Write-NebulaRotationAuthFile -AuthPath $authPath -Password $new

            [System.IO.File]::ReadAllText($authPath) | Should Be ('neo4j/' + $script:FakeNewCredential)
            (Test-NebulaRotationCurrentUserAcl -Path $authPath) | Should Be $true
            (Test-Path -LiteralPath $backupPath) | Should Be $false
        }
        finally { $new.Dispose() }
    }

    It 'reads only a protected current auth file and generates a distinct printable credential' {
        $authPath = Join-Path $TestDrive 'fake-current-auth'
        [System.IO.File]::WriteAllText($authPath, ('neo4j/' + $script:FakeOldCredential), [System.Text.UTF8Encoding]::new($false))
        [void](Protect-NebulaSecretFile -LiteralPath $authPath)
        $old = Get-NebulaRotationProtectedCurrentPassword -AuthPath $authPath
        $new = New-NebulaRotationGeneratedPassword
        try {
            (ConvertTo-NebulaRotationPlainText -Secret $old) | Should Be $script:FakeOldCredential
            $generated = ConvertTo-NebulaRotationPlainText -Secret $new
            $generated | Should Match '^[0-9a-f]{64}$'
            $generated | Should Not Be $script:FakeOldCredential
            (Test-NebulaRotationCredential -Secret $new) | Should Be $true
        }
        finally { $old.Dispose(); $new.Dispose() }
    }

    It 'rejects a malformed protected auth file before constructing a credential' {
        $authPath = Join-Path $TestDrive 'fake-malformed-auth'
        [System.IO.File]::WriteAllText($authPath, ('wrong/' + $script:FakeOldCredential), [System.Text.UTF8Encoding]::new($false))
        [void](Protect-NebulaSecretFile -LiteralPath $authPath)
        $threw = $false
        try { [void](Get-NebulaRotationProtectedCurrentPassword -AuthPath $authPath) } catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'fails closed when query parameters may be logged or logging settings are unavailable' {
        $old = ConvertTo-NebulaRotationSecureString -Value $script:FakeOldCredential
        try {
            Mock Invoke-NebulaRotationDocker {
                [pscustomobject]@{
                    ExitCode = 0
                    StdOut = "setting`r`ndb.logs.query.early_raw_logging_enabled=false`r`ndb.logs.query.parameter_logging_enabled=true`r`n"
                    TimedOut = $false
                }
            }
            (Test-NebulaRotationLogSettingsSafe -DockerCliPath 'docker.exe' -ContainerId ('a' * 64) -Password $old) | Should Be $false
        }
        finally { $old.Dispose() }
    }

    It 'rejects a mismatched live project identity before issuing any Docker command' {
        Mock Get-NebulaRotationMetadata { throw 'unexpected Docker metadata call' }

        $threw = $false
        try { Assert-NebulaRotationLiveIdentity -DockerCliPath 'docker.exe' -ContainerId ('a' * 64) -Project 'wrong-project' -VolumeName $script:NebulaRotationVolumeName -AuthPath 'C:\fake\auth' } catch { $threw = $true }
        $threw | Should Be $true
        Assert-MockCalled Get-NebulaRotationMetadata -Times 0
    }

    It 'accepts only the expected data volume, read-only auth bind, and /logs tmpfs' {
        $container = New-NebulaRotationMountFixture
        { Assert-NebulaRotationMountPolicy -Container $container -VolumeName $script:NebulaRotationVolumeName -AuthPath 'C:\fake\auth' } | Should Not Throw
    }

    It 'rejects a writable auth bind' {
        $container = New-NebulaRotationMountFixture -AuthReadOnly $false
        $threw = $false
        try { Assert-NebulaRotationMountPolicy -Container $container -VolumeName $script:NebulaRotationVolumeName -AuthPath 'C:\fake\auth' } catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'rejects extra mounts even when the required data and auth mounts are present' {
        $container = New-NebulaRotationMountFixture -ExtraMount $true
        $threw = $false
        try { Assert-NebulaRotationMountPolicy -Container $container -VolumeName $script:NebulaRotationVolumeName -AuthPath 'C:\fake\auth' } catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'rejects a missing /logs tmpfs' {
        $container = New-NebulaRotationMountFixture -IncludeTmpfs $false
        $threw = $false
        try { Assert-NebulaRotationMountPolicy -Container $container -VolumeName $script:NebulaRotationVolumeName -AuthPath 'C:\fake\auth' } catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'rejects tmpfs options or additional tmpfs targets' {
        $options = New-NebulaRotationMountFixture -TmpfsValue 'rw,noexec'
        $extraTarget = New-NebulaRotationMountFixture
        $extraTarget.HostConfig.Tmpfs | Add-Member -NotePropertyName '/cache' -NotePropertyValue ''
        foreach ($container in @($options, $extraTarget)) {
            $threw = $false
            try { Assert-NebulaRotationMountPolicy -Container $container -VolumeName $script:NebulaRotationVolumeName -AuthPath 'C:\fake\auth' } catch { $threw = $true }
            $threw | Should Be $true
        }
    }

    It 'requires explicit backup-to-volume confirmation before inspecting a backup path' {
        $missingConfirmationThrew = $false
        try { Assert-NebulaRotationOfflineBackup -Path 'C:\nonexistent\fake-backup' -VolumeName $script:NebulaRotationVolumeName } catch { $missingConfirmationThrew = $true }
        $missingConfirmationThrew | Should Be $true

        $wrongVolumeThrew = $false
        try { Assert-NebulaRotationOfflineBackup -Path 'C:\nonexistent\fake-backup' -VolumeName 'wrong-volume' -BackupForExpectedVolume } catch { $wrongVolumeThrew = $true }
        $wrongVolumeThrew | Should Be $true
    }

    It 'keeps ambiguous old-and-new authentication state unresolved without writing the auth file' {
        $pending = Join-Path $TestDrive 'fake.rotation-pending'
        [System.IO.File]::WriteAllLines($pending, @(
            'NEBULA_ROTATION_PENDING_V1',
            ('old=neo4j/' + $script:FakeOldCredential),
            ('new=neo4j/' + $script:FakeNewCredential)
        ))
        try {
            Mock Test-NebulaRotationCurrentUserAcl { $true }
            Mock Test-NebulaRotationRegularFile { $true }
            Mock Test-NebulaRotationAuthentication { $true }
            Mock Write-NebulaRotationAuthFile { throw 'auth file write must not happen in ambiguity' }
            $result = Resolve-NebulaRotationPending -DockerCliPath 'docker.exe' -ContainerId ('a' * 64) -AuthPath (Join-Path $TestDrive 'fake-auth') -PendingPath $pending

            $result.State | Should Be 'ambiguous'
            $result.Success | Should Be $false
            Test-Path -LiteralPath $pending | Should Be $true
            Assert-MockCalled Write-NebulaRotationAuthFile -Times 0
        }
        finally { }
    }

    It 'uses protected-file generation without prompting and stops before mutation when log preflight fails' {
        $authPath = Join-Path $TestDrive 'fake-generated-path-auth'
        [System.IO.File]::WriteAllText($authPath, ('neo4j/' + $script:FakeOldCredential), [System.Text.UTF8Encoding]::new($false))
        Mock Protect-NebulaSecretFile { $true }
        Mock Test-NebulaRotationCurrentUserAcl { $true }
        Mock Assert-NebulaRotationOfflineBackup { }
        Mock Assert-NebulaRotationLiveIdentity { [pscustomobject]@{ ContainerId = ('a' * 64) } }
        Mock Read-Host { throw 'the protected-file path must not prompt' }
        Mock Test-NebulaRotationAuthentication {
            (ConvertTo-NebulaRotationPlainText -Secret $Password) -eq $script:FakeOldCredential
        }
        Mock Test-NebulaRotationLogSettingsSafe { $false }
        Mock Invoke-NebulaRotationPasswordChange { throw 'password change must not run after failed preflight' }
        Mock Write-NebulaRotationProtectedFile { throw 'pending record must not be written after failed preflight' }
        Mock Write-NebulaRotationAuthFile { throw 'auth file must not be updated after failed preflight' }

        $threw = $false
        try {
            Invoke-NebulaNeo4jCredentialRotation `
                -ExpectedProject $script:NebulaRotationProject `
                -ExpectedContainerId ('a' * 64) `
                -ExpectedVolumeName $script:NebulaRotationVolumeName `
                -AuthFilePath $authPath `
                -BackupDirectory (Join-Path $TestDrive 'fake-backup') `
                -BackupForExpectedVolume `
                -UseProtectedAuthFileAndGenerate
        }
        catch { $threw = $true }

        $threw | Should Be $true
        [System.IO.File]::ReadAllText($authPath) | Should Be ('neo4j/' + $script:FakeOldCredential)
        Test-Path -LiteralPath ($authPath + $script:NebulaRotationPendingSuffix) | Should Be $false
        Assert-MockCalled Read-Host -Times 0
        Assert-MockCalled Test-NebulaRotationAuthentication -Times 2
        Assert-MockCalled Test-NebulaRotationLogSettingsSafe -Times 1
        Assert-MockCalled Invoke-NebulaRotationPasswordChange -Times 0
        Assert-MockCalled Write-NebulaRotationProtectedFile -Times 0
        Assert-MockCalled Write-NebulaRotationAuthFile -Times 0
    }
}
