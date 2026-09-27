[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [ValidateNotNullOrEmpty()]
    [string]$BackupRoot = (Join-Path $env:LOCALAPPDATA 'Dots\startup\scheduled-task-backups'),

    [switch]$BackupOnly
)

$ErrorActionPreference = 'Stop'
$script:DotsLiveCoordinatorTaskName = 'Dots Founder Graph live startup coordinator at logon'
$script:DotsLiveDatabaseTaskName = 'Dots Founder Graph live database at logon'
$script:DotsLiveMcpTaskName = 'Dots live MCP tunnel at logon'
$script:DotsLiveCoordinatorBackupRoot = $BackupRoot

function Get-DotsCoordinatorTask {
    param([Parameter(Mandatory = $true)][string]$TaskName)
    $tasks = @(Get-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction SilentlyContinue)
    if ($tasks.Count -gt 1) { throw 'A scheduled task name resolved to multiple definitions.' }
    if ($tasks.Count -eq 0) { return $null }
    return $tasks[0]
}

function Assert-DotsCoordinatorControlServiceHook {
    $coordinatorPath = Join-Path $PSScriptRoot 'Start-DotsLiveCoordinatorAtLogon.ps1'
    $source = [System.IO.File]::ReadAllText($coordinatorPath)
    $functionStart = $source.IndexOf('function Invoke-DotsLiveLogonCoordinator', [StringComparison]::Ordinal)
    if ($functionStart -lt 0) { throw 'The coordinator entry function was not found.' }
    $functionEnd = $source.IndexOf("`n}", $functionStart, [StringComparison]::Ordinal)
    if ($functionEnd -lt 0) { throw 'The coordinator entry function could not be inspected.' }
    $body = $source.Substring($functionStart, $functionEnd - $functionStart)
    $hookIndex = $body.IndexOf('Start-DotsLiveDashboardController', [StringComparison]::Ordinal)
    $markerIndex = $body.IndexOf('Test-DotsLiveStopIntent', [StringComparison]::Ordinal)
    if ($hookIndex -lt 0 -or $markerIndex -lt 0 -or $hookIndex -gt $markerIndex) {
        throw 'The coordinator does not yet start the always-on local control service before checking explicit-stop intent.'
    }
}

function Export-DotsCoordinatorTask {
    param([Parameter(Mandatory = $true)][string]$TaskName)
    return Export-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction Stop
}

function Resolve-DotsCoordinatorSid {
    param([Parameter(Mandatory = $true)][string]$AccountName)
    try {
        return (New-Object System.Security.Principal.NTAccount($AccountName)).Translate([System.Security.Principal.SecurityIdentifier]).Value
    }
    catch { return $null }
}

function Convert-DotsTaskExecutionTimeLimit {
    param([Parameter(Mandatory = $true)][object]$Value)
    if ($Value -is [TimeSpan]) { return $Value }
    try { return [System.Xml.XmlConvert]::ToTimeSpan([string]$Value) }
    catch { throw 'A scheduled task execution limit was not a valid duration.' }
}

function Assert-DotsLegacyLogonTask {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][object]$Task,
        [Parameter(Mandatory = $true)][string]$StartupScriptPath,
        [Parameter(Mandatory = $true)][TimeSpan]$ExecutionTimeLimit
    )

    $identitySid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $actions = @($Task.Actions)
    $triggers = @($Task.Triggers)
    if ($actions.Count -ne 1 -or $triggers.Count -ne 1) { throw 'A legacy login task did not match the expected action and trigger count.' }

    $expectedPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $expectedArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $StartupScriptPath
    if ([string]$actions[0].Execute -ine $expectedPowerShell -or [string]$actions[0].Arguments -cne $expectedArguments) {
        throw 'A legacy login task action did not match its approved startup script.'
    }
    if ($null -ne $actions[0].WorkingDirectory -and -not [string]::IsNullOrWhiteSpace([string]$actions[0].WorkingDirectory)) {
        throw 'A legacy login task had an unexpected working directory.'
    }

    $triggerType = [string]$triggers[0].CimClass.CimClassName
    if ($triggerType -cne 'MSFT_TaskLogonTrigger' -or -not [bool]$triggers[0].Enabled) {
        throw 'A legacy login task trigger did not match the enabled interactive-logon trigger.'
    }
    if ((Resolve-DotsCoordinatorSid -AccountName ([string]$triggers[0].UserId)) -cne $identitySid -or
        (Resolve-DotsCoordinatorSid -AccountName ([string]$Task.Principal.UserId)) -cne $identitySid -or
        [string]$Task.Principal.LogonType -cne 'Interactive' -or [string]$Task.Principal.RunLevel -cne 'Limited') {
        throw 'A legacy login task principal did not match the current limited interactive user.'
    }

    $settings = $Task.Settings
    if ([string]$settings.MultipleInstances -cne 'IgnoreNew' -or
        -not [bool]$settings.Enabled -or
        -not [bool]$settings.StartWhenAvailable -or
        [bool]$settings.DisallowStartIfOnBatteries -or
        [bool]$settings.StopIfGoingOnBatteries -or
        [bool]$settings.Hidden -or
        (Convert-DotsTaskExecutionTimeLimit -Value $settings.ExecutionTimeLimit) -ne $ExecutionTimeLimit) {
        throw 'A legacy login task setting did not match the approved startup definition.'
    }
    if ([string]$Task.State -notin @('Ready', 'Running')) { throw 'A legacy login task was not enabled.' }
}

function Get-DotsCoordinatorBackupAcl {
    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    if ($null -eq $currentSid) { throw 'The current Windows user could not be identified.' }
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach ($sid in @($currentSid, (New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')), (New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')))) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, [System.Security.AccessControl.FileSystemRights]::FullControl, $inheritance, [System.Security.AccessControl.PropagationFlags]::None, [System.Security.AccessControl.AccessControlType]::Allow)
        [void]$acl.AddAccessRule($rule)
    }
    return $acl
}

function New-DotsCoordinatorBackupDirectory {
    param([Parameter(Mandatory = $true)][string]$Root)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { [void](New-Item -ItemType Directory -Path $Root -Force -ErrorAction Stop) }
    $name = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [Guid]::NewGuid().ToString('N')
    $path = Join-Path $Root $name
    [void](New-Item -ItemType Directory -Path $path -ErrorAction Stop)
    Set-Acl -LiteralPath $path -AclObject (Get-DotsCoordinatorBackupAcl) -ErrorAction Stop
    $acl = Get-Acl -LiteralPath $path -ErrorAction Stop
    $rules = @($acl.Access)
    if (-not $acl.AreAccessRulesProtected -or $rules.Count -ne 3) { throw 'The task-backup permissions could not be verified.' }
    $expectedSids = @([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18', 'S-1-5-32-544')
    foreach ($rule in $rules) {
        try { $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }
        catch { throw 'The task-backup permissions could not be verified.' }
        if ($expectedSids -notcontains $sid -or $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
            $rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl) { throw 'The task-backup permissions could not be verified.' }
        $expectedSids = @($expectedSids | Where-Object { $_ -cne $sid })
    }
    if ($expectedSids.Count -ne 0) { throw 'The task-backup permissions could not be verified.' }
    return $path
}

function Save-DotsCoordinatorTaskBackup {
    param([Parameter(Mandatory = $true)][string]$TaskName, [Parameter(Mandatory = $true)][string]$Xml, [Parameter(Mandatory = $true)][string]$BackupPath)
    if ([string]::IsNullOrWhiteSpace($Xml)) { throw 'A legacy task definition export was empty.' }
    try { [void][xml]$Xml } catch { throw 'A legacy task definition export was not valid XML.' }
    $path = Join-Path $BackupPath (($TaskName -replace '[^A-Za-z0-9-]', '-') + '.xml')
    if (Test-Path -LiteralPath $path) { throw 'A task-backup file already exists.' }
    [System.IO.File]::WriteAllText($path, $Xml, (New-Object System.Text.UTF8Encoding($false)))
    $readBack = [System.IO.File]::ReadAllText($path)
    if ($readBack -cne $Xml) { throw 'A task definition backup did not pass read-back verification.' }
    return $path
}

function New-DotsCoordinatorTaskAction {
    param([string]$Execute, [string]$Argument, [string]$WorkingDirectory)
    New-ScheduledTaskAction -Execute $Execute -Argument $Argument -WorkingDirectory $WorkingDirectory
}
function New-DotsCoordinatorTaskArguments {
    param([Parameter(Mandatory = $true)][string]$ScriptPath)
    return '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $ScriptPath
}
function New-DotsCoordinatorTaskTrigger { param([string]$User) New-ScheduledTaskTrigger -AtLogOn -User $User }
function New-DotsCoordinatorTaskPrincipal { param([string]$UserId) New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited }
function New-DotsCoordinatorTaskSettings {
    New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::FromMinutes(3)) -Hidden
}
function Register-DotsCoordinatorTaskDefinition {
    param([string]$TaskName, [object]$Action, [object]$Trigger, [object]$Principal, [object]$Settings, [string]$Description)
    Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description $Description -ErrorAction Stop | Out-Null
}
function Disable-DotsCoordinatorTask { param([string]$TaskName) Disable-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction Stop | Out-Null }
function Enable-DotsCoordinatorTask { param([string]$TaskName) Enable-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction Stop | Out-Null }
function Remove-DotsCoordinatorTask { param([string]$TaskName) Unregister-ScheduledTask -TaskName $TaskName -TaskPath '\' -Confirm:$false -ErrorAction Stop }

function Register-DotsLiveCoordinatorTask {
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
    param([Parameter()][string]$BackupRoot = $script:DotsLiveCoordinatorBackupRoot, [switch]$BackupOnly)

    if ([string]::IsNullOrWhiteSpace($BackupRoot)) { throw 'A local task-backup directory is required.' }
    if ($null -ne (Get-DotsCoordinatorTask -TaskName $script:DotsLiveCoordinatorTaskName)) {
        throw 'The coordinator task already exists and was not overwritten.'
    }

    $databaseTask = Get-DotsCoordinatorTask -TaskName $script:DotsLiveDatabaseTaskName
    $mcpTask = Get-DotsCoordinatorTask -TaskName $script:DotsLiveMcpTaskName
    if ($null -eq $databaseTask -or $null -eq $mcpTask) {
        throw 'Both existing live login tasks are required; no task was changed.'
    }

    # Preserve the original XML before evaluating or changing either task.
    $databaseXml = Export-DotsCoordinatorTask -TaskName $script:DotsLiveDatabaseTaskName
    $mcpXml = Export-DotsCoordinatorTask -TaskName $script:DotsLiveMcpTaskName
    $databaseScript = Join-Path $PSScriptRoot 'Start-DotsLiveAtLogon.ps1'
    $mcpScript = Join-Path $PSScriptRoot 'Start-DotsLiveMcpAtLogon.ps1'
    Assert-DotsLegacyLogonTask -TaskName $script:DotsLiveDatabaseTaskName -Task $databaseTask -StartupScriptPath $databaseScript -ExecutionTimeLimit ([TimeSpan]::FromMinutes(3))
    Assert-DotsLegacyLogonTask -TaskName $script:DotsLiveMcpTaskName -Task $mcpTask -StartupScriptPath $mcpScript -ExecutionTimeLimit ([TimeSpan]::Zero)
    $controlServiceHookError = $null
    try { Assert-DotsCoordinatorControlServiceHook }
    catch { $controlServiceHookError = $_.Exception.Message }

    if ($WhatIfPreference) {
        return [pscustomobject]@{ Registered = $false; WhatIf = $true; Blocked = ($null -ne $controlServiceHookError); BlockReason = $controlServiceHookError; BackupDirectory = $null; BackupFiles = @(); LegacyTaskNames = @($script:DotsLiveDatabaseTaskName, $script:DotsLiveMcpTaskName) }
    }
    $backupDirectory = New-DotsCoordinatorBackupDirectory -Root $BackupRoot
    $databaseBackup = Save-DotsCoordinatorTaskBackup -TaskName $script:DotsLiveDatabaseTaskName -Xml $databaseXml -BackupPath $backupDirectory
    $mcpBackup = Save-DotsCoordinatorTaskBackup -TaskName $script:DotsLiveMcpTaskName -Xml $mcpXml -BackupPath $backupDirectory

    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ([string]::IsNullOrWhiteSpace($currentUser)) { throw 'The current Windows user could not be identified.' }
    $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $coordinatorScript = Join-Path $PSScriptRoot 'Start-DotsLiveCoordinatorAtLogon.ps1'
    if (-not (Test-Path -LiteralPath $coordinatorScript -PathType Leaf)) { throw 'The coordinator startup script is missing.' }
    $arguments = New-DotsCoordinatorTaskArguments -ScriptPath $coordinatorScript
    $action = New-DotsCoordinatorTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $PSScriptRoot
    $trigger = New-DotsCoordinatorTaskTrigger -User $currentUser
    $principal = New-DotsCoordinatorTaskPrincipal -UserId $currentUser
    $settings = New-DotsCoordinatorTaskSettings
    $description = 'Starts the existing Founder Graph live database preflight and approved MCP tunnel in order; honors the persistent explicit-stop marker.'

    if ($null -ne $controlServiceHookError) {
        if ($BackupOnly) {
            return [pscustomobject]@{ Registered = $false; BackupOnly = $true; Blocked = $true; BlockReason = $controlServiceHookError; BackupDirectory = $backupDirectory; BackupFiles = @($databaseBackup, $mcpBackup); LegacyTaskNames = @($script:DotsLiveDatabaseTaskName, $script:DotsLiveMcpTaskName) }
        }
        throw ('{0} Verified original task XML backups are in: {1}' -f $controlServiceHookError, $backupDirectory)
    }
    if ($BackupOnly) {
        return [pscustomobject]@{ Registered = $false; BackupOnly = $true; BackupDirectory = $backupDirectory; BackupFiles = @($databaseBackup, $mcpBackup); LegacyTaskNames = @($script:DotsLiveDatabaseTaskName, $script:DotsLiveMcpTaskName) }
    }

    $target = 'the two verified live login tasks and the new single coordinator task'
    $operation = 'back up, replace their logon triggers with one hidden current-user coordinator, and keep the original task XML for rollback'
    if (-not $PSCmdlet.ShouldProcess($target, $operation)) {
        return [pscustomobject]@{ Registered = $false; WhatIf = $true; BackupDirectory = $backupDirectory; BackupFiles = @($databaseBackup, $mcpBackup); LegacyTaskNames = @($script:DotsLiveDatabaseTaskName, $script:DotsLiveMcpTaskName) }
    }

    $registered = $false
    $migrationPhase = 'disable_legacy'
    try {
        # Disable only after both exact definitions have been backed up and validated.
        $migrationPhase = 'disable_database_task'
        Disable-DotsCoordinatorTask -TaskName $script:DotsLiveDatabaseTaskName
        $migrationPhase = 'disable_mcp_task'
        Disable-DotsCoordinatorTask -TaskName $script:DotsLiveMcpTaskName
        $migrationPhase = 'verify_legacy_disabled'
        foreach ($legacyName in @($script:DotsLiveDatabaseTaskName, $script:DotsLiveMcpTaskName)) {
            $disabledTask = Get-DotsCoordinatorTask -TaskName $legacyName
            if ($null -eq $disabledTask -or [bool]$disabledTask.Settings.Enabled) {
                throw 'A legacy login task remained enabled after migration.'
            }
        }

        $migrationPhase = 'register_coordinator'
        Register-DotsCoordinatorTaskDefinition `
            -TaskName $script:DotsLiveCoordinatorTaskName `
            -Action $action `
            -Trigger $trigger `
            -Principal $principal `
            -Settings $settings `
            -Description $description
        $registered = $true

        $migrationPhase = 'validate_coordinator'
        $coordinatorTask = Get-DotsCoordinatorTask -TaskName $script:DotsLiveCoordinatorTaskName
        $coordinatorTriggers = @()
        if ($null -ne $coordinatorTask) { $coordinatorTriggers = @($coordinatorTask.Triggers) }
        $identitySid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $actionCount = if ($null -eq $coordinatorTask) { 0 } else { @($coordinatorTask.Actions).Count }
        if ($null -eq $coordinatorTask -or $actionCount -ne 1 -or $coordinatorTriggers.Count -ne 1) {
            throw ('The registered coordinator task shape was present={0}, actions={1}, triggers={2}' -f ($null -ne $coordinatorTask), $actionCount, $coordinatorTriggers.Count)
        }
        $validation = [ordered]@{
            execute = ([string]$coordinatorTask.Actions[0].Execute -ieq $powershell)
            arguments = ([string]$coordinatorTask.Actions[0].Arguments -ceq $arguments)
            working_directory = ([string]$coordinatorTask.Actions[0].WorkingDirectory -ceq $PSScriptRoot)
            trigger_type = ([string]$coordinatorTriggers[0].CimClass.CimClassName -ceq 'MSFT_TaskLogonTrigger')
            trigger_user = ((Resolve-DotsCoordinatorSid -AccountName ([string]$coordinatorTriggers[0].UserId)) -ceq $identitySid)
            principal_user = ((Resolve-DotsCoordinatorSid -AccountName ([string]$coordinatorTask.Principal.UserId)) -ceq $identitySid)
            logon_type = ([string]$coordinatorTask.Principal.LogonType -ceq 'Interactive')
            run_level = ([string]$coordinatorTask.Principal.RunLevel -ceq 'Limited')
            trigger_enabled = [bool]$coordinatorTriggers[0].Enabled
            task_enabled = [bool]$coordinatorTask.Settings.Enabled
            hidden = [bool]$coordinatorTask.Settings.Hidden
            multiple_instances = ([string]$coordinatorTask.Settings.MultipleInstances -ceq 'IgnoreNew')
            time_limit = ((Convert-DotsTaskExecutionTimeLimit -Value $coordinatorTask.Settings.ExecutionTimeLimit) -eq [TimeSpan]::FromMinutes(3))
        }
        $invalid = @($validation.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key })
        if ($invalid.Count -gt 0) {
            $migrationPhase = 'validate_coordinator_' + ($invalid -join '_')
            throw ('The registered coordinator task did not match its definition: {0}' -f ($invalid -join ', '))
        }
        return [pscustomobject]@{ Registered = $true; TaskName = $script:DotsLiveCoordinatorTaskName; BackupDirectory = $backupDirectory; BackupFiles = @($databaseBackup, $mcpBackup); LegacyTaskNames = @($script:DotsLiveDatabaseTaskName, $script:DotsLiveMcpTaskName) }
    }
    catch {
        $validationDetail = if ($migrationPhase -eq 'validate_coordinator') { $_.Exception.Message } else { '' }
        $rollbackFailures = @()
        foreach ($legacyName in @($script:DotsLiveDatabaseTaskName, $script:DotsLiveMcpTaskName)) {
            try {
                $legacy = Get-DotsCoordinatorTask -TaskName $legacyName
                if ($null -ne $legacy -and -not [bool]$legacy.Settings.Enabled) { Enable-DotsCoordinatorTask -TaskName $legacyName }
            }
            catch { $rollbackFailures += $legacyName }
        }
        if ($registered) {
            try { Remove-DotsCoordinatorTask -TaskName $script:DotsLiveCoordinatorTaskName }
            catch { $rollbackFailures += $script:DotsLiveCoordinatorTaskName }
        }
        if ($rollbackFailures.Count -gt 0) {
            throw ('Coordinator migration failed during {0} and automatic rollback needs attention for: {1}. Original XML backups: {2}' -f $migrationPhase, ($rollbackFailures -join ', '), $backupDirectory)
        }
        if ($validationDetail) {
            throw ('Coordinator migration failed during {0}: {1}. The existing tasks were restored. Original XML backups: {2}' -f $migrationPhase, $validationDetail, $backupDirectory)
        }
        throw ('Coordinator migration failed during {0}; the existing tasks were restored. Original XML backups: {1}' -f $migrationPhase, $backupDirectory)
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $result = Register-DotsLiveCoordinatorTask -BackupRoot $BackupRoot -BackupOnly:$BackupOnly
    if ($result.BackupOnly -and $result.Blocked) {
        Write-Output "No scheduled task was changed. Control-service startup is not yet ready; verified task XML backups are in: $($result.BackupDirectory)"
    }
    elseif ($result.BackupOnly) {
        Write-Output "No scheduled task was changed. Verified task XML backups are in: $($result.BackupDirectory)"
    }
    elseif ($result.WhatIf) {
        Write-Output "No scheduled task was changed and no backup files were written. Verified task names: $($result.LegacyTaskNames -join ', ')"
    }
    elseif ($result.Blocked) {
        Write-Output "No scheduled task was changed. Verified existing task definitions: $($result.LegacyTaskNames -join ', '). Control-service startup is not yet ready; XML backups are in: $($result.BackupDirectory)"
    }
    elseif ($result.WhatIf) {
        Write-Output "No scheduled task was changed. Verified existing task definitions: $($result.LegacyTaskNames -join ', '). XML backups: $($result.BackupDirectory)"
    }
    else {
        Write-Output "Registered the single hidden current-user live coordinator. Replaced task definitions: $($result.LegacyTaskNames -join ', '). Verified rollback XML is in: $($result.BackupDirectory)"
    }
}
