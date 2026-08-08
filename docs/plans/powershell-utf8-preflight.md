# PowerShell UTF-8 preflight 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

### 要望原文

> PowerShellセッションのUTF-8初期化と安全な自己診断を再利用可能なスクリプトにし、エージェントごとの手入力漏れを防ぐ。

### ゴール

Windows PowerShell 5.1でdot-sourceできる冪等なpreflightを提供し、UTF-8状態と日本語パスのNode/Python読取を外部書込なしで検査する。

### 成功指標

- 新規プロセスでdot-source後、Console Input/Output、OutputEncoding、PYTHONIOENCODINGがUTF-8 BOMなしになる。
- 日本語パスのfixtureをNode/Pythonで読み、PowerShell読取値と完全一致する。
- 未初期化または不正な状態の安全検査は非ゼロ終了する。

## ユーザーストーリーと受け入れ条件

### US-1 セッションを初期化する

As a Windows版Codexの担当者, I want preflightをdot-sourceしたい, so that PowerShellの文字コード設定を毎回そろえられる。

Given: 新しいWindows PowerShell 5.1プロセスがある
When: Initialize-Utf8Preflight.ps1をdot-sourceする
Then: Console Input/Output、OutputEncodingがBOMなしUTF-8になり、PYTHONIOENCODINGがutf-8になる

### US-2 日本語パスを自己診断する

As a Windows版Codexの担当者, I want NodeとPythonでUTF-8 fixtureを読取検査したい, so that 日本語を含む作業パスでの読取欠損を検出できる。

Given: 日本語を含むUTF-8 fixtureの絶対パスがある
When: preflight後に読取自己診断を実行する
Then: PowerShell、Node、Pythonの読取値が完全一致し、fixtureを変更しない

### US-3 未初期化を停止する

As a Windows版Codexの担当者, I want safety checkで未初期化を検出したい, so that 非ASCII本文をnative CLIへ送る前に停止できる。

Given: preflightを実行していないプロセスまたは不正なencoding状態がある
When: Initialize-Utf8Preflight.ps1を`-Check`付きで実行する
Then: 非ゼロ終了し、native CLI更新を開始しない

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-48-01 | 実接続したGitHub本文更新をpreflightの必須CIにする時期 | CEO | GitHub運用自動化の計画前 |

## スコープ外

- PowerShell profile、レジストリ、PATH、認証、WSL、Node、Pythonの変更。
- 日本語本文のPowerShell直接パイプ送信。
- 外部サービス、GitHub、ファイル内容への書込み。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-48-01 | 失敗経路を含むWindows PowerShell 5.1検査 | 検査: 未初期化checkが非ゼロ、dot-source後のcheckとread-backが成功する | 既知 |
| T-48-02 | 冪等なpreflight、safety check、日本語fixture | 検査: PowerShell 5.1でConsole設定とNode/Python完全一致を実測する | 類推可能 |
| T-48-03 | AGENTSと運用文書からの利用法参照 | 検査: `rg -n "Initialize-Utf8Preflight|Test-Utf8Preflight" AGENTS.md docs/operations/windows-powershell.md` | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 初期化の保存範囲 | ConsoleとProcess環境変数だけを設定する。OS全体へ変更を残さない | profile、レジストリ、PATHの更新は利用者環境を恒久変更するため却下 | 採用 |
| 本文送信 | UTF-8ファイルまたはNode Bufferとread-back完全一致を維持する | OutputEncodingだけ、または日本語本文の直接パイプは経路全体を保証しないため却下 | 採用 |
| 自己診断 | 既存UTF-8 fixtureの読取比較のみを行う | 一時ファイルを書いて検査する案は外部書込なしの要件に反するため却下 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版を作成 | Issue #48の受入条件を実装可能な形へ分解 | T-48-01からT-48-03 |
