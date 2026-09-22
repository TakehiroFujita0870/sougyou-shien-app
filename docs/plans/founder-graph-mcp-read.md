# Founder Graph read MCP bounded plan

## 目的と境界

T-FG-08の第一sliceとして、GraphReadServiceをDeep Research向けのread-only MCP契約へ変換する。`search`と`fetch`だけを公開し、入力上限、canonical URL、安全なshareable projection、owner境界、timeout、prompt-injectionをデータ扱いする境界を固定する。

write command、任意Cypher、Deep Research実行、Secure MCP Tunnel、外部接続、UIはこのsliceで変更しない。

## 受け入れ条件

- tool定義は`search`と`fetch`だけで、write、delete、任意Cypherを公開しない。
- searchはquery/limit/cursorを検証し、timeoutやowner違反を機密情報を含まないMCPエラーへ変換する。
- `local_only`、policy未設定、Personのcontact/private_notesを外部projectionへ返さない。
- shareable fieldだけを`id`、`title`、`kind`、`snippet`、canonical URL、引用metadataへ整形する。
- 外部検索結果の本文はuntrusted dataとして文字列で返し、命令やtool callへ昇格する構造を持たない。
- fetchは同じprojectionを返し、存在しないIDと別ownerを同じnot-foundへ寄せる。

## 回帰テスト

- `backend/tests/test_founder_graph_mcp.py::test_read_surface_exposes_only_search_and_fetch`
- `backend/tests/test_founder_graph_mcp.py::test_search_and_fetch_return_shareable_projection_only`
- `backend/tests/test_founder_graph_mcp.py::test_local_only_and_private_person_fields_never_leave_projection`
- `backend/tests/test_founder_graph_mcp.py::test_prompt_injection_text_is_returned_as_untrusted_data`
- `backend/tests/test_founder_graph_mcp.py::test_invalid_input_timeout_and_owner_miss_are_safe_mcp_errors`

## 完了判定

focused suite、全backend suite、`py_compile`、`git diff --check`がgreenで、差分500行以下の単一目的であること。
