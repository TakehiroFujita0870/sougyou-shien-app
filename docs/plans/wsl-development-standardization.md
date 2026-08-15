# WSL開発環境の標準化 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: WSL2をDots.の主要開発環境として標準化する。

ゴール: Windows版Codexの利用者が、Windowsの制御操作とWSL内の開発実行を分けて、安全に再現できる運用手順を提供する。

成功指標: 手順だけでLinux native clone、依存同期、検査、Vite/FastAPIの起動・停止・ログ確認、WindowsからのHTTP確認を実行できる。

## ユーザーストーリーと受け入れ条件

### US-1

As a Windows版Codexを使う開発者, I want WSLを実行環境として選択する, so that LinuxとCIに近い環境で開発できる。

Given: 新規作業を開始する開発者がいる
When: `AGENTS.md`とWSL手順を読む
Then: PowerShellをWindows制御面、WSLをNode・uv・FastAPI・Vite・SQLの実行面として選べる記載がある

### US-2

As a リポジトリを同期する開発者, I want Linux native cloneだけに依存を置く, so that OneDriveと`/mnt/c`のファイルI/O差異を回避できる。

Given: WSLで依存同期を行う
When: cloneと`npm ci`または`uv sync`を実行する
Then: `/home/<user>/projects`配下にclone、`node_modules`、`.venv`を置き、`/mnt/c`とOneDriveに生成しない手順がある

### US-3

As a UI/APIを確認する開発者, I want 常駐プロセスを観測して停止する, so that ポート競合を切り分けられる。

Given: ViteとFastAPIを起動する
When: systemd user unitの状態、ログ、ポート、HTTP応答を確認する
Then: 起動、状態、ログ、停止、Windows HTTP確認のコマンドが記載される

### US-4

As a WindowsとWSLを併用する開発者, I want Gitで同期する, so that ファイルコピーによる履歴分岐を避けられる。

Given: 二つのcloneの状態が異なる
When: WSL側で最新mainを取得して作業branchを作る
Then: `fetch`、`pull --ff-only`、branch、PRを使い、mainへ直接pushしない手順がある

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-1 | 永続的なsystemd unitをリポジトリ外で標準配布するか | プロダクト責任者 | 別Issue作成前 |

## スコープ外

- Docker Desktop、Supabase、外部API、GitHub認証の新規設定
- Windows側cloneまたはPowerShell安全規約の削除
- WSL distributionの削除、再作成、自動更新
- アプリケーションコード、依存関係、CI設定の変更

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | WSL運用手順 | 検査: 文書内の起動・HTTP・停止コマンドをWSL/Windowsで実行 | 既知 |
| T-2 | エージェント向け参照規則 | 検査: `AGENTS.md`から運用手順へ到達できる | 既知 |
| T-3 | 計画文書 | 検査: planning Exit Criteriaの検索と表レビュー | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 実行環境 | WSL内のLinux native cloneを主要環境にする。Linux CIとファイルシステム挙動を揃えられる。 | `/mnt/c`またはOneDriveのWindows cloneで依存を実行する案は、性能と権限差異があるため却下。 | 採用 |
| 開発サーバー | systemd userのtransient unitを開発時の起動例にする。PIDファイルを手動管理せず状態とログを取得できる。 | 常駐シェルだけでの起動は観測と停止が一貫しないため却下。 | 採用 |
| 同期手段 | Gitのfetch、fast-forward、branch、PRを使う。履歴とレビューを保持できる。 | clone間のファイルコピーは未追跡物と履歴分岐を招くため却下。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | Issue #45の受入条件を実行可能な手順へ分解 | T-1, T-2, T-3 |
