$helper = Join-Path $PSScriptRoot '..\founder-graph.ps1'
$helper = (Resolve-Path -LiteralPath $helper).Path

Describe 'backup protected auth-file handoff' {
    BeforeAll {
        $script:originalAuthFile = $env:FOUNDER_GRAPH_NEO4J_AUTH_FILE
        $script:originalRawAuth = $env:FOUNDER_GRAPH_NEO4J_AUTH
        $script:originalProject = $env:FOUNDER_GRAPH_COMPOSE_PROJECT
    }

    BeforeEach {
        $script:testRoot = Join-Path $env:TEMP ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $script:testRoot | Out-Null
        $script:fakeAuthFile = Join-Path $script:testRoot 'auth.secret'
        [System.IO.File]::WriteAllText($script:fakeAuthFile, 'fake-not-a-secret')
        $acl = Get-Acl -LiteralPath $script:fakeAuthFile
        $acl.SetAccessRuleProtection($true, $false)
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $currentRule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow')
        $systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule('SYSTEM', 'FullControl', 'Allow')
        $adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule('BUILTIN\Administrators', 'FullControl', 'Allow')
        $acl.SetAccessRule($currentRule)
        $acl.AddAccessRule($systemRule)
        $acl.AddAccessRule($adminRule)
        Set-Acl -LiteralPath $script:fakeAuthFile -AclObject $acl
        $env:FOUNDER_GRAPH_NEO4J_AUTH_FILE = $script:fakeAuthFile
        Remove-Item Env:FOUNDER_GRAPH_NEO4J_AUTH -ErrorAction SilentlyContinue
        $env:FOUNDER_GRAPH_COMPOSE_PROJECT = 'founder-graph-local'
        $global:fakeDockerCalls = @()
        $global:fakeDockerAuthSource = $script:fakeAuthFile
        $global:fakeRestoreCreateExit = 1
        $global:fakeRestoreRunExit = 1
        $global:fakeRestoreSource = $null

        function global:docker {
            $call = $args -join ' '
            $global:fakeDockerCalls += $call
            $global:LASTEXITCODE = 0
            if ($call -like '*volume inspect*') {
                $labels = @{
                    'com.openai.founder_graph.role' = 'restore'
                    'com.openai.founder_graph.database' = 'neo4j'
                    'com.openai.founder_graph.project' = 'founder-graph-local'
                    'com.openai.founder_graph.source' = $global:fakeRestoreSource
                }
                Write-Output (ConvertTo-Json -InputObject $labels -Compress)
                return
            }
            if ($call -like '*inspect*') {
                $mount = [pscustomobject]@{ Type = 'bind'; Source = $global:fakeDockerAuthSource; Destination = '/run/secrets/founder_graph_auth'; RW = $false }
                Write-Output (ConvertTo-Json -InputObject @($mount) -Compress)
                return
            }
            if ($call -like '*ps -q neo4j*') { Write-Output 'fake-container-id'; return }
            if ($call -like '* run *') { $global:LASTEXITCODE = $global:fakeRestoreRunExit; return }
            if ($call -like '*volume ls*') { Write-Output 'existing-safe-volume'; return }
            if ($call -like '*volume create*') { $global:LASTEXITCODE = $global:fakeRestoreCreateExit; return }
            if ($call -like '*ps --format*') { Write-Output 'healthy'; return }
        }
    }

    AfterEach {
        Remove-Item Function:\global:docker -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $script:testRoot) { Remove-Item -LiteralPath $script:testRoot -Recurse -Force }
    }

    AfterAll {
        if ($null -eq $script:originalAuthFile) { Remove-Item Env:FOUNDER_GRAPH_NEO4J_AUTH_FILE -ErrorAction SilentlyContinue }
        else { $env:FOUNDER_GRAPH_NEO4J_AUTH_FILE = $script:originalAuthFile }
        if ($null -eq $script:originalRawAuth) { Remove-Item Env:FOUNDER_GRAPH_NEO4J_AUTH -ErrorAction SilentlyContinue }
        else { $env:FOUNDER_GRAPH_NEO4J_AUTH = $script:originalRawAuth }
        if ($null -eq $script:originalProject) { Remove-Item Env:FOUNDER_GRAPH_COMPOSE_PROJECT -ErrorAction SilentlyContinue }
        else { $env:FOUNDER_GRAPH_COMPOSE_PROJECT = $script:originalProject }
    }

    It 'rejects a missing auth file before any container stop' {
        $env:FOUNDER_GRAPH_NEO4J_AUTH_FILE = Join-Path $script:testRoot 'missing.secret'
        { & $helper backup -Path (Join-Path $script:testRoot 'backup') } | Should Throw
        ($global:fakeDockerCalls -join "`n") | Should Not Match 'stop neo4j'
    }

    It 'preserves the caller-owned file and restores its path after dump failure' {
        $failureMessage = $null
        try { & $helper backup -Path (Join-Path $script:testRoot 'backup') } catch { $failureMessage = $_.Exception.Message }
        $failureMessage | Should Not BeNullOrEmpty
        $env:FOUNDER_GRAPH_NEO4J_AUTH_FILE | Should Be $script:fakeAuthFile
        (Test-Path -LiteralPath $script:fakeAuthFile) | Should Be $true
        ($global:fakeDockerCalls -join "`n") | Should Match 'stop neo4j'
        ($global:fakeDockerCalls -join "`n") | Should Match 'start neo4j'
        ($global:fakeDockerCalls -join "`n") | Should Match 'ps --format'
        ($global:fakeDockerCalls -join "`n") | Should Not Match 'Microsoft.PowerShell.Core\\FileSystem::'
        ($global:fakeDockerCalls -join "`n") | Should Match '--file \\\\wsl.localhost'
        ($global:fakeDockerCalls -join "`n") | Should Not Match 'fake-not-a-secret'
    }

    It 'rejects raw auth environment values in protected-file mode before stopping' {
        $env:FOUNDER_GRAPH_NEO4J_AUTH = 'neo4j/fake-not-a-secret'
        { & $helper backup -Path (Join-Path $script:testRoot 'backup') } | Should Throw
        ($global:fakeDockerCalls -join "`n") | Should Not Match 'stop neo4j'
    }

    It 'rejects a path that differs from the existing container mount before stopping' {
        $global:fakeDockerAuthSource = Join-Path $script:testRoot 'different-auth-file'
        { & $helper backup -Path (Join-Path $script:testRoot 'backup') } | Should Throw
        ($global:fakeDockerCalls -join "`n") | Should Not Match 'stop neo4j'
        (Test-Path -LiteralPath $script:fakeAuthFile) | Should Be $true
    }

    It 'checks absent restore volumes without an expected-error inspect under Stop preference' {
        $source = Join-Path $script:testRoot 'restore-source'
        New-Item -ItemType Directory -Path $source | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $source 'neo4j.dump'), 'fake-dump')
        [System.IO.File]::WriteAllText((Join-Path $source 'system.dump'), 'fake-system-dump')
        { & $helper restore -Path $source -RestoreVolume 'founder-graph-restore-fake-test' } | Should Throw
        ($global:fakeDockerCalls -join "`n") | Should Match 'volume ls'
        ($global:fakeDockerCalls -join "`n") | Should Match 'volume create'
        ($global:fakeDockerCalls -join "`n") | Should Not Match 'volume inspect'
        ($global:fakeDockerCalls -join "`n") | Should Not Match 'docker run'
    }

    It 'reads restore volume labels as JSON before isolated load commands' {
        $source = Join-Path $script:testRoot 'restore-source'
        New-Item -ItemType Directory -Path $source | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $source 'neo4j.dump'), 'fake-dump')
        [System.IO.File]::WriteAllText((Join-Path $source 'system.dump'), 'fake-system-dump')
        $global:fakeRestoreSource = (Get-Item -LiteralPath $source).FullName
        $global:fakeRestoreCreateExit = 0
        $global:fakeRestoreRunExit = 0
        & $helper restore -Path $source -RestoreVolume 'founder-graph-restore-fake-test'
        ($global:fakeDockerCalls -join "`n") | Should Match 'volume inspect --format \{\{json \.Labels\}\}'
        ($global:fakeDockerCalls -join "`n") | Should Match '--network none'
        ($global:fakeDockerCalls -join "`n") | Should Not Match 'index \.Labels'
    }

}
