[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$WindowsControlPlaneEnvFile,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$WindowsSyntheticNeo4jAuthFile,

    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$WslDistribution = 'Ubuntu',

    [ValidatePattern('^/home/[A-Za-z0-9._/-]+$')]
    [string]$WslRepository = '/home/hp/projects/dots-live',

    [ValidateNotNullOrEmpty()]
    [ValidatePattern('^[A-Za-z0-9 ._-]+$')]
    [string]$TaskName = 'Dots Synthetic MCP at logon'
)

$ErrorActionPreference = 'Stop'

$utf8PreflightPath = Join-Path $PSScriptRoot 'Initialize-Utf8Preflight.ps1'
if (-not (Test-Path -LiteralPath $utf8PreflightPath -PathType Leaf)) {
    throw 'The UTF-8 preflight helper is missing.'
}
. $utf8PreflightPath
Test-Utf8Preflight

$secretProtectionPath = Join-Path $PSScriptRoot 'Protect-DotsSecretFile.ps1'
if (-not (Test-Path -LiteralPath $secretProtectionPath -PathType Leaf)) {
    throw 'The secret-file protection helper is missing.'
}
. $secretProtectionPath

foreach ($secretFilePath in @($WindowsControlPlaneEnvFile, $WindowsSyntheticNeo4jAuthFile)) {
    if (-not (Protect-DotsSecretFile -LiteralPath $secretFilePath)) {
        throw 'A required synthetic connection secret file could not be protected.'
    }
}

$wslExecutable = Join-Path $env:WINDIR 'System32\wsl.exe'
if (-not (Test-Path -LiteralPath $wslExecutable -PathType Leaf)) {
    throw 'Windows Subsystem for Linux is unavailable.'
}

$dockerExecutable = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
if (-not (Test-Path -LiteralPath $dockerExecutable -PathType Leaf)) {
    $dockerCommand = Get-Command 'docker.exe' -ErrorAction SilentlyContinue
    if ($null -eq $dockerCommand) {
        throw 'Docker Desktop CLI is unavailable.'
    }
    $dockerExecutable = $dockerCommand.Source
}

$containerState = (& $dockerExecutable inspect --format '{{.State.Status}}' 'dots-chatgpt-synthetic-db' 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $containerState -notin @('running', 'exited')) {
    throw 'The dedicated synthetic database container was not found.'
}

$linuxEnvPath = (& $wslExecutable --distribution $WslDistribution --exec wslpath -a $WindowsControlPlaneEnvFile | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($linuxEnvPath)) {
    throw 'The Windows control-plane environment file path could not be mapped into WSL.'
}

$unitInstaller = "$WslRepository/scripts/founder-graph/install-synthetic-tunnel-unit.sh"
& $wslExecutable --distribution $WslDistribution --exec bash $unitInstaller $WslRepository $linuxEnvPath
if ($LASTEXITCODE -ne 0) {
    throw 'The protected WSL tunnel service could not be installed.'
}

$startupScript = "$WslRepository/scripts/founder-graph/start-synthetic-tunnel-at-logon.sh"
& $wslExecutable --distribution $WslDistribution --exec test -f $startupScript
if ($LASTEXITCODE -ne 0) {
    throw 'The WSL login startup script could not be found.'
}
$keepaliveScript = "$WslRepository/scripts/founder-graph/keep-synthetic-tunnel-alive.sh"
& $wslExecutable --distribution $WslDistribution --exec test -f $keepaliveScript
if ($LASTEXITCODE -ne 0) {
    throw 'The WSL login keepalive script could not be found.'
}

# This updates only the dedicated synthetic container and does not start a stopped container.
& $dockerExecutable update --restart unless-stopped 'dots-chatgpt-synthetic-db' *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'The synthetic database restart policy could not be updated.'
}

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $wslExecutable -Argument "--distribution $WslDistribution --exec bash $keepaliveScript $startupScript"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([System.TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Starts Docker Desktop and the synthetic Dots MCP tunnel after this user signs in; a stopped database remains stopped.' `
    -Force | Out-Null

$currentUserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$logoffTaskName = 'Dots Synthetic MCP at logoff'
$logoffSubscription = @"
<QueryList>
  <Query Id="0" Path="System">
    <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Winlogon'] and EventID=7002] and EventData[Data[@Name='UserSid']='$currentUserSid']]</Select>
  </Query>
</QueryList>
"@
$parsedLogoffSubscription = [xml]$logoffSubscription

$taskScheduler = New-Object -ComObject 'Schedule.Service'
$taskScheduler.Connect()
$taskFolder = $taskScheduler.GetFolder('\')
$logoffDefinition = $taskScheduler.NewTask(0)
$logoffDefinition.RegistrationInfo.Description = 'Stops the synthetic Dots MCP tunnel and its WSL keepalive when this user signs out.'
$logoffDefinition.Principal.UserId = $currentUser
$logoffDefinition.Principal.LogonType = 3
$logoffDefinition.Principal.RunLevel = 0
$logoffDefinition.Settings.Enabled = $true
$logoffDefinition.Settings.Hidden = $true
$logoffDefinition.Settings.MultipleInstances = 2
$logoffDefinition.Settings.ExecutionTimeLimit = 'PT1M'
$logoffTrigger = $logoffDefinition.Triggers.Create(0)
$logoffTrigger.Enabled = $true
$logoffTrigger.Subscription = $logoffSubscription
$logoffAction = $logoffDefinition.Actions.Create(0)
$logoffAction.Path = $wslExecutable
$logoffAction.Arguments = "--distribution $WslDistribution --exec systemctl --user stop dots-synthetic-tunnel.service"
$logoffAction.WorkingDirectory = $env:SystemRoot
$stopTaskAction = $logoffDefinition.Actions.Create(0)
$stopTaskAction.Path = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$stopTaskAction.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"Stop-ScheduledTask -TaskName '$TaskName' -ErrorAction SilentlyContinue; exit 0`""
$stopTaskAction.WorkingDirectory = $env:SystemRoot
$taskFolder.RegisterTaskDefinition($logoffTaskName, $logoffDefinition, 6, $currentUser, $null, 3, $null) | Out-Null

Write-Output "Registered the per-user Dots synthetic connection startup task: $TaskName"
Write-Output "Registered the per-user tunnel stop task: $logoffTaskName"
