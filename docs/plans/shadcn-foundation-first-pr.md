# shadcn/ui基盤第一PR 計画
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標
要望: 現行React/Tailwindを監査し、shadcn/ui移行の共通基盤とAccount/Plan共通surfaceを追加する。
ゴール: workflow/APIを変更せず、後続surfaceが同じprimitive・token・用語を利用できる状態にする。
成功指標: components.json、cn、semantic CSS variables、最小primitive、用語集、全surface migration matrixが存在し、Account/PlanのStorybook・テスト・buildが通る。

## ユーザーストーリーと受け入れ条件
### US-1
As a UI実装者, I want 共通primitiveとtokenを利用したい, so that surfaceごとの見た目と操作を統一できる。
Given: React/Tailwindの既存構成がある。
When: UI基盤ファイルを参照する。
Then: `cn`、semantic variables、Button/Card/Badge/Fieldが利用できる。

### US-2
As a Kadode利用者, I want AccountとPlan surfaceを共通UIで確認したい, so that account状態と契約境界を理解できる。
Given: FreeまたはStandardを選択している。
When: Account/Plan surfaceを表示する。
Then: 現在のプラン、変更確認、Pro非対象の境界が表示され、外部課金を実行しない。

### US-3
As a UIレビュー担当者, I want 移行対象と用語を追跡したい, so that 後続PRのscope衝突を防げる。
Given: Home/Project/Knowledgeと共通surfaceがある。
When: glossaryとmigration matrixを確認する。
Then: 各surfaceのowner、移行状態、禁止範囲、許可用語が記録されている。

## 質問リスト
なし。第一PRの境界は依頼文と正本AGENTS.mdで確定している。

## スコープ外
- Home/Project/Knowledge workflow、API、データ取得、状態管理の変更
- App.jsxとshared styleの同時変更
- 実課金、外部サービス接続、Pro機能の実装
- 全surfaceの一括移行（後続PRでmatrix順に実施）

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-FOUNDATION | components.json、cn、semantic tokens、最小primitive | 検査: `npm run test`、`npm run build`、`git diff --check` | 既知 |
| T-ACCOUNT-PLAN | Account/Plan共通surfaceへのprimitive適用 | 検査: component test、Storybook build、a11y test | 類推可能 |
| T-DOCS | 用語集と全surface migration matrix | 検査: 対象surface・owner・禁止範囲が全行にあることをレビュー | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| UI基盤 | 既存Tailwind v4上にshadcn/ui互換のローカルprimitiveを置く | 大規模component依存追加はbundleと更新責任を増やすため却下 | 依存追加なし |
| CSS token | 既存色をsemantic CSS variablesへ整理しTailwindから参照する | hexの画面直書きはテーマ/a11y検証を分断するため却下 | tokenを正本化 |
| migration | Account/Planから段階移行する | Home等のworkflowと同時変更は所有権衝突のため却下 | 後続PRへ分割 |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-08-09 | 初版作成 | 第一PRの境界と受入条件を固定 | 全タスク |
