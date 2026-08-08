# Issue #62 E2E UX loop と local/fake AI補完 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: E2Eシナリオで入力の詰まりを本文を収集せずに観測し、本人が押したときだけ決定的なlocal/fake「AIで補完」をプレビューとして提示する。改善は観測、Issue下書き、承認、単一PRの順に進める。

ゴール: 利用者が対話アイデア入力で言葉に詰まっても、原文を失わずに補完案を採用、編集、破棄でき、外部送信なしで途中から再開できる。

成功指標: 空送信、同じ欄の反復、help表示、中断再開、補完の採用、編集、破棄を単体・コンポーネントテストで確認し、PC、mobile、keyboard、a11y、長文、offlineのStoryと指定コマンドを通す。

## ユーザーストーリーと受け入れ条件

### US-1 詰まりを本人操作で補う

As a アイデアを考える利用者, I want 自分で補完を求めて提案を確認したい, so that 自分の意図を保ったまま入力を続けられる。

Given: 対話入力欄に原文があり、外部AI接続がない
When: 利用者が「AIで補完」を押す
Then: 決定的local/fake提案が原文と別のプレビューとして表示され、入力欄の原文は変化しない。

### US-2 提案を本人が決定する

As a 補完案を確認する利用者, I want 採用、編集、破棄を選びたい, so that 意図しない文面を保存しない。

Given: 補完プレビューが表示されている
When: 利用者が採用、編集、または破棄を実行する
Then: 採用だけが入力欄へ反映され、編集は利用者が変更した文面を入力欄へ反映し、破棄は原文を残してプレビューを閉じる。

### US-3 中断後も会話を再開する

As a 途中で作業を止める利用者, I want 会話と未送信の原文を端末内から再開したい, so that 入力し直さずに検討を続けられる。

Given: 対話履歴と未送信の入力がlocal/fake repositoryにある
When: ワークスペースを再表示する
Then: 本文を外部送信せず、履歴と入力欄の原文を表示する。

### US-4 本文を残さず迷いを観測する

As a プロダクト担当, I want 詰まりの境界を匿名の決定的eventで確認したい, so that 改善仮説をIssue下書きにできる。

Given: 利用者が対話入力欄を操作している
When: 空送信、同じ欄で3回目の変更、help表示、補完要求、または中断再開が起きる
Then: event key、event type、固定のtimestamp相当sequenceだけがlocal observerへ渡り、本文、PII、外部送信は発生しない。

### US-5 E2E結果から承認済みの改善だけを実装する

As a プロダクト担当, I want 観測結果を人の承認を経て一つのPRにしたい, so that E2E失敗でUIが自動変更されない。

Given: local observerに迷いeventがある
When: 改善候補を扱う
Then: 観測、Issue下書き、承認、単一PRの順序が文書化され、アプリは観測だけでUIを変更しない。

## E2Eシナリオとテスト計画

| ID | 対象 | テスト種別 | 手順と期待結果 | 完了判定 |
| --- | --- | --- | --- | --- |
| E2E-01 | 初回プロフィールから対話、候補保存、export | 手動E2E | 経験、得意分野、関心、時間、資金、避けたい条件を保存し、対話から事業のタネを作る。「どんな事業」「市場」「競合」「利益」「実現性」に各1件の最小入力を行い、事業計画書をexportする | 既存の主要フローを壊さないことを手動確認 |
| E2E-02 | 空送信 | コンポーネント | 空欄で送信し、入力を促す表示と`{ key: "idea_message", type: "empty_submit", sequence: 1 }`を確認する | `npm run test` |
| E2E-03 | 同欄反復とhelp | 単体とコンポーネント | 同じ入力欄を3回変更し、help表示で各eventが本文なしに残る | `npm run test` |
| E2E-04 | 補完preview | 単体とコンポーネント | 原文を入力して補完を要求し、原文不変、採用、編集、破棄を確認する | `npm run test` |
| E2E-05 | 中断再開 | コンポーネント | local/fake入力repositoryから未送信原文と会話を復元し、resume eventを確認する | `npm run test` |
| E2E-06 | offline | コンポーネント | local保存が失敗した場合、会話保存の再試行メッセージを表示する | `npm run test` |
| E2E-07 | PC/mobile/長文/keyboard/a11y | Storyと静的a11y | Desktop、Mobile、LongText、OfflineのStoryを用意し、Enter、Shift+Enter、Tabで操作可能であることを確認する | `npm run test:a11y` と `npm run build-storybook` |

E2E-01のプロフィール、5観点、exportを通すブラウザE2Eと、E2E-07のStory別interaction/a11y自動実行は既存基盤に未導入の検査gapである。第一スライスではシナリオを固定し、候補workspaceの単体・コンポーネント検査とStoryで回帰境界を作る。ブラウザE2E導入は`App.jsx`を変更せず別PRで扱う。

## 迷いevent契約

`createLocalIdeaUxObserver()` はメモリ上のobserverであり、eventを分析サービス、network、localStorageへ送らない。eventは`{ key, type, sequence }`だけで、`key`は`idea_message`、`type`は`empty_submit`、`repeated_edit`、`help_opened`、`assist_requested`、`conversation_resumed`のいずれか、`sequence`はobserver生成時に1から単調増加する決定的なtimestamp相当値とする。本文、文字数、PII、ユーザーID、実時刻はeventに含めない。

同欄反復は、同一マウント中の`idea_message`の3回目の`onChange`で一度だけ記録する。中断再開は、読み込んだ会話または未送信原文が存在する場合に一度だけ記録する。helpは説明を開く明示操作でだけ記録する。

会話保存後に下書き消去だけが失敗した場合、保存済み会話を成功として表示し、入力欄は空にする。再開時に下書きが最新のuser発言と一致すれば送信済みとして復元せず、二重送信を防ぐ。

## 改善loop

1. local observerのevent typeとsequenceをE2E検査または開発者確認で読む。
2. 根拠、再現手順、期待する観測可能な結果だけを含むIssue下書きを作る。本文とPIIは記載しない。
3. プロダクト担当がIssue下書きを承認する。
4. 承認済みIssueごとに一目的、一PR、500行未満で実装し、該当E2E回帰を実行する。

この順序以外でeventを契機にアプリがUI、入力、候補、設定を自動変更する処理は実装しない。

具体例: 実画面E2E監査で確認した旧3項目の入力入口と対話workspaceの二重入口、および着想前の否定的なhero文言はIssue #69として下書き・分離する。#62は`IdeaCandidateWorkspace`内の補完と観測に限定し、`App.jsx`を変更しない。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-62-1 | production analyticsの保存先と保持期間 | CEO | CEO決裁前 |

Q-62-1は実装しない。local observerの範囲は既知である。

## スコープ外

- 外部AI、分析サービス、network request、実ユーザーデータ、PII、支出、APIキーの利用。
- UIの自動変更、固定Stage、通過ゲート、IssueやPRの自動作成。
- `src/App.jsx`、全体styles、design token、候補ワークスペース外のコンポーネントの変更。
- Supabase migration、export実装、認証、モデルカタログ、Pro機能。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-62-1 | E2Eシナリオ、event境界、改善loopを含む本計画 | 検査: planning Exit Criteriaの検索とレビュー | 既知 |
| T-62-2 | 決定的補完関数、local observer、未送信入力のlocal/fake repository | 検査: `npm run test -- IdeaCandidateWorkspace` | 既知 |
| T-62-3 | 補完previewの採用、編集、破棄、help、復帰UI | 検査: `npm run test -- IdeaCandidateWorkspace` | 類推可能 |
| T-62-4 | PC、mobile、長文、offline Storyとa11y回帰 | 検査: `npm run test:a11y` と `npm run build-storybook` | 既知 |
| T-62-5 | 指定コマンド、diff review、PR説明 | 検査: `npm run test`; `npm run build`; `uv run pytest`; `git diff --check` | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 補完実装 | 純粋関数による決定的local/fake提案を採用する。外部送信がなく再現可能である。 | 外部LLMはCEO決裁、キー、個人情報送信境界を要するため却下。 | 将来adapter置換時もpreview、採用、編集、破棄を維持する。 |
| 原文保護 | 補完を別状態のpreviewとし、明示採用または編集でだけ入力へ反映する。 | 入力欄の自動上書きは本人の意図を失わせるため却下。 | 原文は破棄時にも残る。 |
| 迷い計測 | event key、type、sequenceだけをメモリobserverへ渡す。 | 本文、PII、実時刻、外部analyticsは最小化原則とCEO決裁境界に反するため却下。 | E2E用の決定的境界になる。 |
| 改善反映 | 観測からIssue下書き、人の承認、単一PRへ進める。 | eventに応じるUI自動変更は予期しない体験変更となるため却下。 | 観測コードはUI状態を変えない。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | Issue #62の第一スライスとE2E優先の実装開始 | T-62-1からT-62-5 |
