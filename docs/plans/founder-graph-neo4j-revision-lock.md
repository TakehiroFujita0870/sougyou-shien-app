# Neo4j Source / ResearchCampaign 同時改訂の直列化計画

最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: Neo4jの既存 `put_node` 経路で、SourceまたはResearchCampaignの同じ保存済み改訂を同時に更新した場合、古い `expected_revision` を使う更新が後勝ちで履歴・現在状態を上書きしないようにする。

ゴール: 既存IDのowner-local Source / ResearchCampaignを更新する場合、idempotency replay判定の後、対象ノードのowner-scoped write lock取得を更新対象の現行revision/history/reference検証より先に行い、ロック保持中に現行値を再読込して `expected_revision` を比較する。

成功指標: 公式manualに沿ったlock-before-read実装をfake query-order/CAS回帰で検証する。同一revision競合に対する実DBのscheduler動作はこのpacketでは未検証であり、後続のopt-in disposable testで一件だけがhistory・node・Source current edge・auditを進め、敗者は `RevisionConflictError` となることを合格証拠にする。通常の成功・失敗後とも内部lock propertyは永続ノードに残らず、既存payload、owner境界、replay fingerprintは変化しない。

## ユーザーストーリーと受け入れ条件

### US-1 Sourceのstale同時更新を拒否する

As a Source更新呼び出し元, I want 同じexpected revisionを使う競合更新の一件だけを成功させたい, so that古い改訂が新しいcurrent pointer/edgeを上書きしない。

Given: 同一ownerのSourceがrevision `n`にあり、二つの異なるkeyがそれぞれ `expected_revision=n` / proposed revision `n+1` で同じSourceを更新する。
When: 両更新が重なり、一方が対象ノードのwrite lockを保持している間に他方が開始する。
Then: 成功は一件だけであり、敗者はlock解放後に読み直したrevisionとの不一致で拒否され、current pointerと `CURRENT_SOURCE_REVISION` は勝者を指し、旧 `HAS_SOURCE_REVISION` 履歴は残る。

### US-2 ResearchCampaignのstale同時更新を拒否する

As a Campaign更新呼び出し元, I want 同じaggregate revisionを使う競合更新の一件だけを成功させたい, so that承認・取消・run countの新状態を古い更新で巻き戻さない。

Given: owner-local ResearchCampaignがaggregate revision `n`で保存され、二つの更新が同じ `expected_revision=n` を指定する。
When: 両更新が重なり、後続が対象node lockを待つ。
Then: lock取得後のrevision比較により一件だけが履歴・Campaign payload・監査を更新し、もう一件はstaleとして拒否される。

### US-3 replayと失敗の境界を保つ

As a 再送する呼び出し元, I want 確定済み同一commandの再送が保存状態を変更せずreceiptを返し、stale失敗も部分保存されないようにしたい, so that再送と競合が履歴を重複させない。

Given: 同じfingerprintのidempotency receiptが既にある、または更新中にhistory/audit作成が失敗する。
When: そのcommandが再送される、または更新transactionが例外で終了する。
Then: replayは現在ノード、history、edge、auditを変えずreceiptを返し、失敗transactionは新history/node/edge/auditを残さない。内部lock propertyもcommit状態に現れない。

## 質問リスト

なし。公開tool/API、保存payload形式、新しいDB schemaは変更しない。

## スコープ外

- InMemory adapterの変更（既に一つのprocess-local lock内でrevisionを比較する）。
- generic Source / ResearchCampaign以外のmutable node、SourceRevision append、capture_source、ResearchRun、lifecycle operationの新command化。
- arbitrary direct Cypher / 別write clientとの競合制御。すべての許可writerが同じ対象node lockを通ることを前提とする。
- 新しいNeo4j label、constraint、index、長寿命lock node、公開property、APIまたはMCP tool。
- 通常DBへの書き込み、サービス再起動、本番runtime exposure。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| RP-NEO4J-REV-01 | `founder_graph_neo4j.py` の既存対象node更新にowner-scoped一時write lockを追加し、同lock保持中に現行revisionを読み直す。既存history、Source edge、auditを同じtransactionに保つ | 検査: fake transactionでlock-before-authoritative-read、owner filter、current revision reread、stale時にhistory/SET/edge/auditなし、replay no-op、lock property非保存を確認。`uv run pytest -q backend/tests/test_founder_graph_neo4j.py backend/tests/test_founder_graph_neo4j_revision_lock.py backend/tests/test_founder_graph_neo4j_write_parity.py` と `git diff --check` | 類推可能 |
| RP-NEO4J-LOCK-SPIKE | 完了: clean mainにfixtureなし、WSL Docker連携なし、Windows Docker CLI/daemon利用可。既存Neo4j containerは未接触。実競合用fixtureは別packetで独立review後に設計 | 検査: unique disposable container/volume追跡・cleanupと2 writer synchronizationをレビューし、実DB/サービスに接続しない | 類推可能 |
| RP-NEO4J-REV-02 | 別packetでDisposable Neo4jのSource/Campaign同revision競合回帰を追加し、独立review後にopt-in実行 | 検査: 合成DB上で勝者一件、stale conflict一件、1 history/1 audit/current edge一致、内部lock property不存在を確認。実行できない場合は実DB競合証拠を未達として明示 | 未知 |

## ADR

| 判断 | 選択と理由 | 却下案と却下理由 | 結果 |
| --- | --- | --- | --- |
| lock単位と順序 | 既存owner-local Source / ResearchCampaign nodeを一時property更新で明示ロックし、同じtransaction内でロック取得後にrevisionを読んでexpected valueと比較する。Node IDは既存label別一意制約で保護され、別ownerの同ID nodeはowner predicateで除外する | read後のconditional `SET`だけでは、Source参照/historyなどの先行validationがstale snapshotに依存する。owner全体を一つのlock nodeで直列化すると不要な競合とschema要素が増える | 同一対象だけを直列化し、公開schemaは増やさない |
| lock cleanup | 専用内部propertyへ一時値をSETして直ちにREMOVEする。Neo4jがproperty変更時にNODE write lockを取得し、そのlockをtransaction終了まで保持する根拠を公式manualで確認する。通常保存SETはallowlist map全体で置き換え、内部fieldを含めない | 永続lock fieldはserialized node stateへ混入する。別lock nodeは一意性migrationとlifecycleが必要 | propertyはtransaction外から観測されず、payload/responseも変わらない |
| replay | 最初にexisting auditを確認して既存replayはlockを取らず返す。lock待ちの間に同じkeyが別transactionで確定した場合はlock後にauditを再確認し、競合更新/二重historyを避ける | lock前の単一audit確認だけでは同時同一key要求がともに未記録を読み、後続がstale conflictか重複記録となる | 最初の通常replayはread-only。in-flight duplicate時の一時lockは保存状態を変更せず、transaction内で解放する |

## 変更履歴

実装拘束: 一時lock propertyのSETとREMOVEは一つのCypher statementにまとめる。検証・履歴・監査など後続callback処理で例外が発生した場合、Neo4j driver-managed transactionをrollbackし、一時propertyを含む一切の変更をcommitしない。

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | Source / ResearchCampaignのNeo4j concurrent expected_revision raceを限定し、owner-scoped temporary node lock案と受入条件を追加 | 既存Neo4jは現行revisionをreadした後に履歴・payloadを更新するため、read-committed下のlost updateを許し得る。Neo4j公式manualはdummy property writeでread前lockを取り、transaction終端まで保持する方法を説明する | RP-NEO4J-REV-01, RP-NEO4J-REV-02 |
| 2026-09-26 | Disposable concurrency harnessと環境証拠の30分spikeをintegration regressionより前に追加 | 通常DBへ触れず、偽の同期テストを実機根拠と誤認しないようにし、安全な隔離実行が可能かを先に判定する | RP-NEO4J-LOCK-SPIKE, RP-NEO4J-REV-02 |
| 2026-09-26 | Lock-before-read implementation packetと実DB race-proof acceptanceを分離 | clean mainには disposable fixtureがなく、WSL Docker連携も無い。現行コンテナを使わず、隔離test harnessの独立review後にのみ一回実行する | RP-NEO4J-REV-01, RP-NEO4J-REV-02 |

## 出典

- Neo4j Operations Manual, [Concurrent data access](https://neo4j.com/docs/operations-manual/current/database-internals/concurrent-data-access/): default read-committedでは読み取りが他writerを止めず、temporary property writeでread前の明示lockを取得し、transaction完了まで保持できると説明する。
- Neo4j Operations Manual, [Database internals and transactional behavior](https://neo4j.com/docs/operations-manual/current/database-internals/): transaction isolation/atomicity、node/property書込みlock、rollback時の解除を説明する。
