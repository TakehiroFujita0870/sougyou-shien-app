"""Cross-platform guard for the Windows scheduler action's launch contract."""
from pathlib import Path


def test_windowless_scheduler_does_not_use_wsl_unc_working_directory():
    root = Path(__file__).resolve().parents[2]
    source = (root / "scripts/powershell/Set-NebulaWindowlessTask.ps1").read_text()
    action = next(line for line in source.splitlines() if line.startswith("$action = New-ScheduledTaskAction"))
    assert "-WorkingDirectory" not in action
    assert "/target:winexe" in source
    assert "Save-NebulaCoordinatorTaskBackup" in source
    assert "Resolve-NebulaCoordinatorSid" in source
    assert "Join-Path $env:USERPROFILE '.local" in source
    assert "$newXml.Task.Actions.InnerXml = $oldXml.Task.Actions.InnerXml" in source
    launcher = (root / "scripts/powershell/NebulaStartupLauncher.cs").read_text()
    assert "CreateNoWindow = true" in launcher
    assert "UseShellExecute = false" in launcher
    assert "return process.ExitCode" in launcher
