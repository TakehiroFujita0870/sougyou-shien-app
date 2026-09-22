# Founder Graph stdio MCP transport 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: Secure MCP Tunnelのstdio profileからDotsの既存read/write surfaceを呼べる標準MCP JSON-RPC transportを追加する。

ゴール: 外部接続なしの単一processで `initialize`、`tools/list`、`tools/call` を処理し、既存のowner・egress・idempotency・error契約を壊さない。

成功指標: 合成fixtureのstdio request列が、read 2 toolと用途限定write 8 toolの計10 toolだけを一覧し、search/fetch/capture_ideaを成功応答へ変換する。malformed request、unknown method/tool、write errorはJSON-RPC errorへ安全に変換する。

## ユーザーストーリーと受け入れ条件

### US-1

As a Secure MCP Tunnel, I want a stdio JSON-RPC server, so that private Dots can be reached without a public endpoint.

Given: server processへ `initialize` と `tools/list` のJSON-RPC requestを送る。

When: requestを1行ずつ処理する。

Then: protocol version、server info、10個の用途限定tool定義だけをJSONで返し、stdoutへ非JSONログを書かない。

### US-2

As a ChatGPT MCP client, I want tools/call to preserve Dots contracts, so that safe read and idempotent write work through the tunnel.

Given: `tools/call`にsearch、fetch、capture_ideaを指定する。

When: owner-scoped in-memory surfaceへ委譲する。

Then: read projectionまたはwrite receiptをstructured contentへ変換し、private/local-only dataとinternal tracebackを返さない。

## スコープ外

- Streamable HTTP、SSE、OAuth、tunnel-client、OpenAI API、ChatGPT実機接続。
- Neo4j driverの自動接続、複数process共有、実機の再起動検証。
- 任意Cypher、任意tool、物理削除、raw exceptionの返却。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-STDIO-01 | stdio JSON-RPC dispatcher | 検査: initialize / tools/list / tools/call / notification / malformed JSONをfocused pytestで確認する | 類推可能 |
| T-STDIO-02 | existing surface composition | 検査: read 2件、write 8件、owner mismatch、unknown tool、write errorをfocused pytestで確認する | 既知 |
| T-STDIO-03 | Secure Tunnel command documentation | 検査: runbookのstdio commandとstatic validatorにentrypointを追加する | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| transport | 外部依存なしのline-delimited stdio JSON-RPCを追加する | FastMCP依存を即時追加する案はdependency / protocol versionの実機検証を広げるため後続へ延期 | tunnel-clientの`--mcp-command`へ接続可能な薄い境界を得る |
| state | defaultはprocess内のin-memory servicesへ委譲し、永続経路は`create_neo4j_stdio_server`への明示注入に分ける | transportが直接domainやNeo4jへ書く案は責務と停止境界を壊すため却下 | stdioは同一owner-bound read/write compositionを受け取れる |
| error | JSON-RPC error codeとDotsのsafe code/messageを分離する | exception文字列・tracebackをそのまま返す案は内部情報漏えいのため却下 | retry可能なunavailableと入力errorを区別できる |

## 実装メモ

- `backend/dots/founder_graph_mcp_stdio.py` にpure dispatcherとstdin loopを追加した。
- `create_neo4j_stdio_server` を追加し、Neo4j read/write adapterを同一gatewayから明示注入できるようにした。自動接続とmigrationは行わない。
- ownerは単独利用向け環境変数 `DOTS_LOCAL_OWNER_ID` または明示引数から取得し、未設定時は `local-owner` とする。秘密情報は扱わない。
- stdio実機接続はSP-TUNNEL-01へ残し、標準MCP protocol versionの互換確認を実機gateで行う。

## 検査結果

- `uv run --isolated --python 3.14 --with pytest pytest -q backend/tests/test_founder_graph_mcp_stdio.py`: 4 passed。
- `validate_mcp_tunnel.py --root .`: stdio entrypoint、method、protocol versionの静的検査を追加済み。
- 実tunnel、ChatGPT tool discovery、write confirmationは未検査。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | stdio JSON-RPC transportの計画を追加 | Secure MCP Tunnelの`--mcp-command`と既存Dots surfaceの間を埋めるため | T-STDIO-01〜03 |
| 2026-09-22 | dependency-free stdio dispatcherと3件のfocused testsを実装 | read/write surfaceをSecure Tunnelのstdio commandへ委譲するため | T-STDIO-01〜03 |
