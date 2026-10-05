using System;
using System.Diagnostics;
using System.IO;

// Build as winexe: allocating a console before PowerShell hides it can flash Terminal.
internal static class NebulaStartupLauncher
{
    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            if (args.Length != 1 || args[0].IndexOfAny(new[] { '"', '\r', '\n', '\0' }) >= 0)
                return 64;
            var script = Path.GetFullPath(args[0]);
            if (!Path.IsPathRooted(args[0]) || !File.Exists(script) ||
                !String.Equals(Path.GetFileName(script), "Start-NebulaLiveCoordinatorAtLogon.ps1", StringComparison.OrdinalIgnoreCase))
                return 64;
            var start = new ProcessStartInfo
            {
                FileName = Path.Combine(Environment.SystemDirectory, @"WindowsPowerShell\v1.0\powershell.exe"),
                Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + script + "\"",
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            using (var process = Process.Start(start))
            {
                if (process == null) return 127;
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch { return 127; } // No script paths, command arguments or secrets in console output.
    }
}
