# Issue #70: 固定段階UIの撤去 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 未使用の固定段階コンポーネントを撤去し、非線形な事業検討方針と矛盾する画面表現を残さない。

ゴール: 未参照のcomponent、Story、単体テストを削除し、会話・プロジェクト・研究の状態表現を変更しない。

成功指標: 割当済みの3ファイルが存在せず、指定された強制文言がruntime/UI sourceと本計画文書で0件となり、全テスト・build・Storybook buildが成功する。

## ユーザーストーリーと受け入れ条件

### US-1: 非線形な検討方針

As a 事業検討を進める利用者, I want 固定順序を強いる進捗表示を見ない, so that 現在の論点に応じて検討を進められる。

Given: アプリケーションの画面を表示している。

When: 画面の静的マークアップを確認する。

Then: 固定順序を表す進捗コンポーネントと強制的な次段階条件の文言は表示されない。

### US-2: 既存状態の保全

As a 研究・会話機能を利用する利用者, I want 既存の技術statusと失敗状態が残る, so that 進行中または失敗した処理の状態を判断できる。

Given: 既存の研究runまたは会話機能がある。

When: 固定段階UIを撤去する。

Then: App接続、chat workflow、repository、研究runの技術status、失敗状態は変更しない。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | PipelineProgressは自身の3ファイル以外から参照されていない | なし | なし |

## スコープ外

- App.jsx、WorkspaceShell、WorkspaceChatPage、chat workflow、repository、auth、runtime、APIの変更。
- shared style、global token、docs/inherited、`docs/plans/issue-61-vintage-sakura-tokens.md`の変更。
- 研究runの技術status、失敗状態、App.testの否定アサーションの変更。
- 新しい置換UI、desktop/390px/a11y Storyまたはテストの追加。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | 未参照のPipelineProgress component、Story、単体テストの削除 | 検査: 3ファイルが存在せず、`git grep 'PipelineProgress'`が対象外参照なし | 既知 |
| T-2 | 強制文言の非再導入確認 | 検査: runtime/UI sourceと本計画文書に指定文言が0件 | 既知 |
| T-3 | 回帰検査 | 検査: `npm run test`、`npm run build`、`npm run build-storybook`、`git diff --check`が成功 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| UIの扱い | 未参照の固定段階UIを削除する。表示を残す利用者価値と接続先が存在しない。 | 新しい進捗UIへ置換する案は、要件と接続先が未割当のため却下。 | 削除する。 |
| 非再導入境界 | 既存のApp否定アサーションと#61計画の禁止記述を維持する。 | #61計画を更新する案は、所有外かつ有効な境界を失うため却下。 | 維持する。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | 更新assignmentで対象と所有権を明確化 | T-1、T-2、T-3 |
