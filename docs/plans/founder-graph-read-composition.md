# Founder Graph read composition 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

### 要望

既存FastAPIアプリへ、in-memoryまたは注入済みNeo4j read serviceを選択できる安全なcomposition境界を追加する。

### ゴール

実機接続を自動開始せず、呼び出し側が明示的に構築したread serviceだけをMCP read routeへ渡せる状態にする。

### 成功指標

- `create_app()`の既定値は現在のin-memory read serviceで、既存API互換性を保つ。
- `create_app(founder_graph_read_service=...)`で注入したserviceがread MCP routeから利用される。
- write serviceとread serviceのowner境界が一致しない注入を拒否する。
- Neo4j driver、credential、環境変数をcomposition関数が自動取得しない。
- fake read serviceだけでrouteのsearch / fetchとowner mismatchを検査できる。

## ユーザーストーリーと受け入れ条件

### US-COMP-1 明示的read service注入

As a local operator, I want to inject a prepared Founder Graph read service, so that Neo4j can be adopted after its live gate without changing MCP routes.

Given: a read service and write service use the same local owner.
When: `create_app` receives the read service explicitly.
Then: the existing MCP read endpoints call the injected service and return its projection.

Given: no read service is supplied.
When: `create_app` is constructed.
Then: the current in-memory read service is used and existing route tests remain green.

Given: an injected read service exposes a different owner than the write service.
When: `create_app` is constructed.
Then: construction fails before any route can serve data.

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-COMP-01 | Neo4j gatewayをdefault compositionへ切り替える時期 | 利用者兼製品責任者 | SP-FG-01 / SP-FG-05のlive gate後 |

## スコープ外

- Neo4j driverの生成、credential読込、環境変数による自動接続。
- `create_app`のdefaultをNeo4jへ変更すること。
- write serviceのNeo4j composition、backup / restore、Docker起動。
- ChatGPT tunnel、Deep Research、外部AI接続。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| COMP-1 | read serviceの注入引数とowner一致検証 | 検査: `backend/tests/test_founder_graph_mcp_api.py`へ注入・不一致ケースを追加し、全backend testsがgreen | 類推可能 |
| COMP-2 | composition境界の文書とself-review | 検査: `py_compile`、`git diff --check`、credential自動取得がないことを確認 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-COMP-1 explicit injection | read serviceを引数で明示注入し、defaultはin-memoryへ固定する。停止中の接続と実機採用を利用者判断まで分離できる | import時または環境変数からNeo4jへ自動接続する案はcredential境界とlive gateを飛ばすため却下 | Q-COMP-01が決まるまで既存挙動を維持しつつ実機adapterを検査できる |
| ADR-COMP-2 owner invariant | read serviceにowner_idを要求し、write serviceと完全一致しない構成を拒否する | routeごとの暗黙owner確認は設定漏れ時にcross-owner readを招くため却下 | composition時点で不整合をfail-fastする |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | 初版。in-memory既定を保ったread service注入境界を定義 | Neo4j read adapterをrouteへ安全に接続するため | COMP-1〜COMP-2 |
| 2026-09-22 | `GraphReadPort`、明示的read service注入、owner一致検証、停止時503を実装 | 構築済みadapterをMCP read routeへ接続できるcomposition境界を追加 | COMP-1〜COMP-2 |

## 実装状況

- `create_app()`はread service未指定時に従来のin-memory `GraphReadService`を構築する。
- `founder_graph_read_service`を明示指定した場合は、そのserviceをMCPのsearch/fetch routeへ渡す。
- write serviceとread serviceの`owner_id`が一致しない構成、および`owner_id`を公開しないserviceは構築時に拒否する。
- Neo4j readの停止・接続失敗はMCPの`unavailable`へ変換し、HTTP 503として返す。
- Neo4j driverの自動生成・credential読込・環境変数接続は引き続き行わない。
