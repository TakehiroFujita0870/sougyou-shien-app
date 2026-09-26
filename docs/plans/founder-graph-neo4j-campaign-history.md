# Neo4j ResearchCampaign 完全履歴 計画
最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: P4-05-HISTとして、Campaignの承認内容をResearchRunの実行時点に照合できるよう、Neo4jに完全な型付きrevision履歴を保存する。

ゴール: Campaignの全aggregate revisionを欠落・重複なく復元し、過去の許諾根拠を現在のCampaign状態から推測せず検証できるようにする。

成功指標: 新規作成から承認、scope変更、再承認、Run登録、取消までの各revisionをexactly-onceで復元できる。既存のmetadata-only履歴や欠番はfail closedとなり、履歴を合成・補完しない。

## ユーザーストーリーと受け入れ条件

### US-HIST-01 — Campaign revisionの完全履歴を保持
As a local Founder Graph owner, I want each Campaign state revision retained as an immutable typed snapshot, so that later Run authorization can be checked against the state that existed at that time.

Given: owner-bound Campaignのrevisionが作成、一般更新、承認、scope変更、Run登録、取消のいずれかで確定する。generic createのrevisionは0とは限らない。
When: Neo4j writerがrevisionをcommitする。
Then: revision 0から連続するCampaignに限り、current nodeと旧revision履歴から`0..current.aggregate_revision`を各1件復元でき、各値は保存時の完全なResearchCampaignと一致する。revision 0が存在しない値はAPI互換のため保存を妨げず、履歴証明時にfail closedとなる。

### US-HIST-02 — 不完全な過去履歴を許諾根拠にしない
As a local Founder Graph owner, I want missing or corrupt historical authorization records rejected, so that old Runs are never legitimized from a later Campaign state.

Given: metadata-only legacy履歴、欠番、重複revision、owner/type/record revisionとpayloadの不一致、またはdecode不能なCampaign payloadがある。
When: trusted Campaign historyを解決する。
Then: 固定されたsafe validation errorで拒否し、欠落revisionの生成、現在状態からの復元、Runやsnapshotの書換えを行わない。

### US-HIST-03 — 更新履歴を非公開のまま保つ
As a local Founder Graph owner, I want authorization snapshots preserved only in owner-scoped internal storage, so that private scope and research fields do not appear in public reads or export.

Given: Campaign revisionには許諾scope、質問、field categories、provenanceが含まれる。
When: 内部history resolverが値を復元し、通常read/search/export projectionを確認する。
Then: trusted domain validatorだけが型付き履歴を受け取り、通常read/search/export/MCP出力には履歴payloadが追加されない。

## 質問リスト
| ID | 質問 | 決定者 | 期限 |
|---|---|---|---|
| なし | Neo4jは既存FounderGraphHistory label/indexを使い、各revisionを既存Campaign node payloadと同じJSON形式で記録する。歴史的な不完全データは拒否し、移行・backfillしない | root / persistence owner | 実装開始前 |

## スコープ外
- Sparse legacy履歴、Run、監査から過去Campaign payloadを推測・復元する処理、DB backfillまたは通常DB書込み。
- 新Neo4j label/index/schema migration。既存のFounderGraphHistoryを再利用する。
- API/MCP/GraphWritePortの公開配線、runtime/service変更、外部調査、実ユーザーデータ。
- Campaign履歴を通常read/search/exportへ表示すること。
- Report/IdeaBrief契約や純粋historical validatorの変更。既存validatorが求める完全な型付き履歴を提供する。

## 変更対象のwriter inventory

| 経路 | 現行動作 | 必須の履歴処理 |
|---|---|---|
| Neo4j `_put_node_tx` 新規Campaign作成 | expected_revision 0でcurrent Campaign nodeとauditを保存。generic APIはaggregate revisionが0より大きい初期値も受け入れ、履歴nodeは作らない | revision 0初期値だけはcurrent nodeが唯一のrevisionとして解決する。revision 0が無い初期値は保存互換性を維持しつつhistorical proofで拒否し、revision 0を合成しない |
| Neo4j `_put_node_tx` Campaign更新 | owner lockとCAS後、旧revisionの `{id,node_type,revision}` metadataのみFounderGraphHistoryへ保存しcurrentを置換 | 旧Campaignの完全な `payload_json` を保存。approve、scope変更、revoke、および他のaggregate transitionを同じ境界で扱う |
| Neo4j `_record_research_run_tx` | Run/HAS_RUNとCampaign更新をatomicに保存するが、旧Campaign履歴はmetadataのみ | 同じ共通history helperで更新前Campaignの完全値を保存し、Run経由でもrevision chainを切らない |
| `InMemoryGraphWriteService` `put_node` / `record_research_run` | `_node_history` に初期値と各immutable Campaign状態を型付きで保持 | 契約比較対象として維持し、Neo4j復元値と全field・revision順を比較 |

Domainの `approve()`, `change_scope()`, `register_run()` はimmutable遷移でaggregate revisionを進める。main #264時点のCampaign persistence入口はgeneric `put_node` とatomic `record_research_run`。別のpending live integrationにはcreate/approve/revokeがgeneric `put_node` 経由であり、mainへ統合する前に本履歴契約を必須とする。scope/revoke用のdomain/APIが別に加わる場合も同じgeneric writerを使用し、generic writerを迂回する新しいCampaign revision writerは同じhistory helperを同一transaction内で呼ぶ。

履歴復元は、owner-scoped immutable prior snapshotsとcurrent typed Campaignを結合する。current revisionを履歴にも重複保存せず、revision番号でsortした後、同一Campaign/owner、uniqueなrevision、`0..current.aggregate_revision`の連続性、decoderのstrict field/type/enum/time検査を確認する。aggregate revision 0で作成されたCampaignはcurrent nodeだけで完全な`0..0`となる。generic createがaggregate revision>0で初期作成された場合、過去revisionは観測されていないため歴史proofを拒否する。aggregate revisionが0より大きいのにprior revisionが欠けるlegacyデータも不完全として拒否する。generic APIの既存保存動作は変更しない。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-HIST-SP-01 | C所有の隔離Neo4j履歴試験API/cleanup read-only spike（30分上限） | 検査: 既存のrevision-lock/run harnessのmetadata/session/transaction fault-injection/volume-cleanup APIを確認し、履歴fixtureと途中rollback注入点、safe diagnostics、exact cleanupを決定。通常DB/service不使用 | 未知 |
| T-HIST-01 | Neo4j current/prior Campaign履歴のstrict typed resolverと共通保存helper | 検査: revision0 current、複数承認epoch、scope変更、Run登録、取消の完全field roundtripと0..max連続性をfocused fake testsで確認。revision>0初期値はfail closedを確認 | 類推可能 |
| T-HIST-02 | 全revision writerのatomic history integrationと拒否回帰tests | 検査: generic create/updateとRun save各経路でold full payload・current node・auditが一transaction、replay/no duplicate、legacy sparse/malformed/duplicate/gap/owner mismatch拒否を確認。fake transactionは期待順序とrollback呼出境界を検査するが、Neo4j実rollbackの証拠に数えない。memory parity、`uv run pytest backend/tests -q`、`git diff --check`、独立全文reviewを実施 | 類推可能 |
| T-HIST-03 | C所有の隔離Neo4j履歴rollback/parity証明 | 検査: T-HIST-SP-01後にsynthetic-only disposable DBでCampaign create→approval/scope/revoke/run履歴の読戻しと途中rollbackを確認し、container/volume exact cleanupとzero residueを証明 | 未知・T-HIST-SP-01先行 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| 履歴表現 | 既存 `FounderGraphHistory` に、更新直前の型付きCampaignを既存`_node_properties`と同じ完全JSON payloadでowner/target/revisionに結び付けて保存する。復元時はprior snapshotsとcurrent typed Campaignを合わせ、current revisionを重複させず一意な連続系列にする | Campaignごとに最新許諾だけ保存する案は以前のRun時点authorizationを検証できない。別node label/indexを追加する案は既存履歴表現とschemaを不要に増やす | 一般更新とRun更新が同じ保存helperを使い、create revision 0はcurrent nodeとして一度だけ数える |
| 既存不完全データ | strict resolverはrevision連続性とstrict decoderを要求し、欠けた値を拒否する | latest CampaignやRun snapshotから過去revisionを合成する案、silent backfillは権威のない許諾を作るため却下 | legacy sparse historyの解消は別の明示的移行判断まで行わない |
| 読取境界 | 履歴値はowner-scoped internal resolverだけで型付きdomain validationへ渡し、MCP/public read projectionから隔離する | 履歴payloadを汎用fetch/searchへ混ぜる案は許諾範囲や調査情報を漏らし得る | 既存safe projection allowlistを拡張しない |
| transaction境界 | Campaign lock下で旧完全payloadの履歴作成、current update、必要なRun/edge/auditを同一Neo4j transactionで確定する | historyを先行/後行する別transactionは、完全なrevision chainとcurrent stateを乖離させる | すべてのCampaign revision writerが同じatomic helperを共有する |
| 初期revision互換性 | generic createの既存条件（expected revision 0）とdomain aggregate revisionを分け、aggregate revision>0の新規保存は許可しても完全履歴resolverで拒否する | 過去のrevision 0状態を新規nodeのpayloadから推定して許諾履歴を作る案は拒否する | revision 0を含む連続系列だけがhistorical proofに使える |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-09-26 | main #264後のCampaign履歴境界を計画。generic writerはaggregate revision>0の新規値も受け入れるため、revision0を捏造せずhistory proof時に拒否する互換境界を追記。fake/pure実装を隔離Neo4j harness spikeから独立させ、Cの実機rollback testだけをspike後に置く | 過去Runのauthoritative proofにcurrent-only/sparse historyでは足りず、writer間で一貫した保存契約が必要 | T-HIST-01〜03 |
| 2026-09-26 | fake transaction検査を実Neo4j rollback証拠と分けて明記 | fake callbackはquery順と模擬状態rollbackのみを検査し、実DBのatomicityを証明しない | T-HIST-02,T-HIST-03 |
