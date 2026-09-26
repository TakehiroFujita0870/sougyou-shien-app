# Neo4j IdeaBrief永続化 計画
最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: mainにあるimmutable `IdeaBriefVersion`とResearchRun参照契約を、既存のmemory writerと同じ保存・読戻し・認可根拠でNeo4jへ永続化する。

ゴール: ownerが現在保持するIdea系譜とBriefの最新版をtransaction内で検証し、draftと調査根拠付きBriefを不変revisionとして保存できる。

成功指標: memory契約と一致するCAS、replay/fingerprint、`created_at`、8章、revision履歴をNeo4j fakeで比較し、ResearchRunの登録・監査・HAS_RUN・Campaign全履歴が揃わない場合に保存を拒否する。実Neo4j rollbackは別の隔離試験で証明する。

## ユーザーストーリーと受け入れ条件

### US-IBP-01 — IdeaとBriefの所有者・最新版を検証
As a local Founder Graph owner, I want each immutable idea brief version anchored to my exact current Idea, so that stale or forked idea lineages cannot receive a new brief.

Given: owner-scoped Idea lineage root and optional existing Brief history are stored.
When: the persistent Brief store accepts an initial version or revision.
Then: it locks the owner’s root and current Idea in one transaction, validates one unbranched and contiguous Idea lineage, and requires `expected_latest_revision` and `supersedes_id` to match the unique latest Brief.

### US-IBP-02 — Briefをmemory契約どおり不変保存
As a local owner, I want every saved brief to round-trip without losing its eight sections or creation time, so that later review sees the exact accepted version.

Given: a valid immutable `IdeaBriefVersion` and idempotency key.
When: it is saved or retrieved by exact ID/latest Idea root.
Then: strict serialization preserves every field, section index/content/classification/reference tuple, egress policy, and timezone-aware `created_at`; save, audit receipt, and lineage record commit atomically, while old versions remain unchanged. Hydration requires the exact persisted key set and matching owner/id/type/revision metadata, accepts only contract-defined nulls, and never fills missing values or generates IDs/timestamps.

### US-IBP-03 — 調査根拠を完全に証明
As a local owner, I want a researched brief accepted only when its Runs and historical authorizations are already durably registered, so that a caller cannot assert an unrecorded or unauthorized Run.

Given: a candidate brief names one or more ResearchRuns.
When: the store validates those references inside the save transaction.
Then: every Run is an owner-scoped typed terminal Run with exactly one matching `ResearchCampaign-[:HAS_RUN]->ResearchRun` edge and exactly one matching `record_research_run` audit receipt, and its full owner-scoped Campaign history is resolved once and passed as `CampaignAuthorizationRegistry.campaigns` to `validate_historical_researched_brief`; otherwise no Brief or audit mutation remains.

### US-IBP-04 — Replayと競合を安全に扱う
As a local owner, I want retries to return only the original receipt and stale writes to fail, so that network uncertainty cannot create duplicate or competing brief revisions.

Given: a key is replayed with identical or changed command content, or two writes target one Idea root.
When: either write executes.
Then: identical replay is checked before current Idea/Campaign expiry or latest-revision validation and returns the original receipt without mutation; a changed fingerprint raises `IdempotencyConflictError`; stale CAS or a concurrent loser raises a fixed safe conflict and preserves the winner.

## 質問リスト
| ID | 質問 | 決定者 | 期限 |
|---|---|---|---|
| なし | 保存と認可の境界は既存memory writerおよびhistorical validatorで確定済み | — | — |

## スコープ外
- public `GraphWritePort`/Protocol、MCP tools/schema、FastAPI/stdio endpoints、runtime切替。内部専用store methodのみを対象とする。
- IdeaBriefを通常search/fetch/export/public allowlistへ露出すること。
- Campaign履歴のbackfill、Run/Campaign/Briefの過去payload推測、通常DBへのmigration実行やデータ書込み。
- 外部調査、ChatGPT接続、LLM、報告書の別形式。
- 実データを使う受入。全fixtureはsynthetic-only。

## 現状監査と保存契約

- main `2f17185766b8`には`IdeaBriefVersion` frozen dataclass、8章の既定shape、`research_run_ids`、`InMemoryGraphWriteService.save_idea_brief/get_idea_brief/get_latest_idea_brief`、および`validate_historical_researched_brief`がある。Neo4j向けIdeaBrief serializer/store/labelは存在しない。
- memory saveはfingerprintを厳密に`payload_fingerprint(operation, brief, brief.created_at, expected_latest_revision, owner_id)`としている。一般のdataclass fingerprintが`created_at`を除外しても、明示引数によりBrief作成時刻はintentに含まれる。Neo4jでもこの式をそのまま再利用する。
- memoryの調査検査はRun nodeだけでなく、owner、terminal status、唯一のHAS_RUN edge、唯一の`record_research_run` receipt、receiptと一致するaudit、型付きかつowner一致するCampaign履歴を要求する。Campaign履歴は完全なNeo4j decoderから得る各registryの`.campaigns`をCampaign IDごとに一度だけ結合する。
- 研究済みBriefのsave-time検証は履歴ベースで行い、後日のCampaign期限切れを理由に既に保存したBriefの履歴状態を読み取り時に再分類しない。
- 既存schema version 2は`NodeType`各labelのID unique制約とowner indexを作るが、IdeaBrief専用labelを含まない。専用`IdeaBriefVersion` labelのID制約とowner indexを追加するversion 3 migrationが必要。search indexは作らず、rollbackは制約/indexだけを除去しpayloadを削除しない。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-IBP-01 | `founder_graph_neo4j_idea_brief.py`のstrict Brief serializer/decoder helpers、`founder_graph_schema.py` v3 migration、`test_founder_graph_neo4j_idea_brief.py`と既存schema/gateway migration tests | 検査: draft/8章/full-field/timezone roundtrip、空section draft、exact key/metadata検査、nullable以外の欠落/余分/不正型/空白正規化拒否、migration v1→v3・rollback queryおよびoffline gateway migrate/rollback契約を確認。save/read/store APIやincomplete stubは公開しない。変更量目標450行以内 | 類推可能 |
| T-IBP-02 | `founder_graph_neo4j.py`のIdea successor leaf-lock hook、Brief lineage/latest CAS、atomic save/read/replay/audit、Run/Campaign historical proofと専用testの拡張 | 検査: Run hydrateもexact full-key/type/owner/revision検査でdefaults/新timestampを生成しないこと、memory parity (initial/revision/get/latest/stale CAS/replay/fingerprint/created_at)、root→leaf lock下のconcurrent Brief/Idea revision winner-or-conflict、static node-label全域のID collision、multi-Run same/different Campaign `.campaigns`、exact edge/receipt/audit、invalid history no-mutation、fake rollback-boundaryを確認し、`uv run pytest backend/tests -q`と`git diff --check`を実施。T-IBP-01 merged後に別packetとして実施し、変更量目標480行以内 | 類推可能 |
| T-IBP-03 | C所有、30分上限の既存disposable Neo4j harness read-only確認 | 検査: merged revision-lock transaction harnessでBrief write中断の注入点、safe failure分類、loopback/container/volume境界とcleanup検証方法を特定する。ここでは実Brief DB runを行わない。通常DB/service不使用 | 未知 |
| T-IBP-04 | C所有の隔離Neo4j persistence/rollback proof | 検査: T-IBP-02 merged後、T-IBP-03 spikeと独立review/実行許可後にsynthetic-only disposable Neo4jでdraft/researched save/replay/CAS/rollback/readbackを確認し、exact container/volume cleanupとzero residueを検査。通常DB/service不使用 | 未知・T-IBP-03先行 |

## ADR
| 判断 | 選択と理由 | 却下案と却下理由 | 結果 |
|---|---|---|---|
| 保存label | `IdeaBriefVersion`専用labelとscalar lineage fields (`idea_lineage_root_id`, `revision`, `supersedes_id`)を使う。Briefは`NodeType`ではなくReportVersionとも異なるaggregate | ReportVersion/Idea labelを流用すると型境界と既存read契約を壊す。監査payloadへBrief全体を埋める案は最新版CASとimmutable readbackを提供しない | schema v3にunique ID制約とowner indexのみ追加し、検索投影へ載せない |
| interface | まず`Neo4jIdeaBriefStore` concrete-only APIとして実装し、既存`GraphWritePort`を拡張しない | Protocol追加は未実装adapterへ実装済み能力を誤表示し、MCP/runtime公開範囲を拡大する | 保存・取得readbackは同じowner-bound gatewayへ結び、公開配線は別承認後 |
| current IdeaとBrief CAS | Brief保存はrootをlockして系譜を読み、terminal Idea leafをowner-scoped temporary lock後に再読込する。Idea successor作成も同じparent leafをlockしてからsuccessor有無とrevisionを検証する | 事前readによるcheck-then-writeやBrief専用lockだけではIdea correctionとのTOCTOU/forkを防げない | root lockはBrief同士、共有leaf lockはBrief保存とIdea correctionを直列化し、exact current Ideaとlatest Brief CASを同じtransactionで確定する |
| 調査根拠 | Run/audit/HAS_RUNを現在のowner-scoped保存から厳密hydrateし、完全Campaign履歴の`.campaigns`をhistorical pure validatorへ渡す | caller供給snapshot/current Campaignだけで認可すると未登録Run・過去許諾を証明できない | validator結果はbool/errorのみ使い、Run/Campaign raw payloadをBrief getter/APIへ返さない |
| schema rollback | migration 3のconstraint/indexのみrollbackし、Brief nodeは自動削除しない | schema rollbackにpayload削除を結合すると再試行不能・情報損失となる | migration実行は別release gate。通常DBには本計画だけで実行しない |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-09-26 | main memory implementationとschema v2を監査し、永続Brief、Run登録証明、full Campaign history、CAS/fingerprint、schema migration境界を計画 | Neo4j adapterのIdeaBrief機能はmainに存在せず、memory-only契約を安全に永続層へ移す必要がある | T-IBP-01〜03 |
| 2026-09-26 | 実装境界を厳密Brief serialization/schema v3 packetとatomic store/proof packetに分割し、T-IBP-01はserializerとschemaのみでsave stub/APIを含めない。T-IBP-04はT-IBP-02のmerge後のみ実行する | T-IBP-01単独の意味単位を限定し、incomplete persistenceを利用可能に見せない | T-IBP-01〜04 |
| 2026-09-26 | T-IBP-01成果物の既存migration integration testsを計画のファイル範囲へ明記 | SCHEMA_VERSION変更時にoffline gateway rollback expectationも同一packetで更新する | T-IBP-01 |
| 2026-09-26 | decoderのidentifier/reference whitespace正規化拒否とdraft空section roundtripをT-IBP-01へ追加し、ID collision検査を実writerのT-IBP-02へ限定 | strict codecは値の正規化可否を検査できるが、Neo4j全node labelの衝突はDB write境界でのみ証明できる | T-IBP-01,T-IBP-02 |
