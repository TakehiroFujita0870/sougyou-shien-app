[CmdletBinding()]
param(
    [string]$WindowsNeo4jAuthFile,
    [switch]$CredentialRotationVerified
)

$ErrorActionPreference = 'Stop'
$secretProtectionPath = Join-Path $PSScriptRoot 'Protect-DotsSecretFile.ps1'
if (-not (Test-Path -LiteralPath $secretProtectionPath -PathType Leaf)) {
    throw 'The secret-file protection helper is missing.'
}
. $secretProtectionPath

$script:DotsLiveTaskName = 'Dots Founder Graph live database at logon'
$script:DotsLiveStartupScript = Join-Path $PSScriptRoot 'Start-DotsLiveAtLogon.ps1'

function Register-DotsLiveLogonTask {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$WindowsNeo4jAuthFile,
        [switch]$CredentialRotationVerified
    )

    if (-not (Test-Path -LiteralPath $script:DotsLiveStartupScript -PathType Leaf)) {
        throw 'The live database startup script is missing.'
    }

    if (-not $CredentialRotationVerified) {
        throw 'Credential rotation confirmation is required before registering live startup.'
    }

    if (-not [System.IO.Path]::IsPathRooted($WindowsNeo4jAuthFile)) {
        throw 'The normal Neo4j auth-file path must be absolute.'
    }

    $existingTask = Get-DotsLiveExistingTask -TaskName $script:DotsLiveTaskName
    if ($null -ne $existingTask) {
        throw 'The live database login task already exists and was not overwritten.'
    }

    try { $protected = Protect-OrAccept-DotsLiveAuthFile -LiteralPath $WindowsNeo4jAuthFile }
    catch { throw 'The normal Neo4j auth file could not be protected.' }
    if (-not $protected) {
        throw 'The normal Neo4j auth file could not be protected.'
    }

    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ([string]::IsNullOrWhiteSpace($currentUser)) {
        throw 'The current Windows user could not be identified.'
    }

    $powershellExecutable = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powershellExecutable -PathType Leaf)) {
        throw 'Windows PowerShell is unavailable.'
    }

    $actionArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $script:DotsLiveStartupScript
    $action = New-DotsLiveTaskAction -Execute $powershellExecutable -Argument $actionArguments
    $trigger = New-DotsLiveTaskTrigger -AtLogOn -User $currentUser
    $principal = New-DotsLiveTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
    $settings = New-DotsLiveTaskSettings `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([System.TimeSpan]::FromMinutes(3))

    # No -Force: an existing task of the same name must be reviewed, not overwritten.
    Register-DotsLiveTaskDefinition `
        -TaskName $script:DotsLiveTaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description 'Checks only the existing local Founder Graph live database after this user signs in; it does not start stopped databases or expose a tunnel.' | Out-Null

    return [pscustomobject]@{ Registered = $true; TaskName = $script:DotsLiveTaskName }
}

function Protect-OrAccept-DotsLiveAuthFile {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$LiteralPath)

    # The live auth file is intentionally shared with SYSTEM and Administrators
    # for the protected Docker bind mount. Accept only this exact ACL read-only;
    # all other secret files retain the generic current-user-only behavior.
    Assert-RegularSecretFile -Path $LiteralPath
    try { $acl = Get-Acl -LiteralPath $LiteralPath -ErrorAction Stop }
    catch { throw 'The normal Neo4j auth-file ACL could not be inspected.' }

    $currentUserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    if ($null -eq $currentUserSid) { throw 'Current Windows user SID is unavailable.' }
    $liveAllowedSids = @($currentUserSid.Value, 'S-1-5-18', 'S-1-5-32-544')
    if (Test-ExactSecretAcl -Acl $acl -AllowedSidValues $liveAllowedSids) { return $true }

    return Protect-DotsSecretFile -LiteralPath $LiteralPath
}

function Get-DotsLiveExistingTask {
    param([Parameter(Mandatory = $true)][string]$TaskName)
    return Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

function New-DotsLiveTaskAction {
    param([string]$Execute, [string]$Argument)
    return New-ScheduledTaskAction -Execute $Execute -Argument $Argument
}

function New-DotsLiveTaskTrigger {
    param([switch]$AtLogOn, [string]$User)
    return New-ScheduledTaskTrigger -AtLogOn:$AtLogOn -User $User
}

function New-DotsLiveTaskPrincipal {
    param([string]$UserId, [string]$LogonType, [string]$RunLevel)
    return New-ScheduledTaskPrincipal -UserId $UserId -LogonType $LogonType -RunLevel $RunLevel
}

function New-DotsLiveTaskSettings {
    param(
        [string]$MultipleInstances,
        [switch]$StartWhenAvailable,
        [switch]$AllowStartIfOnBatteries,
        [switch]$DontStopIfGoingOnBatteries,
        [System.TimeSpan]$ExecutionTimeLimit
    )
    return New-ScheduledTaskSettingsSet `
        -MultipleInstances $MultipleInstances `
        -StartWhenAvailable:$StartWhenAvailable `
        -AllowStartIfOnBatteries:$AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries:$DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit $ExecutionTimeLimit
}

function Register-DotsLiveTaskDefinition {
    param(
        [string]$TaskName,
        [object]$Action,
        [object]$Trigger,
        [object]$Principal,
        [object]$Settings,
        [string]$Description
    )
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Principal $Principal `
        -Settings $Settings `
        -Description $Description | Out-Null
}

if ($MyInvocation.InvocationName -ne '.') {
    if ([string]::IsNullOrWhiteSpace($WindowsNeo4jAuthFile)) {
        throw 'The normal Neo4j auth-file path is required.'
    }
    if (-not $CredentialRotationVerified) {
        throw 'Credential rotation confirmation is required before registering live startup.'
    }
    $result = Register-DotsLiveLogonTask `
        -WindowsNeo4jAuthFile $WindowsNeo4jAuthFile `
        -CredentialRotationVerified
    Write-Output "Registered the current-user live database login task: $($result.TaskName)"
}
