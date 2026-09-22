# Founder Graph 会話付きアイデア保存 計画

最終検証日: 2026-09-23

## 要望 / ゴール / 成功指標

### 要望

ChatGPTから受け取ったアイデアを、アイデア本体だけでなく、保存元の会話と会話の初回版を同じ保存操作でDotsへ登録する。

### ゴール

保存途中の失敗でアイデアだけが残る状態をなくし、再起動後もアイデアと保存元へ到達できる共通契約を一時保存とNeo4j保存へ適用する。

### 成功指標

- 一回のcapture_ideaでIdea、Source、SourceRevisionが各一件作られる。
- Ideaの原文欄は空のまま、原文はSourceRevisionに一件だけ保存される。
- 同じ依頼を二回送ると同じWriteReceiptが再利用され、三つのノードが増えない。
- 一時保存とNeo4j保存の双方で同じ入力検証、所有者境界、冪等性を通過する。

## ユーザーストーリーと受け入れ条件

### US-SC-01 会話を失わずにアイデアを保存する

As a 単独利用者, I want ChatGPTの発言からアイデアと元の会話を一緒に保存したい, so that 後で判断の根拠を確認できる。

Given: Dotsのwrite surfaceが起動し、titleとsource_textを受け取れる
When: capture_ideaを一回実行する
Then: Idea、Source、SourceRevisionが各一件作られ、SourceRevisionが元の会話を持ち、IdeaのprovenanceがSourceRevisionを指す

### US-SC-02 再送で重複させない

As a 単独利用者, I want 通信再送を安全に行いたい, so that 同じ会話が複数の資産にならない。

Given: capture_ideaがidempotency key付きで成功している
When: 同じ入力と同じidempotency keyで再実行する
Then: replayed=trueの同じWriteReceiptが返り、Idea、Source、SourceRevision、監査記録は増えない

### US-SC-03 永続保存経路を統一する

As a 単独利用者, I want 一時保存とNeo4j保存で同じ結果を得たい, so that 保存先を切り替えても利用手順が変わらない。

Given: 一時保存またはNeo4j保存のwrite serviceがowner-bound compositionで作られている
When: capture_ideaを実行する
Then: 所有者検証、Sourceのcurrent_revision_id検証、重複検証、監査記録が同じ順序で行われる

## スコープ外

- IdeaからSourceへの新しいグラフ関係を追加すること。初回版ではIdeaのprovenance.source_idを出典ポインターとして使う。
- 会話の自動要約、名寄せ、facet生成、embedding生成を実行すること。
- 既存Ideaのsource_textを一括移行すること。
- 外部ChatGPT接続、Secure MCP Tunnel実機接続、Deep Research実機実行を完了扱いにすること。
- SourceRevisionの訂正版追加UIを作ること。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| SC-01 | capture_ideaの共通write契約 | 検査: `backend/tests/test_founder_graph_mcp_write.py`で三ノード作成、原文分離、再送、入力失敗を確認する | 既知 |
| SC-02 | 一時保存の一括保存実装 | 検査: 途中例外後にノード、履歴、監査、冪等記録が残らないことを確認する | 既知 |
| SC-03 | Neo4jの一括保存実装 | 検査: `backend/tests/test_founder_graph_neo4j.py`でSource、SourceRevision、Idea、監査のCREATEが各一回で、再送がreplayedになることを確認する | 類推可能 |
| SC-04 | 通常起動の永続保存接続 | 検査: 起動手順と`create_configured_app`の参照先が一致し、Neo4j設定時に`create_app`へ落ちないことを静的検査とruntime testで確認する | 類推可能 |
| SC-05 | 実Neo4j再起動保存確認 | 検査: 合成会話を保存し、コンテナ再起動後に同じIdeaとSourceRevisionをfetchできることを手動記録する | 未知 |

## スパイク

| ID | 結論条件 | 調査方法 | 時間上限 |
| --- | --- | --- | --- |
| SP-SC-01 | Neo4jの一トランザクションで三ノードと監査を確定できる | Docker ComposeのNeo4jへ合成入力を一件保存し、再起動後のfetchと再送を確認する | 30分 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 / 見直し条件 |
| --- | --- | --- | --- |
| ADR-SC-01 保存単位 | Idea、Source、SourceRevision、監査を一回のwrite boundaryで確定する。途中状態を外へ見せないため | Ideaを先に保存してSourceを後から追加する案は、失敗時に出典のないIdeaが残るため却下 | Neo4j実機でrollbackまたは再試行結果が確認できない場合はtransaction設計を見直す |
| ADR-SC-02 原文の所在 | 原文はSourceRevisionへ置き、Idea.source_textは空にする。共有用projectionから原文を除外しやすいため | Ideaへ原文を重複保存する案は更新時の不一致と外部送信境界の曖昧さを生むため却下 | 既存read contractが原文を必須と判定した場合は互換projectionを別途設計する |
| ADR-SC-03 出典ポインター | Idea.provenance.source_idにSourceRevision IDを格納する。既存provenance契約を再利用できるため | 初回から新しいIdea-SOURCE関係を追加する案はschema変更と移行範囲が広がるため却下 | 検索結果で出典追跡が不足した場合に関係追加を別ADRで決める |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-23 | Idea、Source、SourceRevisionを一括保存する計画を追加 | MVPの最初の実機縦断を原文追跡付きで成立させるため | SC-01〜SC-05 |

