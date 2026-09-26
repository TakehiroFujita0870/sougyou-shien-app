# Founder Graph RelationAssertion write plan
最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: 正式な意味関係を、型付き端点・根拠・訂正履歴とともに一度だけ安全に保存する。

ゴール: `RelationAssertion`、構造edge、監査、冪等受領を一つのatomic writeとして扱い、Idea関係にはexact current Brief/章と、そのBrief作成時に受理されたRunの履歴を結び付ける。

成功指標: memory writerがcanonical IDを一度保存し、同じintentの再送で同じopaque IDを返す。不整合入力は状態を変えない。Neo4j writerは別packetで同一契約をtransactionally満たし、実DB rollback gate完了までMCP/runtime exposedとは扱わない。

## ユーザーストーリーと受け入れ条件

### US-1 型付き・根拠付きassertionを保存する

As a Founder Graph owner, I want a formal relation to reference existing owner-scoped entities and active Evidence, so that its endpoints and justification can be checked later.

Given: 同一ownerの既存端点と、各Evidence IDが指すactive・同一ownerの`Evidence`がある。
When: memory writerが`RelationAssertion`を保存する。
Then: 実ノード、型、ownerを照合し、`ASSERTS_FROM`、`ASSERTS_TO`、各`EVIDENCED_BY`を一度だけ作り、canonical receiptと監査記録を返す。

Given: endpointまたはEvidenceが欠落、foreign、inactive、または宣言型と異なる。
When: writeを試す。
Then: node/history/edge/audit/idempotency stateを一切変更せず失敗する。

### US-2 Idea関係を特定の受理済み調査へ結ぶ

As a Founder Graph owner, I want an Idea-related formal relation to cite its exact current brief and section, so that reasoning provenance is traceable without repeating research.

Given: 同一ownerの8-section `IdeaBriefVersion`があり、全`research_run_ids`が正規保存済みcompleted `ResearchRun`を指し、保存されたauthorization snapshot/revisionが各Runの実行時点で有効だったことを信頼できる履歴で確認できる。
When: `based_on_brief_id`とsection indexを持つRelationAssertionを保存する。
Then: M0のowner-scoped storeからexact/latest Briefを解決し、Briefが参照するcurrent IdeaとassertionのIdea endpoint、指定section 0〜7、assertionのEvidence IDsがそのsectionのEvidence IDsに含まれることを照合する。Ideaのformal relationではBriefのRun参照が空なら拒否する。各completed Runはtyped owner-scoped node、単一`HAS_RUN`、一意な`record_research_run` receipt/audit、typed Campaign historyを再解決し、V-Mのhistorical proofで通す。

Given: campaign authorizationがRun完了後に期限切れまたはrevokedとなっている。
When: そのauthorization下で受理・永続されたRunが参照される。
Then: 後日のexpiry/revocationだけで過去のRun/briefを無効化しない。`validate_researched_brief(..., at=now)`を再実行してはならない。

Given: historical authorization at Run finishをauthoritativeに復元できるrecordがない。
When: lineage gateを実装または呼び出す。
Then: fail closedし、現在時刻validatorで近似しない。不変run-authorization proof保存が完了するまでformal Idea-linkを受け付けない。

### US-3 関係訂正・再送は履歴を保つ

As a Founder Graph owner, I want relation corrections and retries to preserve one canonical history, so that rejected or superseded relations cannot be resurrected or duplicated.

Given: 初回assertion、または直近successorのないowner内assertionがある。
When: 同じ関係を訂正して保存する。
Then: 同じfamilyのrevisionを一つ増やし、後継から旧版への`SUPERSEDES`を追加する。端点/述語変更は新familyのrevision 1にする。

Given: 旧assertionにstatusを問わずsuccessorがある。
When: 別keyで二つ目のsuccessorを追加する。
Then: rejectし、既存history・edges・auditを変更しない。

Given: 成功済みcommandを同一key・同一intentまたは同一key・異なるintentで再送する。
When: writerがcommandを処理する。
Then: 同一intentはcurrent stateの再検証/edge repairなしでreplayed receiptを返す。異なるintentはconflictで変更なし。server-generated `valid_from`差だけは同一intentとする。

Given: node/edge作成後audit前に例外が起きる。
When: writeが失敗する。
Then: memoryでは全変更をrollbackし、Neo4jは同一transaction rollbackでnode/edge/audit/receiptを残さない。

Given: 正規登録済みRelationAssertionがあり、同じfamilyまたはendpoint/predicateを変更した訂正を行う。
When: M1のmemory writerが新assertionを保存する。
Then: family latest revisionと期待predecessorのCASを検証し、新assertionから旧assertionへの`SUPERSEDES`とassertionのendpoint/Evidence edgesを一度だけ追加する。owner内で既にsuccessorを持つassertionを再度supersedeできず、別ownerのassertionはfamily・successor判定に影響しない。

Given: 保存済みcommandと一致するidempotency key/fingerprintがある。
When: 同じcommandを再送する。
Then: mutable Idea/Brief/Evidence/successor状態の再検証やedge repairをせず、receipt lookupだけでreplayed receiptを返す。異なるintentの再利用はconflictで状態不変とする。

## 質問リスト / 先行スパイク

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| P4-05-SP-01 | approved snapshotのapproval時刻とrun登録receiptがhistoryから一意に対応付くか。`validate_researched_brief(..., at=now)`再利用は禁止。 | domain/persistence owner + root | 2026-09-26 audit完了。memory/Neo4jの差を下記へ記録 |

最大30分のread-only code audit（2026-09-26、基準main #259 `0294205a2f88`）。Memoryでは`record_research_run`がtyped Run、Campaign aggregate history、`HAS_RUN`、audit、receiptをlock/rollback内で扱い、Campaign node historyは完全な型付き値を保持する。Runはcampaign ID、authorization snapshot ID/revision、start/finishを持つ。従って純粋な歴史validatorはmemoryのtyped historyを入力にして先行実装できるが、既存の`CampaignAuthorizationRegistry.resolve_current`や`validate_researched_brief(..., at=now)`は現行状態を選ぶため流用しない。保存時の現行許諾検査と、既に受理されたBriefのRun時点履歴検査は別契約とする。

Neo4j側はgeneric `FounderGraphHistory.payload_json`が`{id,node_type,revision}`のみで、現在のCampaign payloadだけでは後日取消・scope変更前の承認内容を復元できない。またこのmainにはNeo4jの原子的Run登録writerがまだない。コード監査はsynthetic validator実行やNeo4j永続性の証明ではない。Neo4j Run writerがCampaign/Run/history/`HAS_RUN`/audit/receiptを同じtransactionで保存し、prior Campaignの型付きsnapshot履歴を保持するまでNeo resolver・Neo relation writer・MCP exposureは不可。Sparse legacy historyはproofとしてfail closedする。

## スコープ外

- MCP/API/stdio公開、runtime reload、ChatGPT/実ユーザーデータ、実Neo4j接続。
- Person merge UI、Facet taxonomy固有cycle validation、legacy `Relationship`移行/削除。
- Campaignの現在状態を過去Runのauthorization証明として扱うこと。

## タスク / packet境界

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| P4-05-SP-01 | historical Run authorization evidenceのread-only code audit | 検査: Run/Campaign/History/receipt/edgeの型付き参照と必要なfinish時点proof fieldsを対応付け、memory/Neo4jの復元可否とfail-closed条件を記録。synthetic behavior casesは未実行でP4-05V-M/V-Nの受入条件に含める | code audit完了、behavior未検証 |
| P4-05V-M | Run履歴を検証するpure validatorとsynthetic tests | 検査: typed Campaign historyからRun snapshot ID/revision・owner・Idea scope・approval/expiry時刻を照合。valid historyは後日revoke/expiry後も受理し、missing/foreign/ambiguous/mismatched history、unfinished Run、`at=now`再検証を拒否。exact/latest brief ID、registered Run・`HAS_RUN`・receiptは呼出側/store側の必須事前条件であり、このvalidatorは解決・証明しない | 既知（実装済み、synthetic testsあり） |
| P4-05M0 | owner-scoped memory `IdeaBriefVersion` lineage storage/writer/readとfocused tests | 検査: same-owner current Idea/root lineageとimmutable Idea revision IDを照合し、brief revision/supersedes連続性、必須expected-latest CAS、同key同intent replay/異intent conflict、authoritative latest lookup、audit fault rollbackを検査。nonempty `research_run_ids`はmemory内のtyped completed Run、exact `HAS_RUN`、write receipt/audit、typed Campaign historyを解決してP4-05V-Mを通す。service内の凍結typed valuesだけ保持し、caller status/latest claimsを信用しない。差分500行以内 | 既知（PR #265 merged、main smoke済み） |
| P4-05M1 | domain edge contractとconcrete-only `InMemoryGraphWriteService.save_relation_assertion`、専用tests | 成果物ファイル: `backend/dots/founder_graph.py`（dedicated `RelationAssertionEdgeType`とcanonical typed-triple helper）、`backend/dots/founder_graph_write.py`、`backend/tests/test_founder_graph_relation_assertion_write.py`、`backend/tests/test_founder_graph_v2_parity.py`、本計画。検査: owner/type/current lifecycleが有効な端点（同owner superseding childのないcurrent revision）、assertion declared kindとの完全一致、active same-owner Evidence、idempotency receipt/audit、family CAS、successor uniqueness、全構造edgeを検査。canonical edgesは`RelationAssertion -ASSERTS_FROM-> source`、`RelationAssertion -ASSERTS_TO-> target`、`RelationAssertion -EVIDENCED_BY-> Evidence`、訂正時`successor -SUPERSEDES-> predecessor`。dedicated enum/helperは構造edgeのlabelと方向を閉じて定義し、一般`RelationType`/`Relationship`から新3種edgeを作れないようにする。既存`RelationType.SUPERSEDES`もRelationAssertion同士の`link_entities`利用だけ拒否してfamily CASを迂回させず、それ以外の既存SUPERSEDES pairは変えない。Idea endpointを含む新しいformal assertionはbrief pair必須とし、M0のowner-scoped latest Brief ID、exact current Idea ID、全8章、指定章のEvidence ID所属を照合する。Idea関係ではBriefのRun参照が非空であること。briefの全Runはtyped completed owner-scoped node、exactly-one `HAS_RUN`、一意なwrite receipt/audit、typed Campaign historyで登録証明し、V-M historical proofで許諾を確認する。current-time authorizationを再評価しない。receipt-first replayは状態検査もedge修復もしない。同family correctionは期待latest revision+1、changed endpoint/predicate correctionは新family revision 1とし、いずれも期待predecessorと一致する`supersedes_id`を検証してsupersedeする。初回familyはrevision 1。`assertion.id`を含むcaller intentでfingerprintし、`valid_from`だけの差はretry intentを変えない。generic `put_node`でRelationAssertionを無構造に保存できない。旧v2 RelationAssertion fixtureはnamed seeding helperでread projection/search比較だけに残し、public writerの互換性やformal save成功を表すテストとしない。fault injectionはnodes、histories、edges、audit、idempotencyを全てsnapshot比較し、rollback後の同key retry成功まで検査。`GraphWritePort`は変更しない。通常上限500行を越える本packetは、負例・rollback試験を削らず一目的・5ファイルを一体でレビューするため、今回のみ650行までの例外を記録する（実差分は約630行）。 | 既知（M0/V-M利用可）、類推可能（memory transaction pattern）、類推可能（5ファイル、今回のみ650行例外） |
| P4-05-HIST | Neo4j Run登録と`FounderGraphHistory`で前Campaign revisionのtyped authorization snapshotをlosslessly保持 | 検査: Run、Campaign更新、Run `HAS_RUN`、typed prior Campaign history、audit、receiptを同transactionでcommit/rollback。legacy `{id,node_type,revision}`はproofに使わずfail closed。historyはlocal-onlyでMCP readへ出さない | 未知（Neo Run writer owner release後） |
| P4-05-BRIEF-N | owner-bound Neo4j `IdeaBriefVersion` lineage store/read with typed serialization | 検査: exact latest lookup、revision/supersedes CAS、idempotent receipt/replay、owner scope、transaction rollbackをM0と同じ契約で検査。MCP egress filterとprivate section内容の扱いは既存policyを維持 | 未知（Neo brief persistence/APIが未実装） |
| P4-05V-N | exact/latest briefに対するNeo4j historical Run gate adapter | 検査: P4-05V-Mと同じ正/負例をtransactionで読み、Run登録とexact `HAS_RUN`、receipt、owner/type、Campaign snapshot historyを照合。post-run expiry/revoke後のvalid accepted briefを保持。証拠欠落時はfail closed | 未知（P4-05-HIST/BRIEF-N後） |
| P4-05N | Neo4j gateway/wrapper transactional RelationAssertion writer + fake-query tests | 検査: duplicate/successor CAS、typed same-owner refs、edges/audit、replay、late rollbackを同transactionで検査。P4-05V-Nを使い、current-time authorization gateは呼ばない。差分500行以内 | 未知（P4-05-HIST/BRIEF-N/V-N/M0/M1後、Neo owner release後） |
| P4-05R | disposable Neo4j rollback/replay gate | 検査: dedicated disposable owner/containerで成功・replay・late fault rollbackとcleanupを確認。通常DB/service不使用 | 未知（P4-05N後） |

P4-05V-Mは既存memory typed Campaign history上のpure policy、P4-05M0は権威あるmemory Brief lineage、P4-05M1はconcrete memory mutation、P4-05-HISTはNeo4j Run登録とCampaign履歴永続化、P4-05-BRIEF-Nは権威あるNeo Brief lineage、P4-05V-NはNeo4j historical resolver、P4-05NはNeo4j RelationAssertion transactionとする。基準mainには`IdeaBriefVersion` value objectはあるが、Brief保存・latest解決APIはなかったため、このpacketでInMemoryGraphWriteService内のconcrete-only save/readを追加した。Shared `GraphWritePort`に`save_relation_assertion`はなく、`RelationType`にも`ASSERTS_FROM`/`ASSERTS_TO`/`EVIDENCED_BY`はない。M1はNeo writerなしのProtocol stubを作らず、memory具体実装に閉じ、canonical structural-edge labels/endpoint pairsもdomain contractとして明記・検査する。共有Protocol追加はNeo adapter parityが用意されたpacketまで延期する。Neo Brief storeも未実装のため、V-NはBriefを捏造せず、BRIEF-N完了後に限り実装可能。

P4-05-HISTはP4-05V-M/M0/M1の先行を妨げないが、P4-05V-N/P4-05N/P4-05RおよびNeo/MCP exposureの必須依存である。P4-05M0はP4-05M1の必須依存。P4-05-BRIEF-NはV-N/Nの必須依存。各packetは単一目的・500行以内。P4-05R前にMCP/runtime writeを有効にせず、P4-05全体完了を主張しない。

P4-05V-M実装APIは`backend/dots/founder_graph_historical_brief.py`の`validate_historical_researched_brief(brief: IdeaBriefVersion, idea: Idea, runs: Sequence[ResearchRun], campaigns: Sequence[ResearchCampaign]) -> None`とし、拒否時は`HistoricalResearchValidationError`を送出する。引数はauthoritative typed historyであり、この純粋関数はDB・clock・write・networkを使わない。8章の非空本文、Brief/Idea ownerとID、重複のないRun参照、Campaign履歴の連続性と一意性、Runのcampaign/snapshot ID/revision、同owner/Idea scope、承認開始・expiry・Brief作成時刻を照合する。現在/最新のBrief IDとIdea chain、正規登録済みRun・`HAS_RUN`・receiptは呼出側/store側が照合する必須事前条件であり、この関数は解決・証明しない。typed Campaign historyはauthoritativeとし、enum/authorization値を外部入力から構築しない。current registryや`validate_researched_brief(..., at=now)`は呼ばない。後日revoke/expiry後も有効な過去proofを受理し、不明・不足・矛盾したproofはfail closedとする。

P4-05M0は`InMemoryGraphWriteService.save_idea_brief(brief, *, expected_latest_revision, idempotency_key, actor)`をmemory concrete-only APIとして追加し、`get_idea_brief(brief_id)`/`get_latest_idea_brief(idea_lineage_root_id)`でowner-bound immutable valuesを返す。Briefはservice内のfrozen typed valuesとして保持する。Save/replay/CAS/latest/Idea chain resolutionは同一lock内。exact replayはreceiptだけ返し、保存後にIdea lineageが変わってもcurrent mutable stateを再検証しない。新しいsaveではBrief rootから一意なIdea leafを辿り、supersedes chainと整数revision連続性を検証し、`based_on_idea_id`をそのimmutable Idea IDへ照合する。非空`research_run_ids`はcaller supplied claimsとして扱わず、各Runがtyped owner-scoped `_nodes`にあり、唯一のmatching `HAS_RUN` edge、matching `record_research_run` receipt/audit、typed Campaign historyにあることを確認してからV-Mを呼ぶ。`created_at`はBrief payloadの入力時刻でありhistorical validatorのRun-finish比較に使うためfingerprint対象とする。同一ID/contentでも時刻を変えた再送はintent conflictとし、save-time server clockは追加しない。`IdeaBriefVersion`の固定tuple/frozen sectionのみ返すため、外部変更でlatest/store状態を壊せない。

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| write contract | memory先行は`InMemoryGraphWriteService`のconcrete methodに限定。Neo adapter実装と同時にGraphWritePort contractを追加する | Protocolだけ先に拡張するとNeo concrete classが未実装 stubを継承し、成功を誤報する危険がある。generic `put_node`/legacy `link_entities`もstructural refsと履歴を保証しない | 将来の共通contractは維持しつつ、未実装adapterへの誤公開を防止 |
| brief authority | M0 owner-scoped in-memory lineage storeをM1のlatest/revision source of truthとする | caller supplied brief IDだけではexact/latestを証明できず、現在mainにはBrief persistence APIがない | brief save/readとrelation saveはreceipt/CASを各境界で検証。Neo exposureはNeo Brief store parityまで不可 |
| structural assertion refs | P4-05M1でdedicated `RelationAssertionEdgeType`とcanonical typed-triple helperを定義し、専用writerだけが使用する。`link_entities`は宣言型と解決済みendpoint型の両方でRelationAssertion間の既存SUPERSEDESを拒否する | `RelationType`へ新3種を追加するとlegacy `Relationship`/`link_entities`からAssertion構造edgeを偽造でき、既存Assertion `SUPERSEDES`を無条件に許すとfamily CASが迂回される。宣言型だけの検査では別型を偽って迂回できる | 他の既存SUPERSEDES endpoint pairは維持し、Neo transaction packetは同じenum label/direction/type invariantを使うが、独立writer parityまで共有APIに出さない |
| research recency | 完了時点のauthoritative authorization snapshot/revision proofを検証する | assertion save時にCampaign currentを再評価すると後日のexpiry/revokeを遡及適用する | historical acceptanceは不変、proofなしはfail closed |
| Campaign history | Memoryの既存typed historyでpure validationを先行し、Neo Run登録ではprior `ResearchCampaign` full typed authorization payloadをlocal-only History recordに保存する | `{id,node_type,revision}` pointer-only履歴ではexpired/revoked後のRunを証明できない。current payloadだけでは過去scopeを復元できない | old sparse historyはproofとして扱わず、Neo history packet後の新writeだけを証明可能にする |
| replay fingerprint | caller intentでfingerprintしserver-generated `valid_from`は除く。exact replayはmutable state validationより先。Brief `created_at`はcaller payloadでRun-finish判定に使うため含める | timestamp差をintent変更にする、またはreplayでedge repairする案 | matching replayは副作用なし。Brief retryは同じID/content/created_atを再送する |
| packetization | pure validation、memory mutation、Neo transaction、実機rollbackを分割する | 一度にMCPまで接続すると500行超かつpersisted writer未検証になる | 依存完了後のみ次packet開始 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | memory typed Campaign historyによるpure validatorをNeo persistenceより先行可能にし、Neo Run/history persistenceを独立gateとして分離。save時validatorの再実行を禁止 | memory node historyは型付き履歴を持つ一方、Neo historyはpointer-onlyで後日expiry/revocation後のRunを証明できないため | P4-05-SP-01、P4-05V-M、P4-05M、P4-05-HIST、P4-05V-N、P4-05N |
| 2026-09-26 | P4-05V-Mを`validate_historical_researched_brief(brief, idea, runs, campaigns)`として実装。完全なtyped Campaign履歴からRunが参照したauthorization snapshotを解決し、Run時点のscope/approval/expiryだけを検証する。呼出側はRunsが正規登録済みであることを保証する | 受理済みBriefのhistorical proofを現在のCampaign状態・save時validatorから分離し、後日revoke/expiryによる遡及失効を防ぐ。履歴不足・重複・曖昧さはfail closed | P4-05V-M |
| 2026-09-26 | P4-05MをM0 Brief lineage storeとM1 concrete memory assertion mutationに分割。Brief保存API・GraphWritePort assertion method・assertion structural edge labelsのmain欠落を明記し、M1がcallerのlatest宣言やProtocol stubへ依存しない契約を追加 | exact/latest briefとatomic formal assertionを安全に検証するmemory source of truthが現時点では存在しないため。Neo adapter parity以前の共有Protocol拡張を防ぐ | P4-05M0、P4-05M1 |
| 2026-09-26 | M0をInMemoryGraphWriteService concrete-only Brief save/exact/latest readとして実装。現Idea lineage/revision、expected-latest CAS、immutable value、Run registration/edge/receipt/audit/Campaign-history proof、audit rollbackをfocused synthetic testsで固定。M1とProtocol/Neo/MCP接続は未着手 | Brief保存APIがmainにないため、後続M1がcaller supplied Brief/latest/Run claimsを信頼しない権威あるmemory sourceを先に用意する | P4-05M0 |
| 2026-09-26 | M1を具体化: receipt-first replay、same-owner active typed refs、Brief/Run historical proof、canonical assertion edges、family/predecessor CAS、successor uniqueness、全memory state rollbackとsynthetic acceptance casesを明記。M0は#265でmain配送済み | formal assertionの意味・証拠・履歴をatomicに固定し、Neo/Protocol未実装のまま弱い入口を作らないため | P4-05M1 |
| 2026-09-26 | M1のgeneric-write境界を明確化し、解決済み実ノードがAssertion同士なら宣言型を偽っても既存`SUPERSEDES`を`link_entities`で作れないことを追加。旧bare Assertion parity nodeはpublic write成功fixtureではなく、明示seedingによるsafe read/search projection fixtureへ変更 | generic node writerとAssertion-family CASの意図しない迂回、および既存互換テストによるformal-write要件の弱体化を防ぐ | P4-05M1 |

## ロールバック / 安全境界

P4-05V-Mはpure policyとsynthetic testsのみを追加し、schema/DB/API/runtimeには変更しない。P4-05M0/M1は後続のmemory-only packetであり、Brief/history/edges/audit/idempotency mutationをaudit失敗時にrollbackする。Neo4j packetは同一transactionに閉じ、実機rollback gate前のMCP公開を禁止する。
