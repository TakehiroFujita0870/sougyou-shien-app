# T-IA-05 Knowledge成文化schema・legacy互換計画
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 同一user spaceの原本一意・reference metadata・横断知識境界を、既存`project_knowledge`/`knowledge_grants`と互換な成文化schemaとして定義する。

ゴール: Knowledgeを背景、project概要、出典、decisionへ追跡可能な構造で記録し、owner境界・削除伝播・常時有効な同一space横断検索を後続実装へ引き渡す。

成功指標: この文書だけで後続実装者がschema、参照状態、legacy移行判断、拒否条件をGiven/When/Thenで検証できる。

## ユーザーストーリーと受け入れ条件

### US-1 成文化Knowledgeを参照する所有者

As a user-space owner, I want background, project overview, source, and decision records in one Knowledge schema, so that a project decision can be traced to its source.

Given: ownerが1つの原本をspaceへ登録し、抽出本文・embedding・引用locator・revisionを生成している。
When: 同一spaceの複数project、conversation、ideaからreferenceを作成する。
Then: 原本は1レコードのまま、reference metadataに`source_id`、`source_revision`、`locator`、`target_type`、`target_id`が保持される。

### US-2 同一space横断検索を利用する所有者

As a user-space owner, I want references across my projects enabled by default, so that I can reuse knowledge without per-project grants.

Given: sourceとtargetが同一`space_id`かつ同一`owner_id`で、原本とreferenceが削除されていない。
When: portfolio、project、conversation、ideaの検索境界からKnowledgeを問い合わせる。
Then: 有効なreferenceと原本が検索結果へ含まれ、別ownerのレコードは0件となる。

### US-3 参照先を安全に無効化する所有者

As a user-space owner, I want deletion and revision changes to propagate to references, so that stale or deleted source text is not reused.

Given: 原本、抽出本文、embedding、またはsource revisionが削除・取消済みになる。
When: Knowledge候補、検索、export、既存レポートの参照を取得する。
Then: 新規候補・検索・exportには含めず、既存参照は本文を返さず`unavailable`とlocatorだけを返す。

### US-4 legacy grantを利用する所有者

As a legacy user-space owner, I want existing explicit grants to remain readable during migration, so that previously approved references are not silently lost.

Given: `knowledge_grants`に同一ownerのgrantがあり、`revoked_at`とsourceの`deleted_at`がnullである。
When: compatibility adapterがlegacy recordを成文化referenceへ読み替える。
Then: target projectとgrant時刻を保持したreferenceとして返し、同一space既定横断policyと同じ削除・取消フィルターを適用する。

## 成文化schema（後続実装の契約）

### 原本と派生物

| entity | 必須属性 | 一意性・境界 |
| --- | --- | --- |
| `space_source` | `id`, `owner_id`, `space_id`, `content_hash`, `media_type`, `created_at`, `deleted_at` | `(owner_id, space_id, content_hash)`一意。原本のバイト列はspaceに1回だけ保存する。 |
| `source_revision` | `id`, `source_id`, `revision`, `extracted_text`, `embedding_ref`, `created_at`, `deleted_at` | `(source_id, revision)`一意。本文とembeddingはrevision単位で無効化する。 |
| `knowledge_record` | `id`, `owner_id`, `space_id`, `background`, `project_overview`, `decision`, `decision_status`, `created_at`, `deleted_at` | `owner_id`を認証principalから固定する。生の顧客ヒアリングは保存しない。 |
| `knowledge_reference` | `id`, `owner_id`, `space_id`, `knowledge_id`, `source_id`, `source_revision`, `locator`, `target_type`, `target_id`, `created_at`, `deleted_at` | source/target/knowledgeのowner・space一致を複合FKで検証する。 |

`target_type`は`project`、`conversation`、`idea`、`portfolio`のallowlistとする。`locator`は文書ページ、時間範囲、引用範囲の決定的文字列とし、空値を拒否する。embedding本文は検索用派生物であり、原本削除時に同時に利用不能とする。

### 常時有効横断policy

同一`owner_id`・`space_id`のKnowledge referenceは個別grantなしで検索対象とする。別owner、別space、認証principal不一致、`deleted_at`非null、source revision取消済みの行は候補・検索・exportから除外する。grantが存在するlegacy行はadapterで同じ有効条件へ正規化する。

## legacy compatibility matrix

| legacy record | 成文化への読み替え | 利用可否 | 理由・移行条件 |
| --- | --- | --- | --- |
| `project_knowledge` + 有効`knowledge_grants` | `space_source`→`source_revision`→`knowledge_reference` | 読み取り可 | `owner_id`、source/target project所有、未削除、未取消を全て検証する。 |
| `project_knowledge`のみ、grantなし | 同一spaceのreference候補 | 読み取り可 | 新policyは同一space常時有効。明示grantの新規作成は不要。 |
| `knowledge_grants.revoked_at`非null | `knowledge_reference.deleted_at`またはstatus=`unavailable` | 読み取り不可 | 取消は一方向。再有効化せず、監査時刻だけ保持する。 |
| source `deleted_at`非null | source/revision/referenceをstatus=`unavailable`へ | 本文不可 | 既存レポートへlocatorは残せるが、本文・embedding・export値は返さない。 |
| raw customer interviewを指すlegacy source | 新schemaへ移行しない | 拒否 | 匿名化済み派生物の識別子がない記録は原文再利用を防ぐため隔離する。 |
| ownerまたはspace不一致 | レコードを作らず404/0件 | 拒否 | request bodyのowner/space値を認証principalより優先しない。 |

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-IA-05-01 | embedding provider・次元・保持期間をどの運用基準で固定するか | CEO/技術責任者 | 実装PR開始前 |
| Q-IA-05-02 | PDF/DOCX exportでlocatorをページ・段落のどの形式へ正規化するか | CEO/プロダクト責任者 | export実装前 |
| Q-IA-05-03 | legacy raw interview隔離レコードの監査・削除期限を決定するか | CEO/法務責任者 | migration設計前 |

回答がない項目は本計画の実装タスクへ含めない。

## スコープ外

- UI、App.jsx、WorkspaceShell、Knowledge画面、runtime context snapshot。
- backend API、Supabase migration SQL、RLS policyの変更。
- legacy `knowledge_grants`の削除、再有効化、直接データ移行。
- 外部検索、embedding provider、Supabase実接続、個人情報の外部送信。
- 顧客同意・匿名化器の実装、金融・法務判断、exportファイル生成。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-IA-05-01 | 本schemaの型・一意性・owner/space複合境界をレビュー | 検査: `rg -n "space_source|source_revision|knowledge_record|knowledge_reference" docs/plans/ia-knowledge-schema-compatibility.md` とADRレビュー | 既知 |
| T-IA-05-02 | legacy matrixと削除・取消compatibility adapter方針 | 検査: matrixの全行に利用可否と理由があり、US-4のGiven/When/Thenと整合 | 既知 |
| スパイク T-IA-05-03 | embedding保持とexport locatorの決定を質問リストで解消 | 検査: Q-IA-05-01〜02の決定記録をADRへ追記 | 未知 |
| T-IA-05-03 | T-IA-03 context/privacy contract後にmigration/APIへ分解 | 検査: 実装開始前にQ-IA-05-01〜03を決定し、別PRの受入テストへ転記 | 未知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 原本一意 | `space_source`をcontent hashでspace内一意にする。会話・project・ideaごとの重複保存を防ぐ。 | targetごとに原本を複製する案は削除伝播と容量監査が分裂するため却下。 | reference metadataだけを複数targetへ作成する。 |
| 成文化単位 | `knowledge_record`と`source_revision`を分離し、背景・概要・decisionと抽出本文・embeddingのライフサイクルを分ける。 | 1テーブルへ全文・判断・embeddingを混在させる案はrevision取消と本文非開示を表現できないため却下。 | 判断と出典を追跡可能にする。 |
| 横断権限 | 同一owner・spaceは既定常時有効、別ownerは固定principalで拒否する。legacy grantは読み取りadapterで互換化する。 | 新schemaでもprojectごとのgrantを必須にする案は確定product policyと既存space contractに反するため却下。 | 新規grant依存を増やさず既存grantを安全に読み取る。 |
| 削除伝播 | source/revisionの無効化をreference、候補、検索、exportへ決定的に伝播し、既存参照は`unavailable`とする。 | 既存本文をキャッシュして表示し続ける案は削除境界を破るため却下。 | 本文・embeddingの再利用を停止し、locatorのみ監査に残す。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | T-IA-05 planning sliceを新規作成 | #112/#113 merge後のschema・legacy互換境界を成文化 | T-IA-05-01〜03 |
