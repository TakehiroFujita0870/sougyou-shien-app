# #74 + #76 Home first viewport 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: Home first viewportを、静かなNotion風shell内でDots. AI composerと直近の会話または候補artifactへ即時に到達できる表示へ整える。

ゴール: Desktopと390pxで、Homeの主導線を既存conversationとcandidate decision workflowのまま視認・操作できる状態にする。

成功指標: Desktop、390px、Empty、ConversationのStoryと自動検査で、composer、直近artifact、keyboard focus、axe、reduced-motionを観測できる。

## ユーザーストーリーと受け入れ条件

### US-1

As a 起業準備者, I want Homeを開いた直後に会話composerへ到達したい, so that 考え始める前に画面を探索しない。

Given: HomeをDesktopまたは390px幅で開いている。

When: first viewportを確認する。

Then: compact header、Home / Project / Knowledge nav、Dots. AI composer、直近会話または候補artifactが表示され、巨大heading、重複CTA、二分割の空カードが表示されない。

### US-2

As a キーボード利用者, I want Home composerと候補artifactを順に操作したい, so that ポインタを使わず会話と候補判断を続けられる。

Given: Homeが表示されている。

When: Tab、Enter、Shift+Enter、OSのreduced-motion設定を使う。

Then: focusable controlにvisible focusがあり、composer labelとEnter送信/Shift+Enter改行の説明があり、candidate decision controlと既存の状態保持が利用でき、motionを必須にしない。

### US-3

As a 品質確認者, I want HomeのEmptyとConversation状態をStorybookで比較したい, so that first viewportの密度をDesktopと390pxで確認できる。

Given: Storybookを開いている。

When: Desktop、Mobile、Empty、Conversation Storyを選択する。

Then: 各Storyでnav、composer、状態に応じた会話または候補artifactを確認できる。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-1 | Homeの既存candidate workflowを変更せずにfirst viewportへ表示できるか | プロダクトUI・デザインシステム部 | 実装前のコード調査 |

## スコープ外

- 会話送受信、candidate adopt / hold / rejectの判断ロジック、保存形式、API、外部AI、auth、data model、repositoryの変更。
- Home以外のsurfaceの実データ、workflow、nav項目の追加または削除。
- shared stylesの同時変更、全体tokenの再定義、外部UIライブラリ導入。
- 390px実ブラウザsnapshot以外のブラウザ自動化基盤導入。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | Home first viewportのpresentation調整 | 検査: App DOM testでcomposerと直近artifactを確認 | 類推可能 |
| T-2 | Desktop / Mobile / Empty / Conversation Story | 検査: `npm run build-storybook`が成功 | 類推可能 |
| T-3 | keyboard、axe、reduced-motion回帰検査 | 検査: `npm run test`でa11yとHome presentation testが成功 | 類推可能 |
| T-4 | 最終検査とセルフreview | 検査: `npm run test`、`npm run build`、`npm run build-storybook`、`uv run pytest`、`git diff --check`が成功 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| Home主導線 | 既存IdeaCandidateWorkspaceをHomeの唯一のconversation composerとして見せる。既存の保存とcandidate decisionを保つため。 | 新しいcomposerを追加する案は入力導線とstateを二重化するため却下。 | 実装する。 |
| first viewport | Home見出しをcompactにし、既存conversationを先頭に置く。 | heroまたは空の二分割カードを追加する案は会話開始を遅らせるため却下。 | 実装する。 |
| accent | 既存のvintage基調を保ち、sakuraは候補artifactとfocusの小面積に限定する。 | 大面積の桜背景またはgradientは情報階層を損ねるため却下。 | 実装する。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | #74 + #76のHome presentation sliceを実装前に固定 | T-1からT-4 |
