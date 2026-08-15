# UI E2E UX契約 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 現UIを合格基準にせず、space全体を俯瞰するportfolio stewardのメインAIから壁打ちを開始し、project単位の会話中に事業の芽をpreviewし、本人判断で保存し、添付資料をspace共通libraryから別ページ・別projectで再利用し、F5後も復元できる主要UXをE2E契約にする。

ゴール: PC/390px、keyboard、screen reader、低速hydrationを含む失敗テストと受入基準を、認証・IdeaForm・既存UI実装から独立して固定する。

成功指標: 6シナリオの失敗IDが実行済みテスト名と失敗出力としてCIへ表示され、実装PRが各IDをgreenにするまで合格扱いにならない。

## ユーザーストーリーと受け入れ条件

### US-UX-1 portfolio stewardとproject会話

As a 利用者, I want space全体を俯瞰するportfolio stewardからどのページでも壁打ちを開始し、個別会話はproject単位で扱いたい, so that spaceの前提とprojectの作業文脈を混同しない。

Given: PCまたは390pxで任意のworkspace pageを開いている
When: AI壁打ちの入口をkeyboardまたはscreen readerで探す
Then: 現在ページの主要操作として同じportfolio steward入口へ到達でき、project会話の対象projectが明示される。

### US-UX-2 会話中の芽previewと本人承認

As a 利用者, I want 会話中に事業の芽をpreviewし、内容を承認して保存したい, so that 未確認の生成物が自動保存されない。

Given: AI壁打ちに発言がある
When: 事業の芽previewを開き、本人が保存を承認する
Then: preview、根拠、判断操作が分離され、ユーザーは「プロジェクトに採用して深掘り」「理由付き却下」「保留」から選べ、採用後だけ候補が保存される。判断は強制されない。

Given: 候補を理由付きで却下または保留している
When: 前提が変わらない状態でportfolio stewardが次の候補を提示する
Then: 却下理由に反する同一候補は再提示せず、前提変化がある場合だけ変化と理由付きで再提示する。

### US-UX-3 space共通library再利用

As a 利用者, I want 添付資料をspace共通libraryから別ページ・別projectで再利用したい, so that 同じ資料を再アップロードしない。

Given: 本人がspace libraryへ資料を添付している
When: 別ページまたは別projectで資料候補を開く
Then: 同一user space内では横断知識がデフォルト常時有効で、本人が所有する資料だけが参照候補に表示され、第三者資料は表示されない。

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

Given: 現mainの巨大hero、手入力IdeaForm、Dots. workspace/local fake大警告を確認する
When: 失敗テストを実行する
Then: それぞれの欠陥IDが実行済みのfailing contractとして表示され、実装完了まで受入未達になる。観測eventはPII、本文、owner ID、実時刻、ハッシュを含まない。

## スコープ外

- このPRでの認証、Google sign-in、owner state、IdeaForm、WorkspaceShell、library本体の実装。
- 外部AI、外部ストレージ、Supabase、network送信、実個人情報。
- 失敗テストをskipして合格扱いにすること。
- `docs/inherited/` の変更。
- PDF/DOCX export、公式ひな型adapter、Free/Standard/Proのweighted credits比率と具体credit値。このPRでは契約を追加しない。

## 欠陥台帳とIssue下書き

| ID | 観測した欠陥 | 次Issue |
| --- | --- | --- |
| UX-DEF-01 | 巨大heroがAI壁打ち入口より先に視線を占有する | AI入口を全画面共通化 |
| UX-DEF-02 | 手入力IdeaFormが会話中の芽previewと別入口になっている | 会話previewへ統合 |
| UX-DEF-03 | Dots. workspace/local fake大警告が作業文脈を阻害する | 信頼境界を常設noticeへ再設計 |
| UX-DEF-04 | 添付資料のspace共通library再利用契約がない | library共有境界とproject許可 |
| UX-DEF-05 | 低速hydration中の空状態・F5復元契約がない | hydration state machine |

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-UX-1 | 主要UX E2E失敗テスト | 検査: `npm run test -- --run src/ui-ux-contract.e2e.test.jsx` で6件の実行済みFAIL-UX IDを確認 | 既知 |
| T-UX-2 | PC/390px・keyboard・screen reader契約 | 検査: 同テストのviewport、focus、ARIAシナリオを確認 | 既知 |
| T-UX-3 | 低速hydration/network/PII境界 | 検査: 同テストのhydration遅延、fetch 0件、fixture監査を確認 | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-UX-1: 失敗テストの形式 | 既存Vitest/happy-domで現在のAppをmountし、操作後の不足した意味的UIまたは禁止されたUIをassertする実行可能なred contractにする。実装PRは同じIDをgreenにする。 | `it.todo`は実行も失敗もしないため却下。新runnerは依存と保守責任を増やすため却下。 | 採用 |
| ADR-UX-2: 実装境界 | シナリオ、失敗ID、受入基準だけをこのPRへ置き、認証・IdeaForm・library実装は別Issueへ分離する。 | 大規模なUI変更を同時に行う案は#89と競合し、レビュー範囲500行を超えるため却下。 | 採用 |
| ADR-UX-3: AIの責務境界 | メインAIをspace全体のportfolio steward、個別会話をproject単位として契約する。 | 全projectを単一会話へ混在させる案は、projectの判断境界を失うため却下。 | 採用 |
| ADR-UX-4: 候補判断 | 採用、理由付き却下、保留を明示し、却下理由で再提案を抑制する。前提変化時だけ理由付き再提示を許す。 | 判断を必須化する案はユーザーの保留権を奪うため却下。 | 採用 |
| ADR-UX-5: space横断知識 | 同一user spaceの所有知識はデフォルト常時有効とし、第三者資料を除外する境界だけをE2Eで検証する。 | projectごとのopt-inを必須化する案は確定判断に反するため却下。 | 採用 |
| ADR-UX-6: KPI観測境界 | 成功KPIの目標値は決めず、将来測定可能なPII-free event境界だけを契約する。 | 本文やPIIを収集する分析実装は未承認の外部送信を招くため却下。 | 採用 |

## 保守性ゲート

| 評価順 | 検討結果 | 判断 |
| --- | --- | --- |
| 1. 既存repo内コンポーネント/adapter | 既存App、WorkspaceShell、IdeaCandidateWorkspace、FileLibraryを契約の対象として参照し、新repositoryや新adapterは追加しない。 | 採用 |
| 2. Web/React/Tailwind標準 | VitestとReactの既存テスト境界、既存Tailwind/CSSを使用する。新しいstyled UI基盤や独自dialog/menuは作らない。 | 採用 |
| 3. 実績ある保守ライブラリ | 新規依存は不要。Playwright等はbrowser取得・更新責任・bundle/security/license確認を伴うため、別の依存追加PRへ分離する。 | 今回は不採用 |
| 4. 独自実装 | 独自の実行runnerは作らず、失敗契約の宣言だけを追加する。将来runnerを追加する場合は、既存Vitestで表現できない再現条件、保守責任、移行・削除条件を別ADRへ記録する。 | 今回は最小境界 |

独自境界の削除条件は、実装PRで同じFAIL-UX IDが既存のCI runnerでgreenになった時点で、契約テストをプロダクトの恒久回帰テストへ移し、重複した一時的な契約補助を削除することとする。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | 現UIを合格基準にしないE2E UX契約を固定 | T-UX-1〜3 |
| 2026-08-09 | `it.todo`をmount後に失敗する実行契約へ変更 | todoがgreen扱いとなり受入未達を検出できなかったため | T-UX-1〜3 |
