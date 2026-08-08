# Free・Standardの利用権限とモデル選択 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

### 要望原文

> FreeとStandardの機能境界、利用上限、モデル選択UI、モデルカタログを実装する。

### ゴール

FreeとStandardの利用権限を一元判定し、プランに応じて選択できるモデルとThinking Effortを表示できる状態にする。

### 成功指標

- 自動テストで、Freeの利用可能モデルにThinking Effortが含まれず、Standardの既定モデルが`gpt-5.6-terra`であることを確認する。
- StorybookでFreeとStandardの選択肢をそれぞれ確認できる。

## ユーザーストーリーと受け入れ条件

### US-01 Free利用者

As a Free利用者, I want 軽量モデルだけでアイデア作成を始めたい, so that 追加設定なしにプラン内で安全に利用できる。

Given: Freeプランが選択されている

When: モデル選択UIを表示する

Then: Freeで許可された軽量モデルだけが表示され、Thinking Effortの選択肢は表示されない

### US-02 Standard利用者

As a Standard利用者, I want 許可されたモデルを選びたい, so that 作業に合うモデルを選択できる。

Given: Standardプランが選択されている

When: 初めてモデル選択UIを表示する

Then: `gpt-5.6-terra`が選択済みで、Standardで許可されたモデルだけが選択肢に表示される

### US-03 開発者

As a 開発者, I want モデルと権限の情報を一箇所から参照したい, so that モデルIDやプラン分岐をUIへ重複して書かずに済む。

Given: モデルカタログを参照するコードがある

When: プランごとの選択肢または既定値を求める

Then: カタログと権限判定関数から結果が返り、UIは論理キーだけを扱う

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-01 | 月次回数・処理量の具体的な上限値 | CEO | 原価スパイク完了後 |

## スコープ外

- Stripe契約、本番課金、Proプラン、実モデルAPI接続、APIキー設定。
- 月次回数・処理量の具体的な上限値の決定と永続化。
- 既存アイデア入力UXの変更、データ移行。`App.jsx`へのプラン選択統合は[Free・Standardプラン選択UIとlocal契約計画](../plans/subscription-plan-selection.md)を正本とする。
- モデル更新の自動検知・本番既定値の自動変更。

## タスク

| ID | 成果物 | 完了判定 | 不確実性 |
| --- | --- | --- | --- |
| T-01 | モデルカタログとプラン権限判定 | 検査: `src/models/modelEntitlements.test.js`がFreeのThinkingなし、Standard既定、非許可モデル拒否を確認 | 既知 |
| T-02 | 独立した`ModelSelector`とStory | 検査: Storybook buildがFreeとStandardのStoryを処理する | 類推可能 |
| T-03 | 計画・実装セルフレビュー | 検査: `npm run test`、`npm run build`、`npm run build-storybook`、`uv run pytest`、`git diff --check`が成功する | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| モデル情報の置き場 | `src/models/modelCatalog.js`へ論理キー、provider、modelId、plans、reasoningModes、能力、原価区分、enabled、isDefaultを集約する。UIと将来のAPIで同じ根拠を使える | UI内でモデルIDとプラン分岐を直接記述する案は、更新漏れと仕様不一致を招くため却下 | UIは論理キーと権限関数だけを利用する |
| Freeのモデル | 開発互換として正本に記載された軽量のClaude HaikuをFreeの固定候補にする。Thinking Effortを空配列にして権限判定でも禁止する | 未確認の軽量モデルIDを新設する案は、ライフサイクル正本に根拠がないため却下 | API接続前に公式カタログ確認で再評価する |
| 権限の表現 | 純粋関数でプラン別のモデル、既定、Thinking Effortを返す | UIだけで表示を制御する案は、将来のAPI側で再利用できないため却下 | API実装時も同じ論理キーを入力にして境界で再検証する |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版。Issue #19のFree・Standard境界と独立UIを定義 | Issue本文とモデルライフサイクルを実装可能な受け入れ条件にするため | T-01からT-03 |
