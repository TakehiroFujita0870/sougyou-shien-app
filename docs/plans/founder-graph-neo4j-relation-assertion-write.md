# Neo4j RelationAssertion 書込み計画
最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: memoryで確定した正式関係の保存契約を、Neo4jでも一貫した履歴・根拠・再送境界で実装する。
ゴール: 型付き端点、accepted Brief、Evidence、訂正履歴、監査、冪等receiptを一つのNeo4j transactionで保存する内部writerを用意する。
成功指標: memory writerと同じ合成入力に対して同じaccept/reject・revision・canonical edgeを得る。fake transactionで副作用なしの拒否とrollbackを検査し、別の隔離実DB gate完了まではMCP/runtimeへ公開しない。

## ユーザーストーリーと受け入れ条件

### US-NRA-01 型付き根拠付き関係を保存
As a local Founder Graph owner, I want a formal relation tied to current owner-owned records and cited evidence, so that its meaning and provenance remain verifiable.
Given: owner内current endpointとactive Evidenceがあり、Idea endpointがある場合はlatest accepted BriefとResearchRun/Campaign historyが整合する。
When: concrete Neo4j writerがassertionを保存する。
Then: endpoint kind/owner/currentness、Briefとsection、Evidence所属、Run登録・historical authorizationを同一transaction内の権威ある記録から検証し、RelationAssertion、canonical edges、audit、receiptを一度だけcommitする。不明・foreign・不整合は全状態を変えず拒否する。

### US-NRA-02 訂正と再送を安全に扱う
As a local owner, I want retries and corrections to preserve one unambiguous assertion history, so that retries do not repair or fork mutable graph state.
Given: 同一commandの再送、変更intentのkey再利用、同一predecessorへの競合訂正、または訂正後の再送がある。
When: writerが処理する。
Then: receipt/fingerprintをmutable-state検査前に照合し、完全一致はread-only replay、異なるintentはconflictとする。同family訂正はrevision+1、endpoint/predicate変更は新family revision 1とし、predecessorを一度だけsupersedeする。失敗transactionはnode/edges/audit/receipt/historyを残さない。

### US-NRA-03 Campaign変更と関係保存を直列化
As a local owner, I want the relation write to observe an accepted Brief and its complete authorization proof atomically, so that concurrent Brief or Campaign changes cannot invalidate the evidence between check and save.
Given: Brief lineageまたは参照RunのCampaignが同時に改訂される。
When: Idea関係を保存する。
Then: T-IBP-02の同一transaction対応proof resolverと共有owner-root/current-Idea-leaf/sorted-Campaign lock順を用い、locked stateを再読込してから検証する。後日のexpiry/revokeを理由にaccepted Briefを現在時刻で再判定しない。

### US-NRA-04 実Neo4jで関係の原子性と競合を確かめる
As a local Founder Graph owner, I want the formal relation writer tested against an isolated Neo4j instance, so that its rollback and concurrency guarantees are not inferred from a fake driver.
Given: 専用opt-in、固定済みNeo4j image、UUID所有の一時資源、合成Claim/Evidence fixtureが使われる。
When: 実Neo4jで新規保存、同key再送、訂正、初回同一家族の競合、監査失敗後の再試行を行う。
Then: 正常系はassertion/構造edge/audit/receiptが一件ずつで、再送は副作用なし、訂正は直前revisionを置換、競合は一方だけ成功し、監査失敗は全変更をrollbackし同key retry成功、最後に当該UUID資源だけを削除して残存0を確認する。

## 質問リスト
| ID | 質問 | 決定者 | 期限 |
|---|---|---|---|
| NRA-Q1 | T-IBP-02のtransaction内accepted-Brief proof seamと戻り値。現提案: `founder_graph_neo4j_idea.py`内のprivate `_validate_latest_researched_brief_tx(tx, *, primary_idea_id, owner_id, brief_id, section_index, evidence_ids, locked_ideas, at=None) -> AcceptedIdeaBriefProof`。型・名前は未合意 | Neo4j Brief owner + root | writer着手前 |
| NRA-Q2 | なし。rootはfamily lock labelのschema v4 composite unique制約を承認済み | — | 2026-09-26 |

## スコープ外
- `GraphWritePort`、MCP/API/stdio、runtime登録、画面、外部調査、実利用者/個人データ。
- RelationAssertionやBriefの新しいdomain fields、Brief decoder/store実装。Brief proofはT-IBP-02の内部契約を再利用する。
- legacy Relationship移行、既存不正データの自動補正、通常DBへのmigration/write、performance benchmark。
- 別packetの隔離Neo4j gate承認前のMCP/runtime exposure。
- RelationAssertionの意味検索、Evidenceのread projection、ChatGPT/MCP経由の通し試験。これらはP4-06/P5-03側で別々に検証し、このwriter gateを検索実証とはみなさない。

## 実装前提と不変条件
- #268 mainのmemory `save_relation_assertion`を意味契約とする。`put_node`や`link_entities`へRelationAssertion保存を迂回させない。
- `RelationAssertion -ASSERTS_FROM-> source`、`RelationAssertion -ASSERTS_TO-> target`、`RelationAssertion -EVIDENCED_BY-> Evidence`、訂正時`successor -SUPERSEDES-> predecessor`だけをcanonical structural edgeとする。通常の`RelationType`からassertion scaffoldを生成させない。
- 受理済みIdeaBriefのlatest lineage、exact current Idea、section Evidence、Run/HAS_RUN/receipt/audit、typed full Campaign historyを同じwriter transactionに結ぶ。latest Briefを別sessionで先読みしてから保存するcheck-then-writeは禁止。T-IBP-02からの提案は既存`tx`を受け取るprivate helperと、raw text/Campaign payloadを含まないtyped `AcceptedIdeaBriefProof`だが、これは未実装・未合意である。T-NRA-01で合意されない場合は実装を止める。
- RelationAssertionはIdeaを両端に持てる。両Ideaがある場合もBrief参照はmemory規則どおりsource Idea（sourceがIdeaでなければtarget Idea）1つを証明し、両方のcurrentnessを別々に検証する。T-IBP-02 owner提案はunique Idea rootsをID順、current leavesをID順、Campaign IDsをID順でlockし、private proof helperはlockを取り直さない。提案helperは`primary_idea_id`、`locked_ideas`を受ける。T-NRA-01で他endpoint/family lockとの全体順序を確定し、root/B合意後にシンボルを凍結する。
- Neo更新経路監査で、既存Source/Campaign更新、Run登録、Source captureは親node lockを使う一方、generic `put_node`の新しい`supersedes_id`付きnodeは親をlockしないことを確認した。現`capture_idea`もIdea successor用root/predecessor lockがなく、T-IBP-02 ownerが全Idea successor経路へ同契約を追加すると回答した。RelationAssertion writerがcurrentnessを要求する他のmutable endpointは、その全successor/状態変更writerが同じ親lockを取ることをT-NRA-01で確定する。共有lockのないkindはT-NRA-02/03でfail closedし、並行安全を推測しない。
- Idempotency receiptは最初に確認し、lock待ち後に同key receiptを再確認する。Idea root/leaf、non-Idea endpoint/predecessor、Campaign history、family初回挿入の全lock/collision方式を一つの順序にまとめる。#270 schema v3にはfamily anchorもcomposite constraintもない。root approved: schema v4にinternal `FounderGraphAssertionFamilyLock` labelの`(owner_id,family_key)` unique constraintを追加する。`family_key`は`json.dumps([owner_id,assertion_family_id],ensure_ascii=False,separators=(",",":"))`のUTF-8 bytesをSHA-256したopaque valueとする。ロックnodeはfamilyごとに保持し、検索・NodeType・read projectionに出さない。v4 rollbackはconstraintだけ外しnodeは削除しない。これは計画/オフラインquery検査のみで、通常DBへmigrationを適用しない。live環境v4/v5 cutover対応は別packetで行う。
- Replayはoriginal receiptだけを返し、endpoint、Brief、Evidence、successorのmutable state検査やedge修復をしない。command fingerprintは全caller intentとexpected family revisionを含み、server-generated `valid_from`のみを除外する。
- Idea endpointがあるときは`based_on_brief_id`とsection indexの両方を要求し、exact latest accepted Brief、same Idea、run history、非空section、Evidence subsetを検証する。Idea endpointなしでBrief参照を主張する入力は拒否する。Evidenceはowner内active typed recordに限る。
- New assertion、canonical edges、supersession、audit、idempotency receiptは同一transactionに含める。predecessorが既にsuccessorを持つ場合はstatusにかかわらず拒否する。初回/new familyはrevision 1、同family correctionはexpected family revision+1、changed endpoint/predicate correctionは新family revision 1とする。
- 実DBのrollback、競合直列化、既存schema制約との適合はfake testだけで証明したことにしない。専用disposable gateは個別計画・review・実行許可を要する。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-NRA-01 スパイク | T-IBP-02のaccepted-Brief proof seam、全mutation route lock参加、二Idea endpoint、family uniquenessをread-onlyで照合しshared lock契約を凍結 | 検査: B/root合意済みhelper signature/tx境界、unique roots/leaves/Campaign順、Idea successor全route、Source/Campaign/Run/non-Idea supersedes route、Evidence不変性、first-family lock/constraintをmatrix化して計画追記。lock不参加kindはfail-closed listへ入れる。共通lockやDB制約を証明できない場合はFAILとして実装停止 | 未知 |
| T-NRA-02 | `founder_graph_schema.py`のschema v4 internal family-lock label/composite unique constraintとoffline tests | 検査: `test_founder_graph_schema.py`でv3→v4 create/rollback query、search/NodeType/read projection非露出、rollbackがconstraintのみ削除、exact unique properties `(owner_id,family_key)`を検査。既存`test_founder_graph_neo4j.py`、`test_founder_graph_neo4j_idea_brief.py`のdefault-version/rollback数を更新し、v3固有assertionsは保持。変更量上限500行。通常DB migrationは実行しない | 類推可能（root approved） |
| T-NRA-03 | Neo4j generic createでmutable endpoint predecessorをlockし、successor/currentness checkとcreateをtransaction化する小packet | 検査: `put_node`のsupersedes successor競合winner/loser、foreign/wrong-type predecessor拒否、retry receipt、audit fault rollback。T-IBP-02 ownerがIdea/capture_idea経路を別実装で同じroot-lock契約へ参加させる。`uv run pytest backend/tests/test_founder_graph_neo4j_relation_assertion.py -q`、`git diff --check`。変更量上限500行 | 類推可能（T-NRA-01/02後。未協調routeのkindはunsupported） |
| T-NRA-04 | concrete-only non-Idea assertion writerとfake transaction tests。未対応kind/lock pathはfail closed、port/runtime未公開 | 検査: lock対応endpoint/Evidenceのowner/type/currentness、initial familyはv4 lock anchor、receipt-first replay/changed fingerprint、family CAS・successor一意性、全canonical edge、audit-fault rollbackと同key retryを検査。`uv run pytest backend/tests/test_founder_graph_neo4j_relation_assertion.py backend/tests/test_founder_graph_write.py -q`、`git diff --check`。変更量上限500行 | 類推可能（T-NRA-01〜03後） |
| T-NRA-05 | Idea endpoint経路を凍結済みT-IBP-02 private proof seamへ接続するNeo writer拡張と専用tests | 検査: 0/1/2 Idea endpoint、両Idea currentness、memory規則のprimary Idea Brief、exact latest/section Evidence subset、Run/HAS_RUN/receipt/audit/full Campaign historical proof、後日revoke後のaccepted Brief維持、proof不在時fail-closed、同一tx/lock順をfakeで検査。変更量上限500行 | 未知（T-IBP-02/T-NRA-04 merge後） |
| T-NRA-06 スパイク（設計済） | #266由来の`neo4j_disposable_harness.py`を専用opt-in gateへ再利用する安全設計 | 検査: 固定image `neo4j:5.26-community` をinspectし、`--pull=never`で作成、BoltをIPv4 loopbackだけにbind、image宣言volumeごとに専用UUID名volumeを作成、専用bridge、役割ラベルとrun UUIDで所有確認後のみcleanup、container/volume/network各inventory残存0を確認。通常DB/serviceへ接続せず、Docker起動はテスト実行時だけ。既存helperのrole/nameを引数化しrelation assertion専用値を使う。外向きネットワーク要求なし・合成fixture限定。pytest opt-in既定OFF。 | 既知（コード/既存計画照合済） |
| T-NRA-07（topic branch実機検査済、main未反映） | 独立review後のopt-in隔離Neo4j writer acceptance test | 検査: schema v4 migration後に合成Claim/Evidence endpointで初回保存、同key replayのsnapshot不変、同family successor訂正、barrier同期した同family revision-1競合でwinner一件/conflict一件、deterministic audit ID衝突を使うlate audit constraint failureでassertion/edges/audit/receiptのrollbackと同key retry成功を実Neo4jで確認。各段階でowner-scoped assertion history、canonical structural edges、audit、receiptの状態をsnapshot比較し、UUID exact container/volume/network residue 0。`DOTS_NEO4J_RELATION_ASSERTION_REAL=1 uv run pytest backend/tests/test_founder_graph_neo4j_relation_assertion_real.py -q --tb=short`: 1 passed。通常suiteではopt-inなしでDockerに触れず、backend全体840 passed / 5 skipped / 7 warnings。合成専用資源はcleanup後に残存0、稼働中の通常・合成DBは維持。 | 既知（隔離実機gateはtopic branch上で成功。main配送とChatGPT/MCPの検索・再起動試験は別途） |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| Brief authority | T-IBP-02のsame-tx trusted proofとshared lock contractを再利用する | transaction外の`get_latest`結果やcurrent Campaignだけで受理すると、並行更新と後日revokeでproofが変わる | seamが同一txでなければ実装開始不可 |
| Initial-family serialization | root approved: internal `FounderGraphAssertionFamilyLock` nodeをfamilyごとに残し、schema v4 composite UNIQUE `(owner_id,family_key)`の下で`MERGE`後、temporary lock propertyを同一transactionでset/removeする | 存在しないfamily nodeをlock済みと扱う方法、またはconstraintなし`MERGE`は並列first-insertで二anchorを許し得る。owner全体lockは他のrelation familyを不必要に直列化する | family keyは`SHA256(UTF8(compact JSON [owner_id,assertion_family_id]))`。新labelは`NodeType`/search/read/APIに含めず、rollbackはconstraintのみ。schema変更はoffline testsのみ。live v4/v5 migrationは別cutover packet |
| writer surface | まずNeo4j concrete gateway methodに閉じる | `GraphWritePort`/MCPを先に広げると別adapterで未実装能力を公開し得る | memory/Neo4j parityと実DB gateの後に別計画で公開可否を決める |
| real-test resource identity | disposable helperへrole、name prefix、opt-in variableを呼出側から渡し、`neo4j-relation-assertion` / `dots-relassert-*` / `DOTS_NEO4J_RELATION_ASSERTION_REAL`で明示する | revision-lock専用label/nameを流用するとcleanup inventoryと実行ログの役割が誤認される | Docker lifecycle自体は共通helperの固定image、loopback、exact label/UUID cleanup規則を維持する |
| writer gate scope | 実保存・再送・訂正・同一家族競合・rollback/retryまで。read/searchを含めない | writer gateに意味検索やMCP経路を混ぜると、失敗箇所の切り分けと完了主張が曖昧になる | 検索/再起動後readはP4-06/P5-03へ明示handoffする |
| replay | receipt-first・副作用なし | replay時にcurrent stateを再検査またはedge repairすると、過去成功のretryが後日の変更で失敗・変異する | fingerprint matchはoriginal receiptのみ返す |
| concurrency | T-IBP-02と同一のlock orderに統合 | writerごとの別lock順はBrief/Campaign更新とのTOCTOUとdeadlockを生む | locksとCASを一transactionで適用し、実競合gateを別に設ける |
| scope | fake transaction実装と隔離実DB証明を別タスクにする | fake query testだけでNeo4j rollback/locking実証済みとする案は不正確 | runtime exposureは隔離gate完了まで禁止 |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-09-26 | #270後の新規計画。memory #268を基準にNeo formal assertion writerをBrief T02から分離し、shared proof/lock seamを先行未知依存に設定。T-IBP-02 ownerからprivate tx helperとtyped proofの案を受領したが未合意として記録 | Neo writerがBrief latest/Campaign proofをtransaction外で読むことを防ぎ、decoder重複と早期runtime露出を避ける | T-NRA-01〜05 |
| 2026-09-26 | Route auditでgeneric superseding createにpredecessor lockがなく、Idea successor routesも未調整と確認。BはIdea全経路のroot lock参加を担当。rootはschema v4 family lock constraint案を承認し、schema-only T-NRA-02を開始 | two-Idea endpoint、mutable non-Idea currentness、family初回insertのTOCTOUを避ける。通常DB v4/v5 cutoverはこの承認に含まれない | T-NRA-01〜07 |
| 2026-09-26 | T-NRA-02を実装。schema v4にinternal family-lock compound uniquenessを追加し、offline migration/rollback testsとdefault-version期待を更新。追加testは先に現schema v3で失敗を確認。最新main更新後のfocused schema/Neo gateway/Brief migration tests 44 passed、full backend 733 passed/4 skipped/7 warnings。`migrate_schema.py --validate-only`: version 4、59 planned queries、16 rollback queries | first-family insertが存在しないnodeのlockに依存しないよう、後続writer用のDB uniqueness prerequisiteを確立する。migrationは通常DBに適用していない | T-NRA-02 |
| 2026-09-26 | T-NRA-06をread-only完了。#266 helperは固定image、no-pull、IPv4 loopback、専用volume/network、exact UUID label cleanupと残存検査を備える。現helperはrevision-lockのrole/name/opt-inを固定しているため、引数化しRelationAssertion専用識別子を付けて再利用する。T-NRA-07を実機で行うが、この変更中はDockerを起動せず、通常runではopt-in testをskipする | writer fake testsだけではNeo4j unique constraint競合、実transaction rollbackを証明できない一方、既存Docker安全境界は再利用可能であるため | T-NRA-06、T-NRA-07 |
| 2026-09-27 | 独立レビュー後、使い捨てNeo4jでT-NRA-07を実行。初回保存、同key replay、訂正、family lockを実際に待つ同時書込み、audit constraint failureの全rollbackと同key retryが合格。cleanup後のrole-labeled container/volume/networkは0件。初回実行で見つけた試験側のsnapshot列参照誤りとTaggedSessionのclose不足を修正し、focused 56 passed/1 skipped、実Neo4j gate 1 passed、topic branch全backend 840 passed/5 skipped/7 warnings。main `60b8731857ac`の別クリーンcheckoutでもbackend 837 passed/4 skipped/7 warningsを確認。全試験は通常DB/service不使用。 | fakeだけでは証明できないNeo4jの実lock/rollbackを実機で確認しつつ、誤ったcleanupやセッションリークを避けるため | T-NRA-07 |
