# Founder Graph schema v2 移行の実装計画

最終更新: 2026-09-23

## 目的

schema v1の保存データを壊さずに、schema v2で追加した4種類の記録（EntityRevision、RelationAssertion、ContentChunk、Facet）をNeo4jで受け入れられる状態にする。既存データの自動変換や削除はこの変更の対象にしない。

## 受け入れ条件

### Given / When / Then

1. Given: schema v1の移行計画が必要
   When: v1への移行を要求する
   Then: v1で定義された既存のラベルだけに一意制約と所有者用索引を作り、v2のラベルを後付けしない。
2. Given: 空のNeo4jまたはschema v1のデータがある
   When: v2への移行を要求する
   Then: 4つのv2ラベルへ一意制約、所有者用索引、検索用索引を追加し、既存のノードと関係を変更しない。
3. Given: v2の構造を一時的に外したい
   When: v2からv1への復帰を要求する
   Then: v2の制約と索引だけを外し、ノード、関係、payload、監査履歴を削除しない。
4. Given: 移行が同じ入力で複数回実行される
   When: 同じ移行を再実行する
   Then: `IF NOT EXISTS`または`IF EXISTS`で失敗せず、同じ計画件数を返す。
5. Given: 移行対象のラベルやCypher文字列を外部入力する
   When: 移行を実行する
   Then: 移行計画に定義された固定値だけを使い、任意のラベルやCypherを受け付けない。

## 対象外

- v1データの自動変換、既存ノードの再作成、物理削除。
- RelationAssertionへの既存Relationshipの自動置換。
- 実データや実credentialを使った移行。
- Neo4jのdump / restore、Attachment、manifestの同世代化（P8の決定後に別計画で扱う）。

## 実装単位

- `backend/dots/founder_graph_schema.py`: v1ラベルを固定し、v2の制約・索引と安全なrollback計画を追加する。
- `backend/dots/founder_graph_neo4j.py`: 通常移行の既定対象をschema v2へ進め、明示的なrollback操作を追加する。
- `scripts/founder-graph/migrate_schema.py`: 移行計画とrollback計画をDockerなしで表示・検査できるようにする。
- `backend/tests/`: v1/v2の計画、rollback、再実行性、ゲートウェイ呼び出しを固定する。

## 完了判定

focused test、backend全体、`git diff --check`が成功し、実Neo4jの空volumeでv2移行とrollbackを別の合成fixtureで確認できること。既存のlive volumeは変更しない。
