$script:CoordinatorScriptPath = Join-Path $PSScriptRoot '..\Start-DotsLiveCoordinatorAtLogon.ps1'
. $script:CoordinatorScriptPath

Describe 'Invoke-DotsLiveLogonCoordinator' {
    It 'loads with the Windows built-in PowerShell before any service action' {
        $nativePowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $escapedPath = $script:CoordinatorScriptPath.Replace("'", "''")
        $check = ". '$escapedPath'; if ((Test-Path -LiteralPath `$DatabaseStartupScript) -and (Test-Path -LiteralPath `$TunnelStartupScript)) { exit 0 }; exit 7"
        & $nativePowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command $check | Out-Null
        $LASTEXITCODE | Should Be 0
    }

    BeforeEach {
        $script:CoordinatorCalls = @()
        $script:ApiCalls = @()
        Mock Write-DotsLogonDiagnostic { $true }
        Mock Start-DotsLiveDashboardController { $true }
        Mock Test-DotsLiveServicesReady { $false }
        Mock Start-DotsLiveApiService { $script:ApiCalls += $TimeoutMilliseconds; return $true }
        Mock Test-DotsLiveStopIntent { $false }
        Mock Start-Sleep {}
        Mock Get-DotsLiveTunnelDiagnosticSnapshot { [pscustomobject]@{ Path = 'unused'; Text = ''; LastWriteUtcTicks = 0L } }
        Mock Wait-DotsLiveTunnelReadiness { $true }
        Mock Invoke-DotsLiveHiddenStartupScript {
            $script:CoordinatorCalls += [pscustomobject]@{ ScriptPath = $ScriptPath; WaitForExit = [bool]$WaitForExit; StartupTimeoutSeconds = $StartupTimeoutSeconds }
            if ($WaitForExit) { return [pscustomobject]@{ Started = $true; ExitCode = 0; TimedOut = $false } }
            return [pscustomobject]@{ Started = $true; ExitCode = $null; TimedOut = $false; ProcessId = 1234 }
        }
    }

    It 'starts the dashboard controller before honoring an explicit stop without starting data services' {
        Mock Test-DotsLiveStopIntent { $true }
        $result = Invoke-DotsLiveLogonCoordinator -DatabaseScript 'db.ps1' -TunnelScript 'tunnel.ps1'

        $result.Code | Should Be 'explicit_stop'
        @($script:CoordinatorCalls).Count | Should Be 0
        Assert-MockCalled Start-DotsLiveDashboardController -Times 1
    }

    It 'does not start the database or tunnel when the dashboard controller is unavailable' {
        Mock Start-DotsLiveDashboardController { $false }
        $script:StopIntentReadCount = 0
        Mock Test-DotsLiveStopIntent { $script:StopIntentReadCount++; return $false }

        $result = Invoke-DotsLiveLogonCoordinator -DatabaseScript 'db.ps1' -TunnelScript 'tunnel.ps1'

        $result.Code | Should Be 'local_dashboard_unavailable'
        @($script:CoordinatorCalls).Count | Should Be 0
        $script:StopIntentReadCount | Should Be 0
    }

    It 'waits for database and API readiness before launching the existing tunnel wrapper' {
        $result = Invoke-DotsLiveLogonCoordinator -DatabaseScript 'db.ps1' -TunnelScript 'tunnel.ps1'

        $result.Started | Should Be $true
        @($script:ApiCalls).Count | Should Be 1
        $script:ApiCalls[0] | Should BeGreaterThan 0
        $script:ApiCalls[0] | Should BeLessThan 120001
        @($script:CoordinatorCalls).Count | Should Be 2
        $script:CoordinatorCalls[0].ScriptPath | Should Be 'db.ps1'
        $script:CoordinatorCalls[0].WaitForExit | Should Be $true
        $script:CoordinatorCalls[1].ScriptPath | Should Be 'tunnel.ps1'
        $script:CoordinatorCalls[1].WaitForExit | Should Be $false
        $script:CoordinatorCalls[1].StartupTimeoutSeconds | Should BeLessThan 121
        Assert-MockCalled Wait-DotsLiveTunnelReadiness -Times 1 -ParameterFilter { $ProcessId -eq 1234 -and $TimeoutMilliseconds -gt 0 -and $TimeoutMilliseconds -le 120000 }
    }

    It 'does not repeat preflight when all live services are already ready' {
        Mock Test-DotsLiveServicesReady { $true }

        $result = Invoke-DotsLiveLogonCoordinator -DatabaseScript 'db.ps1' -TunnelScript 'tunnel.ps1'

        $result.Code | Should Be 'ready'
        @($script:CoordinatorCalls).Count | Should Be 0
        @($script:ApiCalls).Count | Should Be 0
    }

    It 'gives the API its own readiness budget after a slow successful database preflight' {
        Mock Invoke-DotsLiveHiddenStartupScript {
            if ($WaitForExit) {
                [System.Threading.Thread]::Sleep(1500)
                return [pscustomobject]@{ Started = $true; ExitCode = 0; TimedOut = $false }
            }
            return [pscustomobject]@{ Started = $true; ExitCode = $null; TimedOut = $false; ProcessId = 1234 }
        }

        $result = Invoke-DotsLiveLogonCoordinator -DatabaseScript 'db.ps1' -TunnelScript 'tunnel.ps1'

        $result.Code | Should Be 'ready'
        $script:ApiCalls[0] | Should BeGreaterThan 119000
    }

    It 'never starts the tunnel when database preflight fails' {
        Mock Invoke-DotsLiveHiddenStartupScript {
            $script:CoordinatorCalls += $ScriptPath
            return [pscustomobject]@{ Started = $false; ExitCode = 127; TimedOut = $false }
        }

        $result = Invoke-DotsLiveLogonCoordinator -DatabaseScript 'db.ps1' -TunnelScript 'tunnel.ps1'

        $result.Code | Should Be 'database_not_ready'
        @($script:CoordinatorCalls).Count | Should Be 1
        $script:CoordinatorCalls[0] | Should Be 'db.ps1'
        @($script:ApiCalls).Count | Should Be 0
    }

    It 'retries a timed-out database preflight before starting the API' {
        $script:PreflightAttempt = 0
        Mock Invoke-DotsLiveHiddenStartupScript {
            if ($WaitForExit) {
                $script:PreflightAttempt++
                if ($script:PreflightAttempt -eq 1) { return [pscustomobject]@{ Started = $true; ExitCode = 124; TimedOut = $true } }
                return [pscustomobject]@{ Started = $true; ExitCode = 0; TimedOut = $false }
            }
            return [pscustomobject]@{ Started = $true; ExitCode = $null; TimedOut = $false; ProcessId = 1234 }
        }

        $result = Invoke-DotsLiveLogonCoordinator -DatabaseScript 'db.ps1' -TunnelScript 'tunnel.ps1'

        $result.Code | Should Be 'ready'
        $script:PreflightAttempt | Should Be 2
        @($script:ApiCalls).Count | Should Be 1
    }

    It 'does not start the tunnel when API systemd or HTTP health verification fails' {
        Mock Start-DotsLiveApiService { $script:ApiCalls += $TimeoutMilliseconds; return $false }
        $script:DiagnosticCalls = @()
        Mock Write-DotsLiveCoordinatorStatus {
            $script:DiagnosticCalls += ('{0}:{1}:{2}' -f $Service, $Outcome, $Code)
        }

        $result = Invoke-DotsLiveLogonCoordinator -DatabaseScript 'db.ps1' -TunnelScript 'tunnel.ps1'

        $result.Code | Should Be 'api_not_ready'
        @($script:CoordinatorCalls).Count | Should Be 1
        $script:CoordinatorCalls[0].ScriptPath | Should Be 'db.ps1'
        @($script:ApiCalls).Count | Should Be 1
        ($script:DiagnosticCalls -contains 'live-database:success:ready') | Should Be $true
        ($script:DiagnosticCalls -contains 'live-mcp-tunnel:unavailable:api_not_ready') | Should Be $true
    }

    It 'waits through an exited restore observation until the exact database is healthy' {
        $script:PreflightAttempt = 0
        Mock Invoke-DotsLiveHiddenStartupScript {
            $script:PreflightAttempt++
            $script:CoordinatorCalls += [pscustomobject]@{ ScriptPath = $ScriptPath; WaitForExit = [bool]$WaitForExit; StartupTimeoutSeconds = $StartupTimeoutSeconds }
            if ($script:PreflightAttempt -lt 3) { return [pscustomobject]@{ Started = $true; ExitCode = 1; TimedOut = $false } }
            if ($WaitForExit) { return [pscustomobject]@{ Started = $true; ExitCode = 0; TimedOut = $false } }
            return [pscustomobject]@{ Started = $true; ExitCode = $null; TimedOut = $false; ProcessId = 1234 }
        }

        $result = Invoke-DotsLiveLogonCoordinator -DatabaseScript 'db.ps1' -TunnelScript 'tunnel.ps1'

        $result.Started | Should Be $true
        @($script:CoordinatorCalls | Where-Object { $_.WaitForExit }).Count | Should Be 3
        $script:CoordinatorCalls[2].ScriptPath | Should Be 'db.ps1'
        $script:CoordinatorCalls[3].ScriptPath | Should Be 'tunnel.ps1'
        @($script:ApiCalls).Count | Should Be 1
    }

    It 'rechecks stop intent after database readiness and before tunnel launch' {
        $script:StopIntentReads = 0
        Mock Test-DotsLiveStopIntent { $script:StopIntentReads++; return ($script:StopIntentReads -ge 3) }

        $result = Invoke-DotsLiveLogonCoordinator -DatabaseScript 'db.ps1' -TunnelScript 'tunnel.ps1'

        $result.Code | Should Be 'explicit_stop'
        @($script:CoordinatorCalls).Count | Should Be 1
        $script:CoordinatorCalls[0].ScriptPath | Should Be 'db.ps1'
        @($script:ApiCalls).Count | Should Be 0
    }

    It 'fails closed when the tunnel child exits or never reports healthy' {
        Mock Wait-DotsLiveTunnelReadiness { $false }

        $result = Invoke-DotsLiveLogonCoordinator -DatabaseScript 'db.ps1' -TunnelScript 'tunnel.ps1'

        $result.Started | Should Be $false
        $result.Code | Should Be 'tunnel_not_ready'
    }

    It 'uses a no-window process and the hidden PowerShell window switch' {
        $source = Get-Content -LiteralPath $script:CoordinatorScriptPath -Raw

        $source | Should Match 'CreateNoWindow = \$true'
        $source | Should Match 'WaitForExit\(\$TimeoutMilliseconds\)'
        $source | Should Match '\-WindowStyle Hidden'
        $source | Should Match 'File\]::Move\(\$temporaryPath, \$Path\)'
    }

    It 'starts and verifies the fixed dashboard system service with one bounded hidden WSL process per command' {
        $source = Get-Content -LiteralPath $script:CoordinatorScriptPath -Raw

        $source | Should Match 'Start-DotsLiveDashboardController'
        $source | Should Match '--distribution Ubuntu --exec systemctl --user start dots-local-dashboard\.service'
        $source | Should Match '--distribution Ubuntu --exec systemctl --user is-active --quiet dots-local-dashboard\.service'
        $source | Should Match 'WaitForExit\(\$remaining\)'
        $source | Should Match 'CreateNoWindow = \$true'
        $source | Should Match '\[ValidateRange\(1, 120000\)\]\[int\]\$TimeoutMilliseconds = 20000'
    }

    It 'starts and verifies the fixed API system service and its loopback health response before the tunnel' {
        $source = Get-Content -LiteralPath $script:CoordinatorScriptPath -Raw
        $apiInvocation = $source.IndexOf('Start-DotsLiveApiService -TimeoutMilliseconds', [StringComparison]::Ordinal)
        $tunnelInvocation = $source.IndexOf('Invoke-DotsLiveHiddenStartupScript -ScriptPath $TunnelScript', [StringComparison]::Ordinal)

        $apiInvocation | Should BeGreaterThan -1
        $tunnelInvocation | Should BeGreaterThan $apiInvocation
        $source | Should Match 'Start-DotsLiveApiService'
        $source | Should Match '--distribution Ubuntu --exec systemctl --user start dots-live-api\.service'
        $source | Should Match '--distribution Ubuntu --exec systemctl --user is-active --quiet dots-live-api\.service'
        $source | Should Match 'http://127\.0\.0\.1:8000/health'
        $source | Should Match '\$health\.status -ceq ''ok'' -and \$health\.service -ceq ''dots-api'''
        $source | Should Match 'Start-DotsLiveApiService -TimeoutMilliseconds'
    }
}

Describe 'Wait-DotsLiveTunnelReadiness' {
    It 'accepts only a fresh ready diagnostic while the wrapper process remains alive' {
        $readyPath = Join-Path $TestDrive 'live-mcp-tunnel-latest.log'
        [System.IO.File]::WriteAllText($readyPath, "2026-09-25T00:00:00.000Z service=live-mcp-tunnel outcome=success code=ready`r`n")
        $before = [pscustomobject]@{ Path = $readyPath; Text = ''; LastWriteUtcTicks = 0L }
        Mock Test-DotsLiveStopIntent { $false }
        Mock Get-Process { [pscustomobject]@{ Id = $Id } }

        (Wait-DotsLiveTunnelReadiness -ProcessId 1234 -BeforeStart $before -TimeoutMilliseconds 1000) | Should Be $true
    }

    It 'rejects a fresh unavailable diagnostic' {
        $readyPath = Join-Path $TestDrive 'live-mcp-tunnel-latest.log'
        [System.IO.File]::WriteAllText($readyPath, '2026-09-25T00:00:00.000Z service=live-mcp-tunnel outcome=unavailable code=database_not_ready')
        $before = [pscustomobject]@{ Path = $readyPath; Text = ''; LastWriteUtcTicks = 0L }
        Mock Test-DotsLiveStopIntent { $false }
        Mock Get-Process { [pscustomobject]@{ Id = $Id } }

        (Wait-DotsLiveTunnelReadiness -ProcessId 1234 -BeforeStart $before -TimeoutMilliseconds 1000) | Should Be $false
    }
}

Describe 'Dots live stop-intent lifecycle' {
    It 'sets, reads, and clears a marker with the restricted directory ACL' {
        $marker = Join-Path $TestDrive 'live-stop-intent\stopped'

        (Set-DotsLiveStopIntent -Path $marker) | Should Be $true
        (Test-DotsLiveStopIntent -Path $marker) | Should Be $true
        (Clear-DotsLiveStopIntent -Path $marker) | Should Be $true
        (Test-DotsLiveStopIntent -Path $marker) | Should Be $false
    }

    It 'uses a dedicated startup directory and atomically publishes the protected marker' {
        $source = Get-Content -LiteralPath $script:CoordinatorScriptPath -Raw

        $source | Should Match 'live-stop-intent\\stopped'
        $source | Should Match 'SetAccessRuleProtection\(\$true, \$false\)'
        $source | Should Match 'FileMode\]::CreateNew'
        $source | Should Match 'File\]::Move\(\$temporaryPath, \$Path\)'
        $source | Should Match 'Remove-Item -LiteralPath \$Path -Force'
    }
}
