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

- 注記: 以下のinventory bulletsはT-IBP-01実装前のmain 2f17185766b8を記録した履歴であり、現在状態は直後のT-IBP-02実装契約の更新基準に従う。

- main `2f17185766b8`には`IdeaBriefVersion` frozen dataclass、8章の既定shape、`research_run_ids`、`InMemoryGraphWriteService.save_idea_brief/get_idea_brief/get_latest_idea_brief`、および`validate_historical_researched_brief`がある。Neo4j向けIdeaBrief serializer/store/labelは存在しない。
- memory saveはfingerprintを厳密に`payload_fingerprint(operation, brief, brief.created_at, expected_latest_revision, owner_id)`としている。一般のdataclass fingerprintが`created_at`を除外しても、明示引数によりBrief作成時刻はintentに含まれる。Neo4jでもこの式をそのまま再利用する。
- memoryの調査検査はRun nodeだけでなく、owner、terminal status、唯一のHAS_RUN edge、唯一の`record_research_run` receipt、receiptと一致するaudit、型付きかつowner一致するCampaign履歴を要求する。Campaign履歴は完全なNeo4j decoderから得る各registryの`.campaigns`をCampaign IDごとに一度だけ結合する。
- 研究済みBriefのsave-time検証は履歴ベースで行い、後日のCampaign期限切れを理由に既に保存したBriefの履歴状態を読み取り時に再分類しない。
- 既存schema version 2は`NodeType`各labelのID unique制約とowner indexを作るが、IdeaBrief専用labelを含まない。専用`IdeaBriefVersion` labelのID制約とowner indexを追加するversion 3 migrationが必要。search indexは作らず、rollbackは制約/indexだけを除去しpayloadを削除しない。

## T-IBP-02 実装契約

T-IBP-02は、strict Idea decoderの独立純関数packet (T-IBP-02A) と、atomic Neo4j store/shared lock packet (T-IBP-02B) に分ける。02Aは保存APIやgateway統合を含めず、02Bは02Aがmainへmergeするまで実装しない。分割は不完全storeを公開せず、decoderを独立に厳密検査するためである。

更新基準: T-IBP-01がmain 139e3f14f35fへmerge済み、その後Neo4j Run/full Campaign history acceptanceとstrict Run decoderがmain 3057772997a2へmerge済み。IdeaBrief専用label、strict Brief codec、strict Run decoder、Campaign full-history resolverを既存依存として利用する。T-IBP-02ではschema migrationを変更・実行しない。

### 保存 / readback

- concrete-only Neo4jIdeaBriefStoreを用意し、`save(brief, *, expected_latest_revision: int | None, idempotency_key: str, actor: str = "local-owner") -> WriteReceipt`、`get(brief_id) -> IdeaBriefVersion | None`、`get_latest(idea_lineage_root_id) -> IdeaBriefVersion | None`を提供する。該当レコードがない場合のget_latestはNone、存在するが破損/不連続/曖昧なlineageはfail closed。GraphWritePort、MCP、FastAPI/stdio、runtime compositionには追加しない。
- saveはmemoryと同じfingerprint payload_fingerprint("save_idea_brief", brief, brief.created_at, expected_latest_revision, owner_id)を使う。owner、actor、key、expected revisionを先に検査する。transactionの最初にowner-scoped audit receiptを照合し、同一key・同一operation・同一fingerprintなら現在のIdea/Campaign状態を再検証せず元receiptをreplayed=Trueで返す。operationまたはfingerprint違いはIdempotencyConflictError。
- Neo4j transaction中、既存receipt再確認 → Idea lineage root lock → receipt再確認 → strict Idea chain read → current leaf lock → exact leaf/readback再確認 → unique sorted Campaign locks → Research proof → exact latest-Brief CAS → global node-ID collision check → Brief node + audit CREATE の順に行う。固定lock順はIdea root → Idea leaf → Campaign ID昇順。全て単一write transaction内。
- Idea lineage確認はowner-scoped Idea scanでscalar `supersedes_id`とstrict typed payloadを照合する。新shapeはscalarとpayloadの親IDが一致しなければfail closed、scalar欠落の旧payload-only Ideaはdecodeした親IDを使う。rootには親IDpropertyを残さず、successorには親IDを文字列で保存する。このbounded scanは単一ownerの書込系譜確認用で、移行なしに既存訂正を取りこぼさない。
- BriefはT-IBP-01 serializerが返すexact metadata/payloadを用いたIdeaBriefVersion nodeとして保存する。scalar metadataはid, owner_id, node_type, revision, idea_lineage_root_id, supersedes_idに限定し、based_on_idea_idと本文はpayloadのみに置く。Brief version間の関係を新設せず、既存版を上書きしない。auditは同一transactionでsave_idea_brief, target/type/revision, idempotency key, fingerprint, actorを記録する。Brief本文・sectionをsearch_textや通常read projectionへ複製しない。
- getはid + owner_idをCypherで絞り、全record metadataをstrict Brief decoderへ渡す。get_latestはowner_id + idea_lineage_root_idの全版をstrict decodeし、revision 1から連続しsupersedes_idが前版と一致する一意chainだけを認める。該当レコードがない場合はNoneを返す。既存のgap、duplicate revision、fork、foreign owner、payload/metadata mismatchはfail closed。
- driverがcommit後に例外を返す場合は、別sessionで同じowner-scoped audit receiptだけを読み直す。operation、fingerprint、target_id、target_type、revisionが要求と完全一致するreceiptだけreplayを返す。receipt未確認、別fingerprint/target/type/revision、またはreadback自体の失敗は固定Neo4jUnavailableErrorを保持する。推測で成功を返したり、raw driver error/payloadを外へ出さない。

### Current Idea / lock contract

- strict Idea decoderは許可された全dataclass payload fieldsと全Provenance fieldsを必須にし、id/owner/node_type/revision record metadataとの一致、enum/time型、canonical re-serializationを確認する。現在のNeo4jGraphWriteService._hydrate_correctionはmissing fieldをdefault補完するため使用しない。復元時にID、時刻、fieldを生成・正規化しない。
- rootはowner-scoped Ideaでsupersedes_id is Noneかつrevision 0の起点。保存時は指定rootから各子supersedes_idをたどり、全nodeのowner/type/revision連続性、唯一のsuccessor、cycleなしを確認してleafを決める。Briefのbased_on_idea_idはそのleaf IDと完全一致し、archived/superseded/retracted leafは拒否する。
- Brief保存と、Idea successorを作る全経路(put_node, record_correction, successorを含むcapture_idea)は同一のowner-scoped root lockを共有する。successor writerはowner-scoped predecessor chainをたどってroot候補を特定し、root lockを得た後でchainを再解決し、parent leafをlockしてunique leaf・owner・revision連続性を再確認してからCREATEする。順序が逆の別実装を追加しない。初回root作成は既存lineageがない場合のみ許す。既存IDの同一Idea更新は現在もNodeAlreadyExistsで拒否されるため、このimmutable behaviorを保ち、in-place SET経路を作らない。capture_ideaの再capture replayは既存receiptのみ返し、Ideaを書き換えない。将来in-place write経路を追加する場合は同じroot lockを必須にするが、T-IBP-02では許可しない。

### Researched Brief proof

- research_run_idsが空ならdraft保存とし、Run/Campaign proofは要求しない。非空なら各IDについてowner-scoped persisted RunをA担当strict decoder founder_graph_neo4j_run.decode_persisted_research_run(record, owner_id=..., expected_id=...)で復元する。同moduleがmainへmergeするまでは実装を開始せず、独自Run decoderを作らない。
- Runごとにexact ResearchCampaign-[:HAS_RUN]->ResearchRun edgeが1本だけあり、owner-scoped FounderGraphAuditにoperation=record_research_run, exact target ID/type/revision, non-empty idempotency key/fingerprintが1件だけ存在することを確認する。Run provenance keyとaudit idempotency keyの同一性はmemory契約で要求されないため仮定しない。audit/edge欠落・重複・不一致はfail closed。
- Runを読みCampaign IDを確定後、重複を除いたCampaign IDを辞書順でlockし、各Campaign registryを一度だけ再取得する。既存_campaign_authorization_registry_txがstrict current Campaign + full contiguous FounderGraphHistory (revision 0..current) を組み立てるためこれを利用し、最新Campaignを二重追加しない。Campaign history欠落・不正・sparse legacy payloadは推測またはbackfillせず拒否する。
- validate_historical_researched_brief(brief, current_idea, runs, campaigns)へ完全typed valuesだけを渡す。全8section、COMPLETED/owner Run、Campaign authorization snapshot履歴、Idea scope、approval/revocation/expiry時刻をsave時に検証する。後日のexpiry/revocationは既保存Briefのreadbackを再分類しない。
- Assertion writerとの将来共有用に、同じlock済みtransaction内で呼ぶ内部`_validate_latest_researched_brief_tx(tx, *, primary_idea_id, owner_id, brief_id, section_index, evidence_ids, locked_ideas, at=None, brief_override=None) -> AcceptedIdeaBriefProof`境界をこのpacketで定義する。成功時の内部typed proofはBrief/section/revision、Idea root/current leaf ID・revision、検証済みevidence IDだけを持ち、本文/Campaign/Run raw payloadは持たない。Brief存在・最新性、選択section/evidence subset、上記Campaign/Run履歴検査を再利用する。呼出前にendpoint側がowner-scoped root IDsを昇順、current leaf IDsを昇順にlockし、helperはそのIdea lockを取り直さずsorted Campaign locksだけを取得する。二つのIdea endpointでは一方をprimaryとしてBriefを結び、双方のcurrent leaf証明をproofに含める。これはpublic APIでなく、別Neo4j sessionや事前`get_latest`をproofとして使わない。

### T-IBP-02 file / test boundary

| 区分 | ファイル | 契約 |
|---|---|---|
| strict Idea hydration prerequisite (T-IBP-02A) | backend/dots/founder_graph_neo4j_idea.py | exact owner/id/type/revision/payload/Provenance decoder。Run decoderを複製しない。gateway/storeへ接続しない |
| T-IBP-02A tests | backend/tests/test_founder_graph_neo4j_idea_decoder.py | complete roundtrip、欠落/余分/型/identity/duplicate JSON/nonfinite/timestamp/normalization rejection |
| T-IBP-02B gateway/store | backend/dots/founder_graph_neo4j.py, backend/dots/founder_graph_neo4j_write.py | Brief transaction、Idea root/leaf shared lock、Idea successor writes、Campaign lock/history proof、audit/replay recovery |
| T-IBP-02B tests | backend/tests/test_founder_graph_neo4j_idea_brief_store.py | isolated stateful fake transaction。memory parity、negative proof、rollback boundary |

- 検査条件: initial/revised draft, get/latest exact immutability, 8-section/full-field/created_at parity, stale CAS, same-key replay after Idea successor/Campaign later revocation, changed fingerprint/operation conflict, global ID collision, Idea fork/gap/foreign/corrupt record, replay/CAS/no-mutation, strict Run decoder malformed/foreign/wrong-type/wrong-ID, missing/duplicate/wrong HAS_RUN, missing/duplicate/wrong audit, incomplete Campaign history, multiple Runs in one Campaign, Runs across sorted Campaign locks, all researched brief section/status/snapshot/scope/time negatives, injected failure after Brief CREATE but before audit rollback, unknown-commit matching receipt recovery and failed receipt lookup. Error assertions use fixed safe errors and never print payloads.
- Lock fakes prove query order/interleaving decisions only; they do not prove real Neo4j lock serialization or rollback. Those claims remain T-IBP-03/04 and require C's separately reviewed disposable harness. Existing main backend suite and git diff --check are required.
- 変更量目標500行に対し初回見積りは約620行だったが、strict Idea decoderをT-IBP-02Aへ独立化した後もatomic store/shared-lock packetが650行を超える場合は、その時点の正確なscopeとline数で再承認を受ける。Brief CREATE/audit境界、Idea correction locks、full historical Run proofは一つの保存契約であり、必須negative/failure testを削って上限へ合わせない。

### T-IBP-02 known gaps

- 既知: T-IBP-01 strict Brief codec/schema、strict Campaign decoder/full-history resolver、historical researched Brief validator、memory save parity、Neo4j Campaign transaction lock/history writerはmainにある。
- 既知: Neo4jのcurrent Idea hydrationはpermissive、Brief storeは未実装、generic Idea successor writeはroot/leaf lockを持たない。capture_ideaもrevisioned Ideaを入力できるため、T-IBP-02ではそのsuccessor pathも同じshared lockへ統合する。
- 類推可能: existing Campaign transaction patternsをIdea root/leaf locksへ適用し、fake transactionでsame Cypher transaction orderingを確認できる。
- 未知: 実Neo4jでBrief save lockがsave_idea_briefとIdea successor writesを直列化し、transaction途中の例外がBrief/auditを残さない。T-IBP-03/04 C-ownedであり、merge/review/実行許可後のexact disposable DBだけで検証する。

## タスク
T-IBP-02行はsummaryである。詳細なファイル、受け入れ条件、約620行見積りと例外境界は直前のT-IBP-02実装契約を正本とする。

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-IBP-01 | `founder_graph_neo4j_idea_brief.py`のstrict Brief serializer/decoder helpers、`founder_graph_schema.py` v3 migration、`test_founder_graph_neo4j_idea_brief.py`と既存schema/gateway migration tests | 検査: draft/8章/full-field/timezone roundtrip、空section draft、exact key/metadata検査、nullable以外の欠落/余分/不正型/空白正規化拒否、migration v1→v3・rollback queryおよびoffline gateway migrate/rollback契約を確認。save/read/store APIやincomplete stubは公開しない。変更量目標450行以内 | 類推可能 |
| T-IBP-02A | `founder_graph_neo4j_idea.py`のstrict Idea decoderと専用pure tests。gateway/store接続なし | 検査: complete roundtrip、欠落/余分/型/owner/id/revision/duplicate JSON/nonfinite/timestamp/normalization拒否を専用pytestと`git diff --check`で確認 | 類推可能 |
| T-IBP-02B | `founder_graph_neo4j.py`のIdea successor root/leaf lock、Brief lineage/latest CAS、atomic save/read/replay/audit、Run/Campaign historical proofと専用test | 検査: memory parity(initial/revision/get/latest/stale CAS/replay/fingerprint/created_at)、sorted root→leaf→Campaign lock、new scalar/legacy payload-only Idea chain、scalar mismatch fail-closed、current Brief、sibling fork no-mutation、global ID collision、Run/HAS_RUN/audit/history negative、rollback/unknown-commit recovery、focused31 passed、backend全suite、`git diff --check`を確認。02A/strict Run decoder merge後。 | 類推可能 |
| T-IBP-03 | C所有、30分上限の既存disposable Neo4j harness read-only確認 | 検査: merged revision-lock transaction harnessでBrief write中断の注入点、safe failure分類、loopback/container/volume境界とcleanup検証方法を特定する。ここでは実Brief DB runを行わない。通常DB/service不使用 | 未知 |
| T-IBP-04 | C所有の隔離Neo4j persistence/rollback proof | 検査: T-IBP-02 merged後、T-IBP-03 spikeと独立review/実行許可後にsynthetic-only disposable Neo4jでdraft/researched save/replay/CAS/rollback/readbackを確認し、exact container/volume cleanupとzero residueを検査。通常DB/service不使用 | 未知・T-IBP-03先行 |

## ADR
| 判断 | 選択と理由 | 却下案と却下理由 | 結果 |
|---|---|---|---|
| 保存label | `IdeaBriefVersion`専用labelとscalar lineage fields (`idea_lineage_root_id`, `revision`, `supersedes_id`)を使う。Briefは`NodeType`ではなくReportVersionとも異なるaggregate | ReportVersion/Idea labelを流用すると型境界と既存read契約を壊す。監査payloadへBrief全体を埋める案は最新版CASとimmutable readbackを提供しない | schema v3にunique ID制約とowner indexのみ追加し、検索投影へ載せない |
| interface | まず`Neo4jIdeaBriefStore` concrete-only APIとして実装し、既存`GraphWritePort`を拡張しない | Protocol追加は未実装adapterへ実装済み能力を誤表示し、MCP/runtime公開範囲を拡大する | 保存・取得readbackは同じowner-bound gatewayへ結び、公開配線は別承認後 |
| current IdeaとBrief CAS | Brief保存はrootをlockして系譜を読み、terminal Idea leafをowner-scoped temporary lock後に再読込する。Idea successor作成も同じparent leafをlockしてからsuccessor有無とrevisionを検証する | 事前readによるcheck-then-writeやBrief専用lockだけではIdea correctionとのTOCTOU/forkを防げない | root lockはBrief同士、共有leaf lockはBrief保存とIdea correctionを直列化し、exact current Ideaとlatest Brief CASを同じtransactionで確定する |
| Idea predecessor property | `_node_properties`はIdeaのfull typed payloadに加えて非null`supersedes_id`をscalar propertyへ書く。owner-scoped chain scanはscalarをpayloadと照合し、欠落scalarの既存payload-only訂正も取り込む | fakeがpayload JSON内のreferenceを直接検索してNeo4j propertyの不在を隠す案、およびscalar/payload不一致を無視する案を却下 | root→successor→current Brief lookup、旧shape fallback、不一致拒否、sibling fork rejectionを検査する |
| 調査根拠 | Run/audit/HAS_RUNを現在のowner-scoped保存から厳密hydrateし、完全Campaign履歴の`.campaigns`をhistorical pure validatorへ渡す | caller供給snapshot/current Campaignだけで認可すると未登録Run・過去許諾を証明できない | validator結果はbool/errorのみ使い、Run/Campaign raw payloadをBrief getter/APIへ返さない |
| schema rollback | migration 3のconstraint/indexのみrollbackし、Brief nodeは自動削除しない | schema rollbackにpayload削除を結合すると再試行不能・情報損失となる | migration実行は別release gate。通常DBには本計画だけで実行しない |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-09-26 | main 3057772997a2を基準にstrict Idea decoderをT-IBP-02Aとして分離し、atomic store/shared locksをT-IBP-02へ依存させた | malformed Ideaを不完全なdefault付きdecoderで扱わず、store APIを実装前に独立検査できる | T-IBP-02A〜04 |
| 2026-09-26 | T-IBP-02Bを826変更行で実装。root承認の850行例外を適用し、Run/Campaign proof付き保存の縦断検査と既存Idea correction lock互換検査を保持 | atomic Brief save・full authorization history proof・全Idea successor writer lock・unknown commit/recoveryを一つの縦断契約として検証する必要があり、これ以上の分割は安全negativeや正例を省くか、接続されないstub packetを生むため。Idea rootはdomainが許す非負revisionのままとし、後続revisionのみ厳密に+1。TDDでunknown-commit例外順を再現後に修正。focused30、backend774 passed/4 skipped/7 warnings、diff-check clean | T-IBP-02B |
| 2026-09-26 | PR #275 reviewで検出したIdea predecessor scalar-property/lineage-query不一致と旧payload-only記録の見落としを修正。累計881変更行、rootが今回に限り承認した900上限内 | owner-scoped scanでscalar/payload一致を確認し、旧shapeをstrict decodeでfallback、矛盾shapeはfail closed。既存訂正を取りこぼさず root/current Brief/siblingを確認する同一永続Brief契約の修正であり、安全回帰を分割せず一目的内に保持。focused31 passed、backend全suite、diff-check clean | T-IBP-02B |
| 2026-09-26 | main memory implementationとschema v2を監査し、永続Brief、Run登録証明、full Campaign history、CAS/fingerprint、schema migration境界を計画 | Neo4j adapterのIdeaBrief機能はmainに存在せず、memory-only契約を安全に永続層へ移す必要がある | T-IBP-01〜03 |
| 2026-09-26 | 実装境界を厳密Brief serialization/schema v3 packetとatomic store/proof packetに分割し、T-IBP-01はserializerとschemaのみでsave stub/APIを含めない。T-IBP-04はT-IBP-02のmerge後のみ実行する | T-IBP-01単独の意味単位を限定し、incomplete persistenceを利用可能に見せない | T-IBP-01〜04 |
| 2026-09-26 | T-IBP-01成果物の既存migration integration testsを計画のファイル範囲へ明記 | SCHEMA_VERSION変更時にoffline gateway rollback expectationも同一packetで更新する | T-IBP-01 |
| 2026-09-26 | decoderのidentifier/reference whitespace正規化拒否とdraft空section roundtripをT-IBP-01へ追加し、ID collision検査を実writerのT-IBP-02へ限定 | strict codecは値の正規化可否を検査できるが、Neo4j全node labelの衝突はDB write境界でのみ証明できる | T-IBP-01,T-IBP-02 |
