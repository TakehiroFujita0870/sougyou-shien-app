# Notion型 workspace shell 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

上部tab中心のUIを、縦型sidebar・page・account footerを持つworkspace shellへ刷新する。PCでは情報階層を読みやすく、390pxではdrawerとして操作できることを成功指標とする。

## ユーザーストーリーと受け入れ条件

### US-74-1
As a 利用者, I want 主要ページを縦型sidebarから選ぶ, so that 現在地を保ったまま移動できる。
Given: PC幅でworkspaceを開く
When: sidebarを確認する
Then: workspace名、AIチャット、事業のタネ、プロジェクト、横断調査、資料、検索、account footerが表示される

### US-74-2
As a スマホ利用者, I want sidebarをdrawerとして開閉する, so that 390px幅で本文を横に押し広げず操作できる。
Given: viewport幅が390pxである
When: menuを開き、ページを選択するかEscapeを押す
Then: drawerが閉じ、本文の横overflowが発生しない

### US-74-3
As a キーボード利用者, I want collapseとページ移動を操作する, so that pointerなしでもshellを使える。
Given: shell内にフォーカスがある
When: collapseまたはnav buttonを操作する
Then: aria-current、aria-expanded、44px以上の操作対象が維持される

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-74-1 | chatの実装本体を同一PRに含めるか | 部長 | #78開始前 |

## スコープ外

- 5観点のdomain本文、外部AI送信、AI広報、固定Stage/gate、Pro契約処理
- Notionや参考画像の見た目の複製

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-74-1 | WorkspaceShell component | 検査: `WorkspaceShell.test.jsx` でsidebar/account/collapse/drawer/Escape | 既知 |
| T-74-2 | App接続とpage state | 検査: `App.test.jsx` と `App.a11y.test.jsx` | 既知 |
| T-74-3 | Desktop/Collapsed/MobileDrawer/Keyboard Story | 検査: Storybook storyの4 exportを確認 | 類推可能 |
| T-74-4 | responsive CSS | 検査: 390pxでoverflow-x hiddenと44px targetを確認 | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-74-1 | shellを独立componentに抽出し、AppはactivePageとchildrenだけ渡す | App内の条件分岐だけでsidebarを描画する案はmobile drawerと再利用性を損なうため却下 | `WorkspaceShell.jsx` を追加 |
| ADR-74-2 | inline SVGを使わずCSS markと文字記号で構成する | 文字化けしやすい絵文字アイコンは不可、外部アイコン依存は不要なため却下 | 小面積のCSS markを採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | #74のshell要件を実装可能な単位へ固定 | T-74-1〜4 |
