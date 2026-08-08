# Windows / PowerShell 安全運用 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: Windows版CodexでPowerShellを標準シェルとして使い、パス、文字コード、CLI引数、ファイル操作、GitHub CLIを安全に扱う規約を整備する。

ゴール: 新しい担当者が、文書だけで日本語を含むGitHub本文を欠損・文字化けなく更新し、検証失敗時に後続作業を停止できる。

成功指標: `AGENTS.md`の必須規約、実行可能な運用手順、`git diff --check`が揃う。

## ユーザーストーリーと受け入れ条件

### US-1

As a Windows版Codexの担当者, I want PowerShellから日本語を含む本文を安全にGitHubへ渡す, so that 文字化けや指示欠損を防げる。

Given: 日本語・複数行のIssue/PR本文を更新する必要がある。
When: UTF-8初期化後にUTF-8ファイルまたはNode.js Buffer経路を使用する。
Then: 直接パイプを使わず、read-back本文が送信元本文と一致することを確認できる。

### US-2

As a Windows版Codexの担当者, I want 送信失敗を完了扱いにしない, so that 壊れた本文のまま次工程へ進まない。

Given: API read-backで文字化け、必須見出し不足、または本文不一致が検出される。
When: 検査コマンドを実行する。
Then: 非ゼロ終了し、更新作業を停止して復旧・再送信が必要だと分かる。

### US-3

As a 新しい担当者, I want PowerShellの安全規約を参照する, so that パスや破壊操作の事故を避けられる。

Given: OneDrive、日本語、空白を含む作業パスがある。
When: `AGENTS.md`から運用文書を開く。
Then: 検索、読取、編集、CLI診断、CI差分の手順を確認できる。

## 質問リスト

該当なし。

## スコープ外

- OS設定、PATH、GitHub認証情報、既定シェルの変更。
- アプリ機能、依存関係、CIランナーの変更。
- `docs/inherited/`の変更。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | `AGENTS.md`の短い必須規約と運用文書リンク | 検査: `rg -n "windows-powershell" AGENTS.md` | 既知 |
| T-2 | UTF-8初期化、安全な送信経路、完全一致read-back、停止条件を含む運用文書 | 検査: `rg -n "UTF-8初期化|完全一致|停止" docs/operations/windows-powershell.md` | 既知 |
| T-3 | 文書差分の整合性確認 | 検査: `git diff --check` | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 非ASCII本文の送信 | UTF-8ファイルまたはNode.jsのUTF-8 Bufferを使用する。PowerShellのパイプ変換に依存しない。 | `$OutputEncoding`設定だけ、またはPowerShellからの直接パイプ。プロセス差で`?`置換を防げない。 | 採用 |
| 更新の完了判定 | API read-backを送信元UTF-8本文と正規化比較し、失敗時は停止する。 | `gh`の終了コードのみ。内容欠損を検知できない。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | Issue #33の受け入れ条件を実装前に固定 | T-1, T-2, T-3 |
