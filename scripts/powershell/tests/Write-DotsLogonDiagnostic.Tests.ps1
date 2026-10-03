$script:LogonDiagnosticScriptPath = Join-Path $PSScriptRoot '..\Write-DotsLogonDiagnostic.ps1'
. $script:LogonDiagnosticScriptPath

Describe 'Write-DotsLogonDiagnostic' {
    BeforeEach {
        $script:OriginalLocalAppData = $env:LOCALAPPDATA
        $env:LOCALAPPDATA = $TestDrive
    }

    AfterEach {
        $env:LOCALAPPDATA = $script:OriginalLocalAppData
    }

    It 'writes only the latest allow-listed result with a UTC timestamp' {
        Write-DotsLogonDiagnostic -Service 'live-database' -Outcome 'success' -Code 'ready' | Should Be $true
        Write-DotsLogonDiagnostic -Service 'live-database' -Outcome 'failure' -Code 'database_preflight_failed' | Should Be $true

        $path = Join-Path $TestDrive 'Dots\startup\live-database-latest.log'
        $lines = @(Get-Content -LiteralPath $path)
        $lines.Count | Should Be 1
        $lines[0] | Should Match '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z service=live-database outcome=failure code=database_preflight_failed$'
    }

    It 'rejects raw exception or secret text as a diagnostic code' {
        $secretMarker = 'secret-marker-do-not-write'
        $didThrow = $false
        try {
            Write-DotsLogonDiagnostic -Service 'live-mcp-tunnel' -Outcome 'failure' -Code $secretMarker
        }
        catch {
            $didThrow = $true
        }

        $didThrow | Should Be $true
        Test-Path -LiteralPath (Join-Path $TestDrive 'Dots\startup\live-mcp-tunnel-latest.log') | Should Be $false
        Get-ChildItem -LiteralPath $TestDrive -Recurse -File | ForEach-Object {
            (Get-Content -LiteralPath $_.FullName -Raw) | Should Not Match $secretMarker
        }
    }

    It 'records a safely unavailable tunnel without calling it ready' {
        Write-DotsLogonDiagnostic -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'database_not_ready' | Should Be $true

        $path = Join-Path $TestDrive 'Dots\startup\live-mcp-tunnel-latest.log'
        $record = Get-Content -LiteralPath $path -Raw
        $record | Should Match 'service=live-mcp-tunnel outcome=unavailable code=database_not_ready'
        $record | Should Not Match 'outcome=success'
    }

    It 'distinguishes API failure from database failure' {
        Write-DotsLogonDiagnostic -Service 'live-database' -Outcome 'success' -Code 'ready' | Should Be $true
        Write-DotsLogonDiagnostic -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'api_not_ready' | Should Be $true

        $database = Get-Content -LiteralPath (Join-Path $TestDrive 'Dots\startup\live-database-latest.log') -Raw
        $tunnel = Get-Content -LiteralPath (Join-Path $TestDrive 'Dots\startup\live-mcp-tunnel-latest.log') -Raw
        $database | Should Match 'outcome=success code=ready'
        $tunnel | Should Match 'outcome=unavailable code=api_not_ready'
    }
}
