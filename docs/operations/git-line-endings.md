# Git line-ending policy

Last verified: 2026-08-09

## Source of truth

`.gitattributes` defines the repository line-ending contract. Ordinary text, including PowerShell, JavaScript, TypeScript, JSX, Python, Markdown, YAML, TOML, JSON, CSS, HTML, and Shell, uses LF. Only `.bat` and `.cmd` use CRLF for `cmd.exe` compatibility.

`core.autocrlf`, `core.safecrlf`, and command-specific configuration are local Git preferences, not a substitute for the committed contract. Do not use them solely to suppress warnings.

The repository currently has no tracked binary assets requiring an explicit `-text` override. When one is added, add the smallest verified binary rule in the same change.

## Verification

Run these from the repository root after changing attributes or investigating line-ending warnings:

```powershell
git check-attr text eol -- src/App.jsx docs/operations/windows-powershell.md .github/workflows/ci.yml scripts/powershell/Initialize-Utf8Preflight.ps1 sample.bat sample.cmd
git ls-files --eol -- src/App.jsx docs/operations/windows-powershell.md
git diff --check
```

Expected attributes are `text: auto` and `eol: lf` for the four existing text paths, then `text: set` and `eol: crlf` for `sample.bat` and `sample.cmd`. The latter paths are attribute probes; they do not need to be committed files.

## Migration boundary

Do not combine policy introduction with `git add --renormalize .`. A future normalization must be a dedicated, reviewed change after verifying its diff and preserving Japanese document encoding. This policy makes new checkouts deterministic; it intentionally leaves existing tracked content unchanged in Issue #83.
