# Free・Standardプラン選択UIとlocal契約 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

### 要望原文

> Free/Standard(980円/月)のlocal/fake plan選択と確認UI、planに応じたModelSelector再計算、Freeへ戻す際のmodel/reasoning正規化、Pro非表示、外部課金未接続表示を実装する。

### ゴール

利用者が設定画面で初回リリース対象のFreeとStandardを比較し、外部課金を行わずにlocal/fake契約のプランを選び直せるようにする。

### 成功指標

- DOMテストでFreeとStandardの説明、確認画面、Pro非表示、外部課金未接続を確認する。
- Freeへの変更後、`ModelSelector`がFreeの既定モデルを表示し、Thinking Effortを表示しないことを確認する。

## ユーザーストーリーと受け入れ条件

### US-01 Free利用者

As a Free利用者, I want Freeの制約を確認して選択したい, so that 許可外のモデルやThinking Effortを使わずに始められる。

Given: 設定画面でFreeを選択する

When: 変更内容を確認して適用する

Then: 現在のプランがFreeとなり、軽量モデル、Thinkingなし、手動調査に上限ありの説明とFreeに許可されたモデルだけが表示される

### US-02 Standard利用者

As a Standard利用者, I want Standardの価格と利用範囲を確認して選択したい, so that 自分に合うモデルを選べる。

Given: 設定画面でStandardを選択する

When: 変更内容を確認して適用する

Then: 現在のプランがStandardとなり、月額980円、複数モデル、既定GPT-5.6 Terra、Freeより大きい調査枠の説明が表示される

### US-03 プラン変更利用者

As a Standard利用者, I want Freeへ戻したとき選択内容を安全に調整したい, so that 非許可のモデルやThinking Effortを保持しない。

Given: StandardでGPT-5.6 TerraとThinking Effortを選択している

When: Freeへの変更を確認して適用する

Then: モデルはFreeの既定モデルへ正規化され、Thinking Effortは表示されない

### US-04 キーボード利用者

As a キーボード利用者, I want 設定画面のプラン選択と確認を操作したい, so that マウスなしで現在のプランを変更できる。

Given: 設定画面を開いている

When: TabとEnterでプランを選び、確認画面で適用する

Then: 操作対象にフォーカスが移動し、選択したプランが適用される

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-01 | 月次回数と処理量の具体的な上限 | CEO | 原価スパイク完了後 |

## スコープ外

- Stripeを含む外部決済、契約、申込確定、API、secret取得。
- Proプラン、定期調査、メール配信の表示または実装。
- local/fake契約状態の永続化、データ移行、バックエンドAPI。
- `IdeaCandidateWorkspace`の変更。
- モデルカタログのモデルIDまたは権限の変更。

## タスク

| ID | 成果物 | 完了判定 | 不確実性 |
| --- | --- | --- | --- |
| T-01 | local/fake契約repositoryと正規化関数 | 検査: repositoryのDOMテストが初期値、確認後の変更、Free正規化を確認 | 既知 |
| T-02 | PlanSelectionコンポーネントとDesktop/Mobile/Free/Standard Story | 検査: `npm run build-storybook`が成功し、Proを描画しない | 類推可能 |
| T-03 | App設定統合とアクセシビリティ | 検査: DOM/a11yテストがプラン変更、キーボード操作、focusを確認し、`npm run test:a11y`が成功 | 類推可能 |
| T-04 | 計画・実装セルフレビュー | 検査: `npm run test`、`npm run build`、`npm run build-storybook`、`uv run pytest`、`git diff --check`が成功 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 契約状態の置き場 | UIに依存しない決定的なin-memory local/fake repositoryでプランを保持する。外部送信なしに確認フローを検証できる | Stripe又はバックエンドへ接続する案はCEO決裁とスコープ外のため却下 | Appはrepository経由で現在プランを得る |
| 選択の反映時点 | プランカードの選択は提案状態に留め、確認の適用で現在プランを更新する | カード選択時に直ちに契約を変える案は確認UIの要件を満たさないため却下 | キャンセル時は現在プランを維持する |
| 正規化の責務 | repositoryがモデル権限関数を使い、プラン変更時にモデルとreasoningを正規化する | ModelSelectorだけで見かけ上の値を置換する案は状態に非許可値を残すため却下 | App状態には常に有効な選択だけを渡す |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版。Issue #54のlocal/fakeプラン選択、確認、正規化を定義 | 実装前に受け入れ条件と決済境界を固定するため | T-01からT-04 |
