# Founder Graph schema v2 保存・読取 parity 計画

最終更新: 2026-09-23
親計画: [`dots-implementation-master-plan.md`](dots-implementation-master-plan.md) の P1-04

## 目的

schema v2の4種類の記録を、一時保存とNeo4j向け保存のどちらから読んでも同じ安全な結果として扱えることを、外部接続なしの合成データで確認する。

## 受け入れ条件

- `EntityRevision`、`RelationAssertion`、`ContentChunk`、`Facet`を含む同じ合成fixtureを両方の保存口へ書き込める。
- 件数、ID、種類、revision、安全な表示項目のmanifestが一致する。
- 代表検索のIDと順序が一致する。
- `ContentChunk.text`など安全な読取一覧にない値は検索結果へ漏れない。一方、保存payloadの完全性はhashとfixtureで確認できる。
- owner越境、外部AI、実データ、通常保存先の既定切替はこの検査の対象外とする。

## 実装と検査

- Neo4jの検索用文字列を安全な読取項目の一覧から作り、一時保存の検索と同じ境界にそろえた。
- `backend/tests/test_founder_graph_v2_parity.py`で、v2全node typeの保存・読取manifest、代表検索、ContentChunkの保存payloadと安全な投影を検査する。
- focused検査: `uv run --isolated pytest backend/tests/test_founder_graph_neo4j.py backend/tests/test_founder_graph_neo4j_read.py backend/tests/test_founder_graph_neo4j_write_parity.py backend/tests/test_founder_graph_v2_parity.py -q`。

## 残課題

- v1既存データをv2のstable anchor / revisionへ変換する処理。
- Compose live volumeのmanifest一致、Attachmentとの同世代復元。
- parity検査後のNeo4j通常保存先への既定切替判断。

## 変更履歴

| 日時 | 変更 | 理由 |
| --- | --- | --- |
| 2026-09-23 | v2全node typeの合成read/write parityと安全なsearch projectionを追加 | 通常保存先の切替前に一時保存とNeo4jの意味を一致させるため |
