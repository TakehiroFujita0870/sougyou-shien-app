[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$LiteralPath
)

function Assert-RegularSecretFile {
    param([string]$Path)

    try {
        $isFile = Test-Path -LiteralPath $Path -PathType Leaf -ErrorAction Stop
    }
    catch {
        throw 'Secret path could not be validated.'
    }

    if (-not $isFile) {
        throw 'Secret path must refer to an existing file.'
    }

    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    }
    catch {
        throw 'Secret file metadata could not be inspected.'
    }

    Assert-RegularSecretFileMetadata -Item $item
}

function Assert-RegularSecretFileMetadata {
    param([object]$Item)

    if ($Item.PSIsContainer) {
        throw 'Secret path must refer to a file, not a directory.'
    }

    if (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Secret path must not be a reparse point.'
    }
}

function Test-ExactSecretAcl {
    param(
        [object]$Acl,
        [string[]]$AllowedSidValues
    )

    if (-not $Acl.AreAccessRulesProtected) {
        return $false
    }

    $rules = @(
        $Acl.GetAccessRules(
            $true,
            $true,
            [System.Security.Principal.SecurityIdentifier]
        )
    )

    if ($rules.Count -ne $AllowedSidValues.Count) {
        return $false
    }

    foreach ($rule in $rules) {
        if (
            $AllowedSidValues -notcontains $rule.IdentityReference.Value -or
            $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
            $rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl -or
            $rule.IsInherited -or
            $rule.InheritanceFlags -ne [System.Security.AccessControl.InheritanceFlags]::None -or
            $rule.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None
        ) {
            return $false
        }
    }

    foreach ($sidValue in $AllowedSidValues) {
        $matchingRules = @($rules | Where-Object { $_.IdentityReference.Value -eq $sidValue })
        if ($matchingRules.Count -ne 1) {
            return $false
        }
    }

    return $true
}

function Protect-DotsSecretFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [ValidateNotNullOrEmpty()]
        [string]$LiteralPath
    )

    $ErrorActionPreference = 'Stop'

    if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
        throw 'Secret-file ACL protection is supported only on Windows.'
    }

    Assert-RegularSecretFile -Path $LiteralPath

    try {
        $acl = Get-Acl -LiteralPath $LiteralPath -ErrorAction Stop
    }
    catch {
        throw 'Secret-file ACL could not be inspected.'
    }

    try {
        $currentUserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
        if ($null -eq $currentUserSid) {
            throw 'Current Windows user SID is unavailable.'
        }

        $principalsBySid = @{ $currentUserSid.Value = $currentUserSid }
        $expectedSidValues = @($currentUserSid.Value)
        if (Test-ExactSecretAcl -Acl $acl -AllowedSidValues $expectedSidValues) {
            return $true
        }

        # Remove inherited permissions and every previous explicit rule, including denies.
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($existingRule in @($acl.Access)) {
            [void]$acl.RemoveAccessRuleSpecific($existingRule)
        }

        foreach ($principal in $principalsBySid.Values) {
            $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
                $principal,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                [System.Security.AccessControl.AccessControlType]::Allow
            )
            [void]$acl.AddAccessRule($rule)
        }
    }
    catch {
        throw 'Secret-file ACL could not be prepared.'
    }

    # Recheck the path immediately before applying the ACL so links and directories are refused.
    Assert-RegularSecretFile -Path $LiteralPath

    try {
        Set-Acl -LiteralPath $LiteralPath -AclObject $acl -ErrorAction Stop
        $verifiedAcl = Get-Acl -LiteralPath $LiteralPath -ErrorAction Stop
    }
    catch {
        throw 'Secret-file ACL could not be applied or verified.'
    }

    if (-not $verifiedAcl.AreAccessRulesProtected) {
        throw 'Secret-file ACL inheritance remains enabled.'
    }

    if (-not (Test-ExactSecretAcl -Acl $verifiedAcl -AllowedSidValues $expectedSidValues)) {
        throw 'Secret-file ACL contains unexpected access rules.'
    }

    # Return a path-free success value. File contents are never opened or emitted.
    return $true
}

if ($MyInvocation.InvocationName -ne '.') {
    if ([string]::IsNullOrWhiteSpace($LiteralPath)) {
        throw 'A secret file path is required.'
    }

    Protect-DotsSecretFile -LiteralPath $LiteralPath
}
