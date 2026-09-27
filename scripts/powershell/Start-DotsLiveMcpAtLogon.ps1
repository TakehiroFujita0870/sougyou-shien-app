[CmdletBinding()]
param(
    [ValidateRange(1, 120)]
    [int]$StartupTimeoutSeconds = 120,

    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$WslDistribution = 'Ubuntu',

    [ValidatePattern('^/home/[A-Za-z0-9._/-]+$')]
    [string]$WslRepository = '/home/hp/projects/dots-live'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Write-DotsLogonDiagnostic.ps1')
$wslExecutable = Join-Path $env:WINDIR 'System32\wsl.exe'
if (-not (Test-Path -LiteralPath $wslExecutable -PathType Leaf)) {
    [void](Write-DotsLogonDiagnostic -Service 'live-mcp-tunnel' -Outcome 'failure' -Code 'wsl_unavailable')
    throw 'Windows Subsystem for Linux is unavailable.'
}

$startupScript = "$WslRepository/scripts/founder-graph/start-live-mcp-tunnel-at-logon.sh"
$keepaliveScript = "$WslRepository/scripts/founder-graph/keep-live-mcp-tunnel-alive.sh"
$script:DotsLiveMcpReadyRecorded = $false
& $wslExecutable --distribution $WslDistribution --exec env "DOTS_STARTUP_TIMEOUT_SECONDS=$StartupTimeoutSeconds" bash $startupScript | ForEach-Object {
    $line = [string]$_
    Write-Output $line
    if ($line -ceq '[dots live tunnel startup] Normal database and live MCP tunnel are ready.') {
        [void](Write-DotsLogonDiagnostic -Service 'live-mcp-tunnel' -Outcome 'success' -Code 'ready')
        $script:DotsLiveMcpReadyRecorded = $true
    }
}
if ($LASTEXITCODE -ne 0) {
    [void](Write-DotsLogonDiagnostic -Service 'live-mcp-tunnel' -Outcome 'failure' -Code 'mcp_tunnel_startup_failed')
    throw 'Live MCP tunnel startup failed closed; see the safe WSL startup message.'
}
if (-not $script:DotsLiveMcpReadyRecorded) {
    [void](Write-DotsLogonDiagnostic -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'database_not_ready')
    exit 0
}

# The ready marker is recorded only after the finite startup command exits.
# Keep WSL alive in a separate process so its open stdout cannot delay that log.
& $wslExecutable --distribution $WslDistribution --exec bash $keepaliveScript --wait-only
if ($LASTEXITCODE -ne 0) {
    [void](Write-DotsLogonDiagnostic -Service 'live-mcp-tunnel' -Outcome 'failure' -Code 'mcp_tunnel_startup_failed')
    throw 'Live MCP tunnel became inactive after startup; see the safe WSL startup message.'
}
