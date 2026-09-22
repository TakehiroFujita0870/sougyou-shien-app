[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('validate', 'start', 'stop', 'status', 'backup', 'restore', 'verify-restore', 'capture-manifest')]
    [string]$Action = 'status',

    [Parameter(Position = 1)]
    [string]$Path,

    [Parameter(Position = 2)]
    [string]$RestoreVolume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDirectory = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDirectory '..\..')).Path
$composeFile = Join-Path $repositoryRoot 'compose.founder-graph.yml'
$validator = Join-Path $scriptDirectory 'validate_local_ops.py'
$restoreVerifier = Join-Path $scriptDirectory 'verify_restore.py'
$manifestCapturer = Join-Path $scriptDirectory 'capture_manifest.py'
$image = 'neo4j:5.26-community'
$liveVolumeKey = 'founder_graph_neo4j_data'
$script:authSecretFile = $null
$script:authFileWasSet = $false
$script:authFileOriginal = $null

function Require-Docker {
    if (-not (Get-Command -Name docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI is unavailable; run this helper inside WSL2 with Docker available.'
    }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Compose v2 is unavailable.'
    }
}

function Require-Auth {
    if ([string]::IsNullOrWhiteSpace($env:FOUNDER_GRAPH_NEO4J_AUTH) -or
        $env:FOUNDER_GRAPH_NEO4J_AUTH -notmatch '^neo4j/.+') {
        throw 'Set FOUNDER_GRAPH_NEO4J_AUTH to neo4j/<local-password> for Docker actions.'
    }
}

function Require-ProjectName {
    $project = if ([string]::IsNullOrWhiteSpace($env:FOUNDER_GRAPH_COMPOSE_PROJECT)) { 'founder-graph-local' } else { $env:FOUNDER_GRAPH_COMPOSE_PROJECT }
    if ($project -notmatch '^[a-z0-9][a-z0-9_-]{0,62}$' -or $project.Contains(',')) {
        throw 'FOUNDER_GRAPH_COMPOSE_PROJECT must use lowercase Docker project-name characters and no commas.'
    }
}

function Initialize-AuthSecret {
    Require-Auth
    $temporaryPath = [System.IO.Path]::GetTempFileName()
    try {
        $encoding = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($temporaryPath, $env:FOUNDER_GRAPH_NEO4J_AUTH, $encoding)
        $acl = Get-Acl -LiteralPath $temporaryPath
        $acl.SetAccessRuleProtection($true, $false)
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $identity,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $acl.SetAccessRule($rule)
        Set-Acl -LiteralPath $temporaryPath -AclObject $acl
    }
    catch {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        throw 'could not create a private temporary auth secret file.'
    }
    $script:authSecretFile = $temporaryPath
    if (Test-Path -LiteralPath Env:FOUNDER_GRAPH_NEO4J_AUTH_FILE) {
        $script:authFileWasSet = $true
        $script:authFileOriginal = $env:FOUNDER_GRAPH_NEO4J_AUTH_FILE
    }
    else {
        $script:authFileWasSet = $false
    }
    $env:FOUNDER_GRAPH_NEO4J_AUTH_FILE = $temporaryPath
}

function Cleanup-AuthSecret {
    if ($null -ne $script:authSecretFile -and (Test-Path -LiteralPath $script:authSecretFile)) {
        Remove-Item -LiteralPath $script:authSecretFile -Force -ErrorAction SilentlyContinue
    }
    if ($script:authFileWasSet) {
        $env:FOUNDER_GRAPH_NEO4J_AUTH_FILE = $script:authFileOriginal
    }
    else {
        Remove-Item Env:FOUNDER_GRAPH_NEO4J_AUTH_FILE -ErrorAction SilentlyContinue
    }
    $script:authSecretFile = $null
}

function Reject-Comma {
    param([string]$Value)
    if ($Value.Contains(',')) { throw 'Docker mount paths and volume names must not contain commas.' }
}

function Is-ReparsePoint {
    param([System.IO.FileSystemInfo]$Item)
    return (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
}

function Assert-BackupDirectory {
    param([string]$RequestedPath)
    if ([string]::IsNullOrWhiteSpace($RequestedPath)) { throw 'backup requires an output directory.' }
    Reject-Comma $RequestedPath
    if (-not [System.IO.Path]::IsPathRooted($RequestedPath)) { throw 'backup output must be an absolute path outside the repository.' }
    $fullPath = [System.IO.Path]::GetFullPath($RequestedPath)
    if ($fullPath.Equals($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $fullPath.StartsWith($repositoryRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase) -or
        $fullPath -match '^[A-Za-z]:[\\/]data([\\/]|$)') { throw 'backup output must not be the repository or a data path.' }

    if (Test-Path -LiteralPath $fullPath) {
        $item = Get-Item -Force -LiteralPath $fullPath
        if (-not $item.PSIsContainer -or (Is-ReparsePoint $item)) { throw 'backup output must be a non-symlink directory.' }
        if (@(Get-ChildItem -Force -LiteralPath $fullPath).Count -ne 0) { throw 'backup output must be empty; existing dumps are never overwritten.' }
    }
    else {
        $parent = Split-Path -Parent $fullPath
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw 'backup output parent must already exist.' }
        if (Is-ReparsePoint (Get-Item -Force -LiteralPath $parent)) { throw 'backup output parent must not be a symlink.' }
        New-Item -ItemType Directory -Path $fullPath | Out-Null
        $item = Get-Item -Force -LiteralPath $fullPath
    }

    # Windows ACL inspection is best effort; reject common broad read grants.
    $broadReaders = @('Everyone', 'BUILTIN\Users', 'Users', 'Authenticated Users', 'NT AUTHORITY\Authenticated Users')
    foreach ($rule in (Get-Acl -LiteralPath $item.FullName).Access) {
        if ($rule.AccessControlType -eq 'Allow' -and $broadReaders -contains $rule.IdentityReference.Value -and [string]$rule.FileSystemRights -match 'Read') {
            throw 'backup output has a broad read ACL; use a private directory.'
        }
    }
    $script:backupDirectory = $item.FullName
}

function Assert-RestoreSource {
    param([string]$RequestedPath)
    if ([string]::IsNullOrWhiteSpace($RequestedPath)) { throw 'restore requires a backup directory.' }
    if (-not [System.IO.Path]::IsPathRooted($RequestedPath)) { throw 'restore source must be an absolute path.' }
    Reject-Comma $RequestedPath
    $item = Get-Item -Force -LiteralPath $RequestedPath
    if (-not $item.PSIsContainer -or (Is-ReparsePoint $item)) { throw 'restore source must be a regular non-symlink directory.' }
    $fullPath = $item.FullName
    if ($fullPath.Equals($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $fullPath.StartsWith($repositoryRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase) -or
        $fullPath -match '^[A-Za-z]:[\\/]data([\\/]|$)') { throw 'restore source must not be the repository or a data path.' }
    foreach ($dump in @('neo4j.dump', 'system.dump')) {
        $dumpItem = Get-Item -Force -LiteralPath (Join-Path $fullPath $dump) -ErrorAction SilentlyContinue
        if ($null -eq $dumpItem -or $dumpItem.PSIsContainer -or (Is-ReparsePoint $dumpItem)) { throw "restore source must contain a regular $dump." }
    }
    $script:backupDirectory = $fullPath
}

function Validate-RestoreVolume {
    param([string]$Volume)
    Reject-Comma $Volume
    if ($Volume -notmatch '^founder-graph-restore-[a-z0-9][a-z0-9_.-]{0,180}$' -or
        @($liveVolumeKey, 'founder-graph-neo4j-data', 'founder-graph-restore-live', 'founder-graph-restore-production') -contains $Volume) {
        throw 'restore volume must match founder-graph-restore-<lowercase-suffix> and not alias the live volume.'
    }
    $script:restoreVolume = $Volume
}

function Invoke-Compose {
    param([string[]]$Arguments)

    & docker compose --file $composeFile @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code $LASTEXITCODE"
    }
}

function Wait-ForHealthy {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $health = (& docker compose --file $composeFile ps --format '{{.Health}}' neo4j 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $health -match 'healthy') { return }
        Start-Sleep -Seconds 1
    }
    throw 'Neo4j did not become healthy after restart.'
}

function Validate-Contract {
    $python = Get-Command -Name python -ErrorAction SilentlyContinue
    if (-not $python) { throw 'python is required for the daemon-free contract validator.' }
    & $python.Source $validator --root $repositoryRoot
    if ($LASTEXITCODE -ne 0) { throw 'Founder Graph local contract validation failed.' }
}

function Backup-Database {
    Assert-BackupDirectory $Path
    $backupDirectory = $script:backupDirectory

    # Official Neo4j 5 syntax: database dump neo4j and database dump system.
    Invoke-Compose @('stop', 'neo4j')
    try {
        Invoke-Compose @(
            'run', '--rm', '--no-deps',
            '--volume', "${backupDirectory}:/backups",
            'neo4j', 'neo4j-admin', 'database', 'dump', 'neo4j',
            '--to-path=/backups'
        )
        Invoke-Compose @(
            'run', '--rm', '--no-deps',
            '--volume', "${backupDirectory}:/backups",
            'neo4j', 'neo4j-admin', 'database', 'dump', 'system',
            '--to-path=/backups'
        )
    }
    finally {
        Invoke-Compose @('start', 'neo4j')
        Wait-ForHealthy
    }
    if (-not (Test-Path -LiteralPath (Join-Path $backupDirectory 'neo4j.dump') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $backupDirectory 'system.dump') -PathType Leaf)) { throw 'Both Neo4j dumps were not created.' }
    Write-Output "Backup written to $backupDirectory\neo4j.dump and system.dump"
}

function Restore-Database {
    Assert-RestoreSource $Path
    $backupDirectory = $script:backupDirectory
    Validate-RestoreVolume $RestoreVolume
    $restoreVolume = $script:restoreVolume
    Require-ProjectName
    $project = if ([string]::IsNullOrWhiteSpace($env:FOUNDER_GRAPH_COMPOSE_PROJECT)) { 'founder-graph-local' } else { $env:FOUNDER_GRAPH_COMPOSE_PROJECT }

    & docker volume inspect $restoreVolume *> $null
    if ($LASTEXITCODE -eq 0) { throw "Refusing an existing restore volume: $restoreVolume" }
    & docker volume create --label com.openai.founder_graph.role=restore --label com.openai.founder_graph.database=neo4j --label "com.openai.founder_graph.project=$project" --label "com.openai.founder_graph.source=$backupDirectory" $restoreVolume *> $null
    if ($LASTEXITCODE -ne 0) { throw "Could not create restore volume: $restoreVolume" }
    $role = (& docker volume inspect --format '{{ index .Labels "com.openai.founder_graph.role" }}' $restoreVolume).Trim()
    $database = (& docker volume inspect --format '{{ index .Labels "com.openai.founder_graph.database" }}' $restoreVolume).Trim()
    if ($role -ne 'restore' -or $database -ne 'neo4j') { throw 'new restore volume labels must be role=restore,database=neo4j.' }

    $dataMount = "type=volume,source=$restoreVolume,target=/data"
    $backupMount = "type=bind,source=$backupDirectory,target=/backups,readonly"
    # The restore invocation intentionally uses --network none.
    & docker run --pull never --rm --network none --user neo4j `
        --mount $dataMount --mount $backupMount `
        $image neo4j-admin database load neo4j `
        --from-path=/backups --overwrite-destination=true
    if ($LASTEXITCODE -ne 0) { throw 'Neo4j restore failed; the isolated volume was retained for inspection.' }
    & docker run --pull never --rm --network none --user neo4j `
        --mount $dataMount --mount $backupMount `
        $image neo4j-admin database load system `
        --from-path=/backups --overwrite-destination=true
    if ($LASTEXITCODE -ne 0) { throw 'Neo4j system restore failed; the isolated volume was retained for inspection.' }
    Write-Output "Restore loaded into isolated volume $restoreVolume"
}

function Verify-Restore {
    if (-not (Get-Command -Name python -ErrorAction SilentlyContinue)) { throw 'python is required for Founder Graph verification.' }
    Validate-RestoreVolume $RestoreVolume
    if ([string]::IsNullOrWhiteSpace($Path)) { throw 'verify-restore requires a manifest JSON path.' }
    Reject-Comma $Path
    & python $restoreVerifier --volume $script:restoreVolume --manifest $Path --secret-file $script:authSecretFile
    if ($LASTEXITCODE -ne 0) { throw 'restore verification failed.' }
}

function Capture-Manifest {
    if (-not (Get-Command -Name python -ErrorAction SilentlyContinue)) { throw 'python is required for manifest capture.' }
    if ([string]::IsNullOrWhiteSpace($Path) -or [string]::IsNullOrWhiteSpace($RestoreVolume)) { throw 'capture-manifest requires queries JSON and output manifest paths.' }
    Reject-Comma $Path
    Reject-Comma $RestoreVolume
    Wait-ForHealthy
    $container = (& docker compose --file $composeFile ps -q neo4j).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($container)) { throw 'could not resolve the healthy Neo4j container.' }
    $project = if ([string]::IsNullOrWhiteSpace($env:FOUNDER_GRAPH_COMPOSE_PROJECT)) { 'founder-graph-local' } else { $env:FOUNDER_GRAPH_COMPOSE_PROJECT }
    & python $manifestCapturer --container $container --queries $Path --output $RestoreVolume --secret-container-path /run/secrets/founder_graph_auth --expected-project $project
    if ($LASTEXITCODE -ne 0) { throw 'manifest capture failed.' }
}

try {
    switch ($Action) {
        'validate' {
            Validate-Contract
        }
        'start' {
            Require-Docker; Require-ProjectName; Initialize-AuthSecret
            Invoke-Compose @('up', '--detach')
            Wait-ForHealthy
        }
        'stop' {
            Require-Docker; Require-ProjectName; Initialize-AuthSecret
            Invoke-Compose @('stop', 'neo4j')
        }
        'status' {
            Require-Docker; Require-ProjectName; Initialize-AuthSecret
            Invoke-Compose @('ps')
        }
        'backup' {
            Require-Docker; Require-ProjectName; Initialize-AuthSecret
            Backup-Database
        }
        'restore' {
            Require-Docker
            Restore-Database
        }
        'verify-restore' {
            Require-Docker; Require-ProjectName; Initialize-AuthSecret
            Verify-Restore
        }
        'capture-manifest' {
            Require-Docker; Require-ProjectName; Initialize-AuthSecret
            Capture-Manifest
        }
    }
}
finally {
    Cleanup-AuthSecret
}
