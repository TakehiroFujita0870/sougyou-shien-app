# Founder Graph report persistence bounded plan

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

### 要望

`save_research_report` が、ReportVersionのshapeだけでなく、保存済みのResearchRun、Evidence、Claim、Campaignへの参照を同一ownerの不変ノードとして検証してから保存する。

### ゴール

通常チャットからのレポートwrite-backで、存在しない参照、別ownerの参照、別Campaignを混ぜたRun参照を永続化せず、同一idempotency keyの再送だけを安全にreplayする。

### 成功指標

有効なdraft/final ReportVersionは参照ノードと一緒に保存でき、無効な参照は状態とauditを変更せずに機械可読エラーとなる。既存の6 write tool、Campaign/Runの不変履歴、Source履歴、モデルカタログには変更を加えない。

## ユーザーストーリーと受け入れ条件

### US-RP-1 参照付きレポート保存

As a report writer, I want a report to resolve all referenced runs, claims, and evidence inside the local owner graph, so that a saved report never points at missing or cross-owner data.

Given: 同一ownerのCampaign、ResearchRun、Claim、Evidenceと8章のReportSectionを保存済みにしている。

When: `save_research_report`へそのIDを渡す。

Then: ReportVersionが保存され、receiptのtarget IDで取得でき、再送は同じreceiptをreplayする。

### US-RP-2 不正参照のfail-closed

As a local owner, I want invalid report references to be rejected before mutation, so that a partial report cannot enter the graph.

Given: ReportVersionのRun、Claim、Evidenceのいずれかを不存在、別owner、別Campaignへ置き換えている。

When: `save_research_report`を呼び出す。

Then: `invalid_input`または`not_found`として拒否され、ReportVersion、node history、audit event、idempotency stateは増えない。

### US-RP-3 final reportの根拠境界

As a report reader, I want a final report to reference only resolved runs and section-level Claim/Evidence pairs, so that finalization cannot bypass provenance checks.

Given: `status=final`の8章ReportVersionを作成している。

When: 全Run、全Report直下Evidence、各SectionのClaim/Evidenceが同一ownerで存在する場合、または一つでも欠ける場合に保存する。

Then: 完全な参照だけが保存され、欠落・owner不一致・EvidenceとClaimの不一致は保存前に拒否される。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-RP-1 | 追加の仕様決定はあるか | なし。既存のFounder Graphピボット契約を適用する | 2026-09-22 |

## スコープ外

- Campaignの新しい状態名、許諾snapshot、試行予算の意味変更。
- ResearchRunの生成・実行・通知、Deep Research、外部AI、MCP transport。
- SourceまたはSourceRevisionのrevision履歴、Source projection。
- モデルカタログ、モデルID、embedding provider。
- Neo4j adapter、DB migration、UI、物理削除。
- `docs/inherited/` の変更。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| RP-1 | write serviceのReportVersion参照検証 | 検査: `test_save_research_report_resolves_same_owner_references`、`test_save_research_report_rejects_missing_or_cross_owner_references`、`test_save_research_report_rejects_mixed_campaign_runs`、`test_save_research_report_rejects_section_evidence_for_another_claim` がgreen。 | 類推可能 |
| RP-2 | MCP保存経路とCampaign境界の回帰 | 検査: `test_save_report_and_decision_are_owner_scoped`、`test_save_research_report_accepts_two_runs_from_one_campaign`、`test_save_research_report_rejects_run_after_campaign_scope_change`、`test_save_research_report_rejects_expired_campaign_authorization`とRP-1がgreen、`python -X utf8 -m py_compile backend/dots/founder_graph_write.py backend/dots/founder_graph_mcp_write.py`、`git diff --check`。 | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-RP-1 検証位置 | InMemoryGraphWriteServiceのsave経路で、既存ノードsnapshotを解決してからputする。MCP以外の同じwrite境界にも同じ安全契約を適用できるため。 | MCP adapterだけで検証する案は別callerのput_nodeから不正ReportVersionが入るため却下。 | 参照検証失敗はnode、history、audit、idempotencyを変更しない。 |
| ADR-RP-2 Campaign帰属 | Reportのrun_idsが0件ならdraft編集を許可し、1件以上なら全Runが同一owner・同一Campaignで、Campaignノードも存在することを要求する。ReportVersionへ新fieldを追加せず既存のResearchRun.campaign_idから導出するため。 | ReportVersionへcampaign_idを追加する案はdomain schema変更を伴い、今回の安全なwrite境界を越えるため却下。 |
| ADR-RP-3 既存互換 | 既存の参照なしdraft保存と8 tool名を維持し、final化時だけ既存ReportVersionの根拠契約と保存済み参照を要求する。 | 全draftに外部参照を要求する案は途中編集を壊すため却下。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | ReportVersionのwrite-back参照境界を追加 | 現行MCPがReportVersion単体を保存し、Campaign/Run/Evidence/Claim参照を解決していないため | RP-1、RP-2 |
