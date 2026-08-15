# Home visual repair 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: Homeを静かなAI-first conversational surfaceへ修復し、1440x900と390x844でcomposerをscrollなしに見せる。

ゴール: Homeに一つのcompact chrome、空状態の一つのcomposer、会話後のmessage streamとsticky composerを表示する。

成功指標: 実ブラウザまたは同等viewport検査で、first viewport、overflow、axe、keyboard、reduced-motionをDesktop/Mobileで確認できる。

## ユーザーストーリーと受け入れ条件

### US-1
As a 利用者, I want Homeを開いた直後にDots. AI composerだけへ集中したい, so that 会話をすぐ始められる。

Given: Homeを1440x900または390x844で開いている。
When: first viewportを確認する。
Then: compact headerと一つのtext composerが表示され、Idea stock、environment-mode copy、collapse control、重複header、巨大hero、floating profile buttonは表示されない。

### US-2
As a 利用者, I want 会話後にmessage streamとcomposerを同時に見たい, so that 入力と直前の文脈を失わない。

Given: Homeに会話履歴がある。
When: viewportを確認する。
Then: message stream、sticky bottom composer、存在するcandidate artifactだけが表示される。

### US-3
As a キーボード・支援技術利用者, I want composerとprofile menuを操作したい, so that ポインタやmotionに依存しない。

Given: Homeが表示されている。
When: Tab、Enter、Shift+Enter、reduced-motion設定を使う。
Then: visible focus、screen-reader label、44px target、motionなしの意味、account footerのprofile accessが確認できる。

### US-4
As a 利用者, I want account menuとplan summaryを分離して見たい, so that profile、利用状況、設定の役割が重複しない。

Given: account footerを表示している。
When: account triggerを明示的にクリックする。
Then: 一つのmenuにprofile、plan、設定、help、logoutが表示され、Plan画面にmodel controlsとupgrade CTAが表示されない。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-1 | 実ブラウザscreenshotをCIへ保存するか | Quality | PR review前 |

## スコープ外

- conversation送受信、candidate decision、hydration、storage、API、auth、外部サービス、domain変更。
- model catalogからの選択・保存ロジック、conversation contextへのmodel接続。
- Project/Knowledge presentation、shared style全体、global token再定義、外部UI library。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | Home visual critiqueとbefore/after viewport evidence | 検査: 1440x900/390x844 screenshotまたはDOM viewport evidenceを保存 | 類推可能 |
| T-2 | compact Home shell/composer presentation | 検査: App presentation testとa11y testが成功 | 類推可能 |
| T-3 | Home Desktop/Mobile/Empty/Conversation Stories | 検査: `npm run build-storybook`が成功 | 類推可能 |
| T-4 | 最終検査 | 検査: `npm run test`、`npm run build`、`npm run build-storybook`、`uv run pytest`、`git diff --check`が成功 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| Home entry | 既存conversation workflowのpresentationをHomeへ置く。storageと候補判断を保てる。 | 新workflow追加は状態と責務を二重化するため却下。 | 実装する。 |
| chrome | header一層、sidebar三項目、account footerに限定し、collapse widgetを置かない。 | breadcrumb/header/Dots.の重複とcollapse controlはfirst viewportを圧迫するため却下。 | 実装する。 |
| profile access | floating buttonをaccount footer/menuへ移す。 | 常時floating buttonはcomposerと競合するため却下。 | 実装する。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | P0 UX修復の実装境界を固定 | T-1からT-4 |
