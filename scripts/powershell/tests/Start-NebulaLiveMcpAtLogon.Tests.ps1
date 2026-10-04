$script:LiveMcpStartupScriptPath = Join-Path $PSScriptRoot '..\Start-NebulaLiveMcpAtLogon.ps1'
$script:LiveMcpShellStartupPath = Join-Path $PSScriptRoot '..\..\founder-graph\start-live-mcp-tunnel-at-logon.sh'

Describe 'Start-NebulaLiveMcpAtLogon readiness reporting' {
    It 'matches the exact ready line emitted by the WSL startup script' {
        $powershellSource = Get-Content -LiteralPath $script:LiveMcpStartupScriptPath -Raw
        $shellSource = Get-Content -LiteralPath $script:LiveMcpShellStartupPath -Raw
        $readyLine = '[nebula live tunnel startup] Normal database and live MCP tunnel are ready.'

        $shellSource | Should Match ([regex]::Escape("log 'Normal database and live MCP tunnel are ready.'"))
        $powershellSource | Should Match ([regex]::Escape("-ceq '$readyLine'"))
    }

    It 'persists readiness before entering the long-lived WSL keepalive' {
        $powershellSource = Get-Content -LiteralPath $script:LiveMcpStartupScriptPath -Raw
        $readyRecord = $powershellSource.IndexOf("-Outcome 'success' -Code 'ready'", [StringComparison]::Ordinal)
        $keepalive = $powershellSource.IndexOf('--wait-only', [StringComparison]::Ordinal)

        $readyRecord | Should BeGreaterThan -1
        $keepalive | Should BeGreaterThan $readyRecord
    }
}
