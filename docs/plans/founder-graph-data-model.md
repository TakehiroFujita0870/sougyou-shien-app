# Founder Graph データモデル正本

最終更新: 2026-09-24
状態: schema v2 domain contract、migration、fixture parityを実装済み。MCPの関係writeはv2 RelationAssertionとsource-grounded Evidenceを使用し、read/searchと通常DB migrationのgateは別途継続中

## 要望 / ゴール / 成功指標

要望は、創業に関するアイデア、保有資産、人物、組織、調査資料、判断、実験、レポートを、ChatGPTから継続利用できるグラフとして保存することである。

ゴールは、ノード、関係、履歴、根拠、削除、検索投影の単位を固定し、Neo4jへ保存できたという事実だけでなく、再利用可能なFounder Graphとして意味が保たれる状態を作ることである。

成功指標は、合成20会話、合成10名刺、文書5件、ResearchRun 3件を投入し、再起動後に同じID、revision、根拠、関係、検索結果を再現し、owner越境、private field外部投影、孤立根拠、循環revisionを各0件にすることである。

## 現行schema v1の扱い

2026-09-24の実装監査ではMCPのcapture_ideaがContentChunkを作成せず、link_entitiesがv1 Relationshipを保存し、Evidence新規作成もMCP経由ではできないことを確認した。その後の根拠付き関係保存計画に従い、現行write経路はv2 RelationAssertionとsource-grounded Evidenceを使用する。旧material_id参照は既存データの読取・変換互換に限り、新しい関係の根拠には使用しない。

2026-09-24時点の実装では`Idea`と`Claim`の訂正を新しい同種ノードで表し、`Relationship`をNeo4j relationshipへ直接保存していた。これはschema v1の履歴記録であり、現行関係writeはRelationAssertionとsource-grounded Evidenceのschema v2契約を使う。

2026-09-23時点で、schema v2へ移行するためのdomain contractとして`EntityRevision`、`RelationAssertion`、`ContentChunk`、`Facet`とpredicate allowlistを追加し、Neo4jへv2の制約・索引を追加するmigrationと非破壊rollbackを実装した。空のNeo4jとv1合成ノードで、移行、同じ移行の再実行、rollback後のデータ保持を実機確認済みである。さらにv2全node typeの一時保存・Neo4j保存・安全なfetch/searchのparityを合成fixtureで確認した。既存データの変換、既定保存先の切替は未完了である。

次の不一致が解消するまで、`create_app()`の既定保存先をNeo4jへ切り替えない。

- 安定IDとrevision IDが分離されていない。
- Relation Assertionが独立した根拠・履歴を持てない。
- `Capability`、Facet、ContentChunkの保存単位が固定されていない。
- raw content、検索用text、private contactの保存境界が同じpayloadへ入り得る。
- `FounderGraphHistory`が元payload全体ではなく最小識別情報しか保持しない経路がある。

## ユーザーストーリーと受け入れ条件

### US-DM-01 安定した同一物を追跡する

As a 単独利用者, I want 同じアイデアや人物を訂正しても同一物として追跡したい, so that 関係が版ごとに分断されない。

Given: 一つのIdea anchorにrevision 1が存在する

When: titleとsummaryを訂正する

Then: Idea IDは変化せず、新しいEntityRevisionが追加され、CURRENT_REVISIONが一件だけ新revisionを指す。

### US-DM-02 根拠付きの関係を扱う

As a 単独利用者, I want 人物とアイデアの関係に根拠と確信度を持たせたい, so that LLMの提案を事実と誤認しない。

Given: Person、Idea、Evidenceが存在する

When: LunaがCAN_CONTRIBUTE_TO候補を生成する

Then: RelationAssertionはinferred状態、confidence、expires_at、Evidence参照、生成model snapshotを持ち、confirmed関係として検索されない。

### US-DM-03 原文と抽出結果を分離する

As a 単独利用者, I want 会話原文とAI抽出を区別したい, so that 誤抽出を訂正しても原文を失わない。

Given: 一つのChatGPT発言をSourceとして保存している

When: IdeaとClaimを抽出する

Then: 原文はSourceRevisionまたはlocal content storeに一度だけ存在し、IdeaRevisionとClaimはSourceRevisionへのDERIVED_FROMを持つ。

### US-DM-04 再起動後も同じ意味で検索する

As a 単独利用者, I want Dotsを停止しても検索結果の意味が変わらないでほしい, so that Graphを創業判断の記憶として信頼できる。

Given: 合成fixtureをschema v2へ保存してmanifestを取得している

When: DotsとNeo4jを停止し、同じvolumeで再起動する

Then: node、assertion、revision、current pointer、代表query hashが停止前manifestと一致する。

### US-DM-05 外部送信対象を限定する

As a 単独利用者, I want Graph全体をローカル検索しつつ外部へは許可fieldだけを渡したい, so that 人脈と個人情報を漏らさずにChatGPTを使える。

Given: local_only、shareable、explicitのfieldを含むPersonとIdeaが存在する

When: MCP searchとfetchを実行する

Then: ローカル順位付けは全許可データを使い、MCP responseにはshareableまたは有効なCampaignで許可されたexplicit fieldだけが含まれる。

## モデル化の判定規則

情報を新しいノードにする条件は次のいずれかである。

1. 独立したIDとライフサイクルを持つ。
2. 二つ以上の対象から参照される。
3. 根拠、送信区分、訂正履歴を単独で持つ。
4. Graph traversalの始点または終点になる。
5. 引用、判断、実験、レポートからIDで参照される。

上記を満たさず、一つのrevisionに従属するscalar、短い文字列、順序付き小配列はpropertyにする。binary、長文原本、秘密情報はNeo4j propertyへ複製せず、local content storeへ置いてhashとlocatorだけをGraphへ保存する。

## schema v2のノード単位

### 安定anchor

安定anchorは同一物を表し、訂正でIDを変更しない。表示内容はCURRENT_REVISION先から取得する。

| Label | 一ノードの単位 | 安定ID | 主な索引field |
| --- | --- | --- | --- |
| OwnerProfile | 本人一人 | `owner_<uuid>` | owner_id |
| Idea | 一つの事業着想または派生案 | `idea_<uuid>` | owner_id, status, current_revision_id |
| Asset | 再利用可能な知識、経験、成果物、データ、設備、チャネル、能力 | `asset_<uuid>` | owner_id, asset_kind, status |
| Person | 同一人物候補の確認後に確定した一人 | `person_<uuid>` | owner_id, status, dedupe fingerprint |
| Organization | 一つの法人、団体、個人事業、非公式チーム | `org_<uuid>` | owner_id, status, normalized_name_hash |
| Source | 一つの原本系列 | `source_<uuid>` | owner_id, source_kind, locator_hash, status |
| ResearchCampaign | 一回許諾した目的、範囲、試行予算 | `campaign_<uuid>` | owner_id, status, authorization_revision |
| Decision | 一つの判断論点 | `decision_<uuid>` | owner_id, status, decided_at |
| Experiment | 一つの可逆な検証 | `experiment_<uuid>` | owner_id, status, deadline |
| InstructionArtifact | 一つのAGENTS.mdまたはSKILL.mdのpath | `instruction_<uuid>` | owner_id, path_hash, status |
| Facet | 再利用する分類語彙 | `facet_<uuid>` | owner_id, namespace, normalized_value |

`Capability`は初期schemaで独立Labelにしない。`Asset.asset_kind=capability`として保存し、Person、OwnerProfile、IdeaからRelationAssertionで参照する。MarketとProductも初期schemaではClaimまたはFacetとして保存し、独立ライフサイクルが必要になった時点でmigration ADRを作る。

### 不変ノード

不変ノードは作成後に本文を更新しない。訂正は新しいノードとSUPERSEDESで表す。

| Label | 一ノードの単位 | 必須field |
| --- | --- | --- |
| EntityRevision | anchor一件の一版 | id, entity_id, entity_type, revision, payload_schema, public_payload_json, local_content_ref, content_hash, created_at, provenance_id |
| SourceRevision | Source一件の一取得版または一編集版 | id, source_id, revision, locator, content_hash, captured_at, egress_policy |
| ContentChunk | SourceRevision内の引用可能な一範囲 | id, source_revision_id, ordinal, char_start, char_end, text_hash, textまたはcontent locator |
| Claim | 一つの主語・述語・目的語または一つの数値仮説 | id, claim_type, text, confidence, status, created_at |
| Evidence | 一つのClaimと一つの保存済みContentChunkの対応 | id, polarity, source_revision_id, content_chunk_id, char_start, char_end, content_hash, confidence, egress_policy |
| RelationAssertion | sourceとtarget間の意味関係一件 | id, owner_id, assertion_family_id, revision, predicate, status, confidence, valid_from, expires_at, supersedes_id, provenance_id, egress_policy |
| CampaignAuthorizationSnapshot | Campaignで本人が許諾した目的、範囲、送信field、試行予算の一版 | id, campaign_id, revision, purpose, scope_hash, field_categories, run_budget, expires_at, authorized_at |
| ResearchRun | 一回の独立調査 | id, campaign_id, input_snapshot_hash, model_snapshot, status, started_at, completed_at |
| ReportVersion | 一回確定した8章レポート | id, campaign_id, parent_report_id, status, created_at |
| ReportSection | ReportVersion内の一章 | id, report_version_id, section_id 0-7, content_hash |
| AuditEvent | 一つのwrite command結果 | id, operation, actor, target_id, idempotency_key, payload_fingerprint, occurred_at |
| Attachment | local content store内の一blob | id, sha256, media_type, size_bytes, relative_locator, encryption_state |

ContentChunkは原文の構造境界を優先し、目標1,200〜2,400 Unicode文字、上限4,000文字とする。表、見出し、段落を途中で切らない。各chunkはchar offsetとhashを持ち、原本を変更した場合は既存chunkを更新せず、新SourceRevision配下へ再生成する。

## Sourceの粒度

Source一件は「同じlocatorで更新される原本系列」とする。

| 入力 | Source単位 | SourceRevision単位 |
| --- | --- | --- |
| ChatGPT会話 | 保存対象となった一発言または選択範囲 | 原則一版。訂正保存時だけ次版 |
| 名刺 | 一枚の名刺画像または一件のCSV row | OCR、手修正ごとに新しい版 |
| ファイル | 一つの論理path | content hashが変わるごとに新しい版 |
| Web | 一つのcanonical URL | 取得content hashが変わるごとに新しい版 |
| AGENTS.md / SKILL.md | 一つの絶対pathとscope | hashが変わるごとに新しい版 |
| 手入力メモ | 一つのメモ | 保存確定ごとに新しい版 |

会話thread全体を一つの巨大SourceRevisionにしない。conversation IDとmessage IDはmetadataとして保持し、保存対象発言だけを独立Sourceへする。

## revision契約

1. anchor IDは変えない。
2. EntityRevisionは`(owner_id, entity_id, revision)`で一意にする。
3. revisionは1から開始し、欠番を作らない。
4. 新revision作成とCURRENT_REVISION差し替えを一transactionで行う。
5. 過去revisionを更新しない。
6. Correctionは旧revision ID、新revision ID、理由、actor、時刻をAuditEventへ記録する。
7. Claim、RelationAssertion、ResearchRun、ReportVersionは不変とし、訂正時はSUPERSEDES chainを作る。
8. current pointerが二件、欠落、別ownerを指す場合はwriteをrollbackする。

## RelationAssertion契約

業務上の意味関係はNeo4j relationship propertyだけを正本にせず、RelationAssertionノードを正本とする。

RelationAssertionは次の構造edgeを持つ。

- `ASSERTS_FROM` → source anchorまたはClaim。
- `ASSERTS_TO` → target anchor、Claim、Facet。
- `EVIDENCED_BY` → Evidenceを0件以上。inferred、confirmedは1件以上を必須にする。
- `SUPERSEDES` → 直前のRelationAssertion。状態変更時に使用する。

`assertion_family_id`は同じ主語、predicate、目的語の訂正系列を表す。訂正時は旧assertionを書き換えず、同familyでrevisionを一つ増やし、SUPERSEDESで直前版に接続する。

predicate allowlistの初期値は次とする。

- REUSES
- ADDRESSES
- DERIVED_FROM
- WORKS_AT
- HAS_CAPABILITY
- REQUIRES_CAPABILITY
- CAN_CONTRIBUTE_TO
- INTRODUCED_BY
- CLASSIFIED_AS
- EVALUATED_BY
- BASED_ON
- SERVES
- COMPETES_WITH
- DEPENDS_ON
- MERGED_INTO

Lunaはpredicate候補を生成できるが、allowlist外の値を保存できない。CAN_CONTRIBUTE_TO、INTRODUCED_BY、MERGED_INTOは本人確認前にconfirmedへできない。

## 構造edge

構造edgeはアプリが決定的に作成し、Lunaへ選択させない。

| Edge | From | To | 制約 |
| --- | --- | --- | --- |
| OWNS | OwnerProfile | 全owner node | 同じownerのみ |
| HAS_REVISION | anchor | EntityRevision | 同じentity_idのみ |
| CURRENT_REVISION | anchor | EntityRevision | anchorごとに一件 |
| HAS_SOURCE_REVISION | Source | SourceRevision | revision連番 |
| CURRENT_SOURCE_REVISION | Source | SourceRevision | Sourceごとに一件 |
| HAS_CHUNK | SourceRevision | ContentChunk | ordinal一意 |
| EVIDENCE_FROM | Evidence | SourceRevision / ContentChunk | 一つ以上 |
| HAS_AUTHORIZATION | ResearchCampaign | CampaignAuthorizationSnapshot | 有効なcurrent許諾は一件 |
| HAS_RUN | ResearchCampaign | ResearchRun | 同じauthorization系列 |
| USES_SOURCE | ResearchRun | SourceRevision | input snapshotに含まれる版のみ |
| PRODUCED | ResearchRun | ReportVersion | ReportVersion.campaign_idとRun.campaign_idが一致 |
| HAS_SECTION | ReportVersion | ReportSection | section_id 0-7を各一件 |
| REFERENCES_CLAIM | ReportSection | Claim | 章で使用したClaimのみ |
| CITES | ReportSection | Evidence | 章の引用対応があるEvidenceのみ |
| GOVERNED_BY | OwnerProfile | InstructionArtifact | 有効なcurrent revisionのみ |
| HAS_ATTACHMENT | SourceRevision | Attachment | hash一致 |

`claim_ids`、`evidence_ids`、`run_ids`、`sources`の配列はschema v1互換のread projectionに限定する。schema v2の正本は構造edgeとし、互換配列とedgeが一致しないwriteを拒否する。

schema v1の`ResearchMaterial`は新規writeに使わない。独立した資料はSource + SourceRevisionへ、引用範囲はContentChunkへ変換し、旧IDはmigration mappingに残す。

## 名寄せとmerge

PersonとOrganizationの自然キーをIDにしない。氏名、会社名、メール、電話は変更または共有されるためである。

名寄せは次の二段階にする。

1. 決定的候補生成: 正規化メールhash、E.164電話hash、名刺content hash、同一locatorを使用する。
2. Luna候補順位付け: 氏名、所属、役職、会話文脈のshareable projectionだけを使用する。

自動mergeは禁止する。本人がmergeを確定した場合、勝者anchorを残し、敗者anchorをarchivedへ変更し、confirmedのMERGED_INTO assertionを作る。旧ID、revision、関係、根拠は削除しない。検索と新規relationは勝者へredirectする。

## privacyと保存場所

| データ | 保存場所 | 検索 | MCP投影 |
| --- | --- | --- | --- |
| anchor ID、status、kind | Neo4j property | 対象 | policy適用後に可 |
| revisionの短い表示field | Neo4j property / payload | 対象 | allowlist fieldだけ |
| 長文原本、binary | local content store | local index経由 | explicit許諾時だけ |
| email、電話、住所、private note | encrypted local contentまたはlocal_only revision | hash候補生成だけ | 既定で禁止 |
| content hash、locator hash | Neo4j property | 対象 |本文を含めず可 |
| model prompt原文 | 保存しない | 対象外 | 禁止 |
| prompt version、model snapshot | AuditEvent / provenance | 対象 |必要最小限 |

fieldにpolicyがない場合はlocal_onlyとして扱う。node単位policyだけで外部投影を決めず、field allowlistを必須にする。

## Graph RAG検索契約

初期検索はvectorを必須にしない。

1. owner_id、active status、delete state、time validityで候補を絞る。
2. IdeaRevision、AssetRevision、Personの公開表示名、Organization、Claim、ContentChunk、ReportSectionを全文検索する。
3. 上位50件からactive RelationAssertionと構造edgeを最大2 hop展開する。
4. Evidence、SourceRevision、Decision、Experimentを付加する。
5. Lunaへ渡す前にlocal_only fieldを除去し、候補50件をtitle、summary、path、根拠IDへ圧縮する。
6. Lunaで上位10件を再順位付けし、結果ごとに関連理由とpathを返す。
7. Luna失敗時は全文scoreとhop距離の決定的順位へfallbackする。

vector indexを追加する場合もcanonical contentをvectorへ置き換えない。embeddingは派生indexであり、model ID、dimension、source hashを持ち、再生成可能にする。

## 削除契約

- 通常操作はsoft deleteだけを公開する。
- deleted anchorとそのcurrent revisionは通常検索、MCP、現行レポート生成から除外する。
- 過去ReportVersionは削除せず、参照元を`unavailable`としてhash、取得時刻、削除時刻を表示する。
- Attachmentの物理削除は、参照countが0、backup policyを満たす、impact previewを本人が確認した場合だけ別commandで実行する。
- 物理削除commandをMCPへ公開しない。

## schema v2の検査fixture

fixtureは次を固定する。

- 20会話Source、Idea 8件、IdeaRevision 14件。
- 名刺10件、Person 8人、重複候補2組、Organization 5件。
- Asset 12件。うちcapability 5件。
- RelationAssertion 30件。proposed、inferred、confirmed、rejected、expiredを含む。
- 文書5件、SourceRevision 8件、ContentChunk 40件以上。
- Claim 25件、Evidence 35件、矛盾するEvidence 3件。
- Campaign 2件、Run 3件、ReportVersion 3件、ReportSection 24件。
- correction、merge、soft delete、unavailable参照を各一件以上。

検査は停止前manifest、停止、同一volume再起動、再取得manifest、代表10問の検索hash比較までを一つのgateにする。加えて、global ID重複、current revision複数または欠落、revision重複、owner越境assertion、根拠なしinferred / confirmed、SUPERSEDES循環、deletedでsearchableなnodeをそれぞれ0件とするCypherをmanifest生成の必須検査にする。

## 質問リスト

| ID | 質問 | MVP早期の扱い | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-DM-01 | schema v2のRelationAssertion正本化とstable anchor / immutable revision分離を採用するか | MVPの仮データ範囲で採用。実データ投入前に最終確認 | 利用者兼製品責任者 | 2026-09-23 |
| Q-DM-02 | private archiveをアプリ層で暗号化するか | 利用者兼製品責任者 | 実データ投入前 |

## スコープ外

- 複数owner間の共有Graph。
- LLMが作る任意node label、任意predicate、任意Cypher。
- 初期版のvector必須化。
- public MCP endpoint。
- Graph内へのbinary保存。
- 自動名寄せ確定と自動physical delete。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| DM-SP-01 | schema v1からv2へのfixture変換spike | 検査: 20会話と10名刺を変換し、欠落field、孤立edge、重複anchor一覧を出力する | 未知 |
| DM-01 | NodeType、revision、RelationAssertion domain contract | 検査: `backend/tests/test_founder_graph_schema_v2.py`と既存Founder Graph unit testでstable anchor参照、immutable revision、evidence境界、predicate allowlistを確認する | 類推可能 |
| DM-02 | Neo4j schema migration v2 | 検査: constraint、index、owner境界、rollback fixtureが実Neo4jで成功する | 類推可能 |
| DM-03 | schema v2 write adapter | 検査: anchorとrevisionのtransaction、idempotency、revision conflict testが成功する | 類推可能 |
| DM-04 | schema v2 read / Graph RAG adapter | 検査: 代表10問でowner越境0件、private field投影0件、根拠path欠落0件になる | 類推可能 |
| DM-05 | 再起動永続化gate | 検査: 停止前後manifestと代表query hashが一致する | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-DM-01 identity | stable anchorとimmutable revisionを分離する。関係を同一物へ保ち、履歴を上書きしないため | revisionごとにIdeaやPersonを新規作成する案は関係が分断されるため却下 | schema v2で移行 |
| ADR-DM-02 semantic relation | RelationAssertionノードを正本にする。根拠、状態、期限、訂正を一件として扱えるため | Neo4j relationship propertyだけを正本にする案はEvidenceとの参照と履歴が弱いため却下 | schema v2で移行 |
| ADR-DM-03 capability | CapabilityはAsset subtypeにする。創業資産として共通の検索・egress・revision契約を使えるため | 独立Labelは初期schemaの型数を増やすため却下 | `asset_kind=capability`を追加 |
| ADR-DM-04 source content | binaryと長文原本はlocal content store、Neo4jはhash、locator、chunkを持つ | binaryをNeo4j propertyへ保存する案はbackup、検索、更新の責務を混ぜるため却下 | Attachment / ContentChunkで参照 |
| ADR-DM-05 retrieval | graph traversal + full-text + Luna rerankで開始する | 未評価embeddingを必須にする案はモデル能力と再現性が未確認のため却下 | vectorは派生indexとして後置 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | 初版。schema v1を暫定契約とし、stable anchor、immutable revision、RelationAssertion正本、ContentChunkをschema v2に定義 | Neo4j既定化前にデータ粒度を固定するため | DM-SP-01〜DM-05 |
| 2026-09-23 | MVPの仮データ範囲でschema v2を採用し、実装と合成永続化検査を開始 | 全体計画を止めず、実データ投入とは分離して進めるため | P1-SP-01〜P2-04 |
| 2026-09-23 | DM-01のdomain contractを追加し、既存schema v1の保存経路は変更せずにv2値の検証を可能にした | stable anchor、immutable revision、RelationAssertion、ContentChunk、FacetをNeo4j移行前にテスト可能にするため | DM-01 |
