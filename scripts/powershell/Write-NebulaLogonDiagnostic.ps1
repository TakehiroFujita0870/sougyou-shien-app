function Write-NebulaLogonDiagnostic {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('live-database', 'live-mcp-tunnel')]
        [string]$Service,

        [Parameter(Mandatory = $true)]
        [ValidateSet('success', 'failure', 'unavailable')]
        [string]$Outcome,

        [Parameter(Mandatory = $true)]
        [ValidateSet('ready', 'database_preflight_failed', 'database_not_ready', 'api_not_ready', 'mcp_tunnel_startup_failed', 'wsl_unavailable', 'explicit_stop')]
        [string]$Code
    )

    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        return $false
    }

    $directory = Join-Path $env:LOCALAPPDATA 'Nebula\startup'
    $path = Join-Path $directory ($Service + '-latest.log')
    $timestamp = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ', [Globalization.CultureInfo]::InvariantCulture)
    $line = '{0} service={1} outcome={2} code={3}' -f $timestamp, $Service, $Outcome, $Code

    try {
        [void](New-Item -ItemType Directory -Path $directory -Force -ErrorAction Stop)
        [System.IO.File]::WriteAllText($path, $line + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
        return $true
    }
    catch {
        # Diagnostics must never change startup behavior or expose exception text.
        return $false
    }
}
