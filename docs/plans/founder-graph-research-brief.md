# Founder Graph ResearchBrief 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: T-FG-15として、DotsのローカルFounder Graphを検索し、外部調査へ渡せる安全なResearchBriefを作る。

ゴール: `GraphReadPort`のowner境界と既存のread projectionを使い、Ideas / Assets / Sourcesの検索結果を、外部通信なしで一つの不変なbriefへ合成する。

成功指標: focused pytestで、三つのカテゴリのshareable結果、関係path、スコア、canonical IDを確認し、local_only・contact・private_notes・source_textをbriefへ出さない。

## ユーザーストーリーと受け入れ条件

### US-RB-01 ローカル資産を調査前に照合する

As a 単独利用者, I want 新しい問いとDots内のIdeas / Assets / Sourcesを一度に照合したい, so that 外部調査の前提を過去の資産から組み立てられる。

Given: owner-scopedな`GraphReadPort`にIdea、Asset、SourceまたはSourceRevisionが存在し、検索結果にshareableとlocal_onlyのノードが含まれている
When: 利用者がqueryをResearchBrief builderへ渡す
Then: builderはGraphReadPortを通じて検索し、shareableなIdeas / Assets / Sourcesだけをカテゴリ、title、snippet、score、relation path、canonical ID付きで返す

### US-RB-02 外部送信境界を守る

As a 単独利用者, I want ResearchBriefからprivate fieldを除外したい, so that Deep Researchへ渡す前に個人情報と原文の漏えいを防げる。

Given: Person、local_only Idea、contact、private_notes、source_textを含む検索結果がある
When: ResearchBriefを生成する
Then: local_onlyノードとcontact、private_notes、source_textは結果に存在せず、brief内の各itemのegress policyはshareableになる

### US-RB-03 ローカル障害を再試行可能に扱う

As a 単独利用者, I want Dots停止中や検索timeoutを外部調査の成功として扱いたくない, so that 復旧後に同じ問いを再試行できる。

Given: GraphReadPortがGraphReadUnavailableErrorまたはGraphReadTimeoutErrorを返す
When: ResearchBrief builderを呼び出す
Then: builderは安全なGraphReadErrorを伝播し、外部通信と部分的な成功結果を生成しない

## 質問リスト

なし。Campaignによるexplicit projectionはT-FG-16以降で別途扱う。

## スコープ外

- Web検索、特許検索、外部MCP、Deep Researchの起動と通知。
- ResearchCampaignのauthorization snapshotとexplicit field projection。
- Luna、ローカルLLM、embedding、vector index、再順位付け。
- ResearchBriefのGraphWrite保存、ReportVersion生成、UI表示。
- Dotsのscheduler、retry queue、外部送信監査の追加。
- Neo4j専用の検索クエリ。builderはGraphReadPortだけを依存先にする。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| SP-RB-01 | 既存GraphReadPortとsafe projectionの境界確認 | 検査: `backend/dots/founder_graph_read.py`と`founder_graph_mcp.py`のallowlist、owner、egress契約をレビューする | 既知 |
| T-RB-01 | `ResearchBrief` immutable value objectとpure builder | 検査: `backend/tests/test_founder_graph_research_brief.py`で三カテゴリ、private除外、relation path、入力検証を確認する | 類推可能 |
| T-RB-02 | recoverable read failureの契約テスト | 検査: unavailable / timeoutをbuilderが外部呼出なしで伝播するfocused pytestを通す | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-RB-01 入力境界 | `GraphReadPort`を唯一の入力にし、InMemoryとNeo4jの違いをbuilderへ持ち込まない | InMemoryGraphWriteServiceへの直接依存は、owner境界とread projectionを迂回するため却下 | adapter交換可能なローカルbriefになる |
| ADR-RB-02 外部投影 | `egress_policy == shareable`の検索hitだけを対象にし、private fieldを静的allowlistで削る | shareable判定をcallerへ委ねる方式は、Deep Research接続前の漏えい境界を弱めるため却下 | explicit projectionはCampaign実装まで未対応のまま安全側に倒す |
| ADR-RB-03 ページング | GraphReadPortの一回のbounded search結果を合成し、`next_cursor`を返す | builder内で無制限に全ページを走査する方式は、timeoutと外部呼出境界の責任を増やすため却下 | 呼出側が次ページを明示的に要求できる |
| ADR-RB-04 出力形状 | dataclassのResearchBrief / ResearchBriefItemを使い、`as_dict`でJSONへ変換する | dictのみの返却は、private fieldとカテゴリの構造を型で検査しにくいため却下 | MCP/APIへ後から接続可能な不変契約になる |

## 実装メモ

- 計画タスク: T-RB-01, T-RB-02
- 受け入れ条件: US-RB-01, US-RB-02, US-RB-03
- エラー分類: GraphReadErrorは回復可能。入力不備は呼出側が修正する回復可能エラー。
- API互換性: 既存MCP/APIの変更なし。新規の内部helperのみ。
- 外部通信: なし。
- 実装済み: `backend/dots/founder_graph_research_brief.py` に不変な `ResearchBrief` / `ResearchBriefItem` と、単一回のbounded searchだけを使うpure builderを追加した。
- 投影境界: Ideas / Assets / Sources（`SourceRevision` / `ResearchMaterial`を含む）をshareable projectionへ再構成し、`local_only`、`contact`、`private_notes`、`source_text`などを除外する。外部通信、LLM、書き込み、schedulerは行わない。
- 検査: `backend/tests/test_founder_graph_research_brief.py` の6件、`py_compile`、`git diff --check`を通過。backend全体は263 passed / 16 skipped（既存のFastAPI/Starlette deprecation warning 5件のみ）。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | ResearchBriefの最小契約を追加 | T-FG-15のpreflight境界を実装可能な単位へ固定 | SP-RB-01, T-RB-01, T-RB-02 |
| 2026-09-22 | 内部builderと6件の契約テストを実装 | Dots内検索結果をDeep Research前の安全なbriefへ合成する | T-RB-01, T-RB-02 |
