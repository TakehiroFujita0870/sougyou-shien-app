# Issue #83 Git line-ending policy plan

Last verified: 2026-08-09

## Request / goal / success criteria

### Original request

> Stop Git CRLF warnings at their cause so they do not keep consuming context, and define a durable repository policy.

### Goal

Make `.gitattributes` the repository source of truth: normal text is stored and checked out as LF, while Windows batch files use CRLF. Document how to verify the policy without changing the current tracked files' contents.

### Success criteria

- `git check-attr` reports `text: auto` and `eol: lf` for representative source, documentation, workflow, and PowerShell paths.
- `git check-attr` reports `text: set` and `eol: crlf` for representative `.bat` and `.cmd` paths.
- `git ls-files --eol` confirms a representative existing tracked source file remains `i/lf`; this change does not run `git add --renormalize` or modify all existing files.

## User stories and acceptance criteria

### US-1 Keep ordinary repository text portable

As a repository contributor, I want ordinary tracked text to use LF, so that Windows and Linux contributors share one line-ending contract.

Given: a tracked JavaScript, Markdown, YAML, or PowerShell file
When: Git evaluates its attributes
Then: the file has `text=auto` and `eol=lf`

### US-2 Preserve Windows batch compatibility

As a Windows maintainer, I want batch command files to use CRLF, so that cmd.exe scripts retain their required convention.

Given: a path ending in `.bat` or `.cmd`
When: Git evaluates its attributes
Then: the path has `text` set and `eol=crlf`

### US-3 Avoid an unrelated mass rewrite

As a reviewer, I want this policy introduced without renormalizing existing tracked content, so that the change stays reviewable and does not alter Japanese document encoding.

Given: the Issue #83 change set
When: I inspect the diff and line-ending report
Then: it contains only the attribute file and documentation, and representative tracked files still report `i/lf`

## Questions

| ID | Question | Decision maker | Deadline |
| --- | --- | --- | --- |
| Q-83-01 | When should existing worktrees be renormalized after this policy is merged? | Repository maintainer | Before a separately planned mass-normalization PR |

## Out of scope

- Running `git add --renormalize .`, changing all existing files, or changing their Japanese text encoding.
- Changing user, system, or repository `core.autocrlf` configuration to hide warnings.
- Adding binary patterns when the repository has no tracked binary assets that need an override.
- Changing application behavior, dependencies, CI runners, or GitHub settings.

## Tasks

| ID | Deliverable | Completion criterion (check:) | Uncertainty |
| --- | --- | --- | --- |
| T-83-01 | `.gitattributes` policy | Check: `git check-attr text eol -- src/App.jsx docs/operations/windows-powershell.md .github/workflows/ci.yml scripts/powershell/Initialize-Utf8Preflight.ps1 sample.bat sample.cmd` reports LF for ordinary text and CRLF for batch paths | Known |
| T-83-02 | Operations guidance | Check: `rg -n "gitattributes|check-attr|ls-files --eol|renormalize" docs/operations/git-line-endings.md` finds the verification and scope boundary | Known |
| T-83-03 | Policy acceptance evidence | Check: `git ls-files --eol -- src/App.jsx` and `git diff --check` succeed without a mass-renormalization diff | Known |

## ADR

| Decision | Choice and reason | Rejected option and reason | Result |
| --- | --- | --- | --- |
| Source of truth | Commit `.gitattributes` with `* text=auto eol=lf`, then narrowly override `.bat` and `.cmd` to CRLF. Attributes travel with the repository and apply consistently across clones. | Suppressing warnings through `core.autocrlf`, `core.safecrlf`, or command flags only changes a local Git client's behavior; it leaves the repository contract undefined and can hide inconsistent checkout behavior. | Accepted |
| Binary handling | Rely on `text=auto` detection and add no binary exception now because no tracked binary assets require one. Add a minimal `-text` rule only when a binary format is introduced. | A broad list of speculative binary extensions creates policy that cannot be verified against this repository and can accidentally classify future text assets incorrectly. | Accepted |
| Migration scope | Introduce attributes and verification only; schedule any `git add --renormalize .` in a dedicated reviewable change. | Renormalizing every tracked file here would create an unrelated large diff and risks obscuring Japanese encoding changes. | Accepted |

## Change history

| Date | Change | Reason | Affected tasks |
| --- | --- | --- | --- |
| 2026-08-09 | Initial plan | Translate Issue #83 into verifiable line-ending policy work | T-83-01 to T-83-03 |
