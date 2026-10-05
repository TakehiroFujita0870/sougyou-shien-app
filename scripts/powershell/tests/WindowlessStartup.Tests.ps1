Describe 'Windowless startup launcher' {
    $source = Join-Path (Split-Path $PSScriptRoot -Parent) 'NebulaStartupLauncher.cs'
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    $executable = Join-Path $TestDrive 'launcher.exe'
    & $compiler /nologo /target:winexe "/out:$executable" $source
    if ($LASTEXITCODE -ne 0) { throw 'Launcher did not compile.' }

    function Invoke-TestLauncher([string]$Arguments) {
        $info = New-Object Diagnostics.ProcessStartInfo
        $info.FileName = $executable
        $info.Arguments = $Arguments
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $process = [Diagnostics.Process]::Start($info)
        try {
            if (-not $process.WaitForExit(10000)) { $process.Kill(); throw 'Launcher timed out.' }
            return $process.ExitCode
        } finally { $process.Dispose() }
    }

    It 'is a GUI executable rather than a console executable' {
        $bytes = [IO.File]::ReadAllBytes($executable)
        $header = [BitConverter]::ToInt32($bytes, 60)
        [BitConverter]::ToUInt16($bytes, $header + 24 + 68) | Should Be 2
    }
    It 'rejects missing arguments and unapproved or relative script paths' {
        (Invoke-TestLauncher '') | Should Be 64
        (Invoke-TestLauncher 'relative.ps1') | Should Be 64
        (Invoke-TestLauncher '"C:\Windows\not-coordinator.ps1"') | Should Be 64
    }
    It 'handles a path with spaces and propagates the child exit code' {
        $fixtureDirectory = Join-Path $TestDrive 'path with spaces'
        New-Item -ItemType Directory -Path $fixtureDirectory | Out-Null
        $fixture = Join-Path $fixtureDirectory 'Start-NebulaLiveCoordinatorAtLogon.ps1'
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'fixtures\coordinator-exit.ps1') -Destination $fixture
        (Invoke-TestLauncher ('"{0}"' -f $fixture)) | Should Be 17
    }
}
