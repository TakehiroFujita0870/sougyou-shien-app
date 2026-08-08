# モバイル初回プロフィール横overflow修正 計画
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 390x844の初回プロフィール画面で右側が切れる不具合を直す。

ゴール: device viewportを宣言し、初回プロフィール対話、header、横スクロールnavを320px以上のviewport内へ制約する。

成功指標: 390x844の5秒後画像でdialogの左右端と操作が見え、ページ全体の横スクロールがない。

## ユーザーストーリーと受け入れ条件

### US-1

As a スマホ利用者, I want 初回質問と操作を画面内で読んで操作したい, so that 横へ移動せずプロフィールを作れる。

Given: 幅390pxで初回アクセスしている
When: local profile repositoryの読込が完了する
Then: dialog panel、textarea、閉じる操作、送信操作の左右端がviewport内に表示される

### US-2

As a スマホ利用者, I want headerとnavが本文幅を押し広げないでほしい, so that ページ全体の横スクロールを避けられる。

Given: 幅320pxまたは390pxでAppを表示している
When: headerとnavが描画される
Then: header文字列は縮小可能で、navのスクロール領域はページ本文幅から分離される

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
|---|---|---|---|
| Q-1 | header説明文を極小幅で省略するか | Product | 実利用テスト後 |

## スコープ外

- 配色、文言、情報設計の全面変更
- plan選択UIと対話アイデアUI
- 外部サービス接続

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-1 | viewport宣言とresponsive constraint回帰テスト | 検査: `npm run test`でviewport metaとdialog/header/nav制約を確認 | 既知 |
| T-2 | Appとprofile panelの幅制約 | 検査: 390x844画像とDOM class検査 | 類推可能 |
| T-3 | 全品質検査 | 検査: test、a11y、build、Storybook、pytest、diff check | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| grid幅 | `minmax(0,1fr)`と子`min-w-0 max-w-full`でgridのmin-content膨張を止める | 固定px幅は320pxとdesktopを同時に扱えないため却下 | viewport内へ収める |
| nav | nav内部だけ横scrollを維持し、外側へ`min-w-0`を付ける | 全項目を縮小すると44px targetと可読性を損なうため却下 | 操作性を維持する |
| header | text側を`min-w-0`かつ折返し可能にする | 説明文の即時削除はブランド情報を失うため却下 | 狭幅でも共存する |
| mobile viewport | `width=device-width, initial-scale=1.0`をHTML entryへ宣言する。CDP実測で未宣言時はdevice幅390pxに対して`innerWidth=980`だった | CSSだけで縮小する案はdevice viewport自体が980pxのため却下 | CSS pixel幅をdevice幅へ一致させる |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-08-09 | 初版 | 390x844実画像でoverflowを確認 | T-1からT-3 |
| 2026-08-09 | CDP実測を追加 | mobile emulationで`innerWidth=980`となりviewport宣言欠落を特定 | T-1、T-2 |
