[CmdletBinding()]
param(
    [switch]$CredentialRotationVerified,

    [switch]$PrivateProjectionAndEgressReviewed,

    [ValidatePattern('^[A-Za-z0-9 ._-]+$')]
    [string]$TaskName = 'Nebula live MCP tunnel at logon'
)

$ErrorActionPreference = 'Stop'
$script:NebulaLiveMcpStartupScript = Join-Path $PSScriptRoot 'Start-NebulaLiveMcpAtLogon.ps1'

function Register-NebulaLiveMcpLogonTask {
    param(
        [Parameter(Mandatory = $true)][switch]$CredentialRotationVerified,
        [Parameter(Mandatory = $true)][switch]$PrivateProjectionAndEgressReviewed,
        [Parameter(Mandatory = $true)][string]$TaskName
    )

    if (-not $CredentialRotationVerified -or -not $PrivateProjectionAndEgressReviewed) {
        throw 'Credential rotation and private-projection/egress review confirmations are required.'
    }
    if (-not (Test-Path -LiteralPath $script:NebulaLiveMcpStartupScript -PathType Leaf)) {
        throw 'The live MCP startup script is missing.'
    }
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        throw 'A task with this name already exists and was not overwritten.'
    }

    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $wslExecutable = Join-Path $env:WINDIR 'System32\wsl.exe'
    if (-not (Test-Path -LiteralPath $wslExecutable -PathType Leaf)) {
        throw 'Windows Subsystem for Linux is unavailable.'
    }
    $powershellExecutable = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $actionArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $script:NebulaLiveMcpStartupScript
    $action = New-NebulaLiveMcpTaskAction -Execute $powershellExecutable -Argument $actionArguments
    $trigger = New-NebulaLiveMcpTaskTrigger -AtLogOn -User $currentUser
    $principal = New-NebulaLiveMcpTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
    $settings = New-NebulaLiveMcpTaskSettings -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-NebulaLiveMcpTaskDefinition -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Starts the live Nebula MCP tunnel only after the existing normal database is healthy and explicit safety gates pass.'
    return [pscustomobject]@{ Registered = $true; TaskName = $TaskName }
}

function New-NebulaLiveMcpTaskAction { param([string]$Execute, [string]$Argument) New-ScheduledTaskAction -Execute $Execute -Argument $Argument }
function New-NebulaLiveMcpTaskTrigger { param([switch]$AtLogOn, [string]$User) New-ScheduledTaskTrigger -AtLogOn:$AtLogOn -User $User }
function New-NebulaLiveMcpTaskPrincipal { param([string]$UserId, [string]$LogonType, [string]$RunLevel) New-ScheduledTaskPrincipal -UserId $UserId -LogonType $LogonType -RunLevel $RunLevel }
function New-NebulaLiveMcpTaskSettings {
    param([string]$MultipleInstances, [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries, [TimeSpan]$ExecutionTimeLimit)
    New-ScheduledTaskSettingsSet -MultipleInstances $MultipleInstances -StartWhenAvailable -AllowStartIfOnBatteries:$AllowStartIfOnBatteries -DontStopIfGoingOnBatteries:$DontStopIfGoingOnBatteries -ExecutionTimeLimit $ExecutionTimeLimit
}
function Register-NebulaLiveMcpTaskDefinition {
    param([string]$TaskName, [object]$Action, [object]$Trigger, [object]$Principal, [object]$Settings, [string]$Description)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description $Description | Out-Null
}

if ($MyInvocation.InvocationName -ne '.') {
    Register-NebulaLiveMcpLogonTask -CredentialRotationVerified:$CredentialRotationVerified -PrivateProjectionAndEgressReviewed:$PrivateProjectionAndEgressReviewed -TaskName $TaskName | Out-Null
    Write-Output "Registered the current-user live MCP logon task: $TaskName"
}
