# Founder Graph Neo4j write parity 計画
最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: Neo4j の永続 write 経路でも ReportVersion の参照整合性を保存前に検証し、in-memory 経路との安全境界の差を小さくする。

ゴール: 同一ownerの Run、Campaign、Claim、Evidenceだけを参照するReportVersionを保存し、欠落、型違い、Campaign不一致、authorization不一致をmutation前に拒否する。

成功指標: fake Neo4j driverで有効な参照が保存され、欠落または不一致の参照ではCREATEとauditが発生しない。

## ユーザーストーリーと受け入れ条件

### US-1

As a Founder Graph owner, I want persistent report writes to validate their graph references, so that Neo4j cannot contain a report pointing to an unrelated or private aggregate.

Given: A ReportVersion references persisted Run, Campaign, Claim, and Evidence records owned by the local owner.
When: The report is written through the Neo4j gateway.
Then: The gateway accepts it only when node types, owner, Campaign membership, authorization snapshot, and section evidence-to-claim links match.

### US-2

As a Founder Graph owner, I want invalid persistent writes to fail before mutation, so that a rejected report cannot leave an audit or partial node behind.

Given: At least one referenced record is missing, cross-owner, wrong type, or inconsistent.
When: The report write is attempted.
Then: A GraphWrite error is raised before report CREATE and audit CREATE queries run.

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
|---|---|---|---|
| Q-N4J-WP-01 | 完全なCampaign履歴をNeo4j Historyへ保存する時期 | 利用者兼製品責任者 | live report write gate 前 |

## スコープ外

- 全NodeTypeの汎用hydrator
- 既存Neo4jデータの移行、履歴payloadの再構成、live Docker gate
- ReportVersion以外の新しいMCP tool
- 外部AI、Deep Research、ChatGPT接続

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| WP-1 | Neo4j ReportVersion参照validator | 検査: `uv run --isolated --python 3.14 --with pytest pytest -q backend/tests/test_founder_graph_neo4j_write_parity.py` が通る | 類推可能 |
| WP-2 | gateway回帰と実装メモ | 検査: `uv run --isolated --python 3.14 --with pytest pytest -q backend/tests/test_founder_graph_neo4j.py backend/tests/test_founder_graph_neo4j_write_parity.py`、`python -m py_compile backend/dots/founder_graph_neo4j.py`、`git diff --check` | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| 検証位置 | gateway transaction内で型・owner・参照を確認する | MCPだけで検証する案は、別callerの直接gateway writeを保護できないため却下 | persistent writeのmutation前境界を一箇所へ集約する |
| Campaign履歴不足 | 現在payloadで確認できるauthorization snapshot / revisionだけを検査し、完全履歴の再構成はこのsliceの責務にしない | 履歴不足を推測で補完する案は、古い許諾を誤って有効化するため却下 | 完全履歴の永続parityはQ-N4J-WP-01とlive gateへ残す |

## 実装メモ

- ReportVersionのRun / Campaign / Claim / Evidenceをparameterized node queryで取得する。
- Campaignの現在authorization、Runのsnapshot/revision、section evidenceのclaim_idを比較する。
- 不整合はCREATE前にGraphWriteErrorへ変換し、既存in-memory contractは変更しない。
- `backend/tests/test_founder_graph_neo4j_write_parity.py` に有効参照、Campaign欠落、section evidence不一致のfake-driver契約テストを追加した。

## 実装結果

- WP-1: 実装済み。`Neo4jGraphGateway._validate_report_references_tx` がRunからCampaignをowner-scopedに解決し、現在のauthorization snapshot / revision、期限、Claim / Evidenceの型とsection対応をCREATE前に検査する。
- WP-2: 実装済み。gateway回帰を含む focused suite は `11 passed`、`python -m py_compile backend/dots/founder_graph_neo4j.py` と `git diff --check` は成功。
- 未完了: Campaignの完全なrevision/history再構成、Neo4j実機でのmutation/再起動検証、live migrationはQ-N4J-WP-01とPhase 0 gateの対象。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-09-22 | 初版作成 | Neo4j persistent writeのReportVersion参照境界をin-memoryと揃えるため | WP-1〜2 |
| 2026-09-22 | ReportVersion参照validatorとfake-driver契約テストを実装 | 永続writeでもCampaign許諾・Claim / Evidence対応をmutation前に検査するため | WP-1〜2 |
