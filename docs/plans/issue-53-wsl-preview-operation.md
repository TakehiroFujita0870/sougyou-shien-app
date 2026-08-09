# Issue #53 WSL preview 運用計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: WSL native cloneでUI 5174とAPI 8000を安全にstart/status/stopし、Windowsから60秒以上のUI/API smokeを確認する。

ゴール: 記録済みunitとPIDだけを操作し、clone欠落、port競合、二重起動で既存processを壊さず非ゼロ終了する。

成功指標: statusがWindows host PID、Linux MainPID、listen port、HTTP状態を表示し、UIと`/health`が60秒後も200になる。

## ユーザーストーリーと受け入れ条件

### US-53-1

As a 開発者, I want WSL native cloneでpreviewを開始したい, so that Windows browserからlocal UIとAPIを確認できる。

Given: UTF-8 preflight済みで、/mnt/c外のcloneと空きport 5174/8000がある
When: `Start-WslPreview.ps1`を実行する
Then: hidden wsl.exeから記録済みのVite/API unitを開始し、60秒後にWindows localhost UIとAPI healthが200であることを確認する。

### US-53-2

As a 開発者, I want preview状態を安全に見たい, so that 停止対象を誤らない。

Given: preview state recordがある
When: `Get-WslPreviewStatus.ps1`を実行する
Then: Windows host PID、Linux MainPID、5174/8000 listen状態、UI/API HTTP状態が表示される。

### US-53-3

As a 開発者, I want 自分が開始したpreviewだけを停止したい, so that 他作業のprocessを止めない。

Given: state recordにunit名とhost PIDが記録されている
When: `Stop-WslPreview.ps1`を実行する
Then: 記録済みunitと存在する記録PIDだけを停止し、recordを削除する。

### US-53-4

As a 共有環境利用者, I want 競合時に安全に失敗したい, so that 稼働中previewを失わない。

Given: clone欠落、/mnt/c clone、port競合、またはstate recordがある
When: startを実行する
Then: 非ゼロ終了し、systemctl stop、kill、WSL全体停止を実行しない。起動後の失敗はそのrunが記録したunit/PID/stateだけをcleanupする。

## スコープ外

- App.jsx、WorkspaceShell、auth、runtime UI、API実装、secret、実サービス接続。
- /mnt/cへのnode_modulesまたは.venv作成、WSL全体停止、広範なprocess kill。
- 既存`wsl-development.md`と`windows-powershell.md`の手順本文の複製。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-53-1 | start/status/stop PowerShell scripts | 検査: `scripts/powershell/Test-WslPreviewScripts.ps1` が成功し、startのtry/finally失敗cleanup構造を検査 | 類推可能 |
| T-53-2 | runbook | 検査: required command名、60秒、ports、fail-safeを`rg`で確認 | 既知 |
| T-53-3 | native WSL smoke | 検査: 実行環境がある場合にstart後60秒でlocalhost 200。未実行時は理由をPRへ記載 | 未知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-53-1: process所有 | state recordのunit名とWindows host PIDだけをstop対象にする。 | port所有者をkillする案は他作業を壊すため却下。 | 採用 |
| ADR-53-2: WSL起動 | systemd user transient unitをhidden wsl.exe経由で開始する。 | /mnt/c cloneまたは永続unit配布は正本と矛盾するため却下。 | 採用 |
| ADR-53-3: 実行検証 | script構造テストをCIで実行し、native smokeはWSL cloneが存在する実行者だけが行う。 | CIでWSLを仮定する案はrunner依存のため却下。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | Issue #53の安全なpreview運用を定義 | T-53-1〜3 |
| 2026-08-09 | 起動後失敗のcleanupを追加 | state/unit/PIDの残留で次回startが永久拒否される問題を防止 | T-53-1 |
