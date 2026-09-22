# Issue #61 ヴィンテージと桜の design token 第一スライス計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: ヴィンテージ参考配色を起点に、Dots. の深緑・生成りへ低彩度の桜ニュアンスを加えた semantic token を導入する。

ゴール: App shell と代表 card/button/dialog が用途名の token を使い、桜を節目・選択・提案・完了の補助にだけ表示する。

成功指標: Desktop、390px Mobile、High Contrast の Story と axe・キーボードテストで、主要状態のコントラスト、focus、横方向あふれなしを観測する。

## ユーザーストーリーと受け入れ条件

### US-1 読みやすい作業面

As a Dots. の利用者, I want 深緑と生成りを基調にした落ち着いた画面を使いたい, so that 長い検討作業に集中できる。

Given: App shell を表示している
When: 通常、hover、focus、disabled、error の状態を確認する
Then: canvas/surface/text/border/action/warning/focus token により各状態が判別でき、focus は可視である。

### US-2 控えめな桜の案内

As a アイデアを検討する利用者, I want 桜色が重要な節目だけを示してほしい, so that 本文の読みやすさを損なわない。

Given: 選択中のナビゲーション、提案 card、完了したプロフィール導線がある
When: 各要素を表示する
Then: sakura petal/blush token は補助領域に限って使われ、本文 canvas は桜色で塗られない。

### US-3 支援技術での操作

As a キーボードまたは高コントラスト表示の利用者, I want 同じ shell を操作したい, so that 視覚設定にかかわらず移動できる。

Given: Desktop、390px Mobile、High Contrast の表示がある
When: Tab と Escape を使い、画面幅を確認する
Then: button の focus が見え、dialog は Escape で閉じ、390px で scrollWidth は viewport 幅を超えない。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | 第一スライスの token 値と適用範囲は Issue #61 で確定済み | プロダクト担当 | なし |

## スコープ外

- IdeaCandidateWorkspace とその E2E、local/fake AI 補完ロジックの変更。
- 全 component の一括 token 置換、画像のアプリへの再配布、外部公開。
- gradient、点滅、連続 animation、固定 Stage gate。
- API、DB、課金、外部 AI 接続、モデルカタログの変更。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | semantic CSS token と reduced motion/high contrast の基盤 | 検査: `npm run test:a11y` | 既知 |
| T-2 | App shell、代表 card/button/dialog の token 適用 | 検査: `npm run test` と 390px 実測 | 類推可能 |
| T-3 | Desktop/Mobile/HighContrast Story と keyboard/a11y 回帰 | 検査: `npm run build-storybook` と `npm run test:a11y` | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| token 層 | CSS custom properties を semantic 名で定義し Tailwind 任意値から参照する。既存 utility を段階移行できるため | component ごとの hex 指定は値が散在し、後続の移行を困難にするため却下 | `styles.css` を第一の token 台帳にする |
| 桜の役割 | 低彩度 petal/blush を選択、節目、提案、完了に限定する | canvas 全面、強い gradient は本文のコントラストと集中を損なうため却下 | 背景面は生成り、桜は狭い補助面 |
| motion | hover は色・影の短い遷移だけにし reduced motion で無効化する | 点滅と連続 animation は注意を奪い、motion 設定を尊重しないため却下 | motion token と media query を追加する |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | Issue #61 と必須 Skills フロー | T-1, T-2, T-3 |
