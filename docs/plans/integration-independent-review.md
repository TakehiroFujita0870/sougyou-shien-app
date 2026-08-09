# 統合部運用PRの独立レビュー計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 統合・リリース管理部が作る運用文書PRで自己通知、自己レビュー、自己マージの循環を廃止し、独立部門長レビューへ置換する。

ゴール: 統合部の運用PRは作成者以外の部門長が通知SHAと全文diffを承認してからだけmergeされる。

成功指標: AGENTS.mdとhandoff正本にREVIEW_REQUEST/REVIEW_APPROVED、独立reviewer、自己循環禁止、部長本人のLuna/low実装境界が記録される。

## ユーザーストーリーと受け入れ条件

### US-IIR-1

As a 統合部, I want 自部門の運用PRを独立部門長へレビュー依頼したい, so that 作成者が自分の差分を承認しない。

Given: 統合部が運用文書PRを作成し、通知SHA、CI、本文read-backを確認している。
When: 統合部が独立reviewerへREVIEW_REQUESTを送る。
Then: reviewerがREVIEW_APPROVEDまたはREVIEW_CHANGES_REQUESTEDを返すまで、統合部はそのPRをmergeしない。

### US-IIR-2

As a 実装部長, I want Luna/lowで自ら割当作業を実装したい, so that subagent前提の誤ったmodel blockを作らない。

Given: 実装部長へLuna/lowのASSIGNMENTが届く。
When: 部長本人が作業を開始する。
Then: subagentをspawnせず指定profileで実装し、profileが実際に利用不能な場合だけBLOCKED(model_unavailable)を返す。

### US-IIR-3

As a 統合部, I want 置換された部門taskのownerとWIPを正本で移管したい, so that 旧taskへ新規ASSIGNMENTを送らない。

Given: 品質または基盤認証の部長taskがLuna/low実行環境へ置換されている。
When: 統合部が同じIssueを再ASSIGNMENTする。
Then: 新owner taskを含むidempotency keyで送信し、旧taskは移行記録だけとして新規作業を持たない。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | reviewerは部門所有権とWIPを見て統合部が指定する | 統合・リリース管理部 | PR作成時 |

## スコープ外

- runtime UI/API、外部接続、個人情報送信、モデルのfallback実装。
- 実装部の通常PRに対する統合レビューの廃止。
- 統合部運用PRをCEO室が直接レビューする経路。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-IIR-1 | AGENTS.mdの自己循環禁止 | 検査: 独立reviewer、REVIEW_REQUEST、自己通知禁止を確認 | 既知 |
| T-IIR-2 | handoffの独立review payload | 検査: payloadにPR、SHA、reviewer、acceptance、判定がある | 既知 |
| T-IIR-3 | 部長本人のLuna/low実装境界 | 検査: subagentなしとmodel_unavailable条件を確認 | 既知 |
| T-IIR-4 | owner registryとWIP移管 | 検査: 新旧task、WIP、旧taskへの新規送信禁止を確認 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 統合部PRレビュー | 別部門長のREVIEW_APPROVEDをmerge前提にする。 | 統合部が自部門へPR_READYを送り自己レビューする案は独立性がないため却下。 | 採用 |
| 実装主体 | 各部長がLuna/lowで自ら実装する。 | subagent前提でLuna/lowをblockする案は部門モデル契約に反するため却下。 | 採用 |
| task置換 | 正本registryで新ownerとWIPを更新し、旧taskを移行記録に限定する。 | 旧taskと新taskへ同時にASSIGNMENTする案は重複実装を招くため却下。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | モデル役割誤解と統合部自己循環イベントを是正 | T-IIR-1からT-IIR-3 |
| 2026-08-09 | 品質・基盤task移管を追加 | Luna/low利用可能な新部長taskへ#89とT-IA-01を移す | T-IIR-4 |
