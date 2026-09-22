# Founder Graph Neo4j read adapter 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

### 要望

既存のNeo4j write gatewayに、ローカルFounder GraphのNodeView、SearchPage、関係一覧を返すread-only adapterを追加する。adapterは注入済みdriverを使い、owner境界、current status、field allowlist、parameterized Cypherを維持する。

### ゴール

Neo4jに保存されたpayloadをdomain objectへ再構成せず、read contractのNodeViewへ限定投影して、既存のin-memory read contractと同じ形式で検証できる永続read境界を用意する。

### 成功指標

- fetchは指定ownerのcurrent nodeだけをNodeViewへ変換し、別owner・欠落・非current nodeをnot-foundとして扱う。
- searchはowner、current status、limit、cursor、timeoutを守り、検索結果と一-hop relation pathをSearchPageへ変換する。
- relationsはownerが一致する関係だけを返し、source/targetのidとstatic relation typeを返す。
- `payload_json`からread field allowlistに含まれる値だけをNodeView.fieldsへ入れる。
- Cypherへ利用者入力を連結せず、label/typeもquery文字列の入力から生成しない。
- fake driverだけでowner境界、projection、pagination、relation path、query parameter化を検査できる。
- driver停止やセッション失敗は再試行可能な`unavailable`としてMCP / HTTP境界へ伝播し、入力不正と区別される。

## ユーザーストーリーと受け入れ条件

### US-NGR-1 owner-scoped fetch

As a local owner, I want to fetch one persisted Founder Graph node, so that ChatGPT can read a stable safe view from Neo4j.

Given: a node row has the requested id and the local owner id.
When: `fetch` is called with that id and owner id.
Then: a NodeView is returned with an allowlisted fields mapping and no raw payload field outside the mapping.

Given: a node row belongs to another owner or has a non-current status.
When: `fetch` is called.
Then: GraphReadNotFoundError is raised and no row from another owner is returned.

### US-NGR-2 bounded search

As a local owner, I want keyword search over persisted graph nodes, so that one conversation can reuse earlier founder assets.

Given: current rows contain owner-scoped searchable text and a query has valid limit, cursor, and timeout values.
When: `search` is called.
Then: a SearchPage is returned with deterministic score ordering, a decimal next cursor, and owner-scoped NodeViews.

Given: a matched node has an owner-scoped relation to another current node.
When: `search` is called.
Then: the related node can appear with a half-score and a `(source_id, relation_type, target_id)` path.

### US-NGR-3 relation listing

As a local owner, I want to list persisted relations around one node, so that graph navigation can use the same owner boundary as search.

Given: the requested node exists for the local owner.
When: `relations` is called.
Then: only relations whose two endpoints belong to the local owner are returned in stable id order.

Given: the requested node is missing or belongs to another owner.
When: `relations` is called.
Then: GraphReadNotFoundError is raised without exposing endpoint rows.

### US-NGR-4 static query and projection boundary

As a local operator, I want read queries to remain fixed and parameterized, so that graph text cannot become Cypher or cross the local owner boundary.

Given: a query, node id, or relation request contains Cypher-like text.
When: the adapter executes a read.
Then: the text appears only in query parameters, the executed query remains one of the static read statements, and no arbitrary Cypher entry point exists.

Given: the Neo4j driver cannot open or complete a session.
When: a read MCP route is called.
Then: the route returns an `unavailable` error with HTTP 503 semantics and does not expose driver details.

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-NGR-01 | GraphReadService本体へNeo4j adapterを接続するcomposition rootの切替時期 | 利用者兼製品責任者 | Neo4j実機read spike前 |

## スコープ外

- `create_app`のdefault repository切替、FastAPI route変更、MCP tool追加。
- domain dataclassへの完全hydration、write historyの読み取り、auditの公開。
- Neo4j実機起動、Docker permission gate、backup/restore検証。
- embedding、rerank、Deep Research、外部LLM接続。
- 任意Cypher、任意label/type、public endpoint、物理削除。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| NGR-S1 スパイク | 既存write payloadとNodeViewのrow shapeを照合し、projection方式を決定 | 検査: `founder_graph_neo4j.py`、`founder_graph_read.py`、既存fake driverを読み、payload_jsonからallowlistへ投影できることを確認する | 未知 |
| NGR-1 | 注入driver向けfetch adapterとrow hydration | 検査: owner一致、foreign owner、non-current、malformed payload、field allowlistのfocused pytest | 類推可能 |
| NGR-2 | parameterized search、pagination、one-hop path | 検査: keyword score、stable cursor、neighbor half-score、timeout validation、query文字列非連結のfocused pytest | 類推可能 |
| NGR-3 | owner-scoped relation listing | 検査: endpoint owner boundary、stable order、missing node、static relation queryのfocused pytest | 類推可能 |
| NGR-4 | adapter documentation and export contract | 検査: `py_compile`、focused pytest、`git diff --check`、計画の曖昧語検査 | 既知 |
| NGR-5 | driver failureからMCP / HTTP unavailableへのmapping | 検査: fake driver failure、MCP error code、HTTP 503、秘密情報非露出をfocused pytestで確認する | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-NGR-1 hydration | write gatewayが保存した`payload_json`をJSON objectとして読み、既存read allowlistからNodeViewへ限定投影する。domain dataclassの再構成を避け、read-only境界を小さく保つ | 全domain dataclassをNeo4j rowから再構成する案はconstructor差分、datetime、将来のschema変更をread adapterへ持ち込むため却下 | payloadの解析失敗はrecoverable read errorとして扱う |
| ADR-NGR-2 query shape | fetch、search nodes、search relations、relationsを固定Cypherとして定義し、利用者値はparametersへ渡す | query textを文字列連結する案とlabel/typeを利用者入力から作る案はquery injectionとowner漏えいの経路になるため却下 | static query contractをfake driverで検査できる |
| ADR-NGR-3 adapter placement | `founder_graph_neo4j_read.py`を新設し、既存GraphReadServiceとNeo4j write gatewayを変更しない | 既存GraphReadServiceへdriver分岐を追加する案はcomposition、in-memory契約、実機接続を同時変更するため却下 | Q-NGR-01を残したままread sliceを独立検証できる |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | 初版。Neo4j read adapterの契約、projection、static query境界を定義 | write gateway後のread persistence境界を独立検証するため | NGR-S1〜NGR-4 |
| 2026-09-22 | NGR-S1を完了。`payload_json`から既存allowlistへ投影し、`founder_graph_neo4j_read.py`へ独立adapterを実装 | domain dataclass再構成を避けたread境界でfake driver契約を検証できるため | NGR-1〜NGR-4 |
| 2026-09-22 | driver停止を`unavailable`へ分類する受入条件を追加 | 停止中アクセスを入力不正と混同せず、再試行可能な境界へ揃えるため | NGR-5 |

## 実装メモ

- 計画タスク: NGR-S1、NGR-1、NGR-2、NGR-3、NGR-4、NGR-5
- 受け入れ条件: US-NGR-1〜US-NGR-4とdriver停止時のunavailable境界
- 追加テスト: `backend/tests/test_founder_graph_neo4j_read.py`、`backend/tests/test_founder_graph_mcp.py`、`backend/tests/test_founder_graph_mcp_api.py`
- エラー分類: payload破損・入力不正は回復可能なGraphReadError、driver障害はNeo4jReadUnavailableError
- API互換性: `create_app`のdefaultとMCP route形状は維持。明示的read service注入は`founder-graph-read-composition.md`で管理し、Q-NGR-01のdefault切替を保留
- ループ周回数: 1
- 検査結果: Neo4j read focused 7 passed、MCP/API unavailable focusedを含むbackend全体 250 passed / 16 skipped; `py_compile` → passed; `git diff --check` → passed
