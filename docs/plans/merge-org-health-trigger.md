# Merge後ORG_HEALTH再配分計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: PR mergeをMERGED報告だけで終えず、同一turnでdependency delivery、`org_health`を内包するMERGED、CEO室のPORTFOLIO_DIRECTIVE、ASSIGNMENTまで完結する。

ゴール: merge後にidle部門とready workが残る状態を検出し、イベント駆動で担当部をactiveまたは明示BLOCKEDへ移す。

成功指標: AGENTS.mdとhandoff正本に必須順序、idempotent merge SHA、ネストpayload項目、#112と#115の回帰checklistが記録される。

## ユーザーストーリーと受け入れ条件

### US-MOH-1

As a 統合部, I want merge後のhandoffを一連のイベントとして完了したい, so that idle部門とready workを残さない。

Given: PRがmergeされmain smokeが成功している
When: 統合部がmerge後handoffを実行する
Then: 必要なDEPENDENCY_READY delivery、`org_health`を内包するMERGED、CEO室のDIRECTIVE、ASSIGNMENT delivery、receiver stateを同一turnで記録する。

### US-MOH-2

As a CEO室, I want 冪等な全社状態を受けたい, so that 同じ状態で重複配分しない。

Given: merge SHA、main SHA、WIP、review queue、依存block、model availabilityが変わらない
When: 統合部がmerge後MERGEDを送る
Then: 同じmerge SHAのMERGEDを二重送信せず、同じstate fingerprintの独立ORG_HEALTHも送信しない。

### US-MOH-3

As a 実装部, I want 指定モデルで配分を受けたい, so that 無断fallbackなしで開始またはBLOCKEDを返せる。

Given: PORTFOLIO_DIRECTIVEがready workを割り当てる
When: 統合部がASSIGNMENTを送る
Then: modelとthinkingをpayloadとturn overrideで一致させ、receiver stateがactiveまたは`reason: model_unavailable`になる。

### US-MOH-4

As a 統合部, I want CEO室の明示的なポートフォリオ判断を受けて配分したい, so that 新規Issue選択とWIP再配分の権限境界を守れる。

Given: `MERGED.org_health`にidle部門とready/unassigned workがある
When: CEO室が再配分不要の場合を含め`PORTFOLIO_DIRECTIVE action=GO_ON|CHANGE|BLOCK`を返す
Then: 統合部はDIRECTIVE後にASSIGNMENTまたはDEPENDENCY_READYを配信し、deliveryとreceiver stateを記録する。

## スコープ外

- 定期ポーリング、Terraへの無断fallback、runtime UI/API、外部サービス接続。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- |
| T-MOH-1 | AGENTS.mdのmerge後順序 | 検査: dependency deliveryからMERGED.org_health、必要時receiver stateまでを確認 | 既知 |
| T-MOH-2 | handoffのpayloadとchecklist | 検査: main SHA、merge source、WIP、queue、block、conflict、candidate、model、released capacity、dependency deliveryを確認 | 既知 |
| T-MOH-3 | #112/#115回帰記録 | 検査: 初期assignment未配信と旧形式独立ORG_HEALTHの二重送信禁止を確認 | 既知 |
| T-MOH-4 | CEO handshake | 検査: idle+ready caseでMERGED、GO_ON|CHANGE|BLOCK、delivery、receiver stateを確認 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| merge後処理 | dependency delivery後に全社状態を内包したMERGEDを1通とする。 | MERGEDだけで終える案はready workをidleに残し、独立ORG_HEALTH往復はメッセージを増やすため却下。 | 採用 |
| 状態送信 | normalized fingerprintで冪等にする。 | 定期ポーリングは重複配分を増やすため却下。 | 採用 |
| モデル障害 | receiverをmodel_unavailable BLOCKEDとして記録する。 | 別モデルへの無断fallbackは役割契約に反するため却下。 | 採用 |
| CEO室返信待ち | CEO室は毎merge SHAへGO_ON、CHANGE、BLOCKのいずれかを必ず返し、統合部はその後に新規配分する。 | 返信なしを承認扱いにするdefault allocationはCEO室のポートフォリオ決定権を損なうため却下。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | #112後の初期assignment未配信を回帰化 | T-MOH-1からT-MOH-3 |
| 2026-08-09 | MERGED内包型へ更新 | #115直後の旧形式独立ORG_HEALTHを回帰例にし、merge起因の往復を1通へ短縮 | T-MOH-1からT-MOH-3 |
| 2026-08-09 | 2-message CEO handshakeへ修正 | default allocation案を撤回し、CEO室の明示DIRECTIVEを必須化 | T-MOH-1、T-MOH-4 |
| 2026-08-09 | CEO actionを3種へ固定 | 継続、変更、停止を短い応答に統一 | T-MOH-4 |
