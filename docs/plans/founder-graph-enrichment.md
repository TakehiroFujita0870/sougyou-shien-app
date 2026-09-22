# Founder Graph enrichment proposal 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: T-FG-14として、共有可能なFounder Graph検索結果から名寄せ、facet、clusterの候補をローカルに組み立て、将来のLuna処理へ差し替えられる不変契約を用意する。

ゴール: `GraphReadPort`の`SearchHit`、`NodeView`、または明示的に安全化した`SafeNodeProjection`だけを入力にし、core `NodeType`を変更せず、`proposed`状態・`model_snapshot`・evidence ID・source IDを備えた候補を生成する。

成功指標: focused pytestで、shareable入力から三種類の候補を生成し、Lunaのsnapshot、根拠ID、確信度、`proposed`状態、不変性を確認する。local_onlyとprivate fieldが出力へ入らず、GraphReadPort利用時もread一回以外の外部通信・書き込みが発生しないことを確認する。

## ユーザーストーリーと受け入れ条件

### US-ENR-01 安全な入力境界

As a 単独利用者, I want shareableなGraphRead結果だけをenrichmentへ渡したい, so that private dataを候補生成の境界から切り離せる。

Given: `SearchHit`または`NodeView`のfieldsに`egress_policy`とprivate fieldがあり、別にshareableな入力も存在する
When: enrichment builderを実行する
Then: shareableなallowlist fieldだけが候補の表示値とfacet値に使われ、local_only入力とprivate fieldは候補にも`as_dict()`にも現れない

### US-ENR-02 三種類の候補

As a Founder Graph runtime, I want name resolution、facet、clusterを別々の不変proposalとして表現したい, so that後続の承認・保存処理が候補の意味を取り違えない。

Given: 同じnode typeと表示名を持つ二つ以上のshareable projection、kindまたはtagを持つprojectionがある
When: enrichment builderを実行する
Then: `NameResolutionProposal`、`FacetProposal`、`ClusterProposal`が必要なtarget IDを持つ`proposed`状態で返る

### US-ENR-03 provenanceとLuna境界

As a Founder Graph runtime, I want each proposal to identify its logical model snapshot and roots, so that候補の再現性を検証できる。

Given: default model catalogまたは明示したlogical keyが利用可能である
When: proposalを生成する
Then: 全proposalにcatalogから解決した`model_snapshot`、有限範囲のconfidence、evidence ID、source IDが入り、provider adapterは呼ばれない

### US-ENR-04 read-onlyと失敗時の安全側処理

As a 単独利用者, I want enrichmentを試してもGraphへ自動保存されないようにしたい, so that候補を確認してから後続のwrite方針を選べる。

Given: `GraphReadPort`を入力にしたbounded search、または安全化済みprojectionのtupleが与えられる
When: enrichment builderを実行する
Then: local read以外の通信・Graph write・MCP write・scheduler呼出を行わず、入力不備またはGraphReadの回復可能エラーを候補保存なしで返す

## 質問リスト

なし。自動採用、永続化、外部調査接続は後続タスクで決定する。

## スコープ外

- Luna providerの起動、API key、外部HTTP、Deep Research、embedding。
- proposalのGraphWrite保存、MCP tool公開、承認UI、自動採用。
- core `NodeType`、`RelationType`、Neo4j gateway、FastAPI composition、Frontendの変更。
- local_only、contact、private_notes、source_text、instruction pathの候補出力。
- candidate品質の実データ評価、threshold tuning、local LLM切替。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| SP-ENR-01 | GraphReadPortとdomain shareable allowlistの境界確認 | 検査: `backend/dots/founder_graph_read.py`、`backend/dots/founder_graph_mcp.py`、`SHAREABLE_PROJECTION_ALLOWLIST`をレビューする | 既知 |
| T-ENR-01 | `SafeNodeProjection`と三種proposalのimmutable value object | 検査: `backend/tests/test_founder_graph_enrichment.py`で入力sanitization、private除外、型と不変性を確認する | 類推可能 |
| T-ENR-02 | name resolution、facet、clusterのpure builder | 検査: 同名候補、kind/tag facet、共通facet cluster、空入力をfocused pytestで確認する | 類推可能 |
| T-ENR-03 | GraphReadPort bounded search adapter | 検査: read stubのsearch一回、owner境界、next cursor、fetch非呼出、read failure伝播をfocused pytestで確認する | 類推可能 |
| T-ENR-04 | Luna logical catalogとproposal provenanceの接続 | 検査: `model_snapshot`が`DEFAULT_MODEL_CATALOG`由来で、provider未設定でもproposal生成が完了することを確認する | 既知 |
| T-ENR-05 | 計画と実装のセルフレビュー | 検査: `uv run --isolated --python 3.14 pytest backend/tests/test_founder_graph_enrichment.py -q`、`python -m py_compile backend/dots/founder_graph_enrichment.py backend/tests/test_founder_graph_enrichment.py`、`git diff --check`を実行する | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-ENR-01 入力 | `GraphReadPort`のshareable hitと`SafeNodeProjection`を受け、domainの静的allowlistを再適用する | callerが任意dictを安全と宣言する方式はlocal_only漏えい境界を弱めるため却下 | InMemoryとNeo4jのread adapterを交換できるlocal contractになる |
| ADR-ENR-02 proposal形状 | name resolution、facet、clusterを別immutable dataclassに分け、共通metadataを各候補へ持たせる | `NodeType`へ候補専用typeを追加する方式はcore schemaと候補状態を混同するため却下 | T-FG-14はcore graphを変更せず後続writeへ渡せる |
| ADR-ENR-03 生成責務 | 初期sliceは安全な表示値の同名・kind・tag groupingだけを決定的に生成し、Lunaはlogical snapshotの provenance境界として解決する | provider呼出をbuilderへ埋め込む方式は外部通信、原価、承認境界を持ち込むため却下 | 実LLM推論は将来のadapterから同じproposal契約へ接続する |
| ADR-ENR-04 読み取り | GraphReadPort入力ではbounded searchを一回だけ行い、`next_cursor`を返す | builder内で全ページを走査する方式はtimeoutと無制限scanを招くため却下 | retryと次ページ取得はcallerの明示操作になる |

## 実装メモ

- 計画タスク: T-ENR-01〜T-ENR-05
- 受け入れ条件: US-ENR-01〜US-ENR-04
- エラー分類: projection・引数不備は呼出側が修正する回復可能エラー。GraphReadのtimeout・unavailableは既存の回復可能エラーを伝播する。
- API互換性: 既存MCP、FastAPI、Neo4j、Frontendの変更なし。新規の内部helperとvalue objectだけ。
- 外部通信: なし。provider registryは解決せず、model catalogのsnapshotだけを読む。
- 実装結果: `backend/dots/founder_graph_enrichment.py`に安全な入力projection、三種のimmutable proposal、deterministic grouping、GraphReadPort bounded search adapterを追加した。`SafeNodeProjection`はdomainの静的shareable allowlistを再適用し、`local_only`、private field、instruction pathを候補へ渡さない。
- 検査結果: `uv run --isolated --python 3.14 pytest backend/tests/test_founder_graph_enrichment.py -q` は5 passed。`python -m py_compile backend/dots/founder_graph_enrichment.py backend/tests/test_founder_graph_enrichment.py` と `git diff --check` は成功した。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | T-FG-14のlocal-only enrichment contractを計画 | name resolution、facet、clusterをcore schemaから分離して実装可能な単位へ固定するため | SP-ENR-01、T-ENR-01〜T-ENR-05 |
| 2026-09-22 | SafeNodeProjection、三種proposal、bounded read builder、5件のfocused testを実装 | Luna snapshotと根拠IDを持つ候補を永続化・外部通信なしで検証するため | T-ENR-01〜T-ENR-05 |
