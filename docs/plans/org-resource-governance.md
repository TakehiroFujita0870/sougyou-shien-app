# 組織再編とリソース管理計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 統合部がIssue/PRのリソース管理を所有し、部門境界とWIPを不揮発な正本へ固定する。

ゴール: 未割当Issueの独自着手、App.jsxとshared styleの同時変更、担当範囲の重複を防ぎ、レビューキューを優先する。

成功指標: AGENTS.mdとoperations文書にassignment権限、部門所有範囲、開始条件、WIP上限、ファイル競合の時分割、ASSIGNMENT payloadが記録される。

## ユーザーストーリーと受け入れ条件

### US-1
As a 統合・リリース管理部, I want Issueと変更ファイルの担当を先に決めたい, so that 複数部門が同じsurfaceを同時変更しない。

Given: 未割当Issueまたは複数部門にまたがる変更がある
When: 統合部がASSIGNMENTを送る
Then: owner task、file ownership、dependencies、WIP slot、受入条件、禁止境界を確認してから実装を開始する。

### US-2
As a 実装部, I want 自分の所有範囲とWIP上限を知りたい, so that レビュー待ちを増やさず依存順に進められる。

Given: レビュー待ち1PRまたは実装中1件がある
When: 新しい実装を開始しようとする
Then: 統合部の追加assignmentまたは既存WIP解消まで開始しない。

### US-3
As a プロダクトUI・デザインシステム部, I want App.jsxやshared styleに触れず安全に最初のUI作業を始めたい, so that 会話・認証PRと競合しない。

Given: 会話体験・プロジェクト部の#78と基盤・認証部の#89が進行中である
When: 統合部が初回ASSIGNMENTを送る
Then: 新設部は専用のdesign inventory/contractだけを作成し、App.jsx、shared style、WorkspaceShell、chat workflowを変更しない。

## 棚卸し

| 対象 | 所有部 | 状態 | 統合判断 |
| --- | --- | --- | --- |
| PR #89 local auth | 基盤・認証部 | latest main再統合待ち | App.jsx/WorkspaceShellの所有権を明記してから再レビュー |
| PR #90 UI E2E | 品質・プロダクト運用部 | merge済み | 独立検証として完了 |
| Issue #78 AI chat page | 会話体験・プロジェクト部 | 未着手 | chat/project workflow/data-contextを所有。UIデザイン部は直接変更しない |
| 新設デザイン部初回作業 | プロダクトUI・デザインシステム部 | assignment対象 | design inventory/contractのみ。App.jsx/shared style/WorkspaceShellを変更禁止 |

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-1 | #78のchat pageで必要なa11y primitiveの実装順 | 統合部 | design inventory完了後 |

## スコープ外

- UI機能、CSS token、App.jsx、WorkspaceShell、chat workflowの実装
- 既存Issue/PRの担当者以外による変更
- WIP上限を超える追加実装

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | 部門所有範囲と開始条件 | 検査: AGENTS.mdとoperations文書の一致 | 既知 |
| T-2 | ASSIGNMENT payloadとWIP規約 | 検査: 必須項目と冪等キーを確認 | 既知 |
| T-3 | 既存PR/Issue棚卸しと初回安全assignment | 検査: #89/#90/#78と新設部の禁止境界を記録 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| assignment権限 | 統合部が所有する | 各部の独自着手はWIPと変更競合を増やす | ASSIGNMENT/DEPENDENCY_READYを開始条件にする |
| UI境界 | 会話体験とUIデザインを分離する | App.jsx/shared styleの同時変更は競合しやすい | file ownershipと時分割を必須にする |
| 新設部初回作業 | design inventory/contractに限定する | App.jsx/WorkspaceShell/CSSの即時変更は#78/#89と競合する | 実装前にQ-1とassignment更新を必要とする |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | 組織再編と統合部のリソース管理開始 | T-1からT-3 |
