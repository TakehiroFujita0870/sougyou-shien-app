# Founder Graph メモリ内 ResearchRun 保存計画
最終検証日: 2026-09-26
## 要望 / ゴール / 成功指標

要望: Campaign と terminal ResearchRun を、承認状態・期限・試行予算を検査したうえで一度だけ原子的に記録する。

ゴール: InMemoryGraphWriteService に、現在の所有者スコープと Campaign revision に結び付いた ResearchRun 登録境界を追加する。

成功指標: 成功時は Campaign revision/run_count、Run、HAS_RUN、監査、冪等レシートが一組で記録され、拒否または監査障害時はその組の一部も残らない。

## ユーザーストーリーと受け入れ条件

### US-RR-01
As a ローカル利用者, I want 承認済み調査の結果を保存したい, so that 許可した範囲と試行回数を一貫して追跡できる。
Given: 所有者と一致するCampaignが現在の承認スナップショットを持ち、期限内で予算に空きがあり、期待revisionと一致する。
When: terminal ResearchRunを記録する。
Then: Campaignが1 revision/run_countだけ進み、RunとHAS_RUN、監査、レシートが1回分だけ保存される。
### US-RR-02
As a ローカル利用者, I want 同じ保存要求の再送を安全に扱いたい, so that 通信再試行で予算を二重消費しない。
Given: 同じ冪等キーで既に受理されたRun要求がある。
When: 同じ業務内容を、再生成された開始・終了・provenance時刻で再送する。
Then: 元のreceiptがreplayedとして返り、保存済みRunとCampaignは変化しない。結果・status・evidenceを含む業務内容の変更は衝突として拒否される。
### US-RR-03
As a ローカル利用者, I want 競合や途中障害で半端な研究記録を残さないようにしたい, so that 後から整合性の取れない履歴を読まない。
Given: 期待revisionが古い、認可/owner/期限/予算/timingが不正、Run IDが重複、または監査記録が失敗する。
When: ResearchRunの記録を試みる。
Then: 失敗し、Campaign現在値・履歴、Run現在値・履歴、HAS_RUN、監査、冪等レシートは変更されない。
## 質問リスト
なし。メモリ内adapter限定、API/Neo4j/MCPは別担当・別packetと確認済み。

## スコープ外
- Neo4j transaction writer、API/stdio/MCP wiring、runtime/service、database migration。
- IdeaBriefの8章・ResearchRun参照gate。Run ingressはまだBriefを持たないため呼び出さない。
- Research scheduling/provider calls、external research、real user data。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-RR-01 | メモリwriter専用の失敗・成功テスト | 検査: `uv run pytest backend/tests/test_founder_graph_research_run_atomic.py -q` が実装前に失敗し、実装後に成功 | 既知 |
| T-RR-02 | InMemoryGraphWriteServiceの原子的record_research_runと時刻/fingerprint共通helper | 検査: focused testでCAS、replay、auth、budget、timing、監査rollbackを確認 | 類推可能 |
| T-RR-03 | writer/helper/test/planの回帰確認と差分監査 | 検査: `uv run pytest backend/tests -q`、`git diff --check`、4file以内・500行以内を確認 | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| Brief gateとRun ingressの順序 | Run記録ではCampaign現行認可、snapshot、owner、時刻、予算を検査する。完全なBrief検証はRun後の保存時に別呼び出しとする | Run記録時に8章Brief gateを呼ぶ案は、Briefがまだ存在しないため不適切 | lifecycle境界を分離 |
| replay fingerprint | idempotency keyを優先し、runのstarted_at/finished_atとprovenance.occurred_atだけをfingerprintから除く。結果・status・evidence・authorization等は含める | 全dataclass時刻を一律除外する案は業務時刻の変更を隠すため却下 | timestamp再生成を許し、業務内容の変更は衝突 |
| memory transaction境界 | serviceの既存RLock内でreplay→authoritative Campaign/CAS/validation→Campaign/Run/edge/auditを一括し、例外時に変更を戻す | 複数の通常put_node呼び出しは中間成功を許すため却下 | memory adapterの原子性を保証。Neo4jは別担当 |
| Run時刻契約 | approval後start、finishはstart以降、検査時刻以下、authorization expiryより前を共通pure helperで検証する | adapterごとの独立判定はmemory/Neo4jの意味ずれを生むため却下 | helperを小さく共有可能な形にする |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | 初版: memory atomic Run記録の境界と受け入れを定義 | #257 merge後のDEPENDENCY_READY | T-RR-01〜03 |
