# Founder Graph relation path identity plan

最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: 検索経路上の意味関係について、実際に保存された関係記録の識別子を後続の安全な投影で参照できるようにする。

ゴール: 既存の文字列経路を維持しながら、edgeごとの情報と任意のRelationAssertion識別子を持つ不変の内部経路要素を用意する。

成功指標（このpacket）: Memory readerが従来の`path`と平行して同順序の`relation_path`を返す。legacy Relationshipには`relation_assertion_id=None`を設定し、端点・述語・方向・edge-local evidence/status/confidence/expiryを正確に保持する。MCP投影へ正式IDを出す完了主張はしない。

## ユーザーストーリーと受け入れ条件

### US-1 関係経路を型付き情報として扱う

As a graph read consumer, I want immutable per-edge path metadata with an optional persisted assertion identity, so that later projections can reference an exact assertion without guessing from endpoints.

Given: 同一ownerのactive legacy Relationshipが検索経路を構成する。
When: Memory readerが検索結果を生成する。
Then: 従来の`path`は変わらず、parallel `relation_path`には同じ経路順のstepが入り、未保存のRelationAssertion IDは`None`となる。

## 質問リスト

なし。このpacketは既存legacy edgeの内部read representationのみを拡張する。

## スコープ外

- Neo4jから保存済みRelationAssertion IDを得るquery。対応するwriter/read edge contract確定後のpacketとする。
- MCP `relation_path` projectionへのassertion ID出力。Neo4j/MCP parity後の別packetとする。
- writer、schema、DB、UI、provenance route変更。
- `SearchHit.path`の削除・形式変更、legacy edgeのID推定、既存検索順序変更。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| RP-ID-01 | immutable RelationPathStep、SearchHit parallel relation_path、Memory legacy builder | 検査: `uv run pytest backend/tests/test_founder_graph_read.py backend/tests/test_founder_graph_neo4j_read.py -q`、`git diff --check` | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 互換性 | SearchHit.pathは維持し、typed relation_pathを追加 | 既存path置換はreader消費者との互換性を壊す | additive parallel field |
| legacy identity | 保存済みAssertionのないlegacy edgeはNoneとする | endpoint/predicateからの推測は同一端点の複数記録を誤認しうる | fabricateしない |
| delivery境界 | Memory representationだけを先行 | Neo4j/MCP parityなしにIDを公開するのは不完全 | 後続packetで追加するまで全体受入れ未完了 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | 内部型付き関係pathの最小packetを定義 | clean mainにはRelationPathStepがなく、liveのMCP edge ID omissionはread identity dependency後に直す必要がある | RP-ID-01 |
