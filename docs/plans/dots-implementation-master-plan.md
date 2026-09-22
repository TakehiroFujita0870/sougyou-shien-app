# Dots 実装全体計画

最終更新: 2026-09-22
実行状態: Q-DM-01確定後にgoal開始可能
製品要件正本: [`founder-graph-pivot.md`](founder-graph-pivot.md)
データモデル正本: [`founder-graph-data-model.md`](founder-graph-data-model.md)

## 要望 / ゴール / 成功指標

要望は、次の指示だけでDotsの初期完成範囲を自律実行できる状態を作ることである。

> Dotsの実装全体計画を完遂するまで自走する。実装はLuna Maxを基幹モデルとし、独立タスクを最大三つ並列実行する。root coordinatorは計画、依存、所有権、検査、PR、判断境界の統制へ集中する。

ゴールは、ChatGPTで生まれたアイデアをローカルDotsへ保存し、DotsとNeo4jを停止・再起動した後も検索でき、本人の資産、人脈、根拠、調査履歴、8章レポートへ接続できる単独利用Founder Graphを完成させることである。

成功指標は、合成データの全gateと実データ投入前のsecurity gateを通過し、代表会話5件、複数ResearchRun、訂正、名寄せ候補、backup / restore、soft delete、Graph UIを同じmain revisionで検証することである。

## ゴールモード開始指示

利用者が次の文を送った場合、root coordinatorは`create_goal`で本計画の完遂をobjectiveに設定し、token budgetは指定しない。

```text
Dotsの実装全体計画（docs/plans/dots-implementation-master-plan.md）を完遂するまでゴールモードで自走してください。
実行モデルはroot coordinatorとworkerの双方で gpt-5.6-luna、reasoning effort max を使用してください。
同時実行枠が4の場合はroot coordinator 1、worker最大3で進め、依存がなく変更ファイルが重ならないready taskを常に優先してください。
root coordinatorは計画、依存関係、変更所有権、受け入れ条件、レビュー、CI、PR、main統合、ユーザー判断境界を管理し、実装と調査はbounded workerへ委譲してください。
会話履歴を正本にせず、本計画、Founder Graphデータモデル正本、GitHub Issue、PR、execution ledgerを正本にしてください。
未決の利用者判断、実外部接続、実データ送信、秘密情報、支出、破壊的移行の境界では対象scopeだけを停止し、他のready taskを続行してください。
各意味単位が完了したらfinish-and-mergeに従い、検査、commit、push、PR、CI、main merge、main smokeまで閉じてください。
全Definition of Doneを満たした場合だけgoalをcompleteにしてください。
```

利用者が「Luna Max 1M」と表現した場合、このリポジトリでは実行指定を`gpt-5.6-luna / max`へ正規化する。1M contextの利用可否を完了条件に含めず、全task packetを短い独立文書として渡す。これによりcontext上限が異なるhostでも同じ計画を実行できる。

## Luna実行プロファイル

本計画のgoalがactiveな期間は、利用者の明示指定として次を適用する。

| 役割 | model | reasoning | 責務 |
| --- | --- | --- | --- |
| root coordinator | `gpt-5.6-luna` | `max` | goal、DAG、WIP、所有権、review、integration、判断境界 |
| implementation worker | `gpt-5.6-luna` | `max` | 一つのtask packetの実装、検査、セルフレビュー |
| research / audit worker | `gpt-5.6-luna` | `max` | 一つのspike、仕様監査、証跡収集 |
| independent reviewer | `gpt-5.6-luna` | `max` | PR差分と受け入れ条件の独立照合 |

Sol、Terra、別providerへのfallbackは行わない。Lunaが利用不能な場合は`model_unavailable`として新規実装を停止し、完了済み成果物のローカル検査と状態記録だけを行う。

Dots製品runtimeのLuna論理キーと、Codex実装agentの`gpt-5.6-luna`指定は別設定として管理する。

## coordinatorの最小context運用

root coordinatorは次だけを常時保持する。

1. active goalと残Definition of Done。
2. phase DAGとready / running / review / blocked / mergedのtask状態。
3. ファイル所有権とWIP。
4. mainの12文字short SHA、open PR、CI状態。
5. 未決decision IDと停止scope。

コード本文の探索、実装、長いtest logの解析はworkerへ渡す。coordinatorはworkerの報告を次の固定形式で受け取る。

```text
TASK: <ID>
RESULT: DONE | CHANGES_REQUIRED | BLOCKED
HEAD: <12-char SHA or none>
FILES: <changed files>
AC: <acceptance criteria result>
TESTS: <command and result>
RISKS: <remaining risk or none>
DECISION: <decision ID or none>
NEXT: <ready dependent task IDs>
```

長いtool outputをhandoffへ貼らず、artifact path、PR URL、失敗行、再現commandを記録する。

## task packet契約

workerへ渡す全task packetは次を含む。

- Task IDと一文objective。
- 先行taskと入力artifact。
- 読む正本file。
- 書込許可fileの列挙。
- 書込禁止file。
- Given / When / Then。
- 実行必須test command。
- 停止条件。
- PR titleとrollback方針。
- model=`gpt-5.6-luna`、thinking=`max`。

書込許可fileが重なるtaskを同時実行しない。`App.jsx`とshared styleは同一workerが同時変更せず、integration taskが順番を決める。

## 並列実行規則

同時実行枠が4の場合、root coordinatorを一枠残し、最大三workerを起動する。

taskを並列化できる条件は次の全てである。

- 全dependencyがmergedまたはread-only artifactとして確定している。
- 書込許可fileが他のrunning taskと重ならない。
- 同じschema、API、UI contractの決定を別workerが同時変更しない。
- task単独で検査できる。
- user decision待ちscopeではない。

ready taskが一件の場合は一workerだけを使う。依存を無視して三workerを埋めることは禁止する。

## 状態管理

- 製品要件: `founder-graph-pivot.md`。
- schema: `founder-graph-data-model.md`。
- 実行DAGとDoD: 本書。
- turn横断状態: `docs/operations/dots-execution-ledger.md`。
- 作業割当と判断: GitHub Issue。
- 実装差分とreview: PR。
- 完了済み正本: main。

execution ledgerはtask ID、status、owner task、branch、PR、head SHA、test、blocked decision、updated_atだけを持つ。会話要約を進捗正本にしない。

## 現在地

### 完了済み

- Founder Graph domain contract、in-memory read/write、Neo4j adapter、MCP read/write、stdio transport。
- Source、Campaign、Run、ReportVersion、Evidence、Claimの基礎validator。
- contact CSV normalizer、instruction scanner、Luna論理model catalog、enrichment proposal contract。
- safe export、report diff、campaign compare、Graph read-only UI。
- Docker Compose、schema migration、manifest、backup / restore helperのnetwork-free検査。
- Windows Docker Desktop Engine応答。
- finish-and-merge Skill、main保護、CI必須、Auto-merge。

### 未完了

- schema v2のstable anchor、immutable revision、RelationAssertion、ContentChunk。
- UbuntuからDocker Desktop Engineを使う経路。
- 実Neo4jでのmigration、write、read、restart、restore。
- FastAPI / stdioの既定runtimeをNeo4jへ切り替えるgate。
- ChatGPT Secure MCP Tunnelのtool discoveryと代表会話。
- Graph全体検索からResearchBriefを作り、許諾後にDeep Researchへ渡す実経路。
- Deep Research完了後のRun、Evidence、ReportVersion write-back。
- Graph UIの実backend接続、訂正、削除impact、実file export。
- private full archive、restore、soft delete propagation。
- 実データ投入前security reviewと既存データ移行判断。

## phase DAG

```text
P0 Control Plane
  -> P1 Schema v2
      -> P2 Neo4j Real Runtime
          -> P3 Local Capture/Search
              -> P4 Assets/People
              -> P5 ChatGPT Synthetic Connection
                  -> P6 Research/Report Write-back
          -> P7 Live UI
      -> P8 Backup/Delete/Export
P3 + P4 + P5 + P6 + P7 + P8
  -> P9 Real-data Readiness and Legacy Disposition
      -> COMPLETE
```

P4とP7はP3完了後に並列実行できる。P5はP3と外部接続decision後に開始する。P8はP2完了後に開始できる。P9は全gate完了後に開始する。

## ユーザーストーリーと受け入れ条件

### US-MP-01 会話から永続保存する

As a 単独利用者, I want ChatGPTで話したアイデアをDotsへ保存したい, so that 再起動後も再利用できる。

Given: schema v2のNeo4j、MCP write、合成会話が起動している

When: capture_ideaを実行し、DotsとNeo4jを停止して同じvolumeで再起動する

Then: 同じIdea anchor、SourceRevision、EntityRevision、provenanceをsearchとfetchで取得できる。

### US-MP-02 資産と人脈を照合する

As a 単独利用者, I want 新しいIdeaを知識、経験、人物、組織へ照合したい, so that 誰と何を検証するか決められる。

Given: Asset、Person、Organization、RelationAssertionが保存されている

When: IdeaについてGraph RAG検索する

Then: 上位結果は根拠path、confidence、status、有効期限を持ち、proposed関係をconfirmedとして表示しない。

### US-MP-03 許諾後に複数調査する

As a 単独利用者, I want 調査目的を一度許諾して複数回試したい, so that 結論を比較できる。

Given: 目的、範囲、外部送信field、試行予算を確定したCampaignがある

When: ChatGPTが二つのResearchRunを実行してwrite-backする

Then: Run、input snapshot、Evidence、ReportVersionは別IDで保存され、旧版を変更せず比較できる。

### US-MP-04 訂正と削除を追跡する

As a 単独利用者, I want 誤りを訂正し不要な情報を削除したい, so that 現在の検索と過去判断を区別できる。

Given: Sourceを参照するClaimとReportVersionがある

When: Sourceをsoft deleteする

Then: 現在検索から除外され、過去ReportVersionにはunavailable、hash、削除時刻が表示される。

### US-MP-05 Lunaで再現可能に実装する

As a 製品責任者, I want Luna workerだけで計画を進行したい, so that 高価な基幹agentへ依存せず反復できる。

Given: 一つのtask packetがreadyである

When: Luna workerが実装、test、セルフレビューを完了する

Then: task packetの全AC、test、file ownership、handoff fieldが満たされ、coordinatorが元コード全文を読み直さずreview判断できる。

## 実装task

### P0 Control Plane

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P0-01 | なし | 本計画とdata modelをAGENTS / HANDOFFから正本化 | 検査: 正本link、model override、finish-and-merge routeが各一件存在する | 既知 |
| P0-02 | P0-01 | execution ledgerとtask packet template | 検査: task、PR、SHA、test、decisionを一行で追跡できる | 既知 |
| P0-03 | P0-01 | Founder Graph用GitHub IssueをDAG taskへ整合 | 検査: pre-pivot Issueをcurrent taskへ誤割当せず、ready taskにownerとdependencyがある | 類推可能 |

### P1 Schema v2

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P1-SP-01 | Q-DM-01 | schema v1→v2 fixture変換spike | 検査: 欠落field、重複anchor、孤立edge、rollback結果を出力する | 未知 |
| P1-01 | P1-SP-01 | stable anchor / EntityRevision domain contract | 検査: anchor ID維持、current pointer一意、revision不変testが成功する | 類推可能 |
| P1-02 | P1-SP-01 | RelationAssertion / Facet / ContentChunk contract | 検査: predicate、根拠、期限、chunk locatorのallowlist testが成功する | 類推可能 |
| P1-03 | P1-01,P1-02 | Neo4j migration v2とrollback | 検査: 実Neo4jの空DBとv1 fixtureの双方でmigration / rollbackが成功する | 類推可能 |
| P1-04 | P1-03 | v2 read/write parity | 検査: in-memoryとNeo4jで同じmanifestと代表query結果になる | 類推可能 |

### P2 Neo4j Real Runtime

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P2-SP-01 | P1-03 | Ubuntu→Docker Desktop接続spike | 検査: Ubuntuでclient/server versionとCompose healthを取得する | 未知 |
| P2-01 | P2-SP-01 | secret、volume、health、shutdownを持つlocal runtime | 検査: secretがGit/logへ残らずNeo4j healthがhealthyになる | 類推可能 |
| P2-02 | P1-04,P2-01 | schema migrationとfixture load | 検査: schema version、constraint、node/assertion countがmanifestと一致する | 類推可能 |
| P2-03 | P2-02 | restart persistence gate | 検査: 停止前後のmanifest、代表10問、revision pointer hashが一致する | 類推可能 |
| P2-04 | P2-03 | local composition既定をNeo4jへ切替 | 検査: 起動時Neo4j、停止時503、公開fallbackなし、rollback flagが成功する | 類推可能 |

### P3 Local Capture / Search

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P3-01 | P2-04 | capture_ideaのSource→Idea transaction | 検査: 冪等再送でanchor一件、Source原文一件、revision一件になる | 類推可能 |
| P3-02 | P2-04 | Graph RAG full-text + 2-hop candidate取得 | 検査: 代表10問で期待anchor top-10命中9件以上、private越境0件になる | 類推可能 |
| P3-SP-03 | P3-02 | Luna rerank評価 | 検査: 固定20問でtop-5命中16件以上、invalid ID 0件、p95 30秒以下を記録する | 未知 |
| P3-03 | P3-SP-03 | search / fetch MCPのsafe projection | 検査: local_only field 0件、pathとEvidence ID欠落0件になる | 類推可能 |

### P4 Assets / People

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P4-01 | P3-01 | OwnerProfile、InstructionArtifact、Asset取込 | 検査: hash差分だけが新revisionとなり秘密文字列が保存されない | 類推可能 |
| P4-02 | P3-01 | Person / Organization手入力とCSV取込 | 検査: 合成名刺10件でfield loss 0件、private投影0件になる | 類推可能 |
| P4-SP-03 | P4-02 | Luna名寄せ候補評価 | 検査: top-3再現率0.90以上、誤自動merge 0件を記録する | 未知 |
| P4-03 | P4-SP-03 | merge確認とRelationAssertion UI/API | 検査: 本人確認なしのconfirmed / MERGED_INTOが0件になる | 類推可能 |

### P5 ChatGPT Synthetic Connection

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P5-SP-01 | D-EXT-01,P3-03 | Secure MCP Tunnel tool discovery | 検査: 合成データだけでsearch、fetch、capture_ideaのtool discoveryを記録する | 未知 |
| P5-01 | P5-SP-01 | 代表会話5件の検知→保存→preflight | 検査: 保存ID、idempotency hash、検索件数、調査未開始を各会話で記録する | 類推可能 |
| P5-02 | P5-01 | ChatGPT接続runbookとredacted evidence | 検査: credential、会話原文、個人連絡先がartifactに0件になる | 類推可能 |

### P6 Research / Report Write-back

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P6-01 | P5-01 | Dots全体検索→ResearchBrief→許諾preflight | 検査: 目的、範囲、field category、試行予算、期限がsnapshot化される | 類推可能 |
| P6-SP-02 | P6-01 | Deep Research一回とwrite-back spike | 検査: 一Campaign、一Run、一ReportVersion、通知時刻、write receiptを記録する | 未知 |
| P6-02 | P6-SP-02 | 二回調査と追加質問のRun分類 | 検査: 方針変更は新Run、再構成は新ReportVersion、transport retryは同Runになる | 類推可能 |
| P6-03 | P6-02 | 固定8章生成、差分、訂正 | 検査: 8章、Claim区分、Evidence、撤退line、roadmapが旧版不変で保存される | 類推可能 |

### P7 Live UI

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P7-01 | P3-03 | Graph UIをlive read APIへ接続 | 検査: empty、loading、unavailable、retry、data表示のcomponent/E2Eが成功する | 類推可能 |
| P7-02 | P4-03 | Person、Asset、RelationAssertion確認UI | 検査: proposed確認、reject、merge preview、keyboard操作が成功する | 類推可能 |
| P7-03 | P6-03 | ReportVersion、Run比較、訂正UI | 検査: 8章差分、根拠、旧版、unavailable参照を表示する | 類推可能 |

### P8 Backup / Delete / Export

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P8-SP-01 | D-BACKUP-01,P2-03 | 世代付きprivate archive / isolated restore spike | 検査: Neo4j、Attachment、manifestを同generationで復元しhash一致を確認する | 未知 |
| P8-01 | P8-SP-01 | backup / restore commandとUI状態 | 検査: success、partial、failed、保持artifactを表示し元volumeを変更しない | 類推可能 |
| P8-02 | D-DELETE-01,P8-01 | soft delete impact previewとpropagation | 検査: search除外、Report unavailable、export除外、audit保持が一致する | 類推可能 |
| P8-03 | P6-03,P8-01 | safe JSON / Markdown / DOCX / PDF export | 検査: 選択scopeだけを出力しprivate field 0件、8章欠落0件になる | 類推可能 |

### P9 Real-data Readiness / Legacy Disposition

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P9-01 | P3,P4,P5,P6,P7,P8 | security / privacy / recovery review | 検査: threat model、egress、secret、restore、deleteのP0/P1未解決が0件になる | 類推可能 |
| P9-SP-02 | P9-01 | 既存Postgres / localStorage実inventory | 検査: owner別count、hash、legacy mapping、変換失敗一覧を作る | 未知 |
| P9-02 | D-LEGACY-01,P9-SP-02 | 変換またはread-only archive | 検査: 変換countまたはarchive count、rollback、旧版参照を照合する | 類推可能 |
| P9-03 | D-REAL-01,P9-01,P9-02 | 実データcanary投入 | 検査: 一Idea、一Person、一Sourceで保存、再起動、検索、backup、delete rehearsalが成功する | 類推可能 |
| P9-04 | P9-03 | 初期完成監査 | 検査: 本書の全DoD、CI、main smoke、runbook、known limitationを照合する | 既知 |

表の`P3`、`P4`、`P5`、`P6`、`P7`、`P8`は各phase内の全task完了を表す。

## 質問リスト / 利用者判断boundary

| ID | 判断 | 推奨既定 | 停止scope | 期限 |
| --- | --- | --- | --- | --- |
| Q-DM-01 | schema v2を採用するか | stable anchor + immutable revision + RelationAssertionを採用 | P1以降 | P1-SP-01前 |
| D-EXT-01 | ChatGPTへSecure MCP Tunnelを初回登録するか | 合成データだけで許可 | P5以降 | P5-SP-01前 |
| D-BACKUP-01 | private archive保護とartifact構成 | アプリ層暗号化、同generationの別artifact | P8-SP-01以降 | P8-SP-01前 |
| D-DELETE-01 | Source delete後の過去Report | Reportを残しunavailable表示 | P8-02以降 | P8-02前 |
| D-LEGACY-01 | 旧データの扱い | 実データが少ない間はJSON export + read-only archive | P9-02だけ | P9-SP-02後 |
| D-REAL-01 | 実会話、名刺、個人資料を初投入するか | 合成gateとsecurity review後に一件canary | P9-03以降 | P9-03前 |

判断待ちは該当scopeだけを止める。別phaseのready taskを停止しない。

## PRとintegration

- 一PRは一taskまたは同じ受け入れ条件を成立させる縦切りtask群に限定する。
- 500行を超える場合、生成物、fixture、schema、adapter、UIを分離できるか先に確認する。
- PR head更新ごとにCIとreviewを再実行する。
- required `quality`成功前にmergeしない。
- merge後はmain smokeとdependent task deliveryを同じturnで閉じる。
- schema migration PRはforward、rollback、既存data影響を記載する。
- 実機証跡は秘密値、個人情報、会話原文を含めない。

## 失敗時の再計画

同じtaskがimplementation loopを三回失敗した場合、worker追加で押し切らずplanningへ戻す。

再計画では次を記録する。

- 失敗したACと最小再現command。
- contract不備、実装不備、環境不備、未知の分類。
- 既存commitとdataを壊さないrollback。
- spikeへ戻すtask ID。
- dependent taskのHOLD範囲。

同じblocking conditionが三goal turn続き、利用者入力または外部状態変化なしでは進めない場合だけgoalをblockedへ更新する。

## スコープ外

- 複数利用者、共同編集、組織権限。
- 課金、Free / Standard / Pro。
- Dots独自のDeep Research schedulerと通知基盤。
- public MCP endpointとcloud常時稼働DB。
- 初期完成条件としてのlocal LLM。
- 未評価embedding providerの追加。
- 自動physical delete、自動名寄せ確定、任意Cypher。
- 法務、税務、投資、融資、特許性の確定判断。

## Definition of Done

本計画は次の全条件を満たした場合だけ完了とする。

- [ ] schema v2のidentity、revision、RelationAssertion、Source、Chunk契約がmainにある。
- [ ] 実Neo4jでmigration、write、read、停止、再起動、restoreが成功している。
- [ ] ChatGPT代表会話5件が合成データでIdea保存と再検索に成功している。
- [ ] Dots全体検索とResearchBriefがprivate fieldを外部へ出さない。
- [ ] 許諾済みCampaignで複数Runと8章ReportVersionを保存・比較できる。
- [ ] Person、Organization、Asset、名寄せ候補、RelationAssertionを確認できる。
- [ ] Graph UIがlive data、訂正、履歴、unavailable、report差分を表示できる。
- [ ] backup、isolated restore、soft delete、safe exportが同じfixtureで成功している。
- [ ] 実データcanary一件が保存、再起動、検索、backup、delete rehearsalを通過している。
- [ ] 全required CIが成功し、main smokeが成功している。
- [ ] setup、起動、停止、復旧、ChatGPT接続runbookが最新である。
- [ ] P0/P1 security、data loss、owner越境issueが0件である。

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-MP-01 execution model | goal期間はrootとworkerを`gpt-5.6-luna / max`へ統一する。利用者が基幹モデルとして指定したため | Sol / Terra混在はモデル差によるhandoff再解釈を増やすため却下 | goal固有override |
| ADR-MP-02 concurrency | root一枠と独立worker最大三枠にする。現在の四枠で統制と実装を両立するため | rootを含む全枠を実装へ使う案はreviewとownership管理が消えるため却下 | ready taskだけ並列化 |
| ADR-MP-03 context | task packetとartifactを正本にし、1M contextへ依存しない | 全履歴を各workerへ渡す案はtoken消費と古い指示混入を増やすため却下 | 短いhandoffを必須化 |
| ADR-MP-04 schema gate | schema v2と実機永続化gate通過後にNeo4jを既定化する | schema v1のまま既定化する案はidentityとrelation履歴が未確定のため却下 | P2-04で切替 |
| ADR-MP-05 external rollout | 合成接続、security review、一件canaryの順にする | 最初から実会話と名刺を送る案は漏えい時の影響が大きいため却下 | D-EXT-01とD-REAL-01を分離 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響task |
| --- | --- | --- | --- |
| 2026-09-22 | 初版。schema v2、Neo4j実機、ChatGPT接続、Research、UI、backup、実データcanaryまでのDAGを定義 | Luna Max主体のゴールモードで実装全体を完遂できる正本が必要なため | P0-01〜P9-04 |
