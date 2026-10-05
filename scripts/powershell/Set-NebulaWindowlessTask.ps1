[CmdletBinding(SupportsShouldProcess = $true)]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Register-NebulaLiveCoordinatorTask.ps1')

$taskName = 'Nebula Founder Graph live startup coordinator at logon'
$task = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction Stop
if ((Resolve-NebulaCoordinatorSid -AccountName $task.Principal.UserId) -cne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value -or
    $task.Principal.RunLevel.ToString() -ne 'Limited') { throw 'Task is not bound to the current limited user.' }
$actions = @($task.Actions)
$expectedPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
if ($actions.Count -ne 1 -or $actions[0].Execute -ine $expectedPowerShell -or
    $actions[0].Arguments -notmatch '^-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "([^"]+Start-NebulaLiveCoordinatorAtLogon\.ps1)"$') {
    throw 'Existing action differs from the verified Nebula coordinator; no task changed.'
}
$coordinatorPath = $Matches[1]
if (-not (Test-Path -LiteralPath $coordinatorPath -PathType Leaf)) { throw 'Coordinator script unavailable.' }
$source = Join-Path $PSScriptRoot 'NebulaStartupLauncher.cs'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) { throw 'Windows C# compiler unavailable.' }
if (-not $PSCmdlet.ShouldProcess($taskName, 'Replace only the console action with a windowless launcher')) { return }
# Avoid packaged-app LocalAppData virtualization: the scheduler runs outside Codex's package.
$backup = New-NebulaCoordinatorBackupDirectory -Root (Join-Path $env:USERPROFILE '.local\share\Nebula\startup')
$originalXml = Export-ScheduledTask -TaskName $taskName -TaskPath '\'
$backupFile = Save-NebulaCoordinatorTaskBackup -TaskName $taskName -Xml $originalXml -BackupPath $backup
$executable = Join-Path $backup 'NebulaStartup.exe'
& $compiler /nologo /target:winexe "/out:$executable" $source
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw 'Compilation failed; task unchanged.' }
# Do not use a WSL UNC working directory: Task Scheduler can fail before the launcher starts.
# The coordinator resolves its dependencies from PSScriptRoot, not the inherited directory.
$action = New-ScheduledTaskAction -Execute $executable -Argument ('"{0}"' -f $coordinatorPath)
try {
    Set-ScheduledTask -TaskName $taskName -TaskPath '\' -Action $action -ErrorAction Stop | Out-Null
    $newXml = [xml](Export-ScheduledTask -TaskName $taskName -TaskPath '\')
    $oldXml = [xml]$originalXml
    $newXml.Task.Actions.InnerXml = $oldXml.Task.Actions.InnerXml
    if ($newXml.OuterXml -cne $oldXml.OuterXml) { throw 'Non-action task settings changed.' }
    $readBack = Get-ScheduledTask -TaskName $taskName -TaskPath '\'
    if ($readBack.Actions.Execute -cne $executable -or $readBack.Actions.Arguments -cne $action.Arguments) { throw 'Action verification failed.' }
} catch {
    Register-ScheduledTask -TaskName $taskName -TaskPath '\' -Xml $originalXml -Force | Out-Null
    throw
}
[pscustomobject]@{ Updated = $true; BackupFile = $backupFile; Launcher = $executable }
