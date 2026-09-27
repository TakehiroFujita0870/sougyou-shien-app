$script:LiveStartupScriptPath = Join-Path $PSScriptRoot '..\Start-DotsLiveAtLogon.ps1'
. $script:LiveStartupScriptPath

function Set-FakeLiveDockerResponse {
    param(
        [string]$Template,
        [string]$Value,
        [int]$ExitCode = 0,
        [bool]$TimedOut = $false
    )
    $script:FakeLiveDockerResponses[$Template] = [pscustomobject]@{
        ExitCode = $ExitCode
        StdOut = $Value
        TimedOut = $TimedOut
    }
}

function Set-HealthyLiveDockerFixture {
    Set-FakeLiveDockerResponse -Template 'desktop start' -Value ''
    Set-FakeLiveDockerResponse -Template 'info --format {{.OperatingSystem}}' -Value 'Docker Desktop'
    Set-FakeLiveDockerResponse -Template 'ps -aq --filter label=com.docker.compose.project=founder-graph-local --filter label=com.docker.compose.service=neo4j' -Value '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
    $id = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
    Set-FakeLiveDockerResponse -Template "inspect --format {{.Name}} $id" -Value '/founder-graph-local-neo4j-1'
    Set-FakeLiveDockerResponse -Template "inspect --format {{index .Config.Labels `"com.docker.compose.project`"}} $id" -Value 'founder-graph-local'
    Set-FakeLiveDockerResponse -Template "inspect --format {{index .Config.Labels `"com.docker.compose.service`"}} $id" -Value 'neo4j'
    Set-FakeLiveDockerResponse -Template "inspect --format {{.HostConfig.RestartPolicy.Name}} $id" -Value 'unless-stopped'
    Set-FakeLiveDockerResponse -Template "inspect --format {{range .Mounts}}{{if eq .Destination `"/data`"}}{{.Type}}|{{.Name}}{{end}}{{end}} $id" -Value 'volume|founder-graph-local_founder_graph_neo4j_data'
    Set-FakeLiveDockerResponse -Template "inspect --format {{json .HostConfig.PortBindings}} $id" -Value '{"7474/tcp":[{"HostIp":"127.0.0.1","HostPort":"7474"}],"7687/tcp":[{"HostIp":"127.0.0.1","HostPort":"7687"}]}'
    Set-FakeLiveDockerResponse -Template 'volume inspect --format {{index .Labels "com.openai.founder_graph.role"}} founder-graph-local_founder_graph_neo4j_data' -Value 'live'
    Set-FakeLiveDockerResponse -Template 'volume inspect --format {{index .Labels "com.openai.founder_graph.database"}} founder-graph-local_founder_graph_neo4j_data' -Value 'neo4j'
    Set-FakeLiveDockerResponse -Template "inspect --format {{.State.Status}} $id" -Value 'running'
    Set-FakeLiveDockerResponse -Template "inspect --format {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} $id" -Value 'healthy'
}

Describe 'Windows login preflight script contract' {
    It 'accepts the shared startup deadline from the coordinator' {
        $command = Get-Command -Name $script:LiveStartupScriptPath -CommandType ExternalScript
        $command.Parameters.ContainsKey('StartupTimeoutSeconds') | Should Be $true
    }
}

Describe 'Invoke-DotsLiveLogonPreflight' {
    BeforeEach {
        $script:FakeLiveDockerResponses = @{}
        $script:FakeLiveDockerCalls = @()
        $script:FakeLiveDockerTimeouts = @()
        $script:FakeLiveDockerDelays = @{}
        Set-HealthyLiveDockerFixture
        Mock Get-DotsLiveDockerCliPath { 'C:\DockerDesktop\docker.exe' }
        Mock Start-Sleep {}
        Mock Invoke-DotsLiveDockerCommand {
            $joinedArguments = $Arguments -join ' '
            $script:FakeLiveDockerCalls += ,$joinedArguments
            $script:FakeLiveDockerTimeouts += $TimeoutMilliseconds
            if ($script:FakeLiveDockerDelays.ContainsKey($joinedArguments)) {
                [System.Threading.Thread]::Sleep($script:FakeLiveDockerDelays[$joinedArguments])
            }
            if (-not $script:FakeLiveDockerResponses.ContainsKey($joinedArguments)) {
                return [pscustomobject]@{ ExitCode = 1; StdOut = ''; TimedOut = $false }
            }
            return $script:FakeLiveDockerResponses[$joinedArguments]
        }
    }

    AfterEach {
        $mutatingDockerCalls = @($script:FakeLiveDockerCalls | Where-Object {
            $_ -match '^(start|create|run|restart|container\s+(start|create|restart))\b' -or
            $_ -match '^compose\b.*\b(up|create)\b'
        })
        $mutatingDockerCalls.Count | Should Be 0
    }

    It 'reports ready only for the exact existing healthy live container' {
        $result = Invoke-DotsLiveLogonPreflight -StartupTimeoutSeconds 5

        $result.Ready | Should Be $true
        $result.Message | Should Match 'ready'
        @($script:FakeLiveDockerCalls | Where-Object { $_ -match '^(start|container\s+start)\b' -or $_ -match '^compose\b.*\bup\b' }).Count | Should Be 0
    }

    It 'does not start or create an explicitly stopped database' {
        Set-FakeLiveDockerResponse -Template 'inspect --format {{.State.Status}} 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef' -Value 'exited'

        $result = Invoke-DotsLiveLogonPreflight -StartupTimeoutSeconds 5

        $result.Ready | Should Be $false
        $result.Message | Should Match 'stopped'
        @($script:FakeLiveDockerCalls | Where-Object { $_ -match '^(start|container\s+start)\b' -or $_ -match '^compose\b.*\bup\b' }).Count | Should Be 0
        @($script:FakeLiveDockerCalls | Where-Object { $_ -eq 'desktop start' }).Count | Should Be 1
    }

    It 'fails closed when the expected project container is absent' {
        Set-FakeLiveDockerResponse -Template 'ps -aq --filter label=com.docker.compose.project=founder-graph-local --filter label=com.docker.compose.service=neo4j' -Value ''

        $result = Invoke-DotsLiveLogonPreflight -StartupTimeoutSeconds 5

        $result.Ready | Should Be $false
        $result.Message | Should Match 'not found'
    }

    It 'fails closed when the mounted live volume identity differs' {
        Set-FakeLiveDockerResponse -Template 'inspect --format {{range .Mounts}}{{if eq .Destination "/data"}}{{.Type}}|{{.Name}}{{end}}{{end}} 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef' -Value 'volume|other-project_data'

        $result = Invoke-DotsLiveLogonPreflight -StartupTimeoutSeconds 5

        $result.Ready | Should Be $false
        $result.Message | Should Match 'volume'
    }

    It 'fails closed when a service port is not loopback-bound' {
        Set-FakeLiveDockerResponse -Template 'inspect --format {{json .HostConfig.PortBindings}} 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef' -Value '{"7474/tcp":[{"HostIp":"0.0.0.0","HostPort":"7474"}],"7687/tcp":[{"HostIp":"127.0.0.1","HostPort":"7687"}]}'

        $result = Invoke-DotsLiveLogonPreflight -StartupTimeoutSeconds 5

        $result.Ready | Should Be $false
        $result.Message | Should Match 'loopback'
    }

    It 'fails closed when Docker reports unhealthy' {
        Set-FakeLiveDockerResponse -Template 'inspect --format {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef' -Value 'unhealthy'

        $result = Invoke-DotsLiveLogonPreflight -StartupTimeoutSeconds 5

        $result.Ready | Should Be $false
        $result.Message | Should Match 'health check failed'
    }

    It 'enforces the overall startup deadline when a bounded command times out' {
        Set-FakeLiveDockerResponse -Template 'desktop start' -Value '' -TimedOut $true

        $result = Invoke-DotsLiveLogonPreflight -StartupTimeoutSeconds 1

        $result.Ready | Should Be $false
        $result.Message | Should Match '120-second'
    }

    It 'fails closed when Docker Desktop does not start' {
        Set-FakeLiveDockerResponse -Template 'desktop start' -Value '' -ExitCode 1

        $result = Invoke-DotsLiveLogonPreflight -StartupTimeoutSeconds 5

        $result.Ready | Should Be $false
        $result.Message | Should Match 'Docker Desktop could not be started'
        @($script:FakeLiveDockerCalls).Count | Should Be 1
    }

    It 'passes the remaining deadline to each Docker check after earlier calls consume time' {
        $script:FakeLiveDockerDelays['desktop start'] = 150
        $script:FakeLiveDockerDelays['info --format {{.OperatingSystem}}'] = 150

        $result = Invoke-DotsLiveLogonPreflight -StartupTimeoutSeconds 3

        $result.Ready | Should Be $true
        @($script:FakeLiveDockerTimeouts).Count | Should BeGreaterThan 2
        $script:FakeLiveDockerTimeouts[1] | Should BeLessThan $script:FakeLiveDockerTimeouts[0]
        $script:FakeLiveDockerTimeouts[2] | Should BeLessThan $script:FakeLiveDockerTimeouts[1]
        @($script:FakeLiveDockerTimeouts | Where-Object { $_ -gt 3000 -or $_ -le 0 }).Count | Should Be 0
    }

    It 'does not issue later Docker checks after a delayed call consumes the deadline' {
        $script:FakeLiveDockerDelays['desktop start'] = 1100

        $result = Invoke-DotsLiveLogonPreflight -StartupTimeoutSeconds 1

        $result.Ready | Should Be $false
        $result.Message | Should Match '120-second'
        @($script:FakeLiveDockerCalls).Count | Should Be 1
        $script:FakeLiveDockerTimeouts[0] | Should BeLessThan 1000
    }

    It 'fails closed when Docker Engine itself reports a timeout' {
        Set-FakeLiveDockerResponse -Template 'info --format {{.OperatingSystem}}' -Value '' -TimedOut $true

        $result = Invoke-DotsLiveLogonPreflight -StartupTimeoutSeconds 5

        $result.Ready | Should Be $false
        $result.Message | Should Match '120-second'
        @($script:FakeLiveDockerCalls | Where-Object { $_ -match '^ps\b' }).Count | Should Be 0
    }
}
