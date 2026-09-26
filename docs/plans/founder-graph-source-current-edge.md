# Source 現行改訂エッジ同期計画

最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: 既存の内部 Source 改訂更新が、Source の現行改訂ポインタと `CURRENT_SOURCE_REVISION` 構造エッジを同じ書き込みで同期する。

ゴール: owner-scoped Source の expected_revision に基づくrevision+1更新後、typed pointer と current edge が同じ最新 SourceRevision を指し、既存の `HAS_SOURCE_REVISION` 履歴を保つ。

成功指標: current_revision_idが非nullの更新後は両adapterで一致するcurrent edgeが正確に1本、nullの更新後は0本となる。InMemoryではaudit失敗後にnode、history、edge、audit、idempotencyが更新前へ戻る。Neo4j fakeではSource設定、edge差し替え、auditが同じexecute_write callbackで実行され、target不在またはaudit失敗ではreceiptが返らない。実DB rollbackはこのpacketの合格範囲に含めない。

## ユーザーストーリーと受け入れ条件

### US-1 内部 Source 改訂更新

As a Source 書き込み経路, I want owner-scoped Source の改訂更新と現行エッジ差し替えを一つの書き込み内で行いたい, so that typed pointer とグラフ traversal が同じ現行改訂を示す。

Given: 同一ownerのSourceがrevision 1、SourceRevision 1が保存済みで、SourceRevision 2が検証済みかつSourceRevision 1をsupersedeしている。
When: 既存の `put_node(Source, expected_revision=1)` がrevision 2のポインタで成功する。
Then: Sourceのrevisionと`current_revision_id`がrevision 2へ進み、`current_revision_id`が非nullならownerのSourceから出る`CURRENT_SOURCE_REVISION`はrevision 2向けの1本だけ、nullなら0本となり、`HAS_SOURCE_REVISION`履歴は維持される。

### US-2 更新失敗のロールバック

As an InMemory Source 書き込み経路, I want audit保存失敗時に現行辺を含む変更を戻したい, so that不完全な更新が見えない。

Given: InMemory adapterに既存Sourceがあり、全node、history、edge、audit、idempotencyのsnapshotがある。
When: expected_revisionを検証した更新後、audit追加時に失敗する。
Then: InMemory adapterの更新前snapshotと全項目が一致し、Source pointerおよびcurrent edgeのどちらも進まない。

### US-3 再送の非変更性

As a Source capture 呼び出し元, I want 更新後の同じ capture_source 要求を再送しても既存receiptだけを受け取りたい, so that古い再送が現行改訂を巻き戻さない。

Given: capture_source成功後に既存のSource更新が完了し、Sourceとedgeのsnapshotを取得している。
When: 初回と同一key・payloadのcapture_sourceを再送する。
Then: replay receiptを返し、Source、history、edge、audit、idempotencyはsnapshotから変化しない。

## 質問リスト

なし。MCP公開操作や新しいSource改訂APIはこの変更に含めない。

## スコープ外

- 新しいMCP tool、HTTP API、Source revision command、UI workflow。
- SourceRevision nodeのappend transaction自体の変更。既存のimmutable revision保存契約を維持する。
- Neo4jでの並行stale-update直列化と、最終更新query内のrevision compare追加。
- `HAS_SOURCE_REVISION` の履歴形式、schema、migration、archive/restore意味の変更。
- 通常DBへの書き込み、サービス再起動、runtime登録先の変更。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| RP-SOURCE-CURRENT-EDGE-01 | InMemory/Neo4jの既存Source expected_revision update時に、同じlock/transaction内でowner-bound current edgeを差し替える。focused回帰テストと本計画を追加 | 検査: current edge cardinality/pointer parity、逐次stale revision拒否、InMemory audit fault rollback全snapshot一致、Neo4j query owner filter/order、capture replay read-onlyを確認する focused tests と `git diff --check` | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 更新境界 | 既存 `put_node(Source)` のowner/expected_revision/revision-history検証後、Source node更新・current edge差し替え・auditを同じlock/transactionに置く | 別commandを追加するとcaller/workflow/API scopeが広がる。pointer更新後に後続edge書き込みすると部分状態が見える | 既存の内部更新契約だけを整合させ、MCPで新しい改訂操作を公開しない |
| edge更新 | 対象Sourceの旧`CURRENT_SOURCE_REVISION` edgeだけを置換し、新targetが同じownerの検証済みSourceRevisionであることを確認する | 全Source edgeの再構築は既存履歴を誤変更する可能性がある | `HAS_SOURCE_REVISION` とsupersedes履歴は不変のまま保つ |

## ロールバック

PR前は変更したwrite adapterと回帰テストを戻す。schema migration、通常DB書き込み、runtime変更はないためデータmigrationやservice rollbackは発生しない。

## 既知の制約と次の依存

Neo4jの既存 `put_node` は保存済みrevisionを読み取ってからSourceを更新する構成であり、最終書き込みquery内のowner-scoped revision比較・lockは行わない。このpacketは単一更新のSource pointer/current-edge parityと同一transaction内のaudit順序を保証するが、並行する古い更新同士の競合防止を保証しない。後続packetでowner-scoped lockとrevision compareを同じatomic update queryへまとめ、並行stale更新の回帰検査を追加する。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | Source typed pointer更新時のcurrent-edge parity、expected_revision、rollback、replay受入条件と並行更新の除外境界を定義 | `put_node(Source)` がtyped pointerを進めても `CURRENT_SOURCE_REVISION` を同期しない不整合を閉じ、既存のNeo4j競合制御不足を別packetに分離 | RP-SOURCE-CURRENT-EDGE-01 |
