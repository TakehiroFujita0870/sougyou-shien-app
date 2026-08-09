# Merge後ORG_HEALTH再配分計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: PR mergeをMERGED報告だけで終えず、同一turnでORG_HEALTH、PORTFOLIO_DIRECTIVE、ASSIGNMENTまで完結する。

ゴール: merge後にidle部門とready workが残る状態を検出し、イベント駆動で担当部をactiveまたは明示BLOCKEDへ移す。

成功指標: AGENTS.mdとhandoff正本に必須順序、idempotent fingerprint、payload項目、#112の回帰checklistが記録される。

## ユーザーストーリーと受け入れ条件

### US-MOH-1

As a 統合部, I want merge後のhandoffを一連のイベントとして完了したい, so that idle部門とready workを残さない。

Given: PRがmergeされmain smokeが成功している
When: 統合部がmerge後handoffを実行する
Then: MERGED、必要なDEPENDENCY_READY delivery、ORG_HEALTH、DIRECTIVE translation、ASSIGNMENT delivery、receiver stateを同一turnで記録する。

### US-MOH-2

As a CEO室, I want 冪等な全社状態を受けたい, so that 同じ状態で重複配分しない。

Given: main SHA、WIP、review queue、依存block、model availabilityが変わらない
When: 統合部がORG_HEALTHを再計算する
Then: 同じstate fingerprintは送信せず、新しいmergeまたは配分結果で状態が変わった場合だけ送信する。

### US-MOH-3

As a 実装部, I want 指定モデルで配分を受けたい, so that 無断fallbackなしで開始またはBLOCKEDを返せる。

Given: PORTFOLIO_DIRECTIVEがready workを割り当てる
When: 統合部がASSIGNMENTを送る
Then: modelとthinkingをpayloadとturn overrideで一致させ、receiver stateがactiveまたは`reason: model_unavailable`になる。

## スコープ外

- 定期ポーリング、Terraへの無断fallback、runtime UI/API、外部サービス接続。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- |
| T-MOH-1 | AGENTS.mdのmerge後順序 | 検査: MERGEDからreceiver stateまでの6要素を確認 | 既知 |
| T-MOH-2 | handoffのpayloadとchecklist | 検査: main SHA、merge source、WIP、queue、block、conflict、candidate、model、released capacityを確認 | 既知 |
| T-MOH-3 | #112回帰記録 | 検査: 初期assignment未配信と再発防止checklistを確認 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| merge後処理 | 同一turnの因果連鎖とする。 | MERGEDだけで終える案はready workをidleに残すため却下。 | 採用 |
| 状態送信 | normalized fingerprintで冪等にする。 | 定期ポーリングは重複配分を増やすため却下。 | 採用 |
| モデル障害 | receiverをmodel_unavailable BLOCKEDとして記録する。 | 別モデルへの無断fallbackは役割契約に反するため却下。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | #112後の初期assignment未配信を回帰化 | T-MOH-1からT-MOH-3 |
