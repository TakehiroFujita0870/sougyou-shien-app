[CmdletBinding()]
param(
    [string]$ExpectedProject,
    [string]$ExpectedContainerId,
    [string]$ExpectedVolumeName,
    [string]$AuthFilePath,
    [string]$BackupDirectory,
    [switch]$BackupForExpectedVolume,
    [switch]$UseProtectedAuthFileAndGenerate,
    [switch]$ResolvePending
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:NebulaRotationProject = 'founder-graph-local'
$script:NebulaRotationContainerName = '/founder-graph-local-neo4j-1'
$script:NebulaRotationVolumeName = 'founder-graph-local_founder_graph_neo4j_data'
$script:NebulaRotationImage = 'neo4j:5.26-community'
$script:NebulaRotationPendingSuffix = '.rotation-pending'
$script:NebulaRotationRepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$script:NebulaRotationSecretHelper = Join-Path $PSScriptRoot 'Protect-NebulaSecretFile.ps1'

if (-not (Test-Path -LiteralPath $script:NebulaRotationSecretHelper -PathType Leaf)) {
    throw 'The secret-file protection helper is missing.'
}
. $script:NebulaRotationSecretHelper

function ConvertTo-NebulaRotationWindowsArgument {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Argument)

    if ($Argument.Length -gt 0 -and $Argument -notmatch '[\s"]') { return $Argument }
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashCount = 0
    foreach ($character in $Argument.ToCharArray()) {
        if ($character -eq [char]92) { $backslashCount++; continue }
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
    if ($backslashCount -gt 0) { [void]$builder.Append(('\' * (2 * $backslashCount))) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Get-NebulaRotationDockerCliPath {
    $candidate = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    $command = Get-Command 'docker.exe' -CommandType Application -ErrorAction SilentlyContinue
    if ($null -ne $command) { return $command.Source }
    throw 'Docker Desktop CLI was not found.'
}

function Invoke-NebulaRotationDocker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DockerCliPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [hashtable]$ChildEnvironment = @{},
        [scriptblock]$InputWriter,
        [switch]$CaptureStdOut,
        [ValidateRange(1, 120)][int]$TimeoutSeconds = 30
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $DockerCliPath
    $startInfo.Arguments = (($Arguments | ForEach-Object { ConvertTo-NebulaRotationWindowsArgument -Argument $_ }) -join ' ')
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.RedirectStandardInput = ($null -ne $InputWriter)
    foreach ($name in $ChildEnvironment.Keys) {
        $startInfo.EnvironmentVariables[[string]$name] = [string]$ChildEnvironment[$name]
    }

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { return [pscustomobject]@{ ExitCode = 127; StdOut = ''; TimedOut = $false } }
    }
    catch {
        return [pscustomobject]@{ ExitCode = 127; StdOut = ''; TimedOut = $false }
    }

    # The environment is inherited by the child process; discard our mutable copy immediately.
    foreach ($name in @($startInfo.EnvironmentVariables.Keys)) {
        if ($ChildEnvironment.ContainsKey([string]$name)) { $startInfo.EnvironmentVariables.Remove([string]$name) }
    }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    try {
        if ($null -ne $InputWriter) {
            & $InputWriter $process.StandardInput
            $process.StandardInput.Flush()
            $process.StandardInput.Close()
        }
    }
    catch {
        try { $process.Kill() } catch { }
        $process.Dispose()
        return [pscustomobject]@{ ExitCode = 125; StdOut = ''; TimedOut = $false }
    }

    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        try { $process.Kill() } catch { }
        $process.Dispose()
        return [pscustomobject]@{ ExitCode = 124; StdOut = ''; TimedOut = $true }
    }
    $process.WaitForExit()
    [void]$stderrTask.Result
    $safeStdout = if ($CaptureStdOut) { [string]$stdoutTask.Result } else { '' }
    $result = [pscustomobject]@{ ExitCode = $process.ExitCode; StdOut = $safeStdout; TimedOut = $false }
    $process.Dispose()
    return $result
}

function ConvertTo-NebulaRotationPlainText {
    param([Parameter(Mandatory = $true)][System.Security.SecureString]$Secret)
    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($Secret)
        $builder = New-Object System.Text.StringBuilder
        for ($index = 0; $index -lt $Secret.Length; $index++) {
            [void]$builder.Append([char][Runtime.InteropServices.Marshal]::ReadInt16($pointer, $index * 2))
        }
        return $builder.ToString()
    }
    finally {
        if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($pointer) }
    }
}

function ConvertTo-NebulaRotationCypherEscapes {
    param([Parameter(Mandatory = $true)][System.Security.SecureString]$Secret)
    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($Secret)
        $builder = New-Object System.Text.StringBuilder
        for ($index = 0; $index -lt $Secret.Length; $index++) {
            $code = [Runtime.InteropServices.Marshal]::ReadInt16($pointer, $index * 2)
            if ($code -lt 32 -or $code -gt 126) { throw 'Credentials must use printable ASCII without line breaks.' }
            [void]$builder.AppendFormat('\u{0:x4}', $code)
        }
        return $builder.ToString()
    }
    finally {
        if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($pointer) }
    }
}

function ConvertTo-NebulaRotationSecureString {
    param([Parameter(Mandatory = $true)][string]$Value)
    $secure = New-Object System.Security.SecureString
    foreach ($character in $Value.ToCharArray()) { $secure.AppendChar($character) }
    $secure.MakeReadOnly()
    return $secure
}

function Test-NebulaRotationCredential {
    param([Parameter(Mandatory = $true)][System.Security.SecureString]$Secret)
    if ($Secret.Length -lt 8 -or $Secret.Length -gt 256) { return $false }
    try { [void](ConvertTo-NebulaRotationCypherEscapes -Secret $Secret); return $true }
    catch { return $false }
}

function Get-NebulaRotationProtectedCurrentPassword {
    param([Parameter(Mandatory = $true)][string]$AuthPath)
    if (-not (Test-NebulaRotationRegularFile -Path $AuthPath) -or -not (Test-NebulaRotationCurrentUserAcl -Path $AuthPath)) {
        throw 'The protected auth file cannot be used to read the current credential.'
    }
    $record = [System.IO.File]::ReadAllText($AuthPath, [System.Text.Encoding]::UTF8)
    if (-not $record.StartsWith('neo4j/', [System.StringComparison]::Ordinal) -or $record.Length -le 6) {
        throw 'The protected auth file format is invalid.'
    }
    $secret = ConvertTo-NebulaRotationSecureString -Value $record.Substring(6)
    if (-not (Test-NebulaRotationCredential -Secret $secret)) {
        $secret.Dispose()
        throw 'The protected auth file credential failed validation.'
    }
    return $secret
}

function New-NebulaRotationGeneratedPassword {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) }
    finally { $generator.Dispose() }
    $value = ([System.BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
    [Array]::Clear($bytes, 0, $bytes.Length)
    return (ConvertTo-NebulaRotationSecureString -Value $value)
}

function Get-NebulaRotationAclSid {
    return [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
}

function Test-NebulaRotationCurrentUserAcl {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        $sid = Get-NebulaRotationAclSid
        if (-not $acl.AreAccessRulesProtected) { return $false }
        $rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
        $allowed = @($sid, 'S-1-5-18', 'S-1-5-32-544')
        if ($rules.Count -lt 1 -or $rules.Count -gt 3) { return $false }
        $seen = @{}
        foreach ($rule in $rules) {
            $ruleSid = $rule.IdentityReference.Value
            if ($allowed -notcontains $ruleSid -or $seen.ContainsKey($ruleSid) -or
                $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
                $rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl -or
                $rule.IsInherited -or
                ($rule.InheritanceFlags -ne [System.Security.AccessControl.InheritanceFlags]::None -and
                 (-not $item.PSIsContainer -or $rule.InheritanceFlags -ne ([System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit))) -or
                $rule.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None) {
                return $false
            }
            $seen[$ruleSid] = $true
        }
        return $seen.ContainsKey($sid)
    }
    catch { return $false }
}

function Test-NebulaRotationRegularFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        return (-not $item.PSIsContainer -and (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0))
    }
    catch { return $false }
}

function Assert-NebulaRotationOfflineBackup {
    param([string]$Path, [string]$VolumeName, [switch]$BackupForExpectedVolume)
    if (-not $BackupForExpectedVolume -or $VolumeName -cne $script:NebulaRotationVolumeName) {
        throw 'A backup for the exact live volume must be confirmed before rotation.'
    }
    if ([string]::IsNullOrWhiteSpace($Path) -or -not [System.IO.Path]::IsPathRooted($Path)) {
        throw 'An absolute offline backup directory is required.'
    }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath.StartsWith($script:NebulaRotationRepositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'The offline backup must be outside the repository.'
    }
    $directory = Get-Item -LiteralPath $fullPath -Force -ErrorAction SilentlyContinue
    if ($null -eq $directory -or -not $directory.PSIsContainer -or (($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw 'The offline backup directory is unavailable or unsafe.'
    }
    if (-not (Test-NebulaRotationCurrentUserAcl -Path $fullPath)) { throw 'The offline backup directory is not current-user-only.' }
    foreach ($name in @('neo4j.dump', 'system.dump')) {
        $dumpPath = Join-Path $fullPath $name
        if (-not (Test-NebulaRotationRegularFile -Path $dumpPath)) { throw 'Both offline Neo4j dump files are required.' }
        $dump = Get-Item -LiteralPath $dumpPath -Force
        if ($dump.Length -le 0 -or -not (Test-NebulaRotationCurrentUserAcl -Path $dumpPath)) {
            throw 'Both offline Neo4j dump files must be non-empty and current-user-only.'
        }
    }
}

function Get-NebulaRotationMetadata {
    param([Parameter(Mandatory = $true)][string]$DockerCliPath, [Parameter(Mandatory = $true)][string[]]$Arguments)
    $result = Invoke-NebulaRotationDocker -DockerCliPath $DockerCliPath -Arguments $Arguments -CaptureStdOut -TimeoutSeconds 15
    if ($result.TimedOut -or $result.ExitCode -ne 0) { throw 'The expected live database metadata could not be verified.' }
    return ([string]$result.StdOut).Trim()
}

function Assert-NebulaRotationMountPolicy {
    param(
        [Parameter(Mandatory = $true)][object]$Container,
        [Parameter(Mandatory = $true)][string]$VolumeName,
        [Parameter(Mandatory = $true)][string]$AuthPath
    )

    $mounts = @($Container.Mounts)
    if ($mounts.Count -ne 2) { throw 'The live container has unexpected mounts.' }

    $dataMounts = @($mounts | Where-Object { $_.Destination -ceq '/data' })
    $secretMounts = @($mounts | Where-Object { $_.Destination -ceq '/run/secrets/founder_graph_auth' })
    if ($dataMounts.Count -ne 1 -or $dataMounts[0].Type -cne 'volume' -or
        $dataMounts[0].Name -cne $VolumeName -or $dataMounts[0].RW -ne $true) {
        throw 'The live data volume identity did not match.'
    }
    if ($secretMounts.Count -ne 1 -or $secretMounts[0].Type -cne 'bind' -or $secretMounts[0].RW -ne $false) {
        throw 'The mounted auth file must be the expected read-only bind.'
    }

    $canonicalAuth = [System.IO.Path]::GetFullPath($AuthPath)
    $canonicalSource = [System.IO.Path]::GetFullPath([string]$secretMounts[0].Source)
    if (-not $canonicalAuth.Equals($canonicalSource, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'The mounted auth-file path did not match.'
    }

    $tmpfsProperties = @()
    if ($null -ne $Container.HostConfig -and $null -ne $Container.HostConfig.Tmpfs) {
        $tmpfsProperties = @($Container.HostConfig.Tmpfs.PSObject.Properties)
    }
    if ($tmpfsProperties.Count -ne 1 -or
        $tmpfsProperties[0].Name -cne '/logs' -or
        [string]$tmpfsProperties[0].Value -cne '') {
        throw 'The live /logs mount must be the exact tmpfs configuration.'
    }
}

function Assert-NebulaRotationLiveIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$DockerCliPath,
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][string]$Project,
        [Parameter(Mandatory = $true)][string]$VolumeName,
        [Parameter(Mandatory = $true)][string]$AuthPath,
        [switch]$AllowUnhealthy
    )

    if ($Project -cne $script:NebulaRotationProject -or $VolumeName -cne $script:NebulaRotationVolumeName -or $ContainerId -notmatch '^[A-Fa-f0-9]{64}$') {
        throw 'The supplied live identity does not match the required Founder Graph target.'
    }
    $ids = Get-NebulaRotationMetadata $DockerCliPath @('ps', '--no-trunc', '-aq', '--filter', "label=com.docker.compose.project=$Project", '--filter', 'label=com.docker.compose.service=neo4j')
    $matches = @($ids -split '[\r\n]+' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($matches.Count -ne 1 -or $matches[0] -cne $ContainerId) { throw 'The live container ID is not the unique expected container.' }

    $raw = Get-NebulaRotationMetadata $DockerCliPath @('inspect', '--type=container', '--format', '{{json .}}', $ContainerId)
    try { $container = ConvertFrom-Json -InputObject $raw -ErrorAction Stop } catch { throw 'The live container identity could not be decoded.' }
    $labels = $container.Config.Labels
    if ($container.Name -cne $script:NebulaRotationContainerName -or
        $container.Config.Image -cne $script:NebulaRotationImage -or
        $labels.'com.docker.compose.project' -cne $Project -or
        $labels.'com.docker.compose.service' -cne 'neo4j' -or
        $container.State.Status -cne 'running') {
        throw 'The live container identity or state did not match.'
    }
    if (-not $AllowUnhealthy -and $container.State.Health.Status -cne 'healthy') { throw 'The live database is not healthy.' }
    if ($AllowUnhealthy -and $container.State.Health.Status -notin @('healthy', 'unhealthy', 'starting')) { throw 'The live database state is unresolved.' }

    $canonicalAuth = [System.IO.Path]::GetFullPath($AuthPath)
    Assert-NebulaRotationMountPolicy -Container $container -VolumeName $VolumeName -AuthPath $canonicalAuth
    if (-not (Test-NebulaRotationRegularFile -Path $canonicalAuth)) { throw 'The mounted auth file is unavailable or unsafe.' }

    $expectedPorts = @{ '7474/tcp' = '7474'; '7687/tcp' = '7687' }
    $portBindings = $container.HostConfig.PortBindings
    if (@($portBindings.PSObject.Properties).Count -ne 2) { throw 'The live database ports are not loopback-only.' }
    foreach ($port in $expectedPorts.Keys) {
        $property = $portBindings.PSObject.Properties[$port]
        if ($null -eq $property -or @($property.Value).Count -ne 1) { throw 'The live database ports are not loopback-only.' }
        $binding = @($property.Value)[0]
        if ($binding.HostIp -cne '127.0.0.1' -or [string]$binding.HostPort -cne $expectedPorts[$port]) { throw 'The live database ports are not loopback-only.' }
    }

    $volumeRaw = Get-NebulaRotationMetadata $DockerCliPath @('volume', 'inspect', '--format', '{{json .}}', $VolumeName)
    try { $volume = ConvertFrom-Json -InputObject $volumeRaw -ErrorAction Stop } catch { throw 'The live volume metadata could not be decoded.' }
    if ($volume.Name -cne $VolumeName -or
        $volume.Labels.'com.openai.founder_graph.role' -cne 'live' -or
        $volume.Labels.'com.openai.founder_graph.database' -cne 'neo4j' -or
        $volume.Labels.'com.docker.compose.project' -cne $Project -or
        $volume.Labels.'com.docker.compose.volume' -cne 'founder_graph_neo4j_data') {
        throw 'The live volume labels did not match.'
    }
    return $container
}

function New-NebulaRotationInputWriter {
    param([System.Security.SecureString]$Password, [System.Security.SecureString]$OldPassword, [System.Security.SecureString]$NewPassword, [ValidateSet('probe', 'alter')][string]$Kind)
    if ($Kind -eq 'probe') {
        return { param($Writer) $Writer.WriteLine('RETURN 1;') }.GetNewClosure()
    }
    $oldParameter = ':param oldPassword => ''' + (ConvertTo-NebulaRotationCypherEscapes -Secret $OldPassword) + ''''
    $newParameter = ':param newPassword => ''' + (ConvertTo-NebulaRotationCypherEscapes -Secret $NewPassword) + ''''
    return {
        param($Writer)
        $Writer.WriteLine($oldParameter)
        $Writer.WriteLine($newParameter)
        $Writer.WriteLine('ALTER CURRENT USER SET PASSWORD FROM $oldPassword TO $newPassword;')
    }.GetNewClosure()
}

function New-NebulaRotationLogSettingsInputWriter {
    return {
        param($Writer)
        $Writer.WriteLine("SHOW SETTINGS YIELD name, value WHERE name IN ['db.logs.query.parameter_logging_enabled', 'db.logs.query.early_raw_logging_enabled'] RETURN name + '=' + toString(value) AS setting ORDER BY setting;")
    }.GetNewClosure()
}

function New-NebulaRotationEnvironment {
    param([System.Security.SecureString]$Password)
    $plain = ConvertTo-NebulaRotationPlainText -Secret $Password
    return @{ NEO4J_USERNAME = 'neo4j'; NEO4J_PASSWORD = $plain; NEO4J_CYPHER_SHELL_HISTORY = 'disable' }
}

function Test-NebulaRotationAuthentication {
    param([string]$DockerCliPath, [string]$ContainerId, [System.Security.SecureString]$Password)
    $environment = New-NebulaRotationEnvironment -Password $Password
    $writer = New-NebulaRotationInputWriter -Password $Password -Kind probe
    $result = Invoke-NebulaRotationDocker `
        -DockerCliPath $DockerCliPath `
        -Arguments @('exec', '-i', '-e', 'NEO4J_USERNAME', '-e', 'NEO4J_PASSWORD', '-e', 'NEO4J_CYPHER_SHELL_HISTORY', $ContainerId, 'cypher-shell', '--address', 'bolt://localhost:7687', '--non-interactive', '--history', 'disable', '--access-mode', 'read', '--format', 'plain') `
        -ChildEnvironment $environment -InputWriter $writer -TimeoutSeconds 20
    foreach ($key in @($environment.Keys)) { $environment[$key] = $null }
    return (-not $result.TimedOut -and $result.ExitCode -eq 0)
}

function Test-NebulaRotationLogSettingsSafe {
    param([string]$DockerCliPath, [string]$ContainerId, [System.Security.SecureString]$Password)
    $environment = New-NebulaRotationEnvironment -Password $Password
    $writer = New-NebulaRotationLogSettingsInputWriter
    $result = Invoke-NebulaRotationDocker `
        -DockerCliPath $DockerCliPath `
        -Arguments @('exec', '-i', '-e', 'NEO4J_USERNAME', '-e', 'NEO4J_PASSWORD', '-e', 'NEO4J_CYPHER_SHELL_HISTORY', $ContainerId, 'cypher-shell', '--address', 'bolt://localhost:7687', '--non-interactive', '--history', 'disable', '--access-mode', 'read', '--format', 'plain') `
        -ChildEnvironment $environment -InputWriter $writer -CaptureStdOut -TimeoutSeconds 20
    foreach ($key in @($environment.Keys)) { $environment[$key] = $null }
    if ($result.TimedOut -or $result.ExitCode -ne 0) { return $false }
    $settings = @(
        [regex]::Matches([string]$result.StdOut, '(?m)^\s*"?(db\.logs\.query\.(?:parameter_logging_enabled|early_raw_logging_enabled)=(?:true|false))"?\s*$') |
            ForEach-Object { $_.Groups[1].Value }
    )
    return (
        $settings.Count -eq 2 -and
        $settings -contains 'db.logs.query.parameter_logging_enabled=false' -and
        $settings -contains 'db.logs.query.early_raw_logging_enabled=false'
    )
}

function Invoke-NebulaRotationPasswordChange {
    param([string]$DockerCliPath, [string]$ContainerId, [System.Security.SecureString]$OldPassword, [System.Security.SecureString]$NewPassword)
    $environment = New-NebulaRotationEnvironment -Password $OldPassword
    $writer = New-NebulaRotationInputWriter -OldPassword $OldPassword -NewPassword $NewPassword -Kind alter
    $result = Invoke-NebulaRotationDocker `
        -DockerCliPath $DockerCliPath `
        -Arguments @('exec', '-i', '-e', 'NEO4J_USERNAME', '-e', 'NEO4J_PASSWORD', '-e', 'NEO4J_CYPHER_SHELL_HISTORY', $ContainerId, 'cypher-shell', '--address', 'bolt://localhost:7687', '--non-interactive', '--history', 'disable', '--access-mode', 'write', '--format', 'plain') `
        -ChildEnvironment $environment -InputWriter $writer -TimeoutSeconds 30
    foreach ($key in @($environment.Keys)) { $environment[$key] = $null }
    return $result
}

function Write-NebulaRotationProtectedFile {
    param([string]$TargetPath, [System.Security.SecureString]$OldPassword, [System.Security.SecureString]$NewPassword)
    if (Test-Path -LiteralPath $TargetPath) { throw 'The protected target file already exists.' }
    $directory = Split-Path -Parent $TargetPath
    $stage = Join-Path $directory ('.nebula-rotation-' + [Guid]::NewGuid().ToString('N') + '.stage')
    try {
        [System.IO.File]::Create($stage).Dispose()
        if (-not (Protect-NebulaSecretFile -LiteralPath $stage)) { throw 'The protected stage file could not be created.' }
        $stream = New-Object System.IO.FileStream($stage, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        $writer = New-Object System.IO.StreamWriter($stream, [System.Text.UTF8Encoding]::new($false))
        try {
            $writer.Write("NEBULA_ROTATION_PENDING_V1`nold=neo4j/")
            $writer.Write((ConvertTo-NebulaRotationPlainText -Secret $OldPassword))
            $writer.Write("`nnew=neo4j/")
            $writer.Write((ConvertTo-NebulaRotationPlainText -Secret $NewPassword))
            $writer.Flush()
        }
        finally { $writer.Dispose() }
        if (-not (Test-NebulaRotationCurrentUserAcl -Path $stage)) { throw 'The pending credential file ACL could not be verified.' }
        [System.IO.File]::Move($stage, $TargetPath)
        if (-not (Test-NebulaRotationCurrentUserAcl -Path $TargetPath)) { throw 'The pending credential file ACL could not be verified.' }
    }
    catch {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Force -ErrorAction SilentlyContinue }
        throw 'A protected pending credential record could not be created.'
    }
}

function Read-NebulaRotationPendingFile {
    param([string]$Path)
    if (-not (Test-NebulaRotationRegularFile -Path $Path) -or -not (Test-NebulaRotationCurrentUserAcl -Path $Path)) {
        throw 'The pending credential record is missing or not current-user-only.'
    }
    $lines = [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)
    if ($lines.Count -ne 3 -or $lines[0] -cne 'NEBULA_ROTATION_PENDING_V1' -or -not $lines[1].StartsWith('old=neo4j/') -or -not $lines[2].StartsWith('new=neo4j/')) {
        throw 'The pending credential record format is invalid.'
    }
    $old = ConvertTo-NebulaRotationSecureString -Value $lines[1].Substring(10)
    $new = ConvertTo-NebulaRotationSecureString -Value $lines[2].Substring(10)
    if (-not (Test-NebulaRotationCredential $old) -or -not (Test-NebulaRotationCredential $new)) {
        $old.Dispose(); $new.Dispose()
        throw 'The pending credential record failed validation.'
    }
    return [pscustomobject]@{ OldPassword = $old; NewPassword = $new }
}

function Write-NebulaRotationAuthFile {
    param([string]$AuthPath, [System.Security.SecureString]$Password)
    if (-not (Test-NebulaRotationRegularFile -Path $AuthPath)) { throw 'The mounted auth file is unavailable or unsafe.' }
    $stage = Join-Path (Split-Path -Parent $AuthPath) ('.nebula-auth-' + [Guid]::NewGuid().ToString('N') + '.stage')
    $replacementBackup = $AuthPath + '.nebula-auth-replacement-backup'
    $phase = 'prepare'
    try {
        [System.IO.File]::Create($stage).Dispose()
        if (-not (Protect-NebulaSecretFile -LiteralPath $stage)) { throw 'The auth stage ACL could not be prepared.' }
        if (Test-Path -LiteralPath $replacementBackup) {
            if (-not (Test-NebulaRotationRegularFile -Path $replacementBackup)) { throw 'The auth replacement backup is unavailable or unsafe.' }
        }
        else {
            [System.IO.File]::Create($replacementBackup).Dispose()
        }
        if (-not (Test-NebulaRotationCurrentUserAcl -Path $replacementBackup)) {
            if (-not (Protect-NebulaSecretFile -LiteralPath $replacementBackup) -or -not (Test-NebulaRotationCurrentUserAcl -Path $replacementBackup)) {
                throw 'The auth replacement backup ACL could not be verified.'
            }
        }
        $plain = ConvertTo-NebulaRotationPlainText -Secret $Password
        [System.IO.File]::WriteAllText($stage, ('neo4j/' + $plain), [System.Text.UTF8Encoding]::new($false))
        if (-not (Test-NebulaRotationCurrentUserAcl -Path $stage)) { throw 'The auth stage ACL could not be verified.' }
        $phase = 'replace'
        [System.IO.File]::Replace($stage, $AuthPath, $replacementBackup)
        $phase = 'verify'
        if (-not (Test-NebulaRotationCurrentUserAcl -Path $AuthPath)) {
            if (-not (Protect-NebulaSecretFile -LiteralPath $AuthPath) -or -not (Test-NebulaRotationCurrentUserAcl -Path $AuthPath)) {
                throw 'The mounted auth file ACL could not be verified.'
            }
        }
        if (-not (Test-NebulaRotationCurrentUserAcl -Path $replacementBackup)) {
            if (-not (Protect-NebulaSecretFile -LiteralPath $replacementBackup) -or -not (Test-NebulaRotationCurrentUserAcl -Path $replacementBackup)) {
                throw 'The auth replacement backup ACL could not be verified.'
            }
        }
        Remove-Item -LiteralPath $replacementBackup -Force -ErrorAction Stop
    }
    catch {
        $baseError = $_.Exception.GetBaseException()
        $reason = $baseError.GetType().Name
        $code = $baseError.HResult
        throw "The mounted auth file could not be replaced safely ($phase, $reason, $code)."
    }
    finally {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Force -ErrorAction SilentlyContinue }
    }
}

function Wait-NebulaRotationHealthy {
    param([string]$DockerCliPath, [string]$ContainerId, [int]$TimeoutSeconds = 90)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $raw = Get-NebulaRotationMetadata $DockerCliPath @('inspect', '--type=container', '--format', '{{json .State}}', $ContainerId)
        try { $state = ConvertFrom-Json -InputObject $raw -ErrorAction Stop } catch { return $false }
        if ($state.Status -cne 'running') { return $false }
        if ($state.Health.Status -ceq 'healthy') { return $true }
        if ($state.Health.Status -notin @('starting', 'unhealthy')) { return $false }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function Remove-NebulaRotationPendingFile {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force -ErrorAction Stop }
}

function Resolve-NebulaRotationPending {
    param([string]$DockerCliPath, [string]$ContainerId, [string]$AuthPath, [string]$PendingPath)
    $pending = Read-NebulaRotationPendingFile -Path $PendingPath
    try {
        $oldWorks = Test-NebulaRotationAuthentication $DockerCliPath $ContainerId $pending.OldPassword
        $newWorks = Test-NebulaRotationAuthentication $DockerCliPath $ContainerId $pending.NewPassword
        if ($oldWorks -eq $newWorks) {
            return [pscustomobject]@{ Success = $false; State = 'ambiguous'; Message = 'Credential state remains ambiguous; the protected recovery record was retained.' }
        }
        $active = if ($newWorks) { $pending.NewPassword } else { $pending.OldPassword }
        Write-NebulaRotationAuthFile -AuthPath $AuthPath -Password $active
        if (-not (Test-NebulaRotationAuthentication $DockerCliPath $ContainerId $active)) {
            return [pscustomobject]@{ Success = $false; State = 'pending'; Message = 'The active credential could not be reverified; the protected recovery record was retained.' }
        }
        if (-not (Wait-NebulaRotationHealthy $DockerCliPath $ContainerId)) {
            return [pscustomobject]@{ Success = $false; State = 'pending'; Message = 'Database health did not recover; the protected recovery record was retained.' }
        }
        Remove-NebulaRotationPendingFile -Path $PendingPath
        return [pscustomobject]@{ Success = $true; State = $(if ($newWorks) { 'new' } else { 'old' }); Message = 'Pending credential recovery completed.' }
    }
    finally { $pending.OldPassword.Dispose(); $pending.NewPassword.Dispose() }
}

function Invoke-NebulaNeo4jCredentialRotation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedProject,
        [Parameter(Mandatory = $true)][string]$ExpectedContainerId,
        [Parameter(Mandatory = $true)][string]$ExpectedVolumeName,
        [Parameter(Mandatory = $true)][string]$AuthFilePath,
        [Parameter(Mandatory = $true)][string]$BackupDirectory,
        [Parameter(Mandatory = $true)][switch]$BackupForExpectedVolume,
        [switch]$UseProtectedAuthFileAndGenerate,
        [switch]$ResolvePending
    )

    $dockerCli = Get-NebulaRotationDockerCliPath
    if (-not $ResolvePending) {
        Assert-NebulaRotationOfflineBackup -Path $BackupDirectory -VolumeName $ExpectedVolumeName -BackupForExpectedVolume:$BackupForExpectedVolume
    }
    $container = Assert-NebulaRotationLiveIdentity `
        -DockerCliPath $dockerCli -ContainerId $ExpectedContainerId -Project $ExpectedProject `
        -VolumeName $ExpectedVolumeName -AuthPath $AuthFilePath -AllowUnhealthy:$ResolvePending
    $authPath = [System.IO.Path]::GetFullPath($AuthFilePath)
    if (-not (Test-NebulaRotationCurrentUserAcl -Path $authPath)) {
        if (-not (Protect-NebulaSecretFile -LiteralPath $authPath) -or -not (Test-NebulaRotationCurrentUserAcl -Path $authPath)) {
            throw 'The mounted auth file is not protected for the current user.'
        }
    }
    $pendingPath = $authPath + $script:NebulaRotationPendingSuffix

    if ($ResolvePending) {
        if (-not (Test-Path -LiteralPath $pendingPath -PathType Leaf)) { throw 'No pending credential recovery record exists.' }
        return Resolve-NebulaRotationPending -DockerCliPath $dockerCli -ContainerId $ExpectedContainerId -AuthPath $authPath -PendingPath $pendingPath
    }
    if (Test-Path -LiteralPath $pendingPath) { throw 'A pending credential recovery record exists; resolve it before another rotation.' }

    $oldPassword = $null
    $newPassword = $null
    try {
        if ($UseProtectedAuthFileAndGenerate) {
            $oldPassword = Get-NebulaRotationProtectedCurrentPassword -AuthPath $authPath
            $newPassword = New-NebulaRotationGeneratedPassword
        }
        else {
            $oldPassword = Read-Host 'Current Neo4j password' -AsSecureString
            $newPassword = Read-Host 'New Neo4j password' -AsSecureString
        }
        if (-not (Test-NebulaRotationCredential $oldPassword) -or -not (Test-NebulaRotationCredential $newPassword)) {
            throw 'Credentials must be 8-256 printable ASCII characters without line breaks.'
        }
        if ((ConvertTo-NebulaRotationCypherEscapes $oldPassword) -ceq (ConvertTo-NebulaRotationCypherEscapes $newPassword)) {
            throw 'The new credential must differ from the current credential.'
        }
        $oldWorks = Test-NebulaRotationAuthentication $dockerCli $ExpectedContainerId $oldPassword
        $newWorks = Test-NebulaRotationAuthentication $dockerCli $ExpectedContainerId $newPassword
        if (-not $oldWorks -or $newWorks) { throw 'Credential preflight was not uniquely confirmed; no database change was attempted.' }
        if (-not (Test-NebulaRotationLogSettingsSafe -DockerCliPath $dockerCli -ContainerId $ExpectedContainerId -Password $oldPassword)) {
            throw 'Read-only query-log settings did not prove credential parameters are excluded from logs; no database change was attempted.'
        }

        Write-NebulaRotationProtectedFile -TargetPath $pendingPath -OldPassword $oldPassword -NewPassword $newPassword
        # Revalidate target metadata immediately before the state-changing command.
        [void](Assert-NebulaRotationLiveIdentity -DockerCliPath $dockerCli -ContainerId $ExpectedContainerId -Project $ExpectedProject -VolumeName $ExpectedVolumeName -AuthPath $authPath)
        [void](Invoke-NebulaRotationPasswordChange -DockerCliPath $dockerCli -ContainerId $ExpectedContainerId -OldPassword $oldPassword -NewPassword $newPassword)

        $oldWorks = Test-NebulaRotationAuthentication $dockerCli $ExpectedContainerId $oldPassword
        $newWorks = Test-NebulaRotationAuthentication $dockerCli $ExpectedContainerId $newPassword
        if ($oldWorks -eq $newWorks) {
            return [pscustomobject]@{ Success = $false; State = 'ambiguous'; Message = 'Credential state is ambiguous; the protected recovery record was retained.' }
        }
        if ($oldWorks) {
            if (-not (Wait-NebulaRotationHealthy $dockerCli $ExpectedContainerId)) {
                return [pscustomobject]@{ Success = $false; State = 'pending'; Message = 'The old credential remains active but health is unresolved; the protected recovery record was retained.' }
            }
            Remove-NebulaRotationPendingFile -Path $pendingPath
            return [pscustomobject]@{ Success = $false; State = 'unchanged'; Message = 'Neo4j did not accept the new credential; the original auth file remains in place.' }
        }

        Write-NebulaRotationAuthFile -AuthPath $authPath -Password $newPassword
        if (-not (Test-NebulaRotationAuthentication $dockerCli $ExpectedContainerId $newPassword)) {
            return [pscustomobject]@{ Success = $false; State = 'pending'; Message = 'The new credential could not be reverified; the protected recovery record was retained.' }
        }
        if (-not (Wait-NebulaRotationHealthy $dockerCli $ExpectedContainerId)) {
            return [pscustomobject]@{ Success = $false; State = 'pending'; Message = 'Database health did not recover; the protected recovery record was retained.' }
        }
        Remove-NebulaRotationPendingFile -Path $pendingPath
        return [pscustomobject]@{ Success = $true; State = 'rotated'; Message = 'Neo4j credential rotation and read-only health checks completed.' }
    }
    finally {
        if ($null -ne $oldPassword) { $oldPassword.Dispose() }
        if ($null -ne $newPassword) { $newPassword.Dispose() }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        $result = Invoke-NebulaNeo4jCredentialRotation `
            -ExpectedProject $ExpectedProject -ExpectedContainerId $ExpectedContainerId `
            -ExpectedVolumeName $ExpectedVolumeName -AuthFilePath $AuthFilePath `
            -BackupDirectory $BackupDirectory -BackupForExpectedVolume:$BackupForExpectedVolume `
            -UseProtectedAuthFileAndGenerate:$UseProtectedAuthFileAndGenerate `
            -ResolvePending:$ResolvePending
        Write-Output $result.Message
        if (-not $result.Success) { exit 2 }
        exit 0
    }
    catch {
        Write-Output 'Credential rotation stopped safely; no credential values were reported.'
        exit 1
    }
}
