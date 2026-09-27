[CmdletBinding()]
param(
    [ValidateRange(1, 120)]
    [int]$StartupTimeoutSeconds = 120
)

$script:DotsLiveStartupDeadlineSeconds = 120
$script:DotsLiveProject = 'founder-graph-local'
$script:DotsLiveContainerName = '/founder-graph-local-neo4j-1'
$script:DotsLiveVolumeName = 'founder-graph-local_founder_graph_neo4j_data'
. (Join-Path $PSScriptRoot 'Write-DotsLogonDiagnostic.ps1')

function Get-DotsLiveDockerCliPath {
    $candidate = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return $candidate
    }

    $dockerCommand = Get-Command 'docker.exe' -CommandType Application -ErrorAction SilentlyContinue
    if ($null -ne $dockerCommand) {
        return $dockerCommand.Source
    }

    throw 'Docker Desktop CLI was not found.'
}

function ConvertTo-DotsWindowsCommandLineArgument {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Argument)

    if ($Argument.Length -gt 0 -and $Argument -notmatch '[\s"]') {
        return $Argument
    }

    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashCount = 0
    foreach ($character in $Argument.ToCharArray()) {
        if ($character -eq [char]92) {
            $backslashCount++
            continue
        }

        if ($character -eq [char]34) {
            [void]$builder.Append(('\' * (2 * $backslashCount + 1)))
            [void]$builder.Append('"')
            $backslashCount = 0
            continue
        }

        if ($backslashCount -gt 0) {
            [void]$builder.Append(('\' * $backslashCount))
            $backslashCount = 0
        }
        [void]$builder.Append($character)
    }

    if ($backslashCount -gt 0) {
        [void]$builder.Append(('\' * (2 * $backslashCount)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-DotsLiveDockerCommand {
    param(
        [Parameter(Mandatory = $true)][string]$DockerCliPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][ValidateRange(1, 120000)][int]$TimeoutMilliseconds
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $DockerCliPath
    $startInfo.Arguments = (($Arguments | ForEach-Object { ConvertTo-DotsWindowsCommandLineArgument -Argument $_ }) -join ' ')
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            return [pscustomobject]@{ ExitCode = 127; StdOut = ''; TimedOut = $false }
        }
    }
    catch {
        return [pscustomobject]@{ ExitCode = 127; StdOut = ''; TimedOut = $false }
    }

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($TimeoutMilliseconds)) {
        try { $process.Kill() } catch { }
        $process.Dispose()
        return [pscustomobject]@{ ExitCode = 124; StdOut = ''; TimedOut = $true }
    }

    $process.WaitForExit()
    # stderr is drained to prevent pipe blockage, but is never returned or logged.
    [void]$stderrTask.Result
    $response = [pscustomobject]@{
        ExitCode = $process.ExitCode
        StdOut = $stdoutTask.Result
        TimedOut = $false
    }
    $process.Dispose()
    return $response
}

function Get-DotsLiveRemainingMilliseconds {
    param([Parameter(Mandatory = $true)][System.Diagnostics.Stopwatch]$Stopwatch)

    $remaining = ($script:DotsLiveStartupDeadlineSeconds * 1000) - [int]$Stopwatch.ElapsedMilliseconds
    if ($remaining -le 0) {
        throw 'The 120-second startup deadline was exceeded.'
    }
    return $remaining
}

function Get-DotsLiveDockerOutput {
    param(
        [Parameter(Mandatory = $true)][string]$DockerCliPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][System.Diagnostics.Stopwatch]$Stopwatch,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    $remaining = Get-DotsLiveRemainingMilliseconds -Stopwatch $Stopwatch
    $result = Invoke-DotsLiveDockerCommand `
        -DockerCliPath $DockerCliPath `
        -Arguments $Arguments `
        -TimeoutMilliseconds $remaining

    if ($result.TimedOut) {
        throw 'The 120-second startup deadline was exceeded.'
    }
    if ($result.ExitCode -ne 0) {
        throw $FailureMessage
    }
    return ([string]$result.StdOut).Trim()
}

function Assert-DotsLiveDockerValue {
    param(
        [Parameter(Mandatory = $true)][string]$DockerCliPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][System.Diagnostics.Stopwatch]$Stopwatch,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    $value = Get-DotsLiveDockerOutput `
        -DockerCliPath $DockerCliPath `
        -Arguments $Arguments `
        -Stopwatch $Stopwatch `
        -FailureMessage $FailureMessage
    if ($value -cne $Expected) {
        throw $FailureMessage
    }
}

function Assert-DotsLiveLoopbackBindings {
    param(
        [Parameter(Mandatory = $true)][string]$DockerCliPath,
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][System.Diagnostics.Stopwatch]$Stopwatch
    )

    $rawBindings = Get-DotsLiveDockerOutput `
        -DockerCliPath $DockerCliPath `
        -Arguments @('inspect', '--format', '{{json .HostConfig.PortBindings}}', $ContainerId) `
        -Stopwatch $Stopwatch `
        -FailureMessage 'The Neo4j ports are not bound only to loopback.'
    try {
        $bindings = ConvertFrom-Json -InputObject $rawBindings -ErrorAction Stop
        if ($null -eq $bindings -or @($bindings.PSObject.Properties).Count -ne 2) {
            throw 'Invalid port binding data.'
        }
        foreach ($port in @('7474/tcp', '7687/tcp')) {
            $bindingProperty = $bindings.PSObject.Properties[$port]
            if ($null -eq $bindingProperty -or @($bindingProperty.Value).Count -ne 1) {
                throw 'Invalid port binding data.'
            }
            $binding = @($bindingProperty.Value)[0]
            if ($binding.HostIp -cne '127.0.0.1' -or [string]$binding.HostPort -cne ($port -replace '/tcp$', '')) {
                throw 'Invalid port binding data.'
            }
        }
    }
    catch {
        throw 'The Neo4j ports are not bound only to loopback.'
    }
}

function Invoke-DotsLiveLogonPreflight {
    [CmdletBinding()]
    param(
        [Parameter()][ValidateRange(1, 120)][int]$StartupTimeoutSeconds = 120
    )

    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $script:DotsLiveStartupDeadlineSeconds = $StartupTimeoutSeconds

    try {
        $dockerCli = Get-DotsLiveDockerCliPath

        [void](Get-DotsLiveDockerOutput `
            -DockerCliPath $dockerCli `
            -Arguments @('desktop', 'start') `
            -Stopwatch $timer `
            -FailureMessage 'Docker Desktop could not be started.')

        $engineReady = $false
        while (-not $engineReady) {
            $remaining = Get-DotsLiveRemainingMilliseconds -Stopwatch $timer
            $engine = Invoke-DotsLiveDockerCommand `
                -DockerCliPath $dockerCli `
                -Arguments @('info', '--format', '{{.OperatingSystem}}') `
                -TimeoutMilliseconds $remaining
            if ($engine.TimedOut) {
                throw 'The 120-second startup deadline was exceeded.'
            }
            if ($engine.ExitCode -eq 0 -and ([string]$engine.StdOut).Trim() -eq 'Docker Desktop') {
                $engineReady = $true
            }
            else {
                $remaining = Get-DotsLiveRemainingMilliseconds -Stopwatch $timer
                Start-Sleep -Milliseconds ([Math]::Min(1000, $remaining))
            }
        }

        $containerIdsText = Get-DotsLiveDockerOutput `
            -DockerCliPath $dockerCli `
            -Arguments @(
                'ps', '-aq',
                '--filter', 'label=com.docker.compose.project=founder-graph-local',
                '--filter', 'label=com.docker.compose.service=neo4j'
            ) `
            -Stopwatch $timer `
            -FailureMessage 'The expected live database could not be inspected.'
        $containerIds = @($containerIdsText -split '[\r\n]+' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if ($containerIds.Count -ne 1 -or $containerIds[0] -notmatch '^[A-Fa-f0-9]{12,64}$') {
            throw 'The expected live database container was not found uniquely.'
        }
        $containerId = $containerIds[0]

        Assert-DotsLiveDockerValue $dockerCli @('inspect', '--format', '{{.Name}}', $containerId) $timer $script:DotsLiveContainerName 'The live container identity did not match.'
        Assert-DotsLiveDockerValue $dockerCli @('inspect', '--format', '{{index .Config.Labels "com.docker.compose.project"}}', $containerId) $timer $script:DotsLiveProject 'The live project identity did not match.'
        Assert-DotsLiveDockerValue $dockerCli @('inspect', '--format', '{{index .Config.Labels "com.docker.compose.service"}}', $containerId) $timer 'neo4j' 'The live service identity did not match.'
        Assert-DotsLiveDockerValue $dockerCli @('inspect', '--format', '{{.HostConfig.RestartPolicy.Name}}', $containerId) $timer 'unless-stopped' 'The live restart policy did not match.'
        Assert-DotsLiveDockerValue $dockerCli @('inspect', '--format', '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Type}}|{{.Name}}{{end}}{{end}}', $containerId) $timer "volume|$($script:DotsLiveVolumeName)" 'The live database volume identity did not match.'
        Assert-DotsLiveLoopbackBindings -DockerCliPath $dockerCli -ContainerId $containerId -Stopwatch $timer
        Assert-DotsLiveDockerValue $dockerCli @('volume', 'inspect', '--format', '{{index .Labels "com.openai.founder_graph.role"}}', $script:DotsLiveVolumeName) $timer 'live' 'The expected live volume label did not match.'
        Assert-DotsLiveDockerValue $dockerCli @('volume', 'inspect', '--format', '{{index .Labels "com.openai.founder_graph.database"}}', $script:DotsLiveVolumeName) $timer 'neo4j' 'The expected database volume label did not match.'

        while ($true) {
            $state = Get-DotsLiveDockerOutput $dockerCli @('inspect', '--format', '{{.State.Status}}', $containerId) $timer 'The live container state could not be inspected.'
            if ($state -ne 'running') {
                throw 'The live database is stopped; it was not started by the login task.'
            }

            $health = Get-DotsLiveDockerOutput $dockerCli @('inspect', '--format', '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}', $containerId) $timer 'The live database health could not be inspected.'
            if ($health -eq 'healthy') {
                return [pscustomobject]@{ Ready = $true; Message = 'Normal Founder Graph database is ready.' }
            }
            if ($health -eq 'unhealthy' -or $health -eq 'none') {
                throw 'The live database health check failed.'
            }

            $remaining = Get-DotsLiveRemainingMilliseconds -Stopwatch $timer
            Start-Sleep -Milliseconds ([Math]::Min(1000, $remaining))
        }
    }
    catch {
        $safeFailures = @(
            'Docker Desktop CLI was not found.',
            'Docker Desktop could not be started.',
            'The 120-second startup deadline was exceeded.',
            'The expected live database could not be inspected.',
            'The expected live database container was not found uniquely.',
            'The live container identity did not match.',
            'The live project identity did not match.',
            'The live service identity did not match.',
            'The live restart policy did not match.',
            'The live database volume identity did not match.',
            'The Neo4j ports are not bound only to loopback.',
            'The expected live volume label did not match.',
            'The expected database volume label did not match.',
            'The live container state could not be inspected.',
            'The live database is stopped; it was not started by the login task.',
            'The live database health could not be inspected.',
            'The live database health check failed.'
        )
        $message = if ($safeFailures -contains $_.Exception.Message) { $_.Exception.Message } else { 'Normal Founder Graph startup failed closed.' }
        return [pscustomobject]@{ Ready = $false; Message = $message }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $result = Invoke-DotsLiveLogonPreflight -StartupTimeoutSeconds $StartupTimeoutSeconds
    Write-Output $result.Message
    $outcome = if ($result.Ready) { 'success' } else { 'failure' }
    $code = if ($result.Ready) { 'ready' } else { 'database_preflight_failed' }
    [void](Write-DotsLogonDiagnostic -Service 'live-database' -Outcome $outcome -Code $code)
    if (-not $result.Ready) {
        exit 1
    }
    exit 0
}
