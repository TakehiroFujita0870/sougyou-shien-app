# T-IA-00: 3 surface IA migration inventory

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: IA reset後に旧AI chat route、端末内state、knowledge contractを安全に扱い、未確認の自動移行を行わない。

ゴール: 実mainの旧surfaceと保存鍵を証拠付きで列挙し、Home / Project / Knowledgeへの移行、保持、廃止の境界を決める。

成功指標: 実行中の旧route、保存鍵、knowledge grantの差異、既存PR #99/#89への影響、rollbackが記録され、後続部門が所有範囲を誤らない。

## inventory結果

| 区分 | 実mainの証拠 | IA resetでの扱い |
| --- | --- | --- |
| navigation | `src/components/WorkspaceShell.jsx` の `SHELL_NAV` は `chat`、`ideas`、`projects`、`research`、`files`、`search` の6項目。 | T-IA-02でHome / Project / Knowledgeの3項目へ置換する。`chat`を第4項目として残さない。 |
| chat placeholder | `src/App.jsx` は `activeWorkspace === 'chat'` でAIチャット見出しと説明を表示する。 | T-IA-02で独立routeをHomeへ非破壊redirectまたは明示案内へ置換する。選択はshell PRのテストで確定する。 |
| unmerged workspace chat | `dots:workspace-chat` と `WorkspaceChatPage` はmainに存在しない。PR #99だけがproducerであり、merge停止中。 | 実ユーザーstateのmigrationは不要。PR #99のstateをmainへ導入しない。 |
| existing idea state | `IdeaCandidateWorkspace` は `dots:idea-candidates`、`dots:idea-conversation`、`dots:idea-input-draft`、`dots:idea-form-draft` を使用する。project IDは保存しない。 | 自動でHomeまたはProjectへ確定移行しない。T-IA-04は利用者が明示してHomeへimportするread-only候補だけを設計する。旧stateの削除は禁止する。 |
| knowledge grants | `project_knowledge` / `knowledge_grants` とRLS migrationはproject単位grantを持つ。一方 `SpaceKnowledgeRepository` は同一user space内の横断参照を既定有効にする。 | T-IA-05でdomain/API compatibility matrixを作るまでDB migrationを行わない。owner隔離、原本一意、reference metadata、削除伝播を後退させない。 |
| old plans | `design-system-chat-boundary.md` は単一`WorkspaceChatPage`を前提とし、`org-resource-governance.md` は旧#78名称を持つ。 | T-IA-02以降の各所有部が新contractに更新する。T-IA-00では旧文書を削除または書換えない。 |

## ユーザーストーリーと受け入れ条件

### US-IA-00-1: 旧会話の保持

As a 既存利用者, I want 旧端末内会話を勝手に別surfaceへ確定移行されない, so that 文脈の違うprojectへ記録が混ざらない。

Given: `dots:idea-conversation`または`dots:idea-input-draft`が端末内にある
When: Home / Project / Knowledgeの新しい会話機能を初めて開く
Then: 旧stateは削除も自動保存先変更もしない。Homeへのimport候補は利用者の明示操作後だけread-onlyで表示する。

### US-IA-00-2: 独立chat routeの廃止

As a 利用者, I want 旧chat routeが第4ナビ項目として残らない, so that 3 surface IAを一貫して操作できる。

Given: 旧 `chat` workspace stateを選択している
When: T-IA-02の3 surface shellを表示する
Then: Homeへ非破壊redirectするか、Homeへ移動する明示案内を表示する。独立chat canvasを新規表示しない。

### US-IA-00-3: knowledge境界の保持

As a 利用者, I want 同一user spaceの知識を参照しても別userの知識を見ない, so that 横断参照とowner隔離を両立できる。

Given: legacy grant recordまたはspace knowledge referenceがある
When: T-IA-05がcompatibility matrixを実装する
Then: 別ownerは0件、原本は一意、reference metadataはlocator/revisionを持ち、原本削除後はreferenceを利用できない。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-IA-00-01 | 旧 `chat` routeはredirectか明示案内か。 | プロダクトUI・デザインシステム部 | T-IA-02開始時 |
| Q-IA-00-02 | Home importで旧conversationをコピーするか、read-only表示に留めるか。 | 会話体験・プロジェクト部 | T-IA-04開始時 |
| Q-IA-00-03 | legacy grantをspace referenceへ読み替える互換APIの有無。 | 事業設計・調査部・基盤部 | T-IA-05開始時 |

## スコープ外

- runtime route、storage、database、migration SQL、既存stateの削除、PR #99/#89の実装変更。
- 外部接続、実ユーザー情報の送信、owner隔離を緩める変更。

## 部門へのhandoff

| 次タスク | 担当部 | 提供契約 | 変更禁止境界 |
| --- | --- | --- | --- |
| T-IA-02 | プロダクトUI・デザインシステム部 | 6項目navと`chat` placeholderを3 surfaceへ置換する必要がある。 | App.jsx、shared style、conversation workflowを同時に所有しない。 |
| T-IA-03 | 基盤・認証部 | current surface、route/view/subview、entity ID/name/revision/locator、selection、dirty、permission、plan、profileをallowlist snapshotにする。 | raw file、hidden knowledge、other-user、sensitive profileを投入しない。 |
| T-IA-04 | 会話体験・プロジェクト部 | #99の`dots:workspace-chat`は未マージ。既存idea stateは明示import候補まで。 | 独立chat route、project IDの推測、自動保存先変更をしない。 |
| T-IA-05 | 事業設計・調査部 | legacy grantとspace knowledgeのcompatibility matrixが必要。 | owner隔離、原本一意、削除伝播を弱めない。 |

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- |
| T-IA-00-1 | このinventory | 検査: `rg`でnav、chat placeholder、storage key、grant、space knowledgeの証拠を確認 | 既知 |
| T-IA-00-2 スパイク | `chat` routeのredirectまたは案内を選ぶUI spike | 検査: Q-IA-00-01の選択と390px/keyboardの観測をT-IA-02計画へ記録 | 未知 |
| T-IA-00-3 スパイク | legacy grantのcompatibility matrix | 検査: Q-IA-00-03の結論とowner/deletion testをT-IA-05計画へ記録 | 未知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 未マージchat state | PR #99のstorage keyはmainに入れない。 | 先にmergeしてから移行する案は独立chat pageを復活させるため却下。 | 採用 |
| existing idea state | project IDがない旧stateは自動移行しない。 | HomeまたはProjectへ推測で確定する案は文脈を混在させるため却下。 | 採用 |
| knowledge contract | legacy grantの削除またはspace contractへの読替はcompatibility matrix後に行う。 | RLSを無視して即時に既定許可へ変える案はowner境界を危険にするため却下。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | T-IA-00のmain inventoryと安全な後続handoffを記録 | T-IA-02からT-IA-05 |
