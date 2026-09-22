# Founder Graph Neo4j gateway 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

### 要望

ローカルNeo4jへFounder Graphのtyped node、relation、idempotency auditを書き込める安全なgatewayを作る。任意CypherをMCPへ公開せず、domain write serviceのowner・allowlist・revision契約を維持する。

### ゴール

既存のin-memory write contractを先に検証したまま、Neo4j Python driverを明示注入した場合だけparameterized Cypherへ変換できる永続境界を用意する。

### 成功指標

- NodeTypeとRelationTypeは静的allowlistからのみCypher label/typeへ変換される。
- node properties、payload、auditへ利用者入力を文字列連結せず、全値をparametersで渡す。
- owner mismatch、duplicate ID、idempotency conflict、missing endpointを保存前に拒否する。
- Campaign / Sourceの更新はexpected revisionを要求し、旧payloadをhistory nodeとして残す。
- migration queryは`founder_graph_schema.migration_queries()`を経由し、任意Cypher入力を受けない。
- 外部接続のないfake driverで全契約をテストできる。

## ユーザーストーリーと受け入れ条件

### US-NG-1 parameterized write

As a local owner, I want typed graph writes to use parameterized Cypher, so that user text cannot become query syntax.

Given: an allowlisted domain node and idempotency key are supplied.

When: the gateway writes the node through a driver transaction.

Then: the query uses a static label, parameters contain payload values, and one audit event is recorded.

### US-NG-2 append-only transition

As a local owner, I want Campaign and Source transitions to retain old state, so that research permission and source corrections remain auditable.

Given: a current node and an incoming aggregate revision one higher with the matching expected revision.

When: the gateway writes the transition.

Then: the current properties advance, a history payload is appended, and stale or duplicate revisions fail without mutation.

### US-NG-3 migration boundary

As a local operator, I want schema migration to be explicit and versioned, so that the gateway cannot execute arbitrary Cypher.

Given: a schema target version.

When: migration is requested.

Then: only queries from the local schema plan are executed in order, and an out-of-range version is rejected before driver access.

### US-NG-4 source revision integrity

As a local owner, I want Neo4j Source and SourceRevision writes to enforce the same owner-scoped revision chain as the in-memory boundary, so that a direct gateway caller cannot create orphaned or incorrectly pointed source history.

Given: a SourceRevision or a Source carrying a current_revision_id is supplied.

When: the gateway validates the write inside the same transaction as the mutation.

Then: the parent Source, owner, contiguous revision predecessor, and latest current pointer are checked before any CREATE or SET; invalid references fail without mutation.

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-NG-01 | Neo4j adapterをGraphReadServiceへ接続するhydration形式 | 利用者兼製品責任者 | T-FG-07の実機read spike前 |

## スコープ外

- ChatGPT tunnel、MCP transport、Deep Research、external AI。
- 任意Cypher query API、public endpoint、physical delete。
- Neo4j実機Docker smoke、backup/restore permission gate（local-ops計画のSP-LO-03）。
- Domain object hydrationを伴うGraphReadService統合。Q-NG-01後に別sliceで実装する。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| NG-1 | static label / relation maps、parameterized node / relation write | 検査: `uv run pytest backend/tests/test_founder_graph_neo4j.py -q` がgreen | 類推可能 |
| NG-2 | revision history and audit transaction boundary | 検査: fake driverでreplay、stale revision、foreign owner、missing endpointを検査する | 類推可能 |
| NG-3 | schema migration gateway | 検査: migration planを全件実行し、out-of-range拒否と`git diff --check`を確認する | 既知 |
| NG-4 | Source / SourceRevision owner・chain・current pointer validation | 検査: fake driverでmissing/foreign parent、non-contiguous predecessor、invalid current_revision_idを検査する | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-NG-1 driver注入 | driverを引数で注入し、module import時に接続しない。テストと停止中のfail-closedを保証する | global driverや起動時の自動接続はcredential、停止状態、test isolationを混ぜるため却下 | 接続はapp composition rootの明示操作に限定される |
| ADR-NG-2 query生成 | label/typeだけ静的mapから選び、valuesはparametersへ渡す | user inputをCypherへ連結する案は任意query injectionを招くため却下 | MCPに任意Cypher toolを持たない |
| ADR-NG-3 history | mutable current nodeとimmutable JSON history nodeを分け、audit eventを同一transactionへ置く | current nodeの上書きだけでは訂正前のpayloadが失われるため却下 | Campaign / Source updateでも旧状態を追跡できる |
| ADR-NG-4 source reference lookup | Source/SourceRevisionの参照値をparameterized node propertiesとして保存し、static label queryで同一ownerの履歴を検証する | payload JSONをCypher側で解釈する案はdriver/Neo4j依存が増え、任意のJSON path入力も許すため却下 | write validationはCREATE/SETより前に同一transactionで実行される |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | 初版。Neo4j parameterized gatewayとmigration境界を定義 | ローカルNeo4j候補をdomain contractへ接続するため | NG-1〜NG-3 |
| 2026-09-22 | Source/SourceRevisionのowner・revision chain・current pointer検証を追加 | direct gateway経由の孤立参照と不正current pointerを防ぐため | NG-4 |

## 実装メモ

- 計画タスク: NG-4
- 受け入れ条件: US-NG-4
- 追加テスト: `backend/tests/test_founder_graph_neo4j.py` の `test_source_revision_rejects_missing_parent_before_create`、`test_source_revision_rejects_foreign_parent_before_create`、`test_source_rejects_invalid_current_revision_pointer_before_create`
- エラー分類: 回復可能な `GraphWriteError` / `GraphWriteNotFoundError`。検証失敗時はCREATE/SETを実行しない
- API互換性: 影響なし。driver注入とtyped write APIは維持
- ループ周回数: 1
- 検査結果: `uv run --isolated --python 3.14 pytest backend/tests/test_founder_graph_neo4j.py -q` → 8 passed; `uv run --isolated --python 3.14 python -m py_compile backend/dots/founder_graph_neo4j.py backend/tests/test_founder_graph_neo4j.py` → pass; `git diff --check` → pass

## 既知の制約

- 実Neo4jへの接続、Docker smoke、既存DBのmigration/backfillはこのsliceで実施していない。
- SourceRevisionの参照検証は、gatewayが保存する`source_id`、`supersedes_id`のtyped propertiesを前提にする。既存のpayload_jsonだけで保存されたデータのbackfillは実機migration sliceで扱う。
- GraphReadServiceへのNeo4j接続とMCP compositionは別タスクのままであり、この変更だけではruntimeの既定driverを切り替えない。
