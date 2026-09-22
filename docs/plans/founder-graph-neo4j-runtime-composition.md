# Founder Graph Neo4j runtime composition 計画
最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: Neo4j を選択した実行時に MCP の読み書きが同一の owner-scoped 永続 gateway を使い、プロセス再起動後もデータが in-memory に取り残されない構成を追加する。

ゴール: Neo4j adapter を明示的に注入した stdio/API composition を提供し、デフォルトの in-memory 開発経路を壊さずに永続経路を検証可能にする。

成功指標: Neo4j gateway adapter の contract test が通り、同一 adapter が `put_node`、`get_node`、`link_entities`、`record_correction` を owner/idempotency/revision 境界付きで提供し、Neo4j 経路を自動起動しない。

## ユーザーストーリーと受け入れ条件

### US-1

As a single Founder Graph owner, I want the MCP write surface to use a persistent Neo4j adapter, so that a process restart does not discard graph writes.

Given: A `Neo4jGraphGateway` and owner id are explicitly injected.
When: A caller creates the Neo4j write adapter and writes a node.
Then: The adapter delegates the write to the gateway and exposes the same owner id without constructing an in-memory store.

### US-2

As a single Founder Graph owner, I want relationship and correction commands to resolve persisted nodes safely, so that command behavior remains consistent across storage backends.

Given: A node record is returned by the owner-scoped Neo4j query.
When: The MCP surface resolves an endpoint or correction target.
Then: Only the allowlisted id, owner, node type, and correction fields are reconstructed; malformed or foreign records fail closed.

### US-3

As the product owner, I want Neo4j activation to be explicit, so that local development cannot silently switch persistence or create a hidden database dependency.

Given: No Neo4j gateway is passed to composition.
When: The default app or stdio server is created.
Then: The existing in-memory path remains active and no Neo4j driver or network connection is created.

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
|---|---|---|---|
| Q-1 | 実 Neo4j driver の接続設定を環境変数で提供する工程をいつ有効化するか | 利用者兼製品責任者 | live Neo4j gate 前 |

## スコープ外

- Neo4j driver の自動インストール、Docker 起動、環境変数の自動生成
- 実データの移行、バックアップ復元、embedding index の追加
- ChatGPT の Tunnel 登録、Deep Research の実行、外部 API key の投入
- in-memory adapter の削除

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-N4J-01 | Neo4j persisted node projection と write adapter | 検査: `uv run --isolated --python 3.14 --with pytest pytest -q backend/tests/test_founder_graph_neo4j_runtime.py` が通る | 類推可能 |
| T-N4J-02 | MCP write surface の backend-neutral typing と correction hydration | 検査: `uv run --isolated --python 3.14 --with pytest pytest -q backend/tests/test_founder_graph_mcp_write.py backend/tests/test_founder_graph_neo4j_runtime.py` が通る | 類推可能 |
| T-N4J-03 | 明示注入用 composition helper と default path 回帰 | 検査: `uv run --isolated --python 3.14 --with pytest pytest -q backend/tests/test_founder_graph_neo4j_runtime.py backend/tests/test_founder_graph_mcp_stdio.py backend/tests/test_founder_graph_mcp_api.py` が通る | 既知 |
| SP-N4J-04 | 実 Neo4j driver / 再起動後の read-write 一致を合成 fixture 外で確認する手順 | 検査: Neo4j起動、schema migration、write、停止、再起動、read-backを30分以内に同一ownerで記録する | 未知・先行スパイク |
| T-N4J-04 | Neo4j live gate の未実施記録 | 検査: `rg -n "live Neo4j|未実施|T-N4J-04" docs/plans/founder-graph-neo4j-runtime-composition.md docs/HANDOFF.md` | 未知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| 永続 adapter の境界 | `Neo4jGraphGateway` を owner-bound port として薄く包む。Cypher は gateway に限定する。 | MCP surface から直接 Cypher を発行する案は、owner/allowlist/audit 境界を分散させるため却下。 | read/write の composition を同一 gateway 系統に保てる。 |
| persisted node の再構成 | endpoint は最小 projection、Idea/Claim correction は allowlisted domain reconstruction に限定する。 | 全 NodeType の汎用 dataclass hydrator は型・遷移規則の漏れが大きいため後工程へ送る。 | correction と link の必要範囲だけを検証できる。 |
| activation | factory/helper への明示注入だけを許可する。 | 環境変数を読んで default app が自動接続する案は、開発環境の不可逆な状態変化を招くため却下。 | 未接続時の挙動が決定的になる。 |

## 実装メモ

- `backend/dots/founder_graph_neo4j_write.py` に `Neo4jGraphWriteService` と `PersistedNodeReference` を追加した。
- `backend/dots/founder_graph_neo4j.py` に owner-bound `fetch_node_record` を追加した。Cypherはgateway内に限定している。
- `backend/dots/founder_graph_runtime.py` に read/write 同一gatewayの明示 factoryを追加した。stdioには `create_neo4j_stdio_server` から注入できる。
- Idea / Claimだけを correction 用に再構成し、他のNodeTypeは関係endpoint用の最小projectionとして扱う。
- `backend/dots/main.py` に `create_neo4j_app` を追加し、FastAPIでも同じ明示 compositionを利用できるようにした。
- 検査: `330 passed, 17 skipped, 5 warnings`（全backend tests）。Neo4j実driver、Docker、ChatGPT接続は未実施。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-09-22 | 初版作成 | in-memory-only gap を閉じるため | T-N4J-01〜04 |
| 2026-09-22 | Neo4j write adapter、bounded hydration、明示 composition helperを追加 | 永続経路の read/write 混在を防ぐため | T-N4J-01〜03 |
