# Neo4j ResearchRun / Campaign履歴 実機受け入れ計画

最終検証日: 2026-09-26

## 要望・ゴール・成功指標

#267のCampaign完全履歴とRun writerを、#266の隔離Neo4j helperで合成データのみ使って検証する。通常DBや製品runtimeは変更しない。rootの独立レビューと実行ごとの明示承認なしにDockerを起動しない。

成功条件は、同じRunの並行保存が一件だけ確定すること、許諾変更後も過去のRun/brief判定が保存当時のscopeに基づくこと、Audit書込み失敗時にtransaction全体がrollbackし同じkeyのretryが一件だけ成功すること、試験用container/volume/networkが全て撤収されること。

## 受け入れ条件

### US-RH-01 — Runの直列化と冪等性

Given: revision 0のpending Campaignを作り、明示承認でrevision 1にする。Runの開始・終了時刻は承認後かつ有効期限前とする。
When: 同じRun/keyを二writerで競合させ、Aがrevision lockを保持中にBを開始する。
Then: transaction metadata付き`SHOW TRANSACTIONS`でBのlock query、blocked状態（`Blocked`または`Blocked by: ...`）、resource情報を確認する。解放後は一件の保存と一件のreplay、Run/HAS_RUN/receipt各一件、run_count増加一回となる。変更したresults/evidenceを同じkeyで送るとconflictになり、合成snapshotは不変。

### US-RH-02 — Campaign完全履歴と非遡及性

Given: Campaign revision 0から開始し、approval (1)、Run記録 (2)、scope変更 (3)、再approval (4)、revoke (5)を保存する。IdeaBriefは`run.finished_at <= brief.created_at < first scope change/revoke`を満たす合成8節版とする。
When: 明示read transactionで`_campaign_authorization_registry_tx`を呼び、完全な`registry.campaigns`をhistorical validatorへ渡す。
Then: revision 0..5がowner-boundの完全なtyped履歴として戻る。scope変更/revoke後にも元のRun/briefは通り、終了がrevoke以後の合成Runは拒否される。revoked Campaignへの新Run writeも拒否されstate不変。履歴payloadを一般read/API/MCPへ公開しない。expiryは常に未来とし、現在時刻による遡及試験はしない。

### US-RH-03 — 最終Audit失敗のrollbackとretry

Given: opt-in試験開始後、read-only `SHOW CONSTRAINTS`で既存`dots_foundergraphaudit_id`がAudit node `id`のuniqueness constraintであると確認する。決定的Audit IDに、異なるsynthetic owner/keyのsentinelを置く。
When: 有効なRunを記録し、最終Audit CREATEでunique violationを起こす。
Then: safe errorだけを返し、Campaign/current payload、全History、Run、HAS_RUN、対象owner/key receiptの前後snapshotが一致する。sentinelのexact ID/ownerだけをfinallyで削除し、同じRun/keyをretryすると各記録が一件だけ確定する。payloadやdriver error本文を診断へ出さない。

### US-RH-04 — 隔離と撤収

Given: callerが明示opt-inした。
When: #266の固定image/DisposableNeo4j helperで全ケースを実行する。
Then: `--pull=never`、UUID/run-role labels、named volumes、単一の`127.0.0.1`動的Bolt port、bounded readiness queryを保つ。driver終了後、labelと実resource情報を照合して個別cleanupし、container/volume/network全inventoryが空であることを検証する。opt-inなしではDockerへ問い合わせる前にskipする。

## 前提・実行境界

- 検証基準はmain #269 `139e3f14f35f`。#267はstrict Campaign history resolverとprior full-payload保存helperを追加した。`dots_foundergraphaudit_id` uniquenessは現行schemaに既存の制約であり、#267の追加ではない。
- `_campaign_authorization_registry_tx(tx, campaign_id)`はowner-scoped current Campaignと全prior Historyをdecodeし、revision 0..currentの連続性を検証する。`_store_prior_campaign_revision_tx(tx, record)`は完全なtyped payloadを同一transactionに保存する。
- Audit sentinelを作る前にconstraintのname/type/label/propertyを実機確認する。不在・不一致ならfault caseを実行しない。
- strict resolverは明示`session.begin_transaction(metadata=...)`内でのみ呼ぶ。完全な`registry.campaigns`をvalidatorへ渡し、snapshotに合うepochを間引かない。
- Synthetic revokeは既存テスト契約の`ResearchCampaign._transition(status=Status.REVOKED, ...)`とgeneric writerを使う。これは公開revoke workflowの検証ではない。
- Briefはpure historical validator用の合成fixtureであり、Brief DB persistence gateは対象外。#266の証拠はSource/Campaign generic revision lockのみで、Run/HIST実機を証明しない。

## テスト設計

1. **常時preflight（Docker前）**: production `validate_capture_source`等ではなく、本件のproduction historical validatorへ実fixtureを渡す。Campaign 0→approval 1→Run 2のmemory registrationでも同じfixtureを通し、brief時刻条件、revoke後の過去判定、post-revoke Run拒否を検証する。失敗時は実機gateへ進まない。
2. **Run race**: #266の既存tagged transaction/lock harnessを再利用する。writer Bのblocked lockを観測してからAを解放し、same-key replayとchanged-intent conflictの前後snapshotを比較する。
3. **History/non-retroactivity**: resolverが返すtyped revision 0..5、authorization snapshot/provenance、full registryでのbrief判定を確認する。期限は試験中ずっと未来。
4. **Late rollback**: constraintを先に照合し、foreign-owner sentinelによるAudit最終write failure後にCampaign/History/Run/link/Audit snapshotが不変であること、sentinel削除後のsame-key retryが一件であることを確認する。
5. **Cleanup**: #266 helperのexact UUID cleanupと三種類の空inventoryを確認。これはsynthetic-only gateであり外部通信・外部調査を行わない。standard bridgeの潜在egressは残る。

## スコープ外

- Production writer/domain/schema/MCP/API/UI変更、新History API、Brief persistence gate、migration追加。
- 通常DB、既存container/volume/network、runtime/service、実ユーザーデータ、外部HTTP/LLM/研究、長時間benchmark。
- 公開revoke workflow、期限後Runの歴史判定、expiryの時計操作、backup/restore、driver再接続・結果不明commit、複数DB/Neo4j版検証。
- #266のSource/Campaign一般put_node実機race再実行。成功後の追加実機実行。失敗後の再実行は新しいrootレビューと明示許可が必要。

## タスク

| ID | 成果物 | 完了条件（検査） | 不確実性 |
|---|---|---|---|
| T-RH-SP-01 | 本計画と#267/#266契約記録 | 検査: resolver順序、既存schema制約、fixture時刻、opt-in/cleanupを照合。通常DB/Dockerなし | 既知・完了 |
| T-RH-01 | 新規`backend/tests/test_founder_graph_neo4j_run_history_real.py` | 検査: production validatorとmemory writerで同じsynthetic fixtureを常時検証し、実機caseはDocker問い合わせ前にskip。focused/default/full backendとdiff-checkを実行 | 既知・focused/default/full pass |
| T-RH-02 | 同じ新規test moduleのopt-in実機suite | 検査: 独立reviewとrootの別途明示承認後、一回だけ実行。race/history/rollback/retry/zero-residueを記録 | 既知・one-shot pass、追試なし |
| T-RH-03 | 関連suite確認 | 検査: campaign history/historical brief/run write focused suiteとdefault backend suiteを実行 | 既知・pass |

## 検証実績

- 2026-09-26、明示opt-inで新規moduleを一度だけ実行: `3 passed`、22.04秒（2 preflight/helper test + 実機gate）。Bのblocked lock観測後にAを解放し、一件の保存・一件のreplay、Campaign revision 2/run_count 1/HAS_RUN・Run・Audit各一件を確認。changed-intent retryはsnapshot不変。
- Strict resolverはCampaign revision `0..5`をfixtureと全field equalityで返し、Run/briefはscope変更・revoke前として通過。revoke後Runの歴史判定と新規writeは拒否されstate不変。Audit最終CREATEのsentinel unique failure後、Campaign/current/History/Run/HAS_RUN/receipt snapshot不変を確認し、sentinel exact cleanup後のsame-key retryは一件だけ成功（history `0..2`、Run/link/Audit各一件）。#266 helperはUUID/run-role labelで三inventory zeroを検証。read-only Docker eventsで得たrun label `31331488d8ea439eac22aa6c509c25b6`をrootがWindows Docker CLIで再確認: container 0 / volume 0 / network 0、全CLI終了0。focused `52 passed, 1 skipped`; backend `698 passed, 4 skipped, 7 warnings`（opt-in時のPython 3.14 driver deprecation warnings含む）。synthetic DBのみ、一回の観測で追試なし。

## ADR

| 判断 | 採用理由 | 却下案と理由 | 結果 |
|---|---|---|
| Runtime | #266 helperを再利用し、fixed preloaded image、no-pull、UUID ownership、loopback、exact cleanupを維持 | 新runnerや通常DB URIはownership/cleanupを重複させる | 全synthetic caseを一module-scoped containerで行い、run-label zero residueを確認 |
| 履歴 | #267 resolverとfull prior payloadを使い、全typed registryをvalidatorへ渡す | 履歴をtest側で捏造、またはcurrent-only payloadで代用すると欠落を隠す | revision 0 createからrevokeまでを読み戻す |
| Rollback | 実constraintを先に検証し、real transactionの全snapshotを比較 | fake-only例外はNeo4j atomicityを証明しない | 全state不変を確認しsentinel exact delete後に同keyを一度retry |
| Brief時刻 | `run.finished_at <= brief.created_at < first scope change/revoke` | Run完了より前に作成したbriefを歴史判定へ使うと時間順序が不正 | expiryは未来に保ちcurrent-time retroexpiryを主張しない |

## 変更履歴

| 日付 | 変更 | 理由 |
|---|---|---|
| 2026-09-26 | #267後のRun/HIST一回限り実機受け入れ計画を作成 | Run transactionとCampaign完全履歴の結合を合成データで確認 |
