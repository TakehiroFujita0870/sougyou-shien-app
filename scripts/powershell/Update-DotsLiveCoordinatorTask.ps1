[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)][string]$CurrentScriptPath,
    [Parameter(Mandatory = $true)][string]$TargetScriptPath,
    [string]$BackupRoot = (Join-Path $env:LOCALAPPDATA 'Dots\startup\scheduled-task-backups')
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Register-DotsLiveCoordinatorTask.ps1')

function Assert-DotsInstalledCoordinator {
    param([object]$Task, [string]$ScriptPath, [TimeSpan]$TimeLimit, [string]$RepeatInterval)
    if ($null -eq $Task -or @($Task.Actions).Count -ne 1 -or @($Task.Triggers).Count -ne 1) {
        throw 'The installed coordinator task did not match its approved shape.'
    }
    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $trigger = $Task.Triggers[0]
    $settings = $Task.Settings
    if ([string]$Task.Actions[0].Execute -ine $powershell -or
        [string]$Task.Actions[0].Arguments -cne (New-DotsCoordinatorTaskArguments -ScriptPath $ScriptPath) -or
        [string]$Task.Actions[0].WorkingDirectory -cne (Split-Path -Parent $ScriptPath) -or
        [string]$trigger.CimClass.CimClassName -cne 'MSFT_TaskLogonTrigger' -or
        -not [bool]$trigger.Enabled -or
        (Resolve-DotsCoordinatorSid -AccountName ([string]$trigger.UserId)) -cne $currentUser -or
        (Resolve-DotsCoordinatorSid -AccountName ([string]$Task.Principal.UserId)) -cne $currentUser -or
        [string]$Task.Principal.LogonType -cne 'Interactive' -or
        [string]$Task.Principal.RunLevel -cne 'Limited' -or
        -not [bool]$settings.Enabled -or -not [bool]$settings.Hidden -or
        -not [bool]$settings.StartWhenAvailable -or
        [string]$settings.MultipleInstances -cne 'IgnoreNew' -or
        (Convert-DotsTaskExecutionTimeLimit -Value $settings.ExecutionTimeLimit) -ne $TimeLimit -or
        [string]$trigger.Repetition.Interval -cne $RepeatInterval -or
        -not [string]::IsNullOrEmpty([string]$trigger.Repetition.Duration)) {
        throw 'The installed coordinator task did not match its approved definition.'
    }
}

function Update-DotsLiveCoordinatorTask {
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
    param([string]$CurrentScriptPath, [string]$TargetScriptPath, [string]$BackupRoot)

    if (-not (Test-Path -LiteralPath $TargetScriptPath -PathType Leaf)) {
        throw 'The target coordinator script was not found.'
    }
    $name = 'Dots Founder Graph live startup coordinator at logon'
    $task = Get-DotsCoordinatorTask -TaskName $name
    Assert-DotsInstalledCoordinator -Task $task -ScriptPath $CurrentScriptPath -TimeLimit ([TimeSpan]::FromMinutes(3)) -RepeatInterval ''
    if (-not $PSCmdlet.ShouldProcess($name, 'back up and update the current-user recovery trigger')) {
        return [pscustomobject]@{ Updated = $false; BackupFile = $null }
    }

    $oldXml = Export-DotsCoordinatorTask -TaskName $name
    $backupDirectory = New-DotsCoordinatorBackupDirectory -Root $BackupRoot
    $backupFile = Save-DotsCoordinatorTaskBackup -TaskName $name -Xml $oldXml -BackupPath $backupDirectory
    $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-DotsCoordinatorTaskAction -Execute (Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe') `
        -Argument (New-DotsCoordinatorTaskArguments -ScriptPath $TargetScriptPath) -WorkingDirectory (Split-Path -Parent $TargetScriptPath)
    $trigger = New-DotsCoordinatorTaskTrigger -User $user
    $settings = New-DotsCoordinatorTaskSettings

    try {
        Set-ScheduledTask -TaskName $name -TaskPath '\' -Action $action -Trigger $trigger -Settings $settings -Principal $task.Principal -ErrorAction Stop | Out-Null
        $updated = Get-DotsCoordinatorTask -TaskName $name
        Assert-DotsInstalledCoordinator -Task $updated -ScriptPath $TargetScriptPath -TimeLimit ([TimeSpan]::FromMinutes(8)) -RepeatInterval 'PT5M'
    }
    catch {
        try { Register-ScheduledTask -TaskName $name -TaskPath '\' -Xml $oldXml -Force -ErrorAction Stop | Out-Null }
        catch { throw ('Coordinator update failed and automatic rollback failed. Verified original task XML: {0}' -f $backupFile) }
        throw ('Coordinator update failed; the original task was restored. Verified original task XML: {0}' -f $backupFile)
    }
    return [pscustomobject]@{ Updated = $true; BackupFile = $backupFile }
}

if ($MyInvocation.InvocationName -ne '.') {
    Update-DotsLiveCoordinatorTask -CurrentScriptPath $CurrentScriptPath -TargetScriptPath $TargetScriptPath -BackupRoot $BackupRoot
}
