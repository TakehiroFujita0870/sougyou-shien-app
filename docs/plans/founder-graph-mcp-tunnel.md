# Founder Graph Secure MCP Tunnel 運用契約 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: Secure MCP Tunnel の実接続前に、Dots のローカルMCPと ChatGPT developer-mode の接続境界を安全に再現できる運用契約へ固定する。

ゴール: Dotsを公開endpointへ変更せず、tunnel-clientのprofile、doctor、run、停止・再接続、失効確認を同じrunbookで実行できる状態にする。

成功指標: 静的validatorが秘密値・実tunnel ID・公開bind・public endpointを含まないrunbookとhelperをPASSし、停止時にMCPがunavailableへ縮退する既存契約を確認できる。

## ユーザーストーリーと受け入れ条件

### US-1

As a 単独利用者, I want private MCPをtunnel-client経由でChatGPTへ接続したい, so that DotsのMCPを公開せずFounder Graphを使える。

Given: ローカルMCP serverとtunnel-client profileが用意されている。

When: runbookのdoctor、run、ChatGPT developer-mode接続手順を順に実行する。

Then: MCP serverはlocalhostまたはprivate networkだけで待ち受け、ChatGPT側はTunnel接続を選択し、公開HTTPS endpointを要求しない。

### US-2

As a 単独利用者, I want 停止・失効・再接続を確認したい, so that Dots停止中に誤成功しない。

Given: Dotsまたはtunnel-clientが停止している。

When: MCP read / writeを実行する。

Then: MCPは既存のunavailableまたは503契約を返し、秘密値、内部stack、raw credentialを返さない。

### US-3

As a local operator, I want the connection contract validated without network access, so that a static check can run before any credential or tunnel is used.

Given: repository checkoutだけがある。

When: `python scripts/founder-graph/validate_mcp_tunnel.py --root .`を実行する。

Then: placeholder以外のtunnel ID、API key、public bind、外部接続コマンドが検出され、runbookとMCP error contractの必須語が検査される。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-TUNNEL-01 | 対象ChatGPT workspaceとPlatform organizationでTunnel権限を利用できるか | 利用者 | 実機gate開始前 |
| Q-TUNNEL-02 | tunnel-clientをWSL user serviceで常駐させるか手動runにするか | 利用者 | 実機gate開始前 |

## スコープ外

- 実tunnelの作成、API key、tunnel ID、ChatGPT workspaceへの接続。
- 外部ネットワーク、OpenAI API、Neo4j、Deep Researchの実行。
- 公開HTTPS endpoint、OAuth、複数利用者、常駐scheduler。
- MCP tool schema、GraphRead/GraphWrite、UIの変更。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-TUNNEL-01 | private tunnel runbook | 検査: runbookにprofile、doctor、run、ChatGPT Tunnel選択、停止、再接続、失効、秘密値非記載がある | 既知 |
| T-TUNNEL-02 | Docker-free static validator | 検査: `test_founder_graph_mcp_tunnel.py` と validator CLI が通り、実ネットワークを開かない | 類推可能 |
| SP-TUNNEL-01 | Secure MCP Tunnel実機縦切り | 検査: 利用者の許諾後にtunnel-client doctor/run、ChatGPT search/fetch/write、停止時unavailableを記録する | 未知・先行スパイク |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 接続方式 | Secure MCP Tunnelのoutbound-only transportを第一候補とする。MCP serverを公開せず、ChatGPT developer-modeから選択できるため | public HTTPS endpointは個人利用の公開面とcredential境界を増やすため却下 | 実機gateまではrunbookと静的契約だけを維持する |
| 検査境界 | repository-only validatorを先に置く。実鍵や実tunnel IDをテストへ入れないため | 外部接続をunit testへ含める案は再現性と秘密管理を壊すため却下 | 実機確認はSP-TUNNEL-01へ分離する |
| 停止時動作 | Dotsの既存MCP `unavailable` / HTTP 503を正本とする | 停止を空結果や成功扱いにする案は誤保存を招くため却下 | ChatGPT側のretryはDots外の責務として記録する |
| write confirmation | Dotsはローカル承認を追加せず、ChatGPT側のwrite confirmation / policyを尊重する | platform確認をDotsから抑止する案は接続側の安全境界を壊すため却下 | 個人利用の自動保存意図とplatform側の確認を分離する |

## 実装メモ

- OpenAI公式のSecure MCP Tunnelガイドにある `tunnel-client init` / `doctor` / `run`、ChatGPT developer-modeでのTunnel選択、inbound不要の境界だけをrunbookへ反映する。
- validatorはファイル内容だけを読み、placeholder形式の例示値を除くcredential/tunnel IDを拒否する。外部コマンド、socket、DNS、Dockerを呼ばない。stdio adapterのentrypoint、method、protocol versionも静的に検査する。
- stdio adapterの詳細は[T-FG stdio transport計画](founder-graph-mcp-stdio.md)の`T-STDIO-01`〜`T-STDIO-03`で管理する。

## 検査結果

- `uv run --isolated --python 3.14 --with pytest pytest -q backend/tests/test_founder_graph_mcp_tunnel.py`: 4 passed。
- `uv run --isolated --python 3.14 --with pytest pytest -q backend/tests/test_founder_graph_mcp_stdio.py`: 4 passed。
- `python scripts/founder-graph/validate_mcp_tunnel.py --root .`: PASS (static, network-free)。
- `python scripts/founder-graph/validate_local_ops.py --root .`: PASS (static, Docker-free)。
- stdio JSON-RPCのfocused testsと静的entrypoint検査は完了。実tunnel、ChatGPT workspace、tool discoveryは未検査で、実機gateの前提として残す。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | Secure MCP Tunnelの静的運用契約を新規作成 | 実機接続前にprivate boundaryと停止時契約を検査可能にするため | T-TUNNEL-01〜02、SP-TUNNEL-01 |
| 2026-09-22 | runbook、network-free validator、4件のfocused testsを実装 | 実credentialなしでdoctor / run / stop / ChatGPT Tunnel選択の境界を回帰検査するため | T-TUNNEL-01〜02 |
