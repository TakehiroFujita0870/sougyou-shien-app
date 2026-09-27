[CmdletBinding()]
param(
    [string]$DatabaseStartupScript,
    [string]$TunnelStartupScript
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($DatabaseStartupScript)) {
    $DatabaseStartupScript = Join-Path $PSScriptRoot 'Start-DotsLiveAtLogon.ps1'
}
if ([string]::IsNullOrWhiteSpace($TunnelStartupScript)) {
    $TunnelStartupScript = Join-Path $PSScriptRoot 'Start-DotsLiveMcpAtLogon.ps1'
}
. (Join-Path $PSScriptRoot 'Write-DotsLogonDiagnostic.ps1')

function Write-DotsLiveCoordinatorStatus {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('live-database', 'live-mcp-tunnel')][string]$Service,
        [Parameter(Mandatory = $true)][ValidateSet('success', 'failure', 'unavailable')][string]$Outcome,
        [Parameter(Mandatory = $true)][ValidateSet('ready', 'database_preflight_failed', 'database_not_ready', 'mcp_tunnel_startup_failed', 'wsl_unavailable', 'explicit_stop')][string]$Code
    )
    [void](Write-DotsLogonDiagnostic -Service $Service -Outcome $Outcome -Code $Code)
}

function Get-DotsLiveStopIntentPath {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'The current-user local application data directory is unavailable.' }
    return Join-Path $env:LOCALAPPDATA 'Dots\startup\live-stop-intent\stopped'
}

function Get-DotsLiveStopIntentAcl {
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

function Initialize-DotsLiveStopIntentDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) { [void](New-Item -ItemType Directory -Path $directory -Force -ErrorAction Stop) }
    Set-Acl -LiteralPath $directory -AclObject (Get-DotsLiveStopIntentAcl) -ErrorAction Stop
    $acl = Get-Acl -LiteralPath $directory -ErrorAction Stop
    if (-not (Test-DotsLiveStopIntentAcl -Acl $acl)) { throw 'The stop-intent directory permissions could not be verified.' }
}

function Test-DotsLiveStopIntentAcl {
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

function Test-DotsLiveStopIntent {
    [CmdletBinding()]
    param([string]$Path = (Get-DotsLiveStopIntentPath))
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $directoryAcl = Get-Acl -LiteralPath (Split-Path -Parent $Path) -ErrorAction Stop
    if (-not (Test-DotsLiveStopIntentAcl -Acl $directoryAcl)) { throw 'The stop-intent marker permissions could not be verified.' }
    return $true
}

function Set-DotsLiveStopIntent {
    [CmdletBinding()]
    param([string]$Path = (Get-DotsLiveStopIntentPath))
    Initialize-DotsLiveStopIntentDirectory -Path $Path
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
    return (Test-DotsLiveStopIntent -Path $Path)
}

function Clear-DotsLiveStopIntent {
    [CmdletBinding()]
    param([string]$Path = (Get-DotsLiveStopIntentPath))
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $true }
    if (-not (Test-DotsLiveStopIntent -Path $Path)) { return $false }
    Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
    return (-not (Test-Path -LiteralPath $Path))
}

function Invoke-DotsLiveHiddenStartupScript {
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

function Start-DotsLiveDashboardController {
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
            $startInfo.Arguments = '--distribution Ubuntu --exec systemctl --user start dots-local-dashboard.service'
        } else {
            $startInfo.Arguments = '--distribution Ubuntu --exec systemctl --user is-active --quiet dots-local-dashboard.service'
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

function Start-DotsLiveApiService {
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
            $startInfo.Arguments = '--distribution Ubuntu --exec systemctl --user start dots-live-api.service'
        } else {
            $startInfo.Arguments = '--distribution Ubuntu --exec systemctl --user is-active --quiet dots-live-api.service'
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
                if ($health.status -ceq 'ok' -and $health.service -ceq 'dots-api') { return $true }
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

function Get-DotsLiveTunnelDiagnosticSnapshot {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { return [pscustomobject]@{ Path = $null; Text = ''; LastWriteUtcTicks = 0L } }
    $path = Join-Path $env:LOCALAPPDATA 'Dots\startup\live-mcp-tunnel-latest.log'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return [pscustomobject]@{ Path = $path; Text = ''; LastWriteUtcTicks = 0L } }
    $item = Get-Item -LiteralPath $path -ErrorAction Stop
    return [pscustomobject]@{ Path = $path; Text = [System.IO.File]::ReadAllText($path); LastWriteUtcTicks = $item.LastWriteTimeUtc.Ticks }
}

function Wait-DotsLiveTunnelReadiness {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][psobject]$BeforeStart,
        [ValidateRange(1, 120000)][int]$TimeoutMilliseconds = 120000
    )
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.ElapsedMilliseconds -lt $TimeoutMilliseconds) {
        if (Test-DotsLiveStopIntent) { return $false }
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

function Invoke-DotsLiveLogonCoordinator {
    [CmdletBinding()]
    param([string]$DatabaseScript = $DatabaseStartupScript, [string]$TunnelScript = $TunnelStartupScript)
    if (-not (Start-DotsLiveDashboardController)) {
        Write-DotsLiveCoordinatorStatus -Service 'live-database' -Outcome 'unavailable' -Code 'wsl_unavailable'
        Write-DotsLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'wsl_unavailable'
        return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'local_dashboard_unavailable' }
    }
    if (Test-DotsLiveStopIntent) {
        Write-DotsLiveCoordinatorStatus -Service 'live-database' -Outcome 'unavailable' -Code 'explicit_stop'
        Write-DotsLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'explicit_stop'
        return [pscustomobject]@{ Started = $false; Outcome = 'stopped'; Code = 'explicit_stop' }
    }
    $deadline = [System.Diagnostics.Stopwatch]::StartNew()
    $database = $null
    while ($deadline.ElapsedMilliseconds -lt 120000) {
        if (Test-DotsLiveStopIntent) {
            Write-DotsLiveCoordinatorStatus -Service 'live-database' -Outcome 'unavailable' -Code 'explicit_stop'
            Write-DotsLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'explicit_stop'
            return [pscustomobject]@{ Started = $false; Outcome = 'stopped'; Code = 'explicit_stop' }
        }
        $remaining = [Math]::Max(1, 120000 - [int]$deadline.ElapsedMilliseconds)
        $remainingSeconds = [int][Math]::Floor($remaining / 1000)
        if ($remainingSeconds -lt 1) { break }
        $database = Invoke-DotsLiveHiddenStartupScript -ScriptPath $DatabaseScript -WaitForExit -StartupTimeoutSeconds $remainingSeconds -TimeoutMilliseconds $remaining
        if (-not $database.Started -or $database.TimedOut) {
            Write-DotsLiveCoordinatorStatus -Service 'live-database' -Outcome 'failure' -Code 'database_preflight_failed'
            Write-DotsLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'database_not_ready'
            return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'database_not_ready' }
        }
        if (-not $database.TimedOut -and $database.ExitCode -eq 0) { break }
        $remaining = 120000 - [int]$deadline.ElapsedMilliseconds
        if ($remaining -le 0) { break }
        Start-Sleep -Milliseconds ([Math]::Min(1000, $remaining))
    }
    if ($null -eq $database -or $database.TimedOut -or $database.ExitCode -ne 0) {
        Write-DotsLiveCoordinatorStatus -Service 'live-database' -Outcome 'failure' -Code 'database_preflight_failed'
        Write-DotsLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'database_not_ready'
        return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'database_not_ready' }
    }
    # A stop request can arrive while the read-only database preflight is waiting.
    if (Test-DotsLiveStopIntent) {
        Write-DotsLiveCoordinatorStatus -Service 'live-database' -Outcome 'unavailable' -Code 'explicit_stop'
        Write-DotsLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'explicit_stop'
        return [pscustomobject]@{ Started = $false; Outcome = 'stopped'; Code = 'explicit_stop' }
    }
    $remaining = 120000 - [int]$deadline.ElapsedMilliseconds
    if ($remaining -le 0 -or -not (Start-DotsLiveApiService -TimeoutMilliseconds ([Math]::Max(1, $remaining)))) {
        Write-DotsLiveCoordinatorStatus -Service 'live-database' -Outcome 'failure' -Code 'database_not_ready'
        Write-DotsLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'database_not_ready'
        return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'api_not_ready' }
    }
    # Do not expose ChatGPT access if a stop request arrived while the API became ready.
    if (Test-DotsLiveStopIntent) {
        Write-DotsLiveCoordinatorStatus -Service 'live-database' -Outcome 'unavailable' -Code 'explicit_stop'
        Write-DotsLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'explicit_stop'
        return [pscustomobject]@{ Started = $false; Outcome = 'stopped'; Code = 'explicit_stop' }
    }
    $beforeTunnel = Get-DotsLiveTunnelDiagnosticSnapshot
    $remaining = 120000 - [int]$deadline.ElapsedMilliseconds
    $remainingSeconds = [int][Math]::Floor($remaining / 1000)
    if ($remainingSeconds -lt 1) {
        Write-DotsLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'unavailable' -Code 'database_not_ready'
        return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'startup_deadline_exceeded' }
    }
    $tunnel = Invoke-DotsLiveHiddenStartupScript -ScriptPath $TunnelScript -WaitForExit:$false -StartupTimeoutSeconds $remainingSeconds
    if (-not $tunnel.Started) {
        Write-DotsLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'failure' -Code 'mcp_tunnel_startup_failed'
        return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'tunnel_not_started' }
    }
    $remaining = 120000 - [int]$deadline.ElapsedMilliseconds
    if ($remaining -le 0) {
        Write-DotsLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'failure' -Code 'mcp_tunnel_startup_failed'
        return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'startup_deadline_exceeded' }
    }
    $tunnelReady = Wait-DotsLiveTunnelReadiness -ProcessId $tunnel.ProcessId -BeforeStart $beforeTunnel -TimeoutMilliseconds $remaining
    if (-not $tunnelReady) {
        Write-DotsLiveCoordinatorStatus -Service 'live-mcp-tunnel' -Outcome 'failure' -Code 'mcp_tunnel_startup_failed'
        return [pscustomobject]@{ Started = $false; Outcome = 'failure'; Code = 'tunnel_not_ready' }
    }
    return [pscustomobject]@{ Started = $true; Outcome = 'success'; Code = 'ready' }
}

if ($MyInvocation.InvocationName -ne '.') {
    $result = Invoke-DotsLiveLogonCoordinator
    Write-Output ('outcome={0} code={1}' -f $result.Outcome, $result.Code)
    if ($result.Outcome -eq 'failure') { exit 1 }
    exit 0
}
