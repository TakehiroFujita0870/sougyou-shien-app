$script:protectScript = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot '..\Protect-DotsSecretFile.ps1')
)
. $script:protectScript

Describe 'Protect-DotsSecretFile.ps1' {
    BeforeEach {
        $script:syntheticSecretPath = Join-Path $TestDrive 'synthetic-secret.txt'
        [System.IO.File]::WriteAllText($script:syntheticSecretPath, 'synthetic-secret-bytes-only')
    }

    It 'protects a synthetic file for the current user only' {
        $result = Protect-DotsSecretFile -LiteralPath $script:syntheticSecretPath
        $result | Should Be $true

        $acl = Get-Acl -LiteralPath $script:syntheticSecretPath
        $acl.AreAccessRulesProtected | Should Be $true

        $rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
        $currentUserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $expectedSidValues = @($currentUserSid)

        $rules.Count | Should Be $expectedSidValues.Count
        foreach ($sidValue in $expectedSidValues) {
            $matchingRules = @($rules | Where-Object { $_.IdentityReference.Value -eq $sidValue })
            $matchingRules.Count | Should Be 1
            $matchingRules[0].AccessControlType | Should Be ([System.Security.AccessControl.AccessControlType]::Allow)
            $matchingRules[0].FileSystemRights | Should Be ([System.Security.AccessControl.FileSystemRights]::FullControl)
            $matchingRules[0].IsInherited | Should Be $false
        }
    }

    It 'is idempotent' {
        $null = Protect-DotsSecretFile -LiteralPath $script:syntheticSecretPath
        $firstAcl = Get-Acl -LiteralPath $script:syntheticSecretPath
        $firstSignature = @(
            $firstAcl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]) |
                ForEach-Object {
                    '{0}|{1}|{2}|{3}|{4}' -f $_.IdentityReference.Value, $_.AccessControlType,
                    $_.FileSystemRights, $_.IsInherited, $_.InheritanceFlags
                } | Sort-Object
        ) -join "`n"

        $null = Protect-DotsSecretFile -LiteralPath $script:syntheticSecretPath
        $secondAcl = Get-Acl -LiteralPath $script:syntheticSecretPath
        $secondSignature = @(
            $secondAcl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]) |
                ForEach-Object {
                    '{0}|{1}|{2}|{3}|{4}' -f $_.IdentityReference.Value, $_.AccessControlType,
                    $_.FileSystemRights, $_.IsInherited, $_.InheritanceFlags
                } | Sort-Object
        ) -join "`n"

        $secondAcl.AreAccessRulesProtected | Should Be $true
        $secondSignature | Should Be $firstSignature
    }

    It 'rejects a missing file' {
        $missingPath = Join-Path $TestDrive 'missing-secret.txt'
        $didThrow = $false
        try {
            Protect-DotsSecretFile -LiteralPath $missingPath
        }
        catch {
            $didThrow = $true
        }
        $didThrow | Should Be $true
    }

    It 'rejects a directory' {
        $directoryPath = Join-Path $TestDrive 'synthetic-directory'
        [void][System.IO.Directory]::CreateDirectory($directoryPath)

        $didThrow = $false
        try {
            Protect-DotsSecretFile -LiteralPath $directoryPath
        }
        catch {
            $didThrow = $true
        }
        $didThrow | Should Be $true
    }

    It 'rejects reparse-point metadata' {
        Mock Get-Item {
            [pscustomobject]@{
                PSIsContainer = $false
                Attributes = [System.IO.FileAttributes]::ReparsePoint
            }
        } -ParameterFilter { $LiteralPath -eq $script:syntheticSecretPath }

        $didThrow = $false
        try {
            Protect-DotsSecretFile -LiteralPath $script:syntheticSecretPath
        }
        catch {
            $didThrow = $true
        }
        $didThrow | Should Be $true
        Assert-MockCalled Get-Item -Times 1 -Exactly -ParameterFilter {
            $LiteralPath -eq $script:syntheticSecretPath
        }
    }

    It 'does not display the synthetic file path or bytes' {
        $output = @(& $script:protectScript -LiteralPath $script:syntheticSecretPath)
        $outputText = [string]::Join([System.Environment]::NewLine, [string[]]$output)

        $output.Count | Should Be 1
        $output[0] | Should Be $true
        $outputText.Contains($script:syntheticSecretPath) | Should Be $false
        $outputText.Contains('synthetic-secret-bytes-only') | Should Be $false
    }
}
