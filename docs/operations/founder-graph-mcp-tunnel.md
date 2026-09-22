# Founder Graph Secure MCP Tunnel runbook

最終検証日: 2026-09-22

このrunbookは実tunnelを作成せず、実機gateへ進む前の安全な手順を固定する。DotsのDBとprivate MCP serverは公開しない。Secure MCP Tunnelは、private network内の `tunnel-client` がOpenAIへoutbound HTTPSを張り、ローカルのMCP serverへ要求を転送する方式を第一候補とする。

## 現在の実装境界

現行Dotsは `backend/dots/main.py` にowner-scoped read/writeのFastAPI-shaped adapterを持ち、`backend/dots/founder_graph_mcp_stdio.py` にstdio JSON-RPC transportを持つ。`backend/dots/founder_graph_runtime.py` の明示 factoryからNeo4j read/write adapterを同じgatewayへ注入できる。HTTP/SSE transport、Neo4j実driver接続、実tunnelは未検査である。

- `search` / `fetch` readと用途限定writeをMCP toolへ変換する。
- 任意Cypher、物理削除、raw payload、private fieldをtoolへ追加しない。
- transport停止、Neo4j停止、owner不一致は `unavailable` / HTTP 503または同等のMCP errorへ変換する。

## 実機gate前の静的確認

リポジトリrootで、外部接続なしに次を実行する。

```bash
python scripts/founder-graph/validate_mcp_tunnel.py --root .
python scripts/founder-graph/validate_local_ops.py --root .
```

PowerShell:

```powershell
python .\scripts\founder-graph\validate_mcp_tunnel.py --root .
python .\scripts\founder-graph\validate_local_ops.py --root .
```

validatorはcredential、実tunnel ID、public bind、socket、Docker、DNSを使用しない。

## 実機gateで準備する値

次の値はローカルのsecret managerまたは一時環境変数にだけ置く。Git、shell history、ログ、issue、画面共有へ出さない。

- Platform tunnel settingsで発行した `tunnel_id`。
- `tunnel-client` 用のruntime API key。
- 対象ChatGPT workspaceとPlatform organizationのTunnel Read + Use権限。
- private MCP serverへ接続するprofile名。

このリポジトリには実値を保存しない。例示では `<tunnel_id>`、`<runtime-api-key>`、`<profile>`を使う。

## tunnel-client profile

OpenAI公式のSecure MCP Tunnel手順に合わせ、最新releaseのbinaryを取得した環境で次を実行する。release URLは固定せず、Platform tunnel settingsまたは公式release案内を使う。

```bash
export CONTROL_PLANE_API_KEY='<runtime-api-key>'
tunnel-client init \
  --sample sample_mcp_stdio_local \
  --profile '<profile>' \
  --tunnel-id '<tunnel_id>' \
  --mcp-command 'env PYTHONPATH=/absolute/path/to/dots/backend uv run --project /absolute/path/to/dots python -m dots.founder_graph_mcp_stdio'
tunnel-client doctor --profile '<profile>' --explain
tunnel-client run --profile '<profile>'
```

`tunnel-client` とMCP serverは同じtrust boundaryで動かす。Dots APIやNeo4jの待受けは `127.0.0.1` またはprivate networkに限定し、`0.0.0.0`、LAN公開、public HTTPS proxyを追加しない。

stdio adapterとNeo4j read/write compositionは合成fixtureで検査済みだが、実機gateでは`tunnel-client`が要求するprotocol versionとtool discovery、Neo4j再起動後のwrite/read一致を再確認する。HTTP MCPを使う場合も、private URLはtunnel-clientからだけ到達可能にし、ChatGPTへprivate URLを直接渡さない。

stdio transportはMCP protocol version `2025-06-18`の `initialize`、`tools/list`、`tools/call` を実装し、10個の用途限定toolを返す。実機でprotocol versionの交渉が合わない場合は、Dots側の定数を更新してfocused testsを先に修正する。

## ChatGPT接続

1. ChatGPTのdeveloper-mode app作成画面でConnectionに **Tunnel** を選ぶ。
2. 対象workspaceへ関連付けた `<tunnel_id>` を選択する。
3. tool一覧に `search`、`fetch`、用途限定writeだけが表示されることを確認する。
4. 合成fixtureでcapture、read、idempotent writeを1回ずつ実行する。

Tunnelが表示されない場合、Platform organizationだけでなく対象ChatGPT workspaceにも関連付いているか、operatorにTunnels Read + Useがあるかを確認する。接続確認前にprivate dataを投入しない。

Dots側は追加の承認画面を持たないが、ChatGPT側のdeveloper-mode policyがwrite actionの確認を要求する場合はそれに従う。Dotsからplatform確認を迂回しない。

## 停止・再接続・失効

```bash
# tunnel-clientを停止し、Dots APIまたはMCP serverも停止
# MCP read/writeを呼び、unavailableまたは503になることを確認
# Dotsを再起動してからtunnel-client doctorを再実行
tunnel-client doctor --profile '<profile>' --explain
tunnel-client run --profile '<profile>'
```

失効時はruntime API keyをsecret managerから削除・再発行し、profileへ実値を残さない。tunnelの削除や権限変更後は、ChatGPT appから古いTunnelを選択できないことを確認する。

## 実機gateの記録

SP-TUNNEL-01の記録には、日時、使用したprofileの識別子、MCP tool名、各コマンド終了コード、doctorのhealth/readiness、ChatGPT側のworkspace association、停止時のerror codeだけを残す。API key、tunnel ID本文、連絡先本文、private graph fieldは記録しない。

実機gate未実施の状態では、静的validatorのPASSをChatGPT接続成功やDeep Research成功と扱わない。

## 参照

- [Secure MCP Tunnel | OpenAI API](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
