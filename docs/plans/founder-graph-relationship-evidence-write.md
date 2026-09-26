# Founder Graph 根拠付き関係保存 計画

最終更新: 2026-09-24
親計画: [Dots実装全体計画](dots-implementation-master-plan.md)
データ契約: [Founder Graphデータモデル](founder-graph-data-model.md)

## 要望 / ゴール / 成功指標

要望: ChatGPTから保存したアイデアと人物を、会話の根拠・確からしさ・有効期限付きで結び付ける。

ゴール: SourceRevision、ContentChunk、Evidence、RelationAssertionをschema v2の同一契約で保存し、ローカル検索まで根拠をたどれるようにする。

成功指標: 同じ合成会話をMCP経由で保存し、根拠付きの人物―アイデア関係を作成して検索したとき、ID・状態・確信度・期限・根拠参照が保持され、本文・連絡先が応答に含まれない。

## ユーザーストーリーと受け入れ条件

### US-GR-01 出典をたどれる会話保存

As a Founder Graph owner, I want a saved idea to return opaque source references, so that a later relation can cite the conversation without sending its text again.

Given: capture_idea receives synthetic source text.

When: The write succeeds or the same idempotency key is replayed.

Then: The same SourceRevision ID and deterministic ContentChunk IDs are returned with no source text, contact data, locator, or private fields.

Given: A durable audit written before ContentChunk receipts were added has the historical fingerprint `payload_fingerprint("capture_idea", idea, source, source_revision, owner_id)` and no source or chunk receipt IDs.

When: `capture_idea` is retried with the matching payload and idempotency key.

Then: Dots transactionally backfills the deterministic ContentChunk nodes, leaves the original audit unchanged, records one separate opaque backfill audit event, and returns the same SourceRevision and chunk IDs on every retry without returning or logging source text.

### US-GR-02 SourceRevisionに結び付く根拠

As a Founder Graph owner, I want an Evidence record to identify a saved Claim and an exact source range, so that graph conclusions can be reviewed.

Given: An active Claim and an active ContentChunk from the same owner exist.

When: capture_evidence is called with their IDs.

Then: Dots creates one immutable Evidence that resolves to the same-owner SourceRevision and chunk, derives its locator and text hash internally, and exposes no chunk text.

### US-GR-03 人物とアイデアの関係

As a Founder Graph owner, I want a person-to-idea relation to cite saved Evidence, so that I can decide who to work with and why.

Given: Active same-owner Person and Idea records and at least one valid same-owner Evidence exist.

When: link_entities receives CAN_CONTRIBUTE_TO or INTRODUCED_BY.

Then: Dots writes an immutable RelationAssertion node with ASSERTS_FROM, ASSERTS_TO, and EVIDENCED_BY structural edges in one transaction; its status is only proposed or inferred, with confidence and expiration.

### US-GR-04 Safe relation search

As a Founder Graph owner, I want search and fetch to show the safe relation path, so that I can inspect why two assets were linked.

Given: A RelationAssertion and its Evidence are stored.

When: search or fetch returns the relation.

Then: The projection includes only egress-authorized assertion fields and opaque Evidence references, while excluding ContentChunk text, SourceRevision content, and local-only endpoint names or contact fields.

### US-GR-05 Explicit source history and chunk path

As a Founder Graph owner, I want source revisions and their content chunks to have explicit graph connections, so that evidence can follow the source path without trusting copied pointer fields.

Given: A same-owner Source, its consistent SourceRevision history and current revision, and ContentChunks with unique ordinals exist.

When: Dots writes or replays these records, or runs the schema v2 data-repair preview and apply operation.

Then: The graph contains one Source-to-SourceRevision history edge, exactly one current edge for the current revision, and one SourceRevision-to-ContentChunk edge per chunk; in-memory and Neo4j results match. Preview writes nothing. Apply adds only missing correct edges after full preflight, and any foreign-owner, malformed, duplicate, or contradictory record stops before mutation. Repeating apply creates no duplicate edge or audit event.

## スコープ外

- 実会話、名刺、その他の実データ。
- 外部Deep Research、Web検索、または外部AIへの送信。
- ネットワーク関係の自動confirmed化、人物の自動統合、物理削除。
- 任意Cypher、汎用node upsert、新しい独立Label。
- ResearchMaterialへの新規write。

## 質問リスト / 利用者判断boundary

追加の利用者判断はない。採用済みschema v2に従い、実データ投入の判断はP9まで保留する。

## ContentChunk生成規則

- SourceRevisionの文字列をUnicode code point単位で連続する範囲へ分割する。各chunkは半開区間[char_start, char_end)を持ち、空chunkと重複範囲を作らない。
- 1 chunkの目標は2,400文字、上限は4,000文字とする。目標位置より前に段落境界があれば直近を選び、なければ文末、空白の順に選ぶ。
- 4,000文字以内に境界がなければ上限位置で分割する。次のchunkは直前chunkの終了位置から始める。
- 全chunkのtextを順に連結した結果はSourceRevision.contentと完全一致し、text_hashとcontent_hashを再計算して一致させる。
- 空本文はSourceRevisionだけを保存し、ContentChunkを作らない。この場合capture_evidenceは該当IDを拒否する。

`capture_evidence` はGR-WR-01Aの構造edgeと既存データ補修gateが完了するまで実装・公開しない。schema versionはv2のままとし、制約・索引を作るschema migrationと既存graphのdata repairを分離する。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| GR-WR-01 | capture_idea時の決定的ContentChunk生成と、SourceRevision / chunk IDだけを含む後方互換WriteReceipt | 検査: 4,000 Unicode文字上限、CRLF一つと空行CRLF二つの境界、連続offset、再構成hash、空本文、冪等再送、旧fingerprint監査からの安全なchunk backfill、本文非返却をin-memory / Neo4j parityで確認する | 類推可能 |
| GR-WR-01A-MEM | in-memoryのsource-chain repair preview/apply契約、事前検査、focused test | 検査: `uv run pytest backend/tests/test_founder_graph_source_repair.py -q` で全件事前検査、preview無変更、不足edgeだけの追加、監査の重複防止、矛盾時停止を確認する | 類推可能 |
| GR-WR-01A-N4J | Neo4j parityとtransactionalなsource-chain repair preview/apply。preflightの全read、不足edge、決定的auditをapplyの単一`execute_write` callback内で実行する | 検査: Neo4j source-repair testでpreview read-only、foreign/malformed/contradictory graphのfail-closed、edge/audit同一transaction、rollback、再実行時audit重複なしを確認する | 類推可能 |
| GR-WR-02A | GR-WR-01A完了後のv2 Evidence内部保存契約 | 検査: Claim、Chunk、SourceRevisionの型・存在・ownerとHAS_CHUNK lineageを確認し、呼出元にexcerpt / locator / source textを要求せず、Evidence、EVIDENCE_FROM、監査をmemory / Neo4jで原子的・冪等に保存する。same-key/same-payloadは同じreceipt、payload変更はconflict、foreign existenceは非開示。安全な内部read projectionにclaim/chunk/revision ID・locator・本文を含めず、旧material参照はread-only互換とする | 類推可能 |
| GR-WR-02B | GR-WR-02A完了後に公開する用途限定capture_evidence MCP write | 検査: MCP / API / stdioの閉じた入力schemaからGR-WR-02Aだけを呼び、共通receiptを返す。ownerやexcerpt / locator / source textの入力を拒否し、tool discovery、再送、safe errorを確認する | 類推可能 |
| GR-WR-03 | link_entitiesからのv2 RelationAssertion保存 | 検査: endpoint / Evidence検証、immutable revision、supersedes、status境界、監査をin-memory / Neo4jで一致させる。Evidenceは同一ownerのactive ContentChunkとSourceRevisionへEVIDENCE_FROM / HAS_CHUNKが各1本だけで到達し、誤ラベル・foreign ownerを含む余分な辺を拒否する。旧materialのみのEvidenceも拒否する。owner_id + assertion_family_id + revisionの重複をschema v5のNeo4j複合unique制約でも拒否する。RelationAssertion focused 54 passed、全backend 894 passed/5 skipped、py_compileとdiff check passed | 完了 |
| GR-WR-04 | assertionを通るsearch / fetchのsafe projection | 検査: status、confidence、expires_at、path、Evidence IDを保持し、local_only fieldの流出が0件になる | 類推可能 |
| GR-WR-05 | stdioからNeo4j再起動後の統合保存・検索gate | 検査: 合成Idea、Claim、Evidence、RelationAssertionを保存し、同じvolume再起動後も同じIDと検索経路を得る。本文は応答artifactに0件とする | 類推可能 |

## 検査コマンド

- Focused backend: uv run pytest backend/tests/test_founder_graph_evidence_write.py backend/tests/test_founder_graph_mcp_write.py backend/tests/test_founder_graph_mcp_api.py backend/tests/test_founder_graph_write.py backend/tests/test_founder_graph_neo4j_write_parity.py backend/tests/test_founder_graph_read.py backend/tests/test_founder_graph_neo4j_read.py backend/tests/test_founder_graph_mcp_stdio.py -q
- Full backend: uv run pytest
- Static/runtime checks: python -m py_compile backend/dots/founder_graph.py backend/dots/founder_graph_mcp_write.py backend/dots/founder_graph_write.py backend/dots/founder_graph_neo4j.py
- Patch check: git diff --check

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| 根拠の単位 | SourceRevision内のContentChunkを引用元にする。開始位置・終了位置・hashを再検証できるため | 呼出元が任意excerptやResearchMaterial IDを送る案は、実在する保存内容との一致を証明できないため却下 | 本文はDots内に留め、MCPには不透明IDだけを渡す |
| source-chain edgeと既存graph補修 | 既に承認済みのschema v2 contractを満たす固定用途data-repair operationとして分離する。全記録を事前検査し、正常なedgeは保持し、不足分だけを同じtransactionで追加する | DDL migrationにdata修復を混ぜる案は、現行migrationがschema versionをDBに記録せず制約・索引だけを扱うため却下。schema v3化は既存v2 contractだけでは不要。矛盾edgeを自動削除・張替えする案は履歴・根拠を壊しうるため却下 | owner / history / current pointer / chunk整合性の矛盾があれば無変更で停止し、対象を限定して報告する。正常なら再実行可能で追加重複なし |
| 旧Evidence互換 | 旧material_id値は読取・変換互換だけに残し、新規writeはSourceRevision / ContentChunkへ統一する | ResearchMaterialを新規writeし続ける案はschema v2の正本と分岐するため却下 | 既存データを破壊せず、新規データだけv2化 |
| 関係の正本 | RelationAssertionノードと3種類の構造edgeを同じtransactionで保存する | Neo4jの直接relationshipだけを保存する案は、根拠・履歴・状態を検索で失うため却下 | v1 relationshipは既存読取互換に限定 |
| 人脈関係の状態 | CAN_CONTRIBUTE_TOとINTRODUCED_BYはEvidence、confidence、expires_atを必須とし、proposed / inferredに留める | 推定をconfirmed扱いする案は本人確認なしに人間関係を確定するため却下 | confirmed化は別の明示確認操作だけに限定 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-09-24 | SourceRevisionからEvidence、RelationAssertion、safe searchまでのschema v2 write/read境界を定義 | 人物とアイデアを結ぶ主要価値を、旧Relationshipと未検証Evidence参照から切り離すため | GR-WR-01〜05 |
| 2026-09-24 | capture_ideaのFastAPI receipt、初回・再送応答、両backendのfingerprint parityをfocused検査へ追加 | 独立reviewでAPI receiptのopaque参照欠落とderived chunkを含まないfingerprint差を検出したため | GR-WR-01 |
| 2026-09-24 | capture_ideaのfingerprintを履歴互換に戻し、receipt参照のない旧監査からのtransactional backfillとCRLF境界検査を追加 | GR-WR-01 reviewで永続再送の旧fingerprint不一致とCRLF誤分割を検出したため | GR-WR-01 |
| 2026-09-24 | Evidenceの前にSource / Revision / Chunk構造edgeと既存graphの安全な補修を必須gateとして追加 | schema v2のedge契約がNeo4jとin-memoryのwrite実装にまだ存在しないことを監査で確認したため | GR-WR-01A、GR-WR-02 |
| 2026-09-27 | GR-WR-01Aをin-memory契約とNeo4j transaction parityの独立packetに分割 | 全件preflightと同一transactionの補修・監査を500行以内で安全にレビューできる単位へ分けるため | GR-WR-01A-MEM、GR-WR-01A-N4J |
| 2026-09-27 | Neo4j repairの全read/writeを一回のwrite transactionへ閉じ、foreign/不正record検査とrollback/replay検査を完了条件へ明記 | implementation時にread/write分離が契約の原子性を満たさないことを確認したため | GR-WR-01A-N4J |
| 2026-09-27 | GR-WR-02を内部保存GR-WR-02AとMCP公開GR-WR-02Bへ分割し、両方の完了を元の受入条件とする | 完成実装が500行目安を超えたため、機能を削らず独立レビューできる順序へ分割するため | GR-WR-02A、GR-WR-02B |
| 2026-09-27 | capture_evidenceをMCP / API / stdioへ公開し、閉じた入力schema、共通receipt、extra field拒否を確認。focused 79 passed、全backend 882 passed / 5 skipped | 保存済み根拠だけをChatGPTから指定でき、本文やlocatorを入力・応答へ出さない公開境界を完成させるため | GR-WR-02B |
| 2026-09-27 | GR-WR-03の両writerでEvidenceのsource lineageの全辺数と期待endpointをtransaction / lock内に検証し、RelationAssertion family revisionの複合unique制約をschema v5に追加。RelationAssertion focused 54 passed、全backend 894 passed / 5 skipped、使い捨てNeo4j実機1 passed、py_compileとdiff check passed。通常DBにはmigrationを適用しない | family単位のアプリ検査だけではNeo4j上の重複revisionを制約できず、余分な誤ラベルまたはforeign ownerのEVIDENCE_FROM / HAS_CHUNK辺を既存の一意edge確認が見逃したため | GR-WR-03 |
