# Founder Graph 通常起動の永続保存 計画

最終更新: 2026-09-23
実行状態: 実装中

## 要望 / ゴール / 成功指標

要望は、実機で確認済みのNeo4j保存をFastAPIの通常起動にも接続し、APIとMCPが同じ保存先を使うことである。

ゴールは、ローカルNeo4jの接続情報が設定された起動で、Dotsの通常保存先をNeo4jにし、接続できない場合は一時メモリへ黙って切り替えないことである。

成功指標は、同じ環境選択規則がFastAPIとstdio MCPで使われ、設定済みNeo4jの起動、明示的な一時メモリ起動、未知の設定、パスワード不足の失敗をテストで確認できることである。

## ユーザーストーリーと受け入れ条件

### US-1 設定済みNeo4jを通常保存先にする

As a 単独利用者, I want ローカルNeo4jを設定したDots起動で保存と検索を行いたい, so that プロセスを再起動してもアイデアが残る。

Given: `DOTS_NEO4J_PASSWORD`があり、必要なら`DOTS_GRAPH_BACKEND=neo4j`が指定されている
When: `dots.main:app`またはstdio MCPを起動する
Then: APIとMCPは同じownerのNeo4j read/write compositionを使う。

### US-2 テストと停止時を安全に扱う

As a 開発者, I want 明示した一時メモリ設定を使いたい, so that Neo4jなしの単体テストを実行できる。

Given: `DOTS_GRAPH_BACKEND=memory`またはNeo4j接続情報が未設定である
When: 設定済み起動を作る
Then: 一時メモリ経路が選ばれ、Neo4j接続は作られない。

### US-3 接続失敗を隠さない

As a 製品責任者, I want Neo4j設定の不備を起動失敗として知りたい, so that 保存したつもりでデータを失わない。

Given: `DOTS_GRAPH_BACKEND=neo4j`またはNeo4jパスワードだけが設定されている
When: 必須接続情報が不足している状態で起動する
Then: 起動は明示的なエラーで停止し、一時メモリへ切り替わらない。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | Neo4j接続情報が設定されている起動を通常保存先とし、設定がない起動はテスト用一時メモリとして扱う | root coordinator | 2026-09-23 |

## スコープ外

- ChatGPTへの実MCP登録。
- schema v2の全migration実装。
- Neo4jが停止したときの自動再接続または一時メモリ退避。
- 外部公開、複数owner、クラウドDB。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| RT-01 | APIとstdioが共有する実行先選択 | 検査: backend選択テストとAPI・MCPのowner一致テストが成功する | 既知 |
| RT-02 | 通常APIのNeo4j composition接続 | 検査: Neo4j設定時の`create_configured_app`がpersistent read/writeを使う | 類推可能 |
| RT-03 | runbookと台帳の更新 | 検査: 起動例、接続失敗、memory明示方法、実機証跡が一致する | 既知 |
| RT-04 | WSL previewの通常起動経路修正 | 検査: `Start-WslPreview.ps1`と`wsl-development.md`が`dots.main:app`を使い、`dots.main:create_app`を参照しないことをPowerShell契約検査で確認する | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 通常保存先の選択 | Neo4jパスワードが設定された起動をNeo4jとし、`memory`を明示した場合だけ一時メモリにする。実運用とテストを分けられるため | 接続失敗時に一時メモリへ切り替える案は保存先を誤認させるため却下 | APIとstdioで同じ選択規則を使う |
| FastAPI app生成 | `create_configured_app`をcomposition rootに置き、`create_app`は既存テスト用factoryとして残す | import先ごとに個別分岐を持つ案はAPIとMCPの挙動を分けるため却下 | `dots.main:app`だけが設定済み実行先を選ぶ |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-23 | API通常起動の保存先選択を追加 | 実機Neo4j保存確認後も`app = create_app()`が一時メモリを使っていたため | RT-01〜RT-03 |
| 2026-09-23 | WSL previewのAPI起動を設定済みappへ変更し、環境変数の例をDOTSへ統一 | Neo4j設定時にpreviewだけが一時メモリへ戻る経路をなくすため | RT-04 |
