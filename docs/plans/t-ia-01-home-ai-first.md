# T-IA-01 Home初期canvas AI-first visual regression acceptance contract 計画
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標
要望: 初期Homeを巨大hero・IdeaForm・大見出しなしのcomposer中心canvasとして受入検証し、PC・390px・F5・keyboard・screen reader・context leakageを観測可能にする。
ゴール: 実装部門がHome surfaceを変更したとき、品質部門の独立テストで受入条件の破壊を検出できる。
成功指標: T-IA-01受入テストがmainで通り、対象ファイルが計画・テスト・fixtureだけである。

## ユーザーストーリーと受け入れ条件
### US-1
As a 利用者, I want 初期Homeでcomposerへすぐ到達したい, so that 最初の行動がアイデア入力になる。
Given: 完了済みプロフィールfixtureを読み込んでいる。
When: Homeを初期表示する。
Then: `アイデアを話してみる` と `textarea#idea-message` が表示され、巨大hero、`IdeaForm`旧3項目、大見出し表現が表示されない。

### US-2
As a mobile利用者, I want 390px幅でcanvasを横スクロールせず使いたい, so that 入力と操作が画面内に収まる。
Given: viewport幅が390pxである。
When: Homeを表示する。
Then: composer、textarea、主要操作、スクリーンリーダー用labelが存在し、横overflowを示す固定幅クラスがない。

### US-3
As a keyboard/screen reader利用者, I want 初期canvasを意味構造と標準操作で使いたい, so that 視覚表示に依存せず入力できる。
Given: Homeを表示している。
When: DOMのランドマーク、label、button、focusable controlを検査する。
Then: `main`、主要ページnav、`aria-label=アイデアストック`、textareaのlabel、type=button/submitの操作要素が観測できる。

### US-4
As a privacy-conscious利用者, I want reload後もlocal-only境界が保たれてほしい, so that 入力文脈が外部へ漏れない。
Given: 完了済みプロフィールとcomposerを表示している。
When: F5相当のunmount/remountを行い、入力を送信する。
Then: 入力と会話が端末内に復元され、fetchが呼ばれず、外部送信を示すcontext leakageがない。

## 質問リスト
なし。受入条件はASSIGNMENTで決定済み。

## スコープ外
- App.jsx、components、surface、shared style、workflow、API、auth、外部接続の変更。
- 実ブラウザの画像差分基盤やCI runnerの追加。
- 実ユーザーデータ、認証情報、個人情報をfixtureへ収録すること。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-IA-01-P | 本計画と受入契約 | 検査: `rg -n "Given:|When:|Then:|^## スコープ外|^## ADR" docs/plans/t-ia-01-home-ai-first.md` | 既知 |
| T-IA-01-F | 完了済みプロフィールfixture | 検査: fixtureが秘密情報・個人情報を含まないJSONであることをレビュー | 既知 |
| T-IA-01-T | Home acceptance E2E/visual contract | 検査: `npm run test -- src/t-ia-01-home-ai-first.acceptance.test.jsx` | 類推可能 |
| T-IA-01-V | 全検査と差分レビュー | 検査: `npm run test`, `npm run build`, `npm run build-storybook`, `uv run pytest`, `git diff --check` | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| visual regressionの実装単位 | 既存Vitest + happy-domでDOM/class/ARIA/viewport契約を固定する。依存追加なしでmainの受入を再現できる。 | 新しいPlaywright画像基盤は依存・runner・baseline管理を増やし、今回の所有範囲を越えるため却下。 | 実画像ではなく、初期canvasの視覚に影響する観測可能な構造契約を検査する。 |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-08-09 | 初版作成 | T-IA-01 ASSIGNMENT | T-IA-01-P/F/T/V |
