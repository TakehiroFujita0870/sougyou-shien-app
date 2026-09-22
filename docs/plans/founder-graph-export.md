# Founder Graph safe export 契約計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: Founder Graphのshareable read projectionまたは安全化済みnode mappingを、owner境界を保った決定的なJSONとMarkdownへ変換する純粋なexport契約を追加する。

ゴール: backup、移行、確認に再利用できるsafe exportを、DB、ネットワーク、UI、write操作なしで生成する。

成功指標: 同じownerの同じprojection集合から入力順に依存しないJSONとMarkdownが生成され、local_only、contact、private_notes、source_text、instruction pathが出力に現れず、schema versionとprovenance IDが保持される。

## ユーザーストーリーと受け入れ条件

### US-EX-01 owner-scoped JSON

As a データ所有者, I want 自分のsafe graph projectionをJSONへexportしたい, so that 移行と保管に使える。

Given: owner Aのshareable projection、owner Bのprojection、private fieldを含む入力がある。

When: owner Aを指定してsafe exportを生成する。

Then: owner Aのshareable nodeだけが、静的allowlistのfields、schema version、provenance IDs付きでJSONへ含まれ、owner Bとprivate fieldは含まれない。

### US-EX-02 deterministic Markdown

As a データ所有者, I want 同じexportをMarkdownでも読めるようにしたい, so that 人間が内容と根拠を確認できる。

Given: 同じsafe projection集合を異なる入力順で渡す。

When: JSONとMarkdownを生成する。

Then: 両方の結果が同じnode順、field順、provenance ID順になり、Markdownの利用者入力は見出し・link・HTMLとして解釈されない。

### US-EX-03 bounded read

As a ChatGPT連携層, I want export入力をbounded readへ限定したい, so that 大量scanと停止中の誤成功を防げる。

Given: GraphReadPort、queryまたは明示node ID、limit、timeoutが与えられる。

When: exportを実行する。

Then: owner一致を検証し、searchまたはfetchを定められた上限内で呼び、GraphReadUnavailableErrorとGraphReadTimeoutErrorを変換せずに呼出元へ伝える。

### US-EX-04 size boundary

As a データ所有者, I want exportの件数とバイト数に上限を設定したい, so that ローカル処理のメモリと転送量を予測できる。

Given: limitまたはmax_bytesが範囲外、または生成結果がmax_bytesを超える。

When: safe exportを生成する。

Then: 外部通信とpartial outputなしに入力エラーを返す。

## 質問リスト

なし。初期sliceは純粋なhelperとfocused testに限定し、UI、MCP、Neo4j compositionは後続で決める。

## スコープ外

- JSONまたはMarkdownファイルの保存、ダウンロード、暗号化。
- backup、restore、deleteの実ストレージ操作。
- MCP tool、FastAPI route、Neo4j query、React UIへの接続。
- private projection、explicit campaign projection、local_only nodeの出力。
- 自動全件scan、外部通信、LLM呼出、write-back、scheduler。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-EX-01 | 安全な入力normalizerとowner/egress/allowlist境界 | 検査: shareable `NodeView`、`SearchHit`、mappingを正規化し、private/local_only/pathを除外するpytest | 既知 |
| T-EX-02 | deterministic JSON / Markdown export value | 検査: schema version、provenance IDs、stable ordering、Markdown escapeをpytestで比較する | 既知 |
| T-EX-03 | GraphReadPort bounded adapter | 検査: query search、node IDs fetch、owner mismatch、unavailable、timeout、limitをpytestで確認する | 類推可能 |
| T-EX-04 | size boundaryと計画実装メモ | 検査: focused pytest、py_compile、git diff --checkを実行し、実装メモへ結果を記録する | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-EX-01 入力境界 | `GraphReadPort`またはsafe mappingを受け、domainの`SHAREABLE_PROJECTION_ALLOWLIST`を再適用する | raw domain nodeを受ける方式はowner、provenance、private raw stateを迂回するため却下 | InMemoryとNeo4jのread adapterに依存しないpure helperになる |
| ADR-EX-02 provenance | callerが明示したopaque `provenance_ids`とallowlist済み参照IDだけを、nodeとtop-levelへstable sortして含める | raw `Provenance` objectの丸ごと出力はactor、prompt、時刻、idempotency情報を漏らすため却下 | 根拠IDを保ち、監査詳細はexport外に留める |
| ADR-EX-03 determinism | node、field、ID、JSON keyをstable sortし、固定schema versionを付ける | 入力順や生成時刻を出力順へ使う方式は差分とhash検証を壊すため却下 | 同一projection集合の再生成比較が可能になる |
| ADR-EX-04 failure | GraphReadのunavailable/timeoutは変換せず、validationとsize超過だけexport固有エラーにする | 停止を空exportとして成功扱いする方式はデータ欠落を隠すため却下 | callerが再試行または入力修正を選べる |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | safe exportのG/W/T、owner境界、allowlist、JSON/Markdown、provenance IDs、size上限を定義 | T-FG-26からUI・ストレージに依存しない再利用可能なexport契約を分離するため | T-EX-01〜04 |
| 2026-09-22 | pure helper、focused test、static projection再適用を実装 | GraphReadPortとsafe mappingの双方で同じowner・egress境界を検証するため | T-EX-01〜04 |

## 実装メモ

- 計画タスク: T-EX-01〜04
- 受け入れ条件: US-EX-01〜04
- 成果物: `backend/dots/founder_graph_export.py`、`backend/tests/test_founder_graph_export.py`
- safe projection: `SHAREABLE_PROJECTION_ALLOWLIST`を再適用し、owner不一致、local_only、contact、private_notes、source_text、instruction path、raw provenanceを出力しない。opaqueな`provenance_ids`とallowlist済み参照IDだけを保持する。
- read境界: GraphReadPortにはquery searchまたは明示node IDs fetchの一方だけを許可し、owner一致、limit、cursor、timeoutをread adapterへ渡す。GraphReadUnavailableErrorとGraphReadTimeoutErrorは変換しない。
- 出力: schema version、stableなnode / field / provenance ID順、JSON文字列、Markdown文字列を一つのimmutable valueへまとめる。Markdownは利用者入力を構文として解釈させない。
- エラー分類: 入力不正・owner不一致・limit超過・size超過はexport validation。read unavailable / timeoutは呼出元が再試行する回復可能状態。partial outputは返さない。
- API互換性: 新規pure moduleのみ。既存API、MCP、DB、UIの変更なし。
- 外部通信: なし。
- 検査結果: `uv run --isolated --python 3.14 pytest backend/tests/test_founder_graph_export.py -q` → 8 passed。`uv run --isolated --python 3.14 python -m py_compile backend/dots/founder_graph_export.py backend/tests/test_founder_graph_export.py` → PASS。`git diff --check` → PASS。
- ループ周回数: 1。mappingproxyのstable sortとexplicit node ID fetch順を修正してfocused testを再実行した。
