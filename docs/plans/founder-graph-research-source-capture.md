# Founder Graph 調査Source取り込み 計画

最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: ChatGPTで許可を得て調査した公開情報の出典を、既存のMCP経由でDotsへ安全に取り込む。

ゴール: URL、タイトル、短い自作要約を、IdeaやAssetを捏造せずowner限定のSource・不変SourceRevision・ContentChunkとして原子的に保存し、Source.current_revision_idとSourceRevision.source_idのtyped referencesを正しく保つ。

成功指標: 1回のMCP呼び出しでSource/Revision/Chunkが全件または無件となり、再試行は同じopaque ID receipt、入力変更再利用はconflictとなる。すべてlocal_onlyで、本文、タイトル、URLをreceiptへ含めない。

## ユーザーストーリーと受け入れ条件

### US-1 出典を保存する

As a Founder Graph user, I want to record a public source and my own concise summary, so that subsequent Claims and Evidence can cite material without inventing an Idea or Asset.

Given: 呼出者が絶対HTTP(S) URL、タイトル、1〜4000文字の自作要約、安定したidempotency keyを指定する
When: `capture_source`を一度呼ぶ
Then: owner専用write portがSource(kind=web)、SourceRevision、決定的ContentChunk群、typed referencesとauditを同一transactionで保存し、全ノードがlocal_onlyとなる。structural lineage edgesは別packetの依存。

Given: 既存source/chunkと競合するID、別owner、credentialを含む/無効なURL、未知引数または境界外要約がある
When: `capture_source`を呼ぶ
Then: 保存せず、適切なowner/input/conflict errorを返す

### US-2 再試行を安全にする

As a caller, I want to retry an interrupted source capture without duplicating or changing evidence, so that I can safely continue to create Claims and Evidence from the returned IDs.

Given: 同じidempotency keyと同じ入力が既に保存済み
When: 同じ`capture_source`を再試行する
Then: 内容を返さず、同じSource、SourceRevision、ContentChunk IDを含むreplayed receiptを返す

Given: 保存済みkeyを異なるURL、タイトル、または要約で再利用する
When: `capture_source`を再試行する
Then: idempotency conflictとなり既存データを変更しない

## スコープ外

- URLへのnetwork fetch、page scraping、外部API/LLM接続。
- ResearchCampaign/ResearchRunの作成・完了、Evidence/Claim作成、Idea/Asset自動作成。
- MCP receiptへの本文、URL、タイトル、summary返却。
- 上書き、SourceRevision更新、既存Sourceへのappend。これはcreate-only command。
- 実DB/service操作。Neo4j transaction fakeとunit testsのみで検査し、実機は別gate。
- source lineage structural edgesと実DB Evidence正規flow。これらは未配送の後続core packetで実装し、RP-04D2D単独ではMVP合格に数えない。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| RP-04D2D | create-only原子的capture_source port、Neo4j/InMemory実装、local_only MCP tool | 検査: `uv run pytest -q backend/tests/test_founder_graph_source_capture_ingress.py backend/tests/test_founder_graph_mcp_write.py backend/tests/test_founder_graph_mcp_api.py backend/tests/test_founder_graph_mcp_stdio.py backend/tests/test_founder_graph_neo4j.py backend/tests/test_founder_graph_neo4j_runtime.py backend/tests/test_founder_graph_neo4j_write_parity.py` | fake/unit基礎のみ。実機fault rollback未検証 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| source取り込み境界 | 明示入力のURL/title/短い自作summaryだけを取り込み、既存mainの`capture_idea`と同じtyped Source.current_revision_id / SourceRevision.source_id refs、Source/Revision/Chunk/auditを1 transactionで作る。stable IDs、payload fingerprint、owner bindingでreplayとcross-ownerを制御 | `capture_idea`再利用はIdeaを捏造するため却下。`put_node`連続呼び出しはpartial source chainを許すため却下。URL fetchは外部egressと不明な権利/本文境界を増やすため却下 | receiptはIDのみ。初期policy固定`local_only`。lineage edges/実DB Evidence flowは後続core packet依存で、全体MVP acceptanceに未充足として残す |

## ロールバック

このpacketではfake transaction callbackとunit testsまでを基礎実装として扱い、実DBのrollback成功とは主張しない。runtimeでの公開・利用開始前に、owner専用・隔離Neo4jでSource/Revision/Chunk/auditの作成、replay、fault injection rollbackを検証するgateが必須であり、現時点では未通過。問題時はMCP toolを公開停止し、`capture_source` port/adapter/testとこの計画をrevertする。書込済みSource graphは物理削除しない。既存capture_idea挙動には変更を加えない。

## 変更履歴

| 日時 | 変更 | 理由 | 影響task |
| --- | --- | --- | --- |
| 2026-09-26 | RP-04D2Dのcapture_source入口とatomicity受入条件を追加 | 許諾済み公開調査の出典を既存Evidence経路へ渡すため | RP-04D2D |
