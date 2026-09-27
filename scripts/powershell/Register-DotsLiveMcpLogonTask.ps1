[CmdletBinding()]
param(
    [switch]$CredentialRotationVerified,

    [switch]$PrivateProjectionAndEgressReviewed,

    [ValidatePattern('^[A-Za-z0-9 ._-]+$')]
    [string]$TaskName = 'Dots live MCP tunnel at logon'
)

$ErrorActionPreference = 'Stop'
$script:DotsLiveMcpStartupScript = Join-Path $PSScriptRoot 'Start-DotsLiveMcpAtLogon.ps1'

function Register-DotsLiveMcpLogonTask {
    param(
        [Parameter(Mandatory = $true)][switch]$CredentialRotationVerified,
        [Parameter(Mandatory = $true)][switch]$PrivateProjectionAndEgressReviewed,
        [Parameter(Mandatory = $true)][string]$TaskName
    )

    if (-not $CredentialRotationVerified -or -not $PrivateProjectionAndEgressReviewed) {
        throw 'Credential rotation and private-projection/egress review confirmations are required.'
    }
    if (-not (Test-Path -LiteralPath $script:DotsLiveMcpStartupScript -PathType Leaf)) {
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
    $actionArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $script:DotsLiveMcpStartupScript
    $action = New-DotsLiveMcpTaskAction -Execute $powershellExecutable -Argument $actionArguments
    $trigger = New-DotsLiveMcpTaskTrigger -AtLogOn -User $currentUser
    $principal = New-DotsLiveMcpTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
    $settings = New-DotsLiveMcpTaskSettings -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-DotsLiveMcpTaskDefinition -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Starts the live Dots MCP tunnel only after the existing normal database is healthy and explicit safety gates pass.'
    return [pscustomobject]@{ Registered = $true; TaskName = $TaskName }
}

function New-DotsLiveMcpTaskAction { param([string]$Execute, [string]$Argument) New-ScheduledTaskAction -Execute $Execute -Argument $Argument }
function New-DotsLiveMcpTaskTrigger { param([switch]$AtLogOn, [string]$User) New-ScheduledTaskTrigger -AtLogOn:$AtLogOn -User $User }
function New-DotsLiveMcpTaskPrincipal { param([string]$UserId, [string]$LogonType, [string]$RunLevel) New-ScheduledTaskPrincipal -UserId $UserId -LogonType $LogonType -RunLevel $RunLevel }
function New-DotsLiveMcpTaskSettings {
    param([string]$MultipleInstances, [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries, [TimeSpan]$ExecutionTimeLimit)
    New-ScheduledTaskSettingsSet -MultipleInstances $MultipleInstances -StartWhenAvailable -AllowStartIfOnBatteries:$AllowStartIfOnBatteries -DontStopIfGoingOnBatteries:$DontStopIfGoingOnBatteries -ExecutionTimeLimit $ExecutionTimeLimit
}
function Register-DotsLiveMcpTaskDefinition {
    param([string]$TaskName, [object]$Action, [object]$Trigger, [object]$Principal, [object]$Settings, [string]$Description)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description $Description | Out-Null
}

if ($MyInvocation.InvocationName -ne '.') {
    Register-DotsLiveMcpLogonTask -CredentialRotationVerified:$CredentialRotationVerified -PrivateProjectionAndEgressReviewed:$PrivateProjectionAndEgressReviewed -TaskName $TaskName | Out-Null
    Write-Output "Registered the current-user live MCP logon task: $TaskName"
}
