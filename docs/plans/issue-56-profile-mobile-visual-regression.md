# Issue #56 プロフィールモバイル visual regression 契約

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 390×844の初回プロフィールdialogで、dialog、textarea、閉じる操作、headerがviewport内に収まり、document横overflowを起こさない受入契約を固定する。

ゴール: UI runtime sourceを変えず、#81のprofile hydration実装に重なり得る表示状態をテストと計画で保護する。

成功指標: 390pxを主条件、320pxと1440pxを回帰条件として記録し、Escape、Enter、Shift+Enter、44px target、a11yの非破壊条件を明文化する。

## ユーザーストーリーと受け入れ条件

### US-56-1

As a 390px幅の初回訪問者, I want プロフィールdialogを横スクロールなしで操作したい, so that 入力中に画面から要素がはみ出さない。

Given: 390×844 viewportで未完了プロフィールdialogを表示する
When: header、閉じる操作、質問、textarea、送信操作を確認する
Then: 各要素は縮小可能かつ最大幅制約を持つDOM/CSS契約テストが通る。実ブラウザでのdocument横overflowと390×844 screenshotは#81後のvisual PRで必須確認する。

### US-56-2

As a キーボード利用者, I want dialogを閉じ、入力を送信または改行したい, so that モバイル幅でも入力方法を変えずに済む。

Given: 390px幅でtextareaにfocusがある
When: Escape、Enter、Shift+Enterを操作する
Then: Escapeは閉じるcallbackを一度呼び、Enterは次の質問へ進み、Shift+Enterは改行を維持する。

### US-56-3

As a 支援技術利用者, I want 既存のa11yと操作targetが退行しないことを確認したい, so that profile変更で主要導線を壊さない。

Given: 320px、390px、1440pxを回帰対象として記録する
When: 既存App a11y検査とprofile契約テストを実行する
Then: 44px target、focus、aria関係は既存検査を退行させず、実ブラウザの物理サイズ確認は#81後のvisual実装PRへ引き継ぐ。

## スコープ外

- App.jsx、UserProfileInterview runtime、shared style、WorkspaceShell、profile hydrationの変更。
- 認証、API、外部接続、cookie、token、owner state。
- #81の実表示状態、physical screenshot比較、browser dependencyの追加。これらは#81後のvisual PRで必須確認する。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-56-1 | viewportとdialog構造の受入テスト | 検査: `npm run test -- --run src/issue-56-profile-mobile-visual-regression.test.jsx` が成功。実ブラウザ390×844 screenshotとphysical overflowは#81後visual PRで確認 | 既知 |
| T-56-2 | keyboard非破壊回帰テスト | 検査: Escape、Enter、Shift+Enterの各assertionが成功 | 既知 |
| T-56-3 | a11y/44px条件の引継ぎ記録 | 検査: `npm run test -- --run src/App.a11y.test.jsx` が成功 | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-56-1: visual境界 | 既存Vitest/happy-domでDOM/CSS幅制約とkeyboard契約を固定する。物理レイアウトは計測しないため、実ブラウザ390×844 screenshotとphysical overflow確認を#81後visual PRの必須受入条件にする。 | Playwright screenshotを本PRへ追加する案はbrowser依存追加と#81のruntime境界を広げるため却下。 | 採用 |
| ADR-56-2: 44px条件 | 既存a11y検査を非破壊条件とし、profile controlの物理寸法は#81後の実ブラウザvisual PRで測定する。 | UI sourceへ最小高さを追加する案はfile ownership違反のため却下。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | #81と競合しないtest-only受入契約を固定 | T-56-1〜3 |
| 2026-08-09 | happy-domの物理overflow assertionを削除 | DOM/CSS契約と実ブラウザvisual検証の境界を明確化 | T-56-1 |
