# UI E2E UX契約 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 現UIを合格基準にせず、全画面からAI壁打ちを開始し、会話中に事業の芽をpreviewし、本人承認で保存し、添付資料をspace共通libraryから別ページ・別projectで再利用し、F5後も復元できる主要UXをE2E契約にする。

ゴール: PC/390px、keyboard、screen reader、低速hydrationを含む失敗テストと受入基準を、認証・IdeaForm・既存UI実装から独立して固定する。

成功指標: 6シナリオの失敗IDがテスト名としてCIへ表示され、実装PRが各IDをgreenにするまで合格扱いにならない。

## ユーザーストーリーと受け入れ条件

### US-UX-1 全画面AI壁打ち

As a 利用者, I want どのページからもAI壁打ちを開始したい, so that ページ移動で文脈を失わない。

Given: PCまたは390pxで任意のworkspace pageを開いている
When: AI壁打ちの入口をkeyboardまたはscreen readerで探す
Then: 現在ページの主要操作として同じAI入口へ到達できる。

### US-UX-2 会話中の芽previewと本人承認

As a 利用者, I want 会話中に事業の芽をpreviewし、内容を承認して保存したい, so that 未確認の生成物が自動保存されない。

Given: AI壁打ちに発言がある
When: 事業の芽previewを開き、本人が保存を承認する
Then: preview、根拠、承認操作が分離され、承認後だけ候補が保存される。

### US-UX-3 space共通library再利用

As a 利用者, I want 添付資料をspace共通libraryから別ページ・別projectで再利用したい, so that 同じ資料を再アップロードしない。

Given: 本人がspace libraryへ資料を添付している
When: 別ページまたは別projectで資料候補を開く
Then: 本人が許可した資料だけが参照候補に表示され、第三者資料は表示されない。

### US-UX-4 F5復元と低速hydration

As a 利用者, I want hydration中も保存済み状態を失わずF5後に復元したい, so that 通信待ちで誤操作しない。

Given: 保存済みプロフィール、会話、芽preview、library資料がある
When: 低速hydrationを模擬してF5相当の再読込を行う
Then: loading中は誤った空状態を表示せず、完了後に同じ所有データだけを復元する。

### US-UX-5 PC/390px keyboard/screen reader

As a 利用者, I want PCと390pxでkeyboardとscreen readerだけでも主要UXを完了したい, so that 入力装置や画面幅で作業を失わない。

Given: 1280pxまたは390pxのviewportで主要UXを開始している
When: Tab、Enter、Escape、aria-label、aria-describedbyだけで操作する
Then: focus順、現在地、dialog、保存結果が観測可能で横overflowがない。

### US-UX-6 境界と欠陥の可視化

As a プロダクト担当者, I want 現UIの欠陥を失敗テストとして残したい, so that 未達をgreenと誤認しない。

Given: 現mainの巨大hero、手入力IdeaForm、Kadode workspace/local fake大警告を確認する
When: 失敗テストを実行する
Then: それぞれの欠陥IDがtodo/failing contractとして表示され、実装完了まで受入未達になる。

## スコープ外

- このPRでの認証、Google sign-in、owner state、IdeaForm、WorkspaceShell、library本体の実装。
- 外部AI、外部ストレージ、Supabase、network送信、実個人情報。
- 失敗テストをskipして合格扱いにすること。
- `docs/inherited/` の変更。

## 欠陥台帳とIssue下書き

| ID | 観測した欠陥 | 次Issue |
| --- | --- | --- |
| UX-DEF-01 | 巨大heroがAI壁打ち入口より先に視線を占有する | AI入口を全画面共通化 |
| UX-DEF-02 | 手入力IdeaFormが会話中の芽previewと別入口になっている | 会話previewへ統合 |
| UX-DEF-03 | Kadode workspace/local fake大警告が作業文脈を阻害する | 信頼境界を常設noticeへ再設計 |
| UX-DEF-04 | 添付資料のspace共通library再利用契約がない | library共有境界とproject許可 |
| UX-DEF-05 | 低速hydration中の空状態・F5復元契約がない | hydration state machine |

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-UX-1 | 主要UX E2E失敗テスト | 検査: `npm run test -- src/ui-ux-contract.e2e.test.jsx` でFAIL-UX IDを確認 | 既知 |
| T-UX-2 | PC/390px・keyboard・screen reader契約 | 検査: 同テストのviewport、focus、ARIAシナリオを確認 | 既知 |
| T-UX-3 | 低速hydration/network/PII境界 | 検査: 同テストのhydration遅延、fetch 0件、fixture監査を確認 | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-UX-1: 失敗テストの形式 | Vitestの`it.todo`で未達契約を常に可視化し、実装PRで同じIDを実行可能なgreen testへ昇格する。 | 現UIに合わせた実装依存assertionは欠陥を合格扱いにするため却下。 | 採用 |
| ADR-UX-2: 実装境界 | シナリオ、失敗ID、受入基準だけをこのPRへ置き、認証・IdeaForm・library実装は別Issueへ分離する。 | 大規模なUI変更を同時に行う案は#89と競合し、レビュー範囲500行を超えるため却下。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | 現UIを合格基準にしないE2E UX契約を固定 | T-UX-1〜3 |
