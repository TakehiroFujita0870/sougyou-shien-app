# Founder Graph Campaign / Run 比較UI 計画

最終検証日: 2026-09-22

## ゴール

同一ResearchCampaignに属する複数のResearchRunとReportVersionを、外部通信・書き込みなしで比較できるsafe UI契約を追加する。既存の8章ReportDiffを再利用し、run ID、試行数、比較対象を表示する。

## Given / When / Then

- Given: 前版・現版のsafe report projectionと、同一Campaignのrun metadataがある。
- When: `FounderGraphCampaignCompare`を描画する。
- Then: Campaign ID、run ID、試行数、8章の差分を表示し、private/raw fieldを描画しない。
- Given: loading / unavailable / error / empty状態である。
- When: componentを描画する。
- Then: 状態メッセージだけを表示し、report本文や比較タブを表示しない。

## スコープ外

- API、MCP、Neo4j、Deep Research、外部通信、write-back。
- App / WorkspaceShell / shared styleへの配線。
- backup / restoreや実ファイルexport。

## ADR

| 判断 | 選択と理由 |
| --- | --- |
| 入力 | safeなmappingだけを受け、既存ReportDiffへ投影する。任意のdomain objectやraw payloadは受けない。 |
| 比較 | ReportDiffへ委譲し、固定8章の章名・statusを二重実装しない。 |
| 状態 | Campaign metadataとreport状態を分離し、停止時はread-only messageで閉じる。 |

## 実装メモ

- `src/components/FounderGraphCampaignCompare.jsx` と focused testsを追加した。
- Campaignは `id / purpose / status / trial_budget / run_count`、Runは `id / status / model_snapshot / created_at / finished_at` に限定して投影し、Run IDを重複排除する。
- 既存の `FounderGraphReportDiff` をcompositionし、8章表示とexport intentを再利用する。export callbackへはReportDiff側のshareable scope契約だけが渡る。
- 外部通信・書き込み・ファイルAPIは呼び出さない。

## 検査結果

- `npm.cmd test -- --run src/components/FounderGraphCampaignCompare.test.jsx`: 7 tests passed。
- 実DB、MCP、Deep Researchとのruntime接続は未検査（本計画のスコープ外）。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | Campaign / Run比較のread-only compositionと7件のfocused testsを追加 | 既存の8章ReportDiffを調査試行単位へ組み込む境界を固定するため | T-FG-25 |
