# Neo4j ResearchRun 原子的write 計画

最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: 現在認可済みのowner-bound ResearchCampaignに対し、terminal ResearchRun、予算消費、履歴、関係、監査receiptを一つのNeo4j transactionへ保存する。

ゴール: メモリwriterと同じfingerprint・時刻・再送契約を、Campaign write-lock付きNeo4j gatewayへ実装する。

成功指標: 合成transaction契約で成功、同一key replay/conflict、lock後recheck、CAS・snapshot・owner・status・budget・時刻拒否、unknown commit後receipt recoveryを検証し、API/MCPで未配線の状態を保つ。

## ユーザーストーリーと受け入れ条件

### US-NRW-01 — 現行CampaignにRunを原子的に記録

As a local Founder Graph owner, I want a terminal ResearchRun recorded against the locked current Campaign, so that trial budget and Run history cannot diverge.

Given: Runはlocal ownerで、Campaign ID、期待revision、現行authorization snapshot/revision、時刻、有効なterminal statusと予算が一致する。

When: owner-scoped idempotency keyでNeo4j writerを呼ぶ。

Then: Campaign lock下の一transactionで履歴・Campaign更新・ResearchRun・HAS_RUN・auditが確定し、各terminal statusのRun一件につきCampaign run_count/revisionは一つ進む。

### US-NRW-02 — 再送と不確定commitの安全な解決

As a local Founder Graph owner, I want exact retries to return the committed receipt and changed retries to conflict, so that network uncertainty cannot double-consume a trial.

Given: 同じowner/keyの監査receiptが存在するか、先行commit結果が通信失敗で不確定である。

When: 同じstable intentを再送する。再生成されたRun開始/終了時刻とprovenance occurred_atだけはfingerprint対象外とする。

Then: lock前とlock後のaudit確認、またはrollback後read-only照会で一致receiptをreplayし、不一致fingerprintは`IdempotencyConflictError`、receipt不在/照会失敗は固定`Neo4jUnavailableError`となる。

## スコープ外

- `GraphWritePort`宣言、MCP接続、API/catalog配線。両adapter完成後のA担当依存follow-up。
- Neo4j実DB並行/rollback試験。C担当の独立opt-in testで扱う。
- full immutable Campaign authorization history。過去Runを履歴として証明するMVP必須の別packetであり、本writerはlock時点のcurrent Campaignしか承認根拠にしない。
- sparseな既存history/Runから過去snapshotを推測、合成、backfillすること。
- 通常DB、service/runtime変更、schema migration、LLM/API/外部調査。

## タスク

| ID | 成果物 | 完了判定 | 不確実性 |
| --- | --- | --- | --- |
| T-NRW-01 | Neo4j gateway transactionとwrite wrapper | 検査: transaction query順、typed Campaign decoder/shared timing/fingerprint再利用、Campaign/Run/edge/history/audit単一writeをfake driverで確認 | 類推可能 |
| T-NRW-02 | compact fake契約testsと本計画 | 検査: success/replay/conflict/race/CAS/authorization/timing/budget/duplicate Run ID/unknown-commit回復とreceipt lookup failure、不変domain拒否、focused/full backend pytest、`git diff --check`、独立全文reviewを確認 | 類推可能 |
| T-NRW-SP-02 | C担当隔離Neo4j run harnessの30分以内独立スパイク | 検査: metadata付きsession API、並行同key/異payload制約競合時のrollback後receipt再照会、exact cleanup手順を一次コードとfake確認で確定 | 未知 |
| T-NRW-03 | C担当隔離Neo4j rollback/parity検査 | 検査: T-NRW-SP-02完了後、専用合成DBで並行同key一件commit、異payload conflict、途中失敗rollback、exact cleanupを実証 | 未知・T-NRW-SP-02先行 |
| T-NRW-04 | A担当GraphWritePort/MCP配線 | 検査: T-NRW-03の実rollback成功とCampaign history proof必須依存の完了後、memory/Neo4j双方で共有portを介した呼出しとruntime選択先を確認 | 既知・必須gate後 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 認可source | Campaign node lock後に同nodeの完全なcurrent payloadを再取得し、owner/CAS/snapshot/revision/status/expiry/budgetを検証する。 | Run入力やmetadata-only historyから過去認可を推測する案は拒否する。 | 古いsnapshotは拒否。履歴証明は必須の別MVP依存として残る。 |
| atomicity | `_lock_revisioned_node_tx`後、Campaign history/update、Run、`HAS_RUN`、auditを同じ`execute_write` callbackで作る。 | 個別writeや事前予算更新では部分確定し得るため却下。 | Neo4jのtransaction rollbackが全件を戻す。fake testは順序を検査し、真のrollbackはCの隔離testが担当する。 |
| idempotency recovery | lock前後でowner/key auditを検査する。non-domain failure後はsession close後のread-only audit照会でfingerprint一致ならreplay、不一致ならconflict、receipt不在/lookup失敗なら元の固定unavailable errorを返す。 | domain validation errorをreplay回復へ流す案と、異なるpayloadを同じ成功へ写像する案は却下。 | replayにより後続Campaign状態は変更しない。 |
| 履歴境界 | 新Run書込みの認可はcurrent Campaignのみ。過去authorization証明を必要とするhistoryは全payload保持の別packet完了前まで証明済みと扱わない。 | 現在のmetadata-only historyや既存Runを自動修復する案は却下。 | current-write実装の限定性を明示し、historical proofは後続必須。 |

## 差分上限の例外

Campaign lock、同一transactionのCampaign/Run/history/edge/audit、replay/recoveryが一つの原子的write契約を構成するため、Gateway/wrapper/fakeの必要な安全負例を別PRへ分けると単独で利用可能な機能にならず、追加helper packetも独立した利用価値を持たない。初回計測は557行（Gateway 200、wrapper 16、fake tests 275、plan 66）。rootはこの単一目的に限り500行目安超過を承認した。後続reviewで重複ID照会到達とreceipt再照会自体の失敗を直接試験する必要が判明し、上限を610行へ拡張する追加例外を承認した。必要な拒否・recoveryケースを残し、変更範囲を同じ契約のみに限定し、full backend suiteと独立全文reviewを必須にする。610行を超える場合は停止して再計画する。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | Strict Campaign decoder merge後にNeo4j Run writer境界を再計画。Gateway/wrapper/fake testsを500行以内へ制限し、real DB testはC所有として分離。30分read-only code spikeではexisting revision-lock、shared timing/fingerprint、post-rollback audit read patternのAPI形状を確認したがreal rollbackは未証明 | 先行793行案を分割し、すでにmainへ入ったdecoderと#259共有contractを再利用する。Cの未知なreal harness API/cleanupは独立spikeを先行させる | T-NRW-01〜04 |
| 2026-09-26 | 実計測557行が目安を超えた。rootは独立した機能価値を持たないhelperへ分割せず、この一つのatomic Run契約に限る例外を承認。テスト境界にexpiry・duplicate Run拒否と4種terminal statusの予算消費確認を明記 | 受入負例を削らず、full backend検査と独立全文reviewを加え、増加上限580行で管理する | T-NRW-01〜02 |
| 2026-09-26 | Reviewでduplicate Run負例の時刻分岐が先行していた点とreceipt再照会例外の未試験を修正対象に記録。rootがこの2安全ケースに限り上限610行を追加承認 | 重複IDquery到達を直接確認し、readback障害でraw例外が漏れないことを試す | T-NRW-02 |
