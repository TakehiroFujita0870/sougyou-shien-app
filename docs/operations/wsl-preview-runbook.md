# WSL preview runbook

最終検証日: 2026-08-09

## 接続先

- Kadodeアプリ: `http://localhost:5174/`
- Storybook: `http://localhost:6006/`
- ローカルAPIヘルスチェック: `http://localhost:8000/health`

このrunbookのpreviewスクリプトが起動するのはアプリとAPIである。Storybookは同じclone/worktreeで`npm run storybook`を別プロセスとして実行し、アプリと同じ変更内容を確認する。

WSL clone、依存同期、systemd前提は[WSL開発環境](wsl-development.md)、PowerShellのUTF-8規約は[Windows / PowerShell](windows-powershell.md)を正本とする。この文書はpreviewのstart/status/stopだけを定める。

## 前提

- cloneはWSL Linux filesystemにあり、`/mnt/c`ではない。
- clone内の`node_modules`と`.venv`はWSL側だけにある。
- 5174と8000に既存listen processがなく、既存preview state recordがない。
- PowerShellでUTF-8 preflightを完了している。

```powershell
. .\scripts\powershell\Initialize-Utf8Preflight.ps1
if (-not (Test-Utf8Preflight)) { throw 'UTF-8 preflight failed' }
```

## 開始

`Distribution`、`User`、`ClonePath`は実在するWSL native cloneに置き換える。scriptはclone欠落、`/mnt/c`、port競合、二重起動で非ゼロ終了し、既存processを停止しない。

```powershell
.\scripts\powershell\Start-WslPreview.ps1 -Distribution Ubuntu -User <user> -ClonePath /home/<user>/projects/sougyou-shien-app
```

Viteは5174、APIは8000でhidden wsl.exeからtransient user unitとして開始する。開始後60秒待機し、Windowsから`http://localhost:5174/`と`http://localhost:8000/health`が200であることを確認する。

起動後にAPI失敗またはsmoke失敗が起きた場合、scriptはそのrunが起動したunit、記録済みhost PID、stateだけをcleanupして非ゼロ終了する。既存stateやport所有者には触れない。

## 状態

```powershell
.\scripts\powershell\Get-WslPreviewStatus.ps1
```

出力はstate recordにあるWindows host PID、Linux MainPID、5174/8000のlisten状態、Windows localhost UI/API HTTPを示す。state recordがない場合は非ゼロ終了する。

## 停止

```powershell
.\scripts\powershell\Stop-WslPreview.ps1
```

停止対象はstate recordに記録されたVite/API unitと、存在する記録済みWindows host PIDだけである。portだけを根拠にkillせず、WSL全体を停止しない。recordがない場合は非ゼロ終了する。

## 失敗時

- clone欠落、`/mnt/c`、port競合、二重起動: 出力を確認し、既存processへ作用せず終了する。
- 60秒後にHTTP 200でない: statusを取り、記録済みunitのjournalを確認する。広範なkillは行わない。
- WSL cloneまたはsystemd userがない: [WSL開発環境](wsl-development.md)の初回確認へ戻る。Windows cloneへ依存を作らない。
