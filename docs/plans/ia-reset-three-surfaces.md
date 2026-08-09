# IA reset: Kadode AI が常駐する3 surface 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 情報設計を独立したAIチャットpageから、Kadode AIがHome、Project、Knowledgeに常駐する構造へ再定義する。

ゴール: first releaseの左ナビをHome、Project、Knowledgeの3項目だけにし、各surfaceの文脈と安全境界を持つKadode AIを段階的に提供する。

成功指標: 独立AIチャットrouteと第4ナビ項目がなく、UI context snapshotの最小項目、同一user spaceの知識参照、owner隔離、明示確認が必要な操作、PC/390px/F5/screen reader/context leakageなしをPR単位で検証できる。

## 現行文書・backlogの矛盾と扱い

| 対象 | 矛盾 | IA reset後の扱い |
| --- | --- | --- |
| `docs/spec/PRD.md` と `docs/spec/workspace-shell-plan.md` | current pageとプロジェクト中心のshellで、Home / Project / Knowledgeの3 surfaceを定義していない。 | 3 surface shell PRで正本を更新する。 |
| Issue #78 と PR #99 | sidebarから独立AIチャットpageへ遷移する。 | #78をHome supervisorとproject会話へ再計画する。#99はmergeしない。 |
| `docs/plans/design-system-chat-boundary.md` | `WorkspaceChatPage`を単一chat pageとして扱う。 | 各surface内のchat presentation境界へ置換し、独立pageの前提を廃止する。 |
| `docs/spec/business-seed-plan.md` と `docs/spec/research-memory-plan.md` | project横断knowledgeに個別grantを要求する。 | `space-knowledge-boundary.md`の「同一user space内で既定有効、reference metadata、owner隔離、削除伝播」を優先する。旧grant契約の移行はT-IA-00で棚卸しする。 |
| PR #89 | App/Shell/shared styleを古いshellへ統合する。 | local auth adapter契約は維持し、3 surface shell確定後にowner/session/privacy boundaryだけを再baseする。 |
| PR #111 | WSL preview start/status/stopの運用PRである。 | IAのUI、route、context、所有ファイルに影響しない。P1 cleanupとモデル利用可能化を待ち、IA実装の依存にはしない。 |

## ユーザーストーリーと受け入れ条件

### US-IA-1: 3項目のナビゲーション

As a 利用者, I want Home、Project、Knowledgeだけを左ナビから選びたい, so that Kadodeの情報空間を迷わず移動できる。

Given: desktopまたは390pxのworkspace shellを表示している
When: 左ナビまたはmobile drawerを開く
Then: Home、Project、Knowledgeの3項目だけが操作可能で、AIチャットまたは専用chat pageへの項目はない。

各surfaceのページタイトルはsmall context labelまたはbreadcrumbだけとし、巨大な見出しにしない。

### US-IA-1a: Homeの会話開始canvas

As a 初回の利用者, I want HomeでKadode AIへすぐに話し始めたい, so that 説明カードを読んでから入力する負担なくアイデアを整理できる。

Given: 初回interview gateを完了したHomeを表示している
When: 初期canvasを確認する
Then: 短いKadode AIの最初の一言、最大3つのprompt chip、常設composerだけが表示される。hero、2カラム説明カード、空のアイデアストック、手入力フォーム、巨大な「事業のタネ」見出し、floating「あなたの情報を更新」は表示されない。

Given: 初回interviewが未完了である
When: Homeを開く
Then: 会話開始前に最小のinterview gateだけを表示し、完了後は同じgateを再表示しない。

### US-IA-2: Home supervisor

As a 利用者, I want HomeでKadode AIにspace全体の次アクションを相談したい, so that projectと知識を横断して判断できる。

Given: Homeを表示し、Kadode AIがproposalを提示している
When: アイデア、プロフィール更新、project採用、保留、理由付き却下、再開、または安全な操作代行を選ぶ
Then: AIの推論と保存済み事実を分けて表示し、破壊的操作、外部送信、料金変更、データ削除は利用者の明示確認前に実行されない。

Kadode AIの最初の一言は「いま考えていることを、そのまま話してください。経験・気になる不便・試してみたいこと、どこからでも大丈夫です。」とする。prompt chipは「最近気になった不便」「活かせそうな経験」「小さく試せること」の最大3件とする。

### US-IA-3: projectごとの会話

As a 利用者, I want Project内の選択したprojectでKadode AIと会話したい, so that 別projectの会話と判断を混在させない。

Given: Project一覧からprojectを選択している
When: 市場、競合、機会、利益、実行可能性、資料、事業計画書を扱う
Then: selected project IDと表示名を持つ会話だけが表示され、別projectの会話は表示も保存先も混ざらない。

会話中だけ、AIはcandidate、knowledge、decisionのinline artifactを提示できる。利用者が採用、保留、理由付き却下を明示するまでprojectまたはKnowledgeへ保存しない。

### US-IA-4: Knowledgeの原本と参照

As a 利用者, I want 原本を一度だけ保存して各projectと会話から参照したい, so that 同じ資料を重複保存せず根拠へ戻れる。

Given: 本人のuser spaceにassetまたは成文化された知識がある
When: Knowledgeで要約、検索、関連付け、追加または削除を行う
Then: 原本は一度だけ保存され、project/conversationはsource ID、revision、locatorを含むreference metadataで関連付く。同一user spaceの有効な知識は既定で横断参照でき、別userの知識は候補に出ない。原本削除後は関連referenceが利用不可になる。

### US-IA-5: Kadode AI context boundary

As a 利用者, I want AIがこの画面の情報を根拠として示してほしい, so that 意図しない情報利用を判断できる。

Given: Home、Project、KnowledgeのいずれかでKadode AIを表示している
When: AIが回答または操作proposalを生成する
Then: current surface、route/view/subview、selected project/asset/decisionのIDと表示名、entity revision/locator、選択範囲、未保存変更、権限、plan、local/production profileを含むUI context snapshotを受ける。raw file全文、非表示knowledge、他user情報、機微profile値は自動投入されず、詳細取得は利用者操作または明示retrieval boundaryを必要とする。

composerは各surface下部に常設し、添付、送信、Enter送信、Shift+Enter改行、390pxで44px以上のtarget、keyboard focus、screen reader labelを持つ。local/fake profileは小さなenvironment badgeまたは設定/開発補助へ置き、外部送信なしはcomposer付近の控えめな説明にする。

### US-IA-6: migrationと既存会話

As a 既存利用者, I want 独立chat pageの端末内状態が安全に移行されるか明示されてほしい, so that F5またはIA更新で判断履歴を失わない。

Given: 旧 `kadode:workspace-chat` の端末内状態がある
When: 3 surface実装のmigrationを開始する
Then: T-IA-00で確定した対応表に従ってHomeまたはproject会話へread-only検証し、未分類の会話は削除も自動確定もせず利用者へ選択を示す。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-IA-01 | 旧端末内会話にproject IDがない場合のHome移行、保持のみ、利用者選択のいずれを採用するか。 | 統合部 | T-IA-00完了時 |
| Q-IA-02 | Knowledgeの「追加・削除支援」でAIが提示できる操作proposalのAPI境界。 | 基盤部・事業設計部 | T-IA-04開始前 |
| Q-IA-03 | Homeのプロフィール更新で機微profile値を除外した表示用snapshotの項目。 | 基盤部・会話体験部 | T-IA-03開始前 |

## スコープ外

- 外部AI、外部検索、外部送信、実OAuth、実課金、実ファイルupload、production profileへの接続。
- 3 surfaceを同一PRで一括実装する変更、独立AI chat page、4つ目のナビ項目、App.jsxとshared styleの同時所有。
- Home初期canvasのhero、2カラム説明カード、空のアイデアストック、手入力フォーム、巨大な「事業のタネ」見出し、会話を遮るfloatingプロフィール更新。
- 他userのknowledge、raw file全文、非表示entity、機微profile値の自動context投入。
- 利用者確認なしの削除、外部送信、料金変更、project採用、保留、却下、再開の確定。

## 移行と互換性

1. IA reset計画をmergeし、#99と#89の旧shell統合をmerge待ちから外す。
2. T-IA-00で旧route、local storage、旧grant文書、既存reference metadataをread-onlyで棚卸しし、Q-IA-01の結論とrollback手順を記録する。
3. 3 surface shellを独立PRで導入し、旧AI chat navigationを削除する。旧routeが存在する間はHomeへの非破壊redirectまたは明示案内をテストで選択する。
4. Home、Project、Knowledge、context snapshot、quality acceptanceを1 surfaceまたは1 contractごとのPRに分割する。
5. migration失敗時は旧端末内stateを削除せず、読み取り不能として表示し、rollback PRで新しいread pathだけを戻す。

## 部門ごとの所有権・依存順・Issue再配分

| 順序 | ID | 担当部 | 所有ファイルまたはcontract | 依存 | 完了条件 |
| --- | --- | --- | --- | --- | --- |
| 0 | T-IA-00 | 統合・リリース管理部 | IA migration inventoryとIssue #78 rename/replan記録 | この計画 | 検査: 旧route/storage/grant文書と#99/#89の衝突表を更新する。 |
| 1 | T-IA-01 | 品質・プロダクト運用部 | Home初期canvasのvisual regression acceptance contract | この計画 | 検査: hero、IdeaForm、大見出し不在、composer only start、PC/390px/keyboard/a11yのE2E契約が成功。 |
| 2 | T-IA-02 | プロダクトUI・デザインシステム部 | `WorkspaceShell`、3 item nav、compact header、conversation surface/composer presentation、tokens、a11y primitives | T-IA-01 | 検査: desktop/390pxで3 nav、44px target、keyboard/screen reader Storyとtestが成功。 |
| 3 | T-IA-03 | 基盤・認証部 | UI context snapshot型、owner/session/privacy boundary、F5 hydration contract | T-IA-00 | 検査: snapshot allowlist、別owner拒否、未保存入力保持の契約testが成功。 |
| 4 | T-IA-04 | 会話体験・プロジェクト部 | Home supervisor、starter prompts、inline artifact、project会話、採用/保留/理由付き却下/reopen workflow、context provider | T-IA-02、T-IA-03 | 検査: composer、surface別会話分離、明示確認、F5 contractをcomponent/E2Eで確認。 |
| 5 | T-IA-05 | 事業設計・調査部 | Knowledgeの成文化schema、project domain contract、reference metadata | T-IA-00、T-IA-03 | 検査: 原本一意、同一space横断参照、owner隔離、削除伝播のpytestが成功。 |
| 6 | T-IA-06 | 品質・プロダクト運用部 | cross-surface E2E acceptanceとcontext leakage検証 | T-IA-02からT-IA-05 | 検査: Home→Project→Knowledge、PC/390px、F5、screen reader、別owner/非表示/raw file不露出をE2Eで確認。 |

`App.jsx`と`src/styles.css`はT-IA-01で対象行と時分割を明示するまで変更しない。T-IA-03はconversation workflowだけ、T-IA-04はdomain/API contractだけを所有し、同じPRで相互の所有ファイルを変更しない。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-IA-00 スパイク | 旧chat route、local storage、grant文書、reference metadataのinventoryとmigration対応表 | 検査: `rg`結果、旧→新対応、Q-IA-01の結論、rollbackを1計画へ記録 | 未知 |
| T-IA-01 | Home initial canvas visual regression contract PR | 検査: hero、IdeaForm、大見出し不在、composer only start、PC/390px/keyboard/a11y E2Eが成功 | 類推可能 |
| T-IA-02 | 3 surface shell and presentation PR | 検査: nav itemが3件、compact header、desktop/390px/keyboard/screen reader testが成功 | 類推可能 |
| T-IA-03 | context snapshotとprivacy contract PR | 検査: allowlist、owner隔離、F5、raw/hidden data不投入のcontract testが成功 | 類推可能 |
| T-IA-04 | Home supervisorとproject conversation PR群 | 検査: starter prompts、inline artifact、surfaceごとの会話分離、決定workflow、明示確認testが成功 | 類推可能 |
| T-IA-05 | Knowledge schema/reference contract PR | 検査: 原本一意、reference locator、同一space横断、削除伝播のpytestが成功 | 類推可能 |
| T-IA-06 | cross-surface E2E PR | 検査: Home→Project→Knowledge、PC/390px、F5、screen reader、context leakageなしを確認 | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| IA | Home、Project、Knowledgeの3 surfaceにKadode AIを常駐させる。会話の目的と文脈を画面に結び付けられる。 | 独立chat pageは文脈を切り離し、第4ナビ項目を増やすため却下。 | 採用 |
| 会話分離 | Homeはspace supervisor、Projectはproject ID単位の会話とする。 | すべてを1会話へ混在させる案は判断と保存境界を失うため却下。 | 採用 |
| 知識 | 原本はuser spaceに一度だけ保存し、reference metadataで関連付ける。同一space横断は既定有効にする。 | projectごとの原本複製と既定deny grantは重複保存と設定摩擦を増やすため却下。 | 採用 |
| context | allowlist形式のUI context snapshotだけを自動投入する。 | raw file全文、非表示knowledge、他user情報、機微profile値の自動投入は最小権限に反するため却下。 | 採用 |
| 安全な操作 | Kadode AIはproposalを提示し、破壊的操作、外部送信、料金変更、データ削除は明示確認後だけ実行する。 | AIが利用者操作を自動確定する案は本人判断を奪うため却下。 | 採用 |
| Home初期canvas | 初期viewは短いAIメッセージ、最大3 chip、常設composerだけにする。 | hero、説明カード、空のアイデアストック、手入力フォームは会話開始を遅らせるため却下。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | CEO室の3 surface IAとcontext contractを実装前に固定 | T-IA-00からT-IA-05 |
| 2026-08-09 | Home会話中心の初期canvas、compact header、visual regression先行を追加 | Home/アイディエーションUX決定をIA resetへ統合 | T-IA-01からT-IA-06 |
