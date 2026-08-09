# T-IA-02-R: 3-surface workspace shell runtime 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: Home / Project / Knowledgeだけをtop-level navに表示し、HomeではKadode AI conversation surfaceをfirst viewportの主役にする。

ゴール: 既存の会話送受信・候補採否・context生成を変更せず、3-surface shell、compact header、responsive layout、selected surfaceのF5保持をruntimeへ接続する。

成功指標: 390px/Desktop、keyboard/a11y、F5後のselected surface保持をテストで確認し、Project/Knowledgeはplaceholder surfaceとして表示される。

## 所有権と前提

- `WorkspaceShell.jsx`、responsive shell presentation、visual tokenの実装は本assignmentの所有範囲。
- `App.jsx`は3項目navのruntime接続、surface placeholder、selected surfaceのF5保持に必要である。assignmentのchange prohibitionに従い、実装開始前に統合部からApp.jsx所有権の明示を受ける。
- `src/styles.css`を変更する場合はApp.jsxと同時変更せず、必要性と時分割を統合部へ報告する。初期実装では既存Tailwind utilityと既存tokenを優先する。
- conversation workflow、送受信、candidate decision、context allowlist、repository、API、authは別部門の所有として変更しない。

## ユーザーストーリーと受け入れ条件

### US-1: 3-surface navigation

As a workspace利用者, I want Home / Project / Knowledgeの3項目だけをtop-level navで選びたい, so that 作業場所を短い視線移動で判断できる。

Given: runtime workspace shellをDesktopまたは390pxで表示している。

When: top-level navを確認する。

Then: Home、Project、Knowledgeの3項目だけが表示され、選択中surfaceは`aria-current="page"`で判別できる。

### US-2: Home AI-first surface

As a Home利用者, I want first viewportでKadode AI conversation surfaceとcomposerを見たい, so that 次の入力を探すためにスクロールしなくてよい。

Given: Homeを選択している。

When: 390pxまたはDesktopのfirst viewportを確認する。

Then: conversation surfaceとcomposerが表示され、巨大hero、二分割空カード、重複CTA、常設開発警告が表示されない。

### US-3: Placeholder surfaces

As a ProjectまたはKnowledge利用者, I want placeholder surfaceで現在位置を確認したい, so that 後続機能の場所を理解できる。

Given: ProjectまたはKnowledgeを選択している。

When: surface contentを確認する。

Then: compact breadcrumb/context labelとplaceholder説明が表示され、会話workflowやデータ取得は開始されない。

### US-4: Keyboard and refresh continuity

As a keyboard利用者, I want navとcomposerをキーボードで操作し、F5後も選択surfaceを保ちたい, so that 操作位置を失わない。

Given: ProjectまたはKnowledgeを選択し、composerが表示されている。

When: Tabでnav/composerへ移動し、F5相当のreloadを行う。

Then: focusable controlにvisible focusがあり、composer labelとEnter送信/Shift+Enter改行の説明があり、selected surfaceはreload後も維持される。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-1 | App.jsxのruntime接続を本部門の今回assignmentへ明示追加するか | 統合・リリース管理部 | 実装開始前 |
| Q-2 | selected surfaceの保持にsessionStorageを使用してよいか | 統合・リリース管理部 | 実装開始前 |

## スコープ外

- 会話送受信、AI応答、候補採否、context生成、workflow、repository、API、auth、外部AI送信。
- Project/Knowledgeの実データ取得、検索、作成、編集。
- 既存の会話体験部所有ファイルの変更。
- App.jsx所有権の明示前のruntime変更。
- shared style/global tokenの大規模変更、外部UIライブラリ導入。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | App.jsx所有権とselected surface保存方針の確認 | 検査: 統合部の明示payloadでApp.jsxとsessionStorage方針を確認 | 未知 |
| T-2 | 3項目navとcompact shell | 検査: WorkspaceShell testでnav件数、`aria-current`、390px/Desktop構造を確認 | 類推可能 |
| T-3 | Home/Project/Knowledge surface接続 | 検査: App testでHome composer、Project/Knowledge placeholder、禁止要素不在を確認 | 類推可能 |
| T-4 | selected surfaceのF5保持とa11y | 検査: selected surface reload test、axe/keyboard test、既存#116 composer契約の再利用を確認 | 未知 |
| T-5 | 最終検査 | 検査: `npm run test`、`npm run build`、`npm run build-storybook`、`git diff --check`、UTF-8 read-backが成功 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| top-level surface | Home / Project / Knowledgeを固定3項目としてshellで扱う。旧top-level項目と独立chat routeを増やさない。 | 旧navを残す案はAI-first契約と3-surface契約に反するため却下。 | 実装する。 |
| selected surface保持 | sessionStorageを候補にする。reload時だけ同一tabの表示位置を復元し、会話データやrepositoryを変更しない。 | API、repository、localStorageへの接続はruntime境界を広げるため却下。 | Q-2確認後に実装する。 |
| Home first viewport | 既存#116のcomposer presentation contractを接続し、Homeの入力導線を一つにする。 | 独立chat routeや重複CTAを追加する案はworkflow境界に入るため却下。 | 実装する。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | T-IA-02-Rのruntime shell first sliceを分解 | T-1からT-5 |
