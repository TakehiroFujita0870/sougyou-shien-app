# 固定Stage残存物の削除 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: Issue #70として、製品コードに残る固定StageのUIを削除する。

ゴール: 利用者に固定Stageまたは通過ゲートを示す製品コンポーネントを残さない。

成功指標: `src/components` に `PipelineProgress`、`PIPELINE_STAGES`、`STAGE GATE`、`currentStage` が存在せず、通常ワークスペースの固定Stage非強制テストが通る。

## ユーザーストーリーと受け入れ条件

### US-1

As a 起業準備者, I want 任意の順序で事業検討を進める, so that 固定の進捗順に縛られない。

Given: Kadodeの製品コードに旧来の固定Stage進捗コンポーネントが存在する
When: Issue #70の変更を適用する
Then: `PipelineProgress`の実装、専用テスト、Storybook storyがリポジトリから削除される

### US-2

As a 起業準備者, I want 通常ワークスペースを使う, so that 固定Stageや通過ゲートを強制されない。

Given: 通常のアプリ画面を静的にレンダリングする
When: App shellの回帰テストを実行する
Then: `STAGE GATE`、`STAGE 0`、進行を止める説明文が表示されない

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | 追加の判断事項なし | - | - |

## スコープ外

- 事業のタネ5観点の表示・編集フローの変更。
- `App`のワークスペースナビゲーション変更。
- 新しい進捗表示の追加。
- `docs/inherited/` の変更。
- API、データベース、外部サービス、課金の変更。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | 固定Stageコンポーネント、専用テスト、Storybook storyの削除 | 検査: `rg -n -i "PipelineProgress|PIPELINE_STAGES|STAGE GATE|currentStage" src/components` が終了コード1になる | 既知 |
| T-2 | 通常Appの固定Stage非強制回帰テストを維持 | 検査: `npm run test -- src/App.test.jsx` が通る | 既知 |
| T-3 | フロントエンド回帰確認 | 検査: `npm run test`、`npm run build`、`npm run build-storybook`、`git diff --check` が通る | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 残存物の扱い | 未参照の固定Stageコンポーネントと専用検証を削除する。PRDの非目標との矛盾を解消できる | 非表示のまま保持する案は、将来の再利用で固定Stage体験を復活させる余地を残すため却下 | 固定Stage関連の3ファイルを削除する |
| 回帰保証 | App shellの非強制テストを維持し、削除対象名の検索を完了判定にする | 新たな代替進捗UIを同一PRに追加する案は、単一目的の範囲を超えるため却下 | 既存のApp回帰テストと検索で保証する |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | 固定Stageの製品コード残存物を削除するため | T-1, T-2, T-3 |
