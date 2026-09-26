# Neo4j改訂ロックの実DB検証計画
最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標
要望: #258で追加した一時node lockが、通常DBに触れず実Neo4jで既存Source/ResearchCampaignの同時更新を直列化するか一度だけ検証する。
ゴール: 第1packetの使い捨てDocker helperを使い、合成データで実Neo4j writer競合を観測するopt-inテストを追加する。
成功指標: 各node種でAがロックを保持中、Bの同じrevisionへのwriter queryをNeo4jのtransactions view上で観測し、その後Aだけが確定、Bがstale conflictとなることを確かめる。

## ユーザーストーリーと受け入れ条件
### US-1 SourceとResearchCampaignの同時改訂
As a 改訂保存処理の保守者, I want 実Neo4jのlock動作を二種類のnodeで確認したい, so that fakeテストだけに依存せずrace時の現行データを保護できる。
Given: 第1packetの隔離helper、preloaded Neo4j 5.26 Community、合成owner/node IDだけを使う。opt-in前にrace testと同じSource/SourceRevision fixturesを`validate_capture_source`とin-memory capture/append/updateで検証し、両campaign候補もin-memory create/updateで検証する。Sourceのlocatorは`https://example.invalid/...`だけを用い、取得しない。
When: opt-in実行でAがトランザクション内lockを保持し、Bが同じexpected revisionで更新を試みる。
Then: Bのmetadataに加え、対象lock query、`Blocked`または`Blocked by: ...`、非空resourceInformationを同じ観測行で確認後にAを解放し、各raceはA成功・B `RevisionConflictError`・winnerのrevision/payload/history/audit/current edge一致となる。

### US-2 実DB試験の安全な既定値
As a ローカルDB保守者, I want 通常テストと未承認の作業で実Docker試験を起動させたくない, so that 既存DBやDocker資源を誤操作しない。
Given: `DOTS_NEO4J_REVISION_LOCK_REAL`が正確に`1`でない、CLIがない、daemon応答がない、またはimage未ロード。
When: pytestを通常実行する。
Then: opt-in前はDocker呼び出しなしでskipし、opt-in時も`--pull=never`の固定image、UUID所有のbridge network、`127.0.0.1`限定のloopback動的port、named volumes、UUID run labelsと第1packetのexact cleanupだけを使う。試験containerは合成データと固定Neo4j問い合わせ以外の外向きリクエストを行わず、Neo4j usage reportを公式設定で無効化する。通常bridgeはcontainerに外向き通信能力を残すため、ネットワーク隔離を保証しない残余リスクを明示する。

## 質問リスト（なし）
実DBの一回実行は、親の独立全文レビュー後に明示再承認を得るまで行わない。

## スコープ外
- 通常/既存Neo4j、production service/runtime、実データ、認証情報、image pull、外部fetch。
- benchmark、再実行、productionコード変更、Gateway/API/MCP/schema変更。
- advanced/archive状態でのmatching-key replay不変性と、write後半のaudit/commit fault rollbackを実DBで再証明すること。既存根拠は`test_founder_graph_neo4j_revision_lock.py`のfake revision/replay testsと`test_founder_graph_source_capture_ingress.py`のsource write-flow/rollback testsだが、これらは実DB証拠ではなく、本試験の成功主張に含めない。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| RP-NEO4J-REV-02B-S | installed Python driver APIとNeo4j SHOW TRANSACTIONS契約の読み取り確認 | 検査: 5.28.6 `begin_transaction(metadata=...)` signature/sourceと公式manualを照合済み | 既知 |
| RP-NEO4J-REV-02B-PREFLIGHT | real raceと共有するSource/Campaign fixturesのproduction validator/in-memory write preflight | 検査: default-running Source baseline capture、revision2 append、両候補更新、およびCampaign baseline/両候補更新が成功する | 既知 |
| RP-NEO4J-REV-02B | 実競合opt-in test、public begin_transaction metadata proxy、fake proxy/status tests、専用plan | 検査: fake tests、default pytest skip、full backend、compile、diff-check。Docker試験はreview後に別承認 | 未知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| transaction tags | raw sessionをwrapし、`begin_transaction(metadata=...)`でmetadataを付けてGateway callbackを実行。明示transactionをcommit/rollback | `Driver.session(metadata=...)`はinstalled driverの公開signatureに合わず、`execute_write`にもmetadata引数がない | wrapperはtest-onlyで、managed transaction retryは再現しない。実競合のみ観測対象 |
| blocked観測 | `status`が`Blocked`または`Blocked by: ...`、同じ行のwriter/run metadata・lock query・resourceInformationで一致するまでAを保持 | thread start順や固定sleepだけでは実ロック待ちを証明しない | 今の公式SHOW docsはstatus enumを`Terminated/Blocked/Closing/Running`、`statusDetails`と`resourceInformation`を別列とする。prefix許容は防御的fallback |
| disposable port transport | UUID付き通常bridge上のNeo4jを、`--publish 127.0.0.1::7687`でloopbackにのみ公開し、実際の`NetworkSettings.Ports`も厳密検査する | 初回runはinternal-only bridge上でhost publish後、実際のport metadataが厳密なloopback条件を満たさず、race前に失敗した。traceにport-map payloadは残っていない | 内部bridgeの方がegress隔離は強いが、今回の確認ではloopback接続を確立できなかった。通常bridgeの残余egress能力を受容し、合成fixture、外向きアプリ要求なし、usage reportとBolt telemetry無効化、固定preloaded image、exact cleanupで範囲を限定する。`0.0.0.0`等は許容しない |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | lifecycle helper #262の後続として実競合のopt-in検証だけを別packet化 | 600行の計画をレビュー可能な499行helperと依存するrace testに分離したため | RP-NEO4J-REV-02B |
| 2026-09-26 | Campaign合成基準をaggregate_revision=1、両提案を2、expected_revision=1に固定しpure fixture assertionを追加 | デフォルト0の新規campaignをexpected=1で更新する不整合を実DB試験前に防ぐため | RP-NEO4J-REV-02B |
| 2026-09-26 | 初回の一回限定実DBrunがinternal-only bridgeのhost-port確認で停止。traceでは`NetworkSettings.Ports`のloopback条件不成立までしか記録されず、実payload形状は保存されていない。専用role label付きcontainer/volume/networkの読み取り一覧はすべて空 | 実writer raceまで到達しなかったため。近似するMoby報告はあるが今回のpayload根拠として扱わない | RP-NEO4J-REV-02B-SAFE-TRANSPORT |
| 2026-09-26 | 次packetでUUID通常bridgeへ切替、loopback厳格検証を維持。official Neo4j env mappingでusage reportとBolt telemetryを無効化し、potential egress残余を明示 | 初回実行がinternal-only bridgeのport条件で停止したため。原因となった実payloadは保存されていない | RP-NEO4J-REV-02B-SAFE-TRANSPORT |
| 2026-09-26 | 通常bridgeでの一回限定runはprecondition後、Source synthetic setupの`capture_source` validationで停止。実行時に確認した最初の不一致はWEB/LOCAL_ONLY policy。追加のコード読解で、同じfixtureにはmatching credential-free HTTP(S) locatorも欠けていた。専用role-label resourcesは再び全一覧0 | real raceへ入る前にfixture rejection。再実行前にshared fixtureをproduction validator + in-memory write pathで検査する | RP-NEO4J-REV-02B-PREFLIGHT |
| 2026-09-26 | shared fixture preflight後に許可された一回の実競合検査がSourceとResearchCampaignの両方で成功（pytest 18.56秒）。SHOW TRANSACTIONSのblocked行、winner/stale conflict、history/audit/current-edge assertionsが通過。専用role-label container/volume/networkの再点検は全一覧0 | fixture修正と通常bridge経路でwriter lockの実挙動を確認。audit/commit故障時rollbackは引き続きfake testの証拠のみ | RP-NEO4J-REV-02B |
| 2026-09-26 | 7ファイル539 changed linesを一つの安全検証packetとして配送対象にする許可を得た（上限560）。main更新前のdefault full backendは624 passed, 3 skipped, 7 warnings | safety helper、transport、preflight、transaction tagging、実競合assertionsは同じopt-in harnessの不可分な責務 | RP-NEO4J-REV-02B |
| 2026-09-26 | #265後のcurrent mainへrebaseし、default full backendを再確認（640 passed, 3 skipped, 7 warnings）。実競合opt-inは再実行せず、先の一回成功結果を維持 | 依存main変更が通常テストを壊さないことを確認し、実DB再試行を避ける | RP-NEO4J-REV-02B |

## 出典
- Neo4j Python Driver, [Transactions](https://neo4j.com/docs/python-manual/current/transactions/): `begin_transaction`のmetadataとexplicit transaction lifecycle。
- Neo4j Operations Manual, [SHOW TRANSACTIONS](https://neo4j.com/docs/operations-manual/current/database-internals/show-and-terminate-transactions/): status、metaData、resourceInformationの出力契約。
- Neo4j Operations Manual, [Configuration settings](https://neo4j.com/docs/operations-manual/current/configuration/configuration-settings/): `dbms.usage_report.enabled=false`。
- Neo4j Operations Manual, [Docker-specific configuration settings](https://neo4j.com/docs/operations-manual/current/docker/ref-settings/): Docker env mapping `NEO4J_dbms_usage__report_enabled`、`NEO4J_server_bolt_telemetry_enabled`。
- Docker CLI, [Publish or expose port](https://docs.docker.com/reference/cli/docker/container/run/): explicit `127.0.0.1` host binding; omitted host IP binds all interfaces by default.
