# Founder Graph write MCP bounded plan

この文書は初期8種類のwrite toolの入力制限・冪等性を定義する。現行write面へのEvidence作成とschema v2 RelationAssertion保存の追加仕様は[根拠付き関係保存計画](founder-graph-relationship-evidence-write.md)を正本とする。

## 目的と境界

T-FG-09の第一sliceとして、ChatGPTの通常チャットからGraphWriteServiceへ渡す用途限定write surfaceを実装する。`capture_idea`、`capture_person`、`capture_organization`、`append_claim`、`link_entities`、`save_research_report`、`record_decision`、`record_correction`の8 toolだけを受け付け、idempotency key、入力上限、owner境界、domain validation、物理削除拒否を固定する。

Deep Research実行、通知、Secure MCP Tunnel、任意Cypher、Neo4j adapter、UIは変更しない。

## 受け入れ条件

- 8用途限定tool以外、任意Cypher、物理削除、schema変更を拒否する。
- 全writeにidempotency keyを要求し、同一payloadの再送はreplay、異なるpayloadはconflictにする。
- ownerはMCP request contextから決め、入力bodyのowner_idを信用しない。
- `capture_idea`はIdea revisionを作り、`append_claim`はClaim type/evidence idsを検証する。
- `link_entities`はrelation allowlist、endpoint存在、network relationの根拠・確信度・期限をGraphWriteServiceへ委譲する。
- `record_correction`は旧nodeを変更せず、新nodeのsupersedesを要求する。
- 入力エラーは秘密情報を含まない機械可読MCP errorへ変換する。

## 回帰テスト

- `backend/tests/test_founder_graph_mcp_write.py::test_write_surface_exposes_exactly_eight_tools`
- `backend/tests/test_founder_graph_mcp_write.py::test_capture_idea_and_append_claim_are_idempotent`
- `backend/tests/test_founder_graph_mcp_write.py::test_link_entities_and_record_correction_use_domain_contracts`
- `backend/tests/test_founder_graph_mcp_write.py::test_save_report_and_decision_are_owner_scoped`
- `backend/tests/test_founder_graph_mcp_write.py::test_unsupported_write_and_payload_conflict_fail_closed`

## 完了判定

focused suite、全backend suite、`py_compile`、`git diff --check`がgreenで、差分500行以下の単一目的であること。
