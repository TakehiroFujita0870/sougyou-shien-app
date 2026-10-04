[CmdletBinding()]
param(
    [string]$DatabaseStartupScript,
    [string]$TunnelStartupScript
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($DatabaseStartupScript)) {
    $DatabaseStartupScript = Join-Path $PSScriptRoot 'Start-NebulaLiveAtLogon.ps1'
}
if ([string]::IsNullOrWhiteSpace($TunnelStartupScript)) {
    $TunnelStartupScript = Join-Path $PSScriptRoot 'Start-NebulaLiveMcpAtLogon.ps1'
}
. (Join-Path $PSScriptRoot 'Write-NebulaLogonDiagnostic.ps1')

function Write-NebulaLiveCoordinatorStatus {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('live-database', 'live-mcp-tunnel')][string]$Service,
        [Parameter(Mandatory = $true)][ValidateSet('success', 'failure', 'unavailable')][string]$Outcome,
        [Parameter(Mandatory = $true)][ValidateSet('ready', 'database_preflight_failed', 'database_not_ready', 'api_not_ready', 'mcp_tunnel_startup_failed', 'wsl_unavailable', 'explicit_stop')][string]$Code
    )
    [void](Write-NebulaLogonDiagnostic -Service $Service -Outcome $Outcome -Code $Code)
}

function Get-NebulaLiveStopIntentPath {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'The current-user local application data directory is unavailable.' }
    return Join-Path $env:LOCALAPPDATA 'Nebula\startup\live-stop-intent\stopped'
}

function Get-NebulaLiveStopIntentAcl {
    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    if ($null -eq $currentSid) { throw 'The current Windows user could not be identified.' }
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    $propagation = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    foreach ($sid in @($currentSid, (New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')), (New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')))) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, [System.Security.AccessControl.FileSystemRights]::FullControl, $inheritance, $propagation, $allow)
        [void]$acl.AddAccessRule($rule)
    }
    return $acl
}

function Initialize-NebulaLiveStopIntentDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) { [void](New-Item -ItemType Directory -Path $directory -Force -ErrorAction Stop) }
    Set-Acl -LiteralPath $directory -AclObject (Get-NebulaLiveStopIntentAcl) -ErrorAction Stop
    $acl = Get-Acl -LiteralPath $directory -ErrorAction Stop
    if (-not (Test-NebulaLiveStopIntentAcl -Acl $acl)) { throw 'The stop-intent directory permissions could not be verified.' }
}

function Test-NebulaLiveStopIntentAcl {
    param([Parameter(Mandatory = $true)][System.Security.AccessControl.DirectorySecurity]$Acl)
    if (-not $Acl.AreAccessRulesProtected) { return $false }
    $rules = @($Acl.Access)
    if ($rules.Count -ne 3) { return $false }
    $expectedSids = @(
        [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value,
        'S-1-5-18',
        'S-1-5-32-544'
    )
    foreach ($rule in $rules) {
        if ($rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
            $rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl) { return $false }
        try { $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }
        catch { return $false }
        if ($expectedSids -notcontains $sid) { return $false }
        $expectedSids = @($expectedSids | Where-Object { $_ -cne $sid })
    }
    return ($expectedSids.Count -eq 0)
}

function Test-NebulaLiveStopIntent {
    [CmdletBinding()]
    param([string]$Path = (Get-NebulaLiveStopIntentPath))
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $directoryAcl = Get-Acl -LiteralPath (Split-Path -Parent $Path) -ErrorAction Stop
    if (-not (Test-NebulaLiveStopIntentAcl -Acl $directoryAcl)) { throw 'The stop-intent marker permissions could not be verified.' }
    return $true
}

function Set-NebulaLiveStopIntent {
    [CmdletBinding()]
    param([string]$Path = (Get-NebulaLiveStopIntentPath))
    Initialize-NebulaLiveStopIntentDirectory -Path $Path
    $temporaryPath = Join-Path (Split-Path -Parent $Path) ('.stopped-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $encoding = New-Object System.Text.UTF8Encoding($false)
    try {
        $stream = New-Object System.IO.FileStream($temporaryPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        try { $bytes = $encoding.GetBytes("explicit-stop`n"); $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) }
        finally { $stream.Dispose() }
        if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $temporaryPath -Force }
        else {
            try { [System.IO.File]::Move($temporaryPath, $Path) }
            catch [System.IO.IOException] {
                if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw }
                Remove-Item -LiteralPath $temporaryPath -Force
            }
        }
    }
    finally { if (Test-Path -LiteralPath $temporaryPath) { Remove-Item -LiteralPath $temporaryPath -Force } }
    return (Test-NebulaLiveStopIntent -Path $Path)
}

function Clear-NebulaLiveStopIntent {
    [CmdletBinding()]
    param([string]$Path = (Get-NebulaLiveStopIntentPath))
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $true }
    if (-not (Test-NebulaLiveStopIntent -Path $Path)) { return $false }
    Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
    return (-not (Test-Path -LiteralPath $Path))
}

function Invoke-NebulaLiveHiddenStartupScript {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)][switch]$WaitForExit,
        [ValidateRange(1, 120)][int]$StartupTimeoutSeconds = 120,
        [ValidateRange(1, 120000)][int]$TimeoutMilliseconds = 120000
    )
    if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) { return [pscustomobject]@{ Started = $false; ExitCode = 127 } }
    $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) { return [pscustomobject]@{ Started = $false; ExitCode = 127 } }
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $powershell
    $startInfo.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -StartupTimeoutSeconds {1}' -f $ScriptPath, $StartupTimeoutSeconds
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { return [pscustomobject]@{ Started = $false; ExitCode = 127 } }
        if (-not $WaitForExit) { return [pscustomobject]@{ Started = $true; ExitCode = $null; TimedOut = $false; ProcessId = $process.Id } }
        if (-not $process.WaitForExit($TimeoutMilliseconds)) {
            try { $process.Kill() } catch { }
            return [pscustomobject]@{ Started = $true; ExitCode = 124; TimedOut = $true; ProcessId = $process.Id }
        }
        return [pscustomobject]@{ Started = $true; ExitCode = $process.ExitCode; ProcessId = $process.Id }
    }
    catch { return [pscustomobject]@{ Started = $false; ExitCode = 127 } }
    finally { $process.Dispose() }
}

function Start-NebulaLiveDashboardController {
    [CmdletBinding()]
    param([ValidateRange(1, 120000)][int]$TimeoutMilliseconds = 20000)
    $wsl = Join-Path $env:WINDIR 'System32\wsl.exe'
    if (-not (Test-Path -LiteralPath $wsl -PathType Leaf)) { return $false }
    $deadline = [System.Diagnostics.Stopwatch]::StartNew()
    foreach ($operation in @('start', 'is-active')) {
        $remaining = $TimeoutMilliseconds - [int]$deadline.ElapsedMilliseconds
        if ($remaining -le 0) { return $false }
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $wsl
        if ($operation -eq 'start') {
            $startInfo.Arguments = '--distribution Ubuntu --exec systemctl --user start nebula-local-dashboard.service'
        } else {
            $startInfo.Arguments = '--distribution Ubuntu --exec systemctl --user is-active --quiet nebula-local-dashboard.service'
        }
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $startInfo
        try {
            if (-not $process.Start()) { return $false }
            if (-not $process.WaitForExit($remaining)) {
                try { $process.Kill() } catch { }
                return $false
            }
            if ($process.ExitCode -ne 0) { return $false }
        }
        catch { return $false }
        finally { $process.Dispose() }
    }
    return $true
}

function Start-NebulaLiveApiService {
    [CmdletBinding()]
    param([ValidateRange(1, 120000)][int]$TimeoutMilliseconds = 120000)
    $wsl = Join-Path $env:WINDIR 'System32\wsl.exe'
    if (-not (Test-Path -LiteralPath $wsl -PathType Leaf)) { return $false }
    $deadline = [System.Diagnostics.Stopwatch]::StartNew()
    foreach ($operation in @('start', 'is-active')) {
        $remaining = $TimeoutMilliseconds - [int]$deadline.ElapsedMilliseconds
        if ($remaining -le 0) { return $false }
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $wsl
        if ($operation -eq 'start') {
            $startInfo.Arguments = '--distribution Ubuntu --exec systemctl --user start nebula-live-api.service'
        } else {
            $startInfo.Arguments = '--distribution Ubuntu --exec systemctl --user is-active --quiet nebula-live-api.service'
        }
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $startInfo
        try {
            if (-not $process.Start()) { return $false }
            if (-not $process.WaitForExit($remaining)) {
                try { $process.Kill() } catch { }
                return $false
            }
            if ($process.ExitCode -ne 0) { return $false }
        }
        catch { return $false }
        finally { $process.Dispose() }
    }

    while ($deadline.ElapsedMilliseconds -lt $TimeoutMilliseconds) {
        $remaining = $TimeoutMilliseconds - [int]$deadline.ElapsedMilliseconds
        if ($remaining -le 0) { break }
        $request = [System.Net.HttpWebRequest]::Create('http://127.0.0.1:8000/health')
        $request.Method = 'GET'
        $request.Timeout = [Math]::Max(1, [Math]::Min(2000, $remaining))
        $request.ReadWriteTimeout = $request.Timeout
        try {
            $response = [System.Net.HttpWebResponse]$request.GetResponse()
            try {
                if ([int]$response.StatusCode -ne 200) { return $false }
                $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
                try { $health = $reader.ReadToEnd() | ConvertFrom-Json -ErrorAction Stop }
                finally { $reader.Dispose() }
                if ($health.status -ceq 'ok' -and $health.service -ceq 'nebula-api') { return $true }
            }
            finally { $response.Dispose() }
        }
        catch { }
        $remaining = $TimeoutMilliseconds - [int]$deadline.ElapsedMilliseconds
        if ($remaining -le 0) { break }
        Start-Sleep -Milliseconds ([Math]::Min(500, $remaining))
    }
    return $false
}

function Test-NebulaLiveServicesReady {
    # A quick, read-only check keeps a recurring recovery task from repeatedly
    # running Docker preflight against an already healthy installation.
    try {
        $dashboardRequest = [System.Net.HttpWebRequest]::Create('http://localhost:8765/api/status')
        $dashboardRequest.Timeout = 3000
        $dashboardRequest.ReadWriteTimeout = 3000
        $dashboardResponse = [System.Net.HttpWebResponse]$dashboardRequest.GetResponse()
        try {
            $reader = New-Object System.IO.StreamReader($dashboardResponse.GetResponseStream())
            try { $state = $reader.ReadToEnd() | ConvertFrom-Json -ErrorAction Stop }
            finally { $reader.Dispose() }
        }
        finally { $dashboardResponse.Dispose() }
        if ($state.services.database -cne 'running' -or $state.services.intent -cne 'running' -or
            $state.services.api -cne 'running' -or $state.services.tunnel -cne 'running') { return $false }

        $apiRequest = [System.Net.HttpWebRequest]::Create('http://127.0.0.1:8000/health')
        $apiRequest.Timeout = 3000
        $apiRequest.ReadWriteTimeout = 3000
        $apiResponse = [System.Net.HttpWebResponse]$apiRequest.GetResponse()
        try {
            $reader = New-Object System.IO.StreamReader($apiResponse.GetResponseStream())
            try { $health = $reader.ReadToEnd() | ConvertFrom-Json -ErrorAction Stop }
            finally { $reader.Dispose() }
        }
        finally { $apiResponse.Dispose() }
        return ($health.status -ceq 'ok' -and $health.service -ceq 'nebula-api')
    }
    catch { return $false }
}

function Get-NebulaLiveTunnelDiagnosticSnapshot {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { return [pscustomobject]@{ Path = $null; Text = ''; LastWriteUtcTicks = 0L } }
    $path = Join-Path $env:LOCALAPPDATA 'Nebula\startup\live-mcp-tunnel-latest.log'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return [pscustomobject]@{ Path = $path; Text = ''; LastWriteUtcTicks = 0L } }
    $item = Get-Item -LiteralPath $path -ErrorAction Stop
    return [pscustomobject]@{ Path = $path; Text = [System.IO.File]::ReadAllText($path); LastWriteUtcTicks = $item.LastWriteTimeUtc.Ticks }
}

function Wait-NebulaLiveTunnelReadiness {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][psobject]$BeforeStart,
        [ValidateRange(1, 120000)][int]$TimeoutMilliseconds = 120000
    )
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.ElapsedMilliseconds -lt $TimeoutMilliseconds) {
        if (Test-NebulaLiveStopIntent) { return $false }
        try {
            if ($null -ne $BeforeStart.Path -and (Test-Path -LiteralPath $BeforeStart.Path -PathType Leaf)) {
                $item = Get-Item -LiteralPath $BeforeStart.Path -ErrorAction Stop
                $text = [System.IO.File]::ReadAllText($BeforeStart.Path)
                $isFresh = ($text -cne $BeforeStart.Text) -or ($item.LastWriteTimeUtc.Ticks -gt $BeforeStart.LastWriteUtcTicks)
                if ($isFresh) {
                    $line = $text.TrimEnd([char[]]@("`r", "`n"))
                    if ($line -match 'service=live-mcp-tunnel outcome=success code=ready$') {
                        try { [void](Get-Process -Id $ProcessId -ErrorAction Stop); return $true }
                        catch { return $false }
                    }
                    if ($line -match 'service=live-mcp-tunnel outcome=(failure|unavailable) code=') { return $false }
                }
            }
            [void](Get-Process -Id $ProcessId -ErrorAction Stop)
        }
        catch { return $false }
        $remaining = $TimeoutMilliseconds - [int]$timer.ElapsedMilliseconds
        if ($remaining -le 0) { break }
        Start-Sleep -Milliseconds ([Math]::Min(500, $remaining))
    }
    return $false
}

function Invoke-NebulaLiveLogonCoordinator {
    [CmdletBinding()]
    param([string]$DatabaseScript = $DatabaseStartupScript, [string]$TunnelScript = $TunnelStartupScript)
    if (-not (Start-NebulaLiveDashboardController)) {
        Write-NebulaLiveCoordinatorStatus -Service 'live-database' -Outcome 'unavailable' -Code 'wsl_unavailable'
        Write-NebulaLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'wsl_unavailable'
        return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'local_dashboard_unavailable' }
    }
    if (Test-NebulaLiveStopIntent) {
        Write-NebulaLiveCoordinatorStatus -Service 'live-database' -Outcome 'unavailable' -Code 'explicit_stop'
        Write-NebulaLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'explicit_stop'
        return [pscustomobject]@{ Started = $false; Outcome = 'stopped'; Code = 'explicit_stop' }
    }
    if (Test-NebulaLiveServicesReady) {
        return [pscustomobject]@{ Started = $true; Outcome = 'success'; Code = 'ready' }
    }
    $databaseDeadline = [System.Diagnostics.Stopwatch]::StartNew()
    $database = $null
    while ($databaseDeadline.ElapsedMilliseconds -lt 180000) {
        if (Test-NebulaLiveStopIntent) {
            Write-NebulaLiveCoordinatorStatus -Service 'live-database' -Outcome 'unavailable' -Code 'explicit_stop'
            Write-NebulaLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'explicit_stop'
            return [pscustomobject]@{ Started = $false; Outcome = 'stopped'; Code = 'explicit_stop' }
        }
        $remaining = [Math]::Max(1, 180000 - [int]$databaseDeadline.ElapsedMilliseconds)
        $remainingSeconds = [Math]::Min(120, [int][Math]::Floor($remaining / 1000))
        if ($remainingSeconds -lt 1) { break }
        $database = Invoke-NebulaLiveHiddenStartupScript -ScriptPath $DatabaseScript -WaitForExit -StartupTimeoutSeconds $remainingSeconds -TimeoutMilliseconds ([Math]::Min(120000, $remaining))
        if (-not $database.Started) {
            Write-NebulaLiveCoordinatorStatus -Service 'live-database' -Outcome 'failure' -Code 'database_preflight_failed'
            Write-NebulaLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'database_not_ready'
            return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'database_not_ready' }
        }
        if (-not $database.TimedOut -and $database.ExitCode -eq 0) { break }
        $remaining = 180000 - [int]$databaseDeadline.ElapsedMilliseconds
        if ($remaining -le 0) { break }
        Start-Sleep -Milliseconds ([Math]::Min(1000, $remaining))
    }
    if ($null -eq $database -or $database.TimedOut -or $database.ExitCode -ne 0) {
        Write-NebulaLiveCoordinatorStatus -Service 'live-database' -Outcome 'failure' -Code 'database_preflight_failed'
        Write-NebulaLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'database_not_ready'
        return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'database_not_ready' }
    }
    # A stop request can arrive while the read-only database preflight is waiting.
    if (Test-NebulaLiveStopIntent) {
        Write-NebulaLiveCoordinatorStatus -Service 'live-database' -Outcome 'unavailable' -Code 'explicit_stop'
        Write-NebulaLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'explicit_stop'
        return [pscustomobject]@{ Started = $false; Outcome = 'stopped'; Code = 'explicit_stop' }
    }
    Write-NebulaLiveCoordinatorStatus -Service 'live-database' -Outcome 'success' -Code 'ready'
    if (-not (Start-NebulaLiveApiService -TimeoutMilliseconds 120000)) {
        Write-NebulaLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'api_not_ready'
        return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'api_not_ready' }
    }
    # Do not expose ChatGPT access if a stop request arrived while the API became ready.
    if (Test-NebulaLiveStopIntent) {
        Write-NebulaLiveCoordinatorStatus -Service 'live-database' -Outcome 'unavailable' -Code 'explicit_stop'
        Write-NebulaLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'explicit_stop'
        return [pscustomobject]@{ Started = $false; Outcome = 'stopped'; Code = 'explicit_stop' }
    }
    $beforeTunnel = Get-NebulaLiveTunnelDiagnosticSnapshot
    $tunnel = Invoke-NebulaLiveHiddenStartupScript -ScriptPath $TunnelScript -WaitForExit:$false -StartupTimeoutSeconds 120
    if (-not $tunnel.Started) {
        Write-NebulaLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'failure' -Code 'mcp_tunnel_startup_failed'
        return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'tunnel_not_started' }
    }
    $tunnelReady = Wait-NebulaLiveTunnelReadiness -ProcessId $tunnel.ProcessId -BeforeStart $beforeTunnel -TimeoutMilliseconds 120000
    if (-not $tunnelReady) {
        Write-NebulaLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'failure' -Code 'mcp_tunnel_startup_failed'
        return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'tunnel_not_ready' }
    }
    return [pscustomobject]@{ Started = $true; Outcome = 'success'; Code = 'ready' }
}

if ($MyInvocation.InvocationName -ne '.') {
    $result = Invoke-NebulaLiveLogonCoordinator
    Write-Output ('outcome={0} code={1}' -f $result.Outcome, $result.Code)
    if ($result.Outcome -eq 'failure') { exit 1 }
    exit 0
}
