# Founder Graph Source lineage delivery plan

最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: 既存のSource captureが、Source・Revision・Chunk間の構造的な系譜を保存し、同じ要求の再送で後続の状態を変更しないようにする。

ゴール: InMemoryとNeo4jの`capture_source`に3つのSource系譜辺を加え、再送時は記録済み受領結果だけを返す。

成功指標: 初回登録で3辺がノードと監査記録と同じwrite boundaryに保存され、後続revisionの後に同一要求を再送してもノード・辺・監査状態が不変である。Archive後の再送は別のlive acceptance gateで検証し、このmain packetの成功指標に含めない。

## ユーザーストーリーと受け入れ条件

### US-1 保存Sourceの系譜を辿る

As a Founder Graph user, I want a captured source's revision and chunks to have explicit graph edges, so that claims and evidence can refer to stored provenance.

Given: 同一ownerの初回Source、SourceRevision、自作要約から作ったContentChunkがある。
When: `capture_source`を実行する。
Then: `HAS_SOURCE_REVISION`、`CURRENT_SOURCE_REVISION`、`HAS_CHUNK`の各辺がSource・Revision・Chunkと監査記録と同じ原子的write内に一度だけ保存され、別ownerや外部取得を追加しない。

### US-2 同一要求の再送で状態を巻き戻さない

As a Founder Graph user, I want an identical retry to return its original receipt without repairing or changing graph state, so that later source updates and archival remain intact.

Given: 初回capture後、Sourceのcurrent revisionが進んでいる。
When: 同じpayloadとidempotency keyで`capture_source`を再送する。
Then: 元の不透明なreceiptがreplayedとして返り、ノード、構造辺、監査記録は再送前と同一であり、変更payloadの同一key再利用はconflictになる。

## 質問リスト

なし。辺名は既存Source capture契約の3辺に固定する。

## スコープ外

- Source MCP tool、入力schema、説明、権限、runtime registrationの変更。
- Source更新・archiveの新規workflow、修復/backfill、Research、Facet、soft-delete意味の変更。
- archive後のreplay回帰はこのmain-baseline packetでは扱わない。Source archive workflowが基準に存在しないため、別のlive acceptance計画の証跡を維持する。
- 公開URLの取得、ネットワーク接続、実ユーザーデータ、実サービス操作。
- この隔離packet単独を実Neo4j fault-rollback gateの合格とみなすこと。live runtime exposure gateは別のSource acceptance計画で追跡し、この差分から合格を推定しない。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| SOURCE-LINEAGE-01 | Memory/Neo4j初回Source 3辺とreceipt-only replay | 検査: Source ingress、fake Neo4j、write rollback focused testsと全backend pytestが成功し、差分checkがclean | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| Source系譜 | 初回write内にSource→Revision、Source→Current Revision、Revision→Chunkの3辺を作る | typed payloadだけに参照を閉じ込める方法はグラフ辺を辿る契約を満たさないため却下 | Claim/Evidenceは既存のChunk参照と連結できる |
| retry | owner-scoped audit receiptとpayload fingerprintが一致した場合、既存状態を読んで修復せずreceiptを返す | 再送時に辺を再作成またはcurrent pointerを戻す方法は後続更新・archiveを上書きするため却下 | retryは状態非変更。payload不一致はconflict |
| 実DB境界 | このpacketはmemory/fake Neo4j回帰のみ。実DB gateはSource runtime integration計画の証跡に従う | fake testを実DB rollback証拠として扱う案は原子性を証明しないため却下 | このpacketでruntime exposureを有効化しない |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | 初回Source系譜辺と状態非変更retryの受け入れ条件を定義 | typed Source payloadだけではグラフ上の3辺が不足し、retry修復が後続revisionを巻き戻しうるため。Archive後のcoverageは別live gateへ残す | SOURCE-LINEAGE-01 |
