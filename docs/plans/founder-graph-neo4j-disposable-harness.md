# Neo4j使い捨て検証環境ヘルパー計画
最終検証日: 2026-09-26
## 要望 / ゴール / 成功指標
要望: 実Neo4j競合検証に先行して、専用Docker資源だけを作成・後片付けする再利用可能なテスト用ヘルパーを独立して配送する。
ゴールと成功指標: 実DBを起動せず、厳密なopt-inと資源所有確認をテストし、未許可・誤所有資源は削除せず、専用Docker資源だけをexact cleanupする500行以内のpacketを配送する。

## ユーザーストーリーと受け入れ条件
### US-1 隔離テスト資源の安全な管理
As a ローカルDB保守者, I want 専用ラベルの一時Docker資源だけを作成し後片付けしたい, so that 通常DBや他のDocker資源に触れず実Neo4j試験を準備できる。
Given: caller opt-inなし、未ロードimage、または所有ラベルが一致しない資源。
When: test callerが`is_opted_in`で起動をgateし、opt-in時はhelperが`--pull=never`と資源検証・cleanupを行う。
Then: 通常pytestはcallerがDocker CLI前にskipし、明示opt-inでもimage取得は発生せず、誤所有や予期しないimage/network/volume/mount/port資源には削除命令が出ず、所有確認できた固有資源だけ個別削除対象になる。

## 質問リスト（なし）

## スコープ外
- 実Docker daemon、Neo4j container、通常/既存DB、services/runtimeへの接続・書込・再起動。
- image pull/prune、既存container停止、任意cleanup target/CLI/image/nameの環境変数化。
- Neo4j競合実証、transaction metadata、production Gateway変更、replay/rollback証明。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| RP-NEO4J-REV-02A | `backend/tests/neo4j_disposable_harness.py` と安全fake tests、専用plan | 検査: helper単体pytest、compile、diff-check。opt-in predicate、Docker引数、exact cleanupをfakeで確認。通常callerのskip-before-CLIは第2packetで統合確認 | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| テスト資源 | exact opt-in、固定Windows Docker CLI、既ロード`neo4j:5.26-community`、`--pull=never`、UUID run label、internal bridge、127.0.0.1の動的port、image宣言named volumeを使う | 通常pytestでの起動、image pull、shared bridge、anonymous volume、広域pruneは誤対象/外部接続リスクを増やす | caller opt-in gateとstart引数・部分失敗cleanupをfakeで検査し、実daemonには接続しない |
| packet分割 | lifecycle helperと安全fakeを先に配送し、その後に実競合テストとmetadata付きtransaction proxyを別packetにする | 全機能を一つにまとめると600行になり、独立レビュー境界を超える | 第2packetは第1packetのmerge後、別planと独立レビューを経る |

後続の実競合packetでは、internal bridge上でloopback publish mappingを得られなかったため、bridge transportだけをUUID所有の通常bridgeへ変更する。上記internal選択は#262 helperの当時の設計記録であり、後続の実競合runnerには適用しない。通常bridgeのegress能力と抑制策は[`founder-graph-neo4j-revision-lock-real-test.md`](founder-graph-neo4j-revision-lock-real-test.md)に記録する。

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | 600行の検証案をlifecycle安全helperと実競合検証に分割 | 安全ガードを先行レビュー可能にし、実Docker実行は依存配送と再承認まで止めるため | RP-NEO4J-REV-02A; 第2packet RP-NEO4J-REV-02B |
| 2026-09-26 | `container create --pull=never`を必須化し、volume createの異常応答後にcandidateをexact inspect/cleanupするfake試験を追加。既定skipはcallerの責務と明記 | Docker CLIのdefaultは`missing`のためpull禁止を明示し、部分作成資源の安全な後片付けを確認する | RP-NEO4J-REV-02A |
| 2026-09-26 | 後続実競合packetでinternal bridgeをUUID所有通常bridgeに置き換える。#262時点のinternal選択は履歴として保持 | 実競合packetの一回限定試験がrequired loopback port metadataを得られずwriter race前に停止したため | RP-NEO4J-REV-02B-SAFE-TRANSPORT |
