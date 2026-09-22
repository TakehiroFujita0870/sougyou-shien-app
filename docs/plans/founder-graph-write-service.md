# Founder Graph GraphWriteService bounded plan

## 目的と境界

T-FG-06の最初のbounded sliceとして、FastAPI、MCP、Neo4jに依存しないGraphWriteService契約を確定する。単独利用者のowner境界、core node/relation allowlist、冪等キー、expected revision、append-only audit、失敗時の原子性をvalue-object上で検証する。

このsliceは永続化アダプター、任意Cypher、外部AI、MCP transport、UIを変更しない。Neo4j adapterは同じ契約を実装する後続sliceとする。

## 受け入れ条件

- 同一idempotency keyと同一payloadの再送は、同じreceiptを返し、node/relation/auditを重複作成しない。
- 同一idempotency keyでpayloadが異なる場合は拒否し、既存状態を変更しない。
- node owner、relationship owner、endpoint ownerが単独ownerと一致しない書き込みを拒否する。
- relation endpointのNodeTypeとallowlistを検証し、存在しないendpoint、任意relation、物理削除を拒否する。
- `expected_revision`が現在値と一致しない書き込みを拒否する。immutable revision nodeは既存IDの上書きを許可しない。
- 失敗したlink/correctionはnode、relation、auditを部分的に残さない。
- audit eventはoperation、target、actor、idempotency key、payload fingerprint、時刻を持ち、秘密情報を含めない。

## 回帰テスト

- `backend/tests/test_founder_graph_write.py::test_put_node_is_idempotent_and_audited`
- `backend/tests/test_founder_graph_write.py::test_idempotency_key_conflict_does_not_mutate_state`
- `backend/tests/test_founder_graph_write.py::test_owner_and_node_type_boundaries_fail_closed`
- `backend/tests/test_founder_graph_write.py::test_link_requires_existing_allowlisted_same_owner_endpoints`
- `backend/tests/test_founder_graph_write.py::test_expected_revision_and_immutable_correction_contract`
- `backend/tests/test_founder_graph_write.py::test_failed_link_rolls_back_relation_and_audit`

## 完了判定

focused suiteがgreen、全backend suiteがgreen、`python -X utf8 -m py_compile backend/dots/founder_graph_write.py`と`git diff --check`がgreenであること。差分は500行以下、GraphWriteService単一目的であること。

## ロールバック

このsliceの新規moduleとtestだけをrevertする。既存domain value-object、Neo4j volume、既存Postgres、実ユーザーデータは変更しない。
