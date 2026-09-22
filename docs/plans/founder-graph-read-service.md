# Founder Graph hybrid read service bounded plan

## 目的と境界

T-FG-07の最初のbounded sliceとして、GraphWriteServiceのsnapshotを対象にしたowner-scopedなローカル検索・fetch契約を実装する。keyword match、関係1-hop近傍、安定したscore/pagination、削除・旧revision除外、timeoutを決定的に検証する。

このsliceはNeo4j driver、embedding provider、MCP transport、外部送信、UIを変更しない。vector capabilityは将来のLuna評価後に別adapterで差し替えられるよう、検索結果の契約だけを固定する。

## 受け入れ条件

- ownerが一致する現行nodeだけを検索・fetchし、別owner、retracted、superseded、archived nodeを通常検索へ返さない。
- node本文のkeyword scoreと、直接relationでつながる1-hop近傍を安定した順位で返す。
- limit（1〜50）、cursor、query長上限、不正cursorを検証し、next cursorを返す。
- 同じsnapshotとqueryでは同じ順序とscoreになり、node IDでtie-breakする。
- timeout budgetを超える検索は部分結果を成功扱いにせず、明示的なrecoverable errorを返す。
- fetchはowner境界を守り、存在しないnodeを安全なnot-foundとして返す。

## 回帰テスト

- `backend/tests/test_founder_graph_read.py::test_search_returns_keyword_and_one_hop_graph_hits`
- `backend/tests/test_founder_graph_read.py::test_search_filters_owner_and_non_current_nodes`
- `backend/tests/test_founder_graph_read.py::test_search_paginates_with_stable_cursor_and_limit`
- `backend/tests/test_founder_graph_read.py::test_fetch_enforces_owner_boundary`
- `backend/tests/test_founder_graph_read.py::test_search_timeout_is_recoverable_and_has_no_partial_success`

## 完了判定

focused suite、全backend suite、`py_compile`、`git diff --check`がgreenで、差分500行以下の単一目的であること。
